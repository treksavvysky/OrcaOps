"""
Metrics aggregation and baseline tracking.

Metrics are computed on-the-fly from RunStore (no separate storage).
Baselines use exponential moving average and persist to ~/.orcaops/baselines.json.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from orcaops.schemas import (
    Anomaly,
    AnomalySeverity,
    AnomalyType,
    JobStatus,
    RunRecord,
)
from orcaops.run_store import RunStore


class MetricsAggregator:
    """Computes aggregate metrics from run records on-the-fly."""

    def __init__(self, run_store: RunStore):
        self.run_store = run_store

    def compute_metrics(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Compute aggregate metrics across all runs in the date range."""
        all_records, _ = self.run_store.list_runs(limit=10000)

        if from_date:
            all_records = [r for r in all_records if r.created_at >= from_date]
        if to_date:
            all_records = [r for r in all_records if r.created_at <= to_date]

        total = len(all_records)
        if total == 0:
            return self._empty_metrics(from_date, to_date)

        status_counts: Dict[str, int] = defaultdict(int)
        durations: List[float] = []
        by_image: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "failed": 0, "durations": []}
        )

        for r in all_records:
            status_counts[r.status.value] += 1

            dur = 0.0
            if r.started_at and r.finished_at:
                dur = (r.finished_at - r.started_at).total_seconds()
                durations.append(dur)

            image = r.image_ref or "unknown"
            by_image[image]["count"] += 1
            if r.status == JobStatus.SUCCESS:
                by_image[image]["success"] += 1
            elif r.status == JobStatus.FAILED:
                by_image[image]["failed"] += 1
            if dur > 0:
                by_image[image]["durations"].append(dur)

        avg_duration = sum(durations) / len(durations) if durations else 0.0

        by_image_clean: Dict[str, Dict[str, Any]] = {}
        for img, data in by_image.items():
            durs = data.pop("durations")
            data["avg_duration_seconds"] = round(sum(durs) / len(durs), 2) if durs else 0.0
            by_image_clean[img] = data

        return {
            "total_runs": total,
            "success_count": status_counts.get("success", 0),
            "failed_count": status_counts.get("failed", 0),
            "timed_out_count": status_counts.get("timed_out", 0),
            "cancelled_count": status_counts.get("cancelled", 0),
            "success_rate": round(status_counts.get("success", 0) / total, 3),
            "avg_duration_seconds": round(avg_duration, 2),
            "total_duration_seconds": round(sum(durations), 2),
            "by_image": by_image_clean,
            "period_start": from_date or min(
                (r.created_at for r in all_records), default=None
            ),
            "period_end": to_date or max(
                (r.created_at for r in all_records), default=None
            ),
        }

    def _empty_metrics(self, from_date, to_date):
        return {
            "total_runs": 0,
            "success_count": 0,
            "failed_count": 0,
            "timed_out_count": 0,
            "cancelled_count": 0,
            "success_rate": 0.0,
            "avg_duration_seconds": 0.0,
            "total_duration_seconds": 0.0,
            "by_image": {},
            "period_start": from_date,
            "period_end": to_date,
        }


class BaselineTracker:
    """Tracks job duration baselines using exponential moving average."""

    def __init__(self, baselines_path: Optional[str] = None, alpha: float = 0.2):
        self.baselines_path = baselines_path or os.path.expanduser(
            "~/.orcaops/baselines.json"
        )
        self.alpha = alpha
        self._baselines: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self.baselines_path):
            try:
                with open(self.baselines_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.baselines_path), exist_ok=True)
        with open(self.baselines_path, "w") as f:
            json.dump(self._baselines, f, indent=2, default=str)

    def _key(self, record: RunRecord) -> str:
        """Generate a baseline key from image + command fingerprint."""
        image = record.image_ref or "unknown"
        cmds = "|".join(s.command for s in record.steps)
        return f"{image}::{cmds}"

    def update(self, record: RunRecord) -> Optional[Anomaly]:
        """Update baseline with a successful run. Returns anomaly if detected."""
        if record.status != JobStatus.SUCCESS:
            return None
        if not record.started_at or not record.finished_at:
            return None

        duration = (record.finished_at - record.started_at).total_seconds()
        key = self._key(record)

        anomaly = None
        if key in self._baselines:
            baseline = self._baselines[key]
            ema = baseline["ema_duration"]
            count = baseline["count"]

            # Detect anomaly: duration > 2x the EMA (only after 3+ data points)
            if count >= 3 and ema > 0 and duration > ema * 2:
                anomaly = Anomaly(
                    anomaly_type=AnomalyType.DURATION,
                    severity=AnomalySeverity.WARNING,
                    expected=f"{ema:.1f}s",
                    actual=f"{duration:.1f}s",
                    message=f"Duration {duration:.1f}s is {duration / ema:.1f}x the baseline ({ema:.1f}s)",
                )

            # Update EMA
            new_ema = self.alpha * duration + (1 - self.alpha) * ema
            self._baselines[key] = {
                "ema_duration": round(new_ema, 3),
                "count": count + 1,
                "last_duration": round(duration, 3),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        else:
            self._baselines[key] = {
                "ema_duration": round(duration, 3),
                "count": 1,
                "last_duration": round(duration, 3),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

        self._save()
        return anomaly

    def get_baseline(self, record: RunRecord) -> Optional[Dict[str, Any]]:
        """Get the baseline for a given record's image+commands."""
        key = self._key(record)
        return self._baselines.get(key)

    def list_baselines(self) -> Dict[str, Any]:
        """Return all baselines."""
        return dict(self._baselines)
