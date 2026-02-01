"""Tests for enhanced BaselineTracker with percentiles, memory, success rate."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone, timedelta

from orcaops.metrics import BaselineTracker
from orcaops.schemas import (
    RunRecord, StepResult, JobStatus, ResourceUsage,
    PerformanceBaseline, JobSpec, SandboxSpec, JobCommand,
)


def _record(job_id="test", status=JobStatus.SUCCESS, image="python:3.11",
            duration_secs=10.0, commands=None, memory_peak_mb=0.0):
    now = datetime.now(timezone.utc)
    steps = []
    if commands:
        for cmd in commands:
            steps.append(StepResult(
                command=cmd, exit_code=0, stdout="", stderr="",
                duration_seconds=duration_secs,
            ))
    else:
        steps.append(StepResult(
            command="echo test", exit_code=0, stdout="", stderr="",
            duration_seconds=duration_secs,
        ))
    resource_usage = None
    if memory_peak_mb > 0:
        resource_usage = ResourceUsage(memory_peak_mb=memory_peak_mb)
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=now,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
        steps=steps,
        resource_usage=resource_usage,
    )


class TestBaselineMigration:
    def test_old_format_migrated(self):
        """Old baselines.json without recent_durations is auto-migrated."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            old_data = {
                "python:3.11::pytest": {
                    "ema_duration": 15.0,
                    "count": 5,
                    "last_duration": 14.0,
                    "last_updated": "2025-01-01T00:00:00+00:00",
                }
            }
            with open(path, "w") as f:
                json.dump(old_data, f)

            tracker = BaselineTracker(baselines_path=path)
            baselines = tracker.list_baselines()
            assert len(baselines) == 1
            b = baselines[0]
            assert b.key == "python:3.11::pytest"
            assert b.duration_ema == 15.0
            assert b.sample_count == 5
            assert b.success_count == 5
            assert b.failure_count == 0
            assert b.success_rate == 1.0
            assert len(b.recent_durations) == 3  # min(5, 3)

    def test_old_format_missing_fields_filled(self):
        """Missing fields in old format are filled with defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            old_data = {
                "node:18::npm test": {
                    "ema_duration": 20.0,
                    "count": 1,
                    "last_duration": 20.0,
                    "last_updated": "2025-01-01T00:00:00+00:00",
                }
            }
            with open(path, "w") as f:
                json.dump(old_data, f)

            tracker = BaselineTracker(baselines_path=path)
            b = tracker.list_baselines()[0]
            assert b.memory_mean_mb == 0.0
            assert b.memory_max_mb == 0.0
            assert len(b.recent_durations) == 1  # min(1, 3)

    def test_new_format_not_migrated(self):
        """Already-migrated entries are not re-migrated."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)
            tracker.update(_record(duration_secs=10.0))

            # Reload
            tracker2 = BaselineTracker(baselines_path=path)
            b = tracker2.list_baselines()[0]
            assert b.sample_count == 1
            assert len(b.recent_durations) == 1


class TestBaselinePercentiles:
    def test_percentiles_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            # Add multiple runs
            for i in range(10):
                tracker.update(_record(job_id=f"r{i}", duration_secs=10.0 + i))

            b = tracker.list_baselines()[0]
            assert b.duration_p50 > 0
            assert b.duration_p95 > 0
            assert b.duration_p99 > 0
            assert b.duration_p50 <= b.duration_p95 <= b.duration_p99

    def test_single_sample_percentiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(duration_secs=10.0))

            b = tracker.list_baselines()[0]
            assert b.duration_p50 == 10.0
            assert b.duration_p95 == 10.0
            assert b.duration_p99 == 10.0

    def test_stddev_with_variation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", duration_secs=10.0))
            tracker.update(_record(job_id="r2", duration_secs=20.0))

            b = tracker.list_baselines()[0]
            assert b.duration_stddev > 0

    def test_stddev_zero_with_single_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(duration_secs=10.0))

            b = tracker.list_baselines()[0]
            assert b.duration_stddev == 0.0


