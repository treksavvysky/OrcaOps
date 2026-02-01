"""FastAPI authentication middleware — auth context extraction and permission checking."""

from typing import List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from orcaops.schemas import Permission
from orcaops.auth import KeyManager, has_permission

security = HTTPBearer(auto_error=False)

# Module-level reference, set by the API layer at startup
_key_manager: Optional[KeyManager] = None


def set_key_manager(km: KeyManager) -> None:
    global _key_manager
    _key_manager = km


class AuthContext(BaseModel):
    """Authentication context injected into API endpoints."""
    workspace_id: str
    key_id: str
    permissions: List[Permission]
    actor_type: str = "api_key"
    actor_id: str


def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[AuthContext]:
    """Extract auth context from Bearer header.  Returns None if no header."""
    if credentials is None:
        return None
    if _key_manager is None:
        return None

    result = _key_manager.validate_key(credentials.credentials)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    api_key, workspace_id = result
    return AuthContext(
        workspace_id=workspace_id,
        key_id=api_key.key_id,
        permissions=list(api_key.permissions),
        actor_id=api_key.key_id,
    )


def require_auth(
    auth: Optional[AuthContext] = Depends(get_auth_context),
) -> AuthContext:
    """Require authentication.  Raises 401 if not authenticated."""
    if auth is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return auth


def require_permission(permission: Permission):
    """Factory returning a dependency that checks a specific permission."""
    def _checker(auth: AuthContext = Depends(require_auth)) -> AuthContext:
        if not has_permission(list(auth.permissions), permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission.value}' required",
            )
        return auth
    return _checker
