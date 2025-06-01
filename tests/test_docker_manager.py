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

    # Mock image object structure returned by build() and get()
    mock_image = mock.MagicMock(spec=docker.models.images.Image)
    mock_image.id = "sha256:testimageid123"
    mock_image.attrs = {'Size': 1024 * 1024 * 5} # 5MB
    mock_image.tags = [] # Will be populated by manager.tag

    def mock_tag_method(tag_name, **kwargs):
        # Simulate Docker's image.tag() behavior
        # In reality, client.images.get(id).tags would show it, but here we just check calls.
        mock_image.tags.append(tag_name) # Keep track of tags applied to this mock image
        return True # As per dockerpy docs, tag returns True on success
    mock_image.tag = mock.MagicMock(side_effect=mock_tag_method)

    # Default behavior for build()
    # build() returns (image, logs_generator)
    mock_client.images.build.return_value = (mock_image, iter([{'stream': 'Build log 1'}, {'stream': 'Build log 2'}]))

    # Default behavior for get()
    mock_client.images.get.return_value = mock_image

    # Default behavior for push()
    mock_client.images.push.return_value = iter([{'status': 'Pushed successfully'}])

    return mock_client

@pytest.fixture
def mock_docker_from_env(mock_docker_client_instance):
    """Patches docker.from_env() to return our MagicMock client instance."""
    with mock.patch('docker.from_env', return_value=mock_docker_client_instance) as mock_from_env:
        yield mock_from_env, mock_docker_client_instance # Yield both for convenience in tests

@pytest.fixture
def docker_manager_instance(mock_docker_from_env):
    """Provides a DockerManager instance with a mocked Docker client."""
    # mock_docker_from_env already activated the patch
    manager = DockerManager(registry_url="test.registry.com")
    # The client used by this manager is mock_docker_client_instance
    return manager, mock_docker_from_env[1] # Return manager and the client mock

@pytest.fixture
def docker_manager_no_registry(mock_docker_from_env):
    """Provides a DockerManager instance without a registry_url."""
    manager = DockerManager(registry_url=None)
    return manager, mock_docker_from_env[1]


# --- Helper for Dockerfile ---
@pytest.fixture
def create_dummy_dockerfile(tmp_path):
    """Creates a dummy Dockerfile in a temporary directory."""
    dockerfile_content = "FROM alpine\nCMD echo 'hello'"
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(dockerfile_content)
    return str(dockerfile), str(tmp_path)

# --- Test Cases ---

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_build_success_explicit_version(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    # Ensure the mocked image build returns a distinct mock_image for this test if needed
    mock_image_specific = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_specific.id = "sha256:explicitversion123"
    mock_image_specific.attrs = {'Size': 1024 * 1024 * 10} # 10MB
    mock_image_specific.tag = mock.MagicMock(return_value=True)

    client_mock.images.build.return_value = (mock_image_specific, iter([{'stream': 'Log entry'}]))
    client_mock.images.get.return_value = mock_image_specific

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="test-image",
        version="1.2.3"
    )

    assert result.image_id == "sha256:explicitversion123"
    assert "test-image:1.2.3" in result.tags
    assert result.size_mb == 10.0
    assert "Log entry" in result.logs

    client_mock.images.build.assert_called_once_with(
        path='/abs/path/.',
        dockerfile='Dockerfile',
        tag='test-image:1.2.3',
        rm=True,
        forcerm=True
    )
    # image.tag() is called by the manager for *additional* tags. The primary tag is done by build().
    # So, for this test, no *additional* tags are applied directly by image.tag() on the mock_image_specific
    # unless latest=True or registry push happens.
    # If we want to check all tags applied, we should check result.tags and how they were formed.
    # The primary tag 'test-image:1.2.3' is passed to client.images.build.

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
@mock.patch.dict(sys.modules, {'package': mock.MagicMock(__version__="2.3.4")})
def test_build_success_autoinfer_version(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    mock_image_autoinfer = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_autoinfer.id = "sha256:autoinfer123"
    mock_image_autoinfer.attrs = {'Size': 1024 * 1024 * 6} # 6MB
    mock_image_autoinfer.tag = mock.MagicMock(return_value=True)

    client_mock.images.build.return_value = (mock_image_autoinfer, iter([]))
    client_mock.images.get.return_value = mock_image_autoinfer

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="auto-image"
        # No version provided
    )
    assert result.image_id == "sha256:autoinfer123"
    assert "auto-image:2.3.4" in result.tags
    assert result.size_mb == 6.0
    client_mock.images.build.assert_called_once_with(
        path='/abs/path/.',
        dockerfile='Dockerfile',
        tag='auto-image:2.3.4',
        rm=True,
        forcerm=True
    )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
