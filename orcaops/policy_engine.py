"""Security policy engine — validates images, commands, and generates container security options."""

import re
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional

from orcaops.schemas import (
    CommandPolicy,
    ImagePolicy,
    JobSpec,
    PolicyResult,
    SecurityPolicy,
    WorkspaceSettings,
)


class PolicyEngine:
    """Validates jobs against security policies."""

    def __init__(
        self,
        policy: Optional[SecurityPolicy] = None,
        workspace_settings: Optional[WorkspaceSettings] = None,
    ):
        self.policy = policy or SecurityPolicy()
        self.workspace_settings = workspace_settings

    def validate_job(self, spec: JobSpec) -> PolicyResult:
        """Validate an entire job spec against all policies."""
        violations: List[str] = []

        # Image check
        img_result = self.validate_image(spec.sandbox.image)
        violations.extend(img_result.violations)

        # Command checks
        for cmd in spec.commands:
            cmd_result = self.validate_command(cmd.command)
            violations.extend(cmd_result.violations)

        return PolicyResult(
            allowed=len(violations) == 0,
            violations=violations,
            policy_name="job_validation",
        )

    def validate_image(self, image: str) -> PolicyResult:
        """Check image against allow/block lists using fnmatch glob patterns."""
        violations: List[str] = []
        ip = self.policy.image_policy

        # Merge workspace settings if present
        allowed = list(ip.allowed_images)
        blocked = list(ip.blocked_images)
        if self.workspace_settings:
            allowed.extend(self.workspace_settings.allowed_images)
            blocked.extend(self.workspace_settings.blocked_images)

        # Blocked list takes priority
        for pattern in blocked:
            if fnmatch(image, pattern):
                violations.append(f"Image '{image}' is blocked by pattern '{pattern}'")

        # If allowed list is non-empty, image must match at least one pattern
        if allowed and not any(fnmatch(image, p) for p in allowed):
            violations.append(
                f"Image '{image}' not in allowed list: {allowed}"
            )

        # Digest requirement
        if ip.require_digest and "@sha256:" not in image:
            violations.append(
                f"Image '{image}' must specify a digest (image@sha256:...)"
            )

        return PolicyResult(
            allowed=len(violations) == 0,
            violations=violations,
            policy_name="image_policy",
        )

    def validate_command(self, command: str) -> PolicyResult:
        """Check command against blocked commands and regex patterns."""
        violations: List[str] = []
        cp = self.policy.command_policy

        # Exact match (full command comparison)
        for blocked in cp.blocked_commands:
            if command.strip() == blocked.strip():
                violations.append(
                    f"Command matches blocked command: '{blocked}'"
                )

        # Regex patterns
        for pattern in cp.blocked_patterns:
            try:
                if re.search(pattern, command):
                    violations.append(
                        f"Command matches blocked pattern: '{pattern}'"
                    )
            except re.error:
                pass  # Skip invalid regex patterns

        return PolicyResult(
            allowed=len(violations) == 0,
            violations=violations,
            policy_name="command_policy",
        )

    def get_container_security_opts(self) -> Dict[str, Any]:
        """Return Docker security options from the policy."""
        return dict(self.policy.container_security)
