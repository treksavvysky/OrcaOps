"""Tests for API key management and permission system."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from orcaops.schemas import APIKey, Permission
from orcaops.auth import KeyManager, ROLE_TEMPLATES, has_permission


class TestPermissions:
    def test_has_direct_permission(self):
        perms = [Permission.JOB_READ, Permission.JOB_CREATE]
        assert has_permission(perms, Permission.JOB_READ) is True
        assert has_permission(perms, Permission.JOB_CREATE) is True

    def test_missing_permission(self):
        perms = [Permission.JOB_READ]
        assert has_permission(perms, Permission.JOB_CREATE) is False

    def test_workspace_admin_implies_all(self):
        perms = [Permission.WORKSPACE_ADMIN]
        assert has_permission(perms, Permission.JOB_CREATE) is True
        assert has_permission(perms, Permission.AUDIT_READ) is True
        assert has_permission(perms, Permission.POLICY_ADMIN) is True

    def test_empty_permissions(self):
        assert has_permission([], Permission.JOB_READ) is False


class TestRoleTemplates:
    def test_admin_has_all(self):
        assert set(ROLE_TEMPLATES["admin"]) == set(Permission)

    def test_viewer_read_only(self):
        for p in ROLE_TEMPLATES["viewer"]:
            assert "read" in p.value

    def test_ci_has_create_and_read(self):
        ci = ROLE_TEMPLATES["ci"]
        assert Permission.JOB_CREATE in ci
        assert Permission.JOB_READ in ci
        assert Permission.WORKFLOW_CREATE in ci
        assert Permission.JOB_CANCEL not in ci

    def test_developer_no_admin(self):
        dev = ROLE_TEMPLATES["developer"]
        assert Permission.WORKSPACE_ADMIN not in dev
        assert Permission.POLICY_ADMIN not in dev
        assert Permission.AUDIT_READ not in dev


class TestKeyManager:
    def test_generate_key_format(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key("ws_test", "my-key", role="admin")
        assert plain.startswith("orcaops_ws_test_")
        assert api_key.key_id.startswith("key_")
        assert api_key.workspace_id == "ws_test"
        assert api_key.name == "my-key"
        assert api_key.revoked is False

    def test_generate_key_with_permissions(self, tmp_path):
        km = KeyManager(str(tmp_path))
        perms = [Permission.JOB_READ, Permission.JOB_CREATE]
        plain, api_key = km.generate_key("ws_test", "custom", permissions=perms)
        assert set(api_key.permissions) == set(perms)

    def test_generate_key_default_role(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key("ws_test", "default-perms")
        # Default is viewer when no role or permissions given
        assert set(api_key.permissions) == set(ROLE_TEMPLATES["viewer"])

    def test_generate_key_with_expiry(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key(
            "ws_test", "expiring", role="ci", expires_in_days=30,
        )
        assert api_key.expires_at is not None
        # Should expire in ~30 days
        delta = api_key.expires_at - datetime.now(timezone.utc)
        assert 28 < delta.total_seconds() / 86400 <= 30

    def test_validate_key_valid(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key("ws_test", "test-key", role="admin")

        result = km.validate_key(plain)
        assert result is not None
        validated, ws_id = result
        assert validated.key_id == api_key.key_id
        assert ws_id == "ws_test"

    def test_validate_key_wrong_key(self, tmp_path):
        km = KeyManager(str(tmp_path))
        km.generate_key("ws_test", "real-key", role="admin")
        assert km.validate_key("orcaops_ws_test_wrongwrongwrongwrong") is None

    def test_validate_key_bad_format(self, tmp_path):
        km = KeyManager(str(tmp_path))
        assert km.validate_key("not_a_valid_key") is None
        assert km.validate_key("") is None

    def test_validate_key_revoked(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key("ws_test", "to-revoke", role="admin")
        km.revoke_key("ws_test", api_key.key_id)
        assert km.validate_key(plain) is None

    def test_validate_key_expired(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key(
            "ws_test", "expired", role="admin", expires_in_days=1,
        )
        # Manually set expiry to the past
        key_path = os.path.join(
            str(tmp_path), "ws_test", "keys", f"{api_key.key_id}.json",
        )
        import json

        with open(key_path) as f:
            data = json.load(f)
        data["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with open(key_path, "w") as f:
            json.dump(data, f)

        assert km.validate_key(plain) is None

    def test_validate_key_updates_last_used(self, tmp_path):
        km = KeyManager(str(tmp_path))
        plain, api_key = km.generate_key("ws_test", "track-usage", role="admin")
        assert api_key.last_used is None

        result = km.validate_key(plain)
        assert result is not None
        validated, _ = result
        assert validated.last_used is not None

    def test_revoke_key(self, tmp_path):
        km = KeyManager(str(tmp_path))
        _, api_key = km.generate_key("ws_test", "revokable", role="admin")
        assert km.revoke_key("ws_test", api_key.key_id) is True

        # Key should not appear in list
        keys = km.list_keys("ws_test")
        assert all(k.key_id != api_key.key_id for k in keys)

    def test_revoke_key_not_found(self, tmp_path):
        km = KeyManager(str(tmp_path))
        assert km.revoke_key("ws_test", "key_nonexistent") is False

    def test_list_keys(self, tmp_path):
        km = KeyManager(str(tmp_path))
        km.generate_key("ws_test", "key1", role="admin")
        km.generate_key("ws_test", "key2", role="viewer")
        keys = km.list_keys("ws_test")
        assert len(keys) == 2
        # Hashes should be redacted
        for k in keys:
            assert k.key_hash == "***"

    def test_list_keys_empty(self, tmp_path):
        km = KeyManager(str(tmp_path))
        assert km.list_keys("ws_empty") == []

    def test_rotate_key(self, tmp_path):
        km = KeyManager(str(tmp_path))
        old_plain, old_key = km.generate_key("ws_test", "rotate-me", role="developer")

        result = km.rotate_key("ws_test", old_key.key_id)
        assert result is not None
        new_plain, new_key = result

        # Old key should be invalid
        assert km.validate_key(old_plain) is None
        # New key should work
        assert km.validate_key(new_plain) is not None
        # Same permissions
        assert set(new_key.permissions) == set(old_key.permissions)

    def test_rotate_key_not_found(self, tmp_path):
        km = KeyManager(str(tmp_path))
        assert km.rotate_key("ws_test", "key_nope") is None

    def test_has_keys(self, tmp_path):
        km = KeyManager(str(tmp_path))
        assert km.has_keys("ws_test") is False
        km.generate_key("ws_test", "first", role="admin")
        assert km.has_keys("ws_test") is True

    def test_persistence_across_instances(self, tmp_path):
        km1 = KeyManager(str(tmp_path))
        plain, api_key = km1.generate_key("ws_test", "persist", role="admin")

        # New instance should still validate
        km2 = KeyManager(str(tmp_path))
        result = km2.validate_key(plain)
        assert result is not None
        assert result[0].key_id == api_key.key_id
