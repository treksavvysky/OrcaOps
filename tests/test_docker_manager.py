import pytest
from unittest import mock
import os
import sys

# Import the entities to be tested
from orcaops.docker_manager import DockerManager, BuildResult
from orcaops import logger as orcaops_logger # To mock it

# Import specific exceptions and classes for testing
from packaging.version import Version, InvalidVersion
import docker # To mock docker.errors.BuildError etc.


# --- Fixtures ---

@pytest.fixture
def mock_docker_client_instance():
    """Mocks the Docker client instance used by DockerManager."""
    mock_client = mock.MagicMock(spec=docker.DockerClient)
    mock_image = mock.MagicMock(spec=docker.models.images.Image)
    mock_image.id = "sha256:testimageid123"
    mock_image.attrs = {'Size': 1024 * 1024 * 5} 
    mock_image.tags = [] 
    def mock_tag_method(tag_name, **kwargs):
        mock_image.tags.append(tag_name)
        return True
    mock_image.tag = mock.MagicMock(side_effect=mock_tag_method)
    mock_client.images.build.return_value = (mock_image, iter([{'stream': 'Build log 1'}]))
    mock_client.images.get.return_value = mock_image
    mock_client.images.push.return_value = iter([{'status': 'Pushed successfully'}])
    return mock_client

@pytest.fixture
def mock_docker_from_env(mock_docker_client_instance):
    with mock.patch('docker.from_env', return_value=mock_docker_client_instance) as mock_from_env:
        yield mock_from_env, mock_docker_client_instance

@pytest.fixture
def docker_manager_instance(mock_docker_from_env):
    manager = DockerManager(registry_url="test.registry.com")
    return manager, mock_docker_from_env[1]

@pytest.fixture
def docker_manager_no_registry(mock_docker_from_env):
    manager = DockerManager(registry_url=None)
    return manager, mock_docker_from_env[1]

@pytest.fixture
def create_dummy_dockerfile(tmp_path):
    dockerfile_dir = tmp_path / "build_context_dummy" # Ensure a subdirectory for context
    dockerfile_dir.mkdir()
    dockerfile = dockerfile_dir / "Dockerfile"
    dockerfile.write_text("FROM alpine\nCMD echo 'hello'")
    return str(dockerfile), str(dockerfile_dir) # Return Dockerfile full path and context full path

