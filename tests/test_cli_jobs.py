import pytest
from unittest import mock
from typer.testing import CliRunner
from datetime import datetime, timezone

from orcaops.schemas import RunRecord, JobStatus, StepResult, ArtifactMetadata


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_jm():
    with mock.patch("orcaops.cli_jobs._get_job_manager") as m:
        jm = mock.MagicMock()
        m.return_value = jm
        yield jm


@pytest.fixture
def mock_rs():
    with mock.patch("orcaops.cli_jobs._get_run_store") as m:
        rs = mock.MagicMock()
        m.return_value = rs
        yield rs


def _make_record(job_id="test-job", status=JobStatus.SUCCESS, image="python:3.9"):
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        steps=[],
        artifacts=[],
    )


def test_run_basic(runner, mock_jm):
    from orcaops.main_cli import app
    record = _make_record(job_id="new-job", status=JobStatus.QUEUED)
    mock_jm.submit_job.return_value = record

    result = runner.invoke(app, ["run", "python:3.9", "echo", "hello"])
    assert result.exit_code == 0
    assert "new-job" in result.output
    mock_jm.submit_job.assert_called_once()


def test_run_no_command_no_spec(runner, mock_jm):
    from orcaops.main_cli import app
    result = runner.invoke(app, ["run", "python:3.9"])
    assert result.exit_code == 1


def test_run_with_env_and_artifact(runner, mock_jm):
    from orcaops.main_cli import app
    record = _make_record(job_id="env-job", status=JobStatus.QUEUED)
    mock_jm.submit_job.return_value = record

    result = runner.invoke(app, [
        "run", "python:3.9", "echo", "test",
        "--env", "FOO=bar",
        "--artifact", "/app/output.txt",
        "--id", "env-job",
    ])
    assert result.exit_code == 0
    assert "env-job" in result.output

    call_args = mock_jm.submit_job.call_args[0][0]
    assert call_args.sandbox.env == {"FOO": "bar"}
    assert call_args.artifacts == ["/app/output.txt"]
    assert call_args.job_id == "env-job"


def test_run_submit_error(runner, mock_jm):
    from orcaops.main_cli import app
    mock_jm.submit_job.side_effect = ValueError("already exists")

    result = runner.invoke(app, ["run", "python:3.9", "echo", "hello"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_jobs_list(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    mock_jm.list_jobs.return_value = [_make_record()]
    mock_rs.list_runs.return_value = ([], 0)

    result = runner.invoke(app, ["jobs"])
    assert result.exit_code == 0
    assert "test-job" in result.output


def test_jobs_list_empty(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    mock_jm.list_jobs.return_value = []
    mock_rs.list_runs.return_value = ([], 0)

    result = runner.invoke(app, ["jobs"])
    assert result.exit_code == 0
    assert "No jobs found" in result.output


def test_jobs_status(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    record = _make_record()
    mock_jm.get_job.return_value = record

    result = runner.invoke(app, ["jobs", "status", "test-job"])
    assert result.exit_code == 0
    assert "test-job" in result.output


def test_jobs_status_not_found(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    mock_jm.get_job.return_value = None
    mock_rs.get_run.return_value = None

    result = runner.invoke(app, ["jobs", "status", "nonexistent"])
    assert result.exit_code == 1


def test_jobs_logs_with_steps(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    record = _make_record()
    record.steps = [
        StepResult(command="echo hello", exit_code=0, stdout="hello\n", stderr="", duration_seconds=0.1),
    ]
    mock_jm.get_job.return_value = record

    result = runner.invoke(app, ["jobs", "logs", "test-job"])
    assert result.exit_code == 0
    assert "echo hello" in result.output
    assert "hello" in result.output


def test_jobs_cancel(runner, mock_jm):
    from orcaops.main_cli import app
    record = _make_record(status=JobStatus.CANCELLED)
    mock_jm.cancel_job.return_value = (True, record)

    result = runner.invoke(app, ["jobs", "cancel", "test-job"])
    assert result.exit_code == 0
    assert "cancelled" in result.output.lower()


def test_jobs_cancel_not_found(runner, mock_jm):
    from orcaops.main_cli import app
    mock_jm.cancel_job.return_value = (False, None)

    result = runner.invoke(app, ["jobs", "cancel", "nonexistent"])
    assert result.exit_code == 1


def test_jobs_artifacts(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    record = _make_record()
    record.artifacts = [
        ArtifactMetadata(name="output.txt", path="output.txt", size_bytes=1024, sha256="abc123def456"),
    ]
    mock_jm.get_job.return_value = record

    result = runner.invoke(app, ["jobs", "artifacts", "test-job"])
    assert result.exit_code == 0
    assert "output.txt" in result.output


def test_jobs_artifacts_not_found(runner, mock_jm, mock_rs):
    from orcaops.main_cli import app
    mock_jm.get_job.return_value = None
    mock_rs.get_run.return_value = None

    result = runner.invoke(app, ["jobs", "artifacts", "nonexistent"])
    assert result.exit_code == 1


def test_runs_cleanup(runner, mock_rs):
    from orcaops.main_cli import app
    mock_rs.cleanup_old_runs.return_value = ["old-1", "old-2"]

    result = runner.invoke(app, ["runs-cleanup", "--older-than", "7d"])
    assert result.exit_code == 0
    assert "2" in result.output
    mock_rs.cleanup_old_runs.assert_called_once_with(older_than_days=7)


def test_runs_cleanup_none(runner, mock_rs):
    from orcaops.main_cli import app
    mock_rs.cleanup_old_runs.return_value = []

    result = runner.invoke(app, ["runs-cleanup"])
    assert result.exit_code == 0
    assert "No runs" in result.output
