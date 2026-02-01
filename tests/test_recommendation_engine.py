"""Tests for the recommendation engine."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from orcaops.recommendation_engine import RecommendationEngine, RecommendationStore
from orcaops.schemas import (
    JobStatus,
    PerformanceBaseline,
    Recommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
    RunRecord,
    StepResult,
)


def _make_record(image="python:3.11", commands=None, **overrides):
    now = datetime.now(timezone.utc)
    steps = []
    if commands:
        for cmd in commands:
            steps.append(StepResult(command=cmd, exit_code=0, stdout="", stderr="", duration_seconds=5.0))
    defaults = dict(
        job_id="test-job",
        status=JobStatus.SUCCESS,
        created_at=now,
        started_at=now,
        finished_at=now + timedelta(seconds=15),
        image_ref=image,
        steps=steps,
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


def _make_baseline(**overrides):
    defaults = dict(
        key="python:3.11::pytest",
        sample_count=10,
        duration_ema=15.0,
        duration_mean=15.0,
        duration_stddev=2.0,
        duration_p50=14.5,
        duration_p95=18.0,
        duration_p99=20.0,
        duration_min=10.0,
        duration_max=22.0,
        memory_mean_mb=128.0,
        memory_max_mb=200.0,
        success_count=9,
        failure_count=1,
        success_rate=0.9,
        last_duration=15.0,
    )
    defaults.update(overrides)
    return PerformanceBaseline(**defaults)


def _mock_engine(records=None, baselines=None):
    rs = MagicMock()
    rs.list_runs.return_value = (records or [], len(records or []))
    bt = MagicMock()
    bt.list_baselines.return_value = baselines or []
    return RecommendationEngine(rs, bt)


# ===================================================================
# Image optimization
# ===================================================================


class TestImageOptimization:
    def test_detects_bloated_python_image(self):
        engine = _mock_engine(records=[_make_record(image="python:3.11")])
        recs = engine.generate_recommendations()
        image_recs = [r for r in recs if r.rec_type == RecommendationType.COST and "slim" in r.action]
        assert len(image_recs) == 1

    def test_detects_bloated_node_image(self):
        engine = _mock_engine(records=[_make_record(image="node:20")])
        recs = engine.generate_recommendations()
        image_recs = [r for r in recs if "slim" in r.action or "alpine" in r.action]
        assert len(image_recs) == 1

    def test_ignores_slim_variant(self):
        engine = _mock_engine(records=[_make_record(image="python:3.11-slim")])
        recs = engine.generate_recommendations()
        image_recs = [r for r in recs if "slim" in r.action]
        assert len(image_recs) == 0

    def test_no_duplicate_for_same_image(self):
        engine = _mock_engine(records=[
            _make_record(image="python:3.11", job_id="j1"),
            _make_record(image="python:3.11", job_id="j2"),
        ])
        recs = engine.generate_recommendations()
        image_recs = [r for r in recs if "slim" in r.action]
        assert len(image_recs) == 1


# ===================================================================
# Timeout optimization
# ===================================================================


class TestTimeoutOptimization:
    def test_suggests_lower_timeout(self):
        bl = _make_baseline(sample_count=10, duration_p99=20.0)
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        timeout_recs = [r for r in recs if "timeout" in r.title.lower()]
        assert len(timeout_recs) == 1
        assert timeout_recs[0].rec_type == RecommendationType.PERFORMANCE

    def test_no_suggestion_when_p99_near_default(self):
        bl = _make_baseline(sample_count=10, duration_p99=2000.0)
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        timeout_recs = [r for r in recs if "timeout" in r.title.lower()]
        assert len(timeout_recs) == 0

    def test_no_suggestion_low_samples(self):
        bl = _make_baseline(sample_count=3, duration_p99=10.0)
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        timeout_recs = [r for r in recs if "timeout" in r.title.lower()]
        assert len(timeout_recs) == 0


# ===================================================================
# Caching opportunities
# ===================================================================


class TestCachingOpportunities:
    def test_detects_pip_install(self):
        records = [
            _make_record(commands=["pip install -r requirements.txt"], job_id=f"j{i}")
            for i in range(3)
        ]
        engine = _mock_engine(records=records)
        recs = engine.generate_recommendations()
        cache_recs = [r for r in recs if "cache" in r.title.lower()]
        assert len(cache_recs) == 1

    def test_detects_npm_install(self):
        records = [
            _make_record(commands=["npm install"], job_id=f"j{i}")
            for i in range(4)
        ]
        engine = _mock_engine(records=records)
        recs = engine.generate_recommendations()
        cache_recs = [r for r in recs if "cache" in r.title.lower()]
        assert len(cache_recs) == 1

    def test_no_cache_rec_below_threshold(self):
        records = [
            _make_record(commands=["pip install foo"], job_id=f"j{i}")
            for i in range(2)
        ]
        engine = _mock_engine(records=records)
        recs = engine.generate_recommendations()
        cache_recs = [r for r in recs if "cache" in r.title.lower()]
        assert len(cache_recs) == 0


# ===================================================================
# Reliability
# ===================================================================


class TestReliability:
    def test_low_success_rate_flagged(self):
        bl = _make_baseline(
            success_count=7, failure_count=5, success_rate=0.58, sample_count=12,
        )
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        rel_recs = [r for r in recs if r.rec_type == RecommendationType.RELIABILITY]
        assert len(rel_recs) == 1

    def test_high_success_rate_not_flagged(self):
        bl = _make_baseline(
            success_count=19, failure_count=1, success_rate=0.95, sample_count=20,
        )
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        rel_recs = [r for r in recs if r.rec_type == RecommendationType.RELIABILITY]
        assert len(rel_recs) == 0


# ===================================================================
# Resource right-sizing
# ===================================================================


class TestResourceRightSizing:
    def test_low_memory_flagged(self):
        bl = _make_baseline(memory_max_mb=30.0, sample_count=10)
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        mem_recs = [r for r in recs if "memory" in r.title.lower()]
        assert len(mem_recs) == 1

    def test_normal_memory_not_flagged(self):
        bl = _make_baseline(memory_max_mb=200.0, sample_count=10)
        engine = _mock_engine(baselines=[bl])
        recs = engine.generate_recommendations()
        mem_recs = [r for r in recs if "memory" in r.title.lower()]
        assert len(mem_recs) == 0


# ===================================================================
# RecommendationStore
# ===================================================================


class TestRecommendationStore:
    def _make_rec(self, rec_id="rec_test1", rec_type=RecommendationType.PERFORMANCE):
        return Recommendation(
            recommendation_id=rec_id,
            rec_type=rec_type,
            priority=RecommendationPriority.MEDIUM,
            title="Test recommendation",
            description="Test description",
            impact="Test impact",
            action="Test action",
        )

    def test_save_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            rec = self._make_rec()
            store.save(rec)
            recs = store.list_recommendations()
            assert len(recs) == 1
            assert recs[0].recommendation_id == "rec_test1"

    def test_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            store.save(self._make_rec())
            rec = store.get("rec_test1")
            assert rec is not None
            assert rec.recommendation_id == "rec_test1"

    def test_get_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            assert store.get("nonexistent") is None

    def test_dismiss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            store.save(self._make_rec())
            assert store.dismiss("rec_test1") is True
            rec = store.get("rec_test1")
            assert rec.status == RecommendationStatus.DISMISSED

    def test_mark_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            store.save(self._make_rec())
            assert store.mark_applied("rec_test1") is True
            rec = store.get("rec_test1")
            assert rec.status == RecommendationStatus.APPLIED

    def test_dismiss_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            assert store.dismiss("nonexistent") is False

    def test_filter_by_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            store.save(self._make_rec("r1", RecommendationType.PERFORMANCE))
            store.save(self._make_rec("r2", RecommendationType.COST))
            recs = store.list_recommendations(rec_type=RecommendationType.PERFORMANCE)
            assert len(recs) == 1
            assert recs[0].recommendation_id == "r1"

    def test_filter_by_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RecommendationStore(recommendations_dir=tmpdir)
            store.save(self._make_rec("r1"))
            store.save(self._make_rec("r2"))
            store.dismiss("r1")
            recs = store.list_recommendations(status=RecommendationStatus.ACTIVE)
            assert len(recs) == 1
            assert recs[0].recommendation_id == "r2"
