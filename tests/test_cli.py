import json

import pytest

from orcaops import core
from orcaops.cli import build_parser
from orcaops.core import OrcaError, compose_file, compose_files, docker

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


def test_compose_files_without_override(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    assert [f.name for f in compose_files(tmp_path)] == ["docker-compose.yml"]


def test_compose_files_includes_override(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.override.yml").write_text("services: {}\n")
    assert [f.name for f in compose_files(tmp_path)] == [
        "docker-compose.yml", "docker-compose.override.yml"]


@pytest.mark.parametrize("with_override", [False, True])
def test_compose_dry_run_shows_every_file(tmp_path, capsys, with_override):
    base = tmp_path / "docker-compose.yml"
    base.write_text("services: {}\n")
    expected = f"-f {base}"
    if with_override:
        override = tmp_path / "docker-compose.override.yml"
        override.write_text("services: {}\n")
        expected += f" -f {override}"
    args = build_parser().parse_args(["up", str(tmp_path), "--dry-run"])
    args.func(args)
    assert capsys.readouterr().out.strip() == f"[dry-run] docker compose {expected} up -d"
