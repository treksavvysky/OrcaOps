"""
CLI commands for workflow management.

All commands operate directly against WorkflowManager and WorkflowStore,
not via HTTP to the API server.
"""

import time
import uuid
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from orcaops.schemas import (
    JobStatus, WorkflowRecord, WorkflowStatus,
)
from orcaops.workflow_manager import WorkflowManager
from orcaops.workflow_store import WorkflowStore

console = Console()

_workflow_manager: Optional[WorkflowManager] = None
_workflow_store: Optional[WorkflowStore] = None


def _get_workflow_manager() -> WorkflowManager:
    global _workflow_manager
    if _workflow_manager is None:
        _workflow_manager = WorkflowManager()
    return _workflow_manager


def _get_workflow_store() -> WorkflowStore:
    global _workflow_store
    if _workflow_store is None:
        _workflow_store = WorkflowStore()
    return _workflow_store


_WF_STATUS_COLORS = {
    WorkflowStatus.PENDING: "dim",
    WorkflowStatus.RUNNING: "blue",
    WorkflowStatus.SUCCESS: "green",
    WorkflowStatus.FAILED: "red",
    WorkflowStatus.CANCELLED: "dim red",
    WorkflowStatus.PARTIAL: "yellow",
}

_JOB_STATUS_COLORS = {
    JobStatus.QUEUED: "dim",
    JobStatus.RUNNING: "blue",
    JobStatus.SUCCESS: "green",
    JobStatus.FAILED: "red",
    JobStatus.TIMED_OUT: "yellow",
    JobStatus.CANCELLED: "dim red",
}


def _wf_status_color(status: WorkflowStatus) -> str:
    return _WF_STATUS_COLORS.get(status, "white")


def _job_status_color(status: JobStatus) -> str:
    return _JOB_STATUS_COLORS.get(status, "white")


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


class WorkflowCLI:
    """Workflow management CLI commands."""

    @staticmethod
    def add_commands(app: typer.Typer):

        workflow_app = typer.Typer(
            name="workflow",
            help="Workflow management commands",
        )

        @workflow_app.command("run", help="Run a workflow from a YAML spec file")
        def workflow_run(
            spec_file: str = typer.Argument(..., help="Path to workflow spec YAML file"),
            follow: bool = typer.Option(False, "--follow", "-f", help="Follow workflow progress"),
            workflow_id: Optional[str] = typer.Option(None, "--id", help="Custom workflow ID"),
        ):
            """Load a workflow spec from YAML and submit for execution."""
            from orcaops.workflow_schema import load_workflow_spec, WorkflowValidationError

            wm = _get_workflow_manager()

            try:
                spec = load_workflow_spec(spec_file)
            except (FileNotFoundError, yaml.YAMLError) as e:
                console.print(f"[red]Error loading spec file: {e}[/red]")
                raise typer.Exit(1)
            except WorkflowValidationError as e:
                console.print(f"[red]Validation error: {e}[/red]")
                raise typer.Exit(1)

            wf_id = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"

            try:
                record = wm.submit_workflow(spec, workflow_id=wf_id, triggered_by="cli")
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(1)

            console.print(f"[green]Workflow submitted:[/green] {record.workflow_id}")
            console.print(f"  Status: {record.status.value}")
            console.print(f"  Jobs: {len(spec.jobs)}")

            if follow:
                _follow_workflow(wm, record.workflow_id)

        @workflow_app.command("status", help="Show detailed workflow status")
        def workflow_status(
            workflow_id: str = typer.Argument(..., help="Workflow ID"),
        ):
            """Show detailed status of a specific workflow."""
            wm = _get_workflow_manager()
            ws = _get_workflow_store()

            record = wm.get_workflow(workflow_id) or ws.get_workflow(workflow_id)
            if not record:
                console.print(f"[red]Workflow '{workflow_id}' not found.[/red]")
                raise typer.Exit(1)

            _display_workflow_detail(record)

        @workflow_app.command("cancel", help="Cancel a running workflow")
        def workflow_cancel(
            workflow_id: str = typer.Argument(..., help="Workflow ID"),
        ):
            """Cancel a running or pending workflow."""
            wm = _get_workflow_manager()
            cancelled, record = wm.cancel_workflow(workflow_id)
            if not cancelled:
                console.print(f"[red]Workflow '{workflow_id}' not found or already completed.[/red]")
                raise typer.Exit(1)
            console.print(f"[green]Workflow '{workflow_id}' cancelled.[/green]")

        @workflow_app.callback(invoke_without_command=True)
        def workflow_list(ctx: typer.Context):
            """List recent workflows."""
            if ctx.invoked_subcommand is not None:
                return

            wm = _get_workflow_manager()
            ws = _get_workflow_store()

            active = wm.list_workflows()
            historical, _ = ws.list_workflows(limit=50)

            active_ids = {r.workflow_id for r in active}
            combined = list(active)
            for r in historical:
                if r.workflow_id not in active_ids:
                    combined.append(r)

            combined.sort(key=lambda r: r.created_at, reverse=True)

            if not combined:
                console.print("[yellow]No workflows found.[/yellow]")
                return

            table = Table(title="Recent Workflows", show_header=True, header_style="bold magenta")
            table.add_column("Workflow ID", style="cyan", min_width=15)
            table.add_column("Spec", style="blue")
            table.add_column("Status", min_width=10)
            table.add_column("Jobs", justify="right")
            table.add_column("Created", style="dim")
            table.add_column("Duration", style="dim")

            from datetime import datetime, timezone

            for r in combined[:20]:
                color = _wf_status_color(r.status)
                duration = ""
                if r.started_at and r.finished_at:
                    dur_secs = (r.finished_at - r.started_at).total_seconds()
                    duration = _format_duration(dur_secs)
                elif r.started_at:
                    dur_secs = (datetime.now(timezone.utc) - r.started_at).total_seconds()
                    duration = _format_duration(dur_secs) + " (running)"

                job_count = str(len(r.job_statuses)) if r.job_statuses else "-"

                table.add_row(
                    r.workflow_id,
                    r.spec_name,
                    f"[{color}]{r.status.value}[/{color}]",
                    job_count,
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "-",
                    duration,
                )

            console.print(table)

        app.add_typer(workflow_app, name="workflow")


