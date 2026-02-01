"""Tests for workspace model and registry."""

import json
import os
from datetime import datetime, timezone

import pytest

from orcaops.schemas import (
    Workspace,
    WorkspaceSettings,
    WorkspaceStatus,
    OwnerType,
    ResourceLimits,
    WorkspaceUsage,
)
from orcaops.workspace import WorkspaceRegistry


class TestWorkspaceModels:
    def test_workspace_valid(self):
        ws = Workspace(
            id="ws_abc123",
            name="my-workspace",
            owner_type=OwnerType.USER,
            owner_id="user1",
        )
        assert ws.id == "ws_abc123"
        assert ws.status == WorkspaceStatus.ACTIVE
        assert ws.settings.retention_days == 30
        assert ws.limits.max_concurrent_jobs == 10

    def test_workspace_id_validation_bad_prefix(self):
        with pytest.raises(ValueError, match="workspace id must start with"):
            Workspace(
                id="bad_id",
                name="test",
                owner_type=OwnerType.USER,
                owner_id="u1",
            )

    def test_workspace_id_validation_special_chars(self):
        with pytest.raises(ValueError):
            Workspace(
                id="ws_ab-cd",
                name="test",
                owner_type=OwnerType.USER,
                owner_id="u1",
            )

    def test_workspace_name_validation(self):
        with pytest.raises(ValueError, match="name must be alphanumeric"):
            Workspace(
                id="ws_abc",
                name="bad name!",
                owner_type=OwnerType.USER,
                owner_id="u1",
            )

    def test_workspace_name_too_long(self):
        with pytest.raises(ValueError, match="name too long"):
            Workspace(
                id="ws_abc",
                name="x" * 65,
                owner_type=OwnerType.USER,
                owner_id="u1",
            )

    def test_resource_limits_defaults(self):
        limits = ResourceLimits()
        assert limits.max_concurrent_jobs == 10
        assert limits.max_memory_per_job_mb == 8192
        assert limits.daily_job_limit is None

    def test_workspace_settings_defaults(self):
        settings = WorkspaceSettings()
        assert settings.default_cleanup_policy == "remove_on_completion"
        assert settings.allowed_images == []
        assert settings.max_job_timeout == 3600

    def test_workspace_usage(self):
        usage = WorkspaceUsage(workspace_id="ws_abc")
        assert usage.current_running_jobs == 0
        assert usage.jobs_today == 0

    def test_owner_type_values(self):
        assert OwnerType.USER == "user"
        assert OwnerType.TEAM == "team"
        assert OwnerType.AI_AGENT == "ai-agent"


class TestWorkspaceRegistry:
    def test_create_workspace(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        ws = reg.create_workspace(
            name="test-ws",
            owner_type=OwnerType.USER,
            owner_id="user1",
        )
        assert ws.id.startswith("ws_")
        assert ws.name == "test-ws"
        assert ws.status == WorkspaceStatus.ACTIVE

    def test_create_with_custom_id(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        ws = reg.create_workspace(
            name="custom",
            owner_type=OwnerType.TEAM,
            owner_id="team1",
            workspace_id="ws_custom123",
        )
        assert ws.id == "ws_custom123"

    def test_create_duplicate_id_raises(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="first",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_dup",
        )
        with pytest.raises(ValueError, match="already exists"):
            reg.create_workspace(
                name="second",
                owner_type=OwnerType.USER,
                owner_id="u1",
                workspace_id="ws_dup",
            )

    def test_create_duplicate_name_raises(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="samename",
            owner_type=OwnerType.USER,
            owner_id="u1",
        )
        with pytest.raises(ValueError, match="already in use"):
            reg.create_workspace(
                name="samename",
                owner_type=OwnerType.USER,
                owner_id="u2",
            )

    def test_get_workspace(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        created = reg.create_workspace(
            name="get-me",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_getme",
        )
        fetched = reg.get_workspace("ws_getme")
        assert fetched is not None
        assert fetched.id == "ws_getme"
        assert fetched.name == "get-me"

    def test_get_workspace_not_found(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        assert reg.get_workspace("ws_nonexistent") is None

    def test_list_workspaces(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(name="ws1", owner_type=OwnerType.USER, owner_id="u1")
        reg.create_workspace(name="ws2", owner_type=OwnerType.TEAM, owner_id="t1")
        result = reg.list_workspaces()
        assert len(result) == 2

    def test_list_workspaces_filter_status(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="active1",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_active1",
        )
        reg.create_workspace(
            name="archived1",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_archived1",
        )
        reg.archive_workspace("ws_archived1")

        active = reg.list_workspaces(status=WorkspaceStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].name == "active1"

    def test_update_workspace(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="update-me",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_update",
        )
        new_settings = WorkspaceSettings(retention_days=7, max_job_timeout=600)
        updated = reg.update_workspace("ws_update", settings=new_settings)
        assert updated.settings.retention_days == 7
        assert updated.settings.max_job_timeout == 600

    def test_update_workspace_not_found(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            reg.update_workspace("ws_missing")

    def test_archive_workspace(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="to-archive",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_archive",
        )
        assert reg.archive_workspace("ws_archive") is True
        ws = reg.get_workspace("ws_archive")
        assert ws.status == WorkspaceStatus.ARCHIVED

    def test_archive_not_found(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        assert reg.archive_workspace("ws_missing") is False

    def test_persistence_to_disk(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="persist",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_persist",
        )

        # Verify file on disk
        ws_path = os.path.join(str(tmp_path), "ws_persist", "workspace.json")
        assert os.path.isfile(ws_path)
        with open(ws_path) as f:
            data = json.load(f)
        assert data["id"] == "ws_persist"
        assert data["name"] == "persist"

    def test_load_from_disk_on_new_registry(self, tmp_path):
        # Create workspace with first registry
        reg1 = WorkspaceRegistry(str(tmp_path))
        reg1.create_workspace(
            name="disk-load",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_diskload",
        )

        # New registry loads from disk
        reg2 = WorkspaceRegistry(str(tmp_path))
        ws = reg2.get_workspace("ws_diskload")
        assert ws is not None
        assert ws.name == "disk-load"

    def test_default_workspace(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        ws = reg.get_default_workspace()
        assert ws.id == "ws_default"
        assert ws.name == "default"
        assert ws.owner_type == OwnerType.USER

        # Second call returns the same workspace
        ws2 = reg.get_default_workspace()
        assert ws2.id == ws.id

    def test_create_with_custom_settings_and_limits(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        settings = WorkspaceSettings(
            allowed_images=["python:*", "node:*"],
            blocked_images=["*:latest"],
            retention_days=7,
        )
        limits = ResourceLimits(
            max_concurrent_jobs=5,
            daily_job_limit=100,
        )
        ws = reg.create_workspace(
            name="custom-config",
            owner_type=OwnerType.AI_AGENT,
            owner_id="claude-session-1",
            settings=settings,
            limits=limits,
        )
        assert ws.settings.allowed_images == ["python:*", "node:*"]
        assert ws.limits.max_concurrent_jobs == 5
        assert ws.limits.daily_job_limit == 100

    def test_archived_name_can_be_reused(self, tmp_path):
        reg = WorkspaceRegistry(str(tmp_path))
        reg.create_workspace(
            name="reuse-name",
            owner_type=OwnerType.USER,
            owner_id="u1",
            workspace_id="ws_old",
        )
        reg.archive_workspace("ws_old")

        # Should not raise — archived name can be reused
        ws = reg.create_workspace(
            name="reuse-name",
            owner_type=OwnerType.USER,
            owner_id="u2",
        )
        assert ws.name == "reuse-name"
