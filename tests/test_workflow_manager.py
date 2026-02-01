"""Tests for workflow manager and workflow store."""

import json
import os
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from orcaops.schemas import (
    WorkflowSpec, WorkflowRecord, WorkflowStatus, WorkflowJobStatus, JobStatus,
)
from orcaops.workflow_manager import WorkflowManager
from orcaops.workflow_store import WorkflowStore
from orcaops.workflow_schema import parse_workflow_spec


def _simple_spec():
    return parse_workflow_spec({
        "name": "test-wf",
        "jobs": {
            "build": {"image": "alpine", "commands": ["echo hello"]},
        },
    })


def _completed_record(workflow_id="wf-1", status=WorkflowStatus.SUCCESS):
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
            ),
        },
    )


class TestWorkflowManager:
    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_submit_returns_pending_record(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = _completed_record()

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        spec = _simple_spec()
        record = wm.submit_workflow(spec, workflow_id="wf-test-1")

        assert record.workflow_id == "wf-test-1"
        assert record.status == WorkflowStatus.PENDING
        assert record.spec_name == "test-wf"

        # Wait for thread to complete
        time.sleep(0.5)
        wm.shutdown(timeout=5)

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_duplicate_id_raises(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = _completed_record()

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        spec = _simple_spec()
        wm.submit_workflow(spec, workflow_id="wf-dup")

        with pytest.raises(ValueError, match="already exists"):
            wm.submit_workflow(spec, workflow_id="wf-dup")

        wm.shutdown(timeout=5)

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_get_workflow_from_memory(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        # Block until we check memory
        barrier = threading.Event()
        def slow_run(*args, **kwargs):
            barrier.wait(timeout=5)
            return _completed_record("wf-mem")
        mock_runner.run.side_effect = slow_run

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        wm.submit_workflow(_simple_spec(), workflow_id="wf-mem")
        time.sleep(0.1)

        # Should find it in memory while running
        record = wm.get_workflow("wf-mem")
        assert record is not None
        assert record.workflow_id == "wf-mem"

        barrier.set()
        wm.shutdown(timeout=5)

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_get_workflow_from_disk(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = _completed_record("wf-disk")

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        wm.submit_workflow(_simple_spec(), workflow_id="wf-disk")
        time.sleep(0.5)
        wm.shutdown(timeout=5)

        # After eviction, should load from disk
        record = wm.get_workflow("wf-disk")
        assert record is not None
        assert record.workflow_id == "wf-disk"

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_get_workflow_not_found(self, MockJM, MockRunner, tmp_path):
        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        assert wm.get_workflow("nonexistent") is None

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_list_workflows(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        barrier = threading.Event()
        def slow_run(*args, **kwargs):
            barrier.wait(timeout=5)
            return _completed_record(args[1])
        mock_runner.run.side_effect = slow_run

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        wm.submit_workflow(_simple_spec(), workflow_id="wf-list-1")
        wm.submit_workflow(_simple_spec(), workflow_id="wf-list-2")
        time.sleep(0.1)

        records = wm.list_workflows()
        assert len(records) == 2

        barrier.set()
        wm.shutdown(timeout=5)

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_cancel_workflow(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        barrier = threading.Event()
        def slow_run(*args, **kwargs):
            barrier.wait(timeout=5)
            return _completed_record(args[1], WorkflowStatus.CANCELLED)
        mock_runner.run.side_effect = slow_run

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        wm.submit_workflow(_simple_spec(), workflow_id="wf-cancel")
        time.sleep(0.1)

        cancelled, record = wm.cancel_workflow("wf-cancel")
        assert cancelled is True
        assert record.status == WorkflowStatus.CANCELLED

        barrier.set()
        wm.shutdown(timeout=5)

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_cancel_not_found(self, MockJM, MockRunner, tmp_path):
        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        cancelled, record = wm.cancel_workflow("nonexistent")
        assert cancelled is False
        assert record is None

    @patch("orcaops.workflow_manager.WorkflowRunner")
    @patch("orcaops.workflow_manager.JobManager")
    def test_persists_to_disk(self, MockJM, MockRunner, tmp_path):
        mock_runner = MockRunner.return_value
        mock_runner.run.return_value = _completed_record("wf-persist")

        wm = WorkflowManager(
            job_manager=MockJM.return_value,
            workflows_dir=str(tmp_path),
        )
        wm.submit_workflow(_simple_spec(), workflow_id="wf-persist")
        time.sleep(0.5)
        wm.shutdown(timeout=5)

        # Verify file on disk
        wf_path = os.path.join(str(tmp_path), "wf-persist", "workflow.json")
        assert os.path.isfile(wf_path)

        with open(wf_path) as f:
            data = json.load(f)
        assert data["workflow_id"] == "wf-persist"
        assert data["status"] == "success"


class TestWorkflowStore:
    def test_empty_store(self, tmp_path):
        store = WorkflowStore(str(tmp_path))
        records, total = store.list_workflows()
        assert records == []
        assert total == 0

    def test_get_workflow(self, tmp_path):
        # Write a workflow record to disk
        wf_dir = os.path.join(str(tmp_path), "wf-store-1")
        os.makedirs(wf_dir)
        record = _completed_record("wf-store-1")
        with open(os.path.join(wf_dir, "workflow.json"), "w") as f:
            f.write(record.model_dump_json(indent=2))

        store = WorkflowStore(str(tmp_path))
        loaded = store.get_workflow("wf-store-1")
        assert loaded is not None
        assert loaded.workflow_id == "wf-store-1"
        assert loaded.status == WorkflowStatus.SUCCESS

    def test_get_workflow_not_found(self, tmp_path):
        store = WorkflowStore(str(tmp_path))
        assert store.get_workflow("nonexistent") is None

    def test_list_with_status_filter(self, tmp_path):
        for i, status in enumerate([WorkflowStatus.SUCCESS, WorkflowStatus.FAILED]):
            wf_dir = os.path.join(str(tmp_path), f"wf-{i}")
            os.makedirs(wf_dir)
            record = _completed_record(f"wf-{i}", status)
            with open(os.path.join(wf_dir, "workflow.json"), "w") as f:
                f.write(record.model_dump_json(indent=2))

        store = WorkflowStore(str(tmp_path))
        records, total = store.list_workflows(status=WorkflowStatus.SUCCESS)
        assert total == 1
        assert records[0].status == WorkflowStatus.SUCCESS

    def test_delete_workflow(self, tmp_path):
        wf_dir = os.path.join(str(tmp_path), "wf-del")
        os.makedirs(wf_dir)
        with open(os.path.join(wf_dir, "workflow.json"), "w") as f:
            f.write(_completed_record("wf-del").model_dump_json())

        store = WorkflowStore(str(tmp_path))
        assert store.delete_workflow("wf-del") is True
        assert not os.path.isdir(wf_dir)
        assert store.delete_workflow("wf-del") is False

    def test_pagination(self, tmp_path):
        for i in range(5):
            wf_dir = os.path.join(str(tmp_path), f"wf-page-{i}")
            os.makedirs(wf_dir)
            record = _completed_record(f"wf-page-{i}")
            with open(os.path.join(wf_dir, "workflow.json"), "w") as f:
                f.write(record.model_dump_json(indent=2))

        store = WorkflowStore(str(tmp_path))
        records, total = store.list_workflows(limit=2, offset=0)
        assert total == 5
        assert len(records) == 2

    def test_nonexistent_dir(self):
        store = WorkflowStore("/nonexistent/path")
        records, total = store.list_workflows()
        assert records == []
        assert total == 0
