"""Execution core: one gate through which every docker command passes."""

import datetime as dt
import json
import os
import shlex
import subprocess
from pathlib import Path

AUDIT_LOG = Path(os.environ.get("ORCA_AUDIT_LOG", "~/.orcaops/audit.jsonl")).expanduser()

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
# Compose's own default override discovery order. Passing `-f` disables that
# discovery, so orca has to find the override itself.
OVERRIDE_FILES = ("compose.override.yml", "compose.override.yaml",
                  "docker-compose.override.yml", "docker-compose.override.yaml")


class OrcaError(RuntimeError):
    """A failure orca can explain to the user; printed without a traceback."""


def docker(*args, mutating=False, dry_run=False, reason=None, capture=False, audit_extra=None):
    """Run a docker command.

    Mutating commands are appended to the audit log with their exit code and
    the operator-supplied reason, plus any `audit_extra` fields. A dry run
    prints the exact command and runs nothing.
    """
    cmd = ["docker", *args]
    if dry_run:
        print(f"[dry-run] {shlex.join(cmd)}")
        return None
    try:
        proc = subprocess.run(cmd, text=True, capture_output=capture)
    except FileNotFoundError:
        raise OrcaError("docker binary not found on PATH") from None
    if mutating:
        _audit(cmd, proc.returncode, reason, audit_extra)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() if capture else f"exit code {proc.returncode}"
        raise OrcaError(f"`{shlex.join(cmd)}` failed: {detail}")
    return proc


def _audit(cmd, exit_code, reason, extra=None):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "cmd": shlex.join(cmd),
        "exit": exit_code,
        "reason": reason,
        **(extra or {}),
    }
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def compose_file(project: Path) -> Path:
    for name in COMPOSE_FILES:
        candidate = project / name
        if candidate.is_file():
            return candidate
    raise OrcaError(f"no compose file found in {project}")


def compose_files(project: Path) -> list[Path]:
    """The base compose file plus the first override file next to it, if any."""
    files = [compose_file(project)]
    for name in OVERRIDE_FILES:
        candidate = project / name
        if candidate.is_file():
            files.append(candidate)
            break
    return files
