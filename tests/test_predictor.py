"""Tests for the predictor module (duration + failure risk)."""

from unittest.mock import MagicMock

import pytest

from orcaops.predictor import DurationPredictor, FailurePredictor
from orcaops.schemas import (
    DurationPrediction,
    FailureRiskAssessment,
    JobCommand,
    JobSpec,
    PerformanceBaseline,
    SandboxSpec,
)


def _make_spec(image="python:3.11", commands=None):
    cmds = commands or ["pytest"]
    return JobSpec(
        job_id="pred-test",
        sandbox=SandboxSpec(image=image),
        commands=[JobCommand(command=c) for c in cmds],
    )


def _make_baseline(**overrides):
    defaults = dict(
        key="python:3.11::pytest",
        sample_count=20,
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
        success_count=18,
        failure_count=2,
        success_rate=0.9,
        last_duration=15.0,
    )
    defaults.update(overrides)
    return PerformanceBaseline(**defaults)


# ===================================================================
# DurationPredictor
# ===================================================================


class TestDurationPredictor:
    def test_predict_with_baseline(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline()
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert isinstance(result, DurationPrediction)
        assert result.estimated_seconds == 14.5  # p50
        assert result.sample_count == 20
        assert result.baseline_key == "python:3.11::pytest"

    def test_predict_no_baseline(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = None
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.estimated_seconds == 300.0
        assert result.confidence == 0.05
        assert result.sample_count == 0

    def test_confidence_scales_with_samples(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(sample_count=50)
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.confidence == 0.95

    def test_confidence_capped_at_095(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(sample_count=100)
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.confidence == 0.95

    def test_confidence_proportional(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(sample_count=10)
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.confidence == 0.2

    def test_range_includes_estimate(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline()
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.range_low <= result.estimated_seconds <= result.range_high

    def test_range_uses_p50_and_p95(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            duration_p50=10.0, duration_p95=25.0,
        )
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.range_low == 8.0  # p50 * 0.8
        assert result.range_high == 25.0  # p95

    def test_fallback_when_p50_zero(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            duration_p50=0.0, duration_p95=0.0, duration_ema=20.0,
        )
        dp = DurationPredictor(bt)
        result = dp.predict(_make_spec())
        assert result.estimated_seconds == 20.0  # falls back to EMA


# ===================================================================
# FailurePredictor
# ===================================================================


class TestFailurePredictor:
    def test_low_risk(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(success_rate=0.95)
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert result.risk_level == "low"
        assert result.risk_score == 0.05

    def test_medium_risk(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            success_rate=0.7, success_count=7, failure_count=3,
        )
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert result.risk_level == "medium"

    def test_high_risk(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            success_rate=0.4, success_count=4, failure_count=6,
        )
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert result.risk_level == "high"

    def test_no_baseline(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = None
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert result.risk_level == "low"
        assert result.risk_score == 0.1
        assert result.sample_count == 0

    def test_factors_include_low_success_rate(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            success_rate=0.6, success_count=6, failure_count=4,
        )
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert any("success rate" in f.lower() for f in result.factors)

    def test_historical_success_rate_included(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(success_rate=0.85)
        fp = FailurePredictor(bt)
        result = fp.assess_risk(_make_spec())
        assert result.historical_success_rate == 0.85
