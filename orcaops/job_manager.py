import os
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from orcaops.docker_manager import DockerManager
from orcaops.job_runner import JobRunner
from orcaops.schemas import JobSpec, RunRecord, JobStatus


@dataclass
class JobEntry:
    spec: JobSpec
    record: RunRecord
    thread: threading.Thread
    cancel_event: threading.Event


class JobManager:
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or os.path.expanduser("~/.orcaops/artifacts")
        os.makedirs(self.output_dir, exist_ok=True)
        self.runner = JobRunner(self.output_dir)
        self._docker = DockerManager()
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobEntry] = {}

    def submit_job(self, spec: JobSpec) -> RunRecord:
        if not spec.job_id:
            raise ValueError("job_id is required")

        with self._lock:
            if spec.job_id in self._jobs:
                raise ValueError(f"Job '{spec.job_id}' already exists")

            record = RunRecord(
                job_id=spec.job_id,
                status=JobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
                image_ref=spec.sandbox.image,
            )
            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run_job,
                args=(spec, cancel_event),
                daemon=True,
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
        with self._lock:
            entry = self._jobs.get(spec.job_id)
            if entry:
                entry.record.status = JobStatus.RUNNING
                entry.record.started_at = datetime.now(timezone.utc)

        record = self.runner.run_sandbox_job(spec)

        if cancel_event.is_set():
            record.status = JobStatus.CANCELLED
            record.error = "Job cancelled by user."

        with self._lock:
            entry = self._jobs.get(spec.job_id)
            if entry:
                entry.record = record

        if cancel_event.is_set():
            self._overwrite_run_record(record)

    def _overwrite_run_record(self, record: RunRecord) -> None:
        job_dir = os.path.join(self.output_dir, record.job_id)
        run_path = os.path.join(job_dir, "run.json")
        try:
            os.makedirs(job_dir, exist_ok=True)
            with open(run_path, "w", encoding="utf-8") as handle:
                handle.write(record.model_dump_json(indent=2))
        except OSError:
            return

    def get_job(self, job_id: str) -> Optional[RunRecord]:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry:
                return entry.record
        return self._load_job_from_disk(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[RunRecord]:
        with self._lock:
            records = [entry.record for entry in self._jobs.values()]

        if status:
            records = [record for record in records if record.status == status]

        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def cancel_job(self, job_id: str) -> Tuple[bool, Optional[RunRecord]]:
        with self._lock:
            entry = self._jobs.get(job_id)
            if not entry:
                return False, None

            entry.cancel_event.set()
            if entry.record.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                entry.record.status = JobStatus.CANCELLED
                entry.record.finished_at = datetime.now(timezone.utc)
                entry.record.error = "Job cancelled by user."

            container_id = entry.record.sandbox_id

        if container_id:
            try:
                self._docker.rm(container_id, force=True)
            except Exception:
                pass

        if entry:
            self._overwrite_run_record(entry.record)

        return True, entry.record

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
