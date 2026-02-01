"""Tests for service manager."""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from orcaops.schemas import ServiceDefinition
from orcaops.service_manager import (
    ServiceManager, _infer_default_port, _parse_duration,
)


@pytest.fixture
def mock_dm():
    dm = MagicMock()
    dm.create_network.return_value = "net-123"
    dm.run.return_value = "container-123"
    dm.connect_to_network.return_value = True
    dm.remove_network.return_value = True
    return dm


class TestServiceManager:
    def test_start_services_creates_network_and_containers(self, mock_dm):
        sm = ServiceManager(docker_manager=mock_dm)
        services = {
            "postgres": ServiceDefinition(image="postgres:15", env={"POSTGRES_PASSWORD": "test"}),
        }
        container_ids, env_vars = sm.start_services(services, "test-net", "wf-1")

        mock_dm.create_network.assert_called_once_with(
            "test-net", labels={"orcaops.workflow_id": "wf-1"}
        )
        assert "postgres" in container_ids
        assert env_vars["POSTGRES_HOST"] == "postgres"
        assert env_vars["POSTGRES_PORT"] == "5432"

    def test_start_services_connects_to_network(self, mock_dm):
        sm = ServiceManager(docker_manager=mock_dm)
        services = {
            "redis": ServiceDefinition(image="redis:7"),
        }
        sm.start_services(services, "test-net", "wf-2")

        mock_dm.connect_to_network.assert_called_once()
        call_args = mock_dm.connect_to_network.call_args
        assert call_args[0][1] == "net-123"  # network_id
        assert "redis" in call_args[1]["aliases"]

    def test_start_multiple_services(self, mock_dm):
        mock_dm.run.side_effect = ["pg-123", "redis-456"]
        sm = ServiceManager(docker_manager=mock_dm)
        services = {
            "postgres": ServiceDefinition(image="postgres:15"),
            "redis": ServiceDefinition(image="redis:7"),
        }
        container_ids, env_vars = sm.start_services(services, "test-net", "wf-3")

        assert len(container_ids) == 2
        assert "POSTGRES_HOST" in env_vars
        assert "REDIS_HOST" in env_vars

    def test_start_service_failure_cleans_up(self, mock_dm):
        mock_dm.run.side_effect = ["pg-123", Exception("Failed to start redis")]
        sm = ServiceManager(docker_manager=mock_dm)
        services = {
            "postgres": ServiceDefinition(image="postgres:15"),
            "redis": ServiceDefinition(image="redis:7"),
        }
        with pytest.raises(Exception, match="Failed to start redis"):
            sm.start_services(services, "test-net", "wf-4")

        # Should have cleaned up the already-started postgres
        mock_dm.rm.assert_called_once_with("pg-123", force=True)
        mock_dm.remove_network.assert_called_once_with("test-net")

    def test_stop_services(self, mock_dm):
        sm = ServiceManager(docker_manager=mock_dm)
        sm.stop_services({"pg": "pg-123", "redis": "redis-456"}, "test-net")

        assert mock_dm.rm.call_count == 2
        mock_dm.remove_network.assert_called_once_with("test-net")

    def test_health_check_healthy(self, mock_dm):
        container_mock = MagicMock()
        container_mock.attrs = {"State": {"Health": {"Status": "healthy"}}}
        mock_dm.client.containers.get.return_value = container_mock

        sm = ServiceManager(docker_manager=mock_dm)
        sm._wait_for_health("c-1", {"interval": "0.1s", "timeout": "5s", "retries": 3}, "test-svc")
        # Should return without error

    def test_health_check_no_healthcheck_but_running(self, mock_dm):
        container_mock = MagicMock()
        container_mock.attrs = {"State": {"Health": {"Status": "none"}}}
        container_mock.status = "running"
        mock_dm.client.containers.get.return_value = container_mock

        sm = ServiceManager(docker_manager=mock_dm)
        sm._wait_for_health("c-1", {"interval": "0.1s", "timeout": "5s"}, "test-svc")

    def test_unknown_image_no_port(self, mock_dm):
        sm = ServiceManager(docker_manager=mock_dm)
        services = {
            "custom": ServiceDefinition(image="myapp:latest"),
        }
        _, env_vars = sm.start_services(services, "test-net", "wf-5")
        assert "CUSTOM_HOST" in env_vars
        assert "CUSTOM_PORT" not in env_vars


class TestInferDefaultPort:
    def test_postgres(self):
        assert _infer_default_port("postgres:15") == 5432

    def test_redis(self):
        assert _infer_default_port("redis:7") == 6379

    def test_mysql(self):
        assert _infer_default_port("mysql:8.0") == 3306

    def test_mongo(self):
        assert _infer_default_port("mongo:6") == 27017

    def test_unknown(self):
        assert _infer_default_port("myapp:latest") is None

    def test_with_registry(self):
        assert _infer_default_port("docker.io/library/postgres:15") == 5432


class TestParseDuration:
    def test_seconds(self):
        assert _parse_duration("5s") == 5.0

    def test_milliseconds(self):
        assert _parse_duration("100ms") == 0.1

    def test_minutes(self):
        assert _parse_duration("2m") == 120.0

    def test_bare_number(self):
        assert _parse_duration("10") == 10.0
