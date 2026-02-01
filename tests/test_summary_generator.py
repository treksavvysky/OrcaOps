"""Tests for SummaryGenerator deterministic job summary creation."""

from datetime import datetime, timezone, timedelta

from orcaops.log_analyzer import SummaryGenerator
from orcaops.schemas import (
    RunRecord, StepResult, JobStatus, ArtifactMetadata,
    ResourceUsage, LogAnalysis, Anomaly, AnomalyType, AnomalySeverity,
)


def _record(status=JobStatus.SUCCESS, steps=None, duration_secs=45.0, **kwargs):
    now = datetime.now(timezone.utc)
    return RunRecord(
        job_id="sum-test",
        status=status,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
        steps=steps or [
            StepResult(command="echo ok", exit_code=0, stdout="ok\n", stderr="",
                       duration_seconds=duration_secs),
        ],
        **kwargs,
    )


class TestSummarySuccess:
    def test_success_one_liner(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record())
        assert "1 step(s) passed" in summary.one_liner
        assert "45.0s" in summary.one_liner

    def test_success_status_label(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record())
        assert summary.status_label == "PASSED"

    def test_success_step_counts(self):
        gen = SummaryGenerator()
        steps = [
            StepResult(command="a", exit_code=0, stdout="", stderr="", duration_seconds=1),
            StepResult(command="b", exit_code=0, stdout="", stderr="", duration_seconds=1),
            StepResult(command="c", exit_code=0, stdout="", stderr="", duration_seconds=1),
        ]
        summary = gen.generate(_record(steps=steps))
        assert summary.step_count == 3
        assert summary.steps_passed == 3
        assert summary.steps_failed == 0

    def test_success_key_events(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record())
        assert any("completed successfully" in e for e in summary.key_events)


class TestSummaryFailed:
    def test_failed_one_liner_with_error(self):
        gen = SummaryGenerator()
        record = _record(
            status=JobStatus.FAILED,
            steps=[StepResult(
                command="test", exit_code=1,
                stdout="", stderr="Error: module not found",
                duration_seconds=2.0,
            )],
        )
        summary = gen.generate(record)
        assert "Failed:" in summary.one_liner
        assert "module not found" in summary.one_liner

    def test_failed_one_liner_no_error(self):
        gen = SummaryGenerator()
        record = _record(
            status=JobStatus.FAILED,
            steps=[StepResult(
                command="test", exit_code=1,
                stdout="", stderr="some output",
                duration_seconds=2.0,
            )],
        )
        summary = gen.generate(record)
        assert "Failed after" in summary.one_liner

    def test_failed_key_events(self):
        gen = SummaryGenerator()
        steps = [
            StepResult(command="a", exit_code=0, stdout="", stderr="", duration_seconds=1),
            StepResult(command="b", exit_code=1, stdout="", stderr="", duration_seconds=1),
        ]
        record = _record(status=JobStatus.FAILED, steps=steps)
        summary = gen.generate(record)
        assert any("Failed at step 2 of 2" in e for e in summary.key_events)

    def test_failed_suggestions_with_stack_trace(self):
        gen = SummaryGenerator()
        record = _record(
            status=JobStatus.FAILED,
            log_analysis=LogAnalysis(
                error_count=1,
                first_error="ValueError: bad",
                stack_traces=["Traceback..."],
                error_lines=["ValueError: bad"],
            ),
            steps=[StepResult(
                command="test", exit_code=1,
                stdout="", stderr="", duration_seconds=1,
            )],
        )
        summary = gen.generate(record)
        assert any("stack trace" in s.lower() for s in summary.suggestions)

    def test_failed_suggestions_no_error_found(self):
        gen = SummaryGenerator()
        record = _record(
            status=JobStatus.FAILED,
            log_analysis=LogAnalysis(),
            steps=[StepResult(
                command="test", exit_code=1,
                stdout="", stderr="", duration_seconds=1,
            )],
        )
        summary = gen.generate(record)
        assert any("stderr" in s.lower() for s in summary.suggestions)


class TestSummaryTimedOut:
    def test_timed_out_one_liner(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record(status=JobStatus.TIMED_OUT))
        assert "Timed out" in summary.one_liner
        assert summary.status_label == "TIMED_OUT"

    def test_timed_out_suggestion(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record(status=JobStatus.TIMED_OUT))
        assert any("timeout" in s.lower() for s in summary.suggestions)


class TestSummaryCancelled:
    def test_cancelled(self):
        gen = SummaryGenerator()
        summary = gen.generate(_record(status=JobStatus.CANCELLED))
        assert "Cancelled" in summary.one_liner
        assert summary.status_label == "CANCELLED"


class TestSummaryWithExtras:
    def test_with_artifacts(self):
        gen = SummaryGenerator()
        record = _record(artifacts=[
            ArtifactMetadata(name="out.txt", path="out.txt", size_bytes=100, sha256="abc"),
            ArtifactMetadata(name="log.txt", path="log.txt", size_bytes=200, sha256="def"),
        ])
        summary = gen.generate(record)
        assert any("2 artifact(s)" in e for e in summary.key_events)

    def test_with_resource_usage(self):
        gen = SummaryGenerator()
        record = _record(resource_usage=ResourceUsage(memory_peak_mb=512.5))
        summary = gen.generate(record)
        assert any("512.5 MB" in e for e in summary.key_events)

    def test_with_anomalies(self):
        gen = SummaryGenerator()
        anomaly = Anomaly(
            anomaly_type=AnomalyType.DURATION,
            severity=AnomalySeverity.WARNING,
            expected="10s", actual="35s",
            message="Slow",
        )
        record = _record(anomalies=[anomaly])
        summary = gen.generate(record)
        assert len(summary.anomalies) == 1

    def test_many_warnings_suggestion(self):
        gen = SummaryGenerator()
        record = _record(
            log_analysis=LogAnalysis(warning_count=15),
        )
        summary = gen.generate(record)
        assert any("15 warnings" in s for s in summary.suggestions)


class TestDurationFormatting:
    def test_seconds(self):
        assert SummaryGenerator._format_duration(45.2) == "45.2s"

    def test_minutes(self):
        assert SummaryGenerator._format_duration(150) == "2m 30s"

    def test_hours(self):
        assert SummaryGenerator._format_duration(3900) == "1h 5m"

    def test_zero(self):
        assert SummaryGenerator._format_duration(0) == "0.0s"
