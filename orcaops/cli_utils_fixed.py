#!/usr/bin/env python3
"""
Fixed CLI utilities for OrcaOps
"""

import time
import shutil
import subprocess
import yaml
import typer
import docker
import docker.errors
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

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

class CLIUtils:
    """Utility functions for CLI operations"""
    
    @staticmethod
    def check_dependencies() -> Dict[str, bool]:
        """Check if required system dependencies are available"""
        dependencies = {
            'docker': shutil.which('docker') is not None,
            'git': shutil.which('git') is not None,
            'curl': shutil.which('curl') is not None,
        }
        return dependencies
    
    @staticmethod
    def get_system_info() -> Dict[str, str]:
        """Get system information for diagnostics"""
        info = {}
        
        try:
            # Docker version
            result = subprocess.run(['docker', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            info['docker_version'] = result.stdout.strip() if result.returncode == 0 else "Not available"
        except:
            info['docker_version'] = "Not available"
        
        try:
            # Available disk space
            import psutil
            usage = psutil.disk_usage('/')
            info['disk_space'] = f"{usage.free // (1024**3)} GB free of {usage.total // (1024**3)} GB"
        except:
            info['disk_space'] = "Unknown"
        
        return info
    
    @staticmethod
    def show_welcome_message():
        """Display welcome message for CLI"""
        welcome_text = """
🐋 [bold blue]Welcome to OrcaOps![/bold blue]

Advanced Docker container management and sandbox orchestration.

[dim]Quick start:[/dim]
• [cyan]orcaops ps[/cyan] - List containers
• [cyan]orcaops doctor[/cyan] - Run diagnostics  
• [cyan]orcaops --help[/cyan] - Show all commands

[dim]Need help? Visit: https://github.com/your-org/orcaops[/dim]
"""
        console.print(Panel(welcome_text, border_style="blue", padding=(1, 2)))

# Simplified CLICommands class for basic functionality
class CLICommands:
    """Additional CLI commands for enhanced functionality"""
    
    @staticmethod
    def add_commands(app):
        """Add enhanced commands to the main CLI app"""
        
        @app.command("cleanup", help="🧹 Clean up unused containers")
        def cleanup(
            containers: bool = typer.Option(True, "--containers", help="Remove stopped containers"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned up")
        ):
            """Clean up Docker resources"""
            from rich.prompt import Confirm
            from orcaops.cli_enhanced import init_docker_manager
            
            dm = init_docker_manager()
            
            if dry_run:
                console.print("🔍 [bold]Dry run - showing what would be cleaned up:[/bold]")
            
            # Clean up containers
            if containers:
                stopped_containers = [c for c in dm.list_running_containers(all=True) 
                                    if c.status != 'running']
                if stopped_containers:
                    console.print(f"Containers: {len(stopped_containers)} stopped")
                    if not dry_run:
                        if Confirm.ask(f"Remove {len(stopped_containers)} stopped containers?"):
                            for container in stopped_containers:
                                dm.rm(container.id)
                            console.print(f"✅ Removed {len(stopped_containers)} containers", style="green")
                else:
                    console.print("✨ No stopped containers to clean up!", style="green")
        
        @app.command("templates", help="📋 List available sandbox templates")
        def list_templates():
            """List all available sandbox templates"""
            from orcaops.sandbox_templates_simple import TemplateManager
            
            table = TemplateManager.list_templates_table()
            console.print(table)
            console.print(f"\n💡 Use [cyan]orcaops init <template-name>[/cyan] to create a new sandbox")
        
        @app.command("init", help="🚀 Initialize a new sandbox from template")
        def init_sandbox(
            template: str = typer.Argument(..., help="Template name (web-dev, python-ml, api-testing, microservices, wordpress)"),
            name: Optional[str] = typer.Option(None, "--name", "-n", help="Sandbox name"),
            directory: Optional[str] = typer.Option(None, "--dir", "-d", help="Output directory")
        ):
            """Initialize a new sandbox from template"""
            from rich.prompt import Prompt, Confirm
            from orcaops.sandbox_templates_simple import TemplateManager
            
            # Validate template
            if not TemplateManager.validate_template_name(template):
                console.print(f"❌ Template '{template}' not found", style="red")
                console.print("\n📋 Available templates:")
                table = TemplateManager.list_templates_table()
                console.print(table)
                raise typer.Exit(1)
            
            # Get sandbox name
            if not name:
                name = Prompt.ask("🏷️ Sandbox name", default=f"my-{template}")
            
            # Get output directory
            if not directory:
                directory = Prompt.ask("📁 Output directory", default=f"./{name}")
            
            output_path = Path(directory)
            
            if output_path.exists() and any(output_path.iterdir()):
                if not Confirm.ask(f"Directory '{directory}' exists and is not empty. Continue?"):
                    raise typer.Exit(0)
            
            # Create template
            success = TemplateManager.create_sandbox_from_template(template, name, directory)
            
            if success:
                console.print(f"✅ Created {template} sandbox in {directory}", style="green")
                
                console.print(f"\n🚀 [bold]Next steps:[/bold]")
                console.print(f"  1. [cyan]cd {directory}[/cyan]")
                console.print(f"  2. [cyan]make start[/cyan] or [cyan]docker-compose up -d[/cyan]")
                console.print(f"  3. [cyan]orcaops ps[/cyan] to see running containers")
                console.print(f"  4. Check the [cyan]README.md[/cyan] for service URLs and details")
            else:
                raise typer.Exit(1)

# Add utility functions to CLIUtils class
CLIUtils.get_container_status_icon = staticmethod(get_container_status_icon)
CLIUtils.format_duration = staticmethod(format_duration)
CLIUtils.format_size = staticmethod(format_size)
