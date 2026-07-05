import json

import pytest

from orcaops import core
from orcaops.cli import build_parser
from orcaops.core import OrcaError, compose_file, docker

COMMAND_SET = ["status", "ps", "logs", "build", "up", "down", "restart", "doctor", "prune"]


def test_parser_covers_exactly_the_doctrine_command_set():
    parser = build_parser()
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    assert sorted(sub.choices) == sorted(COMMAND_SET)


@pytest.mark.parametrize("argv", [
    ["ps", "--all"],
    ["logs", "web", "-f", "--tail", "20"],
    ["down", "some/project", "--dry-run", "--reason", "test"],
    ["prune", "--safe", "--dry-run"],
])
def test_parser_accepts_documented_invocations(argv):
    args = build_parser().parse_args(argv)
    assert callable(args.func)


def test_dry_run_prints_command_and_executes_nothing(capsys):
    result = docker("rm", "-f", "everything", dry_run=True, mutating=True)
    assert result is None
    assert capsys.readouterr().out.strip() == "[dry-run] docker rm -f everything"


def test_mutating_commands_are_audited(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(core, "AUDIT_LOG", log)
    core._audit(["docker", "restart", "web"], 0, "config update")
    entry = json.loads(log.read_text())
    assert entry["cmd"] == "docker restart web"
    assert entry["exit"] == 0
    assert entry["reason"] == "config update"
    assert "ts" in entry


def test_compose_file_discovery(tmp_path):
    with pytest.raises(OrcaError):
        compose_file(tmp_path)
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    assert compose_file(tmp_path).name == "compose.yaml"


def test_prune_refuses_without_safe_flag():
    from orcaops.cli import cmd_prune
    args = build_parser().parse_args(["prune"])
    with pytest.raises(OrcaError, match="--safe"):
        cmd_prune(args)
