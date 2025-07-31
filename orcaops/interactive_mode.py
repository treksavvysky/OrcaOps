#!/usr/bin/env python3
"""
Enhanced interactive mode for OrcaOps container management
"""

import time
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.live import Live

console = Console()

class InteractiveMode:
    """Interactive container management interface"""
    
    def __init__(self, docker_manager):
        self.docker_manager = docker_manager
        self.running = True
    
    def start(self):
        """Start interactive mode"""
        console.clear()
        self.show_welcome()
        
        while self.running:
            try:
                self.main_menu()
            except KeyboardInterrupt:
                self.quit()
                break
            except Exception as e:
                console.print(f"❌ [red]Error: {e}[/red]")
                console.print("Press Enter to continue...")
                input()
    
    def show_welcome(self):
        """Display welcome message"""
        welcome_text = """
🎮 [bold blue]Interactive Container Management[/bold blue]

Navigate through containers and perform actions with ease.
Use Ctrl+C at any time to exit.

[dim]Features:[/dim]
• 📋 Browse containers with real-time status
• 🔍 Detailed container inspection
• 🎛️ Container lifecycle management
• 📝 Log viewing and monitoring
"""
        console.print(Panel(welcome_text, border_style="blue", padding=(1, 2)))
        input("Press Enter to continue...")
    
    def main_menu(self):
        """Display main menu and handle selection"""
        console.clear()
        
        # Get current containers
        containers = self.docker_manager.list_running_containers(all=True)
        
        # Create container table
        if containers:
            table = self.create_container_table(containers)
            console.print(table)
        else:
            console.print("📭 [yellow]No containers found[/yellow]")
        
        # Menu options
        console.print("\n🎯 [bold]Available Actions:[/bold]")
        
        menu_options = [
            ("list", "📋 Refresh container list"),
            ("select", "🎯 Select and manage a container"),
            ("logs", "📝 View container logs"),
            ("create", "🆕 Run a new container"),
            ("cleanup", "🧹 Clean up stopped containers"),
            ("monitor", "📊 Monitor running containers"),
            ("quit", "🚪 Exit interactive mode")
        ]
        
        for key, description in menu_options:
            console.print(f"  [cyan]{key}[/cyan]: {description}")
        
        # Get user choice
        try:
            choice = Prompt.ask(
                "\n🎬 Choose an action",
                choices=[opt[0] for opt in menu_options],
                default="list"
            )
            
            # Handle choice
            if choice == "list":
                return  # Refresh by returning to main loop
            elif choice == "select":
                self.container_selection_menu(containers)
            elif choice == "logs":
                self.logs_menu(containers)
            elif choice == "create":
                self.create_container_menu()
            elif choice == "cleanup":
                self.cleanup_menu()
            elif choice == "monitor":
                self.monitor_menu(containers)
            elif choice == "quit":
                self.quit()
                
        except KeyboardInterrupt:
            self.quit()
    
    def create_container_table(self, containers: List) -> Table:
        """Create a formatted table of containers"""
        running_count = len([c for c in containers if c.status == 'running'])
        total_count = len(containers)
        
        table = Table(
            title=f"🐋 Containers ({running_count} running, {total_count} total)",
            show_header=True,
            header_style="bold magenta"
        )
        
        table.add_column("#", style="dim", width=3)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Name", style="cyan", min_width=15)
        table.add_column("Image", style="blue", min_width=20)
        table.add_column("Created", style="dim")
        
        for i, container in enumerate(containers):
            # Status with icon
            status_icon = self.get_status_icon(container.status)
            status_display = f"{status_icon} {container.status.title()}"
            
            # Format creation time
            from datetime import datetime
            created = datetime.fromisoformat(container.attrs['Created'].replace('Z', '+00:00'))
            time_ago = datetime.now().astimezone() - created.astimezone()
            created_display = self.format_duration(time_ago.total_seconds()) + " ago"
            
            table.add_row(
                str(i + 1),
                status_display,
                container.name,
                container.image.tags[0] if container.image.tags else container.attrs['Config']['Image'],
                created_display
            )
        
        return table
    
    def container_selection_menu(self, containers: List):
        """Container selection and management menu"""
        if not containers:
            console.print("📭 [yellow]No containers available[/yellow]")
            input("Press Enter to continue...")
            return
        
        console.print("\n🎯 [bold]Select a container:[/bold]")
        console.print("Enter the number from the table above, or 'back' to return")
        
        try:
            choice = Prompt.ask("Container number")
            
            if choice.lower() == 'back':
                return
            
            container_index = int(choice) - 1
            if 0 <= container_index < len(containers):
                selected_container = containers[container_index]
                self.container_action_menu(selected_container)
            else:
                console.print("❌ [red]Invalid container number[/red]")
                input("Press Enter to continue...")
                
        except (ValueError, KeyboardInterrupt):
            console.print("❌ [red]Invalid selection[/red]")
            input("Press Enter to continue...")
    
    def container_action_menu(self, container):
        """Action menu for selected container"""
        while True:
            console.clear()
            
            # Container info panel
            info_panel = self.create_container_info_panel(container)
            console.print(info_panel)
            
            # Action options
            console.print("\n🎛️ [bold]Available Actions:[/bold]")
            
            actions = []
            
            # Status-specific actions
            if container.status == 'running':
                actions.extend([
                    ("logs", "📝 View logs"),
                    ("exec", "💻 Execute command"),
                    ("stop", "🛑 Stop container"),
                    ("restart", "🔄 Restart container"),
                ])
            elif container.status == 'exited':
                actions.extend([
                    ("start", "▶️ Start container"),
                    ("logs", "📝 View logs"),
                    ("remove", "🗑️ Remove container"),
                ])
            else:
                actions.extend([
                    ("logs", "📝 View logs"),
                    ("inspect", "🔍 Detailed inspection"),
                ])
            
            # Common actions
            actions.extend([
                ("inspect", "🔍 Detailed inspection"),
                ("back", "⬅️ Back to container list")
            ])
            
            for key, description in actions:
                console.print(f"  [cyan]{key}[/cyan]: {description}")
            
            try:
                action = Prompt.ask(
                    "\n🎬 Choose an action",
                    choices=[a[0] for a in actions]
                )
                
                if action == "back":
                    break
                elif action == "logs":
                    self.show_container_logs(container)
                elif action == "inspect":
                    self.show_container_inspection(container)
                elif action == "stop":
                    self.stop_container(container)
                    break  # Return to main menu after action
                elif action == "start":
                    self.start_container(container)
                    break
                elif action == "restart":
                    self.restart_container(container)
                    break
                elif action == "remove":
                    if self.remove_container(container):
                        break
                elif action == "exec":
                    self.exec_in_container(container)
                    
            except KeyboardInterrupt:
                break
    
    def create_container_info_panel(self, container) -> Panel:
        """Create info panel for container"""
        # Refresh container state
        container.reload()
        
        status_icon = self.get_status_icon(container.status)
        
        info_text = f"""
[bold cyan]Name:[/bold cyan] {container.name}
[bold cyan]ID:[/bold cyan] {container.short_id}
[bold cyan]Image:[/bold cyan] {container.image.tags[0] if container.image.tags else 'unknown'}
[bold cyan]Status:[/bold cyan] {status_icon} {container.status.title()}
[bold cyan]Created:[/bold cyan] {container.attrs['Created']}
"""
        
        # Add ports if running
        if container.status == 'running':
            ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
            if ports:
                port_info = "\n[bold green]Ports:[/bold green]\n"
                for internal, external in ports.items():
                    if external:
                        port_info += f"  • {external[0]['HostPort']} → {internal}\n"
                    else:
                        port_info += f"  • {internal} (not mapped)\n"
                info_text += port_info
        
        return Panel(info_text, title=f"🐋 Container: {container.name}", border_style="blue")
    
    def show_container_logs(self, container):
        """Show container logs with options"""
        console.clear()
        console.print(f"📝 [bold]Logs for {container.name}[/bold]")
        console.print("(Press Ctrl+C to stop)")
        
        try:
            follow = Confirm.ask("Follow logs in real-time?", default=False)
            
            if follow:
                console.print("\n🔄 [dim]Following logs... (Ctrl+C to stop)[/dim]")
                try:
                    self.docker_manager.logs(container.id, stream=True, follow=True, timestamps=True)
                except KeyboardInterrupt:
                    console.print("\n✅ [green]Stopped following logs[/green]")
            else:
                lines = Prompt.ask("Number of lines to show", default="50")
                try:
                    tail_lines = int(lines)
                    logs = self.docker_manager.logs(container.id, stream=False, tail=tail_lines, timestamps=True)
                    if logs:
                        console.print(f"\n📄 [dim]Last {tail_lines} lines:[/dim]")
                        console.print(logs)
                    else:
                        console.print("📭 [yellow]No logs available[/yellow]")
                except ValueError:
                    console.print("❌ [red]Invalid number of lines[/red]")
            
        except KeyboardInterrupt:
            pass
        
        input("\nPress Enter to continue...")
    
    def show_container_inspection(self, container):
        """Show detailed container inspection"""
        console.clear()
        
        try:
            # Get detailed container info
            container.reload()
            
            # Basic info
            console.print(f"🔍 [bold]Detailed Inspection: {container.name}[/bold]\n")
            
            # Create inspection table
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan", min_width=20)
            table.add_column("Value", style="white")
            
            # Add key information
            table.add_row("ID", container.id)
            table.add_row("Name", container.name)
            table.add_row("Image", container.image.tags[0] if container.image.tags else 'unknown')
            table.add_row("Status", f"{self.get_status_icon(container.status)} {container.status}")
            table.add_row("Created", container.attrs['Created'])
            
            if container.status == 'running':
                table.add_row("Started", container.attrs['State']['StartedAt'])
                
                # Network info
                networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                for net_name, net_data in networks.items():
                    ip = net_data.get('IPAddress', 'N/A')
                    table.add_row(f"Network ({net_name})", ip)
            
            # Environment variables
            env_vars = container.attrs.get('Config', {}).get('Env', [])
            if env_vars:
                env_display = '\n'.join([f"  • {var}" for var in env_vars[:5]])
                if len(env_vars) > 5:
                    env_display += f"\n  ... and {len(env_vars) - 5} more"
                table.add_row("Environment", env_display)
            
            console.print(table)
            
        except Exception as e:
            console.print(f"❌ [red]Error inspecting container: {e}[/red]")
        
        input("\nPress Enter to continue...")
    
    def stop_container(self, container):
        """Stop a container with confirmation"""
        if Confirm.ask(f"Stop container '{container.name}'?"):
            with console.status(f"[bold blue]Stopping {container.name}..."):
                success = self.docker_manager.stop(container.id)
            
            if success:
                console.print(f"✅ [green]Container '{container.name}' stopped[/green]")
            else:
                console.print(f"❌ [red]Failed to stop container '{container.name}'[/red]")
            
            input("Press Enter to continue...")
            return True
        return False
    
    def start_container(self, container):
        """Start a container"""
        with console.status(f"[bold blue]Starting {container.name}..."):
            try:
                container.start()
                console.print(f"✅ [green]Container '{container.name}' started[/green]")
            except Exception as e:
                console.print(f"❌ [red]Failed to start container: {e}[/red]")
        
        input("Press Enter to continue...")
        return True
    
    def restart_container(self, container):
        """Restart a container"""
        if Confirm.ask(f"Restart container '{container.name}'?"):
            with console.status(f"[bold blue]Restarting {container.name}..."):
                try:
                    container.restart()
                    console.print(f"✅ [green]Container '{container.name}' restarted[/green]")
                except Exception as e:
                    console.print(f"❌ [red]Failed to restart container: {e}[/red]")
            
            input("Press Enter to continue...")
            return True
        return False
    
    def remove_container(self, container):
        """Remove a container with confirmation"""
        console.print(f"⚠️ [bold yellow]WARNING[/bold yellow]: This will permanently delete the container!")
        console.print(f"Container: {container.name} ({container.status})")
        
        if Confirm.ask("Are you sure you want to remove this container?"):
            force = container.status == 'running'
            if force:
                force = Confirm.ask("Container is running. Force remove?", default=False)
            
            if force or container.status != 'running':
                with console.status(f"[bold blue]Removing {container.name}..."):
                    success = self.docker_manager.rm(container.id, force=force)
                
                if success:
                    console.print(f"✅ [green]Container '{container.name}' removed[/green]")
                    input("Press Enter to continue...")
                    return True
                else:
                    console.print(f"❌ [red]Failed to remove container '{container.name}'[/red]")
        
        input("Press Enter to continue...")
        return False
    
    def exec_in_container(self, container):
        """Execute command in container"""
        console.print(f"💻 [bold]Execute command in {container.name}[/bold]")
        
        try:
            command = Prompt.ask("Command to execute", default="/bin/sh")
            
            console.print(f"🔄 [dim]Executing: {command}[/dim]")
            console.print("(This will open an interactive session - type 'exit' to return)")
            
            # Execute command
            exec_result = container.exec_run(command, tty=True, stdin=True)
            console.print(exec_result.output.decode() if exec_result.output else "Command executed")
            
        except Exception as e:
            console.print(f"❌ [red]Error executing command: {e}[/red]")
        
        input("Press Enter to continue...")
    
    def logs_menu(self, containers: List):
        """Menu for viewing logs from any container"""
        if not containers:
            console.print("📭 [yellow]No containers available[/yellow]")
            input("Press Enter to continue...")
            return
        
        console.print("\n📝 [bold]Select container for log viewing:[/bold]")
        
        try:
            choice = Prompt.ask("Container number (from table above)")
            container_index = int(choice) - 1
            
            if 0 <= container_index < len(containers):
                selected_container = containers[container_index]
                self.show_container_logs(selected_container)
            else:
                console.print("❌ [red]Invalid container number[/red]")
                input("Press Enter to continue...")
                
        except (ValueError, KeyboardInterrupt):
            console.print("❌ [red]Invalid selection[/red]")
            input("Press Enter to continue...")
    
    def create_container_menu(self):
        """Menu for creating new containers"""
        console.clear()
        console.print("🆕 [bold]Create New Container[/bold]\n")
        
        try:
            # Get image name
            image = Prompt.ask("Docker image", default="nginx:alpine")
            
            # Get container name
            name = Prompt.ask("Container name (optional)", default="")
            
            # Get port mapping
            ports_input = Prompt.ask("Port mapping (format: host:container, optional)", default="")
            
            # Build run parameters
            run_params = {"detach": True}
            
            if name:
                run_params["name"] = name
            
            if ports_input and ":" in ports_input:
                try:
                    host_port, container_port = ports_input.split(":")
                    run_params["ports"] = {f"{container_port}/tcp": int(host_port)}
                except ValueError:
                    console.print("⚠️ [yellow]Invalid port format, skipping port mapping[/yellow]")
            
            # Create container
            with console.status(f"[bold blue]Creating container from {image}..."):
                container_id = self.docker_manager.run(image, **run_params)
            
            console.print(f"✅ [green]Container created with ID: {container_id[:12]}...[/green]")
            
        except Exception as e:
            console.print(f"❌ [red]Error creating container: {e}[/red]")
        
        input("Press Enter to continue...")
    
    def cleanup_menu(self):
        """Menu for cleanup operations"""
        console.clear()
        console.print("🧹 [bold]Container Cleanup[/bold]\n")
        
        # Get stopped containers
        all_containers = self.docker_manager.list_running_containers(all=True)
        stopped_containers = [c for c in all_containers if c.status != 'running']
        
        if not stopped_containers:
            console.print("✨ [green]No stopped containers to clean up![/green]")
            input("Press Enter to continue...")
            return
        
        console.print(f"Found {len(stopped_containers)} stopped containers:")
        for container in stopped_containers:
            status_icon = self.get_status_icon(container.status)
            console.print(f"  • {status_icon} {container.name} ({container.status})")
        
        if Confirm.ask(f"\nRemove all {len(stopped_containers)} stopped containers?"):
            removed_count = 0
            with console.status("[bold blue]Removing stopped containers..."):
                for container in stopped_containers:
                    if self.docker_manager.rm(container.id):
                        removed_count += 1
            
            console.print(f"✅ [green]Removed {removed_count} containers[/green]")
        else:
            console.print("🚫 [yellow]Cleanup cancelled[/yellow]")
        
        input("Press Enter to continue...")
    
    def monitor_menu(self, containers: List):
        """Real-time container monitoring"""
        running_containers = [c for c in containers if c.status == 'running']
        
        if not running_containers:
            console.print("📭 [yellow]No running containers to monitor[/yellow]")
            input("Press Enter to continue...")
            return
        
        console.print("📊 [bold]Real-time Container Monitoring[/bold]")
        console.print("(Press Ctrl+C to stop monitoring)\n")
        
        try:
            def generate_monitor_table():
                table = Table(title="📊 Container Stats (Live)", show_header=True)
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("CPU %", style="yellow")
                table.add_column("Memory", style="blue")
                
                for container in running_containers:
                    try:
                        container.reload()
                        status_icon = self.get_status_icon(container.status)
                        
                        # Get basic stats (simplified for demo)
                        if container.status == 'running':
                            try:
                                stats = container.stats(stream=False)
                                memory_usage = stats.get('memory_stats', {}).get('usage', 0)
                                memory_str = self.format_size(memory_usage)
                                cpu_str = "~" # Simplified for demo
                            except:
                                memory_str = "N/A"
                                cpu_str = "N/A"
                        else:
                            memory_str = "N/A"
                            cpu_str = "N/A"
                        
                        table.add_row(
                            container.name,
                            f"{status_icon} {container.status}",
                            cpu_str,
                            memory_str
                        )
                    except Exception as e:
                        table.add_row(container.name, "Error", str(e)[:20], "-")
                
                return table
            
            with Live(generate_monitor_table(), refresh_per_second=2) as live:
                while True:
                    time.sleep(0.5)
                    live.update(generate_monitor_table())
                    
        except KeyboardInterrupt:
            console.print("\n✅ [green]Monitoring stopped[/green]")
            input("Press Enter to continue...")
    
    def quit(self):
        """Exit interactive mode"""
        console.clear()
        console.print("👋 [bold blue]Thanks for using OrcaOps Interactive Mode![/bold blue]")
        console.print("Come back anytime for easy container management.")
        self.running = False
    
    @staticmethod
    def get_status_icon(status: str) -> str:
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
    
    @staticmethod
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
    
    @staticmethod
    def format_size(bytes_size: int) -> str:
        """Format bytes in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f}{unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f}PB"
