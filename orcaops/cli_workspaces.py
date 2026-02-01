"""
CLI commands for workspace management, API keys, audit logs, and sessions.

All commands operate directly against core modules, not via HTTP.
"""

from datetime import datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from orcaops.workspace import WorkspaceRegistry
from orcaops.auth import KeyManager, ROLE_TEMPLATES
from orcaops.audit import AuditLogger, AuditStore
from orcaops.session_manager import SessionManager
from orcaops.schemas import (
    OwnerType,
    WorkspaceStatus,
    WorkspaceSettings,
    ResourceLimits,
    AuditAction,
)

console = Console()

_wr: Optional[WorkspaceRegistry] = None
_km: Optional[KeyManager] = None
_al: Optional[AuditLogger] = None
_as_: Optional[AuditStore] = None
_sm: Optional[SessionManager] = None


def _workspace_registry() -> WorkspaceRegistry:
    global _wr
    if _wr is None:
        _wr = WorkspaceRegistry()
    return _wr


def _key_manager() -> KeyManager:
    global _km
    if _km is None:
        _km = KeyManager()
    return _km


def _audit_logger() -> AuditLogger:
    global _al
    if _al is None:
        _al = AuditLogger()
    return _al


def _audit_store() -> AuditStore:
    global _as_
    if _as_ is None:
        _as_ = AuditStore()
    return _as_


def _session_manager() -> SessionManager:
    global _sm
    if _sm is None:
        _sm = SessionManager()
    return _sm


