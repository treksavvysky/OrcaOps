from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import subprocess
import docker

from orcaops.docker_manager import DockerManager
from orcaops.sandbox_templates_simple import SandboxTemplates, TemplateManager
from orcaops.sandbox_registry import get_registry
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
)

router = APIRouter()
docker_manager = DockerManager()


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
