# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
# Install in development mode
pip install -e .

# Install with test dependencies
pip install -e ".[test]"

# Run all tests with coverage
pytest

# Run a specific test file
pytest tests/test_docker_manager.py -v

# Run a single test
pytest tests/test_golden_path.py::test_job_success -v

# Start the CLI
orcaops --help

# Start the API server (default: http://127.0.0.1:8000)
python run_api.py

# Start API with hot reload
python run_api.py --host 0.0.0.0 --port 8000 --reload
```

No linter or formatter is configured. No CI/CD pipeline exists yet.

## Architecture Overview

OrcaOps is a Docker container management system with dual interfaces (CLI and REST API) sharing common core modules.

```
CLI (Typer)  ──┐
               ├──► Core Modules ──► Docker SDK
API (FastAPI) ─┘
```

### Entry Points

- **CLI**: `orcaops` command → `orcaops/main_cli.py` (delegates to `cli_enhanced.py` for commands, `cli_utils_fixed.py` for sandbox commands)
- **API**: `main.py` creates FastAPI app with routes from `orcaops/api.py` under `/orcaops/` prefix
- **API launcher**: `python run_api.py` (wraps uvicorn)
- **API Docs**: `/docs` (Swagger), `/redoc`

### Core Modules

- **`docker_manager.py`** — Docker SDK wrapper (`DockerManager` class). All container operations (build, run, list, logs, exec, cleanup) go through this.

- **`job_runner.py`** — Executes multi-step jobs inside containers. Handles job fingerprinting (SHA256), timeout via threading+queue, artifact collection, and run record persistence (JSON + JSONL files).

- **`job_manager.py`** — Thread-safe job lifecycle manager. Wraps `JobRunner` with a global lock plus per-job locks for concurrent access. Each submitted job runs in its own thread with a `threading.Event` for cancellation. In-memory job registry with automatic eviction of completed jobs and disk fallback via `~/.orcaops/artifacts/{job_id}/run.json`.

- **`sandbox_runner.py`** — Loads sandbox definitions from `sandboxes.yml` into `SandboxConfig` dataclasses. Manages container lifecycle with cleanup policies.

- **`schemas.py`** — All Pydantic models. Core chain: `JobSpec` → `StepResult` → `RunRecord`. Also defines API request/response models and enums (`JobStatus`, `CleanupStatus`, `SandboxStatus`).

- **`run_store.py`** — Disk-backed persistence layer for historical run records. Scans `~/.orcaops/artifacts/*/run.json` for listing, filtering, deletion, and time-based cleanup.

- **`api.py`** — FastAPI router. Instantiates `DockerManager`, `JobManager`, and `RunStore` as module-level singletons. Endpoints for containers (`/ps`, `/logs`, etc.), sandboxes, templates, jobs (`/jobs`, `/jobs/{id}`, `/jobs/{id}/cancel`, `/jobs/{id}/artifacts`, `/jobs/{id}/logs/stream`), and run history (`/runs`, `/runs/{id}`, `/runs/cleanup`).

### CLI Structure

- `main_cli.py` — Entry point, wires together commands from the modules below
- `cli_enhanced.py` — Core container commands (ps, logs, rm, stop, inspect, doctor, interactive) and shared utility functions (`format_duration`, `format_size`, `get_container_status_icon`)
- `cli_utils_fixed.py` — Sandbox commands (init, list, up, down, cleanup, templates) and `CLIUtils`/`CLICommands` classes
- `cli_jobs.py` — Job management commands (run, jobs, jobs status/logs/cancel/artifacts/download, runs-cleanup)

New container commands go in `cli_enhanced.py`. Sandbox commands go in `cli_utils_fixed.py`. Job commands go in `cli_jobs.py`.

### Data Flow for Job Execution

1. `JobSpec` (Pydantic) defines job: image, commands, artifacts, TTL
2. `JobManager.submit_job()` creates a daemon thread, stores `JobEntry` in memory
3. Thread calls `JobRunner.run_sandbox_job()` which creates container, runs commands sequentially
4. Each command produces a `StepResult` (exit code, stdout, stderr, duration)
5. On first failure, execution stops (fail-fast)
6. `RunRecord` persists to `~/.orcaops/artifacts/{job_id}/run.json` with final status, artifacts, cleanup status

### Persistence

- **Run records**: `~/.orcaops/artifacts/{job_id}/run.json` (full record) + `steps.jsonl` (streaming)
- **Sandbox registry**: `~/.orcaops/sandboxes.json` (tracks scaffolded projects)
- **Sandbox definitions**: `sandboxes.yml` at project root

### Cleanup Policies (sandboxes.yml)

Containers created from sandbox definitions follow one of these policies:
- `always_remove` — Remove regardless of outcome
- `remove_on_completion` — Remove only on success
- `keep_on_completion` — Keep after successful completion
- `remove_on_timeout` — Remove only when timed out
- `never_remove` — Never auto-remove

### Environment Variables

- `ORCAOPS_SKIP_DOCKER_INIT=1` — Skip Docker daemon initialization (useful for CLI testing without Docker)
- Docker daemon must be running for all container-related operations

## Testing Patterns

Tests use `unittest.mock.patch` extensively to mock Docker SDK calls. No real Docker daemon is needed for most tests. Test files:

- `test_docker_manager.py` — DockerManager unit tests (container lifecycle, builds, errors)
- `test_sandbox_runner.py` — SandboxRunner integration tests (YAML loading, cleanup policies, timeouts)
- `test_golden_path.py` — JobRunner end-to-end tests (success, failure, timeout, artifact collection)
- `test_cli.py` — CLI integration tests (container commands)
- `test_cli_jobs.py` — CLI job command tests (run, jobs, cancel, artifacts)
- `test_builder_integration.py` — Docker image build tests
- `test_security.py` — Input validation tests (job_id, image, artifacts, TTL)
- `test_run_store.py` — RunStore persistence layer tests
- `test_api_runs.py` — Run history API endpoint tests
- `test_api_streaming.py` — SSE log streaming endpoint tests

Coverage is configured in `pyproject.toml` via pytest addopts: `--cov=orcaops --cov-report=term-missing`.

## Product Context

OrcaOps is an AI-native DevOps platform — a sandboxed execution environment for AI agents to run code, manage infrastructure, and orchestrate workflows. Target integrations include MCP Server (Claude Code), Custom GPT Actions (REST API), and CI/CD pipelines. The development roadmap is in `docs/` with 6 sprint plans (SPRINT-01 through SPRINT-06). Sprint 01 (Job Execution API) is complete. Next: Sprint 02 (MCP Server Integration).
