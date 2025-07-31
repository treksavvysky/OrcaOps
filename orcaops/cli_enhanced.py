#!/usr/bin/env python3
"""
Enhanced OrcaOps CLI with improved UX, error handling, and interactive features
"""

import typer
import os
import sys
import time
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Prompt, Confirm
from rich.tree import Tree
from rich.text import Text
from rich.live import Live
import docker
import docker.errors

from orcaops.docker_manager import DockerManager
from orcaops import logger
from orcaops.interactive_mode import InteractiveMode
from orcaops.sandbox_templates_simple import TemplateManager

app = typer.Typer(
    name="orcaops",
    help="🐋 OrcaOps - Advanced Docker Container Management",
    context_settings={"help_option_names": ["-h", "--help"]},
    rich_markup_mode="rich"
)

console = Console()

# Global DockerManager instance
docker_manager: Optional[DockerManager] = None

def init_docker_manager() -> DockerManager:
    """Initialize DockerManager with enhanced error handling"""
    global docker_manager
    
    if docker_manager is None:
        try:
            with console.status("[bold blue]Connecting to Docker..."):
                docker_manager = DockerManager()
            console.print("✅ Connected to Docker daemon", style="green")
        except docker.errors.DockerException as e:
            console.print(f"❌ [bold red]Docker connection failed:[/bold red] {e}")
            console.print("\n💡 [bold yellow]Troubleshooting suggestions:[/bold yellow]")
            console.print("   • Ensure Docker Desktop is running")
            console.print("   • Check Docker daemon status: [cyan]docker version[/cyan]")
            console.print("   • Verify DOCKER_HOST environment variable")
            console.print("   • Try restarting Docker Desktop")
            console.print("\n🔧 Run [cyan]orcaops doctor[/cyan] for automated diagnostics")
            raise typer.Exit(1)
    
    return docker_manager

def format_duration(seconds: float) -> str:
    """Format duration in human-readable format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"

def format_size(bytes_size: int) -> str:
    """Format bytes in human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f}{unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f}PB"

def get_container_status_icon(status: str) -> str:
    """Get status icon for container"""
    status_icons = {
        'running': '🟢',
        'exited': '🔴',
        'restarting': '🟡',
        'paused': '🟠',
        'created': '⚪',
        'dead': '💀'
    }
    return status_icons.get(status.lower(), '❓')

@app.command("doctor", help="🏥 Diagnose Docker environment and OrcaOps configuration")
def doctor():
    """Comprehensive system diagnostics"""
    console.print(Panel.fit("🏥 [bold blue]OrcaOps Doctor[/bold blue] - System Diagnostics", 
                           border_style="blue"))
    
    checks = [
        ("Docker daemon", lambda: docker.from_env().ping()),
        ("Docker version", lambda: docker.from_env().version()),
        ("Container permissions", lambda: docker.from_env().containers.list()),
        ("Image permissions", lambda: docker.from_env().images.list()),
        ("Network access", lambda: docker.from_env().networks.list()),
    ]
    
    results = {}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        
        for check_name, check_func in checks:
            task = progress.add_task(f"Checking {check_name}...", total=None)
            
            try:
                result = check_func()
                results[check_name] = ("✅", "OK", str(result)[:100] if result else "OK")
                progress.update(task, description=f"✅ {check_name}")
            except Exception as e:
                results[check_name] = ("❌", "FAILED", str(e))
                progress.update(task, description=f"❌ {check_name}")
            
            time.sleep(0.5)  # Visual delay for better UX
    
    # Display results
    table = Table(title="Diagnostic Results", show_header=True, header_style="bold magenta")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Result", style="dim")
    
    for check_name, (icon, status, details) in results.items():
        table.add_row(check_name, f"{icon} {status}", details)
    
    console.print(table)
    
    # Recommendations
    failed_checks = [name for name, (_, status, _) in results.items() if status == "FAILED"]
    if failed_checks:
        console.print("\n🔧 [bold yellow]Recommendations:[/bold yellow]")
        for check in failed_checks:
            console.print(f"   • Fix {check} issue before proceeding")
    else:
        console.print("\n🎉 [bold green]All checks passed! OrcaOps is ready to use.[/bold green]")

