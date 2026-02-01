"""
CLI commands for AI-driven optimization features.

Commands for optimization suggestions, predictions, anomaly listing,
recommendations, failure patterns, and job debugging.
"""

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from orcaops.metrics import BaselineTracker
from orcaops.run_store import RunStore
from orcaops.schemas import JobCommand, JobSpec, SandboxSpec

console = Console()

_baseline_tracker = None
_run_store = None


def _get_baseline_tracker():
    global _baseline_tracker
    if _baseline_tracker is None:
        _baseline_tracker = BaselineTracker()
    return _baseline_tracker


def _get_run_store():
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


class OptimizationCLI:
    """Optimization and AI-driven CLI commands."""

    @staticmethod
    def add_commands(app: typer.Typer):

        optimize_app = typer.Typer(
            name="optimize",
            help="AI-driven optimization, predictions, and debugging",
            no_args_is_help=True,
        )
        app.add_typer(optimize_app)

        @optimize_app.command("suggest", help="Get optimization suggestions for a job")
        def suggest_command(
            image: str = typer.Argument(..., help="Container image"),
            commands: str = typer.Argument(..., help="Pipe-separated commands (e.g. 'pytest|flake8')"),
            timeout: int = typer.Option(3600, "--timeout", "-t", help="Current timeout in seconds"),
        ):
            """Show optimization suggestions based on baselines."""
            from orcaops.auto_optimizer import AutoOptimizer

            cmd_list = [c.strip() for c in commands.split("|") if c.strip()]
            spec = JobSpec(
                job_id="cli-optimize",
                sandbox=SandboxSpec(image=image),
                commands=[JobCommand(command=c) for c in cmd_list],
                ttl_seconds=timeout,
            )
            ao = AutoOptimizer(_get_baseline_tracker())
            suggestions = ao.suggest_optimizations(spec)

            if not suggestions:
                console.print("[dim]No optimization suggestions available.[/dim]")
                return

            for s in suggestions:
                console.print(Panel(
                    f"[bold]{s.suggestion_type.upper()}[/bold]\n"
                    f"Current: {s.current_value}  ->  Suggested: [green]{s.suggested_value}[/green]\n"
                    f"Reason: {s.reason}\n"
                    f"Confidence: {s.confidence:.0%}",
                    title="Suggestion",
                    border_style="cyan",
                ))

        @optimize_app.command("predict", help="Predict job duration and failure risk")
        def predict_command(
            image: str = typer.Argument(..., help="Container image"),
            commands: str = typer.Argument(..., help="Pipe-separated commands"),
        ):
            """Show duration prediction and failure risk."""
            from orcaops.predictor import DurationPredictor, FailurePredictor

            cmd_list = [c.strip() for c in commands.split("|") if c.strip()]
            spec = JobSpec(
                job_id="cli-predict",
                sandbox=SandboxSpec(image=image),
                commands=[JobCommand(command=c) for c in cmd_list],
            )
            bt = _get_baseline_tracker()
            dur = DurationPredictor(bt).predict(spec)
            risk = FailurePredictor(bt).assess_risk(spec)

            console.print(Panel(
                f"[bold]Duration[/bold]: {dur.estimated_seconds:.1f}s "
                f"(confidence: {dur.confidence:.0%})\n"
                f"Range: {dur.range_low:.1f}s - {dur.range_high:.1f}s\n"
                f"Samples: {dur.sample_count}",
                title="Duration Prediction",
                border_style="blue",
            ))

            risk_color = "green" if risk.risk_level == "low" else "yellow" if risk.risk_level == "medium" else "red"
            console.print(Panel(
                f"[bold]Risk[/bold]: [{risk_color}]{risk.risk_level.upper()}[/{risk_color}] "
                f"(score: {risk.risk_score:.2f})\n"
                f"Factors: {'; '.join(risk.factors)}\n"
                f"Samples: {risk.sample_count}",
                title="Failure Risk",
                border_style=risk_color,
            ))

        @optimize_app.command("debug", help="Debug a failed job")
        def debug_command(
            job_id: str = typer.Argument(..., help="Job ID to debug"),
        ):
            """Analyze a failed job and suggest fixes."""
            from orcaops.knowledge_base import FailureKnowledgeBase

            rs = _get_run_store()
            record = rs.get_run(job_id)
            if not record:
                console.print(f"[red]Job '{job_id}' not found.[/red]")
                raise typer.Exit(1)

            kb = FailureKnowledgeBase()
            analysis = kb.analyze_failure(record, run_store=rs)

            console.print(Panel(
                f"[bold]{analysis.summary}[/bold]",
                title=f"Debug: {job_id}",
                border_style="red",
            ))

            if analysis.likely_causes:
                console.print("\n[bold]Likely Causes:[/bold]")
                for cause in analysis.likely_causes:
                    console.print(f"  - {cause}")

            if analysis.suggested_fixes:
                console.print("\n[bold green]Suggested Fixes:[/bold green]")
                for fix in analysis.suggested_fixes:
                    console.print(f"  - {fix}")

            if analysis.similar_job_ids:
                console.print(f"\n[bold]Similar failed jobs:[/bold] {', '.join(analysis.similar_job_ids)}")

            if analysis.next_steps:
                console.print("\n[bold]Next Steps:[/bold]")
                for step in analysis.next_steps:
                    console.print(f"  - {step}")

        @optimize_app.command("anomalies", help="List detected anomalies")
        def anomalies_command(
            anomaly_type: Optional[str] = typer.Option(None, "--type", help="Filter by type"),
            severity: Optional[str] = typer.Option(None, "--severity", help="Filter by severity"),
            limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
        ):
            """Show detected performance anomalies."""
            from orcaops.anomaly_detector import AnomalyStore
            from orcaops.schemas import AnomalyType, AnomalySeverity

            store = AnomalyStore()
            at = None
            if anomaly_type:
                try:
                    at = AnomalyType(anomaly_type)
                except ValueError:
                    console.print(f"[red]Invalid type: {anomaly_type}[/red]")
                    raise typer.Exit(1)
            sev = None
            if severity:
                try:
                    sev = AnomalySeverity(severity)
                except ValueError:
                    console.print(f"[red]Invalid severity: {severity}[/red]")
                    raise typer.Exit(1)

            anomalies, total = store.query(anomaly_type=at, severity=sev, limit=limit)

            if not anomalies:
                console.print("[dim]No anomalies found.[/dim]")
                return

            table = Table(title=f"Anomalies ({total} total)", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="dim", max_width=16)
            table.add_column("Job", style="cyan")
            table.add_column("Type")
            table.add_column("Severity")
            table.add_column("Title")
            table.add_column("Ack", justify="center")

            for a in anomalies:
                sev_color = "red" if a.severity.value == "critical" else "yellow"
                table.add_row(
                    a.anomaly_id[:16],
                    a.job_id,
                    a.anomaly_type.value,
                    f"[{sev_color}]{a.severity.value}[/{sev_color}]",
                    a.title,
                    "Y" if a.acknowledged else "N",
                )

            console.print(table)

        @optimize_app.command("recommendations", help="Show optimization recommendations")
        def recommendations_command(
            rec_type: Optional[str] = typer.Option(None, "--type", help="Filter by type"),
        ):
            """Show stored recommendations."""
            from orcaops.recommendation_engine import RecommendationStore
            from orcaops.schemas import RecommendationType

            store = RecommendationStore()
            rt = None
            if rec_type:
                try:
                    rt = RecommendationType(rec_type)
                except ValueError:
                    console.print(f"[red]Invalid type: {rec_type}[/red]")
                    raise typer.Exit(1)

            recs = store.list_recommendations(rec_type=rt)

            if not recs:
                console.print("[dim]No recommendations found. Run 'optimize generate' first.[/dim]")
                return

            for r in recs:
                priority_color = "red" if r.priority.value == "high" else "yellow" if r.priority.value == "medium" else "dim"
                console.print(Panel(
                    f"[{priority_color}]{r.priority.value.upper()}[/{priority_color}] "
                    f"[bold]{r.title}[/bold]\n"
                    f"{r.description}\n\n"
                    f"[green]Action:[/green] {r.action}\n"
                    f"[cyan]Impact:[/cyan] {r.impact}",
                    title=f"{r.rec_type.value} | {r.recommendation_id[:16]}",
                    border_style="blue",
                ))

        @optimize_app.command("patterns", help="List known failure patterns")
        def patterns_command(
            category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
        ):
            """Show known failure patterns from the knowledge base."""
            from orcaops.knowledge_base import FailureKnowledgeBase

            kb = FailureKnowledgeBase()
            patterns = kb.list_patterns(category=category)

            if not patterns:
                console.print("[dim]No patterns found.[/dim]")
                return

            table = Table(title="Failure Patterns", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="dim")
            table.add_column("Category")
            table.add_column("Title", style="cyan")
            table.add_column("Occurrences", justify="right")

            for p in patterns:
                table.add_row(
                    p.pattern_id,
                    p.category,
                    p.title,
                    str(p.occurrences),
                )

            console.print(table)
