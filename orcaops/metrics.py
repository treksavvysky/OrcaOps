"""
Metrics aggregation and baseline tracking.

Metrics are computed on-the-fly from RunStore (no separate storage).
Baselines use exponential moving average and persist to ~/.orcaops/baselines.json.
"""

import json
import os
import statistics
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from orcaops.schemas import (
    Anomaly,
    AnomalySeverity,
    AnomalyType,
    JobSpec,
    JobStatus,
    PerformanceBaseline,
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
    """Tracks job performance baselines using exponential moving average.

    Enhanced with percentiles, memory tracking, success rate, and thread safety.
    Backward compatible with old baselines.json format.
    """

    _MAX_RECENT_SAMPLES = 200

    def __init__(self, baselines_path: Optional[str] = None, alpha: float = 0.2):
        self.baselines_path = baselines_path or os.path.expanduser(
            "~/.orcaops/baselines.json"
        )
        self.alpha = alpha
        self._lock = threading.Lock()
        self._baselines: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self.baselines_path):
            try:
                with open(self.baselines_path, "r") as f:
                    data = json.load(f)
                # Migrate old-format entries
                for key in list(data.keys()):
                    if "recent_durations" not in data[key]:
                        data[key] = self._migrate_entry(key, data[key])
                return data
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _migrate_entry(self, key: str, old: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate old-format baseline entry to enhanced format."""
        try:
            ema = float(old.get("ema_duration", 0.0))
        except (TypeError, ValueError):
            ema = 0.0
        try:
            count = int(old.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        try:
            last_dur = float(old.get("last_duration", ema))
        except (TypeError, ValueError):
            last_dur = ema
        last_updated = old.get("last_updated")

        # Synthesize recent_durations from EMA value
        synthetic_count = min(count, 3)
        recent = [ema] * synthetic_count if ema > 0 else []

        entry = {
            "ema_duration": ema,
            "count": count,
            "last_duration": last_dur,
            "last_updated": last_updated,
            "first_seen": last_updated,
            "recent_durations": recent,
            "recent_memory_mb": [],
            "success_count": count,
            "failure_count": 0,
            "memory_mean_mb": 0.0,
            "memory_max_mb": 0.0,
        }
        self._recompute_stats(entry)
        return entry

    def _save(self):
        os.makedirs(os.path.dirname(self.baselines_path), exist_ok=True)
        with open(self.baselines_path, "w") as f:
            json.dump(self._baselines, f, indent=2, default=str)

    def _key(self, record: RunRecord) -> str:
        """Generate a baseline key from image + command fingerprint."""
        image = record.image_ref or "unknown"
        cmds = "|".join(s.command for s in record.steps)
        return f"{image}::{cmds}"

    def _key_from_spec(self, spec: JobSpec) -> str:
        """Generate a baseline key from a JobSpec."""
        image = spec.sandbox.image
        cmds = "|".join(c.command for c in spec.commands)
        return f"{image}::{cmds}"

    def _recompute_stats(self, entry: Dict[str, Any]) -> None:
        """Recompute percentiles and stddev from rolling window."""
        durations = entry.get("recent_durations", [])
        if not durations:
            for k in ("duration_mean", "duration_stddev", "duration_p50",
                       "duration_p95", "duration_p99", "duration_min", "duration_max"):
                entry[k] = 0.0
            return

        entry["duration_mean"] = round(statistics.mean(durations), 3)
        entry["duration_min"] = round(min(durations), 3)
        entry["duration_max"] = round(max(durations), 3)

        if len(durations) >= 2:
            entry["duration_stddev"] = round(statistics.stdev(durations), 3)
            qs = statistics.quantiles(durations, n=100)
            entry["duration_p50"] = round(qs[49], 3)
            entry["duration_p95"] = round(qs[94], 3)
            entry["duration_p99"] = round(qs[min(98, len(qs) - 1)], 3)
        else:
            entry["duration_stddev"] = 0.0
            val = durations[0]
            entry["duration_p50"] = round(val, 3)
            entry["duration_p95"] = round(val, 3)
            entry["duration_p99"] = round(val, 3)

        # Memory stats
        mem = entry.get("recent_memory_mb", [])
        if mem:
            entry["memory_mean_mb"] = round(statistics.mean(mem), 3)
            entry["memory_max_mb"] = round(max(mem), 3)

    def update(self, record: RunRecord) -> Optional[Anomaly]:
        """Update baseline with a completed run. Returns anomaly if detected.

        Success runs update duration/memory baselines.
        All completed runs (success + failed) update success_rate.
        """
        if not record.started_at or not record.finished_at:
            return None
        if record.status not in (JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMED_OUT):
            return None

        duration = (record.finished_at - record.started_at).total_seconds()
        key = self._key(record)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Extract memory from resource_usage if available
        memory_mb = 0.0
        if record.resource_usage and record.resource_usage.memory_peak_mb > 0:
            memory_mb = record.resource_usage.memory_peak_mb

        with self._lock:
            anomaly = None

            if key in self._baselines:
                entry = self._baselines[key]
                ema = entry.get("ema_duration", 0.0)
                count = entry.get("count", 0)

                # Update success tracking for all completed runs
                if record.status == JobStatus.SUCCESS:
                    entry["success_count"] = entry.get("success_count", 0) + 1
                else:
                    entry["failure_count"] = entry.get("failure_count", 0) + 1

                total = entry.get("success_count", 0) + entry.get("failure_count", 0)
                entry["success_rate"] = round(entry.get("success_count", 0) / max(total, 1), 3)

                # Only update duration/memory baselines for successful runs
                if record.status == JobStatus.SUCCESS:
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
                    entry["ema_duration"] = round(new_ema, 3)
                    entry["count"] = count + 1
                    entry["last_duration"] = round(duration, 3)

                    # Add to rolling window
                    recent = entry.get("recent_durations", [])
                    recent.append(round(duration, 3))
                    if len(recent) > self._MAX_RECENT_SAMPLES:
                        recent = recent[-self._MAX_RECENT_SAMPLES:]
                    entry["recent_durations"] = recent

                    # Memory tracking
                    if memory_mb > 0:
                        mem_recent = entry.get("recent_memory_mb", [])
                        mem_recent.append(round(memory_mb, 3))
                        if len(mem_recent) > self._MAX_RECENT_SAMPLES:
                            mem_recent = mem_recent[-self._MAX_RECENT_SAMPLES:]
                        entry["recent_memory_mb"] = mem_recent

                    self._recompute_stats(entry)

                entry["last_updated"] = now_iso
                self._baselines[key] = entry
            else:
                # New baseline — only create for successful runs
                if record.status != JobStatus.SUCCESS:
                    return None

                recent = [round(duration, 3)]
                mem_recent = [round(memory_mb, 3)] if memory_mb > 0 else []

                entry = {
                    "ema_duration": round(duration, 3),
                    "count": 1,
                    "last_duration": round(duration, 3),
                    "last_updated": now_iso,
                    "first_seen": now_iso,
                    "recent_durations": recent,
                    "recent_memory_mb": mem_recent,
                    "success_count": 1,
                    "failure_count": 0,
                    "success_rate": 1.0,
                    "memory_mean_mb": round(memory_mb, 3),
                    "memory_max_mb": round(memory_mb, 3),
                }
                self._recompute_stats(entry)
                self._baselines[key] = entry

            self._save()
            return anomaly

    def _entry_to_model(self, key: str, entry: Dict[str, Any]) -> PerformanceBaseline:
        """Convert internal dict entry to Pydantic model."""
        return PerformanceBaseline(
            key=key,
            sample_count=entry.get("count", 0),
            duration_ema=entry.get("ema_duration", 0.0),
            duration_mean=entry.get("duration_mean", 0.0),
            duration_stddev=entry.get("duration_stddev", 0.0),
            duration_p50=entry.get("duration_p50", 0.0),
            duration_p95=entry.get("duration_p95", 0.0),
            duration_p99=entry.get("duration_p99", 0.0),
            duration_min=entry.get("duration_min", 0.0),
            duration_max=entry.get("duration_max", 0.0),
            memory_mean_mb=entry.get("memory_mean_mb", 0.0),
            memory_max_mb=entry.get("memory_max_mb", 0.0),
            success_count=entry.get("success_count", 0),
            failure_count=entry.get("failure_count", 0),
            success_rate=entry.get("success_rate", 1.0),
            recent_durations=entry.get("recent_durations", []),
            recent_memory_mb=entry.get("recent_memory_mb", []),
            last_duration=entry.get("last_duration", 0.0),
            last_updated=entry.get("last_updated"),
            first_seen=entry.get("first_seen"),
        )

    def get_baseline(self, record: RunRecord) -> Optional[PerformanceBaseline]:
        """Get the baseline for a given record's image+commands."""
        key = self._key(record)
        with self._lock:
            entry = self._baselines.get(key)
            if entry is None:
                return None
            return self._entry_to_model(key, entry)

    def get_baseline_by_key(self, key: str) -> Optional[PerformanceBaseline]:
        """Get baseline by key string."""
        with self._lock:
            entry = self._baselines.get(key)
            if entry is None:
                return None
            return self._entry_to_model(key, entry)

    def get_baseline_for_spec(self, spec: JobSpec) -> Optional[PerformanceBaseline]:
        """Get baseline for a JobSpec."""
        key = self._key_from_spec(spec)
        return self.get_baseline_by_key(key)

    def list_baselines(self) -> List[PerformanceBaseline]:
        """Return all baselines as Pydantic models."""
        with self._lock:
            return [
                self._entry_to_model(key, entry)
                for key, entry in self._baselines.items()
            ]

    def delete_baseline(self, key: str) -> bool:
        """Delete a specific baseline. Returns True if found and deleted."""
        with self._lock:
            if key in self._baselines:
                del self._baselines[key]
                self._save()
                return True
            return False
