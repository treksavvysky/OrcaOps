"""Tests for workspace and API key management endpoints."""

import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from orcaops.schemas import (
    Workspace,
    WorkspaceStatus,
    WorkspaceSettings,
    OwnerType,
    ResourceLimits,
    APIKey,
    Permission,
)


def _ws(workspace_id="ws_test1", name="test-ws", status=WorkspaceStatus.ACTIVE):
    return Workspace(
        id=workspace_id,
        name=name,
        owner_type=OwnerType.USER,
        owner_id="user1",
        status=status,
    )


@pytest.fixture
def client():
    with patch("orcaops.api.docker_manager"), \
         patch("orcaops.api.job_manager") as mock_jm, \
         patch("orcaops.api.run_store") as mock_rs, \
         patch("orcaops.api.workflow_manager") as mock_wm, \
         patch("orcaops.api.workflow_store") as mock_ws, \
         patch("orcaops.api.workspace_registry") as mock_wr, \
         patch("orcaops.api.key_manager") as mock_km:

        mock_jm.output_dir = tempfile.mkdtemp()
        mock_rs.list_runs.return_value = ([], 0)
        mock_ws.list_workflows.return_value = ([], 0)

        from main import app
        yield TestClient(app), mock_wr, mock_km


class TestCreateWorkspace:
    def test_create_valid(self, client):
        tc, mock_wr, _ = client
        mock_wr.create_workspace.return_value = _ws()

        resp = tc.post("/orcaops/workspaces", json={
            "name": "test-ws",
            "owner_type": "user",
            "owner_id": "user1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace"]["id"] == "ws_test1"
        assert data["message"] == "Workspace created."

    def test_create_conflict(self, client):
        tc, mock_wr, _ = client
        mock_wr.create_workspace.side_effect = ValueError("already exists")

        resp = tc.post("/orcaops/workspaces", json={
            "name": "dup",
            "owner_type": "user",
            "owner_id": "u1",
        })
        assert resp.status_code == 409


class TestListWorkspaces:
    def test_list_all(self, client):
        tc, mock_wr, _ = client
        mock_wr.list_workspaces.return_value = [_ws("ws_a", "a"), _ws("ws_b", "b")]

        resp = tc.get("/orcaops/workspaces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_list_with_status_filter(self, client):
        tc, mock_wr, _ = client
        mock_wr.list_workspaces.return_value = [_ws(status=WorkspaceStatus.ACTIVE)]

        resp = tc.get("/orcaops/workspaces?status=active")
        assert resp.status_code == 200


class TestGetWorkspace:
    def test_found(self, client):
        tc, mock_wr, _ = client
        mock_wr.get_workspace.return_value = _ws()

        resp = tc.get("/orcaops/workspaces/ws_test1")
        assert resp.status_code == 200
        assert resp.json()["workspace"]["id"] == "ws_test1"

    def test_not_found(self, client):
        tc, mock_wr, _ = client
        mock_wr.get_workspace.return_value = None

        resp = tc.get("/orcaops/workspaces/ws_missing")
        assert resp.status_code == 404


class TestUpdateWorkspace:
    def test_update_settings(self, client):
        tc, mock_wr, _ = client
        updated = _ws()
        updated.settings = WorkspaceSettings(retention_days=7)
        mock_wr.update_workspace.return_value = updated

        resp = tc.patch("/orcaops/workspaces/ws_test1", json={
            "settings": {"retention_days": 7},
        })
        assert resp.status_code == 200

    def test_update_not_found(self, client):
        tc, mock_wr, _ = client
        mock_wr.update_workspace.side_effect = ValueError("not found")

        resp = tc.patch("/orcaops/workspaces/ws_missing", json={})
        assert resp.status_code == 404


class TestArchiveWorkspace:
    def test_archive_success(self, client):
        tc, mock_wr, _ = client
        mock_wr.archive_workspace.return_value = True

        resp = tc.delete("/orcaops/workspaces/ws_test1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

    def test_archive_not_found(self, client):
        tc, mock_wr, _ = client
        mock_wr.archive_workspace.return_value = False

        resp = tc.delete("/orcaops/workspaces/ws_missing")
        assert resp.status_code == 404


class TestCreateAPIKey:
    def test_create_key(self, client):
        tc, mock_wr, mock_km = client
        mock_wr.get_workspace.return_value = _ws()
        mock_km.generate_key.return_value = (
            "orcaops_ws_test1_abc123",
            APIKey(
                key_id="key_abc",
                key_hash="$2b$...",
                name="test-key",
                workspace_id="ws_test1",
                permissions=[Permission.JOB_READ],
            ),
        )

        resp = tc.post("/orcaops/workspaces/ws_test1/keys", json={
            "name": "test-key",
            "role": "viewer",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["plain_key"] == "orcaops_ws_test1_abc123"
        assert data["key_id"] == "key_abc"

    def test_create_key_workspace_not_found(self, client):
        tc, mock_wr, _ = client
        mock_wr.get_workspace.return_value = None

        resp = tc.post("/orcaops/workspaces/ws_missing/keys", json={
            "name": "key",
            "role": "admin",
        })
        assert resp.status_code == 404


class TestListAPIKeys:
    def test_list_keys(self, client):
        tc, mock_wr, mock_km = client
        mock_wr.get_workspace.return_value = _ws()
        mock_km.list_keys.return_value = [
            APIKey(
                key_id="key_a",
                key_hash="***",
                name="key-a",
                workspace_id="ws_test1",
                permissions=[Permission.JOB_READ],
            ),
        ]

        resp = tc.get("/orcaops/workspaces/ws_test1/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1


class TestRevokeAPIKey:
    def test_revoke_success(self, client):
        tc, _, mock_km = client
        mock_km.revoke_key.return_value = True

        resp = tc.delete("/orcaops/workspaces/ws_test1/keys/key_abc")
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

    def test_revoke_not_found(self, client):
        tc, _, mock_km = client
        mock_km.revoke_key.return_value = False

        resp = tc.delete("/orcaops/workspaces/ws_test1/keys/key_missing")
        assert resp.status_code == 404