@mock.patch('importlib.import_module', side_effect=ModuleNotFoundError("No module named 'package'"))
def test_build_autoinfer_version_no_package_version(mock_import_module, mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    # Patch sys.modules to remove 'package' if it was added by a previous test
    if 'package' in sys.modules:
        del sys.modules['package']

    # Also need to ensure our DockerManager's "import package" fails
    # The DockerManager code has `import package`
    # We need to ensure this specific import fails.
    # The easiest way is to ensure 'package' is not in sys.modules AND importlib.import_module (if used by manager) raises error.
    # The current manager code uses `import package` directly.
    # So, ensuring 'package' is not in sys.modules is key.
    # We can also patch the 'package' module itself within the manager's scope if it proves difficult.
    # For now, the @mock.patch.dict(sys.modules, {'package': None}) or ensuring it's deleted should work for direct `import package`.
    # The `importlib.import_module` mock is for the case where the manager might use that.
    # The current manager code uses `import package`. So we need to ensure `package` is not in `sys.modules`
    # when manager.build is called.

    with mock.patch.dict(sys.modules): # Create a fresh context for sys.modules
        if 'package' in sys.modules:
            del sys.modules['package'] # Ensure it's not there

        with pytest.raises(ValueError, match="Version not provided and could not determine version"):
            manager.build(
                dockerfile_path=dockerfile_path,
                image_name="fail-image"
            )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x) # Simple pass-through
def test_build_invalid_semver(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile
    with pytest.raises(ValueError, match="Invalid version string: 'abc'"):
        manager.build(
            dockerfile_path=dockerfile_path,
            image_name="invalid-ver-image",
            version="abc"
        )

@mock.patch('os.path.exists', return_value=False) # Simulate Dockerfile not existing
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x)
def test_build_dockerfile_not_found(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    # The path from create_dummy_dockerfile won't actually be used by os.path.exists due to the mock
    dockerfile_path, _ = create_dummy_dockerfile
    with pytest.raises(FileNotFoundError, match="Dockerfile not found at /abs/path/"):
        manager.build(
            dockerfile_path=dockerfile_path, # This path will be made absolute by the mock
            image_name="notfound-image",
            version="1.0.0"
        )

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_build_with_latest_tag(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    mock_image_latest = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_latest.id = "sha256:latesttag123"
    mock_image_latest.attrs = {'Size': 1024 * 1024 * 7} # 7MB
    # We need to mock the tag method on this specific image instance
    # because the manager calls image.tag() for additional tags
    tags_applied_to_image = []
    def tag_side_effect(tag_name, **kwargs):
        tags_applied_to_image.append(tag_name)
        return True
    mock_image_latest.tag = mock.MagicMock(side_effect=tag_side_effect)

    client_mock.images.build.return_value = (mock_image_latest, iter([]))
    client_mock.images.get.return_value = mock_image_latest

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="latest-image",
        version="1.2.4",
        latest_tag=True
    )
    assert "latest-image:1.2.4" in result.tags
    assert "latest-image:latest" in result.tags
    assert result.size_mb == 7.0

    # The primary tag is applied during build
    client_mock.images.build.assert_called_once_with(
        path='/abs/path/.',
        dockerfile='Dockerfile',
        tag='latest-image:1.2.4',
        rm=True,
        forcerm=True
    )
    # The 'latest' tag is applied using image.tag()
    # Check that the mock_image_latest.tag method was called with 'latest-image:latest'
    mock_image_latest.tag.assert_any_call("latest-image:latest")
    # More robustly, check the collected tags on the mock image itself:
    assert "latest-image:latest" in tags_applied_to_image


@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_push_success(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance # This manager has registry_url="test.registry.com"
    dockerfile_path, _ = create_dummy_dockerfile

    mock_image_push = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_push.id = "sha256:pushsuccess123"
    mock_image_push.attrs = {'Size': 1024 * 1024 * 8}

    # Mock the image.tag method that will be called by the manager
    # This list will store all arguments image.tag was called with.
    image_tag_calls = []
    def image_tag_side_effect(repo, tag=None, **kwargs):
        #This mock is a bit simplified. Docker's image.tag can take repo OR repo:tag
        # manager calls it like: image.tag(f"{self.registry_url}/{tag_to_push}")
        # which means tag_to_push is like "my-image:1.0.0"
        # so repo becomes "test.registry.com/my-image:1.0.0" and tag is None
        full_tag = repo
        if tag: # if tag is not None
             full_tag = f"{repo}:{tag}"
        image_tag_calls.append(full_tag)
        return True # Simulate success
    mock_image_push.tag = mock.MagicMock(side_effect=image_tag_side_effect)

    client_mock.images.build.return_value = (mock_image_push, iter([]))
    client_mock.images.get.return_value = mock_image_push
    # client_mock.images.push is already mocked in the fixture

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="push-image",
        version="3.0.0",
        push=True,
        latest_tag=True
    )

    assert result.image_id == "sha256:pushsuccess123"

    expected_tags_on_image = [
        "test.registry.com/push-image:3.0.0", # Pushed tag
        "test.registry.com/push-image:latest" # Pushed tag
    ]
    # Check that image.tag() was called for registry tags
    for expected_call in expected_tags_on_image:
         assert expected_call in image_tag_calls

    # Check that client.images.push() was called for each registry-prefixed tag
    expected_push_calls = [
        mock.call("test.registry.com/push-image:3.0.0", stream=True, decode=True),
        mock.call("test.registry.com/push-image:latest", stream=True, decode=True)
    ]
    client_mock.images.push.assert_has_calls(expected_push_calls, any_order=True)
    assert client_mock.images.push.call_count == 2


@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
@mock.patch('orcaops.docker_manager.logger') # Mock the logger used in DockerManager
def test_push_no_registry_url(mock_logger_in_manager, mock_abspath, mock_exists, docker_manager_no_registry, create_dummy_dockerfile):
    manager, client_mock = docker_manager_no_registry # This manager has registry_url=None
    dockerfile_path, _ = create_dummy_dockerfile

    mock_image_no_reg = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_no_reg.id = "sha256:noregistry123"
    mock_image_no_reg.attrs = {'Size': 1024 * 1024 * 3}
    mock_image_no_reg.tag = mock.MagicMock(return_value=True)

    client_mock.images.build.return_value = (mock_image_no_reg, iter([]))
    client_mock.images.get.return_value = mock_image_no_reg

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="no-reg-image",
        version="1.0.0",
        push=True # Attempt to push
    )

    assert result.image_id == "sha256:noregistry123"
    mock_logger_in_manager.warning.assert_called_with(
        "Push requested, but no registry_url was provided during DockerManager initialization. Skipping push."
    )
    client_mock.images.push.assert_not_called()


