"""Tests for Docker network management methods."""

from unittest.mock import MagicMock, patch
import docker.errors
import pytest


class TestDockerManagerNetwork:
    @patch("orcaops.docker_manager.docker.from_env")
    def test_create_network(self, mock_from_env):
        from orcaops.docker_manager import DockerManager

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_network = MagicMock()
        mock_network.id = "net-abc123"
        mock_client.networks.create.return_value = mock_network

        dm = DockerManager()
        result = dm.create_network("test-net", labels={"app": "orcaops"})

        assert result == "net-abc123"
        mock_client.networks.create.assert_called_once_with(
            "test-net", driver="bridge", labels={"app": "orcaops"}
        )

    @patch("orcaops.docker_manager.docker.from_env")
    def test_remove_network_success(self, mock_from_env):
        from orcaops.docker_manager import DockerManager

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_network = MagicMock()
        mock_client.networks.get.return_value = mock_network

        dm = DockerManager()
        assert dm.remove_network("test-net") is True
        mock_network.remove.assert_called_once()

    @patch("orcaops.docker_manager.docker.from_env")
    def test_remove_network_not_found(self, mock_from_env):
        from orcaops.docker_manager import DockerManager

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_client.networks.get.side_effect = docker.errors.NotFound("not found")

        dm = DockerManager()
        assert dm.remove_network("nonexistent") is False

    @patch("orcaops.docker_manager.docker.from_env")
    def test_connect_to_network(self, mock_from_env):
        from orcaops.docker_manager import DockerManager

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_network = MagicMock()
        mock_client.networks.get.return_value = mock_network

        dm = DockerManager()
        result = dm.connect_to_network("container-1", "net-1", aliases=["db", "postgres"])

        assert result is True
        mock_network.connect.assert_called_once_with("container-1", aliases=["db", "postgres"])
