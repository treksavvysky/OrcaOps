"""
OrcaOps MCP Server — exposes OrcaOps capabilities via Model Context Protocol.

Run with: orcaops-mcp (stdio transport for Claude Code integration)
"""

import base64
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from orcaops.schemas import (
    JobSpec,
    SandboxSpec,
    JobCommand,
    JobStatus,
    RunRecord,
    WorkflowStatus,
)

server = FastMCP(
    name="orcaops",
    instructions=(
        "OrcaOps: AI-native Docker container management and sandbox orchestration. "
        "Run sandboxed jobs in containers, manage sandbox projects, inspect containers, "
        "and retrieve execution results and artifacts."
    ),
)

_TERMINAL_STATUSES = {
    JobStatus.SUCCESS,
    JobStatus.FAILED,
    JobStatus.TIMED_OUT,
    JobStatus.CANCELLED,
}

# ---------------------------------------------------------------------------
# Lazy-initialized singletons (avoid import-time Docker/filesystem access)
# ---------------------------------------------------------------------------

_jm = None
_rs = None
_dm = None
_registry = None
_wm = None
_ws = None


def _job_manager():
    global _jm
    if _jm is None:
        from orcaops.job_manager import JobManager
        _jm = JobManager()
    return _jm


def _run_store():
    global _rs
    if _rs is None:
        from orcaops.run_store import RunStore
        _rs = RunStore()
    return _rs


def _docker_manager():
    global _dm
    if _dm is None:
        from orcaops.docker_manager import DockerManager
        _dm = DockerManager()
    return _dm


def _sandbox_registry():
    global _registry
    if _registry is None:
        from orcaops.sandbox_registry import get_registry
        _registry = get_registry()
    return _registry


def _workflow_manager():
    global _wm
    if _wm is None:
        from orcaops.workflow_manager import WorkflowManager
        _wm = WorkflowManager(job_manager=_job_manager())
    return _wm


def _workflow_store():
    global _ws
    if _ws is None:
        from orcaops.workflow_store import WorkflowStore
        _ws = WorkflowStore()
    return _ws


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _success(**kwargs) -> str:
    return json.dumps({"success": True, **kwargs}, default=str)


def _error(code: str, message: str, suggestion: str = "") -> str:
    err = {"code": code, "message": message}
    if suggestion:
        err["suggestion"] = suggestion
    return json.dumps({"success": False, "error": err})


def _record_to_dict(record: RunRecord) -> dict:
    data = json.loads(record.model_dump_json())
    return data


# ===================================================================
# Job Execution Tools
# ===================================================================

@server.tool(
    name="orcaops_run_job",
    description=(
        "Run a command in a Docker container and wait for results. "
        "This is the primary tool for executing code in a sandboxed environment. "
        "Returns the full result including stdout, stderr, exit codes, and artifacts."
    ),
)
def orcaops_run_job(
    image: str,
    commands: List[str],
    env: Optional[Dict[str, str]] = None,
    artifacts: Optional[List[str]] = None,
    timeout: int = 300,
    job_id: Optional[str] = None,
    intent: Optional[str] = None,
    tags: Optional[List[str]] = None,
    triggered_by: str = "mcp",
) -> str:
    """Run commands in a Docker container and wait for completion."""
    try:
        jm = _job_manager()
        jid = job_id or f"mcp-{uuid.uuid4().hex[:12]}"

        spec = JobSpec(
            job_id=jid,
            sandbox=SandboxSpec(image=image, env=env or {}),
            commands=[JobCommand(command=cmd, timeout_seconds=timeout) for cmd in commands],
            artifacts=list(artifacts or []),
            ttl_seconds=timeout,
            triggered_by=triggered_by,
            intent=intent,
            tags=list(tags or []),
        )

        jm.submit_job(spec)

        # Poll until terminal status
        deadline = time.time() + timeout + 30  # extra grace period
        while time.time() < deadline:
            record = jm.get_job(jid)
            if record and record.status in _TERMINAL_STATUSES:
                return _success(
                    job_id=jid,
                    status=record.status.value,
                    steps=[
                        {
                            "command": s.command,
                            "exit_code": s.exit_code,
                            "stdout": s.stdout,
                            "stderr": s.stderr,
                            "duration_seconds": s.duration_seconds,
                        }
                        for s in record.steps
                    ],
                    artifacts=[
                        {"name": a.name, "size_bytes": a.size_bytes, "sha256": a.sha256}
                        for a in record.artifacts
                    ],
                    error=record.error,
                )
            time.sleep(1)

        return _error(
            "JOB_TIMEOUT",
            f"Job '{jid}' did not complete within {timeout}s.",
            "Use orcaops_get_job_status to check progress, or orcaops_cancel_job to cancel.",
        )
    except ValueError as exc:
        return _error("VALIDATION_ERROR", str(exc))
    except Exception as exc:
        return _error("RUN_JOB_ERROR", str(exc))


