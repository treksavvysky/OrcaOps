"""The orca command-line interface: nine commands, nothing more."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .core import AUDIT_LOG, OrcaError, compose_files, docker


def cmd_status(args):
    info = json.loads(docker("info", "--format", "{{json .}}", capture=True).stdout)
    print(f"engine      {info.get('ServerVersion', 'unknown')}")
    print(f"containers  {info.get('ContainersRunning', 0)} running / {info.get('Containers', 0)} total")
    print(f"images      {info.get('Images', 0)}")
    print(flush=True)  # flush before the subprocess writes to the same tty
    docker("system", "df")


def cmd_ps(args):
    flags = ["-a"] if args.all else []
    proc = docker("ps", *flags, "--format", "{{json .}}", capture=True)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if not rows:
        print("no containers" if args.all else "no running containers (try --all)")
        return
    width = max(len(r["Names"]) for r in rows)
    for r in rows:
        print(f"{r['Names']:<{width}}  {r['State']:<10}  {r['Status']:<24}  {r['Image']}")


def cmd_logs(args):
    flags = ["--tail", str(args.tail)]
    if args.follow:
        flags.append("--follow")
    docker("logs", *flags, args.service)


def _project_path(project: Path, name: str) -> Path:
    path = project / name  # an absolute name replaces project
    if not path.is_file():
        raise OrcaError(f"file not found: {path}")
    return path


def _compose_inputs(args):
    """The compose files and env file (or None) this invocation will apply."""
    project = Path(args.project).resolve()
    if args.file:
        # Explicit files replace discovery entirely, override included.
        files = [_project_path(project, name) for name in args.file]
    else:
        files = compose_files(project)
    env_file = _project_path(project, args.env_file) if args.env_file else None
    return files, env_file


def _compose_flags(files, env_file):
    flags = [flag for f in files for flag in ("-f", str(f))]
    if env_file:
        flags += ["--env-file", str(env_file)]
    return flags


def _compose(args, *compose_args, files=None, env_file=None, audit_extra=None):
    if files is None:
        files, env_file = _compose_inputs(args)
    return docker(
        "compose", *_compose_flags(files, env_file), *compose_args,
        mutating=True, dry_run=args.dry_run, reason=args.reason, audit_extra=audit_extra,
    )


def _label_paths(value):
    # Compose stores these labels as comma-joined absolute paths; "" means none.
    return frozenset(os.path.realpath(p) for p in (value or "").split(",") if p)


def _deployed_inputs(files, env_file):
    """What the project's existing containers were created from.

    Returns {(config_files, env_files): [container names]}; empty when the
    project has no containers yet. Compose records only an explicit
    --env-file in the label, never the default .env, so the two compare 1:1.
    """
    flags = _compose_flags(files, env_file)
    config = json.loads(docker("compose", *flags, "config", "--format", "json",
                               capture=True).stdout)
    label = f"label=com.docker.compose.project={config['name']}"
    ids = docker("ps", "-aq", "--filter", label, capture=True).stdout.split()
    deployed = {}
    if ids:
        for c in json.loads(docker("inspect", *ids, capture=True).stdout):
            labels = c["Config"]["Labels"] or {}
            key = (_label_paths(labels.get("com.docker.compose.project.config_files")),
                   _label_paths(labels.get("com.docker.compose.project.environment_file")))
            deployed.setdefault(key, []).append(c["Name"].lstrip("/"))
    return config["name"], deployed


def _fmt(paths):
    return ", ".join(sorted(paths)) or "none"


def cmd_build(args):
    _compose(args, "build")


def cmd_up(args):
    files, env_file = _compose_inputs(args)
    want = (_label_paths(",".join(map(str, files))),
            _label_paths(str(env_file) if env_file else ""))
    name, deployed = _deployed_inputs(files, env_file)
    mismatched = {k: v for k, v in deployed.items() if k != want}
    audit_extra = None
    if not deployed:
        print(f"[guard] project {name}: no existing containers (first deploy)")
    elif not mismatched:
        print(f"[guard] project {name}: match — same files as the running deploy")
    else:
        lines = [f"project {name} was deployed from different files:"]
        for (dep_files, dep_env), names in sorted(mismatched.items()):
            lines.append(f"  deployed ({', '.join(sorted(names))}): "
                         f"files={_fmt(dep_files)}  env-file={_fmt(dep_env)}")
        lines.append(f"  about to apply: files={_fmt(want[0])}  env-file={_fmt(want[1])}")
        if not args.replace_deploy:
            lines.append("  pass the deployed files (--file/--env-file), or "
                         "--replace-deploy if this change is intended")
            raise OrcaError("\n".join(lines))
        print("[guard] OVERRIDDEN (--replace-deploy): " + "\n".join(lines))
        audit_extra = {"guard": {
            "overridden": True,
            "deployed": [{"containers": sorted(names), "files": sorted(f), "env_file": sorted(e)}
                         for (f, e), names in sorted(mismatched.items())],
        }}
    _compose(args, "up", "-d", files=files, env_file=env_file, audit_extra=audit_extra)


def cmd_down(args):
    _compose(args, "down")


def cmd_restart(args):
    docker("restart", args.service, mutating=True, dry_run=args.dry_run, reason=args.reason)


def cmd_prune(args):
    if not args.safe:
        raise OrcaError("only `orca prune --safe` exists; anything more aggressive stays manual")
    docker("image", "prune", "-f",
           mutating=True, dry_run=args.dry_run, reason="prune --safe: dangling images")
    docker("builder", "prune", "-f", "--filter", "until=168h",
           mutating=True, dry_run=args.dry_run, reason="prune --safe: build cache older than 7 days")


def cmd_doctor(args):
    failures = []

    def check(label, ok, hint=""):
        print(f"[{'ok' if ok else 'FAIL':>4}] {label}{' — ' + hint if not ok and hint else ''}")
        if not ok:
            failures.append(label)

    check("docker binary on PATH", shutil.which("docker") is not None,
          "install docker or fix PATH")

    daemon_ok = False
    if shutil.which("docker"):
        try:
            docker("info", "--format", "{{.ServerVersion}}", capture=True)
            daemon_ok = True
        except OrcaError:
            pass
        check("docker daemon reachable", daemon_ok,
              "daemon down, or this user lacks socket access")
        try:
            docker("compose", "version", capture=True)
            compose_ok = True
        except OrcaError:
            compose_ok = False
        check("compose plugin available", compose_ok, "install the docker compose plugin")

    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_LOG.touch(exist_ok=True)
        check(f"audit log writable ({AUDIT_LOG})", True)
    except OSError:
        check(f"audit log writable ({AUDIT_LOG})", False, "check permissions")

    if failures:
        raise OrcaError(f"{len(failures)} check(s) failed")
    print("all checks passed")


def _add_mutating_flags(parser):
    parser.add_argument("--dry-run", action="store_true",
                        help="print the docker command without running it")
    parser.add_argument("--reason", help="why this action is being taken (recorded in the audit log)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="orca",
        description="Safety-gated Docker operations for humans and AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"orcaops {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="engine summary and disk usage")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ps", help="list containers")
    p.add_argument("-a", "--all", action="store_true", help="include stopped containers")
    p.set_defaults(func=cmd_ps)

    p = sub.add_parser("logs", help="show logs for a container")
    p.add_argument("service")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("--tail", type=int, default=100)
    p.set_defaults(func=cmd_logs)

    for name, func, help_text in (
        ("build", cmd_build, "compose build a project"),
        ("up", cmd_up, "compose up -d a project"),
        ("down", cmd_down, "compose down a project"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("project", nargs="?", default=".",
                       help="directory containing a compose file (default: cwd)")
        p.add_argument("--file", action="append", metavar="FILE",
                       help="compose file to use instead of discovery (repeatable; "
                            "relative to project)")
        p.add_argument("--env-file", metavar="FILE",
                       help="env file passed to compose (relative to project)")
        _add_mutating_flags(p)
        if name == "up":
            p.add_argument("--replace-deploy", action="store_true",
                           help="proceed even though the running containers were deployed "
                                "from different compose/env files (recorded in the audit log)")
        p.set_defaults(func=func)

    p = sub.add_parser("restart", help="restart a container")
    p.add_argument("service")
    _add_mutating_flags(p)
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("doctor", help="check that this host is ready for orca")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("prune", help="reclaim space, conservatively")
    p.add_argument("--safe", action="store_true",
                   help="dangling images + build cache older than 7 days")
    p.add_argument("--dry-run", action="store_true",
                   help="print the docker commands without running them")
    p.set_defaults(func=cmd_prune)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except OrcaError as exc:
        print(f"orca: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
