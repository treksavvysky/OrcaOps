#!/usr/bin/env python3
"""
CLI utilities and helper functions for enhanced OrcaOps experience
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

class SandboxTemplates:
    """Predefined sandbox configurations for common development scenarios"""
    
    @staticmethod
    def get_templates() -> Dict[str, Dict]:
        """Get all available sandbox templates"""
        return {
            "web-dev": {
                "name": "Web Development",
                "description": "Full-stack web development environment",
                "services": {
                    "nginx": {
                        "image": "nginx:alpine",
                        "ports": ["80:8080"],
                        "volumes": ["./html:/usr/share/nginx/html:ro"]
                    },
                    "node": {
                        "image": "node:18",
                        "working_dir": "/app",
                        "volumes": ["./app:/app"],
                        "command": "npm run dev",
                        "ports": ["3000:3000"]
                    },
                    "postgres": {
                        "image": "postgres:15",
                        "environment": {
                            "POSTGRES_DB": "devdb",
                            "POSTGRES_USER": "dev",
                            "POSTGRES_PASSWORD": "devpass"
                        },
                        "ports": ["5432:5432"],
                        "volumes": ["postgres_data:/var/lib/postgresql/data"]
                    }
                }
            },
            
            "python-ml": {
                "name": "Python Machine Learning",
                "description": "Python environment with ML libraries and Jupyter",
                "services": {
                    "jupyter": {
                        "image": "jupyter/tensorflow-notebook:latest",
                        "ports": ["8888:8888"],
                        "volumes": [
                            "./notebooks:/home/jovyan/work",
                            "./data:/home/jovyan/data"
                        ],
                        "environment": {
                            "JUPYTER_ENABLE_LAB": "yes"
                        }
                    },
                    "mlflow": {
                        "image": "mlflow/mlflow:latest",
                        "ports": ["5000:5000"],
                        "command": "mlflow ui --host 0.0.0.0",
                        "volumes": ["./mlruns:/mlruns"]
                    }
                }
            },
            
            "api-testing": {
                "name": "API Testing Environment",
                "description": "Environment for testing APIs with databases",
                "services": {
                    "api": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./api:/app"],
                        "command": "npm start",
                        "ports": ["3000:3000"],
                        "depends_on": ["redis", "postgres"]
                    },
                    "redis": {
                        "image": "redis:alpine",
                        "ports": ["6379:6379"]
                    },
                    "postgres": {
                        "image": "postgres:15",
                        "environment": {
                            "POSTGRES_DB": "testdb",
                            "POSTGRES_USER": "test",
                            "POSTGRES_PASSWORD": "testpass"
                        },
                        "ports": ["5432:5432"]
                    }
                }
            },
            
            "microservices": {
                "name": "Microservices Development",
                "description": "Multi-service architecture with service discovery",
                "services": {
                    "gateway": {
                        "image": "nginx:alpine",
                        "ports": ["80:8080"],
                        "volumes": ["./nginx.conf:/etc/nginx/nginx.conf:ro"],
                        "depends_on": ["auth", "api", "frontend"]
                    },
                    "auth": {
                        "image": "node:18",
                        "working_dir": "/app",
                        "volumes": ["./auth-service:/app"],
                        "ports": ["3001:3000"],
                        "environment": {
                            "SERVICE_NAME": "auth",
                            "PORT": "3000"
                        }
                    },
                    "api": {
                        "image": "node:18",
                        "working_dir": "/app", 
                        "volumes": ["./api-service:/app"],
                        "ports": ["3002:3000"],
                        "environment": {
                            "SERVICE_NAME": "api",
                            "PORT": "3000"
                        }
                    },
                    "frontend": {
                        "image": "node:18",
                        "working_dir": "/app",
                        "volumes": ["./frontend:/app"],
                        "ports": ["3003:3000"],
                        "command": "npm run dev"
                    }
                }
            }
        }
    
    @staticmethod
    def create_template_files(template_name: str, output_dir: Path):
        """Create template files and directory structure"""
        templates = SandboxTemplates.get_templates()
        
        if template_name not in templates:
            raise ValueError(f"Template '{template_name}' not found")
        
        template = templates[template_name]
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create docker-compose.yml
        compose_content = SandboxTemplates._generate_compose_file(template)
        (output_dir / "docker-compose.yml").write_text(compose_content)
        
        # Create .env file
        env_content = SandboxTemplates._generate_env_file(template)
        (output_dir / ".env").write_text(env_content)
        
        # Create README.md
        readme_content = SandboxTemplates._generate_readme(template_name, template)
        (output_dir / "README.md").write_text(readme_content)
        
        # Create directory structure and sample files
        SandboxTemplates._create_sample_files(template_name, template, output_dir)
    
    @staticmethod
    def _generate_compose_file(template: Dict) -> str:
        """Generate docker-compose.yml content"""
        compose = {
            "version": "3.8",
            "services": template["services"]
        }
        
        # Add volumes if needed
        volumes = set()
        for service in template["services"].values():
            for volume in service.get("volumes", []):
                if ":" in volume and not volume.startswith("./"):
                    volume_name = volume.split(":")[0]
                    if not volume_name.startswith("/"):
                        volumes.add(volume_name)
        
        if volumes:
            compose["volumes"] = {vol: {} for vol in volumes}
        
        import yaml
        return yaml.dump(compose, default_flow_style=False)
    
    @staticmethod
    def _generate_env_file(template: Dict) -> str:
        """Generate .env file content"""
        env_vars = [
            "# Environment variables for OrcaOps sandbox",
            f"SANDBOX_NAME={template['name'].lower().replace(' ', '-')}",
            "# Add your custom environment variables below",
            "",
        ]
        return "\n".join(env_vars)
    
    @staticmethod
    def _generate_readme(template_name: str, template: Dict) -> str:
        """Generate README.md content"""
        return f"""# {template['name']} Sandbox

