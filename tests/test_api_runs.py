import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from orcaops.schemas import RunRecord, JobStatus


def _make_record(job_id="test-job", status=JobStatus.SUCCESS):
    return RunRecord(
        job_id=job_id,
        status=status,
        created_at=datetime.now(timezone.utc),
        steps=[],
        artifacts=[],
    )


@pytest.fixture
def client():
    """Create test client with mocked dependencies."""
    with patch("orcaops.api.DockerManager"), \
         patch("orcaops.api.JobManager"), \
         patch("orcaops.api.RunStore") as MockRunStore:
        store = MockRunStore.return_value
        import orcaops.api
        orcaops.api.run_store = store
        from main import app
        yield TestClient(app), store


def test_list_runs_empty(client):
    test_client, store = client
    store.list_runs.return_value = ([], 0)
    resp = test_client.get("/orcaops/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["runs"] == []
    assert data["offset"] == 0
    assert data["limit"] == 50


def test_list_runs_with_records(client):
    test_client, store = client
    records = [_make_record("job-1"), _make_record("job-2", JobStatus.FAILED)]
    store.list_runs.return_value = (records, 2)
    resp = test_client.get("/orcaops/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["runs"]) == 2


def test_list_runs_with_status_filter(client):
    test_client, store = client
    store.list_runs.return_value = ([_make_record()], 1)
    resp = test_client.get("/orcaops/runs?status=success&limit=10&offset=5")
    assert resp.status_code == 200
    store.list_runs.assert_called_once_with(
        status=JobStatus.SUCCESS, limit=10, offset=5
    )


def test_get_run_found(client):
    test_client, store = client
    record = _make_record(job_id="my-job")
    store.get_run.return_value = record
    resp = test_client.get("/orcaops/runs/my-job")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "my-job"


def test_get_run_not_found(client):
    test_client, store = client
    store.get_run.return_value = None
    resp = test_client.get("/orcaops/runs/nonexistent")
    assert resp.status_code == 404


def test_delete_run_success(client):
    test_client, store = client
    store.delete_run.return_value = True
    resp = test_client.delete("/orcaops/runs/my-job")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True
    assert data["job_id"] == "my-job"


def test_delete_run_not_found(client):
    test_client, store = client
    store.delete_run.return_value = False
    resp = test_client.delete("/orcaops/runs/nonexistent")
    assert resp.status_code == 404


def test_cleanup_runs_default(client):
    test_client, store = client
    store.cleanup_old_runs.return_value = ["old-1", "old-2"]
    resp = test_client.post("/orcaops/runs/cleanup", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_count"] == 2
    assert data["deleted_job_ids"] == ["old-1", "old-2"]
    store.cleanup_old_runs.assert_called_once_with(older_than_days=30)


def test_cleanup_runs_custom_days(client):
    test_client, store = client
    store.cleanup_old_runs.return_value = []
    resp = test_client.post("/orcaops/runs/cleanup", json={"older_than_days": 7})
    assert resp.status_code == 200
    store.cleanup_old_runs.assert_called_once_with(older_than_days=7)


def test_cleanup_route_not_captured_as_job_id(client):
    """Verify POST /runs/cleanup doesn't match GET /runs/{job_id}."""
    test_client, store = client
    store.cleanup_old_runs.return_value = []
    resp = test_client.post("/orcaops/runs/cleanup", json={})
    assert resp.status_code == 200
    assert "deleted_count" in resp.json()
