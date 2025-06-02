import pytest
from unittest import mock
import yaml
import os
import dataclasses 
from dataclasses import field 
import tempfile # For NamedTemporaryFile

from orcaops.sandbox_runner import SandboxRunner, SandboxConfig, DEFAULT_SANDBOX_FILE
from orcaops.docker_manager import DockerManager
import docker 
import requests 

# --- Fixtures ---
@pytest.fixture
def mock_docker_manager_for_sandbox():
    mock_dm = mock.MagicMock(spec=DockerManager)
    mock_container = mock.MagicMock(spec=docker.models.containers.Container)
    mock_container.id = "sandbox_container_id"
    mock_container.wait.return_value = {'StatusCode': 0} 
    mock_container.logs.return_value = iter([b"Sandbox log line\n"]) 
    # Default attrs for a completed, non-running container
    mock_container.attrs = {'State': {'ExitCode': 0, 'Running': False}, 'Status': 'exited'} 
    mock_container.status = 'exited'

    mock_dm.run.return_value = mock_container.id
    mock_dm.client = mock.MagicMock(spec=docker.DockerClient)
    mock_dm.client.containers = mock.MagicMock()
    mock_dm.client.containers.get.return_value = mock_container
    mock_dm.stop.return_value = True
    mock_dm.rm.return_value = True
    mock_dm.logs.return_value = None # Streaming logs in manager returns None by design

    mock_dm.client.api = mock.MagicMock()
    mock_dm.client.api.exec_create.return_value = {'Id': 'exec_id_123'}
    mock_dm.client.api.exec_start.return_value = iter([b"Exec output\n"])
    mock_dm.client.api.exec_inspect.return_value = {'ExitCode': 0}
    return mock_dm, mock_container

@pytest.fixture
def dummy_sandbox_configs(): # Renamed to reflect it returns dict, not path
    return {
        "sandboxes": [
            {"name": "test_echo_always_remove", "image": "alpine", "command": ["echo", "hello"], "timeout": 10, "cleanup_policy": "always_remove", "success_exit_codes": [0]},
            {"name": "test_fail_remove_on_completion", "image": "alpine", "command": ["sh", "-c", "exit 1"], "timeout": 10, "cleanup_policy": "remove_on_completion", "success_exit_codes": [0]},
            {"name": "test_success_remove_on_completion", "image": "alpine", "command": ["sh", "-c", "exit 0"], "timeout": 10, "cleanup_policy": "remove_on_completion", "success_exit_codes": [0]},
            {"name": "test_custom_success_remove_on_completion", "image": "alpine", "command": ["sh", "-c", "exit 7"], "timeout": 10, "cleanup_policy": "remove_on_completion", "success_exit_codes": [0, 7, 42]},
            {"name": "test_timeout_remove_on_timeout", "image": "alpine", "command": ["sleep", "20"], "timeout": 1, "cleanup_policy": "remove_on_timeout"},
            {"name": "test_timeout_keep_on_completion", "image": "alpine", "command": ["sleep", "20"], "timeout": 1, "cleanup_policy": "keep_on_completion"},
            {"name": "test_complete_keep_on_completion", "image": "alpine", "command": ["echo", "keep me"], "timeout": 10, "cleanup_policy": "keep_on_completion"},
            {"name": "test_never_remove_succeed", "image": "alpine", "command": ["echo", "never remove success"], "timeout": 10, "cleanup_policy": "never_remove"},
            {"name": "test_never_remove_fail", "image": "alpine", "command": ["sh", "-c", "exit 1"], "timeout": 10, "cleanup_policy": "never_remove", "success_exit_codes": [0]},
            {"name": "test_never_remove_timeout", "image": "alpine", "command": ["sleep", "20"], "timeout": 1, "cleanup_policy": "never_remove"},
        ]
    }

@pytest.fixture
def sandbox_runner_instance(mock_docker_manager_for_sandbox, dummy_sandbox_configs):
    # Use NamedTemporaryFile to create a temporary YAML file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".yml") as tmp_file:
        yaml.dump(dummy_sandbox_configs, tmp_file)
        tmp_file_path = tmp_file.name
    
    runner = SandboxRunner(docker_manager=mock_docker_manager_for_sandbox[0], sandbox_file_path=tmp_file_path)
    yield runner, mock_docker_manager_for_sandbox[0], mock_docker_manager_for_sandbox[1] # runner, mock_dm, mock_container
    os.remove(tmp_file_path) # Cleanup the temp file


# --- Test SandboxConfig ---
def test_sandbox_config_creation():
    config = SandboxConfig(name="cfg_test", image="img_test")
    assert config.name == "cfg_test"

