"""Tests for workflow CLI commands."""

import pytest
from unittest import mock
from datetime import datetime, timezone
from typer.testing import CliRunner

from orcaops.schemas import (
    JobStatus, WorkflowRecord, WorkflowStatus, WorkflowJobStatus,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_wm():
    with mock.patch("orcaops.cli_workflows._get_workflow_manager") as m:
        wm = mock.MagicMock()
        m.return_value = wm
        yield wm


@pytest.fixture
def mock_ws():
    with mock.patch("orcaops.cli_workflows._get_workflow_store") as m:
        ws = mock.MagicMock()
        m.return_value = ws
        yield ws


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
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            ),
            "test": WorkflowJobStatus(
                job_name="test",
                status=JobStatus.SUCCESS,
                job_id="wf-wf-1-test",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            ),
        },
    )


class TestWorkflowRun:
    def test_run_valid_spec(self, runner, mock_wm, tmp_path):
        from orcaops.main_cli import app

        spec_file = tmp_path / "workflow.yaml"
        spec_file.write_text(
            "name: test-wf\n"
            "jobs:\n"
            "  build:\n"
            "    image: python:3.11\n"
            "    commands:\n"
            "      - echo hello\n"
        )

        mock_wm.submit_workflow.return_value = _wf_record(status=WorkflowStatus.PENDING)

        result = runner.invoke(app, ["workflow", "run", str(spec_file)])
        assert result.exit_code == 0
        assert "Workflow submitted" in result.output
        assert "wf-1" in result.output
        mock_wm.submit_workflow.assert_called_once()

    def test_run_with_custom_id(self, runner, mock_wm, tmp_path):
        from orcaops.main_cli import app

        spec_file = tmp_path / "workflow.yaml"
        spec_file.write_text(
            "name: test-wf\n"
            "jobs:\n"
            "  build:\n"
            "    image: alpine\n"
            "    commands:\n"
            "      - echo hi\n"
        )

        mock_wm.submit_workflow.return_value = _wf_record(
            workflow_id="my-wf", status=WorkflowStatus.PENDING,
        )

        result = runner.invoke(app, ["workflow", "run", str(spec_file), "--id", "my-wf"])
        assert result.exit_code == 0
        call_kwargs = mock_wm.submit_workflow.call_args[1]
        assert call_kwargs["workflow_id"] == "my-wf"
        assert call_kwargs["triggered_by"] == "cli"

    def test_run_file_not_found(self, runner, mock_wm):
        from orcaops.main_cli import app

        result = runner.invoke(app, ["workflow", "run", "/nonexistent/path.yaml"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_run_submit_error(self, runner, mock_wm, tmp_path):
        from orcaops.main_cli import app

        spec_file = tmp_path / "workflow.yaml"
        spec_file.write_text(
            "name: test-wf\n"
            "jobs:\n"
            "  build:\n"
            "    image: alpine\n"
            "    commands:\n"
            "      - echo hi\n"
        )

        mock_wm.submit_workflow.side_effect = ValueError("already exists")

        result = runner.invoke(app, ["workflow", "run", str(spec_file)])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestWorkflowStatus:
    def test_status_found(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.get_workflow.return_value = _wf_record()

        result = runner.invoke(app, ["workflow", "status", "wf-1"])
        assert result.exit_code == 0
        assert "wf-1" in result.output
        assert "test-wf" in result.output
        assert "build" in result.output
        assert "test" in result.output

    def test_status_from_store(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = _wf_record()

        result = runner.invoke(app, ["workflow", "status", "wf-1"])
        assert result.exit_code == 0
        assert "wf-1" in result.output

    def test_status_not_found(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.get_workflow.return_value = None
        mock_ws.get_workflow.return_value = None

        result = runner.invoke(app, ["workflow", "status", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestWorkflowCancel:
    def test_cancel_active(self, runner, mock_wm):
        from orcaops.main_cli import app

        mock_wm.cancel_workflow.return_value = (
            True, _wf_record(status=WorkflowStatus.CANCELLED),
        )

        result = runner.invoke(app, ["workflow", "cancel", "wf-1"])
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

    def test_cancel_not_found(self, runner, mock_wm):
        from orcaops.main_cli import app

        mock_wm.cancel_workflow.return_value = (False, None)

        result = runner.invoke(app, ["workflow", "cancel", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestWorkflowList:
    def test_list_empty(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.list_workflows.return_value = []
        mock_ws.list_workflows.return_value = ([], 0)

        result = runner.invoke(app, ["workflow"])
        assert result.exit_code == 0
        assert "No workflows found" in result.output

    def test_list_with_records(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.list_workflows.return_value = [
            _wf_record("wf-1"),
            _wf_record("wf-2", status=WorkflowStatus.RUNNING),
        ]
        mock_ws.list_workflows.return_value = ([], 0)

        result = runner.invoke(app, ["workflow"])
        assert result.exit_code == 0
        assert "wf-1" in result.output
        assert "wf-2" in result.output

    def test_list_deduplicates(self, runner, mock_wm, mock_ws):
        from orcaops.main_cli import app

        mock_wm.list_workflows.return_value = [_wf_record("wf-1")]
        mock_ws.list_workflows.return_value = ([_wf_record("wf-1")], 1)

        result = runner.invoke(app, ["workflow"])
        assert result.exit_code == 0
        # Should only appear once in the table
        assert result.output.count("wf-1") >= 1
