from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import docker

from orcaops.docker_manager import DockerManager
from orcaops.sandbox_templates import SandboxTemplates
from orcaops.schemas import Container, ContainerInspect, CleanupReport, Template, TemplateList

router = APIRouter()
docker_manager = DockerManager()
sandbox_templates = SandboxTemplates()

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

@router.get("/templates", response_model=TemplateList, summary="List available sandbox templates")
async def list_templates():
    """
    Get a list of all available sandbox templates.
    """
    try:
        templates = sandbox_templates.get_templates()
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