@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_build_logs_captured(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    log_stream = [
        {'stream': 'Step 1/2 : FROM alpine'},
        {'stream': '\n'},
        {'stream': ' ---> abcdef123456\n'} ,
        {'stream': 'Step 2/2 : CMD echo "hello"'},
        {'stream': '\n'},
        {'stream': ' ---> ghi789klmno\n'},
        {'stream': 'Successfully built ghi789klmno\n'},
        {'stream': 'Successfully tagged logs-image:1.0.0\n'}
    ]
    # This is the image object that build() returns as the first element of its tuple
    mock_image_logs = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_logs.id = "sha256:logsimage123"
    mock_image_logs.attrs = {'Size': 1024 * 1024 * 2}
    mock_image_logs.tag = mock.MagicMock(return_value=True)

    # Configure the mock client's build method to return the mock image and the log stream
    client_mock.images.build.return_value = (mock_image_logs, iter(log_stream))
    # The get method should also return this image for size calculation etc.
    client_mock.images.get.return_value = mock_image_logs

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="logs-image",
        version="1.0.0"
    )

    expected_log_output = (
        "Step 1/2 : FROM alpine\n"
        "\n"  # This might be just an empty string after strip(), depending on exact content
        " ---> abcdef123456\n" # if original was ' ---> abcdef123456\n', strip() removes trailing \n
        "Step 2/2 : CMD echo \"hello\"\n"
        "\n"
        " ---> ghi789klmno\n"
        "Successfully built ghi789klmno\n"
        "Successfully tagged logs-image:1.0.0" # .strip() will remove the final \n if present
    )
    # Normalizing the expected and actual logs for comparison
    normalized_expected_logs = "\n".join(line.strip() for line in expected_log_output.splitlines() if line.strip())
    normalized_actual_logs = "\n".join(line.strip() for line in result.logs.splitlines() if line.strip())

    # For debugging:
    # print("Normalized Expected:\n", normalized_expected_logs)
    # print("Normalized Actual:\n", normalized_actual_logs)

    assert normalized_actual_logs == normalized_expected_logs
    assert result.image_id == "sha256:logsimage123"

