#!/usr/bin/env python

import typer
from typing import List, Optional
from rich.console import Console
from rich.table import Table
import docker 

from orcaops.docker_manager import DockerManager
from orcaops import logger 
import os

app = typer.Typer()
console = Console()

# Global DockerManager instance, conditionally initialized.
docker_manager: Optional[DockerManager] = None
if os.environ.get("ORCAOPS_SKIP_DOCKER_INIT") != "1":
    try:
        docker_manager = DockerManager()
    except docker.errors.DockerException as e:
        logger.error(f"Failed to initialize DockerManager at CLI startup: {e}", exc_info=True)
        console.print(f"[bold red]Error initializing Docker: {e}[/bold red]")
        console.print("Please ensure Docker is running and accessible, or DOCKER_HOST is set correctly.")
        raise typer.Exit(code=1)
else:
    logger.warning("ORCAOPS_SKIP_DOCKER_INIT is set. DockerManager not initialized at module level for testing.")


@app.command("ps", help="List containers. Similar to 'docker ps'.")
def list_containers_command(
    all_containers: bool = typer.Option(False, "--all", "-a", help="Show all containers (including stopped).")
):
    """
    Lists Docker containers. Shows running containers by default.
    Use --all or -a to show all containers.
    """
    if docker_manager is None:
        console.print("[bold red]DockerManager not available (ORCAOPS_SKIP_DOCKER_INIT was set). Cannot execute command.[/bold red]")
        raise typer.Exit(code=2)
    
    logger.info(f"CLI: Listing containers (all: {all_containers})")
    try:
        if all_containers:
            containers = docker_manager.list_running_containers(all=True)
        else:
            containers = docker_manager.list_running_containers() # Default is running only

        if not containers:
            console.print("No containers found.")
            return

        table = Table(title="Docker Containers")
        table.add_column("ID", style="dim", width=15)
        table.add_column("Image", style="cyan")
        table.add_column("Names", style="green")
        table.add_column("Status", style="magenta")

        for container in containers:
            container_id_short = container.short_id
            image_tags = ", ".join(container.image.tags) if container.image and container.image.tags else container.attrs['Config']['Image']
            names = container.name
            status = container.status
            table.add_row(container_id_short, image_tags, names, status)

        console.print(table)
    except docker.errors.APIError as e:
        console.print(f"[bold red]Error listing containers: {e}[/bold red]")
        logger.error(f"CLI: Error listing containers: {e}")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        logger.error(f"CLI: Unexpected error listing containers: {e}", exc_info=True)


