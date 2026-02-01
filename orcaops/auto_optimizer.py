"""
Auto-optimization engine for OrcaOps.

Analyzes baselines to suggest timeout and memory optimizations.
"""

from typing import List, Optional

from orcaops.metrics import BaselineTracker
from orcaops.schemas import (
    JobSpec,
    OptimizationSuggestion,
    PerformanceBaseline,
)

MIN_SAMPLES = 10


class AutoOptimizer:
    """Generates optimization suggestions from baselines."""

    def __init__(self, baseline_tracker: BaselineTracker):
        self.baseline_tracker = baseline_tracker

    def suggest_optimizations(self, spec: JobSpec) -> List[OptimizationSuggestion]:
        baseline = self.baseline_tracker.get_baseline_for_spec(spec)
        if baseline is None or baseline.sample_count < MIN_SAMPLES:
            return []

        suggestions: List[OptimizationSuggestion] = []

        timeout_sug = self._optimize_timeout(spec, baseline)
        if timeout_sug:
            suggestions.append(timeout_sug)

        memory_sug = self._suggest_memory(baseline)
        if memory_sug:
            suggestions.append(memory_sug)

        return suggestions

    def _optimize_timeout(
        self, spec: JobSpec, baseline: PerformanceBaseline,
    ) -> Optional[OptimizationSuggestion]:
        if baseline.duration_p99 <= 0:
            return None

        suggested = round(baseline.duration_p99 * 1.5)
        current = spec.ttl_seconds

        # Only suggest if significantly lower than current
        if suggested >= current * 0.5:
            return None

        confidence = min(baseline.sample_count / 50.0, 0.95)

        return OptimizationSuggestion(
            suggestion_type="timeout",
            current_value=f"{current}s",
            suggested_value=f"{suggested}s",
            reason=(
                f"p99 duration is {baseline.duration_p99:.1f}s. "
                f"Suggested timeout of {suggested}s (1.5x p99) is well below current {current}s."
            ),
            confidence=round(confidence, 3),
            baseline_key=baseline.key,
        )

    def _suggest_memory(
        self, baseline: PerformanceBaseline, current_limit_mb: float = 0,
    ) -> Optional[OptimizationSuggestion]:
        if baseline.memory_max_mb <= 0:
            return None

        # Suggest a memory limit based on observed max + 50% headroom
        suggested_mb = round(baseline.memory_max_mb * 1.5)

        if current_limit_mb > 0 and suggested_mb >= current_limit_mb * 0.8:
            return None

        confidence = min(baseline.sample_count / 50.0, 0.95)

        return OptimizationSuggestion(
            suggestion_type="memory",
            current_value=f"{current_limit_mb:.0f}MB" if current_limit_mb > 0 else "unlimited",
            suggested_value=f"{suggested_mb}MB",
            reason=(
                f"Peak memory is {baseline.memory_max_mb:.0f}MB. "
                f"Setting limit to {suggested_mb}MB (1.5x peak) provides headroom."
            ),
            confidence=round(confidence, 3),
            baseline_key=baseline.key,
        )
