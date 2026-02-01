import pytest
from unittest import mock
from typer.testing import CliRunner
from orcaops.cli_enhanced import app
import docker
import docker.errors

runner = CliRunner()


def _make_mock_dm():
    """Create a mock DockerManager returned by init_docker_manager."""
    return mock.MagicMock()


def _make_container(short_id="test_id", name="test_container",
                    status="running", image_tags=None):
    """Build a mock container matching cli_enhanced expectations."""
    container = mock.MagicMock()
    container.short_id = short_id
    container.name = name
    container.status = status
    container.id = f"full-{short_id}"
    img = mock.MagicMock()
    img.tags = image_tags or ["test-image:latest"]
    container.image = img
    container.attrs = {
        'Config': {'Image': img.tags[0]},
        'Created': '2025-01-01T00:00:00+00:00',
        'NetworkSettings': {'Ports': {}, 'Networks': {}},
        'Mounts': [],
    }
    return container


# --- ps command ---

@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_ps_default(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.list_running_containers.return_value = [_make_container()]
    result = runner.invoke(app, ["ps"])
    assert result.exit_code == 0
    dm.list_running_containers.assert_called_once()
    assert "test_container" in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_ps_all(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.list_running_containers.return_value = [
        _make_container(short_id="running_id", name="running_container"),
        _make_container(short_id="stopped_id", name="stopped_container", status="exited"),
    ]
    result = runner.invoke(app, ["ps", "--all"])
    assert result.exit_code == 0
    dm.list_running_containers.assert_called_once_with(all=True)
    assert "running_container" in result.stdout
    assert "stopped_container" in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_ps_api_error(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.list_running_containers.side_effect = docker.errors.APIError("PS API Error")
    result = runner.invoke(app, ["ps"])
    # The enhanced ps command doesn't catch APIError explicitly, so it propagates
    assert result.exit_code != 0 or "Error" in result.stdout or "PS API Error" in result.stdout


# --- logs command ---

@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_logs_streaming_default(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    result = runner.invoke(app, ["logs", "test_container_id"])
    assert result.exit_code == 0
    dm.logs.assert_called_once_with(
        "test_container_id", stream=True, follow=True, timestamps=True
    )
    assert "Streaming logs for test_container_id" in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_logs_no_stream(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.logs.return_value = "Specific log output for no-stream test."
    result = runner.invoke(app, ["logs", "test_container_id", "--no-stream"])
    assert result.exit_code == 0
    dm.logs.assert_called_once_with(
        "test_container_id", stream=False, timestamps=True
    )
    assert "Specific log output for no-stream test." in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_logs_prompt_for_id(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    result = runner.invoke(app, ["logs"], input="test_container_id_prompted\n")
    assert result.exit_code == 0
    dm.logs.assert_called_once_with(
        "test_container_id_prompted", stream=True, follow=True, timestamps=True
    )


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_logs_container_not_found(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.logs.side_effect = docker.errors.NotFound("Container Not Found")
    result = runner.invoke(app, ["logs", "unknown_id"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


# --- rm command ---

@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_rm_single_container(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.rm.return_value = True
    result = runner.invoke(app, ["rm", "container1"])
    assert result.exit_code == 0
    dm.rm.assert_called_once_with("container1", force=False)
    assert "Container container1 removed successfully." in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_rm_multiple_containers_force(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.rm.return_value = True
    result = runner.invoke(app, ["rm", "c1", "c2", "--force"])
    assert result.exit_code == 0
    calls = [mock.call("c1", force=True), mock.call("c2", force=True)]
    dm.rm.assert_has_calls(calls)


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_rm_prompt_for_ids(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.rm.return_value = True
    result = runner.invoke(app, ["rm"], input="c1, c2, c3\n")
    assert result.exit_code == 0
    calls = [mock.call("c1", force=False), mock.call("c2", force=False), mock.call("c3", force=False)]
    dm.rm.assert_has_calls(calls)


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_rm_failure(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.rm.return_value = False
    result = runner.invoke(app, ["rm", "fail_container"])
    assert result.exit_code == 0
    assert "Failed to remove container fail_container." in result.stdout


# --- stop command ---

@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_stop_single_container(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.stop.return_value = True
    result = runner.invoke(app, ["stop", "container_to_stop"])
    assert result.exit_code == 0
    dm.stop.assert_called_once_with("container_to_stop")
    assert "Container container_to_stop stopped successfully." in result.stdout


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_stop_multiple_containers(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.stop.return_value = True
    result = runner.invoke(app, ["stop", "s1", "s2"])
    assert result.exit_code == 0
    calls = [mock.call("s1"), mock.call("s2")]
    dm.stop.assert_has_calls(calls)


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_stop_prompt_for_ids(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.stop.return_value = True
    result = runner.invoke(app, ["stop"], input="s1\n")
    assert result.exit_code == 0
    dm.stop.assert_called_once_with("s1")


@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_stop_failure(mock_init):
    dm = _make_mock_dm()
    mock_init.return_value = dm
    dm.stop.return_value = False
    result = runner.invoke(app, ["stop", "fail_stop_container"])
    assert result.exit_code == 0
    assert "Failed to stop container fail_stop_container." in result.stdout


# --- init failure ---

@mock.patch("orcaops.cli_enhanced.init_docker_manager")
def test_cli_docker_init_failure(mock_init):
    """Commands exit cleanly when Docker is unavailable."""
    import typer
    mock_init.side_effect = typer.Exit(1)
    result = runner.invoke(app, ["ps"])
    assert result.exit_code == 1
