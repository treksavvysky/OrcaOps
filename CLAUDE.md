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

## MCP Server

OrcaOps exposes an MCP (Model Context Protocol) server for Claude Code and other MCP clients:

```bash
# Start the MCP server (stdio transport)
orcaops-mcp

# Debug mode
orcaops-mcp --debug
```

**Claude Code configuration** — add to `~/.claude/settings.json` or project `.mcp.json`:
```json
{
  "mcpServers": {
    "orcaops": {
      "command": "orcaops-mcp",
      "args": []
    }
  }
}
```

42 MCP tools available: `orcaops_run_job`, `orcaops_submit_job`, `orcaops_list_jobs`, `orcaops_get_job_status`, `orcaops_get_job_logs`, `orcaops_cancel_job`, `orcaops_list_artifacts`, `orcaops_get_artifact`, `orcaops_list_sandboxes`, `orcaops_get_sandbox`, `orcaops_create_sandbox`, `orcaops_start_sandbox`, `orcaops_stop_sandbox`, `orcaops_list_templates`, `orcaops_get_template`, `orcaops_list_containers`, `orcaops_get_container_logs`, `orcaops_inspect_container`, `orcaops_stop_container`, `orcaops_remove_container`, `orcaops_system_info`, `orcaops_cleanup_containers`, `orcaops_list_runs`, `orcaops_get_run`, `orcaops_delete_run`, `orcaops_cleanup_runs`, `orcaops_get_job_summary`, `orcaops_get_metrics`, `orcaops_run_workflow`, `orcaops_submit_workflow`, `orcaops_get_workflow_status`, `orcaops_cancel_workflow`, `orcaops_list_workflows`, `orcaops_create_workspace`, `orcaops_list_workspaces`, `orcaops_get_workspace`, `orcaops_create_api_key`, `orcaops_revoke_api_key`, `orcaops_query_audit`, `orcaops_create_session`, `orcaops_get_session`, `orcaops_list_sessions`, `orcaops_end_session`.

No linter or formatter is configured. No CI/CD pipeline exists yet.

## Architecture Overview

OrcaOps is a Docker container management system with three interfaces (CLI, REST API, and MCP server) sharing common core modules.

```
CLI (Typer)  ──┐
               ├──► Core Modules ──► Docker SDK
API (FastAPI) ─┤
MCP (FastMCP) ─┘
```

### Entry Points

- **CLI**: `orcaops` command → `orcaops/main_cli.py` (delegates to `cli_enhanced.py` for commands, `cli_utils_fixed.py` for sandbox commands)
- **API**: `main.py` creates FastAPI app with routes from `orcaops/api.py` under `/orcaops/` prefix
- **API launcher**: `python run_api.py` (wraps uvicorn)
- **API Docs**: `/docs` (Swagger), `/redoc`
- **MCP**: `orcaops-mcp` command → `orcaops/mcp_server.py` (stdio transport)

### Core Modules

- **`docker_manager.py`** — Docker SDK wrapper (`DockerManager` class). All container operations (build, run, list, logs, exec, cleanup) go through this.

- **`job_runner.py`** — Executes multi-step jobs inside containers. Handles job fingerprinting (SHA256), timeout via threading+queue, artifact collection, and run record persistence (JSON + JSONL files).

- **`job_manager.py`** — Thread-safe job lifecycle manager. Wraps `JobRunner` with a global lock plus per-job locks for concurrent access. Each submitted job runs in its own thread with a `threading.Event` for cancellation. In-memory job registry with automatic eviction of completed jobs and disk fallback via `~/.orcaops/artifacts/{job_id}/run.json`.

- **`sandbox_runner.py`** — Loads sandbox definitions from `sandboxes.yml` into `SandboxConfig` dataclasses. Manages container lifecycle with cleanup policies.

- **`schemas.py`** — All Pydantic models. Core chain: `JobSpec` → `StepResult` → `RunRecord`. Workflow models: `WorkflowSpec`, `WorkflowJob`, `WorkflowRecord`, `WorkflowJobStatus`, `ServiceDefinition`, `MatrixConfig`. Workspace models: `Workspace`, `WorkspaceSettings`, `ResourceLimits`, `WorkspaceUsage`. Auth models: `Permission`, `APIKey`. Security models: `SecurityPolicy`, `ImagePolicy`, `CommandPolicy`, `PolicyResult`. Audit models: `AuditEvent`, `AuditAction`, `AuditOutcome`. Session models: `AgentSession`, `SessionStatus`. Also defines API request/response models and enums (`JobStatus`, `WorkflowStatus`, `WorkspaceStatus`, `OwnerType`, `CleanupStatus`, `SandboxStatus`).

