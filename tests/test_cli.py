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


def _dry_run(argv, capsys):
    args = build_parser().parse_args(argv)
    args.func(args)
    return capsys.readouterr().out.strip()


def test_explicit_file_replaces_discovery(tmp_path, capsys):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.override.yml").write_text("services: {}\n")
    (tmp_path / "compose.atlas.yml").write_text("services: {}\n")
    out = _dry_run(["up", str(tmp_path), "--file", "compose.atlas.yml", "--dry-run"], capsys)
    assert out == f"[dry-run] docker compose -f {tmp_path / 'compose.atlas.yml'} up -d"


def test_explicit_files_are_repeatable_and_ordered(tmp_path, capsys):
    for name in ("a.yml", "b.yml"):
        (tmp_path / name).write_text("services: {}\n")
    out = _dry_run(["build", str(tmp_path), "--file", "b.yml", "--file", "a.yml",
                    "--dry-run"], capsys)
    assert out == (f"[dry-run] docker compose -f {tmp_path / 'b.yml'} "
                   f"-f {tmp_path / 'a.yml'} build")


def test_env_file_is_passed_through(tmp_path, capsys):
    (tmp_path / "compose.atlas.yml").write_text("services: {}\n")
    (tmp_path / "release.env").write_text("X=1\n")
    out = _dry_run(["down", str(tmp_path), "--file", "compose.atlas.yml",
                    "--env-file", "release.env", "--dry-run"], capsys)
    assert out == (f"[dry-run] docker compose -f {tmp_path / 'compose.atlas.yml'} "
                   f"--env-file {tmp_path / 'release.env'} down")


def test_env_file_works_with_discovery(tmp_path, capsys):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "prod.env").write_text("X=1\n")
    out = _dry_run(["up", str(tmp_path), "--env-file", "prod.env", "--dry-run"], capsys)
    assert out == (f"[dry-run] docker compose -f {tmp_path / 'docker-compose.yml'} "
                   f"--env-file {tmp_path / 'prod.env'} up -d")


@pytest.mark.parametrize("flag", ["--file", "--env-file"])
def test_missing_explicit_file_is_refused(tmp_path, flag):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    args = build_parser().parse_args(["up", str(tmp_path), flag, "nope.yml", "--dry-run"])
    with pytest.raises(OrcaError, match="file not found"):
        args.func(args)


def test_explicit_file_command_is_audited(tmp_path, monkeypatch):
    (tmp_path / "compose.atlas.yml").write_text("services: {}\n")
    (tmp_path / "release.env").write_text("X=1\n")
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(core, "AUDIT_LOG", log)
    monkeypatch.setattr(core.subprocess, "run",
                        lambda cmd, **kw: core.subprocess.CompletedProcess(cmd, 0))
    args = build_parser().parse_args(["up", str(tmp_path), "--file", "compose.atlas.yml",
                                      "--env-file", "release.env", "--reason", "release"])
    args.func(args)
    entry = json.loads(log.read_text())
    assert entry["cmd"] == (f"docker compose -f {tmp_path / 'compose.atlas.yml'} "
                            f"--env-file {tmp_path / 'release.env'} up -d")
    assert entry["reason"] == "release"
