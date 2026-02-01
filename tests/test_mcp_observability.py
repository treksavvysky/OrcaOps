"""Tests for Sprint 03 MCP server observability tools."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from orcaops.schemas import RunRecord, JobStatus, StepResult


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


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset MCP server singletons between tests."""
    import orcaops.mcp_server as mcp
    mcp._jm = None
    mcp._rs = None
    mcp._dm = None
    mcp._registry = None
    yield
    mcp._jm = None
    mcp._rs = None
    mcp._dm = None
    mcp._registry = None


class TestGetJobSummary:
    @patch("orcaops.mcp_server._run_store")
    @patch("orcaops.mcp_server._job_manager")
    def test_summary_from_job_manager(self, mock_jm_fn, mock_rs_fn):
        from orcaops.mcp_server import orcaops_get_job_summary

        mock_jm = MagicMock()
        mock_jm.get_job.return_value = _record()
        mock_jm_fn.return_value = mock_jm

        result = json.loads(orcaops_get_job_summary("test-1"))
        assert result["success"] is True
        assert "one_liner" in result
        assert "status_label" in result

    @patch("orcaops.mcp_server._run_store")
    @patch("orcaops.mcp_server._job_manager")
    def test_summary_falls_back_to_run_store(self, mock_jm_fn, mock_rs_fn):
        from orcaops.mcp_server import orcaops_get_job_summary

        mock_jm = MagicMock()
        mock_jm.get_job.return_value = None
        mock_jm_fn.return_value = mock_jm

        mock_rs = MagicMock()
        mock_rs.get_run.return_value = _record()
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_get_job_summary("test-1"))
        assert result["success"] is True

    @patch("orcaops.mcp_server._run_store")
    @patch("orcaops.mcp_server._job_manager")
    def test_summary_not_found(self, mock_jm_fn, mock_rs_fn):
        from orcaops.mcp_server import orcaops_get_job_summary

        mock_jm = MagicMock()
        mock_jm.get_job.return_value = None
        mock_jm_fn.return_value = mock_jm

        mock_rs = MagicMock()
        mock_rs.get_run.return_value = None
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_get_job_summary("nope"))
        assert result["success"] is False
        assert result["error"]["code"] == "JOB_NOT_FOUND"


class TestGetMetrics:
    @patch("orcaops.mcp_server._run_store")
    def test_metrics_empty(self, mock_rs_fn):
        from orcaops.mcp_server import orcaops_get_metrics

        mock_rs = MagicMock()
        mock_rs.list_runs.return_value = ([], 0)
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_get_metrics())
        assert result["success"] is True
        assert result["total_runs"] == 0

    @patch("orcaops.mcp_server._run_store")
    def test_metrics_with_records(self, mock_rs_fn):
        from orcaops.mcp_server import orcaops_get_metrics

        records = [
            _record("j1", JobStatus.SUCCESS),
            _record("j2", JobStatus.FAILED),
            _record("j3", JobStatus.SUCCESS),
        ]
        mock_rs = MagicMock()
        mock_rs.list_runs.return_value = (records, len(records))
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_get_metrics())
        assert result["success"] is True
        assert result["total_runs"] == 3
        assert result["success_count"] == 2


class TestRunJobTriggeredBy:
    @patch("orcaops.mcp_server._job_manager")
    def test_run_job_sets_triggered_by_mcp(self, mock_jm_fn):
        from orcaops.mcp_server import orcaops_submit_job

        mock_jm = MagicMock()
        mock_jm.submit_job.return_value = _record()
        mock_jm_fn.return_value = mock_jm

        result = json.loads(orcaops_submit_job(
            image="python:3.11",
            commands=["echo hello"],
        ))
        assert result["success"] is True

        spec_arg = mock_jm.submit_job.call_args[0][0]
        assert spec_arg.triggered_by == "mcp"

    @patch("orcaops.mcp_server._job_manager")
    def test_submit_with_intent_and_tags(self, mock_jm_fn):
        from orcaops.mcp_server import orcaops_submit_job

        mock_jm = MagicMock()
        mock_jm.submit_job.return_value = _record()
        mock_jm_fn.return_value = mock_jm

        result = json.loads(orcaops_submit_job(
            image="python:3.11",
            commands=["pytest"],
            intent="Run tests for PR #42",
            tags=["ci", "python"],
        ))
        assert result["success"] is True

        spec_arg = mock_jm.submit_job.call_args[0][0]
        assert spec_arg.intent == "Run tests for PR #42"
        assert spec_arg.tags == ["ci", "python"]


class TestListRunsFilters:
    @patch("orcaops.mcp_server._run_store")
    def test_list_runs_with_image_filter(self, mock_rs_fn):
        from orcaops.mcp_server import orcaops_list_runs

        mock_rs = MagicMock()
        records = [_record("j1", image="python:3.11")]
        mock_rs.list_runs.return_value = (records, 1)
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_list_runs(image="python"))
        assert result["success"] is True
        assert result["total"] == 1

        call_kwargs = mock_rs.list_runs.call_args[1]
        assert call_kwargs["image"] == "python"

    @patch("orcaops.mcp_server._run_store")
    def test_list_runs_with_tags_filter(self, mock_rs_fn):
        from orcaops.mcp_server import orcaops_list_runs

        mock_rs = MagicMock()
        mock_rs.list_runs.return_value = ([], 0)
        mock_rs_fn.return_value = mock_rs

        result = json.loads(orcaops_list_runs(tags=["ci", "python"]))
        assert result["success"] is True

        call_kwargs = mock_rs.list_runs.call_args[1]
        assert call_kwargs["tags"] == ["ci", "python"]
