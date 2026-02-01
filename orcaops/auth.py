"""API key management — generation, hashing, validation, and role templates."""

import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import bcrypt

from orcaops.schemas import APIKey, Permission


# --- Role templates ---

ROLE_TEMPLATES: Dict[str, List[Permission]] = {
    "admin": list(Permission),
    "developer": [
        Permission.JOB_CREATE,
        Permission.JOB_READ,
        Permission.JOB_CANCEL,
        Permission.WORKFLOW_CREATE,
        Permission.WORKFLOW_READ,
        Permission.WORKFLOW_CANCEL,
        Permission.SANDBOX_READ,
        Permission.SANDBOX_CREATE,
        Permission.SANDBOX_START,
        Permission.SANDBOX_STOP,
    ],
    "viewer": [
        Permission.JOB_READ,
        Permission.WORKFLOW_READ,
        Permission.SANDBOX_READ,
    ],
    "ci": [
        Permission.JOB_CREATE,
        Permission.JOB_READ,
        Permission.WORKFLOW_CREATE,
        Permission.WORKFLOW_READ,
    ],
}


def has_permission(permissions: List[Permission], required: Permission) -> bool:
    """Check whether *permissions* satisfy *required*, respecting inheritance."""
    if Permission.WORKSPACE_ADMIN in permissions:
        return True
    return required in permissions


class KeyManager:
    """Thread-safe API key manager backed by JSON files."""

    def __init__(self, keys_base_dir: Optional[str] = None):
        self._base = keys_base_dir or os.path.expanduser("~/.orcaops/workspaces")
        self._lock = threading.Lock()

    # --- public API ---

    def generate_key(
        self,
        workspace_id: str,
        name: str,
        permissions: Optional[List[Permission]] = None,
        role: Optional[str] = None,
        expires_in_days: Optional[int] = None,
    ) -> Tuple[str, APIKey]:
        """Create a new API key.  Returns ``(plain_key, APIKey)``."""
        if role and role in ROLE_TEMPLATES:
            perms = ROLE_TEMPLATES[role]
        elif permissions:
            perms = permissions
        else:
            perms = ROLE_TEMPLATES["viewer"]

        key_id = f"key_{secrets.token_hex(8)}"
        raw_secret = secrets.token_hex(16)
        plain_key = f"orcaops_{workspace_id}_{raw_secret}"

        key_hash = bcrypt.hashpw(plain_key.encode(), bcrypt.gensalt()).decode()

        expires_at: Optional[datetime] = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            workspace_id=workspace_id,
            permissions=perms,
            expires_at=expires_at,
        )

        self._persist_key(api_key)
        return plain_key, api_key

    def validate_key(self, plain_key: str) -> Optional[Tuple[APIKey, str]]:
        """Validate a plain key.  Returns ``(APIKey, workspace_id)`` or ``None``."""
        # Key format: orcaops_{workspace_id}_{secret}
        # workspace_id is ws_[alphanumeric]+, so we use regex to extract it
        m = re.match(r'^orcaops_(ws_[a-zA-Z0-9]+)_(.+)$', plain_key)
        if not m:
            return None

        workspace_id = m.group(1)
        keys = self._load_keys(workspace_id)

        for api_key in keys:
            if api_key.revoked:
                continue
            if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
                continue
            if bcrypt.checkpw(plain_key.encode(), api_key.key_hash.encode()):
                api_key.last_used = datetime.now(timezone.utc)
                self._persist_key(api_key)
                return api_key, workspace_id

        return None

    def revoke_key(self, workspace_id: str, key_id: str) -> bool:
        keys = self._load_keys(workspace_id)
        for api_key in keys:
            if api_key.key_id == key_id:
                api_key.revoked = True
                self._persist_key(api_key)
                return True
        return False

    def list_keys(self, workspace_id: str) -> List[APIKey]:
        """Return all non-revoked keys with the hash field cleared."""
        keys = self._load_keys(workspace_id)
        result = []
        for k in keys:
            if not k.revoked:
                copy = k.model_copy()
                copy.key_hash = "***"
                result.append(copy)
        return result

    def rotate_key(
        self, workspace_id: str, key_id: str,
    ) -> Optional[Tuple[str, APIKey]]:
        """Revoke old key and create a new one with the same permissions."""
        keys = self._load_keys(workspace_id)
        old_key = None
        for k in keys:
            if k.key_id == key_id and not k.revoked:
                old_key = k
                break
        if old_key is None:
            return None
        self.revoke_key(workspace_id, key_id)
        return self.generate_key(
            workspace_id=workspace_id,
            name=old_key.name,
            permissions=list(old_key.permissions),
            expires_in_days=None,
        )

    def has_keys(self, workspace_id: str) -> bool:
        """Return True if the workspace has at least one active key."""
        keys = self._load_keys(workspace_id)
        return any(not k.revoked for k in keys)

    # --- persistence ---

    def _keys_dir(self, workspace_id: str) -> str:
        d = os.path.join(self._base, workspace_id, "keys")
        os.makedirs(d, exist_ok=True)
        return d

    def _persist_key(self, api_key: APIKey) -> None:
        d = self._keys_dir(api_key.workspace_id)
        path = os.path.join(d, f"{api_key.key_id}.json")
        try:
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(api_key.model_dump_json(indent=2))
                os.replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    def _load_keys(self, workspace_id: str) -> List[APIKey]:
        d = self._keys_dir(workspace_id)
        keys: List[APIKey] = []
        if not os.path.isdir(d):
            return keys
        for entry in os.listdir(d):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, entry), "r", encoding="utf-8") as f:
                    data = json.load(f)
                keys.append(APIKey.model_validate(data))
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return keys
