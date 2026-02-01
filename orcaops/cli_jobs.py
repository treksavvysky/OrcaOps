"""
CLI commands for job management.

All commands operate directly against JobManager and RunStore,
not via HTTP to the API server.
"""

import os
import shutil
import time
import uuid
from typing import List, Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from orcaops.job_manager import JobManager
from orcaops.run_store import RunStore
from orcaops.schemas import (
    JobSpec, SandboxSpec, JobCommand, JobStatus, RunRecord,
)

console = Console()

_job_manager: Optional[JobManager] = None
_run_store: Optional[RunStore] = None


def _get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager


def _get_run_store() -> RunStore:
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


_STATUS_COLORS = {
    JobStatus.QUEUED: "dim",
    JobStatus.RUNNING: "blue",
    JobStatus.SUCCESS: "green",
    JobStatus.FAILED: "red",
    JobStatus.TIMED_OUT: "yellow",
    JobStatus.CANCELLED: "dim red",
}


def _status_color(status: JobStatus) -> str:
    return _STATUS_COLORS.get(status, "white")


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs}s"


def _format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


class JobCLI:
    """Job management CLI commands."""

    @staticmethod
    def add_commands(app: typer.Typer):

        jobs_app = typer.Typer(
            name="jobs",
            help="Job management commands",
        )

        @app.command("run", help="Run a command in a sandbox container")
        def run_job(
            image: str = typer.Argument(..., help="Docker image to use"),
            command: Optional[List[str]] = typer.Argument(None, help="Command to execute"),
            env: Optional[List[str]] = typer.Option(None, "--env", "-e", help="Environment vars (KEY=VALUE)"),
            artifact: Optional[List[str]] = typer.Option(None, "--artifact", "-a", help="Artifact paths to collect"),
            timeout: int = typer.Option(3600, "--timeout", "-t", help="Timeout in seconds"),
            spec: Optional[str] = typer.Option(None, "--spec", "-s", help="Job spec YAML file"),
            follow: bool = typer.Option(False, "--follow", "-f", help="Follow job output"),
            job_id: Optional[str] = typer.Option(None, "--id", help="Custom job ID"),
        ):
            """Submit and run a job in a sandbox container."""
            jm = _get_job_manager()

            if spec:
                try:
                    with open(spec, "r") as f:
                        spec_data = yaml.safe_load(f)
                    job_spec = JobSpec.model_validate(spec_data)
                except Exception as e:
                    console.print(f"[red]Error loading spec file: {e}[/red]")
                    raise typer.Exit(1)
            else:
                if not command:
                    console.print("[red]Either provide a command or use --spec[/red]")
                    raise typer.Exit(1)

                env_dict = {}
                for e_str in (env or []):
                    if "=" not in e_str:
                        console.print(f"[red]Invalid env format '{e_str}', expected KEY=VALUE[/red]")
                        raise typer.Exit(1)
                    key, val = e_str.split("=", 1)
                    env_dict[key] = val

                generated_id = job_id or f"job-{uuid.uuid4().hex[:12]}"
                cmd_str = " ".join(command)

                job_spec = JobSpec(
                    job_id=generated_id,
                    sandbox=SandboxSpec(image=image, env=env_dict),
                    commands=[JobCommand(command=cmd_str, timeout_seconds=timeout)],
                    artifacts=list(artifact or []),
                    ttl_seconds=timeout,
                    triggered_by="cli",
                )

            try:
                record = jm.submit_job(job_spec)
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(1)

            console.print(f"[green]Job submitted:[/green] {record.job_id}")
            console.print(f"  Status: {record.status.value}")

            if follow:
                _follow_job(jm, record.job_id)

        @jobs_app.callback(invoke_without_command=True)
        def jobs_list(ctx: typer.Context):
            """List recent jobs (from both memory and disk)."""
            if ctx.invoked_subcommand is not None:
                return

            jm = _get_job_manager()
            rs = _get_run_store()

            active = jm.list_jobs()
            historical, _ = rs.list_runs(limit=50)

            active_ids = {r.job_id for r in active}
            combined = list(active)
            for r in historical:
                if r.job_id not in active_ids:
                    combined.append(r)

            combined.sort(key=lambda r: r.created_at, reverse=True)

            if not combined:
                console.print("[yellow]No jobs found.[/yellow]")
                return

            table = Table(title="Recent Jobs", show_header=True, header_style="bold magenta")
            table.add_column("Job ID", style="cyan", min_width=15)
            table.add_column("Status", min_width=10)
            table.add_column("Image", style="blue")
            table.add_column("Created", style="dim")
            table.add_column("Duration", style="dim")

            from datetime import datetime, timezone

            for r in combined[:20]:
                color = _status_color(r.status)
                duration = ""
                if r.started_at and r.finished_at:
                    dur_secs = (r.finished_at - r.started_at).total_seconds()
                    duration = _format_duration(dur_secs)
                elif r.started_at:
                    dur_secs = (datetime.now(timezone.utc) - r.started_at).total_seconds()
                    duration = _format_duration(dur_secs) + " (running)"

                table.add_row(
                    r.job_id,
                    f"[{color}]{r.status.value}[/{color}]",
                    r.image_ref or "-",
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "-",
                    duration,
                )

            console.print(table)

        @jobs_app.command("status", help="Show detailed job status")
        def job_status(
            job_id: str = typer.Argument(..., help="Job ID"),
        ):
            """Show detailed status of a specific job."""
            jm = _get_job_manager()
            rs = _get_run_store()

            record = jm.get_job(job_id) or rs.get_run(job_id)
            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                raise typer.Exit(1)

            _display_job_detail(record)

        @jobs_app.command("logs", help="Show or stream job logs")
        def job_logs(
            job_id: str = typer.Argument(..., help="Job ID"),
            follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
        ):
            """Display logs from a job's steps."""
            jm = _get_job_manager()
            rs = _get_run_store()

            record = jm.get_job(job_id) or rs.get_run(job_id)
            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                raise typer.Exit(1)

            if follow and record.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                _follow_job(jm, job_id)
            else:
                if not record.steps:
                    console.print("[yellow]No step output available.[/yellow]")
                    return
                for i, step in enumerate(record.steps):
                    console.print(f"\n[bold]Step {i + 1}:[/bold] {step.command}")
                    console.print(f"  Exit: {step.exit_code}  Duration: {_format_duration(step.duration_seconds)}")
                    if step.stdout:
                        console.print("[dim]--- stdout ---[/dim]")
                        console.print(step.stdout)
                    if step.stderr:
                        console.print("[red]--- stderr ---[/red]")
                        console.print(step.stderr)

        @jobs_app.command("cancel", help="Cancel a running job")
        def job_cancel(
            job_id: str = typer.Argument(..., help="Job ID"),
        ):
            """Cancel a running or queued job."""
            jm = _get_job_manager()
            cancelled, record = jm.cancel_job(job_id)
            if not cancelled:
                console.print(f"[red]Job '{job_id}' not found or already completed.[/red]")
                raise typer.Exit(1)
            console.print(f"[green]Job '{job_id}' cancelled.[/green]")

        @jobs_app.command("artifacts", help="List job artifacts")
        def job_artifacts(
            job_id: str = typer.Argument(..., help="Job ID"),
        ):
            """List artifacts collected from a job."""
            jm = _get_job_manager()
            rs = _get_run_store()

            record = jm.get_job(job_id) or rs.get_run(job_id)
            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                raise typer.Exit(1)

            artifacts = record.artifacts
            if not artifacts:
                file_list = jm.list_artifacts(job_id)
                if not file_list:
                    console.print("[yellow]No artifacts found.[/yellow]")
                    return
                for name in file_list:
                    console.print(f"  {name}")
                return

            table = Table(title=f"Artifacts for {job_id}", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Size", justify="right")
            table.add_column("SHA256", style="dim")

            for a in artifacts:
                size = _format_size(a.size_bytes)
                table.add_row(a.name, size, a.sha256[:16] + "...")

            console.print(table)

        @jobs_app.command("download", help="Download a job artifact")
        def job_download(
            job_id: str = typer.Argument(..., help="Job ID"),
            filename: str = typer.Argument(..., help="Artifact filename"),
            dest: str = typer.Option(".", "--dest", "-d", help="Destination directory"),
        ):
            """Download an artifact from a job to a local directory."""
            jm = _get_job_manager()
            src_path = jm.get_artifact(job_id, filename)
            if not src_path:
                console.print(f"[red]Artifact '{filename}' not found for job '{job_id}'.[/red]")
                raise typer.Exit(1)

            dest_path = os.path.join(dest, filename)
            shutil.copy2(src_path, dest_path)
            console.print(f"[green]Downloaded {filename} to {dest_path}[/green]")

        @jobs_app.command("summary", help="Show job execution summary")
        def job_summary(
            job_id: str = typer.Argument(..., help="Job ID"),
        ):
            """Display a deterministic summary of a job execution."""
            from orcaops.log_analyzer import SummaryGenerator

            jm = _get_job_manager()
            rs = _get_run_store()

            record = jm.get_job(job_id) or rs.get_run(job_id)
            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                raise typer.Exit(1)

            generator = SummaryGenerator()
            summary = generator.generate(record)

            color = _status_color(record.status)
            info = (
                f"[bold]{summary.one_liner}[/bold]\n\n"
                f"[bold cyan]Status:[/bold cyan] [{color}]{summary.status_label}[/{color}]\n"
                f"[bold cyan]Duration:[/bold cyan] {summary.duration_human}\n"
                f"[bold cyan]Steps:[/bold cyan] {summary.step_count} total, "
                f"{summary.steps_passed} passed, {summary.steps_failed} failed"
            )

            if summary.key_events:
                info += "\n\n[bold cyan]Key Events:[/bold cyan]"
                for event in summary.key_events:
                    info += f"\n  - {event}"

            if summary.errors:
                info += "\n\n[bold red]Errors:[/bold red]"
                for err in summary.errors:
                    info += f"\n  - {err}"

            if summary.warnings:
                info += "\n\n[bold yellow]Warnings:[/bold yellow]"
                for w in summary.warnings:
                    info += f"\n  - {w}"

            if summary.suggestions:
                info += "\n\n[bold green]Suggestions:[/bold green]"
                for s in summary.suggestions:
                    info += f"\n  - {s}"

            if summary.anomalies:
                info += "\n\n[bold magenta]Anomalies:[/bold magenta]"
                for a in summary.anomalies:
                    info += f"\n  - [{a.severity.value}] {a.message}"

            console.print(Panel(info, title=f"Summary: {job_id}", border_style="blue"))

        @app.command("metrics", help="Show aggregate job metrics")
        def metrics_command(
            from_date: Optional[str] = typer.Option(None, "--from", help="Start date (ISO 8601)"),
            to_date: Optional[str] = typer.Option(None, "--to", help="End date (ISO 8601)"),
        ):
            """Display aggregate job metrics from run history."""
            from datetime import datetime
            from orcaops.metrics import MetricsAggregator

            rs = _get_run_store()
            aggregator = MetricsAggregator(rs)

            fd = datetime.fromisoformat(from_date) if from_date else None
            td = datetime.fromisoformat(to_date) if to_date else None

            m = aggregator.compute_metrics(from_date=fd, to_date=td)

            table = Table(title="Job Metrics", show_header=True, header_style="bold magenta")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")

            table.add_row("Total Runs", str(m["total_runs"]))
            table.add_row("Success", f"[green]{m['success_count']}[/green]")
            table.add_row("Failed", f"[red]{m['failed_count']}[/red]")
            table.add_row("Timed Out", f"[yellow]{m['timed_out_count']}[/yellow]")
            table.add_row("Cancelled", str(m["cancelled_count"]))
            table.add_row("Success Rate", f"{m['success_rate'] * 100:.1f}%")
            table.add_row("Avg Duration", _format_duration(m["avg_duration_seconds"]))
            table.add_row("Total Duration", _format_duration(m["total_duration_seconds"]))

            console.print(table)

            if m["by_image"]:
                img_table = Table(title="By Image", show_header=True, header_style="bold magenta")
                img_table.add_column("Image", style="blue")
                img_table.add_column("Count", justify="right")
                img_table.add_column("Success", justify="right", style="green")
                img_table.add_column("Failed", justify="right", style="red")
                img_table.add_column("Avg Duration", justify="right")

                for img, data in m["by_image"].items():
                    img_table.add_row(
                        img,
                        str(data["count"]),
                        str(data["success"]),
                        str(data["failed"]),
                        _format_duration(data.get("avg_duration_seconds", 0)),
                    )

                console.print(img_table)

        @app.command("runs-cleanup", help="Cleanup old run records")
        def runs_cleanup(
            older_than: str = typer.Option("30d", "--older-than", help="Delete runs older than (e.g. 7d, 30d)"),
        ):
            """Delete historical run records older than the specified duration."""
            rs = _get_run_store()

            if not older_than.endswith("d"):
                console.print("[red]Duration must end with 'd' for days (e.g. 7d, 30d)[/red]")
                raise typer.Exit(1)
            try:
                days = int(older_than[:-1])
            except ValueError:
                console.print(f"[red]Invalid duration: {older_than}[/red]")
                raise typer.Exit(1)

            deleted = rs.cleanup_old_runs(older_than_days=days)

            if deleted:
                console.print(f"[green]Deleted {len(deleted)} run(s) older than {days} days.[/green]")
                for jid in deleted:
                    console.print(f"  - {jid}")
            else:
                console.print("[yellow]No runs to clean up.[/yellow]")

        app.add_typer(jobs_app, name="jobs")


def _follow_job(jm: JobManager, job_id: str):
    """Poll and display job status updates until completion."""
    terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED}
    seen_steps = 0

    with console.status(f"[bold blue]Following job {job_id}..."):
        while True:
            record = jm.get_job(job_id)
            if not record:
                rs = _get_run_store()
                record = rs.get_run(job_id)

            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                break

            for step in record.steps[seen_steps:]:
                console.print(f"\n[bold]Step:[/bold] {step.command}")
                console.print(f"  Exit: {step.exit_code}  Duration: {_format_duration(step.duration_seconds)}")
                if step.stdout:
                    console.print(step.stdout)
                if step.stderr:
                    console.print(f"[red]{step.stderr}[/red]")
            seen_steps = len(record.steps)

            if record.status in terminal:
                color = _status_color(record.status)
                console.print(f"\n[{color}]Job {record.status.value}[/{color}]")
                break

            time.sleep(1)


