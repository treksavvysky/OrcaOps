import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from orcaops.schemas import RunRecord, JobStatus


def _make_record(job_id="test-job", status=JobStatus.RUNNING, sandbox_id="container-123"):
    return RunRecord(
        job_id=job_id,
        status=status,
        sandbox_id=sandbox_id,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        steps=[],
        artifacts=[],
    )


@pytest.fixture
def client():
    """Create test client with mocked dependencies."""
    with patch("orcaops.api.DockerManager") as MockDM, \
         patch("orcaops.api.JobManager") as MockJM, \
         patch("orcaops.api.RunStore"):
        jm = MockJM.return_value
        dm = MockDM.return_value
        import orcaops.api
        orcaops.api.job_manager = jm
        orcaops.api.docker_manager = dm
        from main import app
        yield TestClient(app), jm, dm


def test_stream_logs_job_not_found(client):
    test_client, jm, dm = client
    jm.get_job.return_value = None
    resp = test_client.get("/orcaops/jobs/nonexistent/logs/stream")
    assert resp.status_code == 404


def test_stream_logs_no_container(client):
    test_client, jm, dm = client
    record = _make_record(sandbox_id=None, status=JobStatus.QUEUED)
    jm.get_job.return_value = record
    resp = test_client.get("/orcaops/jobs/test-job/logs/stream")
    assert resp.status_code == 400


def test_stream_logs_completed_job(client):
    test_client, jm, dm = client
    record = _make_record(status=JobStatus.SUCCESS)
    jm.get_job.return_value = record
    resp = test_client.get("/orcaops/jobs/test-job/logs/stream")
    assert resp.status_code == 410


def test_stream_logs_failed_job(client):
    test_client, jm, dm = client
    record = _make_record(status=JobStatus.FAILED)
    jm.get_job.return_value = record
    resp = test_client.get("/orcaops/jobs/test-job/logs/stream")
    assert resp.status_code == 410


def test_stream_logs_cancelled_job(client):
    test_client, jm, dm = client
    record = _make_record(status=JobStatus.CANCELLED)
    jm.get_job.return_value = record
    resp = test_client.get("/orcaops/jobs/test-job/logs/stream")
    assert resp.status_code == 410
