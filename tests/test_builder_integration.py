import pytest
import docker
import os # For path joining
from unittest import mock
from orcaops.docker_manager import DockerManager, BuildResult

# Helper to get absolute path for Dockerfile, assuming tests are run from project root
DOCKERFILE_DIR = os.path.abspath("tests")
MINIMAL_DOCKERFILE_PATH = os.path.join(DOCKERFILE_DIR, "MinimalDockerfile")

@pytest.fixture(scope="function")
def docker_client():
    """Provides a Docker client instance."""
    try:
        client = docker.from_env()
        client.ping() # Verify Docker is accessible
        return client
    except docker.errors.DockerException:
        pytest.skip("Docker is not running or accessible, skipping integration tests.")

@pytest.fixture(scope="function")
def image_cleaner(docker_client):
    """Fixture to clean up Docker images after a test."""
    images_to_remove = set() # Use a set to store image IDs/tags

    def add_image(image_ref):
        images_to_remove.add(image_ref)

    yield add_image # This is what the test will use

    # Cleanup phase
    for image_ref in images_to_remove:
        try:
            # Attempt to get the image to see if it has multiple tags
            img_obj = docker_client.images.get(image_ref)
            # If an image has multiple tags, removing by one tag/ref might not remove the underlying image
            # if other tags point to it. We want to remove the specific tags we added,
            # and then the image ID if it's otherwise untagged.
            # However, a simpler approach for these tests is to remove by tag,
            # and then try to remove by ID from BuildResult if available.

            # For tags like "name:version" or "name:latest"
            if ':' in image_ref:
                 docker_client.images.remove(image=image_ref, force=True)
                 print(f"Cleaned up Docker image tag: {image_ref}")
            else:
                # If it's an ID (though tests should primarily add tags or BuildResult.image_id)
                docker_client.images.remove(image=image_ref, force=True) # force=True handles if it's still tagged
                print(f"Cleaned up Docker image ID: {image_ref}")

        except docker.errors.ImageNotFound:
            print(f"Image {image_ref} not found during cleanup, already removed or never existed.")
        except docker.errors.APIError as e:
            print(f"Error removing image {image_ref} during cleanup: {e}")


@pytest.mark.docker
def test_build_minimal_image_integration(docker_client, image_cleaner):
    """
    Tests building a minimal Docker image.
    Verifies BuildResult and image presence in Docker daemon.
    """
    manager = DockerManager()
    image_name = "minimal-test-image-integ"
    version = "0.1.0"
    expected_tag = f"{image_name}:{version}"

    # Ensure Dockerfile exists before running build
    assert os.path.exists(MINIMAL_DOCKERFILE_PATH), f"Dockerfile not found at {MINIMAL_DOCKERFILE_PATH}"

    result = None
    try:
        result = manager.build(
            dockerfile_path=MINIMAL_DOCKERFILE_PATH,
            image_name=image_name,
            version=version,
            build_context=DOCKERFILE_DIR # Build context is 'tests/' directory
        )

        assert result is not None
        assert result.image_id is not None
        assert isinstance(result.image_id, str)
        # Docker image IDs are typically "sha256:" followed by 64 hex chars
        assert result.image_id.startswith("sha256:")
        assert len(result.image_id.split(':')[1]) == 64

        assert expected_tag in result.tags
        assert isinstance(result.size_mb, float)
        assert result.size_mb > 0

        # Verify the image exists in the local daemon using the tag
        image_obj = docker_client.images.get(expected_tag)
        assert image_obj is not None
        assert image_obj.id == result.image_id # Verify ID consistency

        # Add for cleanup
        image_cleaner(expected_tag) # Clean up the tag
        if result.image_id: # Also schedule the ID for cleanup
            image_cleaner(result.image_id)


    finally:
        # The image_cleaner fixture handles the actual removal
        pass


@pytest.mark.docker
def test_build_with_latest_tag_integration(docker_client, image_cleaner):
    """
    Tests building with 'latest_tag=True'.
    Verifies both version and latest tags in BuildResult and Docker daemon.
    """
    manager = DockerManager()
    image_name = "latest-tag-test-image-integ"
    version = "0.2.0"

    version_tag = f"{image_name}:{version}"
    latest_tag = f"{image_name}:latest"

    assert os.path.exists(MINIMAL_DOCKERFILE_PATH), f"Dockerfile not found at {MINIMAL_DOCKERFILE_PATH}"

    result = None
    try:
        result = manager.build(
            dockerfile_path=MINIMAL_DOCKERFILE_PATH,
            image_name=image_name,
            version=version,
            latest_tag=True,
            build_context=DOCKERFILE_DIR
        )

        assert result is not None
        assert result.image_id is not None
        assert version_tag in result.tags
        assert latest_tag in result.tags

        # Verify tags in Docker daemon
        image_version_obj = docker_client.images.get(version_tag)
        assert image_version_obj is not None
        assert image_version_obj.id == result.image_id

        image_latest_obj = docker_client.images.get(latest_tag)
        assert image_latest_obj is not None
        assert image_latest_obj.id == result.image_id

        # Add for cleanup
        image_cleaner(version_tag)
        image_cleaner(latest_tag)
        if result.image_id:
            image_cleaner(result.image_id)

    finally:
        pass


