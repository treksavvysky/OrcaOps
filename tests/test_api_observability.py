"""Tests for Sprint 03 API observability endpoints."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orcaops.schemas import (
    RunRecord, JobStatus, StepResult, JobSpec, SandboxSpec, JobCommand,
)


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    with patch("orcaops.api.docker_manager"), \
         patch("orcaops.api.job_manager") as mock_jm, \
         patch("orcaops.api.run_store") as mock_rs:

        mock_jm.output_dir = tempfile.mkdtemp()
        mock_rs.list_runs.return_value = ([], 0)

        from main import app
        yield TestClient(app), mock_jm, mock_rs


def _record(job_id="test-1", status=JobStatus.SUCCESS, duration_secs=30.0,
            image="python:3.11", commands=None):
    now = datetime.now(timezone.utc)
    steps = []
    if commands:
        for cmd in commands:
            steps.append(StepResult(
                command=cmd, exit_code=0, stdout="ok", stderr="",
                duration_seconds=duration_secs,
            ))
    else:
        steps.append(StepResult(
            command="echo test", exit_code=0, stdout="ok", stderr="",
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


class TestSummaryEndpoint:
    def test_summary_success(self, client):
        tc, mock_jm, mock_rs = client
        record = _record()
        mock_jm.get_job.return_value = record

        resp = tc.get("/orcaops/jobs/test-1/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "test-1"
        assert "summary" in data
        assert "one_liner" in data["summary"]
        assert "status_label" in data["summary"]

    def test_summary_not_found(self, client):
        tc, mock_jm, mock_rs = client
        mock_jm.get_job.return_value = None
        mock_rs.get_run.return_value = None

        resp = tc.get("/orcaops/jobs/nonexistent/summary")
        assert resp.status_code == 404

    def test_summary_falls_back_to_run_store(self, client):
        tc, mock_jm, mock_rs = client
        mock_jm.get_job.return_value = None
        mock_rs.get_run.return_value = _record()

        resp = tc.get("/orcaops/jobs/test-1/summary")
        assert resp.status_code == 200


class TestMetricsEndpoint:
    def test_metrics_empty(self, client):
        tc, mock_jm, mock_rs = client

        resp = tc.get("/orcaops/metrics/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 0
        assert data["success_rate"] == 0.0

    def test_metrics_with_records(self, client):
        tc, mock_jm, mock_rs = client
        records = [
            _record("j1", JobStatus.SUCCESS),
            _record("j2", JobStatus.FAILED),
        ]
        mock_rs.list_runs.return_value = (records, len(records))

        resp = tc.get("/orcaops/metrics/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 2
        assert data["success_count"] == 1
        assert data["failed_count"] == 1


class TestRunsFilterEndpoint:
    def test_image_filter(self, client):
        tc, mock_jm, mock_rs = client
        records = [_record("j1", image="python:3.11")]
        mock_rs.list_runs.return_value = (records, 1)

        resp = tc.get("/orcaops/runs?image=python")
        assert resp.status_code == 200
        mock_rs.list_runs.assert_called_once()
        call_kwargs = mock_rs.list_runs.call_args[1]
        assert call_kwargs["image"] == "python"

    def test_tags_filter(self, client):
        tc, mock_jm, mock_rs = client
        mock_rs.list_runs.return_value = ([], 0)

        resp = tc.get("/orcaops/runs?tags=ci,python")
        assert resp.status_code == 200
        call_kwargs = mock_rs.list_runs.call_args[1]
        assert call_kwargs["tags"] == ["ci", "python"]

    def test_triggered_by_filter(self, client):
        tc, mock_jm, mock_rs = client
        mock_rs.list_runs.return_value = ([], 0)

        resp = tc.get("/orcaops/runs?triggered_by=api")
        assert resp.status_code == 200
        call_kwargs = mock_rs.list_runs.call_args[1]
        assert call_kwargs["triggered_by"] == "api"


class TestJobSubmitTriggeredBy:
    def test_api_sets_triggered_by(self, client):
        tc, mock_jm, mock_rs = client
        record = _record()
        mock_jm.submit_job.return_value = record

        resp = tc.post("/orcaops/jobs", json={
            "job_id": "test-api-1",
            "sandbox": {"image": "python:3.11"},
            "commands": [{"command": "echo hello"}],
        })
        assert resp.status_code == 200
        spec_arg = mock_jm.submit_job.call_args[0][0]
        assert spec_arg.triggered_by == "api"