- **`run_store.py`** — Disk-backed persistence layer for historical run records. Scans `~/.orcaops/artifacts/*/run.json` for listing, filtering (by status, image, tags, triggered_by, date range, duration), deletion, and time-based cleanup.

- **`log_analyzer.py`** — Regex-based log analysis (`LogAnalyzer`) and deterministic summary generation (`SummaryGenerator`). Detects errors, warnings, and stack traces (Python, Node.js, Go, Java) in job output. Generates one-liner summaries, key events, and actionable suggestions.

- **`metrics.py`** — On-the-fly metrics aggregation (`MetricsAggregator`) from RunStore and EMA-based duration baseline tracking (`BaselineTracker`). Baselines persist to `~/.orcaops/baselines.json` and detect anomalies when duration exceeds 2x the EMA after 3+ data points.

- **`workflow_schema.py`** — YAML-based workflow spec loading, DAG validation (cycle detection via `graphlib.TopologicalSorter`), execution order computation, matrix expansion (`itertools.product`), and safe condition evaluation (`ConditionEvaluator` with regex-based parsing, no `eval`).

- **`workflow_runner.py`** — DAG execution engine (`WorkflowRunner`). Runs workflow level-by-level using `ThreadPoolExecutor` for parallel job groups. Delegates individual jobs to `JobManager.submit_job()`. Handles `on_complete` rules (success/failure/always), `if_condition` evaluation, matrix variant expansion, and service container lifecycle.

- **`workflow_manager.py`** — Thread-safe workflow lifecycle manager (`WorkflowManager`), analogous to `JobManager`. Background thread per workflow with `threading.Event` for cancellation. Atomic disk persistence via `~/.orcaops/workflows/{id}/workflow.json`. Memory eviction of completed workflows (cap 100).

- **`workflow_store.py`** — Disk-backed persistence for historical workflow records (`WorkflowStore`). Scans `~/.orcaops/workflows/*/workflow.json` for listing, filtering, and deletion.

- **`service_manager.py`** — Service container lifecycle for workflow jobs (`ServiceManager`). Creates Docker networks, starts service containers with health checks, injects `{SERVICE}_HOST`/`{SERVICE}_PORT` env vars, and cleans up after job completion.

- **`workspace.py`** — Thread-safe workspace registry (`WorkspaceRegistry`). CRUD operations for workspaces with JSON file persistence at `~/.orcaops/workspaces/{workspace_id}/workspace.json`. Auto-creates default workspace (`ws_default`).

- **`auth.py`** — API key management (`KeyManager`). Generates bcrypt-hashed keys (format: `orcaops_{workspace_id}_{random32}`), validates keys, tracks `last_used`, supports key rotation. Role templates: admin, developer, viewer, ci. `has_permission()` checks with `WORKSPACE_ADMIN` inheritance.

- **`auth_middleware.py`** — FastAPI auth dependencies. `AuthContext` model, `get_auth_context()` from Bearer header, `require_auth()` (401), `require_permission(permission)` factory (403). Auth is opt-in — when no keys exist, requests pass through.

- **`policy_engine.py`** — Security policy validation (`PolicyEngine`). `validate_image()` via `fnmatch` glob patterns, `validate_command()` via exact match + regex, `validate_job()` combines both. `get_container_security_opts()` returns Docker security options. Merges workspace-level settings with global policy.

- **`audit.py`** — Thread-safe JSONL audit logging (`AuditLogger`) with date-based files (`~/.orcaops/audit/YYYY-MM-DD.jsonl`). Read-only query layer (`AuditStore`) with filters (workspace, actor, action, date range) and pagination. Cleanup of old files.

- **`quota_tracker.py`** — Thread-safe resource limit enforcement (`QuotaTracker`). Tracks concurrent running jobs/sandboxes per workspace, daily job counts. `check_limits()` validates against `ResourceLimits` before job creation.

- **`session_manager.py`** — Agent session lifecycle manager (`SessionManager`). Creates/tracks MCP sessions with resource attribution. Supports idle expiration, explicit session end, disk persistence at `~/.orcaops/sessions/{session_id}.json`.

