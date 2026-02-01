"""
Thread-safe workflow lifecycle manager.

Analogous to JobManager, but for workflows. Submits workflow execution
in background threads via WorkflowRunner.
"""

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from orcaops.job_manager import JobManager
from orcaops.schemas import WorkflowSpec, WorkflowRecord, WorkflowStatus
from orcaops.workflow_runner import WorkflowRunner


_TERMINAL_STATUSES = {
    WorkflowStatus.SUCCESS, WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED, WorkflowStatus.PARTIAL,
}

_MAX_COMPLETED = 100


@dataclass
class WorkflowEntry:
    record: WorkflowRecord
    thread: threading.Thread
    cancel_event: threading.Event
    lock: threading.Lock = field(default_factory=threading.Lock)


class WorkflowManager:
    """Thread-safe manager for workflow lifecycle."""

    def __init__(
        self,
        job_manager: Optional[JobManager] = None,
        workflows_dir: Optional[str] = None,
        max_parallel: int = 4,
    ):
        self.jm = job_manager or JobManager()
        self.workflows_dir = workflows_dir or os.path.expanduser("~/.orcaops/workflows")
        os.makedirs(self.workflows_dir, exist_ok=True)
        self.runner = WorkflowRunner(self.jm, max_parallel=max_parallel)
        self._lock = threading.Lock()
        self._workflows: Dict[str, WorkflowEntry] = {}

    def submit_workflow(
        self,
        spec: WorkflowSpec,
        workflow_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
    ) -> WorkflowRecord:
        """Submit a workflow for background execution. Returns initial record."""
        wf_id = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"

        with self._lock:
            if wf_id in self._workflows:
                raise ValueError(f"Workflow '{wf_id}' already exists")

            record = WorkflowRecord(
                workflow_id=wf_id,
                spec_name=spec.name,
                status=WorkflowStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                env=dict(spec.env),
                triggered_by=triggered_by,
            )

            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run_workflow,
                args=(spec, wf_id, cancel_event, triggered_by),
                daemon=True,
            )

            self._workflows[wf_id] = WorkflowEntry(
                record=record,
                thread=thread,
                cancel_event=cancel_event,
            )
            thread.start()

        return record

    def _run_workflow(
        self,
        spec: WorkflowSpec,
        workflow_id: str,
        cancel_event: threading.Event,
        triggered_by: Optional[str],
    ) -> None:
        """Background thread: run the workflow and persist result."""
        with self._lock:
            entry = self._workflows.get(workflow_id)
        if not entry:
            return

        final_record = self.runner.run(spec, workflow_id, cancel_event, triggered_by)

        with entry.lock:
            entry.record = final_record

        self._persist_record(final_record)
        self._evict_if_terminal(workflow_id)

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        """Get workflow record (from memory or disk)."""
        with self._lock:
            entry = self._workflows.get(workflow_id)
        if entry:
            with entry.lock:
                return entry.record.model_copy(deep=True)
        return self._load_from_disk(workflow_id)

    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None,
    ) -> List[WorkflowRecord]:
        """List workflows from memory."""
        with self._lock:
            entries = list(self._workflows.values())

        records = []
        for entry in entries:
            with entry.lock:
                records.append(entry.record.model_copy(deep=True))

        if status:
            records = [r for r in records if r.status == status]

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def cancel_workflow(self, workflow_id: str) -> Tuple[bool, Optional[WorkflowRecord]]:
        """Cancel a running workflow."""
        with self._lock:
            entry = self._workflows.get(workflow_id)
            if not entry:
                return False, None

        with entry.lock:
            entry.cancel_event.set()
            if entry.record.status in {WorkflowStatus.PENDING, WorkflowStatus.RUNNING}:
                entry.record.status = WorkflowStatus.CANCELLED
                entry.record.finished_at = datetime.now(timezone.utc)
                entry.record.error = "Workflow cancelled by user."
            snapshot = entry.record.model_copy(deep=True)

        self._persist_record(snapshot)
        return True, snapshot

    def shutdown(self, timeout: float = 30.0) -> None:
        """Cancel all active workflows and wait for threads."""
        with self._lock:
            active = list(self._workflows.values())
        for entry in active:
            entry.cancel_event.set()
        for entry in active:
            entry.thread.join(timeout=timeout)

    def _persist_record(self, record: WorkflowRecord) -> None:
        """Write workflow record atomically to disk."""
        wf_dir = os.path.join(self.workflows_dir, record.workflow_id)
        wf_path = os.path.join(wf_dir, "workflow.json")
        try:
            os.makedirs(wf_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=wf_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(record.model_dump_json(indent=2))
                os.replace(tmp_path, wf_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    def _load_from_disk(self, workflow_id: str) -> Optional[WorkflowRecord]:
        """Load workflow record from disk."""
        wf_path = os.path.join(self.workflows_dir, workflow_id, "workflow.json")
        if not os.path.isfile(wf_path):
            return None
        try:
            with open(wf_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return WorkflowRecord.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _evict_if_terminal(self, workflow_id: str) -> None:
        """Remove completed workflows from in-memory cache."""
        with self._lock:
            entry = self._workflows.get(workflow_id)
            if entry and entry.record.status in _TERMINAL_STATUSES:
                del self._workflows[workflow_id]
            if len(self._workflows) > _MAX_COMPLETED:
                to_evict = [
                    wid for wid, e in self._workflows.items()
                    if e.record.status in _TERMINAL_STATUSES
                ]
                for wid in to_evict:
                    del self._workflows[wid]
