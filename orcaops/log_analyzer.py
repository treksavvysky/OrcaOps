"""
Log analysis and job summary generation.

Uses regex-based pattern detection for errors, warnings, and stack traces.
Summary generation is deterministic (template-based, no LLM dependency).
"""

import re
from typing import List, Optional

from orcaops.schemas import (
    RunRecord,
    StepResult,
    LogAnalysis,
    JobSummary,
    JobStatus,
    Anomaly,
    ResourceUsage,
)


# --- Compiled pattern constants ---

ERROR_PATTERNS = [
    re.compile(r"(?i)\b(error|exception|fatal)\b[:\s]"),
    re.compile(r"(?i)\btraceback\b"),
    re.compile(r"(?i)\bfailed\b[:\s]"),
    re.compile(r"exit code [1-9]\d*"),
    re.compile(r"(?i)\bpanic\b[:\s]"),
]

WARNING_PATTERNS = [
    re.compile(r"(?i)\b(warning|warn)\b[:\s]"),
    re.compile(r"(?i)\bdeprecated\b"),
]

STACK_TRACE_START = [
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s+at\s+.+\(.+:\d+:\d+\)"),
    re.compile(r"^goroutine \d+ \["),
    re.compile(r"^\s+at\s+[\w.$]+\([\w.]+\.java:\d+\)"),
]

_MAX_STACK_TRACES = 5
_MAX_ERROR_LINES = 20
_MAX_LINE_LENGTH = 200


class LogAnalyzer:
    """Analyzes step output for errors, warnings, and stack traces."""

    def analyze_step(self, step: StepResult) -> LogAnalysis:
        """Analyze a single step's stdout and stderr."""
        combined = (step.stdout or "") + "\n" + (step.stderr or "")
        return self._analyze_text(combined)

    def analyze_record(self, record: RunRecord) -> LogAnalysis:
        """Aggregate log analysis across all steps."""
        total_errors = 0
        total_warnings = 0
        first_error: Optional[str] = None
        all_traces: List[str] = []
        all_error_lines: List[str] = []

        for step in record.steps:
            analysis = self.analyze_step(step)
            total_errors += analysis.error_count
            total_warnings += analysis.warning_count
            if first_error is None and analysis.first_error:
                first_error = analysis.first_error
            all_traces.extend(analysis.stack_traces)
            all_error_lines.extend(analysis.error_lines)

        return LogAnalysis(
            error_count=total_errors,
            warning_count=total_warnings,
            first_error=first_error,
            stack_traces=all_traces[:_MAX_STACK_TRACES],
            error_lines=all_error_lines[:_MAX_ERROR_LINES],
        )

    def _analyze_text(self, text: str) -> LogAnalysis:
        lines = text.split("\n")

        error_count = 0
        warning_count = 0
        first_error: Optional[str] = None
        error_lines: List[str] = []
        stack_traces: List[str] = []

        in_stack_trace = False
        current_trace: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_stack_trace and current_trace:
                    stack_traces.append("\n".join(current_trace))
                    current_trace = []
                    in_stack_trace = False
                continue

            # Use original line (preserves indentation) for stack trace patterns
            is_trace_start = False
            for pat in STACK_TRACE_START:
                if pat.search(line):
                    if in_stack_trace and current_trace:
                        stack_traces.append("\n".join(current_trace))
                    current_trace = [stripped]
                    in_stack_trace = True
                    is_trace_start = True
                    break

            if not is_trace_start and in_stack_trace:
                # Continue collecting stack trace lines (check original line for indentation)
                is_indented = line.startswith(("  ", "\t"))
                is_continuation = stripped.startswith(("Caused by", "..."))
                if is_indented or is_continuation:
                    current_trace.append(stripped)
                else:
                    # Non-indented line after trace start — include if it looks like
                    # the final exception line (e.g., "ValueError: bad")
                    if in_stack_trace and ":" in stripped:
                        current_trace.append(stripped)
                    stack_traces.append("\n".join(current_trace))
                    current_trace = []
                    in_stack_trace = False

            # Check error patterns
            for pat in ERROR_PATTERNS:
                if pat.search(stripped):
                    error_count += 1
                    truncated = stripped[:_MAX_LINE_LENGTH]
                    error_lines.append(truncated)
                    if first_error is None:
                        first_error = truncated
                    break

            # Check warning patterns (only if not already counted as error)
            else:
                for pat in WARNING_PATTERNS:
                    if pat.search(stripped):
                        warning_count += 1
                        break

        # Flush any remaining stack trace
        if in_stack_trace and current_trace:
            stack_traces.append("\n".join(current_trace))

        return LogAnalysis(
            error_count=error_count,
            warning_count=warning_count,
            first_error=first_error,
            stack_traces=stack_traces[:_MAX_STACK_TRACES],
            error_lines=error_lines[:_MAX_ERROR_LINES],
        )