- **`api.py`** — FastAPI router. Instantiates `DockerManager`, `JobManager`, `RunStore`, `WorkflowManager`, `WorkflowStore`, `WorkspaceRegistry`, `KeyManager`, and `SessionManager` as module-level singletons. Endpoints for containers (`/ps`, `/logs`, etc.), sandboxes, templates, jobs (`/jobs`, `/jobs/{id}`, `/jobs/{id}/cancel`, `/jobs/{id}/artifacts`, `/jobs/{id}/logs/stream`, `/jobs/{id}/summary`), metrics (`/metrics/jobs`), run history (`/runs`, `/runs/{id}`, `/runs/cleanup`), workflows (`/workflows`, `/workflows/{id}`, `/workflows/{id}/jobs`, `/workflows/{id}/cancel`), workspaces (`/workspaces`, `/workspaces/{id}`, `/workspaces/{id}/keys`), and sessions (`/sessions`, `/sessions/{id}`).

- **`mcp_server.py`** — MCP server using FastMCP (decorator-based API). Exposes 42 tools across 11 categories (job execution, sandbox management, containers, system, observability, run history, workflows, workspaces, API keys, audit, sessions). Uses lazy-initialized singletons for all managers. All tools return structured JSON with `success`/`error` fields. Stdio transport for Claude Code integration.

### CLI Structure

- `main_cli.py` — Entry point, wires together commands from the modules below
- `cli_enhanced.py` — Core container commands (ps, logs, rm, stop, inspect, doctor, interactive) and shared utility functions (`format_duration`, `format_size`, `get_container_status_icon`)
- `cli_utils_fixed.py` — Sandbox commands (init, list, up, down, cleanup, templates) and `CLIUtils`/`CLICommands` classes
- `cli_jobs.py` — Job management commands (run, jobs, jobs status/logs/cancel/artifacts/download/summary, metrics, runs-cleanup)
- `cli_workflows.py` — Workflow management commands (workflow run/status/cancel, workflow list)
- `cli_workspaces.py` — Workspace management commands (workspace create/list/status, workspace keys create/list/revoke, workspace audit, workspace sessions)

New container commands go in `cli_enhanced.py`. Sandbox commands go in `cli_utils_fixed.py`. Job commands go in `cli_jobs.py`. Workflow commands go in `cli_workflows.py`. Workspace/auth/audit/session commands go in `cli_workspaces.py`.

### Data Flow for Job Execution

1. `JobSpec` (Pydantic) defines job: image, commands, artifacts, TTL, triggered_by, intent, tags
2. `JobManager.submit_job()` creates a daemon thread, stores `JobEntry` in memory
3. Thread calls `JobRunner.run_sandbox_job()` which creates container, runs commands sequentially
4. Each command produces a `StepResult` (exit code, stdout, stderr, duration)
5. On first failure, execution stops (fail-fast)
6. After commands: resource usage collected via Docker stats, environment captured, logs analyzed
7. `BaselineTracker` updates EMA-based duration baseline and detects anomalies
8. `RunRecord` persists to `~/.orcaops/artifacts/{job_id}/run.json` with full observability data

### Data Flow for Workflow Execution

1. `WorkflowSpec` (Pydantic) defines workflow: name, env, jobs with dependencies/conditions/services/matrix
2. `WorkflowManager.submit_workflow()` creates a daemon thread, stores `WorkflowEntry` in memory
3. Thread calls `WorkflowRunner.run()` which resolves DAG via `graphlib.TopologicalSorter`
4. Jobs execute level-by-level — jobs in the same level run in parallel via `ThreadPoolExecutor`
5. Each job: optionally starts service containers, builds `JobSpec`, submits to `JobManager`, polls until done
6. `on_complete` rules control execution: `success` (default), `failure` (run on upstream failure), `always`
7. `if_condition` expressions evaluated via `ConditionEvaluator` (regex-based, no eval)
8. Matrix jobs expand into individual variants, each submitted as a separate `JobSpec`
9. `WorkflowRecord` persists to `~/.orcaops/workflows/{workflow_id}/workflow.json`

### Persistence

