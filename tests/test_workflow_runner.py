"""Tests for workflow runner DAG execution engine."""

import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from orcaops.schemas import (
    JobStatus, RunRecord, WorkflowStatus, WorkflowSpec, WorkflowJob,
)
from orcaops.workflow_runner import WorkflowRunner
from orcaops.workflow_schema import parse_workflow_spec


def _mock_job_manager(job_results=None):
    """Create a mock JobManager that returns immediate results."""
    jm = MagicMock()
    _submitted = {}
    _results = job_results or {}

    def submit_job(spec):
        record = RunRecord(
            job_id=spec.job_id,
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        _submitted[spec.job_id] = spec
        return record

    def get_job(job_id):
        status = _results.get(job_id, JobStatus.SUCCESS)
        # Check if any prefix matches (for dynamic workflow job IDs)
        if status == JobStatus.SUCCESS:
            for pattern, s in _results.items():
                if pattern in job_id:
                    status = s
                    break
        return RunRecord(
            job_id=job_id,
            status=status,
            created_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )

    jm.submit_job.side_effect = submit_job
    jm.get_job.side_effect = get_job
    jm.cancel_job.return_value = (True, None)
    jm._submitted = _submitted
    return jm


def _spec(jobs_dict):
    """Create a WorkflowSpec from a dict of job definitions."""
    return parse_workflow_spec({"name": "test-wf", "jobs": jobs_dict})


class TestLinearWorkflow:
    def test_linear_chain_all_succeed(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"], "requires": ["a"]},
            "c": {"image": "alpine", "commands": ["echo c"], "requires": ["b"]},
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-1", cancel)
        assert record.status == WorkflowStatus.SUCCESS
        assert all(js.status == JobStatus.SUCCESS for js in record.job_statuses.values())
        # All 3 jobs should have been submitted
        assert jm.submit_job.call_count == 3

    def test_execution_order_preserved(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"], "requires": ["a"]},
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-2", cancel)
        # First call should be job a, second should be job b
        calls = jm.submit_job.call_args_list
        assert "a" in calls[0][0][0].job_id
        assert "b" in calls[1][0][0].job_id


class TestParallelWorkflow:
    def test_parallel_jobs_both_run(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"]},
            "c": {"image": "alpine", "commands": ["echo c"], "requires": ["a", "b"]},
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-3", cancel)
        assert record.status == WorkflowStatus.SUCCESS
        assert jm.submit_job.call_count == 3


class TestFailurePropagation:
    def test_failure_cancels_downstream(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"], "requires": ["a"]},
            "c": {"image": "alpine", "commands": ["echo c"], "requires": ["b"]},
        })

        def get_job(job_id):
            if "b" in job_id:
                return RunRecord(
                    job_id=job_id, status=JobStatus.FAILED,
                    created_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    error="Command failed",
                )
            return RunRecord(
                job_id=job_id, status=JobStatus.SUCCESS,
                created_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )

        jm = _mock_job_manager()
        jm.get_job.side_effect = get_job
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-4", cancel)
        assert record.job_statuses["a"].status == JobStatus.SUCCESS
        assert record.job_statuses["b"].status == JobStatus.FAILED
        assert record.job_statuses["c"].status == JobStatus.CANCELLED
        assert record.job_statuses["c"].error == "Skipped: upstream failure"
        assert record.status == WorkflowStatus.PARTIAL

    def test_all_fail_gives_failed_status(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
        })

        def get_job(job_id):
            return RunRecord(
                job_id=job_id, status=JobStatus.FAILED,
                created_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )

        jm = _mock_job_manager()
        jm.get_job.side_effect = get_job
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-5", cancel)
        assert record.status == WorkflowStatus.FAILED


class TestConditions:
    def test_if_condition_false_skips_job(self):
        spec = _spec({
            "build": {"image": "alpine", "commands": ["echo"]},
            "deploy": {
                "image": "alpine", "commands": ["echo"],
                "requires": ["build"],
                "if": "${{ env.DEPLOY == 'true' }}",
            },
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-6", cancel)
        assert record.job_statuses["build"].status == JobStatus.SUCCESS
        assert record.job_statuses["deploy"].status == JobStatus.CANCELLED
        assert "condition not met" in record.job_statuses["deploy"].error

    def test_on_complete_always_runs_after_failure(self):
        spec = _spec({
            "build": {"image": "alpine", "commands": ["echo"]},
            "notify": {
                "image": "alpine", "commands": ["echo"],
                "requires": ["build"],
                "on_complete": "always",
            },
        })

        def get_job(job_id):
            if "build" in job_id:
                return RunRecord(
                    job_id=job_id, status=JobStatus.FAILED,
                    created_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
            return RunRecord(
                job_id=job_id, status=JobStatus.SUCCESS,
                created_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )

        jm = _mock_job_manager()
        jm.get_job.side_effect = get_job
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-7", cancel)
        assert record.job_statuses["build"].status == JobStatus.FAILED
        assert record.job_statuses["notify"].status == JobStatus.SUCCESS

    def test_on_complete_failure_runs_when_dep_fails(self):
        spec = _spec({
            "build": {"image": "alpine", "commands": ["echo"]},
            "rollback": {
                "image": "alpine", "commands": ["echo"],
                "requires": ["build"],
                "on_complete": "failure",
            },
        })

        def get_job(job_id):
            if "build" in job_id:
                return RunRecord(
                    job_id=job_id, status=JobStatus.FAILED,
                    created_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
            return RunRecord(
                job_id=job_id, status=JobStatus.SUCCESS,
                created_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )

        jm = _mock_job_manager()
        jm.get_job.side_effect = get_job
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-8", cancel)
        assert record.job_statuses["build"].status == JobStatus.FAILED
        assert record.job_statuses["rollback"].status == JobStatus.SUCCESS

    def test_on_complete_failure_skips_when_dep_succeeds(self):
        spec = _spec({
            "build": {"image": "alpine", "commands": ["echo"]},
            "rollback": {
                "image": "alpine", "commands": ["echo"],
                "requires": ["build"],
                "on_complete": "failure",
            },
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-9", cancel)
        assert record.job_statuses["build"].status == JobStatus.SUCCESS
        assert record.job_statuses["rollback"].status == JobStatus.CANCELLED


class TestCancellation:
    def test_cancel_event_stops_workflow(self):
        spec = _spec({
            "a": {"image": "alpine", "commands": ["echo"]},
            "b": {"image": "alpine", "commands": ["echo"], "requires": ["a"]},
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()
        cancel.set()  # Pre-cancel

        record = runner.run(spec, "wf-10", cancel)
        assert record.status == WorkflowStatus.CANCELLED


class TestMatrixExpansion:
    def test_matrix_creates_multiple_jobs(self):
        spec = _spec({
            "test": {
                "image": "python:3.11",
                "commands": ["pytest"],
                "matrix": {
                    "python": ["3.9", "3.10"],
                },
            },
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        record = runner.run(spec, "wf-11", cancel)
        # 2 matrix variants should be submitted
        assert jm.submit_job.call_count == 2
        assert record.status == WorkflowStatus.SUCCESS


class TestContextPropagation:
    def test_job_spec_has_workflow_context(self):
        spec = _spec({
            "build": {"image": "python:3.11", "commands": ["make"]},
        })
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        runner.run(spec, "wf-12", cancel)
        submitted_spec = jm.submit_job.call_args[0][0]
        assert submitted_spec.triggered_by == "workflow"
        assert submitted_spec.parent_job_id == "wf-12"
        assert "workflow" in submitted_spec.tags
        assert "test-wf" in submitted_spec.tags

    def test_env_merged_from_workflow_and_job(self):
        data = {
            "name": "test-wf",
            "env": {"GLOBAL": "yes"},
            "jobs": {
                "build": {
                    "image": "alpine",
                    "commands": ["echo"],
                    "env": {"LOCAL": "yes"},
                },
            },
        }
        spec = parse_workflow_spec(data)
        jm = _mock_job_manager()
        runner = WorkflowRunner(jm)
        cancel = threading.Event()

        runner.run(spec, "wf-13", cancel)
        submitted_spec = jm.submit_job.call_args[0][0]
        assert submitted_spec.sandbox.env["GLOBAL"] == "yes"
        assert submitted_spec.sandbox.env["LOCAL"] == "yes"