class SummaryGenerator:
    """Generates deterministic job summaries from RunRecords."""

    def __init__(self):
        self.log_analyzer = LogAnalyzer()

    def generate(self, record: RunRecord) -> JobSummary:
        """Generate a summary for a job."""
        # Duration
        duration_secs = 0.0
        if record.started_at and record.finished_at:
            duration_secs = (record.finished_at - record.started_at).total_seconds()
        duration_human = self._format_duration(duration_secs)

        # Step stats
        step_count = len(record.steps)
        steps_passed = sum(1 for s in record.steps if s.exit_code == 0)
        steps_failed = step_count - steps_passed

        # Log analysis (use pre-computed if available)
        log_analysis = record.log_analysis or self.log_analyzer.analyze_record(record)

        # Status label
        status_map = {
            JobStatus.SUCCESS: "PASSED",
            JobStatus.FAILED: "FAILED",
            JobStatus.TIMED_OUT: "TIMED_OUT",
            JobStatus.CANCELLED: "CANCELLED",
            JobStatus.QUEUED: "QUEUED",
            JobStatus.RUNNING: "RUNNING",
        }
        status_label = status_map.get(record.status, record.status.value.upper())

        # Key events
        key_events = self._build_key_events(record, step_count, steps_passed)

        # One-liner
        one_liner = self._generate_one_liner(record, duration_human, log_analysis)

        # Suggestions
        suggestions = self._generate_suggestions(record, log_analysis)

        return JobSummary(
            job_id=record.job_id,
            one_liner=one_liner,
            status_label=status_label,
            duration_human=duration_human,
            step_count=step_count,
            steps_passed=steps_passed,
            steps_failed=steps_failed,
            key_events=key_events,
            errors=log_analysis.error_lines[:5],
            warnings=[],
            suggestions=suggestions,
            anomalies=list(record.anomalies),
        )

    def _build_key_events(self, record, step_count, steps_passed):
        events = []
        if record.status == JobStatus.SUCCESS:
            events.append(f"All {step_count} step(s) completed successfully")
        elif record.status == JobStatus.FAILED:
            events.append(f"Failed at step {steps_passed + 1} of {step_count}")
        elif record.status == JobStatus.TIMED_OUT:
            events.append("Job exceeded time limit")
        elif record.status == JobStatus.CANCELLED:
            events.append("Job was cancelled by user")

        if record.artifacts:
            events.append(f"Collected {len(record.artifacts)} artifact(s)")

        if record.resource_usage and record.resource_usage.memory_peak_mb > 0:
            events.append(f"Peak memory: {record.resource_usage.memory_peak_mb:.1f} MB")

        return events

    def _generate_one_liner(self, record, duration_human, log_analysis):
        if record.status == JobStatus.SUCCESS:
            return f"{len(record.steps)} step(s) passed in {duration_human}"
        elif record.status == JobStatus.FAILED:
            if log_analysis.first_error:
                return f"Failed: {log_analysis.first_error[:80]}"
            return f"Failed after {duration_human}"
        elif record.status == JobStatus.TIMED_OUT:
            return f"Timed out after {duration_human}"
        elif record.status == JobStatus.CANCELLED:
            return f"Cancelled after {duration_human}"
        return f"{record.status.value} in {duration_human}"

    def _generate_suggestions(self, record, log_analysis):
        suggestions = []
        if record.status == JobStatus.TIMED_OUT:
            suggestions.append("Consider increasing the timeout or optimizing the command")
        if record.status == JobStatus.FAILED and log_analysis.stack_traces:
            suggestions.append("Review the stack trace(s) for root cause")
        if record.status == JobStatus.FAILED and not log_analysis.first_error:
            suggestions.append("Check step stderr output for error details")
        if log_analysis.warning_count > 10:
            suggestions.append(
                f"{log_analysis.warning_count} warnings detected -- review for potential issues"
            )
        return suggestions

    @staticmethod
    def _format_duration(seconds):
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
