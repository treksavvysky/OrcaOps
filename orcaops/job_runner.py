import os
import json
import hashlib
import shlex
import time
import shutil
import threading
import queue
from typing import List, Optional, Tuple
from datetime import datetime, timezone

from orcaops import logger
from orcaops.docker_manager import DockerManager
from orcaops.schemas import (
    JobSpec, RunRecord, StepResult, ArtifactMetadata,
    JobStatus, CleanupStatus, JobCommand
)

class JobRunner:
    def __init__(self, output_dir: str = "artifacts"):
        self.dm = DockerManager()
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _compute_fingerprint(self, spec: JobSpec) -> str:
        """Computes a deterministic fingerprint of inputs."""
        # image + commands + env + artifact spec
        data = {
            "image": spec.sandbox.image,
            "commands": [c.model_dump() for c in spec.commands],
            "env": spec.sandbox.env,
            "artifacts": spec.artifacts
        }
        # Use json.dumps with sort_keys to ensure determinism
        canonical = json.dumps(data, sort_keys=True).encode('utf-8')
        return hashlib.sha256(canonical).hexdigest()

    def run_sandbox_job(self, job_spec: JobSpec) -> RunRecord:
        """
        Executes a job in a sandbox container.
        ASSUMPTIONS:
        - The container image MUST contain basic shell utilities: /bin/sh, find, tar.
        - Docker socket is available.
        """
        run_id = job_spec.job_id
        job_dir = os.path.join(self.output_dir, run_id)
        os.makedirs(job_dir, exist_ok=True)

        fingerprint = self._compute_fingerprint(job_spec)

        record = RunRecord(
            job_id=run_id,
            status=JobStatus.QUEUED,
            fingerprint=fingerprint,
            sandbox_id=None,
            image_ref=job_spec.sandbox.image
        )

        container_id = None
        start_time = datetime.now(timezone.utc)
        record.started_at = start_time
        record.status = JobStatus.RUNNING

        try:
            # 1. Start Sandbox
            logger.info(f"Starting sandbox for job {run_id}")

            run_kwargs = {
                "detach": True,
                "command": ["sleep", "infinity"], # Keep alive
                "environment": job_spec.sandbox.env,
                "labels": {
                    "orcaops.job_id": run_id,
                    "orcaops.ttl": str(job_spec.ttl_seconds),
                    "orcaops.created_at": str(start_time.timestamp())
                }
            }
            if job_spec.sandbox.resources:
                # Map resources if needed.
                pass

            container_id = self.dm.run(
                job_spec.sandbox.image,
                **run_kwargs
            )
            record.sandbox_id = container_id

            # 2. Run Commands
            for cmd in job_spec.commands:
                logger.info(f"Running step: {cmd.command}")
                step_start = time.time()

                # Use low-level API to separate stdout/stderr
                # Assuming simple shell execution
                exec_cmd = ["/bin/sh", "-c", cmd.command]

                stdout_str = ""
                stderr_str = ""
                exit_code = -1

                try:
                    exec_response = self.dm.client.api.exec_create(
                        container_id, exec_cmd, workdir=cmd.cwd or "/"
                    )
                    exec_id = exec_response['Id']

                    output_gen = self.dm.client.api.exec_start(exec_id, stream=True, demux=True)

                    # Consume with timeout
                    stdout_str, stderr_str, timed_out = self._read_output_with_timeout(
                        output_gen, cmd.timeout_seconds
                    )

                    if timed_out:
                        exit_code = 124 # Common timeout exit code
                        stderr_str += f"\nCommand timed out after {cmd.timeout_seconds} seconds."
                        logger.error(f"Command timed out: {cmd.command}")
                    else:
                        exit_code = self.dm.client.api.exec_inspect(exec_id).get('ExitCode')

                except Exception as e:
                    logger.error(f"Error executing command: {e}")
                    stderr_str = f"Execution error: {str(e)}"
                    exit_code = -1

                duration = time.time() - step_start

                step_result = StepResult(
                    command=cmd.command,
                    exit_code=exit_code if exit_code is not None else -1,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    duration_seconds=duration
                )
                record.steps.append(step_result)

                if exit_code != 0:
                    record.status = JobStatus.TIMED_OUT if exit_code == 124 else JobStatus.FAILED
                    logger.warning(f"Command failed: {cmd.command} (Exit: {exit_code})")
                    break
            else:
                record.status = JobStatus.SUCCESS

            # 3. Collect Artifacts
            for artifact_pattern in job_spec.artifacts:
                logger.info(f"Collecting artifact pattern: {artifact_pattern}")
                # Safer glob resolution using find -print0
                # Using sh -c to allow glob expansion if user provided wildcards
                find_cmd = ["/bin/sh", "-c", f"find {shlex.quote(artifact_pattern)} -maxdepth 0 -print0 2>/dev/null"]

                try:
                    # We need raw output (bytes) for null separator, exec_command returns string.
                    # exec_command in DM decodes utf-8.
                    ec, paths_str = self.dm.exec_command(container_id, find_cmd)

                    if ec == 0 and paths_str:
                        # paths_str contains \x00 separators but decoded as string
                        paths = paths_str.split('\x00')
                        for path in paths:
                            path = path.strip()
                            if not path: continue

                            filename = os.path.basename(path)
                            try:
                                self.dm.copy_from(container_id, path, job_dir)

                                expected_path = os.path.join(job_dir, filename)
                                if os.path.exists(expected_path):
                                    size = 0
                                    if os.path.isfile(expected_path):
                                        size = os.path.getsize(expected_path)

                                    sha = "N/A"
                                    if os.path.isfile(expected_path):
                                        sha = self._hash_file(expected_path)

                                    record.artifacts.append(ArtifactMetadata(
                                        name=filename,
                                        path=filename,
                                        size_bytes=size,
                                        sha256=sha
                                    ))

                            except Exception as e:
                                logger.error(f"Failed to collect artifact {path}: {e}")
                except Exception as e:
                    logger.warning(f"Error resolving artifact pattern {artifact_pattern}: {e}")


        except Exception as e:
            record.status = JobStatus.FAILED
            record.error = str(e)
            logger.error(f"Job failed with exception: {e}", exc_info=True)

        finally:
            record.finished_at = datetime.now(timezone.utc)

            # Destroy Sandbox
            if container_id:
                logger.info(f"Destroying sandbox {container_id}")
                try:
                    self.dm.rm(container_id, force=True)
                    record.cleanup_status = CleanupStatus.DESTROYED
                except Exception as e:
                    logger.error(f"Failed to destroy sandbox {container_id}: {e}")
                    record.cleanup_status = CleanupStatus.LEAKED
                    record.ttl_expiry = datetime.now(timezone.utc)
            else:
                 record.cleanup_status = CleanupStatus.DESTROYED

            # Write Run Record
            try:
                with open(os.path.join(job_dir, "run.json"), "w") as f:
                    f.write(record.model_dump_json(indent=2))

                with open(os.path.join(job_dir, "steps.jsonl"), "w") as f:
                    for step in record.steps:
                        f.write(step.model_dump_json() + "\n")
            except Exception as e:
                logger.error(f"Failed to write run record/logs: {e}")

        return record

    def _read_output_with_timeout(self, output_gen, timeout_sec) -> Tuple[str, str, bool]:
        """Reads from output generator with timeout."""
        q = queue.Queue()

        def reader():
            try:
                for chunk in output_gen:
                    q.put(chunk)
            except Exception as e:
                q.put(e)
            finally:
                q.put(None)

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        stdout_acc = []
        stderr_acc = []
        timed_out = False
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            remaining = timeout_sec - elapsed

            if remaining <= 0:
                timed_out = True
                break

            try:
                # Wait for chunk with small timeout
                item = q.get(timeout=min(0.5, remaining))

                if item is None:
                    break

                if isinstance(item, Exception):
                    logger.warning(f"Exception reading stream: {item}")
                    break

                stdout_chunk, stderr_chunk = item
                if stdout_chunk:
                    stdout_acc.append(stdout_chunk.decode('utf-8', errors='replace'))
                if stderr_chunk:
                    stderr_acc.append(stderr_chunk.decode('utf-8', errors='replace'))

            except queue.Empty:
                continue

        return "".join(stdout_acc), "".join(stderr_acc), timed_out

    def _hash_file(self, filepath: str) -> str:
        sha = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(8192):
                    sha.update(chunk)
            return sha.hexdigest()
        except Exception:
            return "hash_error"

def cleanup_expired_sandboxes():
    """Stub for sweeper function."""
    pass
