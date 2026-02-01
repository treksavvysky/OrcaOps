"""Tests for Sprint 03 CLI observability commands."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from orcaops.schemas import RunRecord, JobStatus, StepResult


runner = CliRunner()


def _record(job_id="test-1", status=JobStatus.SUCCESS, duration_secs=30.0,
            image="python:3.11"):
    now = datetime.now(timezone.utc)
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=now,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
        steps=[StepResult(
            command="echo test", exit_code=0, stdout="ok", stderr="",
            duration_seconds=duration_secs,
        )],
    )


@pytest.fixture
def app():
    """Create a Typer app with job CLI commands registered."""
    import typer
    from orcaops.cli_jobs import JobCLI

    test_app = typer.Typer()
    JobCLI.add_commands(test_app)
    return test_app


class TestSummaryCommand:
    @patch("orcaops.cli_jobs._get_run_store")
    @patch("orcaops.cli_jobs._get_job_manager")
    def test_summary_success(self, mock_jm_fn, mock_rs_fn, app):
        mock_jm = MagicMock()
        mock_jm.get_job.return_value = _record()
        mock_jm_fn.return_value = mock_jm

        result = runner.invoke(app, ["jobs", "summary", "test-1"])
        assert result.exit_code == 0
        assert "Summary: test-1" in result.output
        assert "passed" in result.output.lower() or "success" in result.output.lower()

    @patch("orcaops.cli_jobs._get_run_store")
    @patch("orcaops.cli_jobs._get_job_manager")
    def test_summary_not_found(self, mock_jm_fn, mock_rs_fn, app):
        mock_jm = MagicMock()
        mock_jm.get_job.return_value = None
        mock_jm_fn.return_value = mock_jm

        mock_rs = MagicMock()
        mock_rs.get_run.return_value = None
        mock_rs_fn.return_value = mock_rs

        result = runner.invoke(app, ["jobs", "summary", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    @patch("orcaops.cli_jobs._get_run_store")
    @patch("orcaops.cli_jobs._get_job_manager")
    def test_summary_failed_job(self, mock_jm_fn, mock_rs_fn, app):
        record = _record(status=JobStatus.FAILED)
        record.steps[0].exit_code = 1
        record.error = "Command failed"

        mock_jm = MagicMock()
        mock_jm.get_job.return_value = record
        mock_jm_fn.return_value = mock_jm

        result = runner.invoke(app, ["jobs", "summary", "test-1"])
        assert result.exit_code == 0
        assert "Summary: test-1" in result.output


class TestMetricsCommand:
    @patch("orcaops.cli_jobs._get_run_store")
    def test_metrics_empty(self, mock_rs_fn, app):
        mock_rs = MagicMock()
        mock_rs.list_runs.return_value = ([], 0)
        mock_rs_fn.return_value = mock_rs

        result = runner.invoke(app, ["metrics"])
        assert result.exit_code == 0
        assert "Job Metrics" in result.output
        assert "Total Runs" in result.output

    @patch("orcaops.cli_jobs._get_run_store")
    def test_metrics_with_records(self, mock_rs_fn, app):
        records = [
            _record("j1", JobStatus.SUCCESS, duration_secs=10),
            _record("j2", JobStatus.FAILED, duration_secs=20),
            _record("j3", JobStatus.SUCCESS, duration_secs=30),
        ]
        mock_rs = MagicMock()
        mock_rs.list_runs.return_value = (records, len(records))
        mock_rs_fn.return_value = mock_rs

        result = runner.invoke(app, ["metrics"])
        assert result.exit_code == 0
        assert "3" in result.output  # total runs
        assert "Success Rate" in result.output