class WorkspaceCLI:
    """Workspace management CLI commands."""

    @staticmethod
    def add_commands(app: typer.Typer) -> None:
        ws_app = typer.Typer(name="workspace", help="Workspace management commands")

        @ws_app.command("create")
        def workspace_create(
            name: str = typer.Argument(..., help="Workspace name"),
            owner_type: str = typer.Option("user", help="Owner type: user, team, ai-agent"),
            owner_id: str = typer.Option("default", help="Owner identifier"),
        ):
            """Create a new workspace."""
            try:
                ot = OwnerType(owner_type)
            except ValueError:
                console.print(f"[red]Invalid owner type: {owner_type}[/red]")
                raise typer.Exit(code=1)

            try:
                ws = _workspace_registry().create_workspace(name, ot, owner_id)
                console.print(Panel(
                    f"[bold green]Workspace created[/bold green]\n"
                    f"ID: {ws.id}\n"
                    f"Name: {ws.name}\n"
                    f"Owner: {ws.owner_type.value}/{ws.owner_id}",
                    title="Workspace",
                    border_style="green",
                ))
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                raise typer.Exit(code=1)

        @ws_app.command("list")
        def workspace_list(
            status: Optional[str] = typer.Option(None, help="Filter by status"),
        ):
            """List workspaces."""
            ws_status = None
            if status:
                try:
                    ws_status = WorkspaceStatus(status)
                except ValueError:
                    console.print(f"[red]Invalid status: {status}[/red]")
                    raise typer.Exit(code=1)

            workspaces = _workspace_registry().list_workspaces(status=ws_status)
            if not workspaces:
                console.print("[dim]No workspaces found.[/dim]")
                return

            table = Table(title="Workspaces", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="cyan")
            table.add_column("Name")
            table.add_column("Owner")
            table.add_column("Status")
            table.add_column("Created")

            for ws in workspaces:
                status_color = {"active": "green", "suspended": "yellow", "archived": "dim"}.get(ws.status.value, "white")
                table.add_row(
                    ws.id,
                    ws.name,
                    f"{ws.owner_type.value}/{ws.owner_id}",
                    f"[{status_color}]{ws.status.value}[/{status_color}]",
                    ws.created_at.strftime("%Y-%m-%d %H:%M"),
                )
            console.print(table)

        @ws_app.command("status")
        def workspace_status(
            workspace_id: str = typer.Argument(..., help="Workspace ID"),
        ):
            """Show workspace details with settings and limits."""
            ws = _workspace_registry().get_workspace(workspace_id)
            if ws is None:
                console.print(f"[red]Workspace '{workspace_id}' not found.[/red]")
                raise typer.Exit(code=1)

            info = (
                f"[bold cyan]ID:[/bold cyan] {ws.id}\n"
                f"[bold cyan]Name:[/bold cyan] {ws.name}\n"
                f"[bold cyan]Owner:[/bold cyan] {ws.owner_type.value}/{ws.owner_id}\n"
                f"[bold cyan]Status:[/bold cyan] {ws.status.value}\n"
                f"[bold cyan]Created:[/bold cyan] {ws.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"\n[bold]Settings:[/bold]\n"
                f"  Cleanup policy: {ws.settings.default_cleanup_policy}\n"
                f"  Max job timeout: {ws.settings.max_job_timeout}s\n"
                f"  Retention days: {ws.settings.retention_days}\n"
                f"\n[bold]Limits:[/bold]\n"
                f"  Max concurrent jobs: {ws.limits.max_concurrent_jobs}\n"
                f"  Max concurrent sandboxes: {ws.limits.max_concurrent_sandboxes}\n"
                f"  Max job duration: {ws.limits.max_job_duration_seconds}s\n"
                f"  Max CPU/job: {ws.limits.max_cpu_per_job}\n"
                f"  Max memory/job: {ws.limits.max_memory_per_job_mb}MB\n"
                f"  Daily job limit: {ws.limits.daily_job_limit or 'unlimited'}"
            )
            console.print(Panel(info, title=f"Workspace {ws.id}", border_style="blue"))

        # --- Key management subcommands ---

        keys_app = typer.Typer(name="keys", help="API key management")

        @keys_app.command("create")
        def keys_create(
            workspace_id: str = typer.Argument(..., help="Workspace ID"),
            name: str = typer.Option("default", help="Key name"),
            role: str = typer.Option("admin", help="Role template: admin, developer, viewer, ci"),
        ):
            """Generate an API key for a workspace."""
            if role not in ROLE_TEMPLATES:
                console.print(f"[red]Invalid role: {role}. Choose from: {', '.join(ROLE_TEMPLATES.keys())}[/red]")
                raise typer.Exit(code=1)

            ws = _workspace_registry().get_workspace(workspace_id)
            if ws is None:
                console.print(f"[red]Workspace '{workspace_id}' not found.[/red]")
                raise typer.Exit(code=1)

            permissions = ROLE_TEMPLATES[role]
            plain_key, api_key = _key_manager().generate_key(workspace_id, name, permissions)
            console.print(Panel(
                f"[bold green]API Key Created[/bold green]\n\n"
                f"[bold]Key ID:[/bold] {api_key.key_id}\n"
                f"[bold]Plain Key:[/bold] [yellow]{plain_key}[/yellow]\n"
                f"[bold]Role:[/bold] {role}\n"
                f"[bold]Permissions:[/bold] {len(permissions)}\n\n"
                f"[dim]Store this key securely — it will not be shown again.[/dim]",
                title="API Key",
                border_style="green",
            ))

        @keys_app.command("list")
        def keys_list(
            workspace_id: str = typer.Argument(..., help="Workspace ID"),
        ):
            """List API keys for a workspace."""
            keys = _key_manager().list_keys(workspace_id)
            if not keys:
                console.print("[dim]No API keys found.[/dim]")
                return

            table = Table(title="API Keys", show_header=True, header_style="bold magenta")
            table.add_column("Key ID", style="cyan")
            table.add_column("Name")
            table.add_column("Permissions")
            table.add_column("Last Used")
            table.add_column("Revoked")

            for k in keys:
                last_used = k.last_used.strftime("%Y-%m-%d %H:%M") if k.last_used else "never"
                revoked_str = "[red]Yes[/red]" if k.revoked else "[green]No[/green]"
                table.add_row(
                    k.key_id,
                    k.name,
                    str(len(k.permissions)),
                    last_used,
                    revoked_str,
                )
            console.print(table)

        @keys_app.command("revoke")
        def keys_revoke(
            workspace_id: str = typer.Argument(..., help="Workspace ID"),
            key_id: str = typer.Argument(..., help="Key ID to revoke"),
        ):
            """Revoke an API key."""
            if _key_manager().revoke_key(workspace_id, key_id):
                console.print(f"[green]Key '{key_id}' revoked.[/green]")
            else:
                console.print(f"[red]Key '{key_id}' not found.[/red]")
                raise typer.Exit(code=1)

        ws_app.add_typer(keys_app, name="keys")

        # --- Audit subcommand ---

        @ws_app.command("audit")
        def workspace_audit(
            workspace_id: Optional[str] = typer.Option(None, "--workspace", help="Filter by workspace"),
            action: Optional[str] = typer.Option(None, "--action", help="Filter by action"),
            limit: int = typer.Option(20, "--limit", help="Max events to show"),
        ):
            """Query the audit log."""
            store = _audit_store()
            audit_action = None
            if action:
                try:
                    audit_action = AuditAction(action)
                except ValueError:
                    console.print(f"[red]Invalid action: {action}[/red]")
                    raise typer.Exit(code=1)

            events, total = store.query(
                workspace_id=workspace_id,
                action=audit_action,
                limit=limit,
            )

            if not events:
                console.print("[dim]No audit events found.[/dim]")
                return

            table = Table(title=f"Audit Log ({total} total)", show_header=True, header_style="bold magenta")
            table.add_column("Time", style="dim")
            table.add_column("Workspace", style="cyan")
            table.add_column("Action")
            table.add_column("Resource")
            table.add_column("Outcome")
            table.add_column("Actor")

            for e in events:
                outcome_color = {"success": "green", "denied": "red", "error": "yellow"}.get(e.outcome.value, "white")
                table.add_row(
                    e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    e.workspace_id,
                    e.action.value,
                    f"{e.resource_type}/{e.resource_id}",
                    f"[{outcome_color}]{e.outcome.value}[/{outcome_color}]",
                    f"{e.actor_type}/{e.actor_id}",
                )
            console.print(table)

        # --- Sessions subcommand ---

        @ws_app.command("sessions")
        def workspace_sessions(
            workspace_id: Optional[str] = typer.Option(None, "--workspace", help="Filter by workspace"),
        ):
            """List active agent sessions."""
            sessions = _session_manager().list_sessions(workspace_id=workspace_id)
            if not sessions:
                console.print("[dim]No sessions found.[/dim]")
                return

            table = Table(title="Agent Sessions", show_header=True, header_style="bold magenta")
            table.add_column("Session ID", style="cyan")
            table.add_column("Agent")
            table.add_column("Workspace")
            table.add_column("Status")
            table.add_column("Started")
            table.add_column("Resources")

            for s in sessions:
                status_color = {"active": "green", "idle": "yellow", "expired": "dim"}.get(s.status.value, "white")
                table.add_row(
                    s.session_id,
                    s.agent_type,
                    s.workspace_id,
                    f"[{status_color}]{s.status.value}[/{status_color}]",
                    s.started_at.strftime("%Y-%m-%d %H:%M"),
                    str(len(s.resources_created)),
                )
            console.print(table)

        app.add_typer(ws_app, name="workspace")