# --- Test SandboxRunner Initialization and Loading ---
def test_sandbox_runner_load_invalid_config_entry(mock_docker_manager_for_sandbox, tmp_path, caplog):
    invalid_entry_file = tmp_path / "invalid_entry.yml"
    content = {
        "sandboxes": [
            {"name": "valid_one", "image": "alpine"},
            {"name_typo": "no_image_sandbox"}, 
            {"name": "no_image_specified"}, 
            {"name": "bad_exit_codes", "image":"alpine", "success_exit_codes": "not_a_list"}
        ]
    }
    with open(invalid_entry_file, 'w') as f: yaml.dump(content, f)
    runner = SandboxRunner(docker_manager=mock_docker_manager_for_sandbox[0], sandbox_file_path=str(invalid_entry_file))
    assert "valid_one" in runner.sandboxes
    assert len(runner.sandboxes) == 2 
    assert "Configuration error for sandbox 'Unnamed_Sandbox_1'" in caplog.text 
    assert "Configuration error for sandbox 'no_image_specified'" in caplog.text

# --- Test SandboxRunner.run_sandbox ---
@pytest.mark.parametrize(
    "sandbox_name, mock_exit_code, is_timeout, expected_run_success, expect_rm_called, expect_stop_called",
    [
        ("test_echo_always_remove", 0, False, True, True, False),
        ("test_echo_always_remove", 1, False, False, True, False), # Failed run, still removed
        ("test_success_remove_on_completion", 0, False, True, True, False),
        ("test_fail_remove_on_completion", 1, False, False, False, False), # Failed, not success_exit_code -> keep
        ("test_custom_success_remove_on_completion", 7, False, True, True, False),
        ("test_custom_success_remove_on_completion", 1, False, False, False, False), # Failed, not in custom success -> keep
        ("test_timeout_remove_on_timeout", None, True, False, True, True), # Timed out, remove, stop called
        ("test_timeout_remove_on_timeout", 0, False, True, False, False),  # Completed (no timeout), keep
        ("test_complete_keep_on_completion", 0, False, True, False, False), # Completed, keep
        ("test_complete_keep_on_completion", 1, False, False, False, False), # Completed (failed exit), still keep
        ("test_timeout_keep_on_completion", None, True, False, True, True), # Timed out (did not complete), remove
        ("test_never_remove_succeed", 0, False, True, False, False),
        ("test_never_remove_fail", 1, False, False, False, False),
        ("test_never_remove_timeout", None, True, False, False, True), # Timed out, keep, but stop if running
    ]
)
def test_run_sandbox_cleanup_policies(
    sandbox_runner_instance, sandbox_name, mock_exit_code, is_timeout,
    expected_run_success, expect_rm_called, expect_stop_called
):
    runner, mock_dm, mock_container = sandbox_runner_instance

    # Reset mocks for this parameterized run
    mock_dm.reset_mock()
    mock_container.reset_mock() # Reset the container mock itself
    mock_dm.client.containers.get.return_value = mock_container # Ensure get returns the reset mock

    if is_timeout:
        mock_container.wait.side_effect = requests.exceptions.ReadTimeout("Simulated timeout")
        mock_container.status = 'running' # Critical: if it times out, it's considered running
        mock_container.attrs = {'State': {'ExitCode': mock_exit_code if mock_exit_code is not None else -1, 'Running': True}}
    else:
        mock_container.wait.return_value = {'StatusCode': mock_exit_code}
        mock_container.wait.side_effect = None
        mock_container.status = 'exited' # If not timeout, it exited
        mock_container.attrs = {'State': {'ExitCode': mock_exit_code, 'Running': False}}

    success, exit_code_returned = runner.run_sandbox(sandbox_name)

    assert success == expected_run_success
    
    if expect_rm_called:
        mock_dm.rm.assert_called_with(mock_container.id, force=True)
    else:
        mock_dm.rm.assert_not_called()

    if expect_stop_called:
        mock_dm.stop.assert_called_with(mock_container.id, timeout=5)
    else:
        # Stop might be called if rm is true AND container was running.
        # The run_sandbox logic: if should_remove -> if container.status == 'running' -> stop() -> rm()
        # If not expect_stop_called, but expect_rm_called is True, and it timed out (so status was 'running')
        # then stop would have been called.
        if not (expect_rm_called and is_timeout): # if not (going to remove AND it was a timeout scenario)
             mock_dm.stop.assert_not_called()
        elif expect_rm_called and is_timeout: # It was a timeout and it's being removed, stop must have been called
             mock_dm.stop.assert_called_with(mock_container.id, timeout=5)