@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_build_failure_logs_captured(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    build_error_log = [
        {'stream': 'Step 1/2 : FROM non_existent_image'},
        {'errorDetail': {'message': 'pull access denied for non_existent_image, repository does not exist or may require \'docker login\''}, 'error': 'pull access denied for non_existent_image, repository does not exist or may require \'docker login\''}
    ]
    # Simulate a build error
    # The actual image ID might be None or some intermediate ID on failure.
    # The BuildError exception itself carries the build_log.
    build_exception = docker.errors.BuildError("Build failed!", build_log=build_error_log)
    build_exception.image_id = "sha256:failedbuildid" # Sometimes an image_id is available on BuildError

    client_mock.images.build.side_effect = build_exception

    # No need to mock client.images.get() as it won't be reached if build fails and returns BuildResult.

    result = manager.build(
        dockerfile_path=dockerfile_path,
        image_name="fail-logs-image",
        version="1.0.0"
    )

    expected_log_output = (
        "Step 1/2 : FROM non_existent_image\n"
        "ERROR: pull access denied for non_existent_image, repository does not exist or may require 'docker login'"
    )
    normalized_expected_logs = "\n".join(line.strip() for line in expected_log_output.splitlines() if line.strip())
    normalized_actual_logs = "\n".join(line.strip() for line in result.logs.splitlines() if line.strip())

    # print("Normalized Expected (fail):\n", normalized_expected_logs)
    # print("Normalized Actual (fail):\n", normalized_actual_logs)

    assert normalized_actual_logs == normalized_expected_logs
    assert result.image_id == "sha256:failedbuildid" # or "unknown_on_failure" if not set on exception
    assert result.tags == [] # No tags on failure
    assert result.size_mb == 0.0 # No size on failure

# A test for Dockerfile path being outside build context
@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: f"/abs/{x}") # e.g. /abs/Dockerfile, /abs/../context
def test_dockerfile_outside_context(mock_abspath, mock_exists, docker_manager_instance):
    manager, _ = docker_manager_instance

    # Simulate Dockerfile path that, when relpath is calculated, results in starting with ".."
    # e.g. dockerfile_path = /abs/Dockerfile, build_context = /abs/context/inner
    # relpath(/abs/Dockerfile, /abs/context/inner) would be ../Dockerfile

    # To achieve this with the current mock_abspath:
    # Let dockerfile_path be 'Dockerfile' -> /abs/Dockerfile
    # Let build_context be 'context/inner' -> /abs/context/inner
    # So, relpath('/abs/Dockerfile', '/abs/context/inner') -> '../../Dockerfile' (if os.path.relpath works like that)
    # Let's adjust the mock for more direct control for this test:

    def abspath_side_effect(path):
        if path == "my_dockerfile":
            return "/project/Dockerfile" # Dockerfile is at /project/Dockerfile
        if path == "some_other_dir":
            return "/project/app/context" # Context is /project/app/context
        return f"/abs/{path}" # default for others like '.'

    with mock.patch('os.path.abspath', side_effect=abspath_side_effect):
        with pytest.raises(ValueError, match="must be within the build context"):
            manager.build(
                dockerfile_path="my_dockerfile", # -> /project/Dockerfile
                build_context="some_other_dir", # -> /project/app/context
                image_name="test-image",
                version="1.0.0"
            )

# Test for the __init__ method failing to connect to Docker
@mock.patch('docker.from_env', side_effect=docker.errors.DockerException("Docker daemon not responding"))
@mock.patch('orcaops.docker_manager.logger') # Mock logger within docker_manager module
def test_docker_manager_init_fail(mock_logger, mock_from_env):
    with pytest.raises(docker.errors.DockerException):
        DockerManager()
    mock_logger.error.assert_any_call("Failed to initialize Docker client: Docker daemon not responding")