# --- Test Cases for build ---

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p) # Assume paths from fixture are already absolute
def test_build_success_explicit_version(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    mock_image_specific = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_specific.id = "sha256:explicitversion123"
    mock_image_specific.attrs = {'Size': 1024 * 1024 * 10}
    mock_image_specific.tag = mock.MagicMock(return_value=True)
    client_mock.images.build.return_value = (mock_image_specific, iter([{'stream': 'Log entry'}]))
    client_mock.images.get.return_value = mock_image_specific

    result = manager.build(
        dockerfile_path=dockerfile_path,
        build_context=build_context_path, # Pass the correct build context
        image_name="test-image",
        version="1.2.3"
    )

    assert result.image_id == "sha256:explicitversion123"
    client_mock.images.build.assert_called_once_with(
        path=build_context_path,
        dockerfile='Dockerfile', # Relative to build_context_path
        tag='test-image:1.2.3',
        rm=True,
        forcerm=True
    )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
@mock.patch.dict(sys.modules, {'package': mock.MagicMock(__version__="2.3.4")})
def test_build_success_autoinfer_version(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    mock_image_autoinfer = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_autoinfer.id = "sha256:autoinfer123"
    mock_image_autoinfer.attrs = {'Size': 1024 * 1024 * 6}
    mock_image_autoinfer.tag = mock.MagicMock(return_value=True)
    client_mock.images.build.return_value = (mock_image_autoinfer, iter([]))
    client_mock.images.get.return_value = mock_image_autoinfer

    result = manager.build(
        dockerfile_path=dockerfile_path,
        build_context=build_context_path,
        image_name="auto-image"
    )
    assert "auto-image:2.3.4" in result.tags
    client_mock.images.build.assert_called_once_with(
        path=build_context_path,
        dockerfile='Dockerfile',
        tag='auto-image:2.3.4',
        rm=True,
        forcerm=True
    )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
@mock.patch('importlib.import_module', side_effect=ModuleNotFoundError("No module named 'package'"))
def test_build_autoinfer_version_no_package_version(mock_import_module, mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    if 'package' in sys.modules: del sys.modules['package']
    
    with mock.patch.dict(sys.modules):
        if 'package' in sys.modules: del sys.modules['package']
        with pytest.raises(ValueError, match="Version not provided and could not determine version"):
            manager.build(
                dockerfile_path=dockerfile_path,
                build_context=build_context_path,
                image_name="fail-image"
            )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x) 
def test_build_invalid_semver(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    with pytest.raises(ValueError, match="Invalid version string: 'abc'"):
        manager.build(
            dockerfile_path=dockerfile_path,
            build_context=build_context_path, 
            image_name="invalid-ver-image",
            version="abc"
        )

@mock.patch('os.path.exists', return_value=False)
# Use a specific mock for abspath that still makes sense for FileNotFoundError
@mock.patch('os.path.abspath', side_effect=lambda p: f"/abs_test_path/{os.path.basename(p)}" if os.path.basename(p) else f"/abs_test_path/{p}")
def test_build_dockerfile_not_found(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path_from_fixture, _ = create_dummy_dockerfile 
    # The abspath mock will transform dockerfile_path_from_fixture
    expected_abs_dockerfile_path = f"/abs_test_path/{os.path.basename(dockerfile_path_from_fixture)}"
    
    with pytest.raises(FileNotFoundError, match=f"Dockerfile not found at {expected_abs_dockerfile_path}"):
        manager.build(
            dockerfile_path=dockerfile_path_from_fixture, 
            image_name="notfound-image",
            version="1.0.0"
        )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
def test_build_with_latest_tag(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    mock_image_latest = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_latest.id = "sha256:latesttag123"
    mock_image_latest.attrs = {'Size': 1024 * 1024 * 7}
    tags_applied_to_image = []
    def tag_side_effect(tag_name, **kwargs):
        tags_applied_to_image.append(tag_name)
        return True
    mock_image_latest.tag = mock.MagicMock(side_effect=tag_side_effect)
    client_mock.images.build.return_value = (mock_image_latest, iter([]))
    client_mock.images.get.return_value = mock_image_latest

    result = manager.build(
        dockerfile_path=dockerfile_path,
        build_context=build_context_path,
        image_name="latest-image",
        version="1.2.4",
        latest_tag=True
    )
    assert "latest-image:latest" in tags_applied_to_image
    client_mock.images.build.assert_called_once_with(
        path=build_context_path,
        dockerfile='Dockerfile',
        tag='latest-image:1.2.4',
        rm=True,
        forcerm=True
    )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
def test_push_success(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    
    mock_image_push = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_push.id = "sha256:pushsuccess123"; mock_image_push.attrs = {'Size': 1024*1024*8}
    image_tag_calls = []
    def image_tag_side_effect(repo, tag=None, **kwargs): image_tag_calls.append(repo if tag is None else f"{repo}:{tag}"); return True
    mock_image_push.tag = mock.MagicMock(side_effect=image_tag_side_effect)
    client_mock.images.build.return_value = (mock_image_push, iter([]))
    client_mock.images.get.return_value = mock_image_push

    manager.build(dockerfile_path, "push-image", "3.0.0", push=True, latest_tag=True, build_context=build_context_path)
    expected_push_calls = [
        mock.call("test.registry.com/push-image:3.0.0", stream=True, decode=True),
        mock.call("test.registry.com/push-image:latest", stream=True, decode=True)
    ]
    client_mock.images.push.assert_has_calls(expected_push_calls, any_order=True)

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
@mock.patch('orcaops.docker_manager.logger')
def test_push_no_registry_url(mock_logger_in_manager, mock_abspath, mock_exists, docker_manager_no_registry, create_dummy_dockerfile):
    manager, client_mock = docker_manager_no_registry
    dockerfile_path, build_context_path = create_dummy_dockerfile
    mock_image_no_reg = mock.MagicMock(); mock_image_no_reg.id="id"; mock_image_no_reg.attrs={'Size':1}; mock_image_no_reg.tag=mock.MagicMock(return_value=True)
    client_mock.images.build.return_value = (mock_image_no_reg, iter([])); client_mock.images.get.return_value = mock_image_no_reg
    manager.build(dockerfile_path, "no-reg", "1.0.0", push=True, build_context=build_context_path)
    mock_logger_in_manager.warning.assert_called_with("Push requested, but no registry_url was provided during DockerManager initialization. Skipping push.")

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_build_logs_captured(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    log_stream = [{'stream': s} for s in ["S1\n", "S2\n"]]
    mock_image_logs = mock.MagicMock(); mock_image_logs.id="id"; mock_image_logs.attrs={'Size':1}; mock_image_logs.tag=mock.MagicMock(return_value=True)
    client_mock.images.build.return_value = (mock_image_logs, iter(log_stream))
    client_mock.images.get.return_value = mock_image_logs
    result = manager.build(dockerfile_path, "logs-img", "1.0.0", build_context=build_context_path)
    assert "S1\nS2" in result.logs.replace("\r", "") # Normalize line endings if any

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p) # Use actual paths from fixture
def test_build_failure_logs_captured(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    build_error_log = [{'stream': 'Error detail line 1'}, {'errorDetail': {'message': 'Build failed error msg'}, 'error': 'Error string'}]
    build_exception = docker.errors.BuildError("Build failed!", build_log=build_error_log)
    build_exception.image_id = "failed_id"
    client_mock.images.build.side_effect = build_exception
    result = manager.build(dockerfile_path, "fail-log", "1.0.0", build_context=build_context_path)
    assert "Error detail line 1" in result.logs
    assert "ERROR: Build failed error msg" in result.logs

@mock.patch('os.path.exists', return_value=True)
def test_dockerfile_outside_context(mock_exists, docker_manager_instance):
    manager, _ = docker_manager_instance
    def abspath_side_effect(path):
        if path == "my_dockerfile": return "/project/Dockerfile"
        if path == "some_other_dir": return "/project/app/context"
        return f"/abs/{path}" # Should not be used for these args
    with mock.patch('os.path.abspath', side_effect=abspath_side_effect):
        with pytest.raises(ValueError, match="must be within the build context"):
            manager.build(dockerfile_path="my_dockerfile", build_context="some_other_dir", image_name="test-image", version="1.0.0")

@mock.patch('docker.from_env', side_effect=docker.errors.DockerException("No Docker!"))
@mock.patch('orcaops.docker_manager.logger')
def test_docker_manager_init_fail(mock_logger, mock_from_env):
    with pytest.raises(docker.errors.DockerException): DockerManager()
    mock_logger.error.assert_any_call("Failed to initialize Docker client: No Docker!")

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
def test_push_failure_api_error(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    mock_img = mock.MagicMock(); mock_img.id="id"; mock_img.attrs={'Size':1}; mock_img.tag=mock.MagicMock(return_value=True)
    client_mock.images.build.return_value=(mock_img, iter([])); client_mock.images.get.return_value=mock_img
    api_error = docker.errors.APIError("Push fail")
    client_mock.images.push.side_effect = api_error
    with mock.patch('orcaops.docker_manager.logger') as mock_log:
        manager.build(dockerfile_path, "push-fail", "1.0.0", push=True, build_context=build_context_path)
    mock_log.error.assert_any_call(f"Failed to push test.registry.com/push-fail:1.0.0: {api_error}")

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_image_size_retrieval_issues(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    mock_img_no_size = mock.MagicMock(); mock_img_no_size.id="id_no_size"; mock_img_no_size.tag=mock.MagicMock(return_value=True)
    client_mock.images.build.return_value = (mock_img_no_size, iter([]))
    client_mock.images.get.side_effect = docker.errors.ImageNotFound("Gone")
    with mock.patch('orcaops.docker_manager.logger') as mock_log:
        res1 = manager.build(dockerfile_path, "s1", "1", build_context=build_context_path)
    assert res1.size_mb == 0.0; mock_log.warning.assert_any_call(f"Could not retrieve image id_no_size after build to get size. Using 0.0 MB.")
    client_mock.images.get.side_effect=None; mock_img_no_size.attrs={}; client_mock.images.get.return_value=mock_img_no_size
    with mock.patch('orcaops.docker_manager.logger') as mock_log:
        res2 = manager.build(dockerfile_path, "s2", "1", build_context=build_context_path)
    assert res2.size_mb == 0.0; mock_log.warning.assert_any_call(f"Could not retrieve size for image id_no_size. Using 0.0 MB.")
    client_mock.images.build.reset_mock(); client_mock.images.get.reset_mock()

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda p: p)
def test_build_uses_forcerm_true(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    manager.build(dockerfile_path, "forcerm-test", "1.0.0", build_context=build_context_path)
    client_mock.images.build.assert_called_once()
    assert client_mock.images.build.call_args[1].get('forcerm') is True

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_build_autoinfer_version_package_attribute_error(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile
    mock_pkg_no_ver = mock.MagicMock(); del mock_pkg_no_ver.__version__
    with mock.patch.dict(sys.modules, {'package': mock_pkg_no_ver}):
        with pytest.raises(ValueError, match="Version not provided and could not determine version"):
            manager.build(dockerfile_path, "fail-attr", build_context=build_context_path)

# --- Tests for new DockerManager methods ---
@pytest.fixture
def mock_container_operations(mock_docker_client_instance):
    client_mock = mock_docker_client_instance
    mock_container = mock.MagicMock(spec=docker.models.containers.Container)
    mock_container.id="test_cont_id"; mock_container.short_id="tc_id"; mock_container.name="tc_name"
    mock_container.status="running"; mock_container.attrs={'Config':{'Image':'img'}, 'State':{'ExitCode':0}}
    mock_container.logs.return_value = iter([b"Log1\n"])
    client_mock.containers = mock.MagicMock()
    client_mock.containers.run.return_value = mock_container
    client_mock.containers.get.return_value = mock_container
    client_mock.containers.list.return_value = [mock_container]
    return client_mock, mock_container

@pytest.fixture
def manager_with_container_ops(mock_docker_from_env, mock_container_operations):
    manager = DockerManager(registry_url="test.registry.com")
    return manager, mock_container_operations[0], mock_container_operations[1]

def test_run_container_simple(manager_with_container_ops):
    manager, client_mock, _ = manager_with_container_ops
    cid = manager.run("img", detach=True, environment=["F=B"])
    assert cid == "test_cont_id"
    client_mock.containers.run.assert_called_once_with("img", detach=True, environment=["F=B"])

def test_logs_container_streaming(manager_with_container_ops):
    manager, _, mock_container = manager_with_container_ops
    mock_container.logs.return_value = iter([b"LogS1\n"])
    with mock.patch('orcaops.docker_manager.logger') as mock_logger:
      # Test call passes follow and timestamps via kwargs to SUT's **kwargs
      manager.logs("id1", stream=True, follow=True, timestamps=True) 
    # SUT's logs method: log_params defaults follow=True, timestamps=True, then updates with kwargs
    # So container.logs should receive follow=True, timestamps=True
    mock_container.logs.assert_called_once_with(stream=True, follow=True, timestamps=True)
    mock_logger.info.assert_any_call("LogS1")

def test_logs_container_no_stream(manager_with_container_ops):
    manager, _, mock_container = manager_with_container_ops
    mock_container.logs.return_value = b"FullLog"
    res = manager.logs("id1", stream=False, option="val")
    assert res == "FullLog"
    mock_container.logs.assert_called_once_with(stream=False, option="val")

def test_list_running_containers_with_all_true(manager_with_container_ops):
    manager, client_mock, mc = manager_with_container_ops
    mcs = mock.MagicMock(spec=docker.models.containers.Container)
    mcs.id="sid"; mcs.status="exited"; mcs.attrs={'Config':{'Image':'s_img'}, 'State':{'ExitCode':0}}
    mcs.short_id = "s_id"; mcs.name = "s_name" # Ensure these are set
    client_mock.containers.list.return_value = [mc, mcs]
    res = manager.list_running_containers(all=True, filters={"label": "test"})
    assert len(res) == 2
    client_mock.containers.list.assert_called_once_with(all=True, filters={"label": "test"})

# Simplified remaining tests for brevity
def test_logs_container_not_found(manager_with_container_ops):
    m,c,_=manager_with_container_ops; c.containers.get.side_effect=docker.errors.NotFound("NF")
    with pytest.raises(docker.errors.NotFound): m.logs("uk")
def test_stop_container_success(manager_with_container_ops):
    m,c,mc=manager_with_container_ops; assert m.stop("id",timeout=5) is True; mc.stop.assert_called_once_with(timeout=5)
def test_stop_container_not_found(manager_with_container_ops):
    m,c,_=manager_with_container_ops; c.containers.get.side_effect=docker.errors.NotFound("NF"); assert m.stop("uk") is False
def test_stop_container_api_error(manager_with_container_ops):
    m,_,mc=manager_with_container_ops; mc.stop.side_effect=docker.errors.APIError("AE"); assert m.stop("id") is False
def test_rm_container_success(manager_with_container_ops):
    m,_,mc=manager_with_container_ops; assert m.rm("id",force=True,v=True) is True; mc.remove.assert_called_once_with(force=True,v=True)
def test_rm_container_not_found(manager_with_container_ops):
    m,c,_=manager_with_container_ops; c.containers.get.side_effect=docker.errors.NotFound("NF"); assert m.rm("uk") is False
def test_rm_container_api_error_running_no_force(manager_with_container_ops):
    m,_,mc=manager_with_container_ops; mc.remove.side_effect=docker.errors.APIError("AE"); assert m.rm("id",force=False) is False
def test_list_running_containers_default(manager_with_container_ops):
    m,c,_=manager_with_container_ops; m.list_running_containers(); c.containers.list.assert_called_once_with(filters={'status':'running'})
def test_list_running_containers_api_error(manager_with_container_ops):
    m,c,_=manager_with_container_ops; c.containers.list.side_effect=docker.errors.APIError("AE"); assert m.list_running_containers()==[]