def test_run_sandbox_api_error_on_wait(sandbox_runner_instance, caplog):
    runner, mock_dm, mock_container = sandbox_runner_instance
    sandbox_name = "test_echo_always_remove" 
    
    api_error_message = "Simulated APIError on container wait"
    mock_container.wait.side_effect = docker.errors.APIError(api_error_message)
    # Simulate state where exit code is not available due to API error during wait
    mock_container.attrs = {'State': {}} # No ExitCode, Running might be true or false
    mock_container.status = 'running' # Assume it was running when wait failed

    mock_dm.run.return_value = "container_id_api_wait_error"
    mock_dm.client.containers.get.return_value = mock_container

    success, exit_code = runner.run_sandbox(sandbox_name)
    
    assert success is False 
    assert exit_code is None # Expect None as state was uncertain
    
    assert f"APIError while waiting for container container_id_api_wait_error: {api_error_message}" in caplog.text
    # Cleanup for 'always_remove' policy
    mock_dm.stop.assert_called_once_with("container_id_api_wait_error", timeout=5) # Should try to stop
    mock_dm.rm.assert_called_once_with("container_id_api_wait_error", force=True)


@mock.patch('orcaops.sandbox_runner.DockerManager') 
@mock.patch('orcaops.sandbox_runner.yaml.dump') 
@mock.patch('orcaops.sandbox_runner.os.remove') 
@mock.patch('orcaops.sandbox_runner.logger') # Mock logger in sandbox_runner
def test_sandbox_runner_main_block(mock_sr_logger, mock_os_remove, mock_yaml_dump, mock_main_dm_class, caplog, monkeypatch):
    # This test runs the __main__ block of sandbox_runner.py
    # It needs ORCAOPS_SKIP_DOCKER_INIT to be "0" or not set to attempt DockerManager instantiation
    monkeypatch.setenv("ORCAOPS_SKIP_DOCKER_INIT", "0")

    # Mock what DockerManager() returns when called in __main__
    mock_dm_instance_for_main = mock.MagicMock(spec=DockerManager)
    mock_main_dm_class.return_value = mock_dm_instance_for_main
    
    import runpy
    # Patch DEFAULT_SANDBOX_FILE for the main block context
    with mock.patch('orcaops.sandbox_runner.DEFAULT_SANDBOX_FILE', "dummy_sandboxes.yml"):
          # Mock open for when SandboxRunner tries to load dummy_sandboxes.yml
          # This is because the real file created by __main__ will be "dummy_sandboxes.yml"
          # and SandboxRunner will try to load it.
          m_open = mock.mock_open(read_data=yaml.dump({"sandboxes": [{"name": "test_dummy", "image": "alpine"}]}))
          with mock.patch('builtins.open', m_open):
            runpy.run_module('orcaops.sandbox_runner', run_name='__main__')

    assert "Running SandboxRunner directly for basic module structure check." in caplog.text # From __main__
    mock_main_dm_class.assert_called_once() 
    mock_yaml_dump.assert_called_once() # __main__ creates dummy_sandboxes.yml
    
    # Check that SandboxRunner tried to load the dummy file created by __main__
    # The logger message from SandboxRunner.__init__
    assert "Successfully loaded 1 sandbox configurations from dummy_sandboxes.yml" in caplog.text
    mock_os_remove.assert_called_with("dummy_sandboxes.yml")


# Remaining tests (most should pass with minor or no changes if above are correct)
def test_sandbox_config_invalid_policy_defaulting(caplog):
    config = SandboxConfig(name="policy_test", image="img", cleanup_policy="bad_policy")
    assert config.cleanup_policy == "remove_on_completion" 
    assert "Invalid cleanup_policy 'bad_policy'" in caplog.text

def test_sandbox_runner_init_success(sandbox_runner_instance):
    runner, _, _ = sandbox_runner_instance
    assert "test_echo_always_remove" in runner.sandboxes # Name from dummy_sandbox_configs

def test_sandbox_runner_init_file_not_found(mock_docker_manager_for_sandbox, tmp_path, caplog):
    non_existent_file = tmp_path / "no_such_file.yml"
    runner = SandboxRunner(docker_manager=mock_docker_manager_for_sandbox[0], sandbox_file_path=str(non_existent_file))
    assert not runner.sandboxes 
    assert f"Sandbox configuration file {non_existent_file} not found" in caplog.text

def test_sandbox_runner_init_malformed_yaml(mock_docker_manager_for_sandbox, tmp_path, caplog):
    malformed_file = tmp_path / "bad.yml"; malformed_file.write_text("sandboxes: [ { name: test ")
    runner = SandboxRunner(docker_manager=mock_docker_manager_for_sandbox[0], sandbox_file_path=str(malformed_file))
    assert not runner.sandboxes
    assert "Critical error loading sandbox configurations" in caplog.text

