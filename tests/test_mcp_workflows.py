"""Tests for workflow MCP tools."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from orcaops.schemas import (
    JobStatus, WorkflowRecord, WorkflowStatus, WorkflowJobStatus,
)


def _wf_record(workflow_id="wf-1", status=WorkflowStatus.SUCCESS):
    return WorkflowRecord(
        workflow_id=workflow_id,
        spec_name="test-wf",
        status=status,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        job_statuses={
            "build": WorkflowJobStatus(
                job_name="build",
                status=JobStatus.SUCCESS,
                job_id="wf-wf-1-build",
            ),
        },
        triggered_by="mcp",
    )


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons before each test."""
    import orcaops.mcp_server as mod
    mod._jm = None
    mod._rs = None
    mod._dm = None
    mod._registry = None
    mod._wm = None
    mod._ws = None
    yield


@pytest.fixture
def mock_wm():
    wm = MagicMock()
    with patch("orcaops.mcp_server._wm", wm):
        with patch("orcaops.mcp_server._workflow_manager", return_value=wm):
            yield wm


@pytest.fixture
def mock_ws():
    ws = MagicMock()
    with patch("orcaops.mcp_server._ws", ws):
        with patch("orcaops.mcp_server._workflow_store", return_value=ws):
            yield ws


def _parse(result: str) -> dict:
    return json.loads(result)


class TestSubmitWorkflow:
    def test_submit_valid(self, mock_wm):
        from orcaops.mcp_server import orcaops_submit_workflow

        mock_wm.submit_workflow.return_value = _wf_record(status=WorkflowStatus.PENDING)

        result = _parse(orcaops_submit_workflow(
            spec={
                "name": "test-wf",
                "jobs": {
                    "build": {
                        "image": "python:3.11",
                        "commands": ["echo hello"],
                    },
                },
            },
        ))

        assert result["success"] is True
        assert result["workflow_id"] == "wf-1"
        assert result["status"] == "pending"
        mock_wm.submit_workflow.assert_called_once()

    def test_submit_invalid_spec(self, mock_wm):
        from orcaops.mcp_server import orcaops_submit_workflow

        result = _parse(orcaops_submit_workflow(
            spec={"name": "test-wf"},  # missing jobs
        ))

        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    def test_submit_duplicate_id(self, mock_wm):
        from orcaops.mcp_server import orcaops_submit_workflow

        mock_wm.submit_workflow.side_effect = ValueError("already exists")

        result = _parse(orcaops_submit_workflow(
            spec={
                "name": "test-wf",
                "jobs": {"build": {"image": "alpine", "commands": ["echo"]}},
            },
            workflow_id="wf-dup",
        ))

        assert result["success"] is False


class TestRunWorkflow:
    def test_run_completes(self, mock_wm):
        from orcaops.mcp_server import orcaops_run_workflow

        pending = _wf_record(status=WorkflowStatus.PENDING)
        done = _wf_record(status=WorkflowStatus.SUCCESS)
        mock_wm.submit_workflow.return_value = pending
        mock_wm.get_workflow.return_value = done

        result = _parse(orcaops_run_workflow(
            spec={
                "name": "test-wf",
                "jobs": {"build": {"image": "alpine", "commands": ["echo"]}},
            },
            timeout=5,
        ))

        assert result["success"] is True
        assert result["status"] == "success"
        assert "build" in result["job_statuses"]

    def test_run_invalid_spec(self, mock_wm):
        from orcaops.mcp_server import orcaops_run_workflow

        result = _parse(orcaops_run_workflow(
            spec={"name": "bad"},
            timeout=5,
        ))

        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGetWorkflowStatus:
    def test_found_in_manager(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_get_workflow_status

        mock_wm.get_workflow.return_value = _wf_record()

        result = _parse(orcaops_get_workflow_status("wf-1"))
        assert result["success"] is True
        assert result["workflow_id"] == "wf-1"

    def test_found_in_store(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_get_workflow_status

        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = _wf_record()

        result = _parse(orcaops_get_workflow_status("wf-1"))
        assert result["success"] is True

    def test_not_found(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_get_workflow_status

        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = None

        result = _parse(orcaops_get_workflow_status("nonexistent"))
        assert result["success"] is False
        assert result["error"]["code"] == "WORKFLOW_NOT_FOUND"


class TestCancelWorkflow:
    def test_cancel_active(self, mock_wm):
        from orcaops.mcp_server import orcaops_cancel_workflow

        mock_wm.cancel_workflow.return_value = (
            True, _wf_record(status=WorkflowStatus.CANCELLED),
        )

        result = _parse(orcaops_cancel_workflow("wf-1"))
        assert result["success"] is True
        assert result["status"] == "cancelled"

    def test_cancel_not_found(self, mock_wm):
        from orcaops.mcp_server import orcaops_cancel_workflow

        mock_wm.cancel_workflow.return_value = (False, None)

        result = _parse(orcaops_cancel_workflow("nonexistent"))
        assert result["success"] is False
        assert result["error"]["code"] == "WORKFLOW_NOT_FOUND"


class TestListWorkflows:
    def test_list_empty(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_list_workflows

        mock_wm.list_workflows.return_value = []
        mock_ws.list_workflows.return_value = ([], 0)

        result = _parse(orcaops_list_workflows())
        assert result["success"] is True
        assert result["count"] == 0
        assert result["workflows"] == []

    def test_list_with_records(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_list_workflows

        mock_wm.list_workflows.return_value = [
            _wf_record("wf-1"),
            _wf_record("wf-2", status=WorkflowStatus.RUNNING),
        ]
        mock_ws.list_workflows.return_value = ([], 0)

        result = _parse(orcaops_list_workflows())
        assert result["success"] is True
        assert result["count"] == 2

    def test_list_deduplicates(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_list_workflows

        mock_wm.list_workflows.return_value = [_wf_record("wf-1")]
        mock_ws.list_workflows.return_value = ([_wf_record("wf-1")], 1)

        result = _parse(orcaops_list_workflows())
        assert result["success"] is True
        assert result["count"] == 1

    def test_list_invalid_status(self, mock_wm, mock_ws):
        from orcaops.mcp_server import orcaops_list_workflows

        result = _parse(orcaops_list_workflows(status="invalid"))
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_STATUS"
