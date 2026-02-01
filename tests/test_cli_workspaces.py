"""Tests for workspace CLI commands."""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from orcaops.schemas import (
    Workspace,
    WorkspaceStatus,
    OwnerType,
    WorkspaceSettings,
    ResourceLimits,
    APIKey,
    AuditEvent,
    AuditAction,
    AuditOutcome,
    AgentSession,
    SessionStatus,
)

runner = CliRunner()


@pytest.fixture
def app():
    """Create a fresh Typer app with workspace commands."""
    import typer
    test_app = typer.Typer()
    from orcaops.cli_workspaces import WorkspaceCLI
    WorkspaceCLI.add_commands(test_app)
    return test_app


def _make_workspace(id="ws_test", name="test"):
    return Workspace(
        id=id,
        name=name,
        owner_type=OwnerType.USER,
        owner_id="user1",
    )


class TestWorkspaceCreate:
    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_create_success(self, mock_wr, app):
        mock_wr.return_value.create_workspace.return_value = _make_workspace()
        result = runner.invoke(app, ["workspace", "create", "test"])
        assert result.exit_code == 0
        assert "Workspace created" in result.output

    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_create_duplicate(self, mock_wr, app):
        mock_wr.return_value.create_workspace.side_effect = ValueError("duplicate")
        result = runner.invoke(app, ["workspace", "create", "test"])
        assert result.exit_code == 1
        assert "duplicate" in result.output

    def test_create_invalid_owner_type(self, app):
        result = runner.invoke(app, ["workspace", "create", "test", "--owner-type", "invalid"])
        assert result.exit_code == 1
        assert "Invalid owner type" in result.output


class TestWorkspaceList:
    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_list_workspaces(self, mock_wr, app):
        mock_wr.return_value.list_workspaces.return_value = [_make_workspace()]
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0
        assert "ws_test" in result.output

    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_list_empty(self, mock_wr, app):
        mock_wr.return_value.list_workspaces.return_value = []
        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0
        assert "No workspaces" in result.output


class TestWorkspaceStatus:
    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_show_status(self, mock_wr, app):
        mock_wr.return_value.get_workspace.return_value = _make_workspace()
        result = runner.invoke(app, ["workspace", "status", "ws_test"])
        assert result.exit_code == 0
        assert "ws_test" in result.output
        assert "Max concurrent jobs" in result.output

    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_not_found(self, mock_wr, app):
        mock_wr.return_value.get_workspace.return_value = None
        result = runner.invoke(app, ["workspace", "status", "ws_none"])
        assert result.exit_code == 1


class TestKeysCommands:
    @patch("orcaops.cli_workspaces._key_manager")
    @patch("orcaops.cli_workspaces._workspace_registry")
    def test_create_key(self, mock_wr, mock_km, app):
        mock_wr.return_value.get_workspace.return_value = _make_workspace()
        mock_key = APIKey(
            key_id="key_abc123",
            key_hash="hash",
            name="test",
            workspace_id="ws_test",
            permissions=[],
        )
        mock_km.return_value.generate_key.return_value = ("orcaops_ws_test_secret123", mock_key)
        result = runner.invoke(app, ["workspace", "keys", "create", "ws_test"])
        assert result.exit_code == 0
        assert "API Key Created" in result.output

    @patch("orcaops.cli_workspaces._key_manager")
    def test_list_keys(self, mock_km, app):
        mock_key = APIKey(
            key_id="key_abc",
            key_hash="hash",
            name="test",
            workspace_id="ws_test",
            permissions=[],
        )
        mock_km.return_value.list_keys.return_value = [mock_key]
        result = runner.invoke(app, ["workspace", "keys", "list", "ws_test"])
        assert result.exit_code == 0
        assert "key_abc" in result.output

    @patch("orcaops.cli_workspaces._key_manager")
    def test_revoke_key(self, mock_km, app):
        mock_km.return_value.revoke_key.return_value = True
        result = runner.invoke(app, ["workspace", "keys", "revoke", "ws_test", "key_abc"])
        assert result.exit_code == 0
        assert "revoked" in result.output


class TestAuditCommand:
    @patch("orcaops.cli_workspaces._audit_store")
    def test_query_audit(self, mock_as, app):
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
        result = runner.invoke(app, ["workspace", "audit"])
        assert result.exit_code == 0
        assert "job.created" in result.output

    @patch("orcaops.cli_workspaces._audit_store")
    def test_empty_audit(self, mock_as, app):
        mock_as.return_value.query.return_value = ([], 0)
        result = runner.invoke(app, ["workspace", "audit"])
        assert result.exit_code == 0
        assert "No audit events" in result.output


class TestSessionsCommand:
    @patch("orcaops.cli_workspaces._session_manager")
    def test_list_sessions(self, mock_sm, app):
        session = AgentSession(
            session_id="sess_abc123",
            agent_type="claude-code",
            workspace_id="ws_test",
        )
        mock_sm.return_value.list_sessions.return_value = [session]
        result = runner.invoke(app, ["workspace", "sessions"])
        assert result.exit_code == 0
        assert "sess_abc123" in result.output
        assert "claude-code" in result.output
