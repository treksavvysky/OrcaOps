import json
import os
import pytest
from datetime import datetime, timezone, timedelta

from orcaops.run_store import RunStore
from orcaops.schemas import JobStatus


@pytest.fixture
def store_dir(tmp_path):
    """Create a temporary artifacts directory."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return str(artifacts)


def _write_run_record(artifacts_dir, job_id, status="success", created_at=None):
    """Helper to write a run.json file."""
    job_dir = os.path.join(artifacts_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    record = {
        "job_id": job_id,
        "status": status,
        "created_at": created_at.isoformat(),
        "steps": [],
        "artifacts": [],
    }
    with open(os.path.join(job_dir, "run.json"), "w") as f:
        json.dump(record, f)


def test_list_runs_empty(store_dir):
    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs()
    assert records == []
    assert total == 0


def test_list_runs_nonexistent_dir(tmp_path):
    store = RunStore(artifacts_dir=str(tmp_path / "does_not_exist"))
    records, total = store.list_runs()
    assert records == []
    assert total == 0


def test_list_runs_returns_records(store_dir):
    _write_run_record(store_dir, "job-1", "success")
    _write_run_record(store_dir, "job-2", "failed")
    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs()
    assert total == 2
    assert len(records) == 2


def test_list_runs_sorted_newest_first(store_dir):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    new = datetime.now(timezone.utc)
    _write_run_record(store_dir, "old-job", "success", created_at=old)
    _write_run_record(store_dir, "new-job", "success", created_at=new)
    store = RunStore(artifacts_dir=store_dir)
    records, _ = store.list_runs()
    assert records[0].job_id == "new-job"
    assert records[1].job_id == "old-job"


def test_list_runs_filter_by_status(store_dir):
    _write_run_record(store_dir, "job-1", "success")
    _write_run_record(store_dir, "job-2", "failed")
    _write_run_record(store_dir, "job-3", "success")
    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs(status=JobStatus.SUCCESS)
    assert total == 2
    assert all(r.status == JobStatus.SUCCESS for r in records)


def test_list_runs_filter_failed(store_dir):
    _write_run_record(store_dir, "job-1", "success")
    _write_run_record(store_dir, "job-2", "failed")
    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs(status=JobStatus.FAILED)
    assert total == 1
    assert records[0].job_id == "job-2"


def test_list_runs_pagination(store_dir):
    for i in range(5):
        _write_run_record(store_dir, f"job-{i}", "success")
    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs(limit=2, offset=0)
    assert total == 5
    assert len(records) == 2


def test_list_runs_pagination_offset(store_dir):
    for i in range(5):
        _write_run_record(store_dir, f"job-{i}", "success")
    store = RunStore(artifacts_dir=store_dir)
    page1, _ = store.list_runs(limit=3, offset=0)
    page2, _ = store.list_runs(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids1 = {r.job_id for r in page1}
    ids2 = {r.job_id for r in page2}
    assert ids1.isdisjoint(ids2)


def test_get_run_found(store_dir):
    _write_run_record(store_dir, "job-1", "success")
    store = RunStore(artifacts_dir=store_dir)
    record = store.get_run("job-1")
    assert record is not None
    assert record.job_id == "job-1"
    assert record.status == JobStatus.SUCCESS


def test_get_run_not_found(store_dir):
    store = RunStore(artifacts_dir=store_dir)
    assert store.get_run("nonexistent") is None


def test_delete_run(store_dir):
    _write_run_record(store_dir, "job-1", "success")
    # Also write a fake artifact file
    with open(os.path.join(store_dir, "job-1", "output.txt"), "w") as f:
        f.write("artifact data")

    store = RunStore(artifacts_dir=store_dir)
    assert store.delete_run("job-1") is True
    assert store.get_run("job-1") is None
    assert not os.path.exists(os.path.join(store_dir, "job-1"))


def test_delete_run_not_found(store_dir):
    store = RunStore(artifacts_dir=store_dir)
    assert store.delete_run("nonexistent") is False


def test_cleanup_old_runs(store_dir):
    old_date = datetime.now(timezone.utc) - timedelta(days=60)
    recent_date = datetime.now(timezone.utc) - timedelta(days=5)

    _write_run_record(store_dir, "old-job", "success", created_at=old_date)
    _write_run_record(store_dir, "recent-job", "success", created_at=recent_date)

    store = RunStore(artifacts_dir=store_dir)
    deleted = store.cleanup_old_runs(older_than_days=30)

    assert "old-job" in deleted
    assert "recent-job" not in deleted
    assert store.get_run("old-job") is None
    assert store.get_run("recent-job") is not None


def test_cleanup_no_old_runs(store_dir):
    _write_run_record(store_dir, "recent-job", "success")
    store = RunStore(artifacts_dir=store_dir)
    deleted = store.cleanup_old_runs(older_than_days=30)
    assert deleted == []


def test_corrupted_run_json_skipped(store_dir):
    # Write valid record
    _write_run_record(store_dir, "good-job", "success")

    # Write corrupted record
    bad_dir = os.path.join(store_dir, "bad-job")
    os.makedirs(bad_dir)
    with open(os.path.join(bad_dir, "run.json"), "w") as f:
        f.write("not valid json{{{")

    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs()
    assert total == 1
    assert records[0].job_id == "good-job"


def test_directory_without_run_json_skipped(store_dir):
    # Create a directory without run.json
    os.makedirs(os.path.join(store_dir, "orphan-dir"))
    _write_run_record(store_dir, "good-job", "success")

    store = RunStore(artifacts_dir=store_dir)
    records, total = store.list_runs()
    assert total == 1
