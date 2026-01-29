# AGENTS.md

## Project Overview
OrcaOps is an AI-native DevOps platform for running Docker-based sandboxes and multi-step jobs via a CLI (Typer) and a REST API (FastAPI). It focuses on sandbox lifecycle management, job execution with cleanup policies, and artifact collection. See `CLAUDE.md` for a deeper architectural overview and roadmap details.

## Key Entry Points
- **CLI (primary)**: `orcaops` (Typer app in `orcaops/main_cli.py`)
- **Legacy CLI**: `orcaops-legacy` (Typer app in `orcaops/cli.py`)
- **API**: `main.py` (FastAPI app), launched via `python run_api.py`

## Core Modules
- `orcaops/docker_manager.py`: Docker SDK wrapper for container actions.
- `orcaops/job_runner.py`: Job execution engine (multi-step runs, artifacts, cleanup).
- `orcaops/sandbox_runner.py`: Loads `sandboxes.yml` and manages lifecycle policies.
- `orcaops/sandbox_templates_simple.py`: Sandbox scaffolding templates.
- `orcaops/sandbox_registry.py`: Registry at `~/.orcaops/sandboxes.json`.

## Development Setup
```bash
pip install -e .
orcaops --help
```

### API Server
```bash
python run_api.py
# or
python run_api.py --host 0.0.0.0 --port 8000 --reload
```

## Tests
```bash
pytest
pytest tests/test_docker_manager.py -v
```

## Configuration & Environment
- **No required `.env` file** for local development.
- Optional environment flag:
  - `ORCAOPS_SKIP_DOCKER_INIT=1` skips Docker initialization for CLI testing.
- Docker daemon must be available for container-related commands.

## Generated Data
- Sandbox registry stored at `~/.orcaops/sandboxes.json`.
- Sandboxes defined in `sandboxes.yml`.

## Docs
- Product roadmap and sprint plans live in `docs/`.
