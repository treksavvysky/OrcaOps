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

## Architecture Overview

OrcaOps is a Python-based Docker container management system with dual interfaces (CLI and REST API).

### Layer Structure

```
CLI (Typer)  ──┐
               ├──► Core Modules ──► Docker SDK
API (FastAPI) ─┘
```

### Key Modules

- **`orcaops/docker_manager.py`** - Core Docker SDK wrapper. Provides `DockerManager` class with methods for build, run, list, logs, exec, cleanup operations.

- **`orcaops/job_runner.py`** - MVP sandbox job execution engine. Implements the golden path for running multi-step jobs in containers with:
  - Job fingerprinting (SHA256 deterministic hash)
  - Timeout handling via threading + queue pattern
  - Artifact collection from containers
  - Run record persistence (JSON + JSONL)
  - Leak detection and cleanup

- **`orcaops/sandbox_runner.py`** - Loads sandbox configs from `sandboxes.yml` into `SandboxConfig` dataclasses and manages container lifecycle with cleanup policies.

- **`orcaops/schemas.py`** - Pydantic models defining the job system: `JobSpec`, `RunRecord`, `StepResult`, `JobStatus`, `CleanupStatus`.

- **`orcaops/sandbox_registry.py`** - Tracks generated sandbox projects in `~/.orcaops/sandboxes.json`. Used by `orcaops init` and `orcaops list`.

- **`orcaops/sandbox_templates_simple.py`** - Template system for scaffolding multi-service projects (web-dev, python-ml, api-testing). Generates docker-compose.yml, Makefile, README.

- **`orcaops/main_cli.py`** - Primary CLI entry point using Typer. Delegates to `cli_enhanced.py` for commands.

- **`orcaops/api.py`** - FastAPI router with endpoints under `/orcaops/` prefix.

### Entry Points

- **CLI**: `orcaops` command (defined in pyproject.toml as `orcaops.main_cli:app`)
- **API**: `main.py` creates FastAPI app, `run_api.py` is the server launcher
- **API Docs**: `/docs` (Swagger), `/redoc`

### Configuration

- **`sandboxes.yml`** - YAML-based sandbox definitions with cleanup policies: `always_remove`, `remove_on_completion`, `keep_on_completion`, `remove_on_timeout`, `never_remove`

### Data Flow for Job Execution

1. `JobSpec` (Pydantic model) defines job parameters
2. `JobRunner.run_sandbox_job()` creates container, executes commands
3. `StepResult` captures each command's output/exit code
4. `RunRecord` persists final state with status, artifacts, cleanup status

---

## Product Vision

**OrcaOps is the AI-native DevOps platform** - the trusted execution environment where AI agents can safely take real-world actions: running code, managing infrastructure, and orchestrating complex workflows with full observability, cost control, and human-in-the-loop when needed.

### Core Thesis

When a GPT, Claude, or any AI assistant needs to "do something" in the real world - run code, test an API, deploy a service - OrcaOps provides the sandboxed, observable, controllable environment to make that happen.

### Target Integration Points

- **MCP Server** - Claude Code integration via Model Context Protocol
- **Custom GPT Actions** - ChatGPT integration via REST API
- **CI/CD Pipelines** - GitHub Actions, GitLab CI integration
- **Web Dashboard** - Visual interface for monitoring (future)

### Key Differentiators

1. **AI-First Design** - Structured outputs optimized for AI consumption
2. **Observable Everything** - Rich run records, anomaly detection, searchable history
3. **Workflow Engine** - Multi-step jobs with dependencies, parallelism, and conditions
4. **Multi-Tenant Safe** - Proper isolation, resource limits, security policies
5. **Self-Improving** - Learns from usage, provides intelligent recommendations

---

## Development Roadmap

The product roadmap is documented in the `docs/` folder with detailed sprint plans:

| Sprint | Focus | Duration |
|--------|-------|----------|
| [SPRINT-01](docs/SPRINT-01.md) | Foundation & Job Execution API | 2 weeks |
| [SPRINT-02](docs/SPRINT-02.md) | MCP Server Integration | 2 weeks |
| [SPRINT-03](docs/SPRINT-03.md) | Observability & Intelligent Run Records | 2 weeks |
| [SPRINT-04](docs/SPRINT-04.md) | Workflow Engine & Job Chaining | 3 weeks |
| [SPRINT-05](docs/SPRINT-05.md) | Multi-Tenant Workspaces & Security | 3 weeks |
| [SPRINT-06](docs/SPRINT-06.md) | AI-Driven Optimization | 3 weeks |

See [docs/ROADMAP.md](docs/ROADMAP.md) for the complete roadmap overview, milestones, and timeline.

### Current State

- Core DockerManager and JobRunner functional
- CLI with sandbox templates and registry
- REST API with container and sandbox endpoints
- Test coverage at 86 tests passing

### Next Steps

Begin with Sprint 01 to expose JobRunner through the REST API, enabling external clients to submit and monitor jobs programmatically
