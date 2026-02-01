import asyncio
import json as json_module
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from typing import List, Optional

import docker
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from orcaops.docker_manager import DockerManager
from orcaops.sandbox_templates_simple import SandboxTemplates, TemplateManager
from orcaops.sandbox_registry import get_registry
from orcaops.job_manager import JobManager
from orcaops.run_store import RunStore
from orcaops.schemas import (
    Container,
    ContainerInspect,
    CleanupReport,
    Template,
    TemplateList,
    Sandbox,
    SandboxList,
    SandboxValidation,
    SandboxActionResult,
    SandboxCreateRequest,
    JobSpec,
    JobStatus,
    JobSubmitResponse,
    JobStatusResponse,
    JobListResponse,
    JobCancelResponse,
    JobArtifactListResponse,
    ArtifactMetadata,
    RunListResponse,
    RunDeleteResponse,
    RunCleanupRequest,
    RunCleanupResponse,
    JobSummaryResponse,
    MetricsResponse,
    WorkflowStatus,
    WorkflowSubmitRequest,
    WorkflowSubmitResponse,
    WorkflowStatusResponse,
    WorkflowListResponse,
    WorkflowCancelResponse,
    WorkflowJobsResponse,
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    WorkspaceResponse,
    WorkspaceListResponse,
    WorkspaceStatus,
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeyResponse,
    APIKeyListResponse,
    Permission,
    SessionStatus,
    SessionResponse,
    SessionListResponse,
)
from orcaops.log_analyzer import SummaryGenerator
from orcaops.metrics import MetricsAggregator
from orcaops.workflow_manager import WorkflowManager
from orcaops.workflow_store import WorkflowStore
from orcaops.workflow_schema import WorkflowValidationError
from orcaops.workspace import WorkspaceRegistry
from orcaops.auth import KeyManager
from orcaops.auth_middleware import set_key_manager
from orcaops.session_manager import SessionManager

router = APIRouter()
docker_manager = DockerManager()
job_manager = JobManager()
run_store = RunStore()
workflow_manager = WorkflowManager(job_manager=job_manager)
workflow_store = WorkflowStore()
workspace_registry = WorkspaceRegistry()
key_manager = KeyManager()
set_key_manager(key_manager)
session_manager = SessionManager()


# Container Management Endpoints

@router.get("/ps", response_model=List[Container], summary="List containers")
async def list_containers(all: bool = Query(False, description="Show all containers (including stopped).")):
    """
    List Docker containers.
    - **all**: If true, show all containers. Otherwise, only running containers are shown.
    """
    try:
        containers = docker_manager.list_running_containers(all=all)
        return [
            Container(
                id=c.short_id,
                names=[c.name],
                image=c.image.tags[0] if c.image.tags else c.attrs['Config']['Image'],
                status=c.status,
            )
            for c in containers
        ]
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{container_id}", response_model=str, summary="Get container logs")
async def get_logs(container_id: str, tail: Optional[int] = Query(100, description="Number of lines to show from the end of the logs.")):
    """
    Get logs from a specific container.
    - **container_id**: The ID or name of the container.
    - **tail**: The number of lines to show from the end of the logs.
    """
    try:
        logs = docker_manager.logs(container_id, stream=False, tail=tail)
        return logs
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{container_id}' not found.")
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inspect/{container_id}", response_model=ContainerInspect, summary="Inspect a container")
async def inspect_container(container_id: str):
    """
    Inspect a container to see detailed information.
    - **container_id**: The ID or name of the container.
    """
    try:
        inspection_data = docker_manager.inspect(container_id)
        return ContainerInspect(
            id=inspection_data.get("Id"),
            name=inspection_data.get("Name"),
            image=inspection_data.get("Config", {}).get("Image"),
            state=inspection_data.get("State"),
            network_settings=inspection_data.get("NetworkSettings"),
        )
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{container_id}' not found.")
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop/{container_id}", summary="Stop a container")
async def stop_container(container_id: str):
    """
    Stop a running container.
    - **container_id**: The ID or name of the container.
    """
    try:
        docker_manager.stop(container_id)
        return {"message": f"Container '{container_id}' stopped successfully."}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{container_id}' not found.")
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rm/{container_id}", summary="Remove a container")
async def remove_container(container_id: str, force: bool = Query(False, description="Force removal of running container")):
    """
    Remove a container.
    - **container_id**: The ID or name of the container.
    - **force**: Force removal even if running.
    """
    try:
        docker_manager.rm(container_id, force=force)
        return {"message": f"Container '{container_id}' removed successfully."}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{container_id}' not found.")
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup", response_model=CleanupReport, summary="Cleanup all containers")
async def cleanup_containers():
    """
    Stop and remove all containers. This is a destructive operation.
    """
    try:
        report = docker_manager.cleanup()
        return report
    except docker.errors.DockerException as e:
        raise HTTPException(status_code=500, detail=str(e))


