"""
Failure knowledge base for OrcaOps.

Provides pattern matching for known failure types and debug analysis
for failed jobs.
"""

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from orcaops.schemas import DebugAnalysis, FailurePattern, JobStatus, RunRecord


BUILTIN_PATTERNS: List[FailurePattern] = [
    FailurePattern(
        pattern_id="builtin_module_not_found",
        regex_pattern=r"ModuleNotFoundError: No module named '(\S+)'",
        category="dependency",
        title="Python module not found",
        description="A required Python module is not installed in the container.",
        solutions=[
            "Add the missing module to requirements.txt or Pipfile.",
            "Install the module in the Dockerfile: RUN pip install <module>.",
            "Use a base image that includes the module.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_npm_not_found",
        regex_pattern=r"(?:npm ERR!|Cannot find module) '(\S+)'",
        category="dependency",
        title="npm module not found",
        description="A required npm package is missing.",
        solutions=[
            "Run 'npm install' before executing the command.",
            "Add the missing package to package.json.",
            "Use a pre-built image with dependencies installed.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_oom",
        regex_pattern=r"(?:Killed|OOMKilled|out of memory|MemoryError|Cannot allocate memory)",
        category="oom",
        title="Out of memory",
        description="The process was killed due to memory limits.",
        solutions=[
            "Increase the container memory limit.",
            "Optimize memory usage in the application.",
            "Process data in smaller batches.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_connection_refused",
        regex_pattern=r"(?:Connection refused|ECONNREFUSED|ConnectionRefusedError)",
        category="network",
        title="Connection refused",
        description="A network connection was refused, typically a service is not running.",
        solutions=[
            "Ensure the target service is running and healthy.",
            "Check the service hostname and port configuration.",
            "Add a health check wait before connecting.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_permission_denied",
        regex_pattern=r"(?:Permission denied|EACCES|PermissionError)",
        category="permission",
        title="Permission denied",
        description="A file or resource access was denied.",
        solutions=[
            "Check file permissions in the container.",
            "Run as a different user or adjust ownership.",
            "Mount volumes with correct permissions.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_syntax_error",
        regex_pattern=r"(?:SyntaxError|IndentationError|TabError|ParseError)",
        category="syntax",
        title="Syntax error in code",
        description="The code contains a syntax error preventing execution.",
        solutions=[
            "Check the file mentioned in the traceback for syntax issues.",
            "Run a linter locally before submitting the job.",
            "Verify Python version compatibility.",
        ],
    ),
    FailurePattern(
        pattern_id="builtin_timeout",
        regex_pattern=r"(?:TimeoutError|timed out|ETIMEDOUT|deadline exceeded)",
        category="timeout",
        title="Operation timed out",
        description="An operation exceeded its time limit.",
        solutions=[
            "Increase the timeout value.",
            "Optimize the slow operation.",
            "Check for infinite loops or deadlocks.",
        ],
    ),
]


class FailureKnowledgeBase:
    """Pattern-based failure analysis and debug tool."""

    def __init__(self, custom_patterns_path: Optional[str] = None):
        self._custom_path = custom_patterns_path or os.path.expanduser(
            "~/.orcaops/failure_patterns.json"
        )
        self._lock = threading.Lock()
        self._patterns: List[FailurePattern] = list(BUILTIN_PATTERNS)
        self._load_custom()

    def _load_custom(self) -> None:
        if not os.path.isfile(self._custom_path):
            return
        try:
            with open(self._custom_path, "r") as f:
                data = json.load(f)
            for item in data:
                self._patterns.append(FailurePattern.model_validate(item))
        except Exception:
            pass

    def _save_custom(self) -> None:
        custom = [p for p in self._patterns if not p.pattern_id.startswith("builtin_")]
        os.makedirs(os.path.dirname(self._custom_path), exist_ok=True)
        with open(self._custom_path, "w") as f:
            json.dump([json.loads(p.model_dump_json()) for p in custom], f, indent=2)

    def match_patterns(self, error_text: str) -> List[FailurePattern]:
        matched = []
        for pattern in self._patterns:
            try:
                if re.search(pattern.regex_pattern, error_text):
                    matched.append(pattern)
            except re.error:
                continue
        return matched

    def analyze_failure(
        self, record: RunRecord, run_store=None,
    ) -> DebugAnalysis:
        # Gather error text from record
        error_parts = []
        if record.error:
            error_parts.append(record.error)
        for step in record.steps:
            if step.exit_code != 0:
                if step.stderr:
                    error_parts.append(step.stderr)
                if step.stdout:
                    error_parts.append(step.stdout)
        error_text = "\n".join(error_parts)

        # Match patterns
        matched = self.match_patterns(error_text)

        # Determine likely causes
        likely_causes = []
        if record.status == JobStatus.TIMED_OUT:
            likely_causes.append("Job exceeded its time limit.")
        for step in record.steps:
            if step.exit_code != 0:
                likely_causes.append(
                    f"Command '{step.command}' failed with exit code {step.exit_code}."
                )
        for pat in matched:
            likely_causes.append(pat.description)

        # Collect suggested fixes
        suggested_fixes = []
        for pat in matched:
            suggested_fixes.extend(pat.solutions)

        # Find similar failed jobs
        similar_ids: List[str] = []
        if run_store and record.image_ref:
            try:
                runs, _ = run_store.list_runs(
                    status=JobStatus.FAILED, image=record.image_ref, limit=5,
                )
                similar_ids = [
                    r.job_id for r in runs if r.job_id != record.job_id
                ]
            except Exception:
                pass

        # Generate next steps
        next_steps = []
        if not matched:
            next_steps.append("Review the full job logs for error details.")
        if matched:
            next_steps.append("Apply the suggested fixes and re-run the job.")
        if similar_ids:
            next_steps.append(f"Compare with similar failed jobs: {', '.join(similar_ids[:3])}.")
        next_steps.append("Check the container environment and dependencies.")

        # Summary
        if matched:
            summary = f"Found {len(matched)} matching failure pattern(s): {', '.join(p.title for p in matched)}."
        elif likely_causes:
            summary = likely_causes[0]
        else:
            summary = "No specific failure pattern matched. Manual investigation recommended."

        return DebugAnalysis(
            job_id=record.job_id,
            summary=summary,
            likely_causes=likely_causes,
            matched_patterns=matched,
            suggested_fixes=suggested_fixes,
            similar_job_ids=similar_ids,
            next_steps=next_steps,
        )

    def add_pattern(self, pattern: FailurePattern) -> None:
        with self._lock:
            self._patterns.append(pattern)
            self._save_custom()

    def list_patterns(self, category: Optional[str] = None) -> List[FailurePattern]:
        patterns = list(self._patterns)
        if category:
            patterns = [p for p in patterns if p.category == category]
        return patterns

    def record_occurrence(self, pattern_id: str) -> bool:
        with self._lock:
            for p in self._patterns:
                if p.pattern_id == pattern_id:
                    p.occurrences += 1
                    p.last_seen = datetime.now(timezone.utc)
                    if not p.pattern_id.startswith("builtin_"):
                        self._save_custom()
                    return True
            return False
