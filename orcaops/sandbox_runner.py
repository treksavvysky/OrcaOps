#!/usr/bin/env python

import yaml
import os
import dataclasses # Added import
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any
import time # For sleep, if needed

import docker
import docker.errors
import requests.exceptions # For timeout handling with container.wait()

from orcaops.docker_manager import DockerManager
from orcaops import logger

DEFAULT_SANDBOX_FILE = "sandboxes.yml"

@dataclass
class SandboxConfig:
    """Configuration for a single sandbox environment."""
    name: str
    image: str
    command: Optional[List[str]] = None
    timeout: int = 60  # seconds for the container to run, not for docker commands like pull
    cleanup_policy: str = "remove_on_completion"
    ports: Optional[Dict[str, Any]] = None
    volumes: Optional[Dict[str, Dict[str, str]]] = None
    environment: Optional[List[str]] = None
    success_exit_codes: List[int] = field(default_factory=lambda: [0])

    def __post_init__(self):
        valid_policies = ["remove_on_completion", "keep_on_completion", "remove_on_timeout", "always_remove", "never_remove"]
        if self.cleanup_policy not in valid_policies:
            # Log this as an error too for higher visibility if instantiation is not directly controlled by user input
            logger.error(f"Invalid cleanup_policy '{self.cleanup_policy}' for sandbox '{self.name}'. Must be one of {valid_policies}. Defaulting to 'remove_on_completion'.")
            # Defaulting or raising depends on how critical this is. For now, let's default and log error.
            # Or raise: raise ValueError(f"Invalid cleanup_policy '{self.cleanup_policy}' for sandbox '{self.name}'. Must be one of {valid_policies}")
            self.cleanup_policy = "remove_on_completion" # Defaulting to a safe option