def test_run_sandbox_config_not_found(sandbox_runner_instance, caplog):
    runner, _, _ = sandbox_runner_instance
    success, exit_code = runner.run_sandbox("non_existent_sandbox_config")
    assert success is False; assert exit_code is None
    assert "Sandbox configuration named 'non_existent_sandbox_config' not found." in caplog.text

def test_run_sandbox_image_not_found(sandbox_runner_instance, caplog):
    runner, mock_dm, _ = sandbox_runner_instance
    mock_dm.run.side_effect = docker.errors.ImageNotFound("Image 'nonexistent_image' not found.")
    success, exit_code = runner.run_sandbox("test_echo_always_remove", image="nonexistent_image") # Use a valid sandbox name
    assert success is False; assert exit_code is None
    assert "Image 'nonexistent_image' not found. Cannot run sandbox." in caplog.text

def test_sandbox_runner_helper_run(sandbox_runner_instance):
    runner, mock_dm, _ = sandbox_runner_instance
    runner.run("helper_image", command=["ls"], detach=False, environment=["VAR=1"])
    mock_dm.run.assert_called_with("helper_image", command=["ls"], detach=False, environment=["VAR=1"])

def test_sandbox_runner_helper_exec(sandbox_runner_instance):
    runner, mock_dm, _ = sandbox_runner_instance
    exit_code, output = runner.exec_in_container("test_id", ["bash", "-c", "echo hello exec"])
    assert exit_code == 0; assert "Exec output" in output

def test_sandbox_runner_helper_stop(sandbox_runner_instance):
    runner, mock_dm, _ = sandbox_runner_instance
    runner.stop("cid_stop_helper", timeout=3)
    mock_dm.stop.assert_called_with("cid_stop_helper", timeout=3)

def test_sandbox_runner_helper_rm(sandbox_runner_instance):
    runner, mock_dm, _ = sandbox_runner_instance
    runner.rm("cid_rm_helper", force=True, v=True)
    mock_dm.rm.assert_called_with("cid_rm_helper", force=True, v=True)

@mock.patch('orcaops.sandbox_runner.os.path.exists', return_value=False)
def test_load_sandboxes_file_not_found_direct(mock_exists_patch, mock_docker_manager_for_sandbox, tmp_path):
    sr = SandboxRunner(mock_docker_manager_for_sandbox[0], sandbox_file_path="will_be_ignored.yml")
    sr.sandboxes = {} 
    non_existent_file = str(tmp_path / "no_such_file_direct.yml")
    with pytest.raises(FileNotFoundError, match=f"Sandbox configuration file not found: {non_existent_file}"):
        sr.load_sandboxes(non_existent_file)
    mock_exists_patch.assert_called_once_with(non_existent_file)

def test_load_sandboxes_empty_or_invalid_yaml_structure(mock_docker_manager_for_sandbox, tmp_path, caplog):
    sr = SandboxRunner(mock_docker_manager_for_sandbox[0], sandbox_file_path="ignored.yml"); sr.sandboxes = {}
    empty_file = tmp_path / "empty.yml"; empty_file.write_text("")
    assert sr.load_sandboxes(str(empty_file)) == {}
    assert f"Invalid YAML structure in {empty_file}" in caplog.text
    no_sandboxes_key_file = tmp_path / "no_key.yml"; yaml.dump({"other_key": []}, open(no_sandboxes_key_file, 'w'))
    assert sr.load_sandboxes(str(no_sandboxes_key_file)) == {}
    assert f"Invalid YAML structure in {no_sandboxes_key_file}" in caplog.text
    not_list_file = tmp_path / "not_list.yml"; yaml.dump({"sandboxes": {"not": "a list"}}, open(not_list_file, 'w'))
    assert sr.load_sandboxes(str(not_list_file)) == {}
    assert f"Invalid YAML structure in {not_list_file}" in caplog.text

def test_run_sandbox_api_error_on_run(sandbox_runner_instance, caplog):
    runner, mock_dm, _ = sandbox_runner_instance; sandbox_name = "test_echo_always_remove"
    api_error_message = "Simulated APIError on container run"
    mock_dm.run.side_effect = docker.errors.APIError(api_error_message)
    success, exit_code = runner.run_sandbox(sandbox_name)
    assert success is False; assert exit_code is None
    assert f"Sandbox '{sandbox_name}': APIError during container run/setup for image 'alpine': {api_error_message}" in caplog.text

def test_run_sandbox_override_kwargs(sandbox_runner_instance): 
    runner, mock_dm, mock_container = sandbox_runner_instance
    override_command = ["echo", "overridden"]
    runner.run_sandbox("test_echo_always_remove", command=override_command)
    call_args = mock_dm.run.call_args
    assert call_args[1]['command'] == override_command