# Template Endpoints

@router.get("/templates", response_model=TemplateList, summary="List available sandbox templates")
async def list_templates():
    """
    Get a list of all available sandbox templates.
    """
    try:
        templates_dict = SandboxTemplates.get_templates()
        templates = [
            Template(
                name=template_id,
                description=info["description"],
                category=info.get("category", "General"),
                services=list(info["services"].keys())
            )
            for template_id, info in templates_dict.items()
        ]
        return TemplateList(templates=templates)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/{template_id}", response_model=Template, summary="Get template details")
async def get_template(template_id: str):
    """
    Get details about a specific template.
    - **template_id**: The template identifier (e.g., web-dev, python-ml, api-testing).
    """
    info = TemplateManager.get_template_info(template_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return Template(
        name=template_id,
        description=info["description"],
        category=info.get("category", "General"),
        services=list(info["services"].keys())
    )


# Sandbox Registry Endpoints

@router.get("/sandboxes", response_model=SandboxList, summary="List registered sandboxes")
async def list_sandboxes(validate: bool = Query(False, description="Include validation status")):
    """
    List all registered sandbox projects.
    - **validate**: If true, check if sandbox directories still exist.
    """
    registry = get_registry()
    sandboxes = registry.list_all()

    sandbox_list = [
        Sandbox(
            name=s.name,
            template=s.template,
            path=s.path,
            created_at=s.created_at,
            status=s.status
        )
        for s in sandboxes
    ]

    return SandboxList(sandboxes=sandbox_list, count=len(sandbox_list))


@router.get("/sandboxes/{name}", response_model=Sandbox, summary="Get sandbox details")
async def get_sandbox(name: str):
    """
    Get details about a specific sandbox.
    - **name**: The sandbox name.
    """
    registry = get_registry()
    sandbox = registry.get(name)

    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{name}' not found.")

    return Sandbox(
        name=sandbox.name,
        template=sandbox.template,
        path=sandbox.path,
        created_at=sandbox.created_at,
        status=sandbox.status
    )


@router.get("/sandboxes/{name}/validate", response_model=SandboxValidation, summary="Validate sandbox")
async def validate_sandbox(name: str):
    """
    Validate that a sandbox's directory and files exist.
    - **name**: The sandbox name.
    """
    registry = get_registry()

    if not registry.exists(name):
        raise HTTPException(status_code=404, detail=f"Sandbox '{name}' not found.")

    validation = registry.validate_sandbox(name)
    return SandboxValidation(
        name=name,
        exists=validation["exists"],
        has_compose=validation["has_compose"],
        has_env=validation["has_env"]
    )


@router.post("/sandboxes", response_model=Sandbox, summary="Create a new sandbox")
async def create_sandbox(request: SandboxCreateRequest):
    """
    Create a new sandbox from a template.
    - **template**: Template name (web-dev, python-ml, api-testing).
    - **name**: Name for the sandbox.
    - **directory**: Output directory (optional, defaults to ./{name}).
    """
    registry = get_registry()

    # Validate template
    if not TemplateManager.validate_template_name(request.template):
        available = list(SandboxTemplates.get_templates().keys())
        raise HTTPException(
            status_code=400,
            detail=f"Template '{request.template}' not found. Available: {available}"
        )

    # Check if name already exists
    if registry.exists(request.name):
        raise HTTPException(
            status_code=409,
            detail=f"Sandbox '{request.name}' already exists."
        )

    # Set directory
    directory = request.directory or f"./{request.name}"

    # Create sandbox
    success = TemplateManager.create_sandbox_from_template(
        request.template,
        request.name,
        directory
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to create sandbox.")

    # Register the sandbox
    entry = registry.register(request.name, request.template, directory)

    return Sandbox(
        name=entry.name,
        template=entry.template,
        path=entry.path,
        created_at=entry.created_at,
        status=entry.status
    )


@router.post("/sandboxes/{name}/up", response_model=SandboxActionResult, summary="Start a sandbox")
async def start_sandbox(name: str, detach: bool = Query(True, description="Run in background")):
    """
    Start a registered sandbox using docker-compose up.
    - **name**: The sandbox name.
    - **detach**: Run in background (default: true).
    """
    registry = get_registry()

    sandbox = registry.get(name)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{name}' not found.")

    validation = registry.validate_sandbox(name)
    if not validation["exists"]:
        raise HTTPException(
            status_code=400,
            detail=f"Sandbox directory not found: {sandbox.path}"
        )

    if not validation["has_compose"]:
        raise HTTPException(
            status_code=400,
            detail=f"No docker-compose.yml found in {sandbox.path}"
        )

    # Start the sandbox
    cmd = ["docker-compose", "up"]
    if detach:
        cmd.append("-d")

    try:
        result = subprocess.run(
            cmd,
            cwd=sandbox.path,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            registry.update_status(name, "running")
            return SandboxActionResult(
                name=name,
                action="up",
                success=True,
                message=f"Sandbox '{name}' started successfully."
            )
        else:
            return SandboxActionResult(
                name=name,
                action="up",
                success=False,
                message=f"Failed to start sandbox: {result.stderr}"
            )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout waiting for sandbox to start.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="docker-compose not found.")


@router.post("/sandboxes/{name}/down", response_model=SandboxActionResult, summary="Stop a sandbox")
async def stop_sandbox(name: str, volumes: bool = Query(False, description="Also remove volumes")):
    """
    Stop a registered sandbox using docker-compose down.
    - **name**: The sandbox name.
    - **volumes**: Also remove volumes (default: false).
    """
    registry = get_registry()

    sandbox = registry.get(name)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{name}' not found.")

    validation = registry.validate_sandbox(name)
    if not validation["exists"]:
        raise HTTPException(
            status_code=400,
            detail=f"Sandbox directory not found: {sandbox.path}"
        )

    # Stop the sandbox
    cmd = ["docker-compose", "down"]
    if volumes:
        cmd.append("-v")

    try:
        result = subprocess.run(
            cmd,
            cwd=sandbox.path,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            registry.update_status(name, "stopped")
            return SandboxActionResult(
                name=name,
                action="down",
                success=True,
                message=f"Sandbox '{name}' stopped successfully."
            )
        else:
            return SandboxActionResult(
                name=name,
                action="down",
                success=False,
                message=f"Failed to stop sandbox: {result.stderr}"
            )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout waiting for sandbox to stop.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="docker-compose not found.")


@router.delete("/sandboxes/{name}", summary="Unregister a sandbox")
async def delete_sandbox(name: str):
    """
    Remove a sandbox from the registry. Does not delete files.
    - **name**: The sandbox name.
    """
    registry = get_registry()

    if not registry.exists(name):
        raise HTTPException(status_code=404, detail=f"Sandbox '{name}' not found.")

    registry.unregister(name)
    return {"message": f"Sandbox '{name}' unregistered successfully."}


@router.post("/sandboxes/cleanup", summary="Cleanup invalid sandbox entries")
async def cleanup_sandboxes():
    """
    Remove sandbox entries whose directories no longer exist.
    """
    registry = get_registry()
    removed = registry.cleanup_invalid()

    return {
        "removed": removed,
        "count": len(removed),
        "message": f"Removed {len(removed)} invalid sandbox(es)."
    }


def _build_artifact_metadata(job_id: str, filename: str) -> ArtifactMetadata:
    job_dir = os.path.join(job_manager.output_dir, job_id)
    path = os.path.join(job_dir, filename)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    sha256 = "missing"
    if os.path.isfile(path):
        sha = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                sha.update(chunk)
        sha256 = sha.hexdigest()
    return ArtifactMetadata(name=filename, path=filename, size_bytes=size, sha256=sha256)


# Job Endpoints

@router.post("/jobs", response_model=JobSubmitResponse, summary="Submit a new job")
async def submit_job(job_spec: JobSpec):
    """
    Submit a new sandbox job.
    """
    if not job_spec.commands:
        raise HTTPException(status_code=400, detail="At least one command is required.")

    if any(not command.command.strip() for command in job_spec.commands):
        raise HTTPException(status_code=400, detail="Command entries must be non-empty strings.")

    if not job_spec.triggered_by:
        job_spec.triggered_by = "api"

    try:
        record = job_manager.submit_job(job_spec)
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))

    return JobSubmitResponse(
        job_id=record.job_id,
        status=record.status,
        created_at=record.created_at,
        message="Job accepted and queued for execution.",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Get job status")
async def get_job_status(job_id: str):
    """
    Get status and details for a job.
    """
    record = job_manager.get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return JobStatusResponse(job_id=record.job_id, status=record.status, record=record)


@router.get("/jobs", response_model=JobListResponse, summary="List recent jobs")
async def list_jobs(
    status: Optional[JobStatus] = Query(None, description="Filter by job status"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Pagination limit"),
):
    """
    List recent jobs, sorted by created_at descending.
    """
    records = job_manager.list_jobs(status=status)
    sliced = records[offset:offset + limit]
    return JobListResponse(jobs=sliced, count=len(records))


@router.post("/jobs/{job_id}/cancel", response_model=JobCancelResponse, summary="Cancel a job")
async def cancel_job(job_id: str):
    """
    Cancel a running or queued job.
    """
    cancelled, record = job_manager.cancel_job(job_id)
    if not cancelled or not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return JobCancelResponse(
        job_id=record.job_id,
        status=record.status,
        message="Cancellation requested. The job will stop as soon as possible.",
    )


@router.get("/jobs/{job_id}/artifacts", response_model=JobArtifactListResponse, summary="List job artifacts")
async def list_job_artifacts(job_id: str):
    """
    List artifacts captured for a completed job.
    """
    record = job_manager.get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    artifacts = record.artifacts
    if not artifacts:
        artifacts = [
            _build_artifact_metadata(job_id, name)
            for name in job_manager.list_artifacts(job_id)
        ]

    return JobArtifactListResponse(job_id=job_id, artifacts=artifacts, count=len(artifacts))


@router.get("/jobs/{job_id}/artifacts/{filename}", summary="Download job artifact")
async def download_job_artifact(job_id: str, filename: str):
    """
    Download a specific artifact by filename.
    """
    job_dir = os.path.join(job_manager.output_dir, job_id)
    requested = os.path.realpath(os.path.join(job_dir, filename))
    root = os.path.realpath(job_dir)
    if not requested.startswith(root + os.sep):
        raise HTTPException(status_code=400, detail="Invalid artifact path.")

    if not os.path.exists(requested):
        raise HTTPException(status_code=404, detail="Artifact not found.")

    return FileResponse(requested, filename=filename)


@router.get("/jobs/{job_id}/summary", response_model=JobSummaryResponse, summary="Get job summary")
async def get_job_summary(job_id: str):
    """
    Get a deterministic summary of a job execution including one-liner,
    key events, errors, warnings, and suggestions.
    """
    record = job_manager.get_job(job_id)
    if not record:
        record = run_store.get_run(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    generator = SummaryGenerator()
    summary = generator.generate(record)
    return JobSummaryResponse(job_id=job_id, summary=summary)


@router.get("/metrics/jobs", response_model=MetricsResponse, summary="Get job metrics")
async def get_job_metrics(
    from_date: Optional[datetime] = Query(None, description="Start of date range (ISO 8601)"),
    to_date: Optional[datetime] = Query(None, description="End of date range (ISO 8601)"),
):
    """
    Get aggregate job metrics including success rates, durations, and per-image breakdown.
    """
    aggregator = MetricsAggregator(run_store)
    metrics = aggregator.compute_metrics(from_date=from_date, to_date=to_date)
    return MetricsResponse(**metrics)


# Log Streaming Endpoint

_TERMINAL_STATUSES = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED}


def _sse_event(data: dict, event_type: str = "message") -> str:
    """Format a single Server-Sent Event."""
    lines = []
    if event_type != "message":
        lines.append(f"event: {event_type}")
    lines.append(f"data: {json_module.dumps(data)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _parse_docker_timestamp(line: str) -> tuple:
    """Extract Docker timestamp prefix from log line if present."""
    if len(line) > 30 and line[10] == 'T':
        space_idx = line.find(' ')
        if 25 < space_idx < 40:
            return line[:space_idx], line[space_idx + 1:]
    return datetime.now(timezone.utc).isoformat(), line


@router.get("/jobs/{job_id}/logs/stream", summary="Stream job logs via SSE")
async def stream_job_logs(
    job_id: str,
    tail: int = Query(100, ge=0, le=10000, description="Number of historical lines"),
):
    """
    Stream logs from a running job's container using Server-Sent Events.

    Each event is JSON: {"timestamp": "...", "stream": "stdout", "line": "..."}
    Stream ends with an event of type `done`.

    Usage: curl -N http://localhost:8000/orcaops/jobs/{job_id}/logs/stream
    """
    record = job_manager.get_job(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    container_id = record.sandbox_id
    if not container_id:
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' has no associated container (status: {record.status.value}).",
        )

    if record.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=410,
            detail=f"Job '{job_id}' already completed ({record.status.value}). "
                   f"Use GET /orcaops/logs/{container_id} for static logs.",
        )

    async def event_generator():
        loop = asyncio.get_event_loop()

        try:
            container = await loop.run_in_executor(
                None, docker_manager.client.containers.get, container_id
            )
        except docker.errors.NotFound:
            yield _sse_event(
                {"stream": "system", "line": "Container not found.",
                 "timestamp": datetime.now(timezone.utc).isoformat()}
            )
            yield _sse_event(
                {"stream": "system", "line": "Stream ended.",
                 "timestamp": datetime.now(timezone.utc).isoformat()},
                event_type="done",
            )
            return

        log_kwargs = {"stream": True, "follow": True, "timestamps": True}
        if tail > 0:
            log_kwargs["tail"] = tail

        queue = asyncio.Queue()

        def reader():
            try:
                log_stream = container.logs(**log_kwargs)
                for chunk in log_stream:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, reader)

        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                if isinstance(chunk, Exception):
                    yield _sse_event({
                        "stream": "system",
                        "line": f"Error: {chunk}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    break

                line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                ts, msg = _parse_docker_timestamp(line)
                yield _sse_event({"timestamp": ts, "stream": "stdout", "line": msg})
        except asyncio.CancelledError:
            pass

        yield _sse_event(
            {"stream": "system", "line": "Stream ended.",
             "timestamp": datetime.now(timezone.utc).isoformat()},
            event_type="done",
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Run History Endpoints

@router.get("/runs", response_model=RunListResponse, summary="List historical runs")
async def list_runs(
    status: Optional[JobStatus] = Query(None, description="Filter by job status"),
    image: Optional[str] = Query(None, description="Filter by image (substring match)"),
    tags: Optional[str] = Query(None, description="Filter by tags (comma-separated, all must match)"),
    triggered_by: Optional[str] = Query(None, description="Filter by trigger source"),
    after: Optional[datetime] = Query(None, description="Only runs created after this date (ISO 8601)"),
    before: Optional[datetime] = Query(None, description="Only runs created before this date (ISO 8601)"),
    min_duration: Optional[float] = Query(None, description="Minimum duration in seconds"),
    max_duration: Optional[float] = Query(None, description="Maximum duration in seconds"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Pagination limit"),
):
    """
    List historical run records from disk with optional filtering.
    Distinct from /jobs which shows in-memory active jobs.
    """
    tags_list = [t.strip() for t in tags.split(",")] if tags else None
    records, total = run_store.list_runs(
        status=status,
        image=image,
        tags=tags_list,
        triggered_by=triggered_by,
        after=after,
        before=before,
        min_duration_seconds=min_duration,
        max_duration_seconds=max_duration,
        limit=limit,
        offset=offset,
    )
    return RunListResponse(runs=records, total=total, offset=offset, limit=limit)


@router.post("/runs/cleanup", response_model=RunCleanupResponse, summary="Cleanup old runs")
async def cleanup_runs(request: RunCleanupRequest = RunCleanupRequest()):
    """
    Delete run records older than the specified number of days.
    """
    deleted = run_store.cleanup_old_runs(older_than_days=request.older_than_days)
    return RunCleanupResponse(
        deleted_count=len(deleted),
        deleted_job_ids=deleted,
        message=f"Deleted {len(deleted)} run(s) older than {request.older_than_days} days.",
    )


@router.get("/runs/{job_id}", response_model=JobStatusResponse, summary="Get historical run")
async def get_run(job_id: str):
    """
    Get a specific historical run record.
    """
    record = run_store.get_run(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run '{job_id}' not found.")
    return JobStatusResponse(job_id=record.job_id, status=record.status, record=record)


@router.delete("/runs/{job_id}", response_model=RunDeleteResponse, summary="Delete a run")
async def delete_run(job_id: str):
    """
    Delete a run record and its artifacts from disk.
    """
    deleted = run_store.delete_run(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Run '{job_id}' not found.")
    return RunDeleteResponse(
        job_id=job_id,
        deleted=True,
        message=f"Run '{job_id}' and its artifacts deleted.",
    )


# --- Workflow Endpoints ---

@router.post("/workflows", response_model=WorkflowSubmitResponse, summary="Submit a workflow")
async def submit_workflow(request: WorkflowSubmitRequest):
    """Submit a workflow for execution."""
    try:
        record = workflow_manager.submit_workflow(
            request.spec, triggered_by=request.triggered_by or "api"
        )
    except (ValueError, WorkflowValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return WorkflowSubmitResponse(
        workflow_id=record.workflow_id,
        status=record.status,
        created_at=record.created_at,
        message="Workflow accepted and queued for execution.",
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowStatusResponse, summary="Get workflow status")
async def get_workflow_status(workflow_id: str):
    """Get the current status and details of a workflow."""
    record = workflow_manager.get_workflow(workflow_id)
    if not record:
        record = workflow_store.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    return WorkflowStatusResponse(workflow_id=workflow_id, status=record.status, record=record)


@router.get("/workflows/{workflow_id}/jobs", response_model=WorkflowJobsResponse, summary="List workflow jobs")
async def get_workflow_jobs(workflow_id: str):
    """List the jobs within a workflow and their statuses."""
    record = workflow_manager.get_workflow(workflow_id)
    if not record:
        record = workflow_store.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    return WorkflowJobsResponse(
        workflow_id=workflow_id, jobs=record.job_statuses, count=len(record.job_statuses)
    )


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowCancelResponse, summary="Cancel a workflow")
async def cancel_workflow(workflow_id: str):
    """Cancel a running workflow."""
    cancelled, record = workflow_manager.cancel_workflow(workflow_id)
    if not cancelled or not record:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found or already completed.")
    return WorkflowCancelResponse(
        workflow_id=workflow_id, status=record.status, message="Workflow cancellation requested."
    )


@router.get("/workflows", response_model=WorkflowListResponse, summary="List workflows")
async def list_workflows(
    status: Optional[WorkflowStatus] = Query(None, description="Filter by workflow status"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Pagination limit"),
):
    """List workflow runs with optional status filter."""
    active = workflow_manager.list_workflows(status=status)
    historical, _ = workflow_store.list_workflows(status=status, limit=limit)
    active_ids = {r.workflow_id for r in active}
    combined = list(active) + [h for h in historical if h.workflow_id not in active_ids]
    combined.sort(key=lambda r: r.created_at, reverse=True)
    sliced = combined[offset:offset + limit]
    return WorkflowListResponse(workflows=sliced, count=len(combined))


# --- Workspace Management Endpoints ---

@router.post("/workspaces", response_model=WorkspaceResponse, summary="Create a workspace")
async def create_workspace(req: WorkspaceCreateRequest):
    """Create a new workspace."""
    try:
        ws = workspace_registry.create_workspace(
            name=req.name,
            owner_type=req.owner_type,
            owner_id=req.owner_id,
            settings=req.settings,
            limits=req.limits,
        )
        return WorkspaceResponse(workspace=ws, message="Workspace created.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/workspaces", response_model=WorkspaceListResponse, summary="List workspaces")
async def list_workspaces(
    status: Optional[WorkspaceStatus] = Query(None, description="Filter by status"),
):
    """List all workspaces."""
    workspaces = workspace_registry.list_workspaces(status=status)
    return WorkspaceListResponse(workspaces=workspaces, count=len(workspaces))


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse, summary="Get workspace")
async def get_workspace(workspace_id: str):
    """Get a workspace by ID."""
    ws = workspace_registry.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return WorkspaceResponse(workspace=ws)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse, summary="Update workspace")
async def update_workspace(workspace_id: str, req: WorkspaceUpdateRequest):
    """Update workspace settings, limits, or status."""
    try:
        ws = workspace_registry.update_workspace(
            workspace_id,
            settings=req.settings,
            limits=req.limits,
            status=req.status,
        )
        return WorkspaceResponse(workspace=ws, message="Workspace updated.")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/workspaces/{workspace_id}", summary="Archive workspace")
async def archive_workspace(workspace_id: str):
    """Archive (soft-delete) a workspace."""
    if not workspace_registry.archive_workspace(workspace_id):
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return {"workspace_id": workspace_id, "status": "archived", "message": "Workspace archived."}


# --- API Key Management Endpoints ---

@router.post("/workspaces/{workspace_id}/keys", response_model=APIKeyCreateResponse, summary="Create API key")
async def create_api_key(workspace_id: str, req: APIKeyCreateRequest):
    """Generate a new API key for a workspace."""
    ws = workspace_registry.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    try:
        plain_key, api_key = key_manager.generate_key(
            workspace_id=workspace_id,
            name=req.name,
            permissions=req.permissions,
            role=req.role,
            expires_in_days=req.expires_in_days,
        )
        return APIKeyCreateResponse(
            key_id=api_key.key_id,
            plain_key=plain_key,
            name=api_key.name,
            workspace_id=workspace_id,
            permissions=list(api_key.permissions),
            expires_at=api_key.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspaces/{workspace_id}/keys", response_model=APIKeyListResponse, summary="List API keys")
async def list_api_keys(workspace_id: str):
    """List all active API keys for a workspace."""
    ws = workspace_registry.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    keys = key_manager.list_keys(workspace_id)
    key_responses = [
        APIKeyResponse(
            key_id=k.key_id,
            name=k.name,
            workspace_id=k.workspace_id,
            permissions=list(k.permissions),
            created_at=k.created_at,
            last_used=k.last_used,
            expires_at=k.expires_at,
            revoked=k.revoked,
        )
        for k in keys
    ]
    return APIKeyListResponse(keys=key_responses, count=len(key_responses))


@router.delete("/workspaces/{workspace_id}/keys/{key_id}", summary="Revoke API key")
async def revoke_api_key(workspace_id: str, key_id: str):
    """Revoke an API key."""
    if not key_manager.revoke_key(workspace_id, key_id):
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found.")
    return {"key_id": key_id, "revoked": True, "message": "API key revoked."}


# Session Management Endpoints

@router.get("/sessions", response_model=SessionListResponse, summary="List sessions")
async def list_sessions(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    status: Optional[str] = Query(None, description="Filter by status (active, idle, expired)"),
):
    """List agent sessions."""
    session_status = None
    if status:
        try:
            session_status = SessionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    sessions = session_manager.list_sessions(workspace_id=workspace_id, status=session_status)
    return SessionListResponse(sessions=sessions, count=len(sessions))


@router.get("/sessions/{session_id}", response_model=SessionResponse, summary="Get session")
async def get_session(session_id: str):
    """Get a session by ID."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return SessionResponse(session=session)


@router.delete("/sessions/{session_id}", summary="End session")
async def end_session(session_id: str):
    """End an agent session."""
    session = session_manager.end_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return SessionResponse(session=session, message="Session ended.")