class SandboxRunner:
    """Manages the execution of predefined sandboxed environments."""

    def __init__(self, docker_manager: DockerManager, sandbox_file_path: str = DEFAULT_SANDBOX_FILE):
        self.docker_manager = docker_manager
        self.sandbox_file_path = sandbox_file_path
        try:
            self.sandboxes = self.load_sandboxes(self.sandbox_file_path)
            if self.sandboxes: # Only log success if sandboxes were actually loaded
                logger.info(f"Successfully loaded {len(self.sandboxes)} sandbox configurations from {self.sandbox_file_path}")
        except FileNotFoundError:
            logger.warning(f"Sandbox configuration file {self.sandbox_file_path} not found. No sandboxes loaded. SandboxRunner will operate with an empty configuration set.")
            self.sandboxes: Dict[str, SandboxConfig] = {}
        except (yaml.YAMLError, ValueError) as e: # Catch YAML parsing errors and config validation errors
            logger.error(f"Critical error loading sandbox configurations from {self.sandbox_file_path}: {e}. SandboxRunner will operate with an empty configuration set.")
            self.sandboxes: Dict[str, SandboxConfig] = {} # Ensure it's initialized safely
            # Depending on application requirements, might want to raise this
            # raise


    def load_sandboxes(self, sandbox_file_path: str) -> Dict[str, SandboxConfig]:
        logger.info(f"Attempting to load sandbox configurations from: {sandbox_file_path}")
        if not os.path.exists(sandbox_file_path):
            raise FileNotFoundError(f"Sandbox configuration file not found: {sandbox_file_path}")

        try:
            with open(sandbox_file_path, 'r') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error in {sandbox_file_path}: {e}")
            raise  # Propagate to __init__ for handling

        if not data or 'sandboxes' not in data or not isinstance(data.get('sandboxes'), list):
            logger.warning(f"Invalid YAML structure in {sandbox_file_path}. Expected a top-level 'sandboxes' list. No sandboxes loaded.")
            return {}

        loaded_sandboxes: Dict[str, SandboxConfig] = {}
        for i, config_dict in enumerate(data['sandboxes']):
            if not isinstance(config_dict, dict):
                logger.warning(f"Sandbox entry at index {i} in {sandbox_file_path} is not a dictionary, skipping.")
                continue
            
            entry_name = config_dict.get('name', f'Unnamed_Sandbox_{i}')
            try:
                if 'success_exit_codes' in config_dict and not isinstance(config_dict['success_exit_codes'], list):
                    logger.warning(f"Sandbox '{entry_name}': 'success_exit_codes' should be a list. Found: {config_dict['success_exit_codes']}. Using default [0].")
                    del config_dict['success_exit_codes'] # Use default from dataclass

                config = SandboxConfig(**config_dict)
                if config.name in loaded_sandboxes:
                    logger.warning(f"Duplicate sandbox name '{config.name}' in {sandbox_file_path}. Overwriting previous definition.")
                loaded_sandboxes[config.name] = config
                logger.debug(f"Successfully parsed and validated sandbox configuration: {config.name}")
            except TypeError as e:
                logger.error(f"Configuration error for sandbox '{entry_name}' in {sandbox_file_path}: Missing required fields or incorrect type - {e}. Skipping this entry.")
            except ValueError as e: # Catches validation errors from SandboxConfig (e.g. __post_init__)
                 logger.error(f"Validation error for sandbox '{entry_name}' in {sandbox_file_path}: {e}. Skipping this entry.")
        
        if not loaded_sandboxes:
            logger.warning(f"No valid sandbox configurations found in {sandbox_file_path} after parsing.")
        return loaded_sandboxes

    # --- Helper methods for tests / ad-hoc runs ---
    def run(self, image: str, command: Optional[List[str]] = None, **kwargs) -> Optional[str]:
        logger.info(f"Ad-hoc run: Attempting to start container from image '{image}' with command '{command}' and options {kwargs}")
        kwargs.setdefault('detach', True)
        try:
            # Pass command directly to docker_manager.run
            container_id = self.docker_manager.run(image, command=command, **kwargs)
            logger.info(f"Ad-hoc container {container_id} started from image '{image}'.")
            return container_id
        except docker.errors.ImageNotFound:
            logger.error(f"Ad-hoc run: Image '{image}' not found.")
            return None
        except docker.errors.APIError as e:
            logger.error(f"Ad-hoc run: APIError while starting container from image '{image}': {e}")
            return None
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"Ad-hoc run: Unexpected error starting container from image '{image}': {e}", exc_info=True)
            return None

    def exec_in_container(self, container_id: str, cmd: List[str], **kwargs) -> Tuple[Optional[int], str]:
        logger.info(f"Attempting to execute command '{' '.join(cmd)}' in container '{container_id}' with options {kwargs}")
        try:
            # Check if container exists first (optional, exec_create might fail cleanly too)
            # self.docker_manager.client.containers.get(container_id) 
            
            exec_response = self.docker_manager.client.api.exec_create(container_id, cmd, **kwargs)
            exec_id = exec_response['Id']
            
            # Stream output
            exec_output_generator = self.docker_manager.client.api.exec_start(exec_id, stream=True)
            output_lines = []
            for chunk in exec_output_generator:
                line = chunk.decode('utf-8', errors='replace').strip()
                output_lines.append(line)
                logger.debug(f"Exec output from {container_id} ({exec_id}): {line}")
            
            full_output = "\n".join(output_lines)
            
            # Inspect to get exit code
            exec_inspect_info = self.docker_manager.client.api.exec_inspect(exec_id)
            exit_code = exec_inspect_info.get('ExitCode')

            if exit_code == 0:
                logger.info(f"Command '{' '.join(cmd)}' in container '{container_id}' executed successfully (Exit Code: {exit_code}).")
            else:
                logger.warning(f"Command '{' '.join(cmd)}' in container '{container_id}' finished with non-zero Exit Code: {exit_code}.")
            return exit_code, full_output
        except docker.errors.NotFound:
            logger.error(f"Cannot exec in container '{container_id}': Container not found.")
            return (None, "Error: Container not found.")
        except docker.errors.APIError as e:
            logger.error(f"APIError during exec in container '{container_id}': {e}")
            return (None, f"APIError: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during exec in container '{container_id}': {e}", exc_info=True)
            return (None, f"Unexpected error: {e}")

    def stop(self, container_id: str, **kwargs) -> bool:
        logger.debug(f"SandboxRunner: Delegating stop command for container {container_id} to DockerManager.")
        return self.docker_manager.stop(container_id, **kwargs)

    def rm(self, container_id: str, force: bool = False, **kwargs) -> bool:
        logger.debug(f"SandboxRunner: Delegating rm command for container {container_id} (force: {force}) to DockerManager.")
        return self.docker_manager.rm(container_id, force=force, **kwargs)

    def run_sandbox(self, name: str, **override_kwargs) -> Tuple[bool, Optional[int]]:
        """
        Runs a predefined sandbox configuration.

        Args:
            name: The name of the sandbox configuration to run.
            **override_kwargs: Keyword arguments to override SandboxConfig parameters
                               (e.g., command, timeout, environment).

        Returns:
            A tuple (success: bool, exit_code: Optional[int]).
            'success' is True if the container ran and its exit code is in success_exit_codes.
            'exit_code' is the container's exit code, or None if it could not be determined
            (e.g., container failed to start, or timed out and was killed before exit code reported).
        """
        logger.info(f"Attempting to run sandbox: '{name}' with overrides: {override_kwargs}")

        if name not in self.sandboxes:
            logger.error(f"Sandbox configuration named '{name}' not found.")
            return False, None

        base_config = self.sandboxes[name]
        
        # Create a new config instance with overrides
        config_params = base_config.__dict__.copy() # Start with base config
        # Filter override_kwargs to only include valid SandboxConfig fields
        valid_override_keys = {f.name for f in dataclasses.fields(SandboxConfig)}
        for key, value in override_kwargs.items():
            if key in valid_override_keys:
                config_params[key] = value
            else:
                logger.warning(f"Ignoring invalid override parameter '{key}' for sandbox '{name}'.")
        
        try:
            # Create a new SandboxConfig instance for this run
            # This also re-validates if __post_init__ has checks
            current_config = SandboxConfig(**config_params)
        except (TypeError, ValueError) as e:
            logger.error(f"Error applying overrides to sandbox config '{name}': {e}")
            return False, None

        logger.info(f"Running sandbox '{current_config.name}' with image '{current_config.image}' and command '{current_config.command}'")

        container_id: Optional[str] = None
        container_ran_to_completion = False
        timed_out = False
        exit_code: Optional[int] = None
        container_obj = None

        try:
            run_kwargs = {
                "detach": True, # Essential for background run and wait
                "command": current_config.command,
                "ports": current_config.ports,
                "volumes": current_config.volumes,
                "environment": current_config.environment,
                # name for the container itself, can be useful for debugging
                "name": f"sandbox_{current_config.name}_{int(time.time())}" 
            }
            # Filter out None values for kwargs passed to docker_manager.run
            run_kwargs_filtered = {k: v for k, v in run_kwargs.items() if v is not None}

            container_id = self.docker_manager.run(current_config.image, **run_kwargs_filtered)
            if not container_id: # Should be caught by exceptions in docker_manager.run, but as a safeguard
                logger.error(f"Sandbox '{current_config.name}': Failed to start container (no ID returned). Image: {current_config.image}")
                return False, None

            logger.info(f"Sandbox '{current_config.name}': Container {container_id} started. Streaming logs.")
            # Stream logs. DockerManager.logs with stream=True currently logs via logger.info.
            # follow=False makes it non-blocking in terms of waiting for container to finish.
            # timestamps=True for more informative logs.
            self.docker_manager.logs(container_id, stream=True, follow=False, timestamps=True, tail="all")
            
            container_obj = self.docker_manager.client.containers.get(container_id)
            logger.info(f"Sandbox '{current_config.name}': Waiting for container {container_id} to complete (timeout: {current_config.timeout}s).")
            
            try:
                wait_result = container_obj.wait(timeout=current_config.timeout)
                exit_code = wait_result.get('StatusCode')
                container_ran_to_completion = True
                logger.info(f"Sandbox '{current_config.name}': Container {container_id} completed with exit code: {exit_code}.")
            except requests.exceptions.ReadTimeout: # This is what docker SDK raises for timeout on wait()
                timed_out = True
                logger.warning(f"Sandbox '{current_config.name}': Container {container_id} timed out after {current_config.timeout}s.")
                # Attempt to get exit code if possible, though it might not be available if killed
                try:
                    status = container_obj.attrs.get('State', {})
                    if status.get('Running') is False and status.get('ExitCode') is not None:
                        exit_code = status.get('ExitCode')
                        logger.info(f"Sandbox '{current_config.name}': Container {container_id} (timed out) reported exit code {exit_code} after being stopped/killed.")
                except Exception as e_attrs:
                    logger.warning(f"Sandbox '{current_config.name}': Could not retrieve exit code for timed out container {container_id}: {e_attrs}")
            except docker.errors.APIError as e: # Other API errors during wait
                 logger.error(f"Sandbox '{current_config.name}': APIError while waiting for container {container_id}: {e}")
                 # Try to get exit code if container is stopped
                 try:
                    status = container_obj.attrs.get('State', {})
                    if status.get('Running') is False and status.get('ExitCode') is not None:
                        exit_code = status.get('ExitCode')
                 except Exception:
                    pass # Ignore if we can't get it

        except docker.errors.ImageNotFound:
            logger.error(f"Sandbox '{current_config.name}': Image '{current_config.image}' not found. Cannot run sandbox.")
            return False, None # No container_id, cleanup not applicable
        except docker.errors.APIError as e:
            logger.error(f"Sandbox '{current_config.name}': APIError during container run/setup for image '{current_config.image}': {e}")
            # If container_id was set before error, it might need cleanup
            # but often these errors are before container_id is available.
            if container_id:
                logger.info(f"Attempting cleanup for container {container_id} due to APIError during setup/run.")
                self.docker_manager.rm(container_id, force=True) # Force remove as state is uncertain
            return False, None 
        except Exception as e: # Catch-all for other unexpected errors
            logger.error(f"Sandbox '{current_config.name}': Unexpected error: {e}", exc_info=True)
            if container_id: # If container exists, try to clean up based on a default policy or always_remove
                logger.warning(f"Sandbox '{current_config.name}': Unexpected error. Attempting to force remove container {container_id}.")
                self.docker_manager.rm(container_id, force=True)
            return False, None
        finally:
            # Cleanup logic
            if container_id:
                succeeded_by_exit_code = exit_code is not None and exit_code in current_config.success_exit_codes
                
                should_remove = False
                if current_config.cleanup_policy == "always_remove":
                    should_remove = True
                    logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'always_remove'. Marking for removal.")
                elif current_config.cleanup_policy == "never_remove":
                    should_remove = False
                    logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'never_remove'. Skipping removal.")
                elif current_config.cleanup_policy == "remove_on_completion":
                    if container_ran_to_completion and succeeded_by_exit_code:
                        should_remove = True
                        logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'remove_on_completion', completed successfully (exit {exit_code}). Marking for removal.")
                    elif container_ran_to_completion and not succeeded_by_exit_code:
                         logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'remove_on_completion', completed with failure (exit {exit_code}). Keeping container.")
                    elif timed_out: # Did not complete
                         logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'remove_on_completion', but timed out. Keeping container.")
                elif current_config.cleanup_policy == "keep_on_completion":
                    if container_ran_to_completion:
                        should_remove = False
                        logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'keep_on_completion', completed. Keeping container.")
                    elif timed_out: # Did not complete, so policy implies removal if it didn't complete
                        should_remove = True
                        logger.warning(f"Sandbox '{current_config.name}' ({container_id}): Policy 'keep_on_completion', but timed out. Marking for removal.")
                elif current_config.cleanup_policy == "remove_on_timeout":
                    if timed_out:
                        should_remove = True
                        logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'remove_on_timeout', and it timed out. Marking for removal.")
                    else: # Did not time out
                        logger.info(f"Sandbox '{current_config.name}' ({container_id}): Policy 'remove_on_timeout', but did not time out (exit {exit_code}). Keeping container.")

                if should_remove:
                    logger.info(f"Sandbox '{current_config.name}': Attempting to stop and remove container {container_id}.")
                    # Ensure container is stopped before removal, especially if it timed out and might still be running.
                    # If container_obj is available and its status is 'running', stop it.
                    stopped_before_rm = False
                    try:
                        if container_obj: # container_obj might not be set if run failed very early
                            container_obj.reload() # refresh attributes
                            if container_obj.status == 'running':
                                logger.debug(f"Sandbox '{current_config.name}': Container {container_id} is still running. Stopping before removal.")
                                self.docker_manager.stop(container_id, timeout=5) # Short timeout for stop
                                stopped_before_rm = True
                                logger.debug(f"Sandbox '{current_config.name}': Container {container_id} stopped.")
                    except docker.errors.NotFound:
                        logger.warning(f"Sandbox '{current_config.name}': Container {container_id} not found when trying to stop it before removal. Already removed or never fully started.")
                    except docker.errors.APIError as e:
                        logger.error(f"Sandbox '{current_config.name}': APIError stopping container {container_id} before removal: {e}. Proceeding with rm attempt.")
                    
                    rm_success = self.docker_manager.rm(container_id, force=True) # Force remove if stop failed or if it's stuck
                    if rm_success:
                        logger.info(f"Sandbox '{current_config.name}': Container {container_id} removed successfully.")
                    else:
                        logger.warning(f"Sandbox '{current_config.name}': Failed to remove container {container_id}.")
                else:
                    logger.info(f"Sandbox '{current_config.name}': Container {container_id} will be kept based on cleanup policy '{current_config.cleanup_policy}'.")

        # Determine overall success
        # Success means it ran (or was intended to run but failed in a way that gives an exit code)
        # AND the exit code is in the list of success_exit_codes.
        # If it timed out, it's generally not a "success" in terms of exit code.
        # If image not found, it's not a success.
        # If API error prevented run, not a success.
        
        # We define "success" as: the sandbox was configured, an attempt was made to run it,
        # it produced an exit code (i.e., it didn't time out AND fail to report one),
        # and that exit code is considered successful.
        final_success_status = container_ran_to_completion and exit_code is not None and exit_code in current_config.success_exit_codes
        
        if timed_out and final_success_status:
            # If it timed out, but somehow we got a success exit code (e.g. process exited just before timeout kill)
            # we might still consider it a failure due to timeout. For now, exit code takes precedence.
            logger.info(f"Sandbox '{current_config.name}' completed with a success exit code {exit_code} but also hit timeout. Considered success by exit code.")


        logger.info(f"Sandbox '{current_config.name}' finished. Overall success: {final_success_status}, Exit Code: {exit_code}, Timed Out: {timed_out}")
        return final_success_status, exit_code


if __name__ == '__main__':
    # Example usage (requires a DockerManager instance and a sandboxes.yml)
    # This is for basic testing if run directly, not part of the module's normal use.
    logger.info("Running SandboxRunner directly for basic module structure check.")
    try:
        dm = DockerManager() # Assumes Docker is running
        # Create a dummy sandboxes.yml for this direct run test
        dummy_sandbox_file = "dummy_sandboxes.yml"
        with open(dummy_sandbox_file, "w") as f:
            yaml.dump({"sandboxes": [{"name": "test_dummy", "image": "alpine", "command": ["echo", "hello from dummy"]}]}, f)
        
        sr = SandboxRunner(docker_manager=dm, sandbox_file_path=dummy_sandbox_file)
        if "test_dummy" in sr.sandboxes:
            logger.info("Dummy sandbox 'test_dummy' loaded successfully for direct run test.")
        else:
            logger.error("Failed to load dummy sandbox for direct run test.")
        os.remove(dummy_sandbox_file) # Clean up dummy file
    except docker.errors.DockerException as de:
        logger.error(f"Docker not available for direct run test: {de}")
    except Exception as e:
        logger.error(f"Error during direct run test of SandboxRunner: {e}", exc_info=True)
