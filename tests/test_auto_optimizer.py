"""Tests for the auto-optimization engine."""

from unittest.mock import MagicMock

import pytest

from orcaops.auto_optimizer import AutoOptimizer
from orcaops.schemas import (
    JobCommand,
    JobSpec,
    OptimizationSuggestion,
    PerformanceBaseline,
    SandboxSpec,
)


def _make_spec(timeout=3600):
    return JobSpec(
        job_id="opt-test",
        sandbox=SandboxSpec(image="python:3.11"),
        commands=[JobCommand(command="pytest")],
        ttl_seconds=timeout,
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


class TestTimeoutSuggestion:
    def test_suggests_lower_timeout(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(duration_p99=20.0)
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec(timeout=3600))
        timeout_sugs = [s for s in suggestions if s.suggestion_type == "timeout"]
        assert len(timeout_sugs) == 1
        assert timeout_sugs[0].suggested_value == "30s"  # 20 * 1.5

    def test_no_suggestion_when_close(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(duration_p99=2000.0)
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec(timeout=3600))
        timeout_sugs = [s for s in suggestions if s.suggestion_type == "timeout"]
        assert len(timeout_sugs) == 0

    def test_no_suggestion_low_samples(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(sample_count=5)
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec())
        assert len(suggestions) == 0

    def test_no_suggestion_no_baseline(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = None
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec())
        assert len(suggestions) == 0


class TestMemorySuggestion:
    def test_suggests_memory_limit(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(memory_max_mb=200.0)
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec())
        mem_sugs = [s for s in suggestions if s.suggestion_type == "memory"]
        assert len(mem_sugs) == 1
        assert mem_sugs[0].suggested_value == "300MB"  # 200 * 1.5

    def test_no_memory_suggestion_zero(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(memory_max_mb=0.0)
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec())
        mem_sugs = [s for s in suggestions if s.suggestion_type == "memory"]
        assert len(mem_sugs) == 0

    def test_confidence_scales(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            sample_count=50, memory_max_mb=200.0, duration_p99=20.0,
        )
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec())
        for s in suggestions:
            assert s.confidence == 0.95

    def test_both_suggestions(self):
        bt = MagicMock()
        bt.get_baseline_for_spec.return_value = _make_baseline(
            duration_p99=20.0, memory_max_mb=200.0,
        )
        ao = AutoOptimizer(bt)
        suggestions = ao.suggest_optimizations(_make_spec(timeout=3600))
        types = {s.suggestion_type for s in suggestions}
        assert "timeout" in types
        assert "memory" in types