class TestBaselineMemoryTracking:
    def test_memory_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", duration_secs=10.0, memory_peak_mb=256.0))
            tracker.update(_record(job_id="r2", duration_secs=10.0, memory_peak_mb=512.0))

            b = tracker.list_baselines()[0]
            assert b.memory_max_mb == 512.0
            assert b.memory_mean_mb > 0

    def test_no_memory_when_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(duration_secs=10.0))

            b = tracker.list_baselines()[0]
            assert b.memory_mean_mb == 0.0
            assert b.memory_max_mb == 0.0

    def test_memory_rolling_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            for i in range(5):
                tracker.update(_record(job_id=f"r{i}", duration_secs=10.0,
                                       memory_peak_mb=100.0 + i * 10))

            b = tracker.list_baselines()[0]
            assert len(b.recent_memory_mb) == 5


class TestBaselineSuccessRate:
    def test_success_rate_tracks_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            # 3 successes first
            for i in range(3):
                tracker.update(_record(job_id=f"s{i}", duration_secs=10.0))

            # 1 failure
            tracker.update(_record(job_id="f1", status=JobStatus.FAILED, duration_secs=5.0))

            b = tracker.list_baselines()[0]
            assert b.success_count == 3
            assert b.failure_count == 1
            assert b.success_rate == 0.75

    def test_failed_runs_dont_update_durations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="s1", duration_secs=10.0))
            tracker.update(_record(job_id="f1", status=JobStatus.FAILED, duration_secs=100.0))

            b = tracker.list_baselines()[0]
            # Duration baselines unchanged by failed run
            assert b.duration_ema == 10.0
            assert b.sample_count == 1
            assert len(b.recent_durations) == 1

    def test_first_run_failed_no_baseline_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(status=JobStatus.FAILED, duration_secs=10.0))

            assert len(tracker.list_baselines()) == 0

    def test_timed_out_counted_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="s1", duration_secs=10.0))
            tracker.update(_record(job_id="t1", status=JobStatus.TIMED_OUT, duration_secs=60.0))

            b = tracker.list_baselines()[0]
            assert b.failure_count == 1
            assert b.success_rate == 0.5


class TestBaselineRollingWindow:
    def test_window_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)
            tracker._MAX_RECENT_SAMPLES = 5  # Small for testing

            for i in range(10):
                tracker.update(_record(job_id=f"r{i}", duration_secs=10.0 + i))

            b = tracker.list_baselines()[0]
            assert len(b.recent_durations) == 5


class TestBaselineDeleteAndList:
    def test_delete_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", duration_secs=10.0))
            baselines = tracker.list_baselines()
            assert len(baselines) == 1

            key = baselines[0].key
            assert tracker.delete_baseline(key) is True
            assert len(tracker.list_baselines()) == 0

    def test_delete_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)
            assert tracker.delete_baseline("nonexistent") is False

    def test_list_returns_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", image="python:3.11", duration_secs=10.0))
            tracker.update(_record(job_id="r2", image="node:18", duration_secs=20.0))

            baselines = tracker.list_baselines()
            assert len(baselines) == 2
            assert all(isinstance(b, PerformanceBaseline) for b in baselines)


class TestBaselineGetByKey:
    def test_get_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(duration_secs=10.0))
            baselines = tracker.list_baselines()
            key = baselines[0].key

            b = tracker.get_baseline_by_key(key)
            assert b is not None
            assert b.duration_ema == 10.0

    def test_get_by_key_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)
            assert tracker.get_baseline_by_key("nope") is None


class TestBaselineForSpec:
    def test_key_from_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(image="python:3.11", commands=["pytest"]))

            spec = JobSpec(
                job_id="test",
                sandbox=SandboxSpec(image="python:3.11"),
                commands=[JobCommand(command="pytest")],
            )
            b = tracker.get_baseline_for_spec(spec)
            assert b is not None
            assert b.sample_count == 1


class TestBaselineThreadSafety:
    def test_concurrent_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            errors = []

            def update_baseline(thread_id):
                try:
                    for i in range(5):
                        tracker.update(_record(
                            job_id=f"t{thread_id}_r{i}",
                            duration_secs=10.0 + i,
                        ))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=update_baseline, args=(t,)) for t in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            baselines = tracker.list_baselines()
            assert len(baselines) == 1
            assert baselines[0].sample_count == 15


class TestBaselineMinMax:
    def test_min_max_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", duration_secs=5.0))
            tracker.update(_record(job_id="r2", duration_secs=15.0))
            tracker.update(_record(job_id="r3", duration_secs=10.0))

            b = tracker.list_baselines()[0]
            assert b.duration_min == 5.0
            assert b.duration_max == 15.0