- **Run records**: `~/.orcaops/artifacts/{job_id}/run.json` (full record) + `steps.jsonl` (streaming)
- **Workflow records**: `~/.orcaops/workflows/{workflow_id}/workflow.json` (full record with job statuses)
- **Baselines**: `~/.orcaops/baselines.json` (EMA-based duration baselines per image+command)
- **Sandbox registry**: `~/.orcaops/sandboxes.json` (tracks scaffolded projects)
- **Sandbox definitions**: `sandboxes.yml` at project root
- **Workspaces**: `~/.orcaops/workspaces/{workspace_id}/workspace.json`
- **API keys**: `~/.orcaops/workspaces/{workspace_id}/keys/{key_id}.json` (bcrypt-hashed)
- **Audit logs**: `~/.orcaops/audit/YYYY-MM-DD.jsonl` (append-only JSONL)
- **Agent sessions**: `~/.orcaops/sessions/{session_id}.json`

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
- `test_mcp_server.py` — MCP server tool tests (all 26 tools, mocked dependencies)
- `test_schemas_sprint03.py` — Sprint 03 schema tests (backward compat, new models, round-trip)
- `test_job_runner_observability.py` — Resource collection, environment capture, log analysis integration
- `test_log_analyzer.py` — LogAnalyzer unit tests (error/warning/stack trace detection, caps)
- `test_summary_generator.py` — SummaryGenerator tests (all status types, extras, duration formatting)
- `test_metrics.py` — MetricsAggregator tests (counts, by-image, date filter, durations)
- `test_baselines.py` — BaselineTracker tests (EMA, anomaly detection, persistence, key generation)
- `test_run_store_filters.py` — RunStore extended filter tests (image, tags, triggered_by, date, duration)
- `test_api_observability.py` — API observability endpoint tests (summary, metrics, run filters)
- `test_mcp_observability.py` — MCP observability tool tests (summary, metrics, context params)
- `test_cli_observability.py` — CLI observability command tests (summary, metrics)
- `test_workflow_schema.py` — Workflow schema tests (YAML loading, DAG validation, matrix expansion, conditions)
- `test_workflow_runner.py` — WorkflowRunner tests (linear, parallel, failure, conditions, matrix, cancellation)
- `test_workflow_manager.py` — WorkflowManager tests (submit, get, list, cancel, persistence)
- `test_service_manager.py` — ServiceManager tests (start/stop, health checks, port inference, duration parsing)
- `test_docker_network.py` — DockerManager network method tests (create, remove, connect)
- `test_api_workflows.py` — Workflow API endpoint tests (submit, status, jobs, cancel, list)
- `test_cli_workflows.py` — Workflow CLI command tests (run, status, cancel, list)
- `test_mcp_workflows.py` — Workflow MCP tool tests (submit, run, status, cancel, list)
- `test_workspace.py` — WorkspaceRegistry tests (CRUD, validation, persistence, defaults)
- `test_auth.py` — KeyManager tests (generate, validate, revoke, rotate, permissions, roles)
- `test_auth_middleware.py` — Auth middleware tests (AuthContext, get/require auth, permissions)
- `test_api_workspaces.py` — Workspace/key API endpoint tests (CRUD, keys)
- `test_policy_engine.py` — PolicyEngine tests (image/command validation, workspace merge, security opts)
- `test_audit.py` — Audit logging tests (JSONL write, query, filters, thread safety, cleanup)
- `test_quota_tracker.py` — QuotaTracker tests (limits, daily counts, workspace isolation, concurrency)
- `test_integration_security.py` — Integration tests (policy enforcement, quota, audit, security opts in job manager)
- `test_session_manager.py` — SessionManager tests (lifecycle, resources, filters, idle expiry, persistence)
- `test_cli_workspaces.py` — Workspace CLI tests (create, list, status, keys, audit, sessions)
- `test_mcp_workspaces.py` — Workspace/auth/audit/session MCP tool tests

Coverage is configured in `pyproject.toml` via pytest addopts: `--cov=orcaops --cov-report=term-missing`.

## Product Context

OrcaOps is an AI-native DevOps platform — a sandboxed execution environment for AI agents to run code, manage infrastructure, and orchestrate workflows. Target integrations include MCP Server (Claude Code), Custom GPT Actions (REST API), and CI/CD pipelines. The development roadmap is in `docs/` with 6 sprint plans (SPRINT-01 through SPRINT-06). Sprint 01 (Job Execution API), Sprint 02 (MCP Server Integration), Sprint 03 (Observability & Intelligent Run Records), Sprint 04 (Workflow Engine & Job Chaining), and Sprint 05 (Multi-Tenant Workspaces & Security Policies) are complete. Next: Sprint 06.