# Test for push failing due to API error
@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_push_failure_api_error(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance # Has registry_url
    dockerfile_path, _ = create_dummy_dockerfile

    mock_image_push_fail = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_push_fail.id = "sha256:pushfail123"
    mock_image_push_fail.attrs = {'Size': 1024 * 1024 * 2}

    # image.tag will be called to tag with registry_url/image:tag
    # We need to ensure it's callable and returns True for the push logic to proceed.
    # The critical part is that client.images.push() raises an error.
    registry_tag_applied = False
    def image_tag_for_push_side_effect(repo_uri, **kwargs):
        nonlocal registry_tag_applied
        if manager.registry_url in repo_uri : # e.g. "test.registry.com/push-fail-image:1.0.0"
            registry_tag_applied = True
        return True # Simulate successful tagging
    mock_image_push_fail.tag = mock.MagicMock(side_effect=image_tag_for_push_side_effect)

    client_mock.images.build.return_value = (mock_image_push_fail, iter([]))
    client_mock.images.get.return_value = mock_image_push_fail

    # Simulate API error on push
    api_error = docker.errors.APIError("Simulated push API error (e.g. auth failure)")
    client_mock.images.push.side_effect = api_error

    # We also need to mock the logger to check the error message
    with mock.patch('orcaops.docker_manager.logger') as mock_logger_in_manager:
        result = manager.build(
            dockerfile_path=dockerfile_path,
            image_name="push-fail-image",
            version="1.0.0",
            push=True
        )

    assert result.image_id == "sha256:pushfail123" # Build itself succeeded
    assert registry_tag_applied # Image was tagged for push

    # Check that push was attempted
    expected_push_uri = f"{manager.registry_url}/push-fail-image:1.0.0"
    client_mock.images.push.assert_called_once_with(expected_push_uri, stream=True, decode=True)

    # Check that the error was logged
    mock_logger_in_manager.error.assert_any_call(f"Failed to push {expected_push_uri}: {api_error}")

    # The build result should still be returned
    assert result.tags == ["push-fail-image:1.0.0"] # Only local tags, registry tags are not added to BuildResult.tags by default
    assert result.size_mb == 2.0

# Test for image size calculation failure (e.g., image disappears or 'Size' key missing)
@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_image_size_retrieval_issues(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    mock_image_no_size = mock.MagicMock(spec=docker.models.images.Image)
    mock_image_no_size.id = "sha256:nosize123"
    mock_image_no_size.tag = mock.MagicMock(return_value=True)
    # Do NOT set mock_image_no_size.attrs['Size']

    client_mock.images.build.return_value = (mock_image_no_size, iter([]))

    # Scenario 1: ImageNotFound when trying to get it post-build
    client_mock.images.get.side_effect = docker.errors.ImageNotFound("Image disappeared")
    with mock.patch('orcaops.docker_manager.logger') as mock_logger_in_manager:
        result1 = manager.build(dockerfile_path, "size-test1", "1.0.0")
    assert result1.size_mb == 0.0
    mock_logger_in_manager.warning.assert_any_call(f"Could not retrieve image {mock_image_no_size.id} after build to get size. Using 0.0 MB.")

    # Reset side_effect for next scenario and ensure attrs is missing 'Size'
    client_mock.images.get.side_effect = None
    mock_image_no_size.attrs = {} # Explicitly empty attrs
    client_mock.images.get.return_value = mock_image_no_size
    with mock.patch('orcaops.docker_manager.logger') as mock_logger_in_manager:
        result2 = manager.build(dockerfile_path, "size-test2", "1.0.0") # Need different name to avoid mock call count issues
    assert result2.size_mb == 0.0
    mock_logger_in_manager.warning.assert_any_call(f"Could not retrieve size for image {mock_image_no_size.id}. Using 0.0 MB.")
    # Reset build mock call count for subsequent tests if manager instance is reused by other tests in same class/module
    client_mock.images.build.reset_mock()
    client_mock.images.get.reset_mock()

# Test to ensure `forcerm=True` is passed to `client.images.build`
@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: '/abs/path/' + x if x == '.' else '/abs/path/Dockerfile')
def test_build_uses_forcerm_true(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, client_mock = docker_manager_instance
    dockerfile_path, build_context_path = create_dummy_dockerfile

    manager.build(
        dockerfile_path=dockerfile_path,
        image_name="test-forcerm-image",
        version="1.0.0"
    )

    client_mock.images.build.assert_called_once() # Ensure it was called
    args, kwargs = client_mock.images.build.call_args
    assert kwargs.get('forcerm') is True # Check that forcerm=True was passed
    assert kwargs.get('rm') is True # Also check rm=True, as per current implementation

# Test to ensure `package` attribute error during version inference is handled
@mock.patch('os.path.exists', return_value=True)
@mock.patch('os.path.abspath', side_effect=lambda x: x)
def test_build_autoinfer_version_package_attribute_error(mock_abspath, mock_exists, docker_manager_instance, create_dummy_dockerfile):
    manager, _ = docker_manager_instance
    dockerfile_path, _ = create_dummy_dockerfile

    # Mock the 'package' module but make it so it doesn't have __version__
    mock_package_no_version = mock.MagicMock()
    del mock_package_no_version.__version__ # Ensure AttributeError

    with mock.patch.dict(sys.modules, {'package': mock_package_no_version}):
         # Re-check if 'package' is in sys.modules and its state for this specific test context
        assert 'package' in sys.modules
        assert not hasattr(sys.modules['package'], '__version__')
        with pytest.raises(ValueError, match="Version not provided and could not determine version"):
            manager.build(
                dockerfile_path=dockerfile_path,
                image_name="fail-attr-image"
                # No version provided
            )