_TERMINAL_WF_STATUSES = {
    WorkflowStatus.SUCCESS, WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED, WorkflowStatus.PARTIAL,
}


def _follow_workflow(wm: WorkflowManager, workflow_id: str):
    """Poll and display workflow status updates until completion."""
    ws = _get_workflow_store()
    seen_jobs: dict = {}

    with console.status(f"[bold blue]Following workflow {workflow_id}..."):
        while True:
            record = wm.get_workflow(workflow_id)
            if not record:
                record = ws.get_workflow(workflow_id)

            if not record:
                console.print(f"[red]Workflow '{workflow_id}' not found.[/red]")
                break

            # Report job status changes
            for job_name, js in record.job_statuses.items():
                prev_status = seen_jobs.get(job_name)
                if prev_status != js.status:
                    color = _job_status_color(js.status)
                    console.print(f"  [{color}]{job_name}: {js.status.value}[/{color}]")
                    seen_jobs[job_name] = js.status

            if record.status in _TERMINAL_WF_STATUSES:
                color = _wf_status_color(record.status)
                console.print(f"\n[{color}]Workflow {record.status.value}[/{color}]")
                if record.error:
                    console.print(f"[red]Error: {record.error}[/red]")
                break

            time.sleep(1)


def _display_workflow_detail(record: WorkflowRecord):
    """Display detailed workflow information."""
    color = _wf_status_color(record.status)
    info = (
        f"[bold cyan]Workflow ID:[/bold cyan] {record.workflow_id}\n"
        f"[bold cyan]Spec:[/bold cyan] {record.spec_name}\n"
        f"[bold cyan]Status:[/bold cyan] [{color}]{record.status.value}[/{color}]\n"
        f"[bold cyan]Created:[/bold cyan] {record.created_at}\n"
        f"[bold cyan]Started:[/bold cyan] {record.started_at or 'N/A'}\n"
        f"[bold cyan]Finished:[/bold cyan] {record.finished_at or 'N/A'}\n"
        f"[bold cyan]Triggered by:[/bold cyan] {record.triggered_by or 'N/A'}"
    )

    if record.error:
        info += f"\n[bold red]Error:[/bold red] {record.error}"

    console.print(Panel(info, title=f"Workflow {record.workflow_id}", border_style="blue"))

    if record.job_statuses:
        table = Table(title="Jobs", show_header=True, header_style="bold magenta")
        table.add_column("Job Name", style="cyan")
        table.add_column("Status", min_width=10)
        table.add_column("Job ID", style="dim")
        table.add_column("Duration", style="dim")
        table.add_column("Error", style="red")

        for job_name, js in record.job_statuses.items():
            jcolor = _job_status_color(js.status)
            duration = ""
            if js.started_at and js.finished_at:
                dur = (js.finished_at - js.started_at).total_seconds()
                duration = _format_duration(dur)

            table.add_row(
                job_name,
                f"[{jcolor}]{js.status.value}[/{jcolor}]",
                js.job_id or "-",
                duration,
                (js.error or "")[:60],
            )

        console.print(table)
