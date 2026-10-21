# OrcaOps

> OrcaOps is not a Docker wrapper. It is an operational safety layer for
> AI-assisted infrastructure work.

`orca` is a small CLI that sits between "an agent (or a human) wants to change
container state" and "the host actually changes state." Every mutating action
is explicit, auditable, and previewable. This is v2, rebuilt from scratch;
v1 lives at [OrcaOps-legacy](https://github.com/treksavvysky/OrcaOps-legacy).

## Install

```bash
uv tool install .        # or: uv pip install -e . inside a venv
orca doctor
```

Requires Python ≥ 3.10 and the `docker` CLI with the compose plugin. There are
no runtime dependencies — orca shells out to `docker` and parses its JSON.

## Commands

This is the whole surface. New commands need a reason to exist.

```
orca status                    engine summary and disk usage
orca ps [--all]                list containers
orca logs <service> [-f]       container logs (default: last 100 lines)
orca build [project]           compose build   (project dir, default cwd)
orca up [project]              compose up -d
orca down [project]            compose down
orca restart <service>         restart a container
orca doctor                    is this host ready for orca?
orca prune --safe              dangling images + build cache older than 7 days
```

`build`, `up` and `down` use the project's compose file plus its
`*.override.yml`, as Compose itself would. For release-style deploys, pass
`--file compose.atlas.yml` (repeatable; replaces discovery, override included)
and `--env-file release.env`. Both are relative to the project dir.

`up` and `down` check what the project's existing containers were deployed
from (Compose's `config_files` / `environment_file` labels). If that differs
from the files about to be applied, they refuse, dry runs included, and name
both sides; a `down` from a stale layout that shares the project and service
names would otherwise remove the real deployment. Pass the deployed files, or
`--ignore-deploy-mismatch` (`--replace-deploy` on `up`) when it is intended;
the override and the previously deployed files go into the audit entry.

## Safety model

- **Dry runs everywhere it matters.** Every mutating command accepts
  `--dry-run` and prints the exact `docker` invocation instead of running it.
- **Audit trail.** Every mutating command appends a JSONL entry
  (timestamp, exact command, exit code, reason) to `~/.orcaops/audit.jsonl`
  (override with `ORCA_AUDIT_LOG`). It's a plain file — read it with `jq`.
- **Reasons are recorded.** `orca restart anamnesis --reason "config update"`
  puts the why next to the what.
- **Pruning is conservative by construction.** `orca prune` only has a
  `--safe` mode; anything more aggressive stays a deliberate manual act.

## Non-goals

Learned from v1: no web UI, no REST API, no database, no auth system, no demo
scripts. A dashboard (e.g. Arcane) can *show* state; orca is the bounded tool
that *changes* it.

## Development

```bash
uv sync
uv run pytest
```