@server.tool(
    name="orcaops_submit_job",
    description=(
        "Submit a job for execution without waiting for completion. "
        "Returns immediately with the job_id. Use orcaops_get_job_status to poll."
    ),
)
def orcaops_submit_job(
    image: str,
    commands: List[str],
    env: Optional[Dict[str, str]] = None,
    artifacts: Optional[List[str]] = None,
    timeout: int = 300,
    job_id: Optional[str] = None,
    intent: Optional[str] = None,
    tags: Optional[List[str]] = None,
    triggered_by: str = "mcp",
) -> str:
    """Submit a job without waiting. Returns job_id for later polling."""
    try:
        jm = _job_manager()
        jid = job_id or f"mcp-{uuid.uuid4().hex[:12]}"

        spec = JobSpec(
            job_id=jid,
            sandbox=SandboxSpec(image=image, env=env or {}),
            commands=[JobCommand(command=cmd, timeout_seconds=timeout) for cmd in commands],
            artifacts=list(artifacts or []),
            ttl_seconds=timeout,
            triggered_by=triggered_by,
            intent=intent,
            tags=list(tags or []),
        )

        record = jm.submit_job(spec)
        return _success(
            job_id=record.job_id,
            status=record.status.value,
            message="Job submitted. Use orcaops_get_job_status to check progress.",
        )
    except ValueError as exc:
        return _error("VALIDATION_ERROR", str(exc))
    except Exception as exc:
        return _error("SUBMIT_JOB_ERROR", str(exc))


@server.tool(
    name="orcaops_get_job_status",
    description="Get the current status and details of a job by its ID.",
)
def orcaops_get_job_status(job_id: str) -> str:
    """Check status of a submitted job."""
    try:
        jm = _job_manager()
        record = jm.get_job(job_id)
        if not record:
            rs = _run_store()
            record = rs.get_run(job_id)
        if not record:
            return _error(
                "JOB_NOT_FOUND",
                f"Job '{job_id}' not found.",
                "Use orcaops_list_jobs to see available jobs.",
            )
        return _success(**_record_to_dict(record))
    except Exception as exc:
        return _error("GET_STATUS_ERROR", str(exc))


@server.tool(
    name="orcaops_get_job_logs",
    description="Get stdout and stderr output from a job's executed steps.",
)
def orcaops_get_job_logs(job_id: str) -> str:
    """Retrieve step output for a job."""
    try:
        jm = _job_manager()
        record = jm.get_job(job_id)
        if not record:
            rs = _run_store()
            record = rs.get_run(job_id)
        if not record:
            return _error(
                "JOB_NOT_FOUND",
                f"Job '{job_id}' not found.",
                "Use orcaops_list_jobs to see available jobs.",
            )
        if not record.steps:
            return _success(
                job_id=job_id,
                status=record.status.value,
                steps=[],
                message="No step output available yet.",
            )
        return _success(
            job_id=job_id,
            status=record.status.value,
            steps=[
                {
                    "command": s.command,
                    "exit_code": s.exit_code,
                    "stdout": s.stdout,
                    "stderr": s.stderr,
                    "duration_seconds": s.duration_seconds,
                }
                for s in record.steps
            ],
        )
    except Exception as exc:
        return _error("GET_LOGS_ERROR", str(exc))