{template['description']}

## Quick Start

1. **Start the sandbox:**
   ```bash
   orcaops sandbox start
   ```

2. **View running services:**
   ```bash
   orcaops ps
   ```

3. **Stop the sandbox:**
   ```bash
   orcaops sandbox stop
   ```

## Services

"""

class CLICommands:
    """Additional CLI commands for enhanced functionality"""
    
    @staticmethod
    def add_commands(app):
        """Add enhanced commands to the main CLI app"""
        
        @app.command("init", help="🚀 Initialize a new sandbox from template")
        def init_sandbox(
            template: str = typer.Argument(..., help="Template name (web-dev, python-ml, api-testing, microservices)"),
            name: Optional[str] = typer.Option(None, "--name", "-n", help="Sandbox name"),
            directory: Optional[str] = typer.Option(None, "--dir", "-d", help="Output directory")
        ):
            """Initialize a new sandbox from template"""
            from rich.prompt import Prompt, Confirm
            
            templates = SandboxTemplates.get_templates()
            
            if template not in templates:
                console.print(f"❌ Template '{template}' not found", style="red")
                console.print("\n📋 Available templates:")
                for t_name, t_info in templates.items():
                    console.print(f"  • [cyan]{t_name}[/cyan]: {t_info['description']}")
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
            with console.status(f"[bold blue]Creating {template} sandbox..."):
                try:
                    SandboxTemplates.create_template_files(template, output_path)
                    console.print(f"✅ Created {template} sandbox in {directory}", style="green")
                    
                    console.print(f"\n🚀 [bold]Next steps:[/bold]")
                    console.print(f"  1. cd {directory}")
                    console.print(f"  2. orcaops sandbox start")
                    console.print(f"  3. orcaops ps")
                    
                except Exception as e:
                    console.print(f"❌ Failed to create sandbox: {e}", style="red")
                    raise typer.Exit(1)
        
        @app.command("templates", help="📋 List available sandbox templates")
        def list_templates():
            """List all available sandbox templates"""
            templates = SandboxTemplates.get_templates()
            
            table = Table(title="🏗️ Available Sandbox Templates", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan", min_width=15)
            table.add_column("Description", style="blue")
            table.add_column("Services", style="green")
            
            for name, info in templates.items():
                services = ", ".join(info["services"].keys())
                table.add_row(name, info["description"], services)
            
            console.print(table)
            console.print(f"\n💡 Use [cyan]orcaops init <template-name>[/cyan] to create a new sandbox")
        
        @app.command("cleanup", help="🧹 Clean up unused containers, images, and volumes")
        def cleanup(
            containers: bool = typer.Option(True, "--containers", help="Remove stopped containers"),
            images: bool = typer.Option(False, "--images", help="Remove unused images"),
            volumes: bool = typer.Option(False, "--volumes", help="Remove unused volumes"),
            networks: bool = typer.Option(False, "--networks", help="Remove unused networks"),
            all_resources: bool = typer.Option(False, "--all", help="Clean up all unused resources"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be cleaned up")
        ):
            """Clean up Docker resources"""
            from rich.prompt import Confirm
            
            if all_resources:
                containers = images = volumes = networks = True
            
            dm = init_docker_manager()
            cleanup_summary = []
            
            if dry_run:
                console.print("🔍 [bold]Dry run - showing what would be cleaned up:[/bold]")
            
            # Clean up containers
            if containers:
                stopped_containers = [c for c in dm.list_running_containers(all=True) 
                                    if c.status != 'running']
                if stopped_containers:
                    cleanup_summary.append(f"Containers: {len(stopped_containers)} stopped")
                    if not dry_run:
                        if Confirm.ask(f"Remove {len(stopped_containers)} stopped containers?"):
                            for container in stopped_containers:
                                dm.rm(container.id)
                            console.print(f"✅ Removed {len(stopped_containers)} containers", style="green")
            
            # Clean up images
            if images:
                try:
                    unused_images = dm.client.images.list(filters={"dangling": True})
                    if unused_images:
                        cleanup_summary.append(f"Images: {len(unused_images)} unused")
                        if not dry_run:
                            if Confirm.ask(f"Remove {len(unused_images)} unused images?"):
                                for image in unused_images:
                                    dm.client.images.remove(image.id)
                                console.print(f"✅ Removed {len(unused_images)} images", style="green")
                except Exception as e:
                    console.print(f"⚠️ Could not clean images: {e}", style="yellow")
            
            # Clean up volumes
            if volumes:
                try:
                    unused_volumes = dm.client.volumes.list(filters={"dangling": True})
                    if unused_volumes:
                        cleanup_summary.append(f"Volumes: {len(unused_volumes)} unused")
                        if not dry_run:
                            if Confirm.ask(f"Remove {len(unused_volumes)} unused volumes?"):
                                for volume in unused_volumes:
                                    volume.remove()
                                console.print(f"✅ Removed {len(unused_volumes)} volumes", style="green")
                except Exception as e:
                    console.print(f"⚠️ Could not clean volumes: {e}", style="yellow")
            
            if cleanup_summary:
                if dry_run:
                    console.print("\n📋 [bold]Resources that would be cleaned:[/bold]")
                    for item in cleanup_summary:
                        console.print(f"  • {item}")
                    console.print("\n💡 Run without --dry-run to actually clean up")
                else:
                    console.print("🎉 Cleanup completed!", style="green")
            else:
                console.print("✨ Nothing to clean up!", style="green")
        
        @app.command("stats", help="📊 Show container resource usage statistics")
        def container_stats(
            name: Optional[str] = typer.Argument(None, help="Container name (optional)"),
            follow: bool = typer.Option(False, "--follow", "-f", help="Follow stats in real-time"),
            format_output: str = typer.Option("table", "--format", help="Output format: table, json")
        ):
            """Show container resource usage"""
            dm = init_docker_manager()
            
            if name:
                try:
                    container = dm.client.containers.get(name)
                    containers = [container]
                except docker.errors.NotFound:
                    console.print(f"❌ Container '{name}' not found", style="red")
                    raise typer.Exit(1)
            else:
                containers = dm.list_running_containers()
            
            if not containers:
                console.print("📭 No running containers found", style="yellow")
                return
            
            if follow:
                # Real-time stats
                try:
                    from rich.live import Live
                    import json
                    
                    def generate_stats_table():
                        table = Table(title="📊 Container Stats (Live)", show_header=True)
                        table.add_column("Name", style="cyan")
                        table.add_column("CPU %", style="green")
                        table.add_column("Memory", style="blue")
                        table.add_column("Network I/O", style="yellow")
                        table.add_column("Block I/O", style="magenta")
                        
                        for container in containers:
                            try:
                                stats = container.stats(stream=False)
                                
                                # Calculate CPU percentage
                                cpu_percent = 0.0
                                if 'cpu_stats' in stats and 'precpu_stats' in stats:
                                    cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                              stats['precpu_stats']['cpu_usage']['total_usage']
                                    system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                                                 stats['precpu_stats']['system_cpu_usage']
                                    if system_delta > 0:
                                        cpu_percent = (cpu_delta / system_delta) * \
                                                    len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100
                                
                                # Memory usage
                                memory_usage = stats.get('memory_stats', {}).get('usage', 0)
                                memory_limit = stats.get('memory_stats', {}).get('limit', 0)
                                memory_str = f"{CLIUtils.format_size(memory_usage)}"
                                if memory_limit > 0:
                                    memory_percent = (memory_usage / memory_limit) * 100
                                    memory_str += f" ({memory_percent:.1f}%)"
                                
                                # Network I/O
                                networks = stats.get('networks', {})
                                net_rx = sum(net.get('rx_bytes', 0) for net in networks.values())
                                net_tx = sum(net.get('tx_bytes', 0) for net in networks.values())
                                network_str = f"↓{CLIUtils.format_size(net_rx)} ↑{CLIUtils.format_size(net_tx)}"
                                
                                # Block I/O
                                blkio = stats.get('blkio_stats', {}).get('io_service_bytes_recursive', [])
                                blk_read = sum(item.get('value', 0) for item in blkio if item.get('op') == 'Read')
                                blk_write = sum(item.get('value', 0) for item in blkio if item.get('op') == 'Write')
                                block_str = f"↓{CLIUtils.format_size(blk_read)} ↑{CLIUtils.format_size(blk_write)}"
                                
                                table.add_row(
                                    container.name,
                                    f"{cpu_percent:.1f}%",
                                    memory_str,
                                    network_str,
                                    block_str
                                )
                            except Exception as e:
                                table.add_row(container.name, "Error", str(e), "-", "-")
                        
                        return table
                    
                    with Live(generate_stats_table(), refresh_per_second=1) as live:
                        while True:
                            time.sleep(1)
                            live.update(generate_stats_table())
                            
                except KeyboardInterrupt:
                    console.print("\n👋 Stats monitoring stopped")
            else:
                # Single stats snapshot
                table = Table(title="📊 Container Stats", show_header=True)
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("CPU %", style="yellow")
                table.add_column("Memory Usage", style="blue")
                
                for container in containers:
                    try:
                        if container.status == 'running':
                            stats = container.stats(stream=False)
                            # Simplified stats for snapshot
                            memory_usage = stats.get('memory_stats', {}).get('usage', 0)
                            memory_str = CLIUtils.format_size(memory_usage)
                            cpu_str = "Calculating..."
                        else:
                            memory_str = "-"
                            cpu_str = "-"
                        
                        status_icon = CLIUtils.get_container_status_icon(container.status)
                        table.add_row(
                            container.name,
                            f"{status_icon} {container.status}",
                            cpu_str,
                            memory_str
                        )
                    except Exception as e:
                        table.add_row(container.name, "Error", str(e), "-")
                
                console.print(table)

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
