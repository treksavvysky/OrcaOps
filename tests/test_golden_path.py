import pytest
from unittest.mock import MagicMock, patch, ANY
import os
import json
import shutil
import time
from orcaops.job_runner import JobRunner
from orcaops.schemas import JobSpec, SandboxSpec, JobCommand, JobStatus, CleanupStatus

@pytest.fixture
def output_dir():
    path = "test_artifacts"
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    yield path
    if os.path.exists(path):
        shutil.rmtree(path)

@pytest.fixture
def mock_docker_manager():
    with patch('orcaops.job_runner.DockerManager') as mock:
        dm_instance = mock.return_value
        # Default setup
        dm_instance.run.return_value = "container_123"
        dm_instance.client.api.exec_create.return_value = {'Id': 'exec_123'}
        dm_instance.client.api.exec_start.return_value = [(b"mock output", b"")]
        dm_instance.client.api.exec_inspect.return_value = {'ExitCode': 0}
        yield dm_instance

def test_job_runner_success(output_dir, mock_docker_manager):
    runner = JobRunner(output_dir=output_dir)

    # Setup artifact collection mock
    mock_docker_manager.exec_command.return_value = (0, "/app/test_file.txt")

    def copy_from_side_effect(container_id, src, dest):
        # Simulate artifact landing
        fname = os.path.basename(src)
        with open(os.path.join(dest, fname), "w") as f:
            f.write("artifact content")

    mock_docker_manager.copy_from.side_effect = copy_from_side_effect

    spec = JobSpec(
        job_id="test_job_1",
        sandbox=SandboxSpec(
            image="python:3.9-slim",
            env={"TEST_VAR": "hello"}
        ),
        commands=[
            JobCommand(command="echo hello"),
            JobCommand(command="ls")
        ],
        artifacts=["/test_file.txt"],
        ttl_seconds=3600
    )

    record = runner.run_sandbox_job(spec)

    assert record.status == JobStatus.SUCCESS
    assert record.job_id == "test_job_1"
    assert record.cleanup_status == CleanupStatus.DESTROYED
    assert len(record.steps) == 2
    assert record.steps[0].exit_code == 0

    # Check artifacts
    assert len(record.artifacts) == 1
    assert record.artifacts[0].name == "test_file.txt"

    # Check docker calls
    mock_docker_manager.run.assert_called_once()
    call_args = mock_docker_manager.run.call_args
    assert "labels" in call_args[1]
    assert call_args[1]["labels"]["orcaops.job_id"] == "test_job_1"
    assert call_args[1]["labels"]["orcaops.ttl"] == "3600"

    mock_docker_manager.rm.assert_called_with("container_123", force=True)

def test_job_runner_failure(output_dir, mock_docker_manager):
    runner = JobRunner(output_dir=output_dir)

    # Setup failure on second command
    def exec_inspect_side_effect(exec_id):
        if exec_id == "exec_fail":
            return {'ExitCode': 1}
        return {'ExitCode': 0}

    mock_docker_manager.client.api.exec_inspect.side_effect = exec_inspect_side_effect

    # We need to coordinate create/inspect
    call_count = 0
    def exec_create_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return {'Id': 'exec_fail'}
        return {'Id': 'exec_ok'}

    mock_docker_manager.client.api.exec_create.side_effect = exec_create_side_effect

    spec = JobSpec(
        job_id="test_job_fail",
        sandbox=SandboxSpec(image="python:3.9-slim"),
        commands=[
            JobCommand(command="echo ok"),
            JobCommand(command="exit 1"),
            JobCommand(command="echo skipped")
        ]
    )

    record = runner.run_sandbox_job(spec)

    assert record.status == JobStatus.FAILED
    assert len(record.steps) == 2 # Should stop after failure
    assert record.steps[1].exit_code == 1
    assert record.cleanup_status == CleanupStatus.DESTROYED

def test_job_runner_timeout(output_dir, mock_docker_manager):
    runner = JobRunner(output_dir=output_dir)

    # Mock exec_start to block or yield slowly
    def exec_start_slow(exec_id, stream=True, demux=True):
        time.sleep(1.1) # wait longer than timeout (1s timeout passed below)
        yield (b"done", None)

    mock_docker_manager.client.api.exec_start.side_effect = exec_start_slow

    spec = JobSpec(
        job_id="test_job_timeout",
        sandbox=SandboxSpec(image="python:3.9-slim"),
        commands=[
            JobCommand(command="sleep 2", timeout_seconds=1)
        ]
    )

    record = runner.run_sandbox_job(spec)

    assert record.status == JobStatus.TIMED_OUT
    assert record.steps[0].exit_code == 124
    assert "timed out" in record.steps[0].stderr
    assert record.cleanup_status == CleanupStatus.DESTROYED

def test_job_runner_cleanup_on_crash(output_dir, mock_docker_manager):
    runner = JobRunner(output_dir=output_dir)

    # Simulate crash during run
    mock_docker_manager.run.side_effect = Exception("Docker crash")

    spec = JobSpec(
        job_id="test_job_crash",
        sandbox=SandboxSpec(image="python:3.9-slim"),
        commands=[]
    )

    record = runner.run_sandbox_job(spec)

    assert record.status == JobStatus.FAILED
    assert "Docker crash" in record.error

def test_job_runner_cleanup_after_exec_crash(output_dir, mock_docker_manager):
    runner = JobRunner(output_dir=output_dir)

    mock_docker_manager.client.api.exec_create.side_effect = Exception("Exec crash")

    spec = JobSpec(
        job_id="test_job_exec_crash",
        sandbox=SandboxSpec(image="python:3.9-slim"),
        commands=[JobCommand(command="ls")]
    )

    record = runner.run_sandbox_job(spec)

    assert record.status == JobStatus.FAILED
    assert record.error is None
    assert "Exec crash" in record.steps[0].stderr
    mock_docker_manager.rm.assert_called_with("container_123", force=True)