@app.command("ps", help="📋 List containers with enhanced formatting")
def list_containers(
    all_containers: bool = typer.Option(False, "--all", "-a", help="Show all containers"),
    format_output: str = typer.Option("table", "--format", "-f", help="Output format: table, json, tree"),
    filter_status: Optional[str] = typer.Option(None, "--filter", help="Filter by status: running, exited, etc."),
    sort_by: str = typer.Option("created", "--sort", help="Sort by: name, created, status, image")
):
    """Enhanced container listing with multiple output formats"""
    dm = init_docker_manager()
    
    with console.status("[bold blue]Fetching containers..."):
        containers = dm.list_running_containers(all=all_containers)
    
    if not containers:
        console.print("📭 No containers found", style="yellow")
        return
    
    # Apply filters
    if filter_status:
        containers = [c for c in containers if c.status.lower() == filter_status.lower()]
    
    # Sort containers
    sort_keys = {
        'name': lambda c: c.name,
        'created': lambda c: c.attrs['Created'],
        'status': lambda c: c.status,
        'image': lambda c: c.image.tags[0] if c.image.tags else 'unknown'
    }
    
    if sort_by in sort_keys:
        containers.sort(key=sort_keys[sort_by])
    
    if format_output == "json":
        import json
        data = []
        for container in containers:
            data.append({
                'id': container.short_id,
                'name': container.name,
                'image': container.image.tags[0] if container.image.tags else 'unknown',
                'status': container.status,
                'created': container.attrs['Created'],
                'ports': container.attrs.get('NetworkSettings', {}).get('Ports', {})
            })
        console.print(json.dumps(data, indent=2))
        
    elif format_output == "tree":
        tree = Tree("🐋 Docker Containers")
        
        for container in containers:
            icon = get_container_status_icon(container.status)
            node = tree.add(f"{icon} {container.name}")
            node.add(f"ID: {container.short_id}")
            node.add(f"Image: {container.image.tags[0] if container.image.tags else 'unknown'}")
            node.add(f"Status: {container.status}")
            
        console.print(tree)
        
    else:  # table format (default)
        running_count = len([c for c in containers if c.status == 'running'])
        total_count = len(containers)
        
        table = Table(
            title=f"🐋 Docker Containers ({running_count} running, {total_count} total)",
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("Status", justify="center", width=8)
        table.add_column("Name", style="cyan", min_width=15)
        table.add_column("Image", style="blue", min_width=20)
        table.add_column("Ports", style="green")
        table.add_column("Created", style="dim")
        
        for container in containers:
            # Format ports
            ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
            port_str = []
            for internal, external in ports.items():
                if external:
                    port_str.append(f"{external[0]['HostPort']}→{internal.split('/')[0]}")
            ports_display = ", ".join(port_str) if port_str else "-"
            
            # Format creation time
            created = datetime.fromisoformat(container.attrs['Created'].replace('Z', '+00:00'))
            time_ago = datetime.now().astimezone() - created.astimezone()
            created_display = format_duration(time_ago.total_seconds()) + " ago"
            
            icon = get_container_status_icon(container.status)
            status_display = f"{icon} {container.status.title()}"
            
            table.add_row(
                status_display,
                container.name,
                container.image.tags[0] if container.image.tags else container.attrs['Config']['Image'],
                ports_display,
                created_display
            )
        
        console.print(table)
        console.print(f"\n💡 Use [cyan]orcaops inspect <name>[/cyan] for detailed information")

@app.command("inspect", help="🔍 Detailed container information")
def inspect_container(
    container_name: str = typer.Argument(..., help="Container name or ID"),
    format_output: str = typer.Option("rich", "--format", "-f", help="Output format: rich, json, yaml")
):
    """Get detailed information about a container"""
    dm = init_docker_manager()
    
    try:
        with console.status(f"[bold blue]Inspecting {container_name}..."):
            container = dm.client.containers.get(container_name)
        
        if format_output == "json":
            import json
            console.print(json.dumps(container.attrs, indent=2))
            return
        elif format_output == "yaml":
            import yaml
            console.print(yaml.dump(container.attrs, default_flow_style=False))
            return
        
        # Rich format (default)
        panel_title = f"🔍 Container: {container.name}"
        
        # Basic info
        basic_info = f"""
[bold cyan]ID:[/bold cyan] {container.id}
[bold cyan]Name:[/bold cyan] {container.name}
[bold cyan]Image:[/bold cyan] {container.image.tags[0] if container.image.tags else 'unknown'}
[bold cyan]Status:[/bold cyan] {get_container_status_icon(container.status)} {container.status}
[bold cyan]Created:[/bold cyan] {container.attrs['Created']}
"""
        
        # Network info
        networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
        network_info = "\n[bold yellow]Networks:[/bold yellow]\n"
        for net_name, net_data in networks.items():
            ip = net_data.get('IPAddress', 'N/A')
            network_info += f"  • {net_name}: {ip}\n"
        
        # Port mappings
        ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
        port_info = "\n[bold green]Port Mappings:[/bold green]\n"
        if ports:
            for internal, external in ports.items():
                if external:
                    port_info += f"  • {external[0]['HostPort']} → {internal}\n"
                else:
                    port_info += f"  • {internal} (not mapped)\n"
        else:
            port_info += "  No port mappings\n"
        
        # Mounts
        mounts = container.attrs.get('Mounts', [])
        mount_info = "\n[bold blue]Mounts:[/bold blue]\n"
        if mounts:
            for mount in mounts:
                mount_info += f"  • {mount['Source']} → {mount['Destination']} ({mount['Type']})\n"
        else:
            mount_info += "  No mounts\n"
        
        content = basic_info + network_info + port_info + mount_info
        
        console.print(Panel(content, title=panel_title, border_style="blue"))
        
    except docker.errors.NotFound:
        console.print(f"❌ Container '{container_name}' not found", style="red")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"❌ Error inspecting container: {e}", style="red")
        raise typer.Exit(1)

@app.command("interactive", help="🎮 Interactive container management mode")
def interactive_mode():
    """Start interactive mode for container management"""
    dm = init_docker_manager()
    
    try:
        interactive = InteractiveMode(dm)
        interactive.start()
    except KeyboardInterrupt:
        console.print("\n👋 [bold blue]Goodbye![/bold blue]")
    except Exception as e:
        console.print(f"❌ [red]Interactive mode error: {e}[/red]")
        logger.error(f"Interactive mode error: {e}", exc_info=True)

if __name__ == "__main__":
    app()
