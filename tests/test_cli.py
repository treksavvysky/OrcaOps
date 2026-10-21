import json

import pytest

from orcaops import core
from orcaops.cli import build_parser
from orcaops.core import OrcaError, compose_file, compose_files, docker

COMMAND_SET = ["status", "ps", "logs", "build", "up", "down", "restart", "doctor", "prune"]


class FakeDocker:
    """Stands in for the docker binary: answers the guard's reads, records the rest."""

    def __init__(self):
        self.project = "proj"
        self.containers = []  # dicts: name, files, env
        self.calls = []

    def add(self, name, files, env=""):
        self.containers.append({"name": name, "files": files, "env": env})

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = ""
        if cmd[:2] == ["docker", "compose"] and "config" in cmd:
            out = json.dumps({"name": self.project})
        elif cmd[1:3] == ["ps", "-aq"]:
            out = "\n".join(f"id{i}" for i, _ in enumerate(self.containers))
        elif cmd[1] == "inspect":
            out = json.dumps([{"Name": "/" + c["name"], "Config": {"Labels": {
                "com.docker.compose.project": self.project,
                "com.docker.compose.project.config_files": c["files"],
                "com.docker.compose.project.environment_file": c["env"],
            }}} for c in self.containers])
        return core.subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


@pytest.fixture(autouse=True)
def fake_docker(monkeypatch, tmp_path):
    fake = FakeDocker()
    monkeypatch.setattr(core.subprocess, "run", fake)
    monkeypatch.setattr(core, "AUDIT_LOG", tmp_path / "audit.jsonl")
    return fake


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
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == f"[dry-run] docker compose {expected} up -d"


def _dry_run(argv, capsys):
    args = build_parser().parse_args(argv)
    args.func(args)
    return capsys.readouterr().out.strip().splitlines()[-1]


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
    log = core.AUDIT_LOG
    args = build_parser().parse_args(["up", str(tmp_path), "--file", "compose.atlas.yml",
                                      "--env-file", "release.env", "--reason", "release"])
    args.func(args)
    entry = json.loads(log.read_text())
    assert entry["cmd"] == (f"docker compose -f {tmp_path / 'compose.atlas.yml'} "
                            f"--env-file {tmp_path / 'release.env'} up -d")
    assert entry["reason"] == "release"


@pytest.fixture
def release(tmp_path):
    """A project dir shaped like the FTS release: base, atlas file, release.env."""
    for name in ("docker-compose.yml", "compose.atlas.yml"):
        (tmp_path / name).write_text("services: {}\n")
    (tmp_path / "release.env").write_text("X=1\n")
    return tmp_path


def _up(argv, capsys):
    args = build_parser().parse_args(["up", *argv])
    args.func(args)
    return capsys.readouterr().out.strip().splitlines()


def _ran_up(fake):
    return [c for c in fake.calls if c[-2:] == ["up", "-d"]]


def test_guard_no_containers_allows_first_deploy(release, fake_docker, capsys):
    out = _up([str(release), "--dry-run"], capsys)
    assert out[0] == "[guard] project proj: no existing containers (first deploy)"
    assert out[-1].startswith("[dry-run] docker compose")


