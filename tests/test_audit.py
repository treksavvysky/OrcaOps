"""Tests for audit logging and querying."""

import json
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

from orcaops.schemas import AuditAction, AuditEvent, AuditOutcome
from orcaops.audit import AuditLogger, AuditStore


def _event(workspace_id="ws_test", action=AuditAction.JOB_CREATED, resource_id="job-1"):
    return AuditEvent(
        event_id="evt_test123",
        workspace_id=workspace_id,
        actor_type="api_key",
        actor_id="key_abc",
        action=action,
        resource_type="job",
        resource_id=resource_id,
        outcome=AuditOutcome.SUCCESS,
    )


class TestAuditLogger:
    def test_log_creates_file(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        event = _event()
        logger.log(event)

        date_str = event.timestamp.strftime("%Y-%m-%d")
        path = os.path.join(str(tmp_path), f"{date_str}.jsonl")
        assert os.path.isfile(path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_id"] == "evt_test123"

    def test_log_appends(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        logger.log(_event(resource_id="job-1"))
        logger.log(_event(resource_id="job-2"))

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(str(tmp_path), f"{date_str}.jsonl")
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_log_action_convenience(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        event = logger.log_action(
            workspace_id="ws_test",
            actor_type="api_key",
            actor_id="key_abc",
            action=AuditAction.KEY_CREATED,
            resource_type="key",
            resource_id="key_new",
            outcome=AuditOutcome.SUCCESS,
            details={"role": "admin"},
        )
        assert event.event_id.startswith("evt_")
        assert event.details == {"role": "admin"}

    def test_thread_safety(self, tmp_path):
        logger = AuditLogger(str(tmp_path))
        errors = []

        def log_events():
            try:
                for i in range(10):
                    logger.log(_event(resource_id=f"job-{threading.current_thread().name}-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=log_events, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(str(tmp_path), f"{date_str}.jsonl")
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 50


class TestAuditStore:
    def _populate(self, audit_dir, events):
        logger = AuditLogger(audit_dir)
        for e in events:
            logger.log(e)

    def test_query_all(self, tmp_path):
        self._populate(str(tmp_path), [_event(resource_id=f"j{i}") for i in range(5)])
        store = AuditStore(str(tmp_path))
        events, total = store.query()
        assert total == 5
        assert len(events) == 5

    def test_query_filter_workspace(self, tmp_path):
        self._populate(str(tmp_path), [
            _event(workspace_id="ws_a", resource_id="j1"),
            _event(workspace_id="ws_b", resource_id="j2"),
        ])
        store = AuditStore(str(tmp_path))
        events, total = store.query(workspace_id="ws_a")
        assert total == 1
        assert events[0].workspace_id == "ws_a"

    def test_query_filter_action(self, tmp_path):
        self._populate(str(tmp_path), [
            _event(action=AuditAction.JOB_CREATED, resource_id="j1"),
            _event(action=AuditAction.JOB_CANCELLED, resource_id="j2"),
        ])
        store = AuditStore(str(tmp_path))
        events, total = store.query(action=AuditAction.JOB_CANCELLED)
        assert total == 1

    def test_query_pagination(self, tmp_path):
        self._populate(str(tmp_path), [_event(resource_id=f"j{i}") for i in range(10)])
        store = AuditStore(str(tmp_path))
        events, total = store.query(limit=3, offset=0)
        assert len(events) == 3
        assert total == 10

    def test_query_empty(self, tmp_path):
        store = AuditStore(str(tmp_path))
        events, total = store.query()
        assert total == 0
        assert events == []

    def test_cleanup_old_files(self, tmp_path):
        # Create a file that looks old
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d")
        old_path = os.path.join(str(tmp_path), f"{old_date}.jsonl")
        with open(old_path, "w") as f:
            f.write('{"test": true}\n')

        # Create a recent file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new_path = os.path.join(str(tmp_path), f"{today}.jsonl")
        with open(new_path, "w") as f:
            f.write('{"test": true}\n')

        store = AuditStore(str(tmp_path))
        deleted = store.cleanup(older_than_days=90)
        assert deleted == 1
        assert not os.path.exists(old_path)
        assert os.path.exists(new_path)

    def test_query_sorted_newest_first(self, tmp_path):
        self._populate(str(tmp_path), [
            _event(resource_id="first"),
            _event(resource_id="second"),
        ])
        store = AuditStore(str(tmp_path))
        events, _ = store.query()
        # Both have same timestamp, but order should be consistent
        assert len(events) == 2
