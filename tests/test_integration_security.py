"""Integration tests for security pipeline: policy + quota + audit in job submission."""

from unittest.mock import MagicMock, patch

import pytest

from orcaops.schemas import (
    CommandPolicy,
    ImagePolicy,
    JobCommand,
    JobSpec,
    ResourceLimits,
    SandboxSpec,
    SecurityPolicy,
    Workspace,
    WorkspaceSettings,
    WorkspaceStatus,
    OwnerType,
)
from orcaops.audit import AuditLogger
from orcaops.policy_engine import PolicyEngine
from orcaops.quota_tracker import QuotaTracker
from orcaops.workspace import WorkspaceRegistry


def _make_spec(job_id="test-job", image="python:3.11", commands=None, workspace_id=None):
    cmds = commands or ["echo hello"]
    return JobSpec(
        job_id=job_id,
        sandbox=SandboxSpec(image=image),
        commands=[JobCommand(command=c) for c in cmds],
        workspace_id=workspace_id,
    )


class TestPolicyEnforcementInJobManager:
    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_blocked_image_rejects_job(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        policy = SecurityPolicy(
            image_policy=ImagePolicy(blocked_images=["python:*"]),
        )
        jm = JobManager(
            output_dir=str(tmp_path),
            policy_engine=policy,
        )

        with pytest.raises(ValueError, match="Policy violation"):
            jm.submit_job(_make_spec(image="python:3.11"))

    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_blocked_command_rejects_job(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        policy = SecurityPolicy(
            command_policy=CommandPolicy(blocked_commands=["rm -rf /"]),
        )
        jm = JobManager(
            output_dir=str(tmp_path),
            policy_engine=policy,
        )

        with pytest.raises(ValueError, match="Policy violation"):
            jm.submit_job(_make_spec(commands=["rm -rf /"]))

    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_valid_job_accepted(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        policy = SecurityPolicy(
            image_policy=ImagePolicy(allowed_images=["python:*"]),
        )
        mock_runner = mock_runner_cls.return_value
        mock_runner.run_sandbox_job.return_value = MagicMock(
            status="success", steps=[], artifacts=[], cleanup_status=None
        )

        jm = JobManager(
            output_dir=str(tmp_path),
            policy_engine=policy,
        )

        record = jm.submit_job(_make_spec(image="python:3.11"))
        assert record.job_id == "test-job"


class TestQuotaEnforcementInJobManager:
    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_quota_exceeded_rejects_job(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        ws_registry = MagicMock(spec=WorkspaceRegistry)
        ws = Workspace(
            id="ws_test",
            name="test",
            owner_type=OwnerType.USER,
            owner_id="user1",
            limits=ResourceLimits(max_concurrent_jobs=1),
        )
        ws_registry.get_workspace.return_value = ws

        qt = QuotaTracker()
        qt.on_job_start("ws_test", "existing-job")

        jm = JobManager(
            output_dir=str(tmp_path),
            quota_tracker=qt,
            workspace_registry=ws_registry,
        )

        with pytest.raises(ValueError, match="Quota exceeded"):
            jm.submit_job(_make_spec(workspace_id="ws_test"))

    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_no_quota_check_without_workspace_id(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        qt = QuotaTracker()
        # Even though tracker has running jobs, no workspace_id means no check
        qt.on_job_start("ws_test", "existing-job")

        mock_runner = mock_runner_cls.return_value
        mock_runner.run_sandbox_job.return_value = MagicMock(
            status="success", steps=[], artifacts=[], cleanup_status=None
        )

        jm = JobManager(
            output_dir=str(tmp_path),
            quota_tracker=qt,
        )
        record = jm.submit_job(_make_spec())  # no workspace_id
        assert record.job_id == "test-job"


class TestPolicyAuditLogging:
    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_policy_violation_audited(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        audit_dir = str(tmp_path / "audit")
        audit_logger = AuditLogger(audit_dir)

        policy = SecurityPolicy(
            image_policy=ImagePolicy(blocked_images=["bad:*"]),
        )
        jm = JobManager(
            output_dir=str(tmp_path / "artifacts"),
            policy_engine=policy,
            audit_logger=audit_logger,
        )

        with pytest.raises(ValueError, match="Policy violation"):
            jm.submit_job(_make_spec(image="bad:latest", workspace_id="ws_test"))

        # Verify audit event was written
        from orcaops.audit import AuditStore
        store = AuditStore(audit_dir)
        events, total = store.query()
        assert total == 1
        assert events[0].action.value == "policy.violation"
        assert events[0].outcome.value == "denied"


class TestSecurityOptsInjection:
    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_security_opts_added_to_metadata(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        policy = SecurityPolicy()  # defaults: cap_drop=ALL, no-new-privileges
        mock_runner = mock_runner_cls.return_value
        mock_runner.run_sandbox_job.return_value = MagicMock(
            status="success", steps=[], artifacts=[], cleanup_status=None
        )

        jm = JobManager(
            output_dir=str(tmp_path),
            policy_engine=policy,
        )

        spec = _make_spec()
        jm.submit_job(spec)

        # The spec should have _security_opts injected
        assert "_security_opts" in spec.metadata
        opts = spec.metadata["_security_opts"]
        assert opts["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in opts["security_opt"]


class TestWorkspaceSettingsMerge:
    @patch("orcaops.job_manager.DockerManager")
    @patch("orcaops.job_manager.JobRunner")
    def test_workspace_blocked_images_enforced(self, mock_runner_cls, mock_dm_cls, tmp_path):
        from orcaops.job_manager import JobManager

        ws_registry = MagicMock(spec=WorkspaceRegistry)
        ws = Workspace(
            id="ws_test",
            name="test",
            owner_type=OwnerType.USER,
            owner_id="user1",
            settings=WorkspaceSettings(blocked_images=["evil:*"]),
        )
        ws_registry.get_workspace.return_value = ws

        policy = SecurityPolicy()  # empty policy, workspace blocks
        jm = JobManager(
            output_dir=str(tmp_path),
            policy_engine=policy,
            workspace_registry=ws_registry,
        )

        with pytest.raises(ValueError, match="Policy violation"):
            jm.submit_job(_make_spec(image="evil:latest", workspace_id="ws_test"))
