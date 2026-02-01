"""Quota tracking — enforce workspace resource limits."""

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional, Set, Tuple

from orcaops.schemas import ResourceLimits, WorkspaceUsage


class QuotaTracker:
    """Thread-safe tracker for workspace resource consumption."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running_jobs: Dict[str, Set[str]] = defaultdict(set)
        self._running_sandboxes: Dict[str, Set[str]] = defaultdict(set)
        self._daily_counts: Dict[str, Dict[str, int]] = {}  # ws_id -> {date_str: count}

    def check_limits(
        self,
        workspace_id: str,
        limits: ResourceLimits,
        resource_type: str = "job",
    ) -> Tuple[bool, Optional[str]]:
        """Check if a workspace can start a new resource. Returns (allowed, reason)."""
        with self._lock:
            if resource_type == "job":
                current = len(self._running_jobs.get(workspace_id, set()))
                if current >= limits.max_concurrent_jobs:
                    return False, (
                        f"Concurrent job limit reached: {current}/{limits.max_concurrent_jobs}"
                    )
                # Daily limit check
                if limits.daily_job_limit is not None:
                    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    daily = self._daily_counts.get(workspace_id, {}).get(today, 0)
                    if daily >= limits.daily_job_limit:
                        return False, (
                            f"Daily job limit reached: {daily}/{limits.daily_job_limit}"
                        )
            elif resource_type == "sandbox":
                current = len(self._running_sandboxes.get(workspace_id, set()))
                if current >= limits.max_concurrent_sandboxes:
                    return False, (
                        f"Concurrent sandbox limit reached: {current}/{limits.max_concurrent_sandboxes}"
                    )

        return True, None

    def on_job_start(self, workspace_id: str, job_id: str) -> None:
        """Record that a job has started running."""
        with self._lock:
            self._running_jobs[workspace_id].add(job_id)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if workspace_id not in self._daily_counts:
                self._daily_counts[workspace_id] = {}
            self._daily_counts[workspace_id][today] = (
                self._daily_counts[workspace_id].get(today, 0) + 1
            )

    def on_job_end(self, workspace_id: str, job_id: str) -> None:
        """Record that a job has finished."""
        with self._lock:
            jobs = self._running_jobs.get(workspace_id)
            if jobs:
                jobs.discard(job_id)

    def on_sandbox_start(self, workspace_id: str, sandbox_id: str) -> None:
        """Record that a sandbox has started."""
        with self._lock:
            self._running_sandboxes[workspace_id].add(sandbox_id)

    def on_sandbox_end(self, workspace_id: str, sandbox_id: str) -> None:
        """Record that a sandbox has stopped."""
        with self._lock:
            sandboxes = self._running_sandboxes.get(workspace_id)
            if sandboxes:
                sandboxes.discard(sandbox_id)

    def get_usage(self, workspace_id: str) -> WorkspaceUsage:
        """Get current usage snapshot for a workspace."""
        with self._lock:
            running_jobs = len(self._running_jobs.get(workspace_id, set()))
            running_sandboxes = len(self._running_sandboxes.get(workspace_id, set()))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            jobs_today = self._daily_counts.get(workspace_id, {}).get(today, 0)

        return WorkspaceUsage(
            workspace_id=workspace_id,
            current_running_jobs=running_jobs,
            current_running_sandboxes=running_sandboxes,
            jobs_today=jobs_today,
        )
