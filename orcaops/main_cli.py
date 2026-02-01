#!/usr/bin/env python3
"""
Main enhanced CLI entry point with all Phase 1 improvements
"""

import typer
from orcaops.cli_enhanced import app, init_docker_manager
from orcaops.cli_utils_fixed import CLICommands, CLIUtils

# Add enhanced commands to the main app
CLICommands.add_commands(app)

# Add job management commands
from orcaops.cli_jobs import JobCLI
JobCLI.add_commands(app)

@app.command("version", help="📦 Show OrcaOps version information")
def show_version():
    """Display version and system information"""
    from rich.panel import Panel
    import sys
    
    # Try to get package version
    try:
        import importlib.metadata
        version = importlib.metadata.version("orcaops")
    except Exception:
        version = "development"
    
    version_info = f"""
[bold cyan]OrcaOps[/bold cyan] v{version}
Python: {sys.version.split()[0]}
Platform: {sys.platform}

[dim]Advanced Docker container management and sandbox orchestration[/dim]
"""
    
    from rich.console import Console
    console = Console()
    console.print(Panel(version_info, title="📦 Version Info", border_style="blue"))

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    """🐋 OrcaOps - Advanced Docker Container Management"""
    if version:
        show_version()
        return
    
    if ctx.invoked_subcommand is None:
        CLIUtils.show_welcome_message()
        ctx.get_help()

if __name__ == "__main__":
    app()
