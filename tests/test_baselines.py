"""Tests for BaselineTracker EMA-based duration baselines and anomaly detection."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta

from orcaops.metrics import BaselineTracker
from orcaops.schemas import RunRecord, StepResult, JobStatus, AnomalyType, AnomalySeverity


def _record(job_id="test", status=JobStatus.SUCCESS, image="python:3.11",
            duration_secs=10.0, commands=None):
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
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=now,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
        steps=steps,
    )


class TestBaselineFirstRun:
    def test_creates_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)
            anomaly = tracker.update(_record(duration_secs=10.0))
            assert anomaly is None
            baselines = tracker.list_baselines()
            assert len(baselines) == 1
            assert baselines[0].duration_ema == 10.0
            assert baselines[0].sample_count == 1


class TestBaselineEMA:
    def test_ema_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path, alpha=0.2)

            # First run: EMA = 10.0
            tracker.update(_record(job_id="r1", duration_secs=10.0))
            # Second run: EMA = 0.2 * 20 + 0.8 * 10 = 12.0
            tracker.update(_record(job_id="r2", duration_secs=20.0))

            baselines = tracker.list_baselines()
            assert len(baselines) == 1
            assert baselines[0].duration_ema == 12.0
            assert baselines[0].sample_count == 2


class TestAnomalyDetection:
    def test_anomaly_detected_after_3_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path, alpha=0.2)

            # Build up baseline with 3 normal runs (~10s each)
            for i in range(3):
                anomaly = tracker.update(_record(job_id=f"r{i}", duration_secs=10.0))
                assert anomaly is None

            # 4th run: way over 2x baseline (~10s) → anomaly
            anomaly = tracker.update(_record(job_id="r4", duration_secs=25.0))
            assert anomaly is not None
            assert anomaly.anomaly_type == AnomalyType.DURATION
            assert anomaly.severity == AnomalySeverity.WARNING
            assert "25.0s" in anomaly.actual
            assert "10.0s" in anomaly.expected

    def test_no_anomaly_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path, alpha=0.2)

            for i in range(3):
                tracker.update(_record(job_id=f"r{i}", duration_secs=10.0))

            # 1.5x the baseline — below 2x threshold
            anomaly = tracker.update(_record(job_id="r4", duration_secs=15.0))
            assert anomaly is None

    def test_no_anomaly_with_fewer_than_3_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path, alpha=0.2)

            tracker.update(_record(job_id="r1", duration_secs=10.0))
            tracker.update(_record(job_id="r2", duration_secs=10.0))
            # Only 2 data points — no anomaly even for 3x
            anomaly = tracker.update(_record(job_id="r3", duration_secs=30.0))
            assert anomaly is None


class TestBaselineSkipsFailed:
    def test_failed_runs_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            anomaly = tracker.update(_record(status=JobStatus.FAILED))
            assert anomaly is None
            assert len(tracker.list_baselines()) == 0

    def test_timed_out_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            anomaly = tracker.update(_record(status=JobStatus.TIMED_OUT))
            assert anomaly is None
            assert len(tracker.list_baselines()) == 0


class TestBaselinePersistence:
    def test_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")

            tracker1 = BaselineTracker(baselines_path=path)
            tracker1.update(_record(duration_secs=10.0))

            # New tracker instance reads from same file
            tracker2 = BaselineTracker(baselines_path=path)
            baselines = tracker2.list_baselines()
            assert len(baselines) == 1
            assert baselines[0].duration_ema == 10.0


class TestBaselineKeyGeneration:
    def test_different_images_different_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", image="python:3.11"))
            tracker.update(_record(job_id="r2", image="node:18"))

            assert len(tracker.list_baselines()) == 2

    def test_different_commands_different_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "baselines.json")
            tracker = BaselineTracker(baselines_path=path)

            tracker.update(_record(job_id="r1", commands=["pytest"]))
            tracker.update(_record(job_id="r2", commands=["npm test"]))

            assert len(tracker.list_baselines()) == 2