@server.tool(
    name="orcaops_list_jobs",
    description="List recent jobs with optional status filter.",
)
def orcaops_list_jobs(
    status: Optional[str] = None,
    limit: int = 20,
) -> str:
    """List recent jobs."""
    try:
        jm = _job_manager()
        status_filter = JobStatus(status) if status else None
        records = jm.list_jobs(status=status_filter)
        sliced = records[:limit]
        return _success(
            jobs=[
                {
                    "job_id": r.job_id,
                    "status": r.status.value,
                    "image": r.image_ref,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in sliced
            ],
            count=len(records),
        )
    except ValueError:
        valid = [s.value for s in JobStatus]
        return _error("INVALID_STATUS", f"Invalid status. Valid values: {valid}")
    except Exception as exc:
        return _error("LIST_JOBS_ERROR", str(exc))


@server.tool(
    name="orcaops_cancel_job",
    description="Cancel a running or queued job.",
)
def orcaops_cancel_job(job_id: str) -> str:
    """Cancel a job by ID."""
    try:
        jm = _job_manager()
        cancelled, record = jm.cancel_job(job_id)
        if not cancelled:
            return _error(
                "JOB_NOT_FOUND",
                f"Job '{job_id}' not found or already completed.",
                "Use orcaops_list_jobs to see active jobs.",
            )
        return _success(
            job_id=job_id,
            status=record.status.value,
            message=f"Job '{job_id}' cancelled.",
        )
    except Exception as exc:
        return _error("CANCEL_JOB_ERROR", str(exc))


@server.tool(
    name="orcaops_list_artifacts",
    description="List artifacts collected from a completed job.",
)
def orcaops_list_artifacts(job_id: str) -> str:
    """List artifacts for a job."""
    try:
        jm = _job_manager()
        record = jm.get_job(job_id)
        if not record:
            rs = _run_store()
            record = rs.get_run(job_id)
        if not record:
            return _error(
                "JOB_NOT_FOUND",
                f"Job '{job_id}' not found.",
                "Use orcaops_list_jobs to see available jobs.",
            )
        artifacts = record.artifacts
        if not artifacts:
            names = jm.list_artifacts(job_id)
            return _success(
                job_id=job_id,
                artifacts=[{"name": n} for n in names],
                count=len(names),
            )
        return _success(
            job_id=job_id,
            artifacts=[
                {"name": a.name, "size_bytes": a.size_bytes, "sha256": a.sha256}
                for a in artifacts
            ],
            count=len(artifacts),
        )
    except Exception as exc:
        return _error("LIST_ARTIFACTS_ERROR", str(exc))


@server.tool(
    name="orcaops_get_artifact",
    description=(
        "Read the contents of a job artifact. "
        "Returns text content directly, or base64-encoded content for binary files."
    ),
)
def orcaops_get_artifact(job_id: str, filename: str) -> str:
    """Read artifact content from a completed job."""
    try:
        jm = _job_manager()
        path = jm.get_artifact(job_id, filename)
        if not path:
            return _error(
                "ARTIFACT_NOT_FOUND",
                f"Artifact '{filename}' not found for job '{job_id}'.",
                "Use orcaops_list_artifacts to see available artifacts.",
            )

        # Path traversal check
        job_dir = os.path.realpath(os.path.join(jm.output_dir, job_id))
        real_path = os.path.realpath(path)
        if not real_path.startswith(job_dir + os.sep):
            return _error("INVALID_PATH", "Invalid artifact path.")

        try:
            with open(real_path, "r", encoding="utf-8") as f:
                content = f.read()
            return _success(
                job_id=job_id,
                filename=filename,
                encoding="text",
                content=content,
            )
        except UnicodeDecodeError:
            with open(real_path, "rb") as f:
                raw = f.read()
            return _success(
                job_id=job_id,
                filename=filename,
                encoding="base64",
                content=base64.b64encode(raw).decode("ascii"),
                size_bytes=len(raw),
            )
    except Exception as exc:
        return _error("GET_ARTIFACT_ERROR", str(exc))


# ===================================================================
# Sandbox Management Tools
# ===================================================================

@server.tool(
    name="orcaops_list_sandboxes",
    description="List all registered sandbox projects with their status and paths.",
)
def orcaops_list_sandboxes(validate: bool = False) -> str:
    """List registered sandboxes."""
    try:
        registry = _sandbox_registry()
        sandboxes = registry.list_all()
        result = []
        for s in sandboxes:
            entry = {
                "name": s.name,
                "template": s.template,
                "path": s.path,
                "created_at": s.created_at,
                "status": s.status,
            }
            if validate:
                validation = registry.validate_sandbox(s.name)
                entry["validation"] = validation
            result.append(entry)
        return _success(sandboxes=result, count=len(result))
    except Exception as exc:
        return _error("LIST_SANDBOXES_ERROR", str(exc))


@server.tool(
    name="orcaops_get_sandbox",
    description="Get details about a specific registered sandbox project.",
)
def orcaops_get_sandbox(name: str) -> str:
    """Get sandbox details by name."""
    try:
        registry = _sandbox_registry()
        sandbox = registry.get(name)
        if not sandbox:
            return _error(
                "SANDBOX_NOT_FOUND",
                f"Sandbox '{name}' not found.",
                "Use orcaops_list_sandboxes to see available sandboxes.",
            )
        validation = registry.validate_sandbox(name)
        return _success(
            name=sandbox.name,
            template=sandbox.template,
            path=sandbox.path,
            created_at=sandbox.created_at,
            status=sandbox.status,
            validation=validation,
        )
    except Exception as exc:
        return _error("GET_SANDBOX_ERROR", str(exc))


@server.tool(
    name="orcaops_create_sandbox",
    description=(
        "Create a new sandbox project from a template. "
        "Available templates: web-dev, python-ml, api-testing."
    ),
)
def orcaops_create_sandbox(
    template: str,
    name: str,
    directory: Optional[str] = None,
) -> str:
    """Create a sandbox from a template."""
    try:
        from orcaops.sandbox_templates_simple import SandboxTemplates, TemplateManager

        if not TemplateManager.validate_template_name(template):
            available = list(SandboxTemplates.get_templates().keys())
            return _error(
                "INVALID_TEMPLATE",
                f"Template '{template}' not found.",
                f"Available templates: {available}",
            )

        registry = _sandbox_registry()
        if registry.exists(name):
            return _error(
                "SANDBOX_EXISTS",
                f"Sandbox '{name}' already exists.",
                "Choose a different name or use orcaops_get_sandbox to view the existing one.",
            )

        dest = directory or f"./{name}"
        success = TemplateManager.create_sandbox_from_template(template, name, dest)
        if not success:
            return _error("CREATE_FAILED", "Failed to create sandbox from template.")

        entry = registry.register(name, template, dest)
        return _success(
            name=entry.name,
            template=entry.template,
            path=entry.path,
            created_at=entry.created_at,
            message=f"Sandbox '{name}' created from template '{template}'.",
        )
    except Exception as exc:
        return _error("CREATE_SANDBOX_ERROR", str(exc))


@server.tool(
    name="orcaops_start_sandbox",
    description="Start a registered sandbox using docker-compose up.",
)
def orcaops_start_sandbox(name: str) -> str:
    """Start a sandbox (docker-compose up -d)."""
    try:
        registry = _sandbox_registry()
        sandbox = registry.get(name)
        if not sandbox:
            return _error(
                "SANDBOX_NOT_FOUND",
                f"Sandbox '{name}' not found.",
                "Use orcaops_list_sandboxes to see available sandboxes.",
            )

        validation = registry.validate_sandbox(name)
        if not validation["exists"]:
            return _error("DIR_NOT_FOUND", f"Sandbox directory not found: {sandbox.path}")
        if not validation["has_compose"]:
            return _error("NO_COMPOSE", f"No docker-compose.yml in {sandbox.path}")

        result = subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=sandbox.path,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            registry.update_status(name, "running")
            return _success(
                name=name,
                action="start",
                message=f"Sandbox '{name}' started.",
                output=result.stdout,
            )
        return _error("START_FAILED", f"docker-compose up failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        return _error("TIMEOUT", "Timeout waiting for sandbox to start.")
    except FileNotFoundError:
        return _error("DOCKER_COMPOSE_NOT_FOUND", "docker-compose not found on PATH.")
    except Exception as exc:
        return _error("START_SANDBOX_ERROR", str(exc))


@server.tool(
    name="orcaops_stop_sandbox",
    description="Stop a running sandbox using docker-compose down.",
)
def orcaops_stop_sandbox(name: str, volumes: bool = False) -> str:
    """Stop a sandbox (docker-compose down)."""
    try:
        registry = _sandbox_registry()
        sandbox = registry.get(name)
        if not sandbox:
            return _error(
                "SANDBOX_NOT_FOUND",
                f"Sandbox '{name}' not found.",
                "Use orcaops_list_sandboxes to see available sandboxes.",
            )

        validation = registry.validate_sandbox(name)
        if not validation["exists"]:
            return _error("DIR_NOT_FOUND", f"Sandbox directory not found: {sandbox.path}")

        cmd = ["docker-compose", "down"]
        if volumes:
            cmd.append("-v")

        result = subprocess.run(
            cmd,
            cwd=sandbox.path,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            registry.update_status(name, "stopped")
            return _success(
                name=name,
                action="stop",
                message=f"Sandbox '{name}' stopped.",
            )
        return _error("STOP_FAILED", f"docker-compose down failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        return _error("TIMEOUT", "Timeout waiting for sandbox to stop.")
    except FileNotFoundError:
        return _error("DOCKER_COMPOSE_NOT_FOUND", "docker-compose not found on PATH.")
    except Exception as exc:
        return _error("STOP_SANDBOX_ERROR", str(exc))


@server.tool(
    name="orcaops_list_templates",
    description="List available sandbox templates that can be used to create new sandboxes.",
)
def orcaops_list_templates() -> str:
    """List available templates."""
    try:
        from orcaops.sandbox_templates_simple import SandboxTemplates
        templates = SandboxTemplates.get_templates()
        result = []
        for tid, info in templates.items():
            result.append({
                "name": tid,
                "description": info["description"],
                "category": info.get("category", "General"),
                "services": list(info["services"].keys()),
            })
        return _success(templates=result, count=len(result))
    except Exception as exc:
        return _error("LIST_TEMPLATES_ERROR", str(exc))


@server.tool(
    name="orcaops_get_template",
    description="Get details about a specific sandbox template including its services.",
)
def orcaops_get_template(template_id: str) -> str:
    """Get template details."""
    try:
        from orcaops.sandbox_templates_simple import TemplateManager
        info = TemplateManager.get_template_info(template_id)
        if not info:
            return _error(
                "TEMPLATE_NOT_FOUND",
                f"Template '{template_id}' not found.",
                "Use orcaops_list_templates to see available templates.",
            )
        return _success(
            name=template_id,
            description=info["description"],
            category=info.get("category", "General"),
            services=list(info["services"].keys()),
        )
    except Exception as exc:
        return _error("GET_TEMPLATE_ERROR", str(exc))


# ===================================================================
# Container Management Tools
# ===================================================================

@server.tool(
    name="orcaops_list_containers",
    description="List Docker containers. By default shows only running containers.",
)
def orcaops_list_containers(all: bool = False) -> str:
    """List Docker containers."""
    try:
        dm = _docker_manager()
        containers = dm.list_running_containers(all=all)
        result = []
        for c in containers:
            image = c.image.tags[0] if c.image.tags else c.attrs.get("Config", {}).get("Image", "unknown")
            result.append({
                "id": c.short_id,
                "name": c.name,
                "image": image,
                "status": c.status,
            })
        return _success(containers=result, count=len(result))
    except Exception as exc:
        return _error("LIST_CONTAINERS_ERROR", str(exc))


@server.tool(
    name="orcaops_get_container_logs",
    description="Get logs from a Docker container.",
)
def orcaops_get_container_logs(container_id: str, tail: int = 100) -> str:
    """Get container logs."""
    try:
        dm = _docker_manager()
        logs = dm.logs(container_id, stream=False, tail=tail)
        return _success(container_id=container_id, logs=logs or "")
    except Exception as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower() or "404" in error_msg:
            return _error(
                "CONTAINER_NOT_FOUND",
                f"Container '{container_id}' not found.",
                "Use orcaops_list_containers to see available containers.",
            )
        return _error("GET_LOGS_ERROR", error_msg)


@server.tool(
    name="orcaops_inspect_container",
    description="Get detailed information about a Docker container.",
)
def orcaops_inspect_container(container_id: str) -> str:
    """Inspect a container."""
    try:
        dm = _docker_manager()
        attrs = dm.inspect(container_id)
        return _success(
            container_id=container_id,
            name=attrs.get("Name"),
            image=attrs.get("Config", {}).get("Image"),
            state=attrs.get("State"),
            network_settings=attrs.get("NetworkSettings", {}).get("Networks"),
            created=attrs.get("Created"),
        )
    except Exception as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower() or "404" in error_msg:
            return _error(
                "CONTAINER_NOT_FOUND",
                f"Container '{container_id}' not found.",
                "Use orcaops_list_containers to see available containers.",
            )
        return _error("INSPECT_ERROR", error_msg)


@server.tool(
    name="orcaops_stop_container",
    description="Stop a running Docker container.",
)
def orcaops_stop_container(container_id: str) -> str:
    """Stop a container."""
    try:
        dm = _docker_manager()
        success = dm.stop(container_id)
        if success:
            return _success(
                container_id=container_id,
                message=f"Container '{container_id}' stopped.",
            )
        return _error(
            "STOP_FAILED",
            f"Failed to stop container '{container_id}'. It may not exist or is already stopped.",
        )
    except Exception as exc:
        return _error("STOP_CONTAINER_ERROR", str(exc))


@server.tool(
    name="orcaops_remove_container",
    description="Remove a Docker container. Use force=True for running containers.",
)
def orcaops_remove_container(container_id: str, force: bool = False) -> str:
    """Remove a container."""
    try:
        dm = _docker_manager()
        success = dm.rm(container_id, force=force)
        if success:
            return _success(
                container_id=container_id,
                message=f"Container '{container_id}' removed.",
            )
        return _error(
            "REMOVE_FAILED",
            f"Failed to remove container '{container_id}'.",
            "Try with force=True if the container is running.",
        )
    except Exception as exc:
        return _error("REMOVE_CONTAINER_ERROR", str(exc))


# ===================================================================
# System Tools
# ===================================================================

@server.tool(
    name="orcaops_system_info",
    description="Get Docker daemon status and system information.",
)
def orcaops_system_info() -> str:
    """Get system and Docker info."""
    try:
        import platform
        dm = _docker_manager()
        docker_info = dm.client.info()
        return _success(
            python_version=sys.version.split()[0],
            platform=sys.platform,
            architecture=platform.machine(),
            docker=dict(
                version=docker_info.get("ServerVersion"),
                containers=docker_info.get("Containers"),
                containers_running=docker_info.get("ContainersRunning"),
                containers_paused=docker_info.get("ContainersPaused"),
                containers_stopped=docker_info.get("ContainersStopped"),
                images=docker_info.get("Images"),
                os=docker_info.get("OperatingSystem"),
                kernel=docker_info.get("KernelVersion"),
                memory_bytes=docker_info.get("MemTotal"),
                cpus=docker_info.get("NCPU"),
            ),
        )
    except Exception as exc:
        return _error("SYSTEM_INFO_ERROR", str(exc))


@server.tool(
    name="orcaops_cleanup_containers",
    description=(
        "Stop and remove all Docker containers. "
        "WARNING: This is a destructive operation."
    ),
)
def orcaops_cleanup_containers() -> str:
    """Stop and remove all containers."""
    try:
        dm = _docker_manager()
        report = dm.cleanup()
        return _success(
            stopped=report.get("stopped_containers", []),
            removed=report.get("removed_containers", []),
            errors=report.get("errors", []),
        )
    except Exception as exc:
        return _error("CLEANUP_ERROR", str(exc))


# ===================================================================
# Observability Tools
# ===================================================================

@server.tool(
    name="orcaops_get_job_summary",
    description=(
        "Get a deterministic summary of a job execution including one-liner, "
        "key events, errors, warnings, and suggestions."
    ),
)
def orcaops_get_job_summary(job_id: str) -> str:
    """Get a summary of a completed job."""
    try:
        jm = _job_manager()
        record = jm.get_job(job_id)
        if not record:
            rs = _run_store()
            record = rs.get_run(job_id)
        if not record:
            return _error(
                "JOB_NOT_FOUND",
                f"Job '{job_id}' not found.",
                "Use orcaops_list_jobs or orcaops_list_runs to see available jobs.",
            )

        from orcaops.log_analyzer import SummaryGenerator
        generator = SummaryGenerator()
        summary = generator.generate(record)
        return _success(**json.loads(summary.model_dump_json()))
    except Exception as exc:
        return _error("GET_SUMMARY_ERROR", str(exc))


@server.tool(
    name="orcaops_get_metrics",
    description=(
        "Get aggregate job metrics including success rates, durations, "
        "and per-image breakdown. Optionally filter by date range."
    ),
)
def orcaops_get_metrics(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> str:
    """Get aggregate job metrics."""
    try:
        from datetime import datetime
        from orcaops.metrics import MetricsAggregator

        rs = _run_store()
        aggregator = MetricsAggregator(rs)

        fd = datetime.fromisoformat(from_date) if from_date else None
        td = datetime.fromisoformat(to_date) if to_date else None

        metrics = aggregator.compute_metrics(from_date=fd, to_date=td)
        return _success(**{k: v for k, v in metrics.items()})
    except Exception as exc:
        return _error("GET_METRICS_ERROR", str(exc))


# ===================================================================
# Run History Tools
# ===================================================================

@server.tool(
    name="orcaops_list_runs",
    description="List historical job run records from disk with optional filters.",
)
def orcaops_list_runs(
    status: Optional[str] = None,
    image: Optional[str] = None,
    tags: Optional[List[str]] = None,
    triggered_by: Optional[str] = None,
    limit: int = 50,
) -> str:
    """List historical runs with optional filtering."""
    try:
        rs = _run_store()
        status_filter = JobStatus(status) if status else None
        records, total = rs.list_runs(
            status=status_filter,
            image=image,
            tags=tags,
            triggered_by=triggered_by,
            limit=limit,
        )
        return _success(
            runs=[
                {
                    "job_id": r.job_id,
                    "status": r.status.value,
                    "image": r.image_ref,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "triggered_by": r.triggered_by,
                    "tags": r.tags,
                }
                for r in records
            ],
            total=total,
        )
    except ValueError:
        valid = [s.value for s in JobStatus]
        return _error("INVALID_STATUS", f"Invalid status. Valid values: {valid}")
    except Exception as exc:
        return _error("LIST_RUNS_ERROR", str(exc))


@server.tool(
    name="orcaops_get_run",
    description="Get a specific historical run record by job ID.",
)
def orcaops_get_run(job_id: str) -> str:
    """Get a historical run record."""
    try:
        rs = _run_store()
        record = rs.get_run(job_id)
        if not record:
            return _error(
                "RUN_NOT_FOUND",
                f"Run '{job_id}' not found.",
                "Use orcaops_list_runs to see historical runs.",
            )
        return _success(**_record_to_dict(record))
    except Exception as exc:
        return _error("GET_RUN_ERROR", str(exc))


@server.tool(
    name="orcaops_delete_run",
    description="Delete a historical run record and its artifacts from disk.",
)
def orcaops_delete_run(job_id: str) -> str:
    """Delete a run record."""
    try:
        rs = _run_store()
        deleted = rs.delete_run(job_id)
        if not deleted:
            return _error(
                "RUN_NOT_FOUND",
                f"Run '{job_id}' not found.",
                "Use orcaops_list_runs to see historical runs.",
            )
        return _success(job_id=job_id, message=f"Run '{job_id}' deleted.")
    except Exception as exc:
        return _error("DELETE_RUN_ERROR", str(exc))


@server.tool(
    name="orcaops_cleanup_runs",
    description="Delete historical run records older than the specified number of days.",
)
def orcaops_cleanup_runs(older_than_days: int = 30) -> str:
    """Clean up old run records."""
    try:
        rs = _run_store()
        deleted = rs.cleanup_old_runs(older_than_days=older_than_days)
        return _success(
            deleted_count=len(deleted),
            deleted_job_ids=deleted,
            message=f"Deleted {len(deleted)} run(s) older than {older_than_days} days.",
        )
    except Exception as exc:
        return _error("CLEANUP_RUNS_ERROR", str(exc))


# ===================================================================
# Workflow Tools
# ===================================================================

_TERMINAL_WF_STATUSES = {
    WorkflowStatus.SUCCESS,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.PARTIAL,
}


@server.tool(
    name="orcaops_run_workflow",
    description=(
        "Submit a workflow from a spec dict and wait for completion. "
        "Returns the final workflow record with all job statuses."
    ),
)
def orcaops_run_workflow(
    spec: dict,
    workflow_id: Optional[str] = None,
    timeout: int = 3600,
) -> str:
    """Submit a workflow and poll until completion."""
    try:
        from orcaops.workflow_schema import parse_workflow_spec, WorkflowValidationError

        try:
            workflow_spec = parse_workflow_spec(spec)
        except (WorkflowValidationError, ValueError) as e:
            return _error("VALIDATION_ERROR", str(e))

        wm = _workflow_manager()
        wf_id = workflow_id or f"mcp-wf-{uuid.uuid4().hex[:12]}"
        record = wm.submit_workflow(workflow_spec, workflow_id=wf_id, triggered_by="mcp")

        # Poll until terminal status
        deadline = time.time() + timeout + 30
        while time.time() < deadline:
            record = wm.get_workflow(wf_id)
            if record and record.status in _TERMINAL_WF_STATUSES:
                return _success(
                    workflow_id=wf_id,
                    spec_name=record.spec_name,
                    status=record.status.value,
                    job_statuses={
                        name: {
                            "status": js.status.value,
                            "job_id": js.job_id,
                            "error": js.error,
                        }
                        for name, js in record.job_statuses.items()
                    },
                    error=record.error,
                )
            time.sleep(1)

        return _error(
            "WORKFLOW_TIMEOUT",
            f"Workflow '{wf_id}' did not complete within {timeout}s.",
            "Use orcaops_get_workflow_status to check progress, or orcaops_cancel_workflow to cancel.",
        )
    except ValueError as exc:
        return _error("VALIDATION_ERROR", str(exc))
    except Exception as exc:
        return _error("RUN_WORKFLOW_ERROR", str(exc))


@server.tool(
    name="orcaops_submit_workflow",
    description=(
        "Submit a workflow for execution without waiting for completion. "
        "Returns immediately with the workflow_id. Use orcaops_get_workflow_status to poll."
    ),
)
def orcaops_submit_workflow(
    spec: dict,
    workflow_id: Optional[str] = None,
) -> str:
    """Submit a workflow without waiting. Returns workflow_id for later polling."""
    try:
        from orcaops.workflow_schema import parse_workflow_spec, WorkflowValidationError

        try:
            workflow_spec = parse_workflow_spec(spec)
        except (WorkflowValidationError, ValueError) as e:
            return _error("VALIDATION_ERROR", str(e))

        wm = _workflow_manager()
        wf_id = workflow_id or f"mcp-wf-{uuid.uuid4().hex[:12]}"
        record = wm.submit_workflow(workflow_spec, workflow_id=wf_id, triggered_by="mcp")
        return _success(
            workflow_id=record.workflow_id,
            status=record.status.value,
            message="Workflow submitted. Use orcaops_get_workflow_status to check progress.",
        )
    except ValueError as exc:
        return _error("VALIDATION_ERROR", str(exc))
    except Exception as exc:
        return _error("SUBMIT_WORKFLOW_ERROR", str(exc))


@server.tool(
    name="orcaops_get_workflow_status",
    description="Get the current status and job details of a workflow by its ID.",
)
def orcaops_get_workflow_status(workflow_id: str) -> str:
    """Check status of a submitted workflow."""
    try:
        wm = _workflow_manager()
        record = wm.get_workflow(workflow_id)
        if not record:
            ws = _workflow_store()
            record = ws.get_workflow(workflow_id)
        if not record:
            return _error(
                "WORKFLOW_NOT_FOUND",
                f"Workflow '{workflow_id}' not found.",
                "Use orcaops_list_workflows to see available workflows.",
            )
        data = json.loads(record.model_dump_json())
        return _success(**data)
    except Exception as exc:
        return _error("GET_WORKFLOW_STATUS_ERROR", str(exc))


@server.tool(
    name="orcaops_cancel_workflow",
    description="Cancel a running or pending workflow.",
)
def orcaops_cancel_workflow(workflow_id: str) -> str:
    """Cancel a workflow by ID."""
    try:
        wm = _workflow_manager()
        cancelled, record = wm.cancel_workflow(workflow_id)
        if not cancelled:
            return _error(
                "WORKFLOW_NOT_FOUND",
                f"Workflow '{workflow_id}' not found or already completed.",
                "Use orcaops_list_workflows to see active workflows.",
            )
        return _success(
            workflow_id=workflow_id,
            status=record.status.value,
            message=f"Workflow '{workflow_id}' cancelled.",
        )
    except Exception as exc:
        return _error("CANCEL_WORKFLOW_ERROR", str(exc))


@server.tool(
    name="orcaops_list_workflows",
    description="List workflows with optional status filter.",
)
def orcaops_list_workflows(
    status: Optional[str] = None,
    limit: int = 50,
) -> str:
    """List workflows from memory and disk."""
    try:
        wm = _workflow_manager()
        ws = _workflow_store()

        status_filter = WorkflowStatus(status) if status else None
        active = wm.list_workflows(status=status_filter)
        historical, total = ws.list_workflows(status=status_filter, limit=limit)

        active_ids = {r.workflow_id for r in active}
        combined = list(active)
        for r in historical:
            if r.workflow_id not in active_ids:
                combined.append(r)

        combined.sort(key=lambda r: r.created_at, reverse=True)
        sliced = combined[:limit]

        return _success(
            workflows=[
                {
                    "workflow_id": r.workflow_id,
                    "spec_name": r.spec_name,
                    "status": r.status.value,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "job_count": len(r.job_statuses),
                    "triggered_by": r.triggered_by,
                }
                for r in sliced
            ],
            count=len(combined),
        )
    except ValueError:
        valid = [s.value for s in WorkflowStatus]
        return _error("INVALID_STATUS", f"Invalid status. Valid values: {valid}")
    except Exception as exc:
        return _error("LIST_WORKFLOWS_ERROR", str(exc))


# ===================================================================
# Entry point
# ===================================================================

def main():
    """Run the OrcaOps MCP server (stdio transport)."""
    debug = "--debug" in sys.argv
    if debug:
        server.settings.log_level = "DEBUG"
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
