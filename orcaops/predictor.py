"""
Predictive capabilities for OrcaOps.

Provides duration prediction and failure risk assessment
based on historical job performance baselines.
"""

from typing import Optional

from orcaops.metrics import BaselineTracker
from orcaops.schemas import (
    DurationPrediction,
    FailureRiskAssessment,
    JobSpec,
    PerformanceBaseline,
)


class DurationPredictor:
    """Predicts job duration using historical baselines."""

    def __init__(self, baseline_tracker: BaselineTracker):
        self.baseline_tracker = baseline_tracker

    def predict(self, spec: JobSpec) -> DurationPrediction:
        baseline = self.baseline_tracker.get_baseline_for_spec(spec)
        if baseline is None or baseline.sample_count < 1:
            return DurationPrediction(
                estimated_seconds=300.0,
                confidence=0.05,
                range_low=60.0,
                range_high=3600.0,
                sample_count=0,
                baseline_key=None,
            )

        confidence = min(baseline.sample_count / 50.0, 0.95)

        estimated = baseline.duration_ema
        if baseline.duration_p50 > 0:
            estimated = baseline.duration_p50

        range_low = baseline.duration_p50 * 0.8 if baseline.duration_p50 > 0 else estimated * 0.5
        range_high = baseline.duration_p95 if baseline.duration_p95 > 0 else estimated * 2.0

        # Ensure range_low <= estimated <= range_high
        range_low = min(range_low, estimated)
        range_high = max(range_high, estimated)

        return DurationPrediction(
            estimated_seconds=round(estimated, 2),
            confidence=round(confidence, 3),
            range_low=round(range_low, 2),
            range_high=round(range_high, 2),
            sample_count=baseline.sample_count,
            baseline_key=baseline.key,
        )


class FailurePredictor:
    """Assesses failure risk using historical baselines."""

    def __init__(self, baseline_tracker: BaselineTracker):
        self.baseline_tracker = baseline_tracker

    def assess_risk(self, spec: JobSpec) -> FailureRiskAssessment:
        baseline = self.baseline_tracker.get_baseline_for_spec(spec)
        if baseline is None or baseline.sample_count < 1:
            return FailureRiskAssessment(
                risk_score=0.1,
                risk_level="low",
                factors=["No historical data available — assuming low risk."],
                sample_count=0,
                baseline_key=None,
            )

        risk_score = round(1.0 - baseline.success_rate, 3)
        factors = []

        total = baseline.success_count + baseline.failure_count
        if baseline.success_rate < 0.8:
            factors.append(
                f"Low success rate: {baseline.success_rate * 100:.0f}% over {total} runs."
            )
        if baseline.failure_count > 0:
            factors.append(f"{baseline.failure_count} historical failures out of {total} runs.")
        if not factors:
            factors.append("Historical data indicates stable execution.")

        if risk_score < 0.2:
            risk_level = "low"
        elif risk_score < 0.5:
            risk_level = "medium"
        else:
            risk_level = "high"

        return FailureRiskAssessment(
            risk_score=risk_score,
            risk_level=risk_level,
            factors=factors,
            historical_success_rate=baseline.success_rate,
            sample_count=baseline.sample_count,
            baseline_key=baseline.key,
        )
