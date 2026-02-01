import os
import json
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from orcaops.docker_manager import DockerManager
from orcaops.job_runner import JobRunner
from orcaops.schemas import JobSpec, RunRecord, JobStatus, Anomaly, AuditAction, AuditOutcome

_TERMINAL_STATUSES = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMED_OUT, JobStatus.CANCELLED}
_MAX_COMPLETED_JOBS = 200


@dataclass
class JobEntry:
    spec: JobSpec
    record: RunRecord
    thread: threading.Thread
    cancel_event: threading.Event
    lock: threading.Lock = field(default_factory=threading.Lock)


class JobManager:
    def __init__(
        self,
        output_dir: Optional[str] = None,
        policy_engine=None,
        audit_logger=None,
        quota_tracker=None,
        workspace_registry=None,
        baseline_tracker=None,
    ):
        self.output_dir = output_dir or os.path.expanduser("~/.orcaops/artifacts")
        os.makedirs(self.output_dir, exist_ok=True)
        self.runner = JobRunner(self.output_dir)
        self._docker = DockerManager()
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobEntry] = {}
        self._policy_engine = policy_engine
        self._audit_logger = audit_logger
        self._quota_tracker = quota_tracker
        self._workspace_registry = workspace_registry
        self._baseline_tracker = baseline_tracker

    def submit_job(self, spec: JobSpec) -> RunRecord:
        if not spec.job_id:
            raise ValueError("job_id is required")

        # Policy enforcement
        if self._policy_engine:
            ws_settings = None
            if spec.workspace_id and self._workspace_registry:
                ws = self._workspace_registry.get_workspace(spec.workspace_id)
                if ws:
                    ws_settings = ws.settings
            from orcaops.policy_engine import PolicyEngine
            engine = PolicyEngine(self._policy_engine, workspace_settings=ws_settings)
            result = engine.validate_job(spec)
            if not result.allowed:
                if self._audit_logger:
                    self._audit_logger.log_action(
                        workspace_id=spec.workspace_id or "ws_default",
                        actor_type="system",
                        actor_id="job_manager",
                        action=AuditAction.POLICY_VIOLATION,
                        resource_type="job",
                        resource_id=spec.job_id,
                        outcome=AuditOutcome.DENIED,
                        details={"violations": result.violations},
                    )
                raise ValueError(
                    f"Policy violation: {'; '.join(result.violations)}"
                )

        # Quota enforcement
        if self._quota_tracker and spec.workspace_id and self._workspace_registry:
            ws = self._workspace_registry.get_workspace(spec.workspace_id)
            if ws:
                allowed, reason = self._quota_tracker.check_limits(
                    spec.workspace_id, ws.limits, resource_type="job"
                )
                if not allowed:
                    raise ValueError(f"Quota exceeded: {reason}")

        # Inject container security opts into metadata
        if self._policy_engine:
            from orcaops.policy_engine import PolicyEngine
            engine = PolicyEngine(self._policy_engine)
            sec_opts = engine.get_container_security_opts()
            spec.metadata["_security_opts"] = sec_opts

        with self._lock:
            if spec.job_id in self._jobs:
                raise ValueError(f"Job '{spec.job_id}' already exists")

            record = RunRecord(
                job_id=spec.job_id,
                status=JobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
                image_ref=spec.sandbox.image,
                workspace_id=spec.workspace_id,
            )
            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run_job,
                args=(spec, cancel_event),
                daemon=False,
            )
            self._jobs[spec.job_id] = JobEntry(
                spec=spec,
                record=record,
                thread=thread,
                cancel_event=cancel_event,
            )
            thread.start()

        return record

    def _run_job(self, spec: JobSpec, cancel_event: threading.Event) -> None:
        # Look up entry once
        with self._lock:
            entry = self._jobs.get(spec.job_id)
        if not entry:
            return

        # Mark as RUNNING
        with entry.lock:
            entry.record.status = JobStatus.RUNNING
            entry.record.started_at = datetime.now(timezone.utc)

        # Track quota
        if self._quota_tracker and spec.workspace_id:
            self._quota_tracker.on_job_start(spec.workspace_id, spec.job_id)

        # Long-running call — no locks held
        record = self.runner.run_sandbox_job(spec)

        # Update baseline tracking
        try:
            if self._baseline_tracker:
                tracker = self._baseline_tracker
            else:
                from orcaops.metrics import BaselineTracker
                tracker = BaselineTracker()
            anomaly = tracker.update(record)
            if anomaly:
                record.anomalies.append(anomaly)

            # Enhanced anomaly detection
            baseline = tracker.get_baseline(record)
            if baseline:
                from orcaops.anomaly_detector import AnomalyDetector, AnomalyStore
                detector = AnomalyDetector()
                anomaly_records = detector.detect(record, baseline)
                if anomaly_records:
                    store = AnomalyStore()
                    for ar in anomaly_records:
                        store.store(ar)
                        record.anomalies.append(Anomaly(
                            anomaly_type=ar.anomaly_type,
                            severity=ar.severity,
                            expected=ar.expected,
                            actual=ar.actual,
                            message=ar.description,
                        ))
        except Exception:
            pass  # Baseline tracking is best-effort

        # Update entry, but respect cancellation
        with entry.lock:
            if entry.cancel_event.is_set():
                # Cancellation was recorded by cancel_job() — preserve that status
                # but merge useful data from the completed run
                entry.record.steps = record.steps
                entry.record.artifacts = record.artifacts
                entry.record.cleanup_status = record.cleanup_status
            else:
                entry.record = record

            # Persist final state atomically
            self._overwrite_run_record(entry.record)

        # Release quota
        if self._quota_tracker and spec.workspace_id:
            self._quota_tracker.on_job_end(spec.workspace_id, spec.job_id)

        # Audit log completion
        if self._audit_logger and spec.workspace_id:
            self._audit_logger.log_action(
                workspace_id=spec.workspace_id,
                actor_type="system",
                actor_id="job_manager",
                action=AuditAction.JOB_COMPLETED,
                resource_type="job",
                resource_id=spec.job_id,
                outcome=AuditOutcome.SUCCESS if record.status == JobStatus.SUCCESS else AuditOutcome.ERROR,
                details={"status": record.status.value},
            )

        # Evict from in-memory cache now that it's persisted
        self._evict_if_terminal(spec.job_id)

    def _overwrite_run_record(self, record: RunRecord) -> None:
        """Write run record to disk atomically (temp file + rename)."""
        job_dir = os.path.join(self.output_dir, record.job_id)
        run_path = os.path.join(job_dir, "run.json")
        try:
            os.makedirs(job_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=job_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(record.model_dump_json(indent=2))
                os.replace(tmp_path, run_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            return

    def _evict_if_terminal(self, job_id: str) -> None:
        """Remove completed jobs from in-memory cache after persisting to disk."""
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry and entry.record.status in _TERMINAL_STATUSES:
                del self._jobs[job_id]

            # Safety net: cap in-memory entries
            if len(self._jobs) > _MAX_COMPLETED_JOBS:
                to_evict = [
                    jid for jid, e in self._jobs.items()
                    if e.record.status in _TERMINAL_STATUSES
                ]
                for jid in to_evict:
                    del self._jobs[jid]

    def get_job(self, job_id: str) -> Optional[RunRecord]:
        with self._lock:
            entry = self._jobs.get(job_id)
        if entry:
            with entry.lock:
                return entry.record.model_copy()
        return self._load_job_from_disk(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[RunRecord]:
        with self._lock:
            entries = list(self._jobs.values())

        records = []
        for entry in entries:
            with entry.lock:
                records.append(entry.record.model_copy())

        if status:
            records = [r for r in records if r.status == status]

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def cancel_job(self, job_id: str) -> Tuple[bool, Optional[RunRecord]]:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                return False, None

        with entry.lock:
            entry.cancel_event.set()
            if entry.record.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                entry.record.status = JobStatus.CANCELLED
                entry.record.finished_at = datetime.now(timezone.utc)
                entry.record.error = "Job cancelled by user."
            container_id = entry.record.sandbox_id
            record_snapshot = entry.record.model_copy()

        # Docker rm outside all locks (can be slow)
        if container_id:
            try:
                self._docker.rm(container_id, force=True)
            except Exception:
                pass

        # Persist cancellation
        self._overwrite_run_record(record_snapshot)

        return True, record_snapshot

    def get_artifact(self, job_id: str, filename: str) -> Optional[str]:
        job_dir = os.path.join(self.output_dir, job_id)
        path = os.path.join(job_dir, filename)
        if not os.path.exists(path):
            return None
        return path

    def list_artifacts(self, job_id: str) -> List[str]:
        job_dir = os.path.join(self.output_dir, job_id)
        if not os.path.isdir(job_dir):
            return []
        return [
            name
            for name in os.listdir(job_dir)
            if os.path.isfile(os.path.join(job_dir, name))
            and name not in {"run.json", "steps.jsonl"}
        ]

    def shutdown(self, timeout: float = 30.0) -> None:
        """Cancel all active jobs and wait for threads to finish."""
        with self._lock:
            active_entries = list(self._jobs.values())

        for entry in active_entries:
            entry.cancel_event.set()

        for entry in active_entries:
            entry.thread.join(timeout=timeout)

    def _load_job_from_disk(self, job_id: str) -> Optional[RunRecord]:
        run_path = os.path.join(self.output_dir, job_id, "run.json")
        if not os.path.exists(run_path):
            return None
        try:
            with open(run_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return RunRecord.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
