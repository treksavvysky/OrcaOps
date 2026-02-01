"""Tests for agent session manager."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from orcaops.schemas import AgentSession, SessionStatus
from orcaops.session_manager import SessionManager


class TestSessionCreation:
    def test_create_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("claude-code", "ws_test")
        assert session.session_id.startswith("sess_")
        assert session.agent_type == "claude-code"
        assert session.workspace_id == "ws_test"
        assert session.status == SessionStatus.ACTIVE

    def test_create_with_metadata(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("claude-code", "ws_test", metadata={"model": "opus"})
        assert session.metadata == {"model": "opus"}

    def test_unique_ids(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        s1 = sm.create_session("agent", "ws_test")
        s2 = sm.create_session("agent", "ws_test")
        assert s1.session_id != s2.session_id


class TestSessionLifecycle:
    def test_get_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        retrieved = sm.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id

    def test_get_nonexistent(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        assert sm.get_session("nonexistent") is None

    def test_touch_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        original_activity = session.last_activity
        time.sleep(0.01)
        updated = sm.touch_session(session.session_id)
        assert updated is not None
        assert updated.last_activity >= original_activity

    def test_touch_expired_returns_none(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        sm.end_session(session.session_id)
        assert sm.touch_session(session.session_id) is None

    def test_end_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        ended = sm.end_session(session.session_id)
        assert ended is not None
        assert ended.status == SessionStatus.EXPIRED

    def test_end_nonexistent(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        assert sm.end_session("nonexistent") is None

    def test_delete_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        assert sm.delete_session(session.session_id) is True
        assert sm.get_session(session.session_id) is None

    def test_delete_nonexistent(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        assert sm.delete_session("nonexistent") is False


class TestResourceTracking:
    def test_track_resource(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        session = sm.create_session("agent", "ws_test")
        assert sm.track_resource(session.session_id, "job-1") is True
        assert sm.track_resource(session.session_id, "job-2") is True

        updated = sm.get_session(session.session_id)
        assert "job-1" in updated.resources_created
        assert "job-2" in updated.resources_created

    def test_track_nonexistent_session(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        assert sm.track_resource("nonexistent", "job-1") is False


class TestListAndFilter:
    def test_list_all(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        sm.create_session("agent-a", "ws_a")
        sm.create_session("agent-b", "ws_b")
        sessions = sm.list_sessions()
        assert len(sessions) == 2

    def test_filter_by_workspace(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        sm.create_session("agent", "ws_a")
        sm.create_session("agent", "ws_b")
        sessions = sm.list_sessions(workspace_id="ws_a")
        assert len(sessions) == 1
        assert sessions[0].workspace_id == "ws_a"

    def test_filter_by_status(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        s1 = sm.create_session("agent", "ws_test")
        sm.create_session("agent", "ws_test")
        sm.end_session(s1.session_id)

        active = sm.list_sessions(status=SessionStatus.ACTIVE)
        assert len(active) == 1

        expired = sm.list_sessions(status=SessionStatus.EXPIRED)
        assert len(expired) == 1


class TestIdleExpiration:
    def test_expire_idle_sessions(self, tmp_path):
        sm = SessionManager(str(tmp_path), idle_timeout_seconds=0)
        sm.create_session("agent", "ws_test")
        time.sleep(0.01)
        expired_count = sm.expire_idle_sessions()
        assert expired_count == 1

        sessions = sm.list_sessions(status=SessionStatus.EXPIRED)
        assert len(sessions) == 1

    def test_active_not_expired(self, tmp_path):
        sm = SessionManager(str(tmp_path), idle_timeout_seconds=3600)
        sm.create_session("agent", "ws_test")
        expired_count = sm.expire_idle_sessions()
        assert expired_count == 0


class TestPersistence:
    def test_persist_and_reload(self, tmp_path):
        sm1 = SessionManager(str(tmp_path))
        session = sm1.create_session("agent", "ws_test", metadata={"key": "value"})
        sm1.track_resource(session.session_id, "job-1")

        sm2 = SessionManager(str(tmp_path))
        reloaded = sm2.get_session(session.session_id)
        assert reloaded is not None
        assert reloaded.agent_type == "agent"
        assert reloaded.workspace_id == "ws_test"
        assert "job-1" in reloaded.resources_created


class TestThreadSafety:
    def test_concurrent_create(self, tmp_path):
        sm = SessionManager(str(tmp_path))
        errors = []
        sessions = []
        lock = threading.Lock()

        def create_many(prefix):
            try:
                for i in range(10):
                    s = sm.create_session(f"{prefix}-agent", "ws_test")
                    with lock:
                        sessions.append(s.session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_many, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(sessions) == 50
        assert len(set(sessions)) == 50  # all unique
