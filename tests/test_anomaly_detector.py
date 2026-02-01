"""Tests for anomaly detection engine."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from orcaops.anomaly_detector import AnomalyDetector, AnomalyStore
from orcaops.schemas import (
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
    JobStatus,
    PerformanceBaseline,
    ResourceUsage,
    RunRecord,
    StepResult,
)


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


def _make_record(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        job_id="test-job-1",
        status=JobStatus.SUCCESS,
        created_at=now - timedelta(seconds=20),
        started_at=now - timedelta(seconds=15),
        finished_at=now,
        image_ref="python:3.11",
        steps=[
            StepResult(command="pytest", exit_code=0, stdout="ok", stderr="", duration_seconds=15.0),
        ],
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


# ===================================================================
# AnomalyDetector tests
# ===================================================================


class TestDurationAnomaly:
    def test_no_anomaly_within_threshold(self):
        detector = AnomalyDetector()
        record = _make_record()  # 15s, mean=15, stddev=2 -> z=0
        baseline = _make_baseline()
        anomalies = detector.detect(record, baseline)
        assert len(anomalies) == 0

    def test_warning_z_score_above_2(self):
        detector = AnomalyDetector()
        # duration=20s, mean=15, stddev=2 -> z=2.5 -> WARNING
        now = datetime.now(timezone.utc)
        record = _make_record(
            started_at=now - timedelta(seconds=20),
            finished_at=now,
        )
        baseline = _make_baseline(duration_mean=15.0, duration_stddev=2.0)
        anomalies = detector.detect(record, baseline)
        duration_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.DURATION]
        assert len(duration_anomalies) == 1
        assert duration_anomalies[0].severity == AnomalySeverity.WARNING

    def test_critical_z_score_above_3(self):
        detector = AnomalyDetector()
        # duration=22s, mean=15, stddev=2 -> z=3.5 -> CRITICAL
        now = datetime.now(timezone.utc)
        record = _make_record(
            started_at=now - timedelta(seconds=22),
            finished_at=now,
        )
        baseline = _make_baseline(duration_mean=15.0, duration_stddev=2.0)
        anomalies = detector.detect(record, baseline)
        duration_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.DURATION]
        assert len(duration_anomalies) == 1
        assert duration_anomalies[0].severity == AnomalySeverity.CRITICAL

    def test_skip_non_success(self):
        detector = AnomalyDetector()
        record = _make_record(status=JobStatus.FAILED)
        baseline = _make_baseline()
        anomalies = detector.detect(record, baseline)
        duration_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.DURATION]
        assert len(duration_anomalies) == 0

    def test_skip_zero_stddev(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(duration_stddev=0.0)
        anomalies = detector.detect(record, baseline)
        duration_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.DURATION]
        assert len(duration_anomalies) == 0

    def test_skip_low_sample_count(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(sample_count=2)
        anomalies = detector.detect(record, baseline)
        assert len(anomalies) == 0


class TestMemoryAnomaly:
    def test_no_anomaly_within_threshold(self):
        detector = AnomalyDetector()
        record = _make_record()
        record.resource_usage = ResourceUsage(memory_peak_mb=250.0)
        baseline = _make_baseline(memory_max_mb=200.0)
        anomalies = detector.detect(record, baseline)
        memory_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.MEMORY]
        assert len(memory_anomalies) == 0

    def test_warning_above_1_5x(self):
        detector = AnomalyDetector()
        record = _make_record()
        record.resource_usage = ResourceUsage(memory_peak_mb=350.0)
        baseline = _make_baseline(memory_max_mb=200.0)
        anomalies = detector.detect(record, baseline)
        memory_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.MEMORY]
        assert len(memory_anomalies) == 1
        assert memory_anomalies[0].severity == AnomalySeverity.WARNING

    def test_critical_above_2x(self):
        detector = AnomalyDetector()
        record = _make_record()
        record.resource_usage = ResourceUsage(memory_peak_mb=450.0)
        baseline = _make_baseline(memory_max_mb=200.0)
        anomalies = detector.detect(record, baseline)
        memory_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.MEMORY]
        assert len(memory_anomalies) == 1
        assert memory_anomalies[0].severity == AnomalySeverity.CRITICAL

    def test_skip_no_resource_usage(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(memory_max_mb=200.0)
        anomalies = detector.detect(record, baseline)
        memory_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.MEMORY]
        assert len(memory_anomalies) == 0


class TestFlakyDetection:
    def test_flaky_detected(self):
        detector = AnomalyDetector()
        record = _make_record()
        # success_rate=0.6 with 20 samples -> flaky
        baseline = _make_baseline(
            success_count=12, failure_count=8, success_rate=0.6,
        )
        anomalies = detector.detect(record, baseline)
        flaky = [a for a in anomalies if a.anomaly_type == AnomalyType.FLAKY]
        assert len(flaky) == 1
        assert flaky[0].severity == AnomalySeverity.WARNING

    def test_not_flaky_high_success(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(
            success_count=18, failure_count=2, success_rate=0.9,
        )
        anomalies = detector.detect(record, baseline)
        flaky = [a for a in anomalies if a.anomaly_type == AnomalyType.FLAKY]
        assert len(flaky) == 0

    def test_not_flaky_low_samples(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(
            success_count=3, failure_count=3, success_rate=0.5,
        )
        anomalies = detector.detect(record, baseline)
        flaky = [a for a in anomalies if a.anomaly_type == AnomalyType.FLAKY]
        assert len(flaky) == 0


class TestSuccessRateDegradation:
    def test_degradation_detected(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(
            success_count=3, failure_count=4, success_rate=0.43,
        )
        anomalies = detector.detect(record, baseline)
        deg = [a for a in anomalies if a.anomaly_type == AnomalyType.SUCCESS_RATE_DEGRADATION]
        assert len(deg) == 1
        assert deg[0].severity == AnomalySeverity.CRITICAL

    def test_no_degradation_above_threshold(self):
        detector = AnomalyDetector()
        record = _make_record()
        baseline = _make_baseline(
            success_count=9, failure_count=1, success_rate=0.9,
        )
        anomalies = detector.detect(record, baseline)
        deg = [a for a in anomalies if a.anomaly_type == AnomalyType.SUCCESS_RATE_DEGRADATION]
        assert len(deg) == 0


class TestZScore:
    def test_z_score_calculation(self):
        assert AnomalyDetector._z_score(20, 15, 2) == 2.5

    def test_z_score_zero_stddev(self):
        assert AnomalyDetector._z_score(20, 15, 0) == 0.0


# ===================================================================
# AnomalyStore tests
# ===================================================================


class TestAnomalyStore:
    def _make_anomaly_record(self, anomaly_id="anom_test1", job_id="job-1"):
        return AnomalyRecord(
            anomaly_id=anomaly_id,
            job_id=job_id,
            baseline_key="python:3.11::pytest",
            anomaly_type=AnomalyType.DURATION,
            severity=AnomalySeverity.WARNING,
            title="Test anomaly",
            description="Duration is too long",
            expected="15.0s",
            actual="25.0s",
            z_score=2.5,
            deviation_percent=66.7,
        )

    def test_store_and_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            rec = self._make_anomaly_record()
            store.store(rec)
            results, total = store.query()
            assert total == 1
            assert results[0].anomaly_id == "anom_test1"

    def test_query_by_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            store.store(self._make_anomaly_record("a1"))
            store.store(AnomalyRecord(
                anomaly_id="a2",
                job_id="job-2",
                baseline_key="python:3.11::pytest",
                anomaly_type=AnomalyType.MEMORY,
                severity=AnomalySeverity.CRITICAL,
                title="Memory anomaly",
                description="Too much memory",
                expected="200MB",
                actual="450MB",
            ))
            results, total = store.query(anomaly_type=AnomalyType.DURATION)
            assert total == 1
            assert results[0].anomaly_id == "a1"

    def test_query_by_severity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            store.store(self._make_anomaly_record("a1"))
            store.store(AnomalyRecord(
                anomaly_id="a2",
                job_id="job-2",
                baseline_key="key",
                anomaly_type=AnomalyType.MEMORY,
                severity=AnomalySeverity.CRITICAL,
                title="Memory",
                description="desc",
                expected="200MB",
                actual="450MB",
            ))
            results, total = store.query(severity=AnomalySeverity.CRITICAL)
            assert total == 1
            assert results[0].anomaly_id == "a2"

    def test_query_by_job_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            store.store(self._make_anomaly_record("a1", job_id="job-1"))
            store.store(self._make_anomaly_record("a2", job_id="job-2"))
            results, total = store.query(job_id="job-1")
            assert total == 1
            assert results[0].job_id == "job-1"

    def test_acknowledge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            store.store(self._make_anomaly_record("a1"))
            assert store.acknowledge("a1") is True
            results, _ = store.query()
            assert results[0].acknowledged is True

    def test_acknowledge_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            assert store.acknowledge("nonexistent") is False

    def test_query_pagination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            for i in range(5):
                store.store(self._make_anomaly_record(f"a{i}"))
            results, total = store.query(limit=2)
            assert total == 5
            assert len(results) == 2

    def test_query_acknowledged_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            store.store(self._make_anomaly_record("a1"))
            store.store(self._make_anomaly_record("a2"))
            store.acknowledge("a1")
            results, total = store.query(acknowledged=False)
            assert total == 1
            assert results[0].anomaly_id == "a2"

    def test_empty_store_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AnomalyStore(anomalies_dir=tmpdir)
            results, total = store.query()
            assert total == 0
            assert results == []
