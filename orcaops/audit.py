"""Audit logging — thread-safe JSONL-based event logging with date-based files."""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from orcaops.schemas import AuditAction, AuditEvent, AuditOutcome


class AuditLogger:
    """Thread-safe audit event logger writing to date-based JSONL files."""

    def __init__(self, audit_dir: Optional[str] = None):
        self._dir = audit_dir or os.path.expanduser("~/.orcaops/audit")
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event: AuditEvent) -> None:
        """Append an audit event to the date-based JSONL file."""
        date_str = event.timestamp.strftime("%Y-%m-%d")
        path = os.path.join(self._dir, f"{date_str}.jsonl")
        with self._lock:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(event.model_dump_json() + "\n")
            except OSError:
                pass

    def log_action(
        self,
        workspace_id: str,
        actor_type: str,
        actor_id: str,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        outcome: AuditOutcome,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AuditEvent:
        """Convenience method to create and log an audit event."""
        event = AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details or {},
            ip_address=ip_address,
        )
        self.log(event)
        return event


class AuditStore:
    """Read-only query layer for audit log files."""

    def __init__(self, audit_dir: Optional[str] = None):
        self._dir = audit_dir or os.path.expanduser("~/.orcaops/audit")

    def query(
        self,
        workspace_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AuditEvent], int]:
        """Query audit events with filtering."""
        events = self._load_events(after, before)

        # Apply filters
        if workspace_id:
            events = [e for e in events if e.workspace_id == workspace_id]
        if actor_id:
            events = [e for e in events if e.actor_id == actor_id]
        if action:
            events = [e for e in events if e.action == action]
        if resource_type:
            events = [e for e in events if e.resource_type == resource_type]

        # Sort newest first
        events.sort(key=lambda e: e.timestamp, reverse=True)
        total = len(events)
        return events[offset:offset + limit], total

    def cleanup(self, older_than_days: int = 90) -> int:
        """Delete audit log files older than N days."""
        if not os.path.isdir(self._dir):
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        deleted = 0
        for filename in os.listdir(self._dir):
            if not filename.endswith(".jsonl"):
                continue
            date_part = filename.replace(".jsonl", "")
            if date_part < cutoff_str:
                try:
                    os.unlink(os.path.join(self._dir, filename))
                    deleted += 1
                except OSError:
                    pass
        return deleted

    def _load_events(
        self,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
    ) -> List[AuditEvent]:
        """Load events from JSONL files, optionally filtering by date range."""
        if not os.path.isdir(self._dir):
            return []

        events: List[AuditEvent] = []
        for filename in sorted(os.listdir(self._dir)):
            if not filename.endswith(".jsonl"):
                continue
            # Date-based filtering on filenames
            date_part = filename.replace(".jsonl", "")
            if after and date_part < after.strftime("%Y-%m-%d"):
                continue
            if before and date_part > before.strftime("%Y-%m-%d"):
                continue

            path = os.path.join(self._dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            events.append(AuditEvent.model_validate(data))
                        except (json.JSONDecodeError, ValueError):
                            pass
            except OSError:
                pass

        return events
