"""Tests for workspace/auth/audit/session MCP tools."""

import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from orcaops.schemas import (
    Workspace,
    OwnerType,
    WorkspaceStatus,
    WorkspaceSettings,
    ResourceLimits,
    APIKey,
    AuditEvent,
    AuditAction,
    AuditOutcome,
    AgentSession,
    SessionStatus,
)


def _make_workspace(id="ws_test", name="test"):
    return Workspace(
        id=id,
        name=name,
        owner_type=OwnerType.USER,
        owner_id="user1",
    )


class TestWorkspaceTools:
    @patch("orcaops.mcp_server._workspace_registry")
    def test_create_workspace(self, mock_wr):
        from orcaops.mcp_server import orcaops_create_workspace
        mock_wr.return_value.create_workspace.return_value = _make_workspace()
        result = json.loads(orcaops_create_workspace("test"))
        assert result["success"] is True
        assert result["workspace_id"] == "ws_test"

    @patch("orcaops.mcp_server._workspace_registry")
    def test_create_workspace_duplicate(self, mock_wr):
        from orcaops.mcp_server import orcaops_create_workspace
        mock_wr.return_value.create_workspace.side_effect = ValueError("duplicate")
        result = json.loads(orcaops_create_workspace("test"))
        assert result["success"] is False
        assert "duplicate" in result["error"]["message"]

    @patch("orcaops.mcp_server._workspace_registry")
    def test_list_workspaces(self, mock_wr):
        from orcaops.mcp_server import orcaops_list_workspaces
        mock_wr.return_value.list_workspaces.return_value = [_make_workspace()]
        result = json.loads(orcaops_list_workspaces())
        assert result["success"] is True
        assert result["count"] == 1
        assert result["workspaces"][0]["id"] == "ws_test"

    @patch("orcaops.mcp_server._workspace_registry")
    def test_get_workspace(self, mock_wr):
        from orcaops.mcp_server import orcaops_get_workspace
        mock_wr.return_value.get_workspace.return_value = _make_workspace()
        result = json.loads(orcaops_get_workspace("ws_test"))
        assert result["success"] is True
        assert result["name"] == "test"

    @patch("orcaops.mcp_server._workspace_registry")
    def test_get_workspace_not_found(self, mock_wr):
        from orcaops.mcp_server import orcaops_get_workspace
        mock_wr.return_value.get_workspace.return_value = None
        result = json.loads(orcaops_get_workspace("ws_none"))
        assert result["success"] is False


class TestAPIKeyTools:
    @patch("orcaops.mcp_server._key_manager_mcp")
    def test_create_api_key(self, mock_km):
        from orcaops.mcp_server import orcaops_create_api_key
        mock_key = APIKey(
            key_id="key_abc",
            key_hash="hash",
            name="test",
            workspace_id="ws_test",
            permissions=[],
        )
        mock_km.return_value.generate_key.return_value = ("orcaops_ws_test_secret", mock_key)
        result = json.loads(orcaops_create_api_key("ws_test"))
        assert result["success"] is True
        assert result["key_id"] == "key_abc"
        assert result["plain_key"] == "orcaops_ws_test_secret"

    def test_create_api_key_invalid_role(self):
        from orcaops.mcp_server import orcaops_create_api_key
        result = json.loads(orcaops_create_api_key("ws_test", role="invalid"))
        assert result["success"] is False
        assert "Invalid role" in result["error"]["message"]

    @patch("orcaops.mcp_server._key_manager_mcp")
    def test_revoke_api_key(self, mock_km):
        from orcaops.mcp_server import orcaops_revoke_api_key
        mock_km.return_value.revoke_key.return_value = True
        result = json.loads(orcaops_revoke_api_key("ws_test", "key_abc"))
        assert result["success"] is True
        assert result["revoked"] is True

    @patch("orcaops.mcp_server._key_manager_mcp")
    def test_revoke_not_found(self, mock_km):
        from orcaops.mcp_server import orcaops_revoke_api_key
        mock_km.return_value.revoke_key.return_value = False
        result = json.loads(orcaops_revoke_api_key("ws_test", "key_none"))
        assert result["success"] is False


class TestAuditTools:
    @patch("orcaops.mcp_server._audit_store")
    def test_query_audit(self, mock_as):
        from orcaops.mcp_server import orcaops_query_audit
        event = AuditEvent(
            event_id="evt_test",
            workspace_id="ws_test",
            actor_type="api_key",
            actor_id="key_abc",
            action=AuditAction.JOB_CREATED,
            resource_type="job",
            resource_id="job-1",
            outcome=AuditOutcome.SUCCESS,
        )
        mock_as.return_value.query.return_value = ([event], 1)
        result = json.loads(orcaops_query_audit())
        assert result["success"] is True
        assert result["total"] == 1
        assert result["events"][0]["action"] == "job.created"

    @patch("orcaops.mcp_server._audit_store")
    def test_query_audit_empty(self, mock_as):
        from orcaops.mcp_server import orcaops_query_audit
        mock_as.return_value.query.return_value = ([], 0)
        result = json.loads(orcaops_query_audit())
        assert result["success"] is True
        assert result["total"] == 0


class TestSessionTools:
    @patch("orcaops.mcp_server._session_manager")
    def test_create_session(self, mock_sm):
        from orcaops.mcp_server import orcaops_create_session
        session = AgentSession(
            session_id="sess_abc",
            agent_type="claude-code",
            workspace_id="ws_test",
        )
        mock_sm.return_value.create_session.return_value = session
        result = json.loads(orcaops_create_session("claude-code"))
        assert result["success"] is True
        assert result["session_id"] == "sess_abc"

    @patch("orcaops.mcp_server._session_manager")
    def test_get_session(self, mock_sm):
        from orcaops.mcp_server import orcaops_get_session
        session = AgentSession(
            session_id="sess_abc",
            agent_type="claude-code",
            workspace_id="ws_test",
        )
        mock_sm.return_value.get_session.return_value = session
        result = json.loads(orcaops_get_session("sess_abc"))
        assert result["success"] is True
        assert result["agent_type"] == "claude-code"

    @patch("orcaops.mcp_server._session_manager")
    def test_get_session_not_found(self, mock_sm):
        from orcaops.mcp_server import orcaops_get_session
        mock_sm.return_value.get_session.return_value = None
        result = json.loads(orcaops_get_session("sess_none"))
        assert result["success"] is False

    @patch("orcaops.mcp_server._session_manager")
    def test_list_sessions(self, mock_sm):
        from orcaops.mcp_server import orcaops_list_sessions
        session = AgentSession(
            session_id="sess_abc",
            agent_type="claude-code",
            workspace_id="ws_test",
        )
        mock_sm.return_value.list_sessions.return_value = [session]
        result = json.loads(orcaops_list_sessions())
        assert result["success"] is True
        assert result["count"] == 1

    @patch("orcaops.mcp_server._session_manager")
    def test_end_session(self, mock_sm):
        from orcaops.mcp_server import orcaops_end_session
        session = AgentSession(
            session_id="sess_abc",
            agent_type="claude-code",
            workspace_id="ws_test",
            status=SessionStatus.EXPIRED,
        )
        mock_sm.return_value.end_session.return_value = session
        result = json.loads(orcaops_end_session("sess_abc"))
        assert result["success"] is True
        assert result["status"] == "expired"

    @patch("orcaops.mcp_server._session_manager")
    def test_end_session_not_found(self, mock_sm):
        from orcaops.mcp_server import orcaops_end_session
        mock_sm.return_value.end_session.return_value = None
        result = json.loads(orcaops_end_session("sess_none"))
        assert result["success"] is False
