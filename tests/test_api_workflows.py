"""Tests for workflow API endpoints."""

import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orcaops.schemas import (
    WorkflowRecord, WorkflowStatus, WorkflowJobStatus, JobStatus,
)


def _wf_record(workflow_id="wf-1", status=WorkflowStatus.SUCCESS):
    return WorkflowRecord(
        workflow_id=workflow_id,
        spec_name="test-wf",
        status=status,
        created_at=datetime.now(timezone.utc),
        job_statuses={
            "build": WorkflowJobStatus(
                job_name="build", status=JobStatus.SUCCESS,
            ),
        },
    )


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    with patch("orcaops.api.docker_manager"), \
         patch("orcaops.api.job_manager") as mock_jm, \
         patch("orcaops.api.run_store") as mock_rs, \
         patch("orcaops.api.workflow_manager") as mock_wm, \
         patch("orcaops.api.workflow_store") as mock_ws:

        mock_jm.output_dir = tempfile.mkdtemp()
        mock_rs.list_runs.return_value = ([], 0)
        mock_ws.list_workflows.return_value = ([], 0)

        from main import app
        yield TestClient(app), mock_wm, mock_ws


class TestSubmitWorkflow:
    def test_submit_valid_workflow(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.submit_workflow.return_value = _wf_record(status=WorkflowStatus.PENDING)

        resp = tc.post("/orcaops/workflows", json={
            "spec": {
                "name": "test-wf",
                "jobs": {
                    "build": {
                        "image": "python:3.11",
                        "commands": ["echo hello"],
                    },
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "wf-1"
        assert data["status"] == "pending"

    def test_submit_sets_triggered_by_api(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.submit_workflow.return_value = _wf_record(status=WorkflowStatus.PENDING)

        tc.post("/orcaops/workflows", json={
            "spec": {
                "name": "test-wf",
                "jobs": {"build": {"image": "alpine", "commands": ["echo"]}},
            },
        })
        call_kwargs = mock_wm.submit_workflow.call_args[1]
        assert call_kwargs["triggered_by"] == "api"

    def test_submit_invalid_spec(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.submit_workflow.side_effect = ValueError("Invalid spec")

        resp = tc.post("/orcaops/workflows", json={
            "spec": {
                "name": "test-wf",
                "jobs": {"build": {"image": "alpine", "commands": ["echo"]}},
            },
        })
        assert resp.status_code == 400


class TestGetWorkflowStatus:
    def test_get_status_found(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.get_workflow.return_value = _wf_record()

        resp = tc.get("/orcaops/workflows/wf-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "wf-1"
        assert data["status"] == "success"

    def test_get_status_from_store(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = _wf_record()

        resp = tc.get("/orcaops/workflows/wf-1")
        assert resp.status_code == 200

    def test_get_status_not_found(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = None

        resp = tc.get("/orcaops/workflows/nonexistent")
        assert resp.status_code == 404


class TestGetWorkflowJobs:
    def test_get_jobs(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.get_workflow.return_value = _wf_record()

        resp = tc.get("/orcaops/workflows/wf-1/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert "build" in data["jobs"]


class TestCancelWorkflow:
    def test_cancel_active(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.cancel_workflow.return_value = (True, _wf_record(status=WorkflowStatus.CANCELLED))

        resp = tc.post("/orcaops/workflows/wf-1/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_not_found(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.cancel_workflow.return_value = (False, None)

        resp = tc.post("/orcaops/workflows/nonexistent/cancel")
        assert resp.status_code == 404


class TestListWorkflows:
    def test_list_empty(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.list_workflows.return_value = []

        resp = tc.get("/orcaops/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_with_records(self, client):
        tc, mock_wm, mock_ws = client
        mock_wm.list_workflows.return_value = [_wf_record("wf-1"), _wf_record("wf-2")]
        mock_ws.list_workflows.return_value = ([], 0)

        resp = tc.get("/orcaops/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
