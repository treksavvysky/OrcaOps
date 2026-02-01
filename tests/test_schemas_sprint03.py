"""Tests for Sprint 03 schema additions: observability models and RunRecord extensions."""

import json
from datetime import datetime, timezone

from orcaops.schemas import (
    AnomalySeverity,
    AnomalyType,
    Anomaly,
    EnvironmentCapture,
    JobCommand,
    JobSpec,
    JobStatus,
    JobSummary,
    JobSummaryResponse,
    LogAnalysis,
    MetricsResponse,
    ResourceUsage,
    RunRecord,
    SandboxSpec,
)


class TestBackwardCompatibility:
    """Existing run.json files (without new fields) must still deserialize."""

    def test_runrecord_minimal(self):
        data = {"job_id": "old-job", "status": "success"}
        record = RunRecord.model_validate(data)
        assert record.job_id == "old-job"
        assert record.triggered_by is None
        assert record.intent is None
        assert record.parent_job_id is None
        assert record.tags == []
        assert record.metadata == {}
        assert record.resource_usage is None
        assert record.environment is None
        assert record.log_analysis is None
        assert record.anomalies == []

    def test_runrecord_full_sprint01_format(self):
        data = {
            "job_id": "test-123",
            "status": "failed",
            "created_at": "2024-01-15T10:30:00Z",
            "started_at": "2024-01-15T10:30:01Z",
            "finished_at": "2024-01-15T10:30:45Z",
            "sandbox_id": "abc123",
            "image_ref": "python:3.11",
            "steps": [
                {
                    "command": "echo hello",
                    "exit_code": 0,
                    "stdout": "hello\n",
                    "stderr": "",
                    "duration_seconds": 0.5,
                    "timestamp": "2024-01-15T10:30:02Z",
                }
            ],
            "artifacts": [],
            "cleanup_status": "destroyed",
            "fingerprint": "abc",
            "error": "step failed",
        }
        record = RunRecord.model_validate(data)
        assert record.status == JobStatus.FAILED
        assert record.triggered_by is None
        assert record.anomalies == []

    def test_jobspec_without_new_fields(self):
        spec = JobSpec(
            job_id="test-1",
            sandbox=SandboxSpec(image="python:3.11"),
            commands=[JobCommand(command="echo hi")],
        )
        assert spec.triggered_by is None
        assert spec.intent is None
        assert spec.tags == []
        assert spec.metadata == {}


class TestNewModels:
    """Test construction and serialization of new models."""

    def test_resource_usage(self):
        ru = ResourceUsage(cpu_seconds=1.5, memory_peak_mb=128.3, network_rx_bytes=1024)
        data = json.loads(ru.model_dump_json())
        assert data["cpu_seconds"] == 1.5
        assert data["memory_peak_mb"] == 128.3
        assert data["network_rx_bytes"] == 1024
        assert data["disk_read_bytes"] == 0

    def test_resource_usage_defaults(self):
        ru = ResourceUsage()
        assert ru.cpu_seconds == 0.0
        assert ru.memory_peak_mb == 0.0

    def test_environment_capture(self):
        ec = EnvironmentCapture(
            image_digest="sha256:abc123",
            env_vars={"PATH": "/usr/bin", "SECRET": "***REDACTED***"},
            resource_limits={"memory_bytes": 536870912},
            docker_version="24.0.7",
        )
        data = json.loads(ec.model_dump_json())
        assert data["image_digest"] == "sha256:abc123"
        assert data["env_vars"]["SECRET"] == "***REDACTED***"
        assert data["docker_version"] == "24.0.7"

    def test_log_analysis(self):
        la = LogAnalysis(
            error_count=3,
            warning_count=5,
            first_error="ImportError: no module named foo",
            stack_traces=["Traceback...\n  File..."],
            error_lines=["ImportError: no module named foo"],
        )
        data = json.loads(la.model_dump_json())
        assert data["error_count"] == 3
        assert len(data["stack_traces"]) == 1

    def test_anomaly(self):
        a = Anomaly(
            anomaly_type=AnomalyType.DURATION,
            severity=AnomalySeverity.WARNING,
            expected="10.0s",
            actual="35.0s",
            message="Duration 35.0s is 3.5x the baseline (10.0s)",
        )
        data = json.loads(a.model_dump_json())
        assert data["anomaly_type"] == "duration"
        assert data["severity"] == "warning"

    def test_job_summary(self):
        s = JobSummary(
            job_id="test-1",
            one_liner="3 step(s) passed in 45.2s",
            status_label="PASSED",
            duration_human="45.2s",
            step_count=3,
            steps_passed=3,
            steps_failed=0,
            key_events=["All 3 step(s) completed successfully"],
            suggestions=[],
        )
        data = json.loads(s.model_dump_json())
        assert data["status_label"] == "PASSED"
        assert data["steps_failed"] == 0


class TestRunRecordWithNewFields:
    """Test RunRecord with all new fields populated."""

    def test_round_trip(self):
        record = RunRecord(
            job_id="obs-test",
            status=JobStatus.SUCCESS,
            triggered_by="mcp",
            intent="Run pytest for PR #123",
            parent_job_id="parent-1",
            tags=["ci", "python"],
            metadata={"pr_number": 123},
            resource_usage=ResourceUsage(cpu_seconds=2.5, memory_peak_mb=256.0),
            environment=EnvironmentCapture(docker_version="24.0.7"),
            log_analysis=LogAnalysis(error_count=0, warning_count=1),
            anomalies=[],
        )
        json_str = record.model_dump_json()
        restored = RunRecord.model_validate_json(json_str)
        assert restored.triggered_by == "mcp"
        assert restored.intent == "Run pytest for PR #123"
        assert restored.tags == ["ci", "python"]
        assert restored.resource_usage.cpu_seconds == 2.5
        assert restored.environment.docker_version == "24.0.7"
        assert restored.log_analysis.warning_count == 1

    def test_jobspec_with_context(self):
        spec = JobSpec(
            job_id="ctx-test",
            sandbox=SandboxSpec(image="python:3.11"),
            commands=[JobCommand(command="pytest")],
            triggered_by="cli",
            intent="Run unit tests",
            tags=["test", "ci"],
            metadata={"branch": "main"},
        )
        assert spec.triggered_by == "cli"
        assert spec.intent == "Run unit tests"
        assert "test" in spec.tags


class TestResponseModels:
    def test_job_summary_response(self):
        summary = JobSummary(
            job_id="x", one_liner="ok", status_label="PASSED",
            duration_human="1.0s", step_count=1, steps_passed=1, steps_failed=0,
        )
        resp = JobSummaryResponse(job_id="x", summary=summary)
        assert resp.summary.one_liner == "ok"

    def test_metrics_response(self):
        resp = MetricsResponse(
            total_runs=10, success_count=8, failed_count=2,
            timed_out_count=0, cancelled_count=0,
            success_rate=0.8, avg_duration_seconds=30.5,
            total_duration_seconds=305.0,
        )
        assert resp.success_rate == 0.8
