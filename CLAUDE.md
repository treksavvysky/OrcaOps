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