def test_guard_match_allows_up(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    out = _up([str(release), "--file", "compose.atlas.yml", "--env-file", "release.env",
               "--reason", "redeploy"], capsys)
    assert out[0] == "[guard] project proj: match — same files as the running deploy"
    assert len(_ran_up(fake_docker)) == 1
    assert "guard" not in json.loads(core.AUDIT_LOG.read_text())


def test_guard_match_compares_file_sets_not_order(release, fake_docker, capsys):
    a, b = release / "docker-compose.yml", release / "compose.atlas.yml"
    fake_docker.add("web", f"{b},{a}")
    out = _up([str(release), "--file", "docker-compose.yml", "--file", "compose.atlas.yml",
               "--dry-run"], capsys)
    assert "match" in out[0]


def test_guard_mismatch_refuses_and_runs_nothing(release, fake_docker):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    args = build_parser().parse_args(["up", str(release), "--reason", "oops"])
    with pytest.raises(OrcaError) as exc:
        args.func(args)
    msg = str(exc.value)
    assert f"deployed (web): files={release / 'compose.atlas.yml'}" in msg
    assert f"env-file={release / 'release.env'}" in msg
    assert f"about to apply: files={release / 'docker-compose.yml'}  env-file=none" in msg
    assert "--ignore-deploy-mismatch" in msg
    assert _ran_up(fake_docker) == []
    assert not core.AUDIT_LOG.exists()


def test_guard_mismatch_is_refused_in_dry_run_too(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}")
    args = build_parser().parse_args(["up", str(release), "--dry-run"])
    with pytest.raises(OrcaError, match="deployed from different files"):
        args.func(args)
    assert "[dry-run]" not in capsys.readouterr().out


def test_guard_env_file_alone_is_a_mismatch(release, fake_docker):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    args = build_parser().parse_args(["up", str(release), "--file", "compose.atlas.yml",
                                      "--dry-run"])
    with pytest.raises(OrcaError, match="env-file=none"):
        args.func(args)


def test_guard_override_proceeds_and_is_audited(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    out = _up([str(release), "--replace-deploy", "--reason", "move to new layout"], capsys)
    assert out[0].startswith("[guard] OVERRIDDEN (--ignore-deploy-mismatch)")
    assert len(_ran_up(fake_docker)) == 1
    entry = json.loads(core.AUDIT_LOG.read_text())
    assert entry["reason"] == "move to new layout"
    assert entry["guard"] == {"overridden": True, "deployed": [{
        "containers": ["web"],
        "files": [str(release / "compose.atlas.yml")],
        "env_file": [str(release / "release.env")],
    }]}


def test_guard_reads_project_name_with_the_same_files(release, fake_docker, capsys):
    _up([str(release), "--file", "compose.atlas.yml", "--env-file", "release.env",
         "--dry-run"], capsys)
    config_call = next(c for c in fake_docker.calls if "config" in c)
    assert config_call == ["docker", "compose", "-f", str(release / "compose.atlas.yml"),
                           "--env-file", str(release / "release.env"),
                           "config", "--format", "json"]
    ps_call = next(c for c in fake_docker.calls if c[1] == "ps")
    assert ps_call[-1] == "label=com.docker.compose.project=proj"


def test_replace_deploy_alias_only_on_up():
    assert build_parser().parse_args(["up", ".", "--replace-deploy"]).ignore_deploy_mismatch
    with pytest.raises(SystemExit):
        build_parser().parse_args(["down", ".", "--replace-deploy"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["build", ".", "--ignore-deploy-mismatch"])


def _down(argv, capsys):
    args = build_parser().parse_args(["down", *argv])
    args.func(args)
    return capsys.readouterr().out.strip().splitlines()


def _ran_down(fake):
    return [c for c in fake.calls if c[-1] == "down"]


def test_down_guard_no_containers_is_a_noop_pass(release, fake_docker, capsys):
    out = _down([str(release), "--dry-run"], capsys)
    assert out[0] == "[guard] project proj: no existing containers (nothing to take down)"
    assert out[-1] == f"[dry-run] docker compose -f {release / 'docker-compose.yml'} down"


def test_down_guard_match_allows_down(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    out = _down([str(release), "--file", "compose.atlas.yml", "--env-file", "release.env",
                 "--reason", "planned stop"], capsys)
    assert out[0] == "[guard] project proj: match — same files as the running deploy"
    assert len(_ran_down(fake_docker)) == 1
    assert "guard" not in json.loads(core.AUDIT_LOG.read_text())


def test_down_guard_mismatch_refuses_and_runs_nothing(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    for extra in (["--reason", "oops"], ["--dry-run"]):
        args = build_parser().parse_args(["down", str(release), *extra])
        with pytest.raises(OrcaError) as exc:
            args.func(args)
        msg = str(exc.value)
        assert f"deployed (web): files={release / 'compose.atlas.yml'}" in msg
        assert f"about to apply: files={release / 'docker-compose.yml'}  env-file=none" in msg
        assert "--ignore-deploy-mismatch" in msg
    assert _ran_down(fake_docker) == []
    assert "[dry-run]" not in capsys.readouterr().out
    assert not core.AUDIT_LOG.exists()


def test_down_guard_override_proceeds_and_is_audited(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}", f"{release / 'release.env'}")
    out = _down([str(release), "--ignore-deploy-mismatch", "--reason", "retire layout"], capsys)
    assert out[0].startswith("[guard] OVERRIDDEN (--ignore-deploy-mismatch)")
    assert len(_ran_down(fake_docker)) == 1
    entry = json.loads(core.AUDIT_LOG.read_text())
    assert entry["cmd"].endswith(" down")
    assert entry["guard"] == {"overridden": True, "deployed": [{
        "containers": ["web"],
        "files": [str(release / "compose.atlas.yml")],
        "env_file": [str(release / "release.env")],
    }]}


def test_build_is_not_guarded(release, fake_docker, capsys):
    fake_docker.add("web", f"{release / 'compose.atlas.yml'}")
    out = build_parser().parse_args(["build", str(release), "--dry-run"])
    out.func(out)
    assert capsys.readouterr().out.strip() == (
        f"[dry-run] docker compose -f {release / 'docker-compose.yml'} build")
    assert not any("config" in c for c in fake_docker.calls)
