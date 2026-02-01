"""Tests for Sprint 03 observability instrumentation in JobRunner."""

import os
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

from orcaops.job_runner import JobRunner
from orcaops.schemas import (
    JobSpec, SandboxSpec, JobCommand, JobStatus,
    ResourceUsage, EnvironmentCapture,
)


def _make_spec(**overrides):
    defaults = dict(
        job_id="obs-test-1",
        sandbox=SandboxSpec(image="python:3.11"),
        commands=[JobCommand(command="echo hello")],
        ttl_seconds=60,
    )
    defaults.update(overrides)
    return JobSpec(**defaults)


class TestContextPropagation:
    """Verify context fields from JobSpec propagate to RunRecord."""

    @patch("orcaops.job_runner.DockerManager")
    def test_triggered_by_propagated(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.client.containers.get.return_value = _mock_container()
        dm.client.version.return_value = {"Version": "24.0"}
        dm.rm.return_value = True

        runner = JobRunner(output_dir="/tmp/obs-test")
        spec = _make_spec(
            triggered_by="mcp",
            intent="Run tests for PR #42",
            parent_job_id="parent-xyz",
            tags=["ci", "python"],
            metadata={"pr": 42},
        )
        record = runner.run_sandbox_job(spec)

        assert record.triggered_by == "mcp"
        assert record.intent == "Run tests for PR #42"
        assert record.parent_job_id == "parent-xyz"
        assert record.tags == ["ci", "python"]
        assert record.metadata == {"pr": 42}

    @patch("orcaops.job_runner.DockerManager")
    def test_context_defaults_when_not_provided(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.client.containers.get.return_value = _mock_container()
        dm.client.version.return_value = {"Version": "24.0"}
        dm.rm.return_value = True

        runner = JobRunner(output_dir="/tmp/obs-test")
        spec = _make_spec()
        record = runner.run_sandbox_job(spec)

        assert record.triggered_by is None
        assert record.intent is None
        assert record.tags == []
        assert record.metadata == {}


class TestResourceUsageCollection:

    @patch("orcaops.job_runner.DockerManager")
    def test_resource_usage_collected(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.rm.return_value = True

        container_mock = _mock_container(stats={
            "cpu_stats": {"cpu_usage": {"total_usage": 2_500_000_000}},
            "memory_stats": {"max_usage": 268435456},
            "networks": {"eth0": {"rx_bytes": 1024, "tx_bytes": 2048}},
            "blkio_stats": {"io_service_bytes_recursive": [
                {"op": "read", "value": 4096},
                {"op": "write", "value": 8192},
            ]},
        })
        dm.client.containers.get.return_value = container_mock
        dm.client.version.return_value = {"Version": "24.0"}

        runner = JobRunner(output_dir="/tmp/obs-test")
        record = runner.run_sandbox_job(_make_spec())

        assert record.resource_usage is not None
        assert record.resource_usage.cpu_seconds == 2.5
        assert record.resource_usage.memory_peak_mb == 256.0
        assert record.resource_usage.network_rx_bytes == 1024
        assert record.resource_usage.network_tx_bytes == 2048
        assert record.resource_usage.disk_read_bytes == 4096
        assert record.resource_usage.disk_write_bytes == 8192

    @patch("orcaops.job_runner.DockerManager")
    def test_resource_usage_fails_gracefully(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.rm.return_value = True

        container_mock = MagicMock()
        container_mock.stats.side_effect = Exception("Docker API error")
        container_mock.image.attrs = {"RepoDigests": []}
        container_mock.attrs = {"Config": {"Env": []}, "HostConfig": {}}
        dm.client.containers.get.return_value = container_mock
        dm.client.version.return_value = {"Version": "24.0"}

        runner = JobRunner(output_dir="/tmp/obs-test")
        record = runner.run_sandbox_job(_make_spec())

        assert record.resource_usage is not None
        assert record.resource_usage.cpu_seconds == 0.0
        assert record.resource_usage.memory_peak_mb == 0.0


class TestEnvironmentCapture:

    @patch("orcaops.job_runner.DockerManager")
    def test_environment_captured(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.rm.return_value = True

        container_mock = _mock_container(
            env=["PATH=/usr/bin", "HOME=/root"],
            digests=["python@sha256:abc123"],
            host_config={"Memory": 536870912, "NanoCpus": 2000000000},
        )
        dm.client.containers.get.return_value = container_mock
        dm.client.version.return_value = {"Version": "24.0.7"}

        runner = JobRunner(output_dir="/tmp/obs-test")
        record = runner.run_sandbox_job(_make_spec())

        assert record.environment is not None
        assert record.environment.image_digest == "python@sha256:abc123"
        assert record.environment.docker_version == "24.0.7"
        assert record.environment.env_vars["PATH"] == "/usr/bin"
        assert record.environment.resource_limits["memory_bytes"] == 536870912

    @patch("orcaops.job_runner.DockerManager")
    def test_sensitive_vars_redacted(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.rm.return_value = True

        container_mock = _mock_container(
            env=[
                "PATH=/usr/bin",
                "DB_PASSWORD=supersecret",
                "API_KEY=abc123",
                "AWS_SECRET_ACCESS_KEY=hidden",
                "MY_TOKEN=tok123",
            ],
        )
        dm.client.containers.get.return_value = container_mock
        dm.client.version.return_value = {"Version": "24.0"}

        runner = JobRunner(output_dir="/tmp/obs-test")
        record = runner.run_sandbox_job(_make_spec())

        env = record.environment.env_vars
        assert env["PATH"] == "/usr/bin"
        assert env["DB_PASSWORD"] == "***REDACTED***"
        assert env["API_KEY"] == "***REDACTED***"
        assert env["AWS_SECRET_ACCESS_KEY"] == "***REDACTED***"
        assert env["MY_TOKEN"] == "***REDACTED***"

    @patch("orcaops.job_runner.DockerManager")
    def test_environment_capture_fails_gracefully(self, MockDM):
        dm = MockDM.return_value
        dm.run.return_value = "cid-123"
        dm.client.api.exec_create.return_value = {"Id": "exec-1"}
        dm.client.api.exec_start.return_value = iter([])
        dm.client.api.exec_inspect.return_value = {"ExitCode": 0}
        dm.rm.return_value = True

        dm.client.containers.get.side_effect = Exception("Container not found")

        runner = JobRunner(output_dir="/tmp/obs-test")
        record = runner.run_sandbox_job(_make_spec())

        # Both should fall back to defaults
        assert record.environment is not None
        assert record.environment.image_digest is None
        assert record.resource_usage is not None
        assert record.resource_usage.cpu_seconds == 0.0


def _mock_container(stats=None, env=None, digests=None, host_config=None):
    """Create a mock container with configurable attributes."""
    container = MagicMock()
    container.attrs = {
        "Config": {"Env": env or []},
        "HostConfig": host_config or {},
    }
    container.image.attrs = {"RepoDigests": digests or []}
    container.stats.return_value = stats or {
        "cpu_stats": {"cpu_usage": {"total_usage": 0}},
        "memory_stats": {"max_usage": 0},
        "networks": {},
        "blkio_stats": {"io_service_bytes_recursive": []},
    }
    return container
