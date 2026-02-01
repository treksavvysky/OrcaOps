"""Workspace registry — CRUD for workspace records with thread-safe disk persistence."""

import json
import os
import secrets
import tempfile
import threading
from typing import Dict, List, Optional

from orcaops.schemas import (
    Workspace,
    WorkspaceSettings,
    WorkspaceStatus,
    OwnerType,
    ResourceLimits,
)

_DEFAULT_WORKSPACE_ID = "ws_default"


class WorkspaceRegistry:
    """Thread-safe workspace registry backed by JSON files."""

    def __init__(self, workspaces_dir: Optional[str] = None):
        self._dir = workspaces_dir or os.path.expanduser("~/.orcaops/workspaces")
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: Dict[str, Workspace] = {}
        self._load_all()

    # --- public API ---

    def create_workspace(
        self,
        name: str,
        owner_type: OwnerType,
        owner_id: str,
        settings: Optional[WorkspaceSettings] = None,
        limits: Optional[ResourceLimits] = None,
        workspace_id: Optional[str] = None,
    ) -> Workspace:
        ws_id = workspace_id or f"ws_{secrets.token_hex(8)}"
        ws = Workspace(
            id=ws_id,
            name=name,
            owner_type=owner_type,
            owner_id=owner_id,
            settings=settings or WorkspaceSettings(),
            limits=limits or ResourceLimits(),
        )
        with self._lock:
            if ws_id in self._cache:
                raise ValueError(f"Workspace '{ws_id}' already exists")
            # Check for duplicate names
            for existing in self._cache.values():
                if existing.name == name and existing.status != WorkspaceStatus.ARCHIVED:
                    raise ValueError(f"Workspace name '{name}' already in use")
            self._cache[ws_id] = ws
        self._persist(ws)
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        with self._lock:
            ws = self._cache.get(workspace_id)
        if ws is not None:
            return ws.model_copy()
        # Fallback to disk
        return self._load_from_disk(workspace_id)

    def get_default_workspace(self) -> Workspace:
        """Return the default workspace, creating it if needed."""
        ws = self.get_workspace(_DEFAULT_WORKSPACE_ID)
        if ws is not None:
            return ws
        return self.create_workspace(
            name="default",
            owner_type=OwnerType.USER,
            owner_id="system",
            workspace_id=_DEFAULT_WORKSPACE_ID,
        )

    def list_workspaces(
        self, status: Optional[WorkspaceStatus] = None,
    ) -> List[Workspace]:
        with self._lock:
            workspaces = list(self._cache.values())
        if status is not None:
            workspaces = [w for w in workspaces if w.status == status]
        return sorted(workspaces, key=lambda w: w.created_at, reverse=True)

    def update_workspace(
        self,
        workspace_id: str,
        settings: Optional[WorkspaceSettings] = None,
        limits: Optional[ResourceLimits] = None,
        status: Optional[WorkspaceStatus] = None,
    ) -> Workspace:
        with self._lock:
            ws = self._cache.get(workspace_id)
            if ws is None:
                raise ValueError(f"Workspace '{workspace_id}' not found")
            from datetime import datetime, timezone
            ws.updated_at = datetime.now(timezone.utc)
            if settings is not None:
                ws.settings = settings
            if limits is not None:
                ws.limits = limits
            if status is not None:
                ws.status = status
        self._persist(ws)
        return ws.model_copy()

    def archive_workspace(self, workspace_id: str) -> bool:
        try:
            self.update_workspace(workspace_id, status=WorkspaceStatus.ARCHIVED)
            return True
        except ValueError:
            return False

    # --- persistence ---

    def _persist(self, ws: Workspace) -> None:
        ws_dir = os.path.join(self._dir, ws.id)
        ws_path = os.path.join(ws_dir, "workspace.json")
        try:
            os.makedirs(ws_dir, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=ws_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(ws.model_dump_json(indent=2))
                os.replace(tmp_path, ws_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    def _load_from_disk(self, workspace_id: str) -> Optional[Workspace]:
        ws_path = os.path.join(self._dir, workspace_id, "workspace.json")
        if not os.path.exists(ws_path):
            return None
        try:
            with open(ws_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ws = Workspace.model_validate(data)
            with self._lock:
                self._cache[workspace_id] = ws
            return ws.model_copy()
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _load_all(self) -> None:
        """Scan disk and populate the in-memory cache."""
        if not os.path.isdir(self._dir):
            return
        for entry in os.listdir(self._dir):
            ws_path = os.path.join(self._dir, entry, "workspace.json")
            if os.path.isfile(ws_path):
                try:
                    with open(ws_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ws = Workspace.model_validate(data)
                    self._cache[ws.id] = ws
                except (OSError, json.JSONDecodeError, ValueError):
                    pass