def _display_job_detail(record: RunRecord):
    """Display detailed job information."""
    color = _status_color(record.status)
    info = (
        f"[bold cyan]Job ID:[/bold cyan] {record.job_id}\n"
        f"[bold cyan]Status:[/bold cyan] [{color}]{record.status.value}[/{color}]\n"
        f"[bold cyan]Image:[/bold cyan] {record.image_ref or 'N/A'}\n"
        f"[bold cyan]Created:[/bold cyan] {record.created_at}\n"
        f"[bold cyan]Started:[/bold cyan] {record.started_at or 'N/A'}\n"
        f"[bold cyan]Finished:[/bold cyan] {record.finished_at or 'N/A'}\n"
        f"[bold cyan]Container:[/bold cyan] {record.sandbox_id or 'N/A'}\n"
        f"[bold cyan]Cleanup:[/bold cyan] {record.cleanup_status.value if record.cleanup_status else 'N/A'}\n"
        f"[bold cyan]Fingerprint:[/bold cyan] {record.fingerprint or 'N/A'}"
    )

    if record.error:
        info += f"\n[bold red]Error:[/bold red] {record.error}"

    console.print(Panel(info, title=f"Job {record.job_id}", border_style="blue"))

    if record.steps:
        table = Table(title="Steps", show_header=True, header_style="bold magenta")
        table.add_column("#", justify="right", width=3)
        table.add_column("Command", style="cyan")
        table.add_column("Exit", justify="center", width=6)
        table.add_column("Duration", justify="right")

        for i, step in enumerate(record.steps, 1):
            exit_color = "green" if step.exit_code == 0 else "red"
            table.add_row(
                str(i),
                step.command[:60],
                f"[{exit_color}]{step.exit_code}[/{exit_color}]",
                _format_duration(step.duration_seconds),
            )

        console.print(table)

    if record.artifacts:
        console.print(f"\n[bold]Artifacts:[/bold] {len(record.artifacts)}")
        for a in record.artifacts:
            console.print(f"  {a.name} ({_format_size(a.size_bytes)})")
