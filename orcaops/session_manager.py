"""Agent session management — track MCP sessions with lifecycle and resource attribution."""

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from orcaops.schemas import AgentSession, SessionStatus


class SessionManager:
    """Thread-safe manager for agent session lifecycle."""

    def __init__(
        self,
        sessions_dir: Optional[str] = None,
        idle_timeout_seconds: int = 1800,
    ):
        self._dir = sessions_dir or os.path.expanduser("~/.orcaops/sessions")
        os.makedirs(self._dir, exist_ok=True)
        self._idle_timeout = idle_timeout_seconds
        self._lock = threading.Lock()
        self._sessions: Dict[str, AgentSession] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load existing sessions from disk."""
        if not os.path.isdir(self._dir):
            return
        for filename in os.listdir(self._dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self._dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = AgentSession.model_validate(data)
                self._sessions[session.session_id] = session
            except (OSError, json.JSONDecodeError, ValueError):
                pass

    def create_session(
        self,
        agent_type: str,
        workspace_id: str,
        metadata: Optional[Dict] = None,
    ) -> AgentSession:
        """Create a new agent session."""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = AgentSession(
            session_id=session_id,
            agent_type=agent_type,
            workspace_id=workspace_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._sessions[session_id] = session
        self._persist(session)
        return session

    def touch_session(self, session_id: str) -> Optional[AgentSession]:
        """Update last_activity timestamp. Returns None if session not found."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if session.status == SessionStatus.EXPIRED:
                return None
            session.last_activity = datetime.now(timezone.utc)
            session.status = SessionStatus.ACTIVE
        self._persist(session)
        return session

    def track_resource(self, session_id: str, resource_id: str) -> bool:
        """Associate a created resource with a session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.resources_created.append(resource_id)
        self._persist(session)
        return True

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get a session by ID."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                return session.model_copy(deep=True)
        return None

    def list_sessions(
        self,
        workspace_id: Optional[str] = None,
        status: Optional[SessionStatus] = None,
    ) -> List[AgentSession]:
        """List sessions with optional filters."""
        with self._lock:
            sessions = list(self._sessions.values())

        if workspace_id:
            sessions = [s for s in sessions if s.workspace_id == workspace_id]
        if status:
            sessions = [s for s in sessions if s.status == status]

        return sorted(sessions, key=lambda s: s.started_at, reverse=True)

    def end_session(self, session_id: str) -> Optional[AgentSession]:
        """End a session explicitly. Returns the session or None."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.status = SessionStatus.EXPIRED
            session.last_activity = datetime.now(timezone.utc)
        self._persist(session)
        return session.model_copy(deep=True)

    def expire_idle_sessions(self) -> int:
        """Expire sessions that have been idle longer than the timeout."""
        now = datetime.now(timezone.utc)
        expired_count = 0
        with self._lock:
            for session in self._sessions.values():
                if session.status == SessionStatus.EXPIRED:
                    continue
                idle_seconds = (now - session.last_activity).total_seconds()
                if idle_seconds > self._idle_timeout:
                    session.status = SessionStatus.EXPIRED
                    expired_count += 1
                elif idle_seconds > self._idle_timeout / 2:
                    session.status = SessionStatus.IDLE

        # Persist changes outside lock
        if expired_count > 0:
            with self._lock:
                for session in self._sessions.values():
                    if session.status in (SessionStatus.EXPIRED, SessionStatus.IDLE):
                        self._persist(session)

        return expired_count

    def _persist(self, session: AgentSession) -> None:
        """Write session to disk atomically."""
        path = os.path.join(self._dir, f"{session.session_id}.json")
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(session.model_dump_json(indent=2))
                os.replace(tmp_path, path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    def delete_session(self, session_id: str) -> bool:
        """Remove a session from memory and disk."""
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
        path = os.path.join(self._dir, f"{session_id}.json")
        try:
            os.unlink(path)
        except OSError:
            pass
        return True
