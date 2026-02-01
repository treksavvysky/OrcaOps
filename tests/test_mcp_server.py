import json
import os
import pytest
from unittest import mock
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from orcaops.schemas import RunRecord, JobStatus, StepResult, ArtifactMetadata


# ---------------------------------------------------------------------------
# Fixtures — mock the lazy singletons
# ---------------------------------------------------------------------------

def _make_record(
    job_id="test-job",
    status=JobStatus.SUCCESS,
    image="python:3.9",
    steps=None,
    artifacts=None,
):
    return RunRecord(
        job_id=job_id,
        status=status,
        image_ref=image,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        steps=steps or [],
        artifacts=artifacts or [],
    )


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons before each test."""
    import orcaops.mcp_server as mod
    mod._jm = None
    mod._rs = None
    mod._dm = None
    mod._registry = None
    mod._wm = None
    mod._ws = None
    yield


@pytest.fixture
def mock_jm():
    jm = MagicMock()
    with patch("orcaops.mcp_server._jm", jm):
        # Also patch the getter to return our mock
        with patch("orcaops.mcp_server._job_manager", return_value=jm):
            yield jm


@pytest.fixture
def mock_rs():
    rs = MagicMock()
    with patch("orcaops.mcp_server._rs", rs):
        with patch("orcaops.mcp_server._run_store", return_value=rs):
            yield rs


@pytest.fixture
def mock_dm():
    dm = MagicMock()
    with patch("orcaops.mcp_server._dm", dm):
        with patch("orcaops.mcp_server._docker_manager", return_value=dm):
            yield dm


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    with patch("orcaops.mcp_server._registry", reg):
        with patch("orcaops.mcp_server._sandbox_registry", return_value=reg):
            yield reg


def _parse(result: str) -> dict:
    return json.loads(result)


# ===================================================================
# Job Execution Tools
# ===================================================================

class TestRunJob:
    def test_success(self, mock_jm):
        from orcaops.mcp_server import orcaops_run_job

        record_queued = _make_record(job_id="j1", status=JobStatus.QUEUED)
        record_done = _make_record(
            job_id="j1",
            status=JobStatus.SUCCESS,
            steps=[
                StepResult(command="echo hi", exit_code=0, stdout="hi\n", stderr="", duration_seconds=0.1),
            ],
        )
        mock_jm.submit_job.return_value = record_queued
        mock_jm.get_job.return_value = record_done

        result = _parse(orcaops_run_job(
            image="python:3.9",
            commands=["echo hi"],
            job_id="j1",
            timeout=10,
        ))
        assert result["success"] is True
        assert result["status"] == "success"
        assert result["steps"][0]["stdout"] == "hi\n"

    def test_timeout(self, mock_jm):
        from orcaops.mcp_server import orcaops_run_job

        record = _make_record(job_id="j2", status=JobStatus.RUNNING)
        mock_jm.submit_job.return_value = record
        mock_jm.get_job.return_value = record

        with patch("orcaops.mcp_server.time.sleep"):
            with patch("orcaops.mcp_server.time.time") as mock_time:
                # Simulate time progressing past deadline (timeout=10 + 30 grace = 40)
                mock_time.side_effect = [0, 0, 100, 200]
                result = _parse(orcaops_run_job(
                    image="python:3.9",
                    commands=["sleep 999"],
                    job_id="j2",
                    timeout=10,
                ))
        assert result["success"] is False
        assert result["error"]["code"] == "JOB_TIMEOUT"

    def test_validation_error(self, mock_jm):
        from orcaops.mcp_server import orcaops_run_job

        mock_jm.submit_job.side_effect = ValueError("bad image")

        result = _parse(orcaops_run_job(
            image="!!!",
            commands=["echo"],
            timeout=10,
        ))
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestSubmitJob:
    def test_success(self, mock_jm):
        from orcaops.mcp_server import orcaops_submit_job

        record = _make_record(job_id="async-1", status=JobStatus.QUEUED)
        mock_jm.submit_job.return_value = record

        result = _parse(orcaops_submit_job(
            image="python:3.9",
            commands=["echo hi"],
            job_id="async-1",
        ))
        assert result["success"] is True
        assert result["job_id"] == "async-1"
        assert result["status"] == "queued"


class TestGetJobStatus:
    def test_found(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_get_job_status

        record = _make_record()
        mock_jm.get_job.return_value = record

        result = _parse(orcaops_get_job_status("test-job"))
        assert result["success"] is True
        assert result["job_id"] == "test-job"

    def test_found_in_run_store(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_get_job_status

        mock_jm.get_job.return_value = None
        record = _make_record()
        mock_rs.get_run.return_value = record

        result = _parse(orcaops_get_job_status("test-job"))
        assert result["success"] is True

    def test_not_found(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_get_job_status

        mock_jm.get_job.return_value = None
        mock_rs.get_run.return_value = None

        result = _parse(orcaops_get_job_status("nope"))
        assert result["success"] is False
        assert result["error"]["code"] == "JOB_NOT_FOUND"


class TestGetJobLogs:
    def test_with_steps(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_get_job_logs

        record = _make_record(steps=[
            StepResult(command="echo hi", exit_code=0, stdout="hi\n", stderr="", duration_seconds=0.1),
        ])
        mock_jm.get_job.return_value = record

        result = _parse(orcaops_get_job_logs("test-job"))
        assert result["success"] is True
        assert len(result["steps"]) == 1
        assert result["steps"][0]["stdout"] == "hi\n"

    def test_no_steps(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_get_job_logs

        record = _make_record()
        mock_jm.get_job.return_value = record

        result = _parse(orcaops_get_job_logs("test-job"))
        assert result["success"] is True
        assert result["steps"] == []


class TestListJobs:
    def test_list(self, mock_jm):
        from orcaops.mcp_server import orcaops_list_jobs

        mock_jm.list_jobs.return_value = [_make_record(), _make_record(job_id="j2")]

        result = _parse(orcaops_list_jobs())
        assert result["success"] is True
        assert result["count"] == 2

    def test_with_filter(self, mock_jm):
        from orcaops.mcp_server import orcaops_list_jobs

        mock_jm.list_jobs.return_value = [_make_record()]

        result = _parse(orcaops_list_jobs(status="success"))
        assert result["success"] is True
        mock_jm.list_jobs.assert_called_once_with(status=JobStatus.SUCCESS)

    def test_invalid_status(self, mock_jm):
        from orcaops.mcp_server import orcaops_list_jobs

        result = _parse(orcaops_list_jobs(status="invalid"))
        assert result["success"] is False
        assert result["error"]["code"] == "INVALID_STATUS"


class TestCancelJob:
    def test_success(self, mock_jm):
        from orcaops.mcp_server import orcaops_cancel_job

        record = _make_record(status=JobStatus.CANCELLED)
        mock_jm.cancel_job.return_value = (True, record)

        result = _parse(orcaops_cancel_job("test-job"))
        assert result["success"] is True
        assert result["status"] == "cancelled"

    def test_not_found(self, mock_jm):
        from orcaops.mcp_server import orcaops_cancel_job

        mock_jm.cancel_job.return_value = (False, None)

        result = _parse(orcaops_cancel_job("nope"))
        assert result["success"] is False


class TestListArtifacts:
    def test_from_record(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_list_artifacts

        record = _make_record(artifacts=[
            ArtifactMetadata(name="out.txt", path="out.txt", size_bytes=100, sha256="abc123"),
        ])
        mock_jm.get_job.return_value = record

        result = _parse(orcaops_list_artifacts("test-job"))
        assert result["success"] is True
        assert result["count"] == 1
        assert result["artifacts"][0]["name"] == "out.txt"

    def test_from_disk(self, mock_jm, mock_rs):
        from orcaops.mcp_server import orcaops_list_artifacts

        record = _make_record()  # no artifacts in record
        mock_jm.get_job.return_value = record
        mock_jm.list_artifacts.return_value = ["file1.txt", "file2.txt"]

        result = _parse(orcaops_list_artifacts("test-job"))
        assert result["success"] is True
        assert result["count"] == 2


class TestGetArtifact:
    def test_text_file(self, mock_jm, tmp_path):
        from orcaops.mcp_server import orcaops_get_artifact

        job_dir = tmp_path / "test-job"
        job_dir.mkdir()
        (job_dir / "output.txt").write_text("hello world")

        mock_jm.output_dir = str(tmp_path)
        mock_jm.get_artifact.return_value = str(job_dir / "output.txt")

        result = _parse(orcaops_get_artifact("test-job", "output.txt"))
        assert result["success"] is True
        assert result["encoding"] == "text"
        assert result["content"] == "hello world"

    def test_not_found(self, mock_jm):
        from orcaops.mcp_server import orcaops_get_artifact

        mock_jm.get_artifact.return_value = None

        result = _parse(orcaops_get_artifact("test-job", "missing.txt"))
        assert result["success"] is False
        assert result["error"]["code"] == "ARTIFACT_NOT_FOUND"


# ===================================================================
# Sandbox Management Tools
# ===================================================================

class TestListSandboxes:
    def test_list(self, mock_registry):
        from orcaops.mcp_server import orcaops_list_sandboxes

        entry = MagicMock()
        entry.name = "my-app"
        entry.template = "web-dev"
        entry.path = "/tmp/my-app"
        entry.created_at = "2024-01-01"
        entry.status = "stopped"
        mock_registry.list_all.return_value = [entry]

        result = _parse(orcaops_list_sandboxes())
        assert result["success"] is True
        assert result["count"] == 1
        assert result["sandboxes"][0]["name"] == "my-app"


class TestGetSandbox:
    def test_found(self, mock_registry):
        from orcaops.mcp_server import orcaops_get_sandbox

        entry = MagicMock()
        entry.name = "my-app"
        entry.template = "web-dev"
        entry.path = "/tmp/my-app"
        entry.created_at = "2024-01-01"
        entry.status = "stopped"
        mock_registry.get.return_value = entry
        mock_registry.validate_sandbox.return_value = {"exists": True, "has_compose": True, "has_env": False}

        result = _parse(orcaops_get_sandbox("my-app"))
        assert result["success"] is True
        assert result["validation"]["exists"] is True

    def test_not_found(self, mock_registry):
        from orcaops.mcp_server import orcaops_get_sandbox

        mock_registry.get.return_value = None

        result = _parse(orcaops_get_sandbox("nope"))
        assert result["success"] is False
        assert result["error"]["code"] == "SANDBOX_NOT_FOUND"


class TestCreateSandbox:
    @patch("orcaops.mcp_server.TemplateManager", create=True)
    @patch("orcaops.mcp_server.SandboxTemplates", create=True)
    def test_success(self, mock_st, mock_tm, mock_registry):
        from orcaops.mcp_server import orcaops_create_sandbox

        # Patch the imports inside the function
        with patch("orcaops.sandbox_templates_simple.TemplateManager") as MockTM, \
             patch("orcaops.sandbox_templates_simple.SandboxTemplates") as MockST:
            MockTM.validate_template_name.return_value = True
            MockTM.create_sandbox_from_template.return_value = True
            mock_registry.exists.return_value = False
            entry = MagicMock()
            entry.name = "new-app"
            entry.template = "web-dev"
            entry.path = "/tmp/new-app"
            entry.created_at = "2024-01-01"
            mock_registry.register.return_value = entry

            result = _parse(orcaops_create_sandbox("web-dev", "new-app"))
            assert result["success"] is True
            assert result["name"] == "new-app"


class TestListTemplates:
    def test_list(self):
        from orcaops.mcp_server import orcaops_list_templates

        with patch("orcaops.sandbox_templates_simple.SandboxTemplates") as MockST:
            MockST.get_templates.return_value = {
                "web-dev": {
                    "description": "Web development",
                    "category": "Development",
                    "services": {"nginx": {}, "node": {}},
                },
            }
            result = _parse(orcaops_list_templates())
            assert result["success"] is True
            assert result["count"] == 1


class TestGetTemplate:
    def test_found(self):
        from orcaops.mcp_server import orcaops_get_template

        with patch("orcaops.sandbox_templates_simple.TemplateManager") as MockTM:
            MockTM.get_template_info.return_value = {
                "description": "Web dev",
                "category": "Dev",
                "services": {"nginx": {}},
            }
            result = _parse(orcaops_get_template("web-dev"))
            assert result["success"] is True
            assert result["name"] == "web-dev"

    def test_not_found(self):
        from orcaops.mcp_server import orcaops_get_template

        with patch("orcaops.sandbox_templates_simple.TemplateManager") as MockTM:
            MockTM.get_template_info.return_value = None
            result = _parse(orcaops_get_template("nope"))
            assert result["success"] is False
            assert result["error"]["code"] == "TEMPLATE_NOT_FOUND"


# ===================================================================
# Container Management Tools
# ===================================================================

class TestListContainers:
    def test_list(self, mock_dm):
        from orcaops.mcp_server import orcaops_list_containers

        c = MagicMock()
        c.short_id = "abc123"
        c.name = "test-container"
        c.image.tags = ["python:3.9"]
        c.status = "running"
        mock_dm.list_running_containers.return_value = [c]

        result = _parse(orcaops_list_containers())
        assert result["success"] is True
        assert result["count"] == 1
        assert result["containers"][0]["id"] == "abc123"


class TestGetContainerLogs:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_get_container_logs

        mock_dm.logs.return_value = "hello world\n"

        result = _parse(orcaops_get_container_logs("abc123"))
        assert result["success"] is True
        assert result["logs"] == "hello world\n"

    def test_not_found(self, mock_dm):
        from orcaops.mcp_server import orcaops_get_container_logs

        mock_dm.logs.side_effect = Exception("404 not found")

        result = _parse(orcaops_get_container_logs("nope"))
        assert result["success"] is False
        assert result["error"]["code"] == "CONTAINER_NOT_FOUND"


class TestInspectContainer:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_inspect_container

        mock_dm.inspect.return_value = {
            "Name": "/test",
            "Config": {"Image": "python:3.9"},
            "State": {"Status": "running"},
            "NetworkSettings": {"Networks": {}},
            "Created": "2024-01-01T00:00:00Z",
        }

        result = _parse(orcaops_inspect_container("abc123"))
        assert result["success"] is True
        assert result["name"] == "/test"


class TestStopContainer:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_stop_container

        mock_dm.stop.return_value = True

        result = _parse(orcaops_stop_container("abc123"))
        assert result["success"] is True

    def test_failure(self, mock_dm):
        from orcaops.mcp_server import orcaops_stop_container

        mock_dm.stop.return_value = False

        result = _parse(orcaops_stop_container("abc123"))
        assert result["success"] is False


class TestRemoveContainer:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_remove_container

        mock_dm.rm.return_value = True

        result = _parse(orcaops_remove_container("abc123"))
        assert result["success"] is True

    def test_failure(self, mock_dm):
        from orcaops.mcp_server import orcaops_remove_container

        mock_dm.rm.return_value = False

        result = _parse(orcaops_remove_container("abc123"))
        assert result["success"] is False
        assert result["error"]["code"] == "REMOVE_FAILED"


# ===================================================================
# System Tools
# ===================================================================

class TestSystemInfo:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_system_info

        mock_dm.client.info.return_value = {
            "ServerVersion": "24.0.0",
            "Containers": 5,
            "ContainersRunning": 2,
            "ContainersPaused": 0,
            "ContainersStopped": 3,
            "Images": 10,
            "OperatingSystem": "Ubuntu 22.04",
            "KernelVersion": "5.15.0",
            "MemTotal": 8_000_000_000,
            "NCPU": 4,
        }

        result = _parse(orcaops_system_info())
        assert result["success"] is True
        assert result["docker"]["version"] == "24.0.0"
        assert result["docker"]["cpus"] == 4


class TestCleanupContainers:
    def test_success(self, mock_dm):
        from orcaops.mcp_server import orcaops_cleanup_containers

        mock_dm.cleanup.return_value = {
            "stopped_containers": ["a", "b"],
            "removed_containers": ["a", "b"],
            "errors": [],
        }

        result = _parse(orcaops_cleanup_containers())
        assert result["success"] is True
        assert len(result["stopped"]) == 2


# ===================================================================
# Run History Tools
# ===================================================================

class TestListRuns:
    def test_list(self, mock_rs):
        from orcaops.mcp_server import orcaops_list_runs

        mock_rs.list_runs.return_value = ([_make_record()], 1)

        result = _parse(orcaops_list_runs())
        assert result["success"] is True
        assert result["total"] == 1

    def test_invalid_status(self, mock_rs):
        from orcaops.mcp_server import orcaops_list_runs

        result = _parse(orcaops_list_runs(status="bogus"))
        assert result["success"] is False


class TestGetRun:
    def test_found(self, mock_rs):
        from orcaops.mcp_server import orcaops_get_run

        mock_rs.get_run.return_value = _make_record()

        result = _parse(orcaops_get_run("test-job"))
        assert result["success"] is True

    def test_not_found(self, mock_rs):
        from orcaops.mcp_server import orcaops_get_run

        mock_rs.get_run.return_value = None

        result = _parse(orcaops_get_run("nope"))
        assert result["success"] is False


class TestDeleteRun:
    def test_success(self, mock_rs):
        from orcaops.mcp_server import orcaops_delete_run

        mock_rs.delete_run.return_value = True

        result = _parse(orcaops_delete_run("test-job"))
        assert result["success"] is True

    def test_not_found(self, mock_rs):
        from orcaops.mcp_server import orcaops_delete_run

        mock_rs.delete_run.return_value = False

        result = _parse(orcaops_delete_run("nope"))
        assert result["success"] is False


class TestCleanupRuns:
    def test_success(self, mock_rs):
        from orcaops.mcp_server import orcaops_cleanup_runs

        mock_rs.cleanup_old_runs.return_value = ["old-1", "old-2"]

        result = _parse(orcaops_cleanup_runs(older_than_days=7))
        assert result["success"] is True
        assert result["deleted_count"] == 2
