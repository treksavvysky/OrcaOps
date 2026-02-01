"""Tests for Sprint 03 extended RunStore query filters."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta

from orcaops.run_store import RunStore
from orcaops.schemas import RunRecord, JobStatus


def _write_record(artifacts_dir, job_id, status=JobStatus.SUCCESS, image="python:3.11",
                  duration_secs=30.0, triggered_by=None, tags=None, created_at=None):
    now = created_at or datetime.now(timezone.utc)
    record = RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=now,
        started_at=now - timedelta(seconds=duration_secs),
        finished_at=now,
        triggered_by=triggered_by,
        tags=tags or [],
    )
    job_dir = os.path.join(artifacts_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, "run.json"), "w") as f:
        f.write(record.model_dump_json(indent=2))
    return record


class TestFilterByImage:
    def test_substring_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", image="python:3.11")
            _write_record(tmp, "j2", image="python:3.12")
            _write_record(tmp, "j3", image="node:18")

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(image="python")
            assert total == 2
            assert all("python" in r.image_ref for r in records)

    def test_exact_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", image="python:3.11")
            _write_record(tmp, "j2", image="node:18")

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(image="node:18")
            assert total == 1


class TestFilterByTags:
    def test_single_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", tags=["ci", "python"])
            _write_record(tmp, "j2", tags=["ci"])
            _write_record(tmp, "j3", tags=["manual"])

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(tags=["ci"])
            assert total == 2

    def test_multiple_tags_all_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", tags=["ci", "python"])
            _write_record(tmp, "j2", tags=["ci"])

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(tags=["ci", "python"])
            assert total == 1
            assert records[0].job_id == "j1"


class TestFilterByTriggeredBy:
    def test_exact_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", triggered_by="mcp")
            _write_record(tmp, "j2", triggered_by="api")
            _write_record(tmp, "j3", triggered_by="mcp")

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(triggered_by="mcp")
            assert total == 2


class TestFilterByDateRange:
    def test_after(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", created_at=now - timedelta(days=10))
            _write_record(tmp, "j2", created_at=now - timedelta(days=3))
            _write_record(tmp, "j3", created_at=now - timedelta(days=1))

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(after=now - timedelta(days=5))
            assert total == 2

    def test_before(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", created_at=now - timedelta(days=10))
            _write_record(tmp, "j2", created_at=now - timedelta(days=3))
            _write_record(tmp, "j3", created_at=now - timedelta(days=1))

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(before=now - timedelta(days=5))
            assert total == 1


class TestFilterByDuration:
    def test_min_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", duration_secs=10)
            _write_record(tmp, "j2", duration_secs=30)
            _write_record(tmp, "j3", duration_secs=60)

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(min_duration_seconds=20)
            assert total == 2

    def test_max_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", duration_secs=10)
            _write_record(tmp, "j2", duration_secs=30)
            _write_record(tmp, "j3", duration_secs=60)

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(max_duration_seconds=30)
            assert total == 2


class TestFilterCombined:
    def test_status_and_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", status=JobStatus.SUCCESS, image="python:3.11")
            _write_record(tmp, "j2", status=JobStatus.FAILED, image="python:3.11")
            _write_record(tmp, "j3", status=JobStatus.SUCCESS, image="node:18")

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(status=JobStatus.SUCCESS, image="python")
            assert total == 1
            assert records[0].job_id == "j1"


class TestFilterNoMatches:
    def test_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", image="python:3.11")

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(image="ruby")
            assert total == 0
            assert records == []


class TestExistingFilterRegression:
    def test_status_filter_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_record(tmp, "j1", status=JobStatus.SUCCESS)
            _write_record(tmp, "j2", status=JobStatus.FAILED)
            _write_record(tmp, "j3", status=JobStatus.SUCCESS)

            store = RunStore(artifacts_dir=tmp)
            records, total = store.list_runs(status=JobStatus.SUCCESS)
            assert total == 2
            assert all(r.status == JobStatus.SUCCESS for r in records)
