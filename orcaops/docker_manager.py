from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class BuildResult:
    """Stores the result of a Docker image build."""
    image_id: str
    tags: List[str]
    size_mb: float
    logs: Optional[str] = None


import docker
import docker.errors # Added for error handling
import os
from packaging.version import Version, InvalidVersion
from typing import Optional, List, Union # Union for type hinting

from orcaops import logger # Assuming logger is initialized in orcaops/__init__.py

class DockerManager:
    """Manages Docker image building, container lifecycle, and interaction."""

    def __init__(self, registry_url: Optional[str] = None):
        """
        Initializes DockerManager with an optional Docker registry URL.

        Args:
            registry_url: The URL of the Docker registry (e.g., 'your-registry.com').
        """
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            logger.error(
                "Please ensure Docker is running and accessible, or that DOCKER_HOST environment variable is set correctly."
            )
            raise
        self.registry_url = registry_url
        logger.info(f"DockerManager initialized. Registry URL: {self.registry_url if self.registry_url else 'Not set'}")

    def build(
        self,
        dockerfile_path: str,
        image_name: str,
        version: Optional[str] = None,
        build_context: str = ".",
        push: bool = False,
        latest_tag: bool = False,
    ) -> BuildResult:
        """
        Builds a Docker image, optionally tags it with version and 'latest', and pushes to a registry.

        Args:
            dockerfile_path: Path to the Dockerfile.
            image_name: Name for the Docker image (e.g., 'my-app').
            version: Version string (e.g., '1.2.3'). If None, tries to use `package.__version__`.
            build_context: Path to the build context (directory containing Dockerfile and build files).
            push: If True, pushes the image to the registry specified in `__init__`.
            latest_tag: If True, also tags the image as '<image_name>:latest'.

        Returns:
            A BuildResult object containing build details.

        Raises:
            FileNotFoundError: If the Dockerfile is not found.
            ValueError: If version is invalid or cannot be determined, or if other input is invalid.
            docker.errors.BuildError: If the Docker build itself fails.
            docker.errors.APIError: For other Docker API errors.
        """
        abs_build_context = os.path.abspath(build_context)
        abs_dockerfile_path = os.path.abspath(dockerfile_path)

        if not os.path.exists(abs_dockerfile_path):
            raise FileNotFoundError(f"Dockerfile not found at {abs_dockerfile_path}")

        # Dockerfile path relative to build context
        relative_dockerfile_path = os.path.relpath(abs_dockerfile_path, abs_build_context)
        if relative_dockerfile_path.startswith(".."):
            raise ValueError(
                f"Dockerfile {abs_dockerfile_path} must be within the build context {abs_build_context}"
            )

        logger.info(f"Starting Docker build for {image_name} using Dockerfile: {abs_dockerfile_path}")
        logger.info(f"Build context: {abs_build_context}")

        # Determine version
        if version is None:
            try:
                # Attempt to import the main package of the project to get __version__
                # This assumes the command is run from a context where 'package' is importable
                # and refers to the user's package. This might need adjustment based on project structure.
                import package
                version = package.__version__
                logger.info(f"Version not provided, using package.__version__: {version}")
            except (ImportError, AttributeError, ModuleNotFoundError):
                msg = (
                    "Version not provided and could not determine version from `package.__version__`. "
                    "Please provide a version string or ensure `package.__version__` is available."
                )
                logger.error(msg)
                raise ValueError(msg)

        try:
            parsed_version = Version(version)
        except InvalidVersion:
            msg = (
                f"Invalid version string: '{version}'. Version must be PEP 440 compliant."
            )
            logger.error(msg)
            raise ValueError(msg)

        primary_tag = f"{image_name}:{parsed_version.major}.{parsed_version.minor}.{parsed_version.micro}"
        all_tags = [primary_tag]
        if latest_tag:
            all_tags.append(f"{image_name}:latest")

        logger.info(f"Generated tags: {all_tags}")

        build_logs_str = ""
        try:
            logger.info(
                f"Building image with tag {primary_tag} (and others: {all_tags if len(all_tags) > 1 else 'None'})"
            )
            # The client.images.build returns a tuple (image, logs_generator)
            image, logs_generator = self.client.images.build(
                path=abs_build_context,
                dockerfile=relative_dockerfile_path,
                tag=primary_tag,  # Initial tag, others will be added later
                rm=True,  # Remove intermediate containers
                forcerm=True, # Force remove intermediate containers
            )
            log_lines = []
            for log_chunk in logs_generator:
                if 'stream' in log_chunk:
                    log_line = log_chunk['stream'].strip()
                    log_lines.append(log_line)
                    logger.debug(f"Build log: {log_line}") # Log individual lines at debug level
                elif 'error' in log_chunk:
                    error_detail = log_chunk['errorDetail']['message']
                    log_lines.append(f"ERROR: {error_detail}")
                    logger.error(f"Build error: {error_detail}") # Log error line
            build_logs_str = "\n".join(log_lines)

            # Tag with any additional tags
            for t in all_tags[1:]: # First tag was already applied by build()
                 logger.info(f"Tagging {image.id} with {t}")
                 image.tag(t)

        except docker.errors.BuildError as e:
            logger.error(f"Docker build failed for {image_name}: {e}")
            log_lines = []
            for log_chunk in e.build_log:
                if 'stream' in log_chunk:
                    log_line = log_chunk['stream'].strip()
                    log_lines.append(log_line)
                elif 'error' in log_chunk:
                    error_detail = log_chunk['errorDetail']['message']
                    log_lines.append(f"ERROR: {error_detail}")
            build_logs_str = "\n".join(log_lines)
            logger.error("Build logs:\n" + build_logs_str)
            # Include logs in the BuildResult even on failure, if possible
            # The image ID might not be available or relevant on complete failure
            # Try to get image ID if it exists, otherwise use a placeholder
            image_id_on_fail = e.image_id if hasattr(e, 'image_id') and e.image_id else "unknown_on_failure"
            # Size is not applicable on build failure
            return BuildResult(image_id=image_id_on_fail, tags=[], size_mb=0.0, logs=build_logs_str)
        except docker.errors.APIError as e:
            logger.error(f"Docker API error during build for {image_name}: {e}")
            raise

        # Get image object again to ensure attributes are populated, especially size
        try:
            image_obj = self.client.images.get(image.id)
            size_in_bytes = image_obj.attrs['Size']
            size_in_mb = round(size_in_bytes / (1024 * 1024), 2)
            logger.info(f"Image {image.id} built successfully. Size: {size_in_mb} MB")
        except docker.errors.ImageNotFound:
            logger.warning(f"Could not retrieve image {image.id} after build to get size. Using 0.0 MB.")
            size_in_mb = 0.0
        except KeyError:
            logger.warning(f"Could not retrieve size for image {image.id}. Using 0.0 MB.")
            size_in_mb = 0.0


        if push:
            if not self.registry_url:
                logger.warning(
                    "Push requested, but no registry_url was provided during DockerManager initialization. Skipping push."
                )
            else:
                logger.info(f"Pushing image {image_name} to registry {self.registry_url}")
                for tag_to_push in all_tags:
                    repo_uri = f"{self.registry_url}/{tag_to_push}"
                    try:
                        logger.info(f"Tagging image {image.id} as {repo_uri} for push")
                        # The tag format for registry push is <registry>/<image_name>:<version>
                        # If image_name already contains parts of registry, docker client handles it.
                        # Here, tag_to_push is like 'my-app:1.0.0' or 'my-app:latest'.
                        # So, repo_uri will be 'my-registry.com/my-app:1.0.0'.
                        if image.tag(repo_uri): # image.tag() returns True on success
                            logger.info(f"Pushing {repo_uri}")
                            push_output_gen = self.client.images.push(repo_uri, stream=True, decode=True)
                            for line in push_output_gen:
                                if 'status' in line:
                                    logger.info(f"Push status: {line['status']} {line.get('progress', '')}")
                                elif 'error' in line:
                                    logger.error(f"Push error: {line['errorDetail']['message']}")
                                else:
                                    logger.debug(f"Push output: {line}")
                            logger.info(f"Successfully pushed {repo_uri}")
                        else:
                            logger.error(f"Failed to tag image {image.id} with {repo_uri}")
                    except docker.errors.APIError as e:
                        logger.error(f"Failed to push {repo_uri}: {e}")
                        # Decide if we want to continue pushing other tags or stop.
                        # For now, log and continue.

        return BuildResult(
            image_id=image.id,
            tags=all_tags,
            size_mb=size_in_mb,
            logs=build_logs_str,
        )

    def run(self, image_name: str, **kwargs) -> str:
        """
        Runs a Docker container.

        Args:
            image_name: Name of the Docker image to run.
            **kwargs: Keyword arguments for docker.client.containers.run()
                      (e.g., detach=True, ports={'8000/tcp': 8000},
                       volumes={'/host/path': {'bind': '/container/path', 'mode': 'rw'}},
                       environment=["FOO=bar"]).

        Returns:
            The ID of the started container.

        Raises:
            docker.errors.ImageNotFound: If the image does not exist.
            docker.errors.APIError: For other Docker API errors.
        """
        logger.info(f"Attempting to run container from image: {image_name} with options: {kwargs}")
        try:
            container = self.client.containers.run(image_name, **kwargs)
            logger.info(f"Successfully started container {container.id} from image {image_name}")
            return container.id
        except docker.errors.ImageNotFound as e:
            logger.error(f"Image {image_name} not found: {e}")
            raise
        except docker.errors.APIError as e:
            logger.error(f"Failed to run container from image {image_name}: {e}")
            raise

    def logs(self, container_id: str, stream: bool = True, **kwargs) -> Union[str, None]:
        """
        Fetches logs from a container.

        Args:
            container_id: ID of the container.
            stream: If True (default), streams logs and prints them.
                    If False, returns all logs as a string.
            **kwargs: Additional keyword arguments for container.logs()
                      (e.g., tail="all", since=datetime_obj, until=datetime_obj).

        Returns:
            Log string if stream is False, None otherwise.

        Raises:
            docker.errors.NotFound: If the container is not found.
            docker.errors.APIError: For other Docker API errors.
        """
        logger.info(f"Fetching logs for container {container_id} (stream: {stream})")
        try:
            container = self.client.containers.get(container_id)
            if stream:
                # Build params carefully to avoid duplicate keywords if they are also in kwargs
                log_params = {"follow": True, "timestamps": True} # Defaults for streaming
                log_params.update(kwargs) # User-provided kwargs can override these
                log_params["stream"] = True # Ensure stream is True for this path

                log_stream = container.logs(**log_params)
                logger.info(f"Streaming logs for {container_id}:")
                for log_entry in log_stream:
                    # log_entry is bytes, decode to string
                    logger.info(log_entry.decode('utf-8').strip())
                return None # Streaming directly logs, does not return logs as a string
            else:
                all_logs = container.logs(stream=False, **kwargs)
                decoded_logs = all_logs.decode('utf-8')
                logger.info(f"Fetched all logs for {container_id}:\n{decoded_logs[:500]}{'...' if len(decoded_logs) > 500 else ''}") # Log a snippet
                return decoded_logs
        except docker.errors.NotFound:
            logger.error(f"Container {container_id} not found when trying to fetch logs.")
            raise
        except docker.errors.APIError as e:
            logger.error(f"Failed to fetch logs for container {container_id}: {e}")
            raise

    def stop(self, container_id: str, **kwargs) -> bool:
        """
        Stops a running container.

        Args:
            container_id: ID of the container to stop.
            **kwargs: Additional keyword arguments for container.stop() (e.g., timeout=10).

        Returns:
            True if successful, False otherwise.
        """
        logger.info(f"Attempting to stop container {container_id}")
        try:
            container = self.client.containers.get(container_id)
            container.stop(**kwargs)
            logger.info(f"Successfully stopped container {container_id}")
            return True
        except docker.errors.NotFound:
            logger.warning(f"Container {container_id} not found when trying to stop. Already stopped/removed?")
            return False
        except docker.errors.APIError as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            return False

    def rm(self, container_id: str, force: bool = False, **kwargs) -> bool:
        """
        Removes a container.

        Args:
            container_id: ID of the container to remove.
            force: If True, force removes the container (e.g., if it's running).
            **kwargs: Additional keyword arguments for container.remove() (e.g., v=True to remove volumes).

        Returns:
            True if successful, False otherwise.
        """
        logger.info(f"Attempting to remove container {container_id} (force: {force})")
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=force, **kwargs)
            logger.info(f"Successfully removed container {container_id}")
            return True
        except docker.errors.NotFound:
            logger.warning(f"Container {container_id} not found when trying to remove. Already removed?")
            return False # Considered not a failure of the operation's intent
        except docker.errors.APIError as e:
            # This can happen if trying to remove a running container without force=True
            logger.error(f"Failed to remove container {container_id}: {e}. Try with force=True if it is running.")
            return False

    def list_running_containers(self, **kwargs) -> List[docker.models.containers.Container]:
        """
        Lists running Docker containers.

        Args:
            **kwargs: Keyword arguments for docker.client.containers.list()
                      (e.g., all=True, filters={"status": "exited"}).

        Returns:
            A list of docker.models.containers.Container objects.
        """
        logger.info(f"Listing running containers with options: {kwargs}")
        try:
            # Default to only running containers if 'all' is not in kwargs
            if 'all' not in kwargs and 'filters' not in kwargs:
                 kwargs.setdefault('filters', {'status': 'running'})

            containers = self.client.containers.list(**kwargs)
            logger.info(f"Found {len(containers)} containers.")
            for i, c in enumerate(containers):
                logger.debug(f"  {i+1}. ID: {c.short_id}, Name: {c.name}, Image: {c.attrs['Config']['Image']}, Status: {c.status}")
            return containers
        except docker.errors.APIError as e:
            logger.error(f"Failed to list containers: {e}")
            return [] # Return empty list on error
