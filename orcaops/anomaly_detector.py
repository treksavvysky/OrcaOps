"""
Anomaly detection engine using z-score based statistical analysis.

Detects: duration anomalies, memory anomalies, flaky job patterns,
and success rate degradation.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from orcaops.schemas import (
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
    JobStatus,
    PerformanceBaseline,
    RunRecord,
)


class AnomalyDetector:
    """Detects anomalies by comparing job results against baselines."""

    def detect(
        self, record: RunRecord, baseline: PerformanceBaseline
    ) -> List[AnomalyRecord]:
        """Detect all anomalies for a completed job run.

        Requires baseline.sample_count >= 3 for z-score based checks.
        """
        anomalies: List[AnomalyRecord] = []

        if baseline.sample_count < 3:
            return anomalies

        duration_anomaly = self._check_duration(record, baseline)
        if duration_anomaly:
            anomalies.append(duration_anomaly)

        memory_anomaly = self._check_memory(record, baseline)
        if memory_anomaly:
            anomalies.append(memory_anomaly)

        flaky_anomaly = self._check_flaky(record, baseline)
        if flaky_anomaly:
            anomalies.append(flaky_anomaly)

        degradation = self._check_success_rate_degradation(record, baseline)
        if degradation:
            anomalies.append(degradation)

        return anomalies

    def _check_duration(
        self, record: RunRecord, baseline: PerformanceBaseline
    ) -> Optional[AnomalyRecord]:
        """Z-score duration check. |z| > 2 = WARNING, |z| > 3 = CRITICAL."""
        if record.status != JobStatus.SUCCESS:
            return None
        if not record.started_at or not record.finished_at:
            return None
        if baseline.duration_stddev <= 0:
            return None

        duration = (record.finished_at - record.started_at).total_seconds()
        z = self._z_score(duration, baseline.duration_mean, baseline.duration_stddev)

        if abs(z) <= 2:
            return None

        severity = AnomalySeverity.CRITICAL if abs(z) > 3 else AnomalySeverity.WARNING
        deviation_pct = ((duration - baseline.duration_mean) / baseline.duration_mean) * 100

        return AnomalyRecord(
            anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
            job_id=record.job_id,
            baseline_key=baseline.key,
            anomaly_type=AnomalyType.DURATION,
            severity=severity,
            title="Duration anomaly detected",
            description=(
                f"Duration {duration:.1f}s deviates from baseline "
                f"(mean={baseline.duration_mean:.1f}s, z-score={z:.1f})"
            ),
            expected=f"{baseline.duration_mean:.1f}s",
            actual=f"{duration:.1f}s",
            z_score=round(z, 2),
            deviation_percent=round(deviation_pct, 1),
        )

    def _check_memory(
        self, record: RunRecord, baseline: PerformanceBaseline
    ) -> Optional[AnomalyRecord]:
        """Memory peak > max*1.5 = WARNING, > max*2.0 = CRITICAL."""
        if not record.resource_usage or record.resource_usage.memory_peak_mb <= 0:
            return None
        if baseline.memory_max_mb <= 0:
            return None

        peak = record.resource_usage.memory_peak_mb
        ratio = peak / baseline.memory_max_mb

        if ratio <= 1.5:
            return None

        severity = AnomalySeverity.CRITICAL if ratio > 2.0 else AnomalySeverity.WARNING

        return AnomalyRecord(
            anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
            job_id=record.job_id,
            baseline_key=baseline.key,
            anomaly_type=AnomalyType.MEMORY,
            severity=severity,
            title="Memory usage anomaly",
            description=(
                f"Memory peak {peak:.0f}MB is {ratio:.1f}x the baseline max ({baseline.memory_max_mb:.0f}MB)"
            ),
            expected=f"{baseline.memory_max_mb:.0f}MB",
            actual=f"{peak:.0f}MB",
            deviation_percent=round((ratio - 1) * 100, 1),
        )

    def _check_flaky(
        self, record: RunRecord, baseline: PerformanceBaseline
    ) -> Optional[AnomalyRecord]:
        """Detect flaky jobs: success_rate between 0.3 and 0.9 with 10+ samples."""
        total = baseline.success_count + baseline.failure_count
        if total < 10:
            return None
        if baseline.success_rate >= 0.9 or baseline.success_rate < 0.3:
            return None

        return AnomalyRecord(
            anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
            job_id=record.job_id,
            baseline_key=baseline.key,
            anomaly_type=AnomalyType.FLAKY,
            severity=AnomalySeverity.WARNING,
            title="Flaky job pattern detected",
            description=(
                f"Job has a {baseline.success_rate * 100:.0f}% success rate "
                f"over {total} runs, indicating intermittent failures"
            ),
            expected=">=90% success rate",
            actual=f"{baseline.success_rate * 100:.0f}%",
        )

    def _check_success_rate_degradation(
        self, record: RunRecord, baseline: PerformanceBaseline
    ) -> Optional[AnomalyRecord]:
        """Success rate dropping below 0.8 with 5+ samples."""
        total = baseline.success_count + baseline.failure_count
        if total < 5:
            return None
        if baseline.success_rate >= 0.8:
            return None

        return AnomalyRecord(
            anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
            job_id=record.job_id,
            baseline_key=baseline.key,
            anomaly_type=AnomalyType.SUCCESS_RATE_DEGRADATION,
            severity=AnomalySeverity.CRITICAL,
            title="Success rate degradation",
            description=(
                f"Success rate has dropped to {baseline.success_rate * 100:.0f}% "
                f"over {total} runs"
            ),
            expected=">=80% success rate",
            actual=f"{baseline.success_rate * 100:.0f}%",
        )

    @staticmethod
    def _z_score(value: float, mean: float, stddev: float) -> float:
        """Calculate z-score. Returns 0.0 if stddev is 0."""
        if stddev <= 0:
            return 0.0
        return (value - mean) / stddev


class AnomalyStore:
    """JSONL-based anomaly persistence and query layer."""

    def __init__(self, anomalies_dir: Optional[str] = None):
        self.anomalies_dir = anomalies_dir or os.path.expanduser(
            "~/.orcaops/anomalies"
        )
        self._lock = threading.Lock()

    def store(self, anomaly: AnomalyRecord) -> None:
        """Append anomaly to date-based JSONL file."""
        with self._lock:
            os.makedirs(self.anomalies_dir, exist_ok=True)
            date_str = anomaly.detected_at.strftime("%Y-%m-%d")
            path = os.path.join(self.anomalies_dir, f"{date_str}.jsonl")
            with open(path, "a") as f:
                f.write(anomaly.model_dump_json() + "\n")

    def query(
        self,
        anomaly_type: Optional[AnomalyType] = None,
        severity: Optional[AnomalySeverity] = None,
        job_id: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AnomalyRecord], int]:
        """Query anomalies with filters."""
        all_records = self._scan_all()

        if anomaly_type:
            all_records = [r for r in all_records if r.anomaly_type == anomaly_type]
        if severity:
            all_records = [r for r in all_records if r.severity == severity]
        if job_id:
            all_records = [r for r in all_records if r.job_id == job_id]
        if acknowledged is not None:
            all_records = [r for r in all_records if r.acknowledged == acknowledged]

        # Sort by detected_at descending
        all_records.sort(key=lambda r: r.detected_at, reverse=True)
        total = len(all_records)
        return all_records[offset : offset + limit], total

    def acknowledge(self, anomaly_id: str) -> bool:
        """Mark an anomaly as acknowledged by rewriting its JSONL file."""
        with self._lock:
            if not os.path.isdir(self.anomalies_dir):
                return False

            for fname in os.listdir(self.anomalies_dir):
                if not fname.endswith(".jsonl"):
                    continue
                fpath = os.path.join(self.anomalies_dir, fname)
                lines = []
                found = False
                with open(fpath, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = AnomalyRecord.model_validate_json(line)
                            if record.anomaly_id == anomaly_id:
                                record.acknowledged = True
                                found = True
                            lines.append(record.model_dump_json())
                        except Exception:
                            lines.append(line)

                if found:
                    with open(fpath, "w") as f:
                        for ln in lines:
                            f.write(ln + "\n")
                    return True

            return False

    def _scan_all(self) -> List[AnomalyRecord]:
        """Scan all JSONL files for anomalies."""
        records: List[AnomalyRecord] = []
        if not os.path.isdir(self.anomalies_dir):
            return records

        for fname in sorted(os.listdir(self.anomalies_dir), reverse=True):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(self.anomalies_dir, fname)
            try:
                with open(fpath, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            records.append(AnomalyRecord.model_validate_json(line))
                        except Exception:
                            continue
            except OSError:
                continue

        return records
