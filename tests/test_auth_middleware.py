"""Tests for auth middleware."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from orcaops.schemas import Permission
from orcaops.auth_middleware import AuthContext, get_auth_context, require_auth, require_permission


class FakeCredentials:
    def __init__(self, credentials: str):
        self.credentials = credentials


class TestAuthContext:
    def test_auth_context_model(self):
        ctx = AuthContext(
            workspace_id="ws_abc",
            key_id="key_abc",
            permissions=[Permission.JOB_READ],
            actor_id="key_abc",
        )
        assert ctx.workspace_id == "ws_abc"
        assert ctx.actor_type == "api_key"


class TestGetAuthContext:
    def test_no_credentials(self):
        from fastapi import Request
        mock_req = MagicMock(spec=Request)
        result = get_auth_context(mock_req, None)
        assert result is None

    def test_valid_key(self):
        from fastapi import Request
        from orcaops.schemas import APIKey
        import orcaops.auth_middleware as mod

        mock_km = MagicMock()
        mock_api_key = MagicMock()
        mock_api_key.key_id = "key_abc"
        mock_api_key.permissions = [Permission.JOB_READ, Permission.JOB_CREATE]
        mock_km.validate_key.return_value = (mock_api_key, "ws_abc")

        old_km = mod._key_manager
        mod._key_manager = mock_km
        try:
            mock_req = MagicMock(spec=Request)
            creds = FakeCredentials("orcaops_ws_abc_secret123")
            result = get_auth_context(mock_req, creds)
            assert result is not None
            assert result.workspace_id == "ws_abc"
            assert result.key_id == "key_abc"
        finally:
            mod._key_manager = old_km

    def test_invalid_key_raises_401(self):
        from fastapi import HTTPException, Request
        import orcaops.auth_middleware as mod

        mock_km = MagicMock()
        mock_km.validate_key.return_value = None

        old_km = mod._key_manager
        mod._key_manager = mock_km
        try:
            mock_req = MagicMock(spec=Request)
            creds = FakeCredentials("orcaops_ws_abc_badkey")
            with pytest.raises(HTTPException) as exc_info:
                get_auth_context(mock_req, creds)
            assert exc_info.value.status_code == 401
        finally:
            mod._key_manager = old_km

    def test_no_key_manager(self):
        from fastapi import Request
        import orcaops.auth_middleware as mod

        old_km = mod._key_manager
        mod._key_manager = None
        try:
            mock_req = MagicMock(spec=Request)
            creds = FakeCredentials("orcaops_ws_abc_secret")
            result = get_auth_context(mock_req, creds)
            assert result is None
        finally:
            mod._key_manager = old_km


class TestRequireAuth:
    def test_with_auth(self):
        ctx = AuthContext(
            workspace_id="ws_abc",
            key_id="key_abc",
            permissions=[Permission.JOB_READ],
            actor_id="key_abc",
        )
        assert require_auth(ctx) is ctx

    def test_without_auth_raises_401(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            require_auth(None)
        assert exc_info.value.status_code == 401


class TestRequirePermission:
    def test_has_permission(self):
        checker = require_permission(Permission.JOB_READ)
        ctx = AuthContext(
            workspace_id="ws_abc",
            key_id="key_abc",
            permissions=[Permission.JOB_READ],
            actor_id="key_abc",
        )
        result = checker(ctx)
        assert result is ctx

    def test_missing_permission_raises_403(self):
        from fastapi import HTTPException
        checker = require_permission(Permission.WORKSPACE_ADMIN)
        ctx = AuthContext(
            workspace_id="ws_abc",
            key_id="key_abc",
            permissions=[Permission.JOB_READ],
            actor_id="key_abc",
        )
        with pytest.raises(HTTPException) as exc_info:
            checker(ctx)
        assert exc_info.value.status_code == 403

    def test_admin_passes_any_permission(self):
        checker = require_permission(Permission.AUDIT_READ)
        ctx = AuthContext(
            workspace_id="ws_abc",
            key_id="key_abc",
            permissions=[Permission.WORKSPACE_ADMIN],
            actor_id="key_abc",
        )
        result = checker(ctx)
        assert result is ctx