@pytest.mark.docker
def test_build_nonexistent_dockerfile_integration(docker_client):
    """
    Tests that building with a non-existent Dockerfile raises FileNotFoundError.
    No cleanup needed as no image should be built.
    """
    manager = DockerManager()
    image_name = "nonexistent-df-test"
    version = "0.1.0"

    non_existent_dockerfile = os.path.join(DOCKERFILE_DIR, "NonExistentDockerfile")

    with pytest.raises(FileNotFoundError):
        manager.build(
            dockerfile_path=non_existent_dockerfile,
            image_name=image_name,
            version=version,
            build_context=DOCKERFILE_DIR
        )

@pytest.mark.docker
def test_build_image_and_push_to_local_registry_integration(docker_client, image_cleaner):
    """
    Tests building an image and "pushing" it.
    Since we don't want to rely on external registries, we'll simulate by:
    1. Starting a local registry container (if not already running for tests).
    2. Building and tagging for this local registry.
    3. Pushing to it.
    4. Verifying the image is "pushed" (e.g. by pulling it via the registry URI or checking registry API if simple).
    5. Cleaning up the local registry and the image.
    This test is more complex and might be better as a separate set of tests or with more infrastructure.
    For now, we'll test the push logic by ensuring the image is tagged with the registry prefix
    and that the push command is invoked. Actual push to a real registry is hard to test hermetically here.
    We will use a placeholder registry URL and check that the image is tagged correctly for that registry.
    The `DockerManager`'s push logic itself relies on `docker-py` which is assumed to work.
    """

    # This test will use a dummy registry URL. The actual push won't go anywhere unless a local registry
    # is running on localhost:5000 and the manager is initialized with that.
    # For this test, we'll focus on the tagging part and the attempt to push.
    # A true push test would require `docker run -d -p 5000:5000 --name registry registry:2`
    # and then `DockerManager(registry_url="localhost:5000")`.

    local_registry_url = "localhost:5000" # Standard local registry port
    manager = DockerManager(registry_url=local_registry_url) # Use a common local registry for testing

    image_name = "push-test-image-integ"
    version = "0.3.0"

    # Full repository URI for the versioned tag
    expected_repo_uri_version = f"{local_registry_url}/{image_name}:{version}"
    # Full repository URI for the latest tag
    expected_repo_uri_latest = f"{local_registry_url}/{image_name}:latest"

    assert os.path.exists(MINIMAL_DOCKERFILE_PATH), f"Dockerfile not found at {MINIMAL_DOCKERFILE_PATH}"

    # Mock the actual push command to avoid network calls and dependency on a running registry for this specific test.
    # We are verifying the manager's logic to *prepare* for a push (tagging) and *attempt* a push.
    # A full end-to-end push test would be a heavier integration test.

    # We need to use a real docker client for build, but mock the push part of it.
    # This is tricky because the manager creates its own client.
    # Solution: Patch `docker.DockerClient.images.push` globally for this test.

    result = None
    with mock.patch.object(docker.DockerClient, 'images', wraps=docker_client.images) as mock_images_attr:
        # mock_images_attr is now a MagicMock wrapping the real images attribute.
        # We can mock the push method on this.
        mock_push_method = mock.MagicMock(return_value=iter([{'status': 'Mocked push successful'}]))
        mock_images_attr.push = mock_push_method

        try:
            result = manager.build(
                dockerfile_path=MINIMAL_DOCKERFILE_PATH,
                image_name=image_name,
                version=version,
                push=True,
                latest_tag=True, # Also push latest
                build_context=DOCKERFILE_DIR
            )

            assert result is not None
            assert result.image_id is not None

            # Check that the image was tagged with the registry prefix locally
            # These tags are applied by DockerManager before calling push.
            img_obj_version_registry = docker_client.images.get(expected_repo_uri_version)
            assert img_obj_version_registry is not None
            assert img_obj_version_registry.id == result.image_id

            img_obj_latest_registry = docker_client.images.get(expected_repo_uri_latest)
            assert img_obj_latest_registry is not None
            assert img_obj_latest_registry.id == result.image_id

            # Check that push was called with the correct arguments
            mock_push_method.assert_any_call(expected_repo_uri_version, stream=True, decode=True)
            mock_push_method.assert_any_call(expected_repo_uri_latest, stream=True, decode=True)
            assert mock_push_method.call_count == 2 # For version and latest tag

            # Add all involved tags and the ID for cleanup
            image_cleaner(f"{image_name}:{version}") # Original local tag
            image_cleaner(f"{image_name}:latest")   # Original local latest tag
            image_cleaner(expected_repo_uri_version) # Registry-prefixed tag
            image_cleaner(expected_repo_uri_latest)  # Registry-prefixed latest tag
            if result.image_id:
                image_cleaner(result.image_id)

        finally:
            pass # Cleanup handled by fixture