@app.command("logs", help="Fetch logs from a container.")
def logs_command(
    container_id: str = typer.Argument(None, help="The ID or name of the container."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Fetch all logs at once instead of streaming."),
    follow: bool = typer.Option(True, "--follow", "-f", help="Follow log output (if streaming)."),
    timestamps: bool = typer.Option(True, "--timestamps", "-t", help="Show timestamps in logs (if streaming).")
):
    """
    Fetches and displays logs from a specified container.
    Streams logs by default.
    """
    if docker_manager is None:
        console.print("[bold red]DockerManager not available (ORCAOPS_SKIP_DOCKER_INIT was set). Cannot execute command.[/bold red]")
        raise typer.Exit(code=2)

    if not container_id:
        container_id = typer.prompt("Please enter the container ID or name")
        if not container_id: 
            console.print("[bold red]Container ID or name is required.[/bold red]")
            raise typer.Exit(code=1)

    logger.info(f"CLI: Fetching logs for container '{container_id}' (stream: {not no_stream})")
    try:
        if no_stream:
            log_data = docker_manager.logs(container_id, stream=False, timestamps=timestamps)
            if log_data:
                console.print(log_data)
            else:
                console.print(f"No logs returned for container {container_id}.")
        else:
            console.print(f"Streaming logs for {container_id}... (Press Ctrl+C to stop)")
            docker_manager.logs(container_id, stream=True, follow=follow, timestamps=timestamps)

    except docker.errors.NotFound:
        console.print(f"[bold red]Error: Container '{container_id}' not found.[/bold red]")
        logger.warning(f"CLI: Container '{container_id}' not found for logs.")
    except docker.errors.APIError as e:
        console.print(f"[bold red]Error fetching logs for '{container_id}': {e}[/bold red]")
        logger.error(f"CLI: APIError fetching logs for '{container_id}': {e}")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
        logger.error(f"CLI: Unexpected error fetching logs: {e}", exc_info=True)


@app.command("rm", help="Remove one or more containers.")
def remove_containers_command(
    container_ids: List[str] = typer.Argument(None, help="The IDs or names of the containers to remove."),
    force: bool = typer.Option(False, "--force", "-f", help="Force the removal of a running container.")
):
    """
    Removes one or more specified containers.
    Prompts for container IDs if none are provided.
    """
    if docker_manager is None:
        console.print("[bold red]DockerManager not available (ORCAOPS_SKIP_DOCKER_INIT was set). Cannot execute command.[/bold red]")
        raise typer.Exit(code=2)

    if not container_ids:
        ids_str = typer.prompt("Please enter the container IDs or names to remove (comma-separated)")
        if not ids_str:
            console.print("[bold red]At least one container ID or name is required.[/bold red]")
            raise typer.Exit(code=1)
        container_ids = [id_val.strip() for id_val in ids_str.split(',')]

    logger.info(f"CLI: Attempting to remove containers: {container_ids} (force: {force})")
    for cid in container_ids:
        try:
            console.print(f"Removing container {cid}...")
            success = docker_manager.rm(cid, force=force)
            if success:
                console.print(f"[green]Container {cid} removed successfully.[/green]")
                logger.info(f"CLI: Container {cid} removed successfully.")
            else:
                console.print(f"[yellow]Failed to remove container {cid}. See logs for details.[/yellow]")
                logger.warning(f"CLI: Failed to remove container {cid} (force: {force}). DockerManager.rm returned False.")
        except Exception as e: 
            console.print(f"[bold red]Error removing container {cid}: {e}[/bold red]")
            logger.error(f"CLI: Exception while trying to remove container {cid}: {e}", exc_info=True)


@app.command("stop", help="Stop one or more containers.")
def stop_containers_command(
    container_ids: List[str] = typer.Argument(None, help="The IDs or names of the containers to stop.")
):
    """
    Stops one or more specified containers.
    Prompts for container IDs if none are provided.
    """
    if docker_manager is None:
        console.print("[bold red]DockerManager not available (ORCAOPS_SKIP_DOCKER_INIT was set). Cannot execute command.[/bold red]")
        raise typer.Exit(code=2)

    if not container_ids:
        ids_str = typer.prompt("Please enter the container IDs or names to stop (comma-separated)")
        if not ids_str:
            console.print("[bold red]At least one container ID or name is required.[/bold red]")
            raise typer.Exit(code=1)
        container_ids = [id_val.strip() for id_val in ids_str.split(',')]

    logger.info(f"CLI: Attempting to stop containers: {container_ids}")
    for cid in container_ids:
        try:
            console.print(f"Stopping container {cid}...")
            success = docker_manager.stop(cid) 
            if success:
                console.print(f"[green]Container {cid} stopped successfully.[/green]")
                logger.info(f"CLI: Container {cid} stopped successfully.")
            else:
                console.print(f"[yellow]Failed to stop container {cid}. It might already be stopped or an error occurred. See logs.[/yellow]")
                logger.warning(f"CLI: Failed to stop container {cid}. DockerManager.stop returned False.")
        except Exception as e: 
            console.print(f"[bold red]Error stopping container {cid}: {e}[/bold red]")
            logger.error(f"CLI: Exception while trying to stop container {cid}: {e}", exc_info=True)


if __name__ == "__main__":
    # This check is important if __main__ might try to use docker_manager
    # when ORCAOPS_SKIP_DOCKER_INIT was set.
    if docker_manager is None and os.environ.get("ORCAOPS_SKIP_DOCKER_INIT") == "1":
        console.print("[yellow]CLI cannot run directly with ORCAOPS_SKIP_DOCKER_INIT set, as DockerManager is not initialized.[/yellow]")
        console.print("[yellow]This mode is intended for testing where DockerManager is mocked.[/yellow]")
    else:
        app()
