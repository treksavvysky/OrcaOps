"""
Run record persistence layer.

Scans ~/.orcaops/artifacts/*/run.json to provide historical run queries,
filtering, deletion, and cleanup operations.
"""

import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

from orcaops.schemas import RunRecord, JobStatus


class RunStore:
    """Disk-backed store for historical RunRecords."""

    def __init__(self, artifacts_dir: Optional[str] = None):
        self.artifacts_dir = artifacts_dir or os.path.expanduser("~/.orcaops/artifacts")

    def list_runs(
        self,
        status: Optional[JobStatus] = None,
        image: Optional[str] = None,
        tags: Optional[List[str]] = None,
        triggered_by: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[RunRecord], int]:
        """
        List historical run records from disk with optional filtering.

        Returns:
            Tuple of (paginated records, total matching count).
        """
        all_records = self._scan_all_records()

        if status:
            all_records = [r for r in all_records if r.status == status]
        if image:
            all_records = [r for r in all_records if r.image_ref and image in r.image_ref]
        if tags:
            all_records = [r for r in all_records if all(t in r.tags for t in tags)]
        if triggered_by:
            all_records = [r for r in all_records if r.triggered_by == triggered_by]
        if after:
            all_records = [r for r in all_records if r.created_at >= after]
        if before:
            all_records = [r for r in all_records if r.created_at <= before]
        if min_duration_seconds is not None:
            all_records = [r for r in all_records
                           if self._get_duration(r) >= min_duration_seconds]
        if max_duration_seconds is not None:
            all_records = [r for r in all_records
                           if self._get_duration(r) <= max_duration_seconds]

        all_records.sort(key=lambda r: r.created_at, reverse=True)

        total = len(all_records)
        sliced = all_records[offset:offset + limit]
        return sliced, total

    @staticmethod
    def _get_duration(record: RunRecord) -> float:
        """Get job duration in seconds."""
        if record.started_at and record.finished_at:
            return (record.finished_at - record.started_at).total_seconds()
        return 0.0

    def get_run(self, job_id: str) -> Optional[RunRecord]:
        """Get a specific run record by job_id."""
        run_path = os.path.join(self.artifacts_dir, job_id, "run.json")
        return self._load_record(run_path)

    def delete_run(self, job_id: str) -> bool:
        """Delete a run record and all its artifacts."""
        job_dir = os.path.join(self.artifacts_dir, job_id)
        if not os.path.isdir(job_dir):
            return False
        shutil.rmtree(job_dir)
        return True

    def cleanup_old_runs(self, older_than_days: int = 30) -> List[str]:
        """
        Delete run records older than N days.

        Returns:
            List of deleted job_ids.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        all_records = self._scan_all_records()
        deleted = []

        for record in all_records:
            if record.created_at < cutoff:
                if self.delete_run(record.job_id):
                    deleted.append(record.job_id)

        return deleted

    def _scan_all_records(self) -> List[RunRecord]:
        """Scan artifacts directory for all run.json files."""
        records = []
        if not os.path.isdir(self.artifacts_dir):
            return records

        for entry in os.listdir(self.artifacts_dir):
            run_path = os.path.join(self.artifacts_dir, entry, "run.json")
            record = self._load_record(run_path)
            if record:
                records.append(record)

        return records

    def _load_record(self, run_path: str) -> Optional[RunRecord]:
        """Load a single RunRecord from a run.json file."""
        if not os.path.isfile(run_path):
            return None
        try:
            with open(run_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RunRecord.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
