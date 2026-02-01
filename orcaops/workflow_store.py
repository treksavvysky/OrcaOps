"""
Disk-backed persistence for historical workflow records.
Scans ~/.orcaops/workflows/*/workflow.json.
"""

import json
import os
import shutil
from typing import List, Optional, Tuple

from orcaops.schemas import WorkflowRecord, WorkflowStatus


class WorkflowStore:
    """Disk-backed store for historical WorkflowRecords."""

    def __init__(self, workflows_dir: Optional[str] = None):
        self.workflows_dir = workflows_dir or os.path.expanduser("~/.orcaops/workflows")

    def list_workflows(
        self,
        status: Optional[WorkflowStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[WorkflowRecord], int]:
        """List workflow records with optional filtering and pagination."""
        records = self._scan_all()
        if status:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: r.created_at, reverse=True)
        total = len(records)
        return records[offset:offset + limit], total

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        """Get a single workflow record by ID."""
        path = os.path.join(self.workflows_dir, workflow_id, "workflow.json")
        return self._load(path)

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow record and its directory."""
        wf_dir = os.path.join(self.workflows_dir, workflow_id)
        if not os.path.isdir(wf_dir):
            return False
        shutil.rmtree(wf_dir)
        return True

    def _scan_all(self) -> List[WorkflowRecord]:
        """Scan all workflow.json files from disk."""
        records = []
        if not os.path.isdir(self.workflows_dir):
            return records
        for entry in os.listdir(self.workflows_dir):
            path = os.path.join(self.workflows_dir, entry, "workflow.json")
            rec = self._load(path)
            if rec:
                records.append(rec)
        return records

    def _load(self, path: str) -> Optional[WorkflowRecord]:
        """Load and validate a single WorkflowRecord from JSON."""
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return WorkflowRecord.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
