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

from orcaops.cli_enhanced import format_duration, format_size, get_container_status_icon

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
        except Exception:
            info['docker_version'] = "Not available"
        
        try:
            # Available disk space
            import psutil
            usage = psutil.disk_usage('/')
            info['disk_space'] = f"{usage.free // (1024**3)} GB free of {usage.total // (1024**3)} GB"
        except Exception:
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
            from orcaops.sandbox_registry import get_registry

            registry = get_registry()

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

            # Check if name already exists in registry
            if registry.exists(name):
                existing = registry.get(name)
                console.print(f"⚠️  Sandbox '{name}' already exists at {existing.path}", style="yellow")
                if not Confirm.ask("Create anyway with this name?"):
                    raise typer.Exit(0)

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
                # Register the sandbox
                registry.register(name, template, directory)

                console.print(f"✅ Created {template} sandbox in {directory}", style="green")

                console.print(f"\n🚀 [bold]Next steps:[/bold]")
                console.print(f"  1. [cyan]cd {directory}[/cyan]")
                console.print(f"  2. [cyan]make start[/cyan] or [cyan]docker-compose up -d[/cyan]")
                console.print(f"  3. [cyan]orcaops list[/cyan] to see your sandboxes")
                console.print(f"  4. [cyan]orcaops ps[/cyan] to see running containers")
                console.print(f"  5. Check the [cyan]README.md[/cyan] for service URLs and details")
            else:
                raise typer.Exit(1)

        @app.command("list", help="📋 List generated sandboxes")
        def list_sandboxes(
            validate: bool = typer.Option(False, "--validate", "-v", help="Validate sandbox directories exist"),
            cleanup: bool = typer.Option(False, "--cleanup", help="Remove sandboxes with missing directories")
        ):
            """List all registered sandboxes"""
            from rich.table import Table
            from orcaops.sandbox_registry import get_registry

            registry = get_registry()

            # Optionally clean up invalid entries
            if cleanup:
                removed = registry.cleanup_invalid()
                if removed:
                    console.print(f"🧹 Removed {len(removed)} invalid sandbox(es): {', '.join(removed)}", style="yellow")

            sandboxes = registry.list_all()

            if not sandboxes:
                console.print("📭 No sandboxes registered yet", style="yellow")
                console.print("\n💡 Create one with: [cyan]orcaops init <template>[/cyan]")
                console.print("   Available templates: [cyan]orcaops templates[/cyan]")
                return

            table = Table(title="📦 Registered Sandboxes", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan", min_width=15)
            table.add_column("Template", style="blue", min_width=12)
            table.add_column("Path", style="dim")
            table.add_column("Created", style="green")
            if validate:
                table.add_column("Valid", justify="center")

            for sandbox in sandboxes:
                # Parse and format created date
                try:
                    from datetime import datetime
                    created = datetime.fromisoformat(sandbox.created_at)
                    created_str = created.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    created_str = sandbox.created_at[:16]

                row = [sandbox.name, sandbox.template, sandbox.path, created_str]

                if validate:
                    validation = registry.validate_sandbox(sandbox.name)
                    if validation["exists"] and validation["has_compose"]:
                        row.append("✅")
                    elif validation["exists"]:
                        row.append("⚠️")
                    else:
                        row.append("❌")

                table.add_row(*row)

            console.print(table)
            console.print(f"\n💡 Use [cyan]orcaops up <name>[/cyan] to start a sandbox")

        @app.command("up", help="🚀 Start a sandbox")
        def start_sandbox(
            name: str = typer.Argument(..., help="Sandbox name (from orcaops list)"),
            detach: bool = typer.Option(True, "--detach/--no-detach", "-d", help="Run in background")
        ):
            """Start a registered sandbox"""
            import subprocess
            from orcaops.sandbox_registry import get_registry

            registry = get_registry()

            # Check if sandbox exists
            sandbox = registry.get(name)
            if not sandbox:
                console.print(f"❌ Sandbox '{name}' not found", style="red")
                console.print("\n💡 Available sandboxes:")
                for s in registry.list_all():
                    console.print(f"   • {s.name}")
                if not registry.list_all():
                    console.print("   (none - create one with [cyan]orcaops init <template>[/cyan])")
                raise typer.Exit(1)

            # Validate sandbox directory exists
            validation = registry.validate_sandbox(name)
            if not validation["exists"]:
                console.print(f"❌ Sandbox directory not found: {sandbox.path}", style="red")
                console.print("💡 Use [cyan]orcaops list --cleanup[/cyan] to remove invalid entries")
                raise typer.Exit(1)

            if not validation["has_compose"]:
                console.print(f"⚠️  No docker-compose.yml found in {sandbox.path}", style="yellow")
                raise typer.Exit(1)

            # Start the sandbox
            console.print(f"🚀 Starting sandbox '{name}'...", style="blue")

            cmd = ["docker-compose", "up"]
            if detach:
                cmd.append("-d")

            try:
                result = subprocess.run(
                    cmd,
                    cwd=sandbox.path,
                    capture_output=False,
                    text=True
                )

                if result.returncode == 0:
                    registry.update_status(name, "running")
                    console.print(f"✅ Sandbox '{name}' started successfully!", style="green")
                    console.print(f"\n💡 Use [cyan]orcaops ps[/cyan] to see running containers")
                    console.print(f"💡 Use [cyan]orcaops down {name}[/cyan] to stop")
                else:
                    console.print(f"❌ Failed to start sandbox '{name}'", style="red")
                    raise typer.Exit(1)

            except FileNotFoundError:
                console.print("❌ docker-compose not found. Please install Docker Compose.", style="red")
                raise typer.Exit(1)

        @app.command("down", help="🛑 Stop a sandbox")
        def stop_sandbox(
            name: str = typer.Argument(..., help="Sandbox name (from orcaops list)"),
            volumes: bool = typer.Option(False, "--volumes", "-v", help="Also remove volumes")
        ):
            """Stop a registered sandbox"""
            import subprocess
            from orcaops.sandbox_registry import get_registry

            registry = get_registry()

            # Check if sandbox exists
            sandbox = registry.get(name)
            if not sandbox:
                console.print(f"❌ Sandbox '{name}' not found", style="red")
                raise typer.Exit(1)

            # Validate sandbox directory exists
            validation = registry.validate_sandbox(name)
            if not validation["exists"]:
                console.print(f"❌ Sandbox directory not found: {sandbox.path}", style="red")
                raise typer.Exit(1)

            # Stop the sandbox
            console.print(f"🛑 Stopping sandbox '{name}'...", style="blue")

            cmd = ["docker-compose", "down"]
            if volumes:
                cmd.append("-v")

            try:
                result = subprocess.run(
                    cmd,
                    cwd=sandbox.path,
                    capture_output=False,
                    text=True
                )

                if result.returncode == 0:
                    registry.update_status(name, "stopped")
                    console.print(f"✅ Sandbox '{name}' stopped successfully!", style="green")
                else:
                    console.print(f"❌ Failed to stop sandbox '{name}'", style="red")
                    raise typer.Exit(1)

            except FileNotFoundError:
                console.print("❌ docker-compose not found. Please install Docker Compose.", style="red")
                raise typer.Exit(1)

# Add utility functions to CLIUtils class
CLIUtils.get_container_status_icon = staticmethod(get_container_status_icon)
CLIUtils.format_duration = staticmethod(format_duration)
CLIUtils.format_size = staticmethod(format_size)
