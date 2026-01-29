# OrcaOps 🐳⚙️

**The AI-Native DevOps Platform** - A trusted execution environment where AI agents can safely run code, manage infrastructure, and orchestrate complex workflows with full observability and control.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-86%20passing-green.svg)]()

**Why "Orca"?**
Docker's logo is a whale; an orca is the apex whale. OrcaOps aims to give your containers the same edge—fast, smart, streamlined.

## 🎯 Vision

When a GPT, Claude, or any AI assistant needs to "do something" in the real world - run code, test an API, deploy a service - OrcaOps provides the sandboxed, observable, controllable environment to make that happen.

**Target Integrations:**
- **MCP Server** - Claude Code integration via Model Context Protocol
- **Custom GPT Actions** - ChatGPT integration via REST API
- **CI/CD Pipelines** - GitHub Actions, GitLab CI integration

See [docs/ROADMAP.md](docs/ROADMAP.md) for the complete product roadmap.

## 🚀 Features

- **Sandbox Templates**: Pre-configured multi-service environments (web-dev, python-ml, api-testing)
- **Sandbox Registry**: Track and manage generated sandbox projects
- **REST API**: Full API for programmatic container and sandbox management
- **Interactive CLI**: Rich terminal interface with progress bars and status indicators
- **Job Execution Engine**: Run multi-step jobs with cleanup policies and artifact collection
- **Cleanup Policies**: Intelligent container lifecycle management (`always_remove`, `keep_on_completion`, etc.)

## 📋 Prerequisites

- **Python 3.8+**
- **Docker Desktop** or **Docker Engine** (running)

## ⚡ Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/treksavvysky/OrcaOps.git
cd OrcaOps

# Install in development mode
pip install -e .

# Verify installation
orcaops --help
```

### Create and Run a Sandbox

```bash
# List available templates
orcaops templates

# Create a new sandbox from template
orcaops init web-dev --name my-app --dir ./my-app

# List your sandboxes
orcaops list

# Start the sandbox
orcaops up my-app

# Check running containers
orcaops ps

# Stop the sandbox
orcaops down my-app
```

### REST API

```bash
# Start API server (default: http://127.0.0.1:8000)
python run_api.py

# Or with hot reload
python run_api.py --host 0.0.0.0 --port 8000 --reload
```

**Interactive Documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 📡 API Endpoints

### Containers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/orcaops/ps` | List containers (`?all=true` for all) |
| GET | `/orcaops/logs/{id}` | Get container logs |
| GET | `/orcaops/inspect/{id}` | Inspect container details |
| POST | `/orcaops/stop/{id}` | Stop a container |
| DELETE | `/orcaops/rm/{id}` | Remove a container |
| POST | `/orcaops/cleanup` | Stop and remove all containers |

### Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/orcaops/templates` | List available templates |
| GET | `/orcaops/templates/{id}` | Get template details |

### Sandboxes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/orcaops/sandboxes` | List registered sandboxes |
| GET | `/orcaops/sandboxes/{name}` | Get sandbox details |
| POST | `/orcaops/sandboxes` | Create sandbox from template |
| POST | `/orcaops/sandboxes/{name}/up` | Start a sandbox |
| POST | `/orcaops/sandboxes/{name}/down` | Stop a sandbox |
| GET | `/orcaops/sandboxes/{name}/validate` | Validate sandbox exists |
| DELETE | `/orcaops/sandboxes/{name}` | Unregister a sandbox |
| POST | `/orcaops/sandboxes/cleanup` | Remove invalid entries |

## 🎮 CLI Commands

### Sandbox Management

```bash
# List available templates
orcaops templates

# Create sandbox from template
orcaops init <template> [--name NAME] [--dir DIRECTORY]
# Templates: web-dev, python-ml, api-testing

# List registered sandboxes
orcaops list [--validate] [--cleanup]

# Start a sandbox
orcaops up <sandbox-name>

# Stop a sandbox
orcaops down <sandbox-name> [--volumes]
```

### Container Management

```bash
# List containers
orcaops ps [--all]

# View container logs
orcaops logs <container-id>

# Stop containers
orcaops stop <container-id> [<container-id>...]

# Remove containers
orcaops rm <container-id> [--force]

# System diagnostics
orcaops doctor
```

## 🏗️ Project Structure

```
OrcaOps/
├── orcaops/
│   ├── __init__.py              # Package initialization
│   ├── main_cli.py              # CLI entry point (Typer)
│   ├── cli_enhanced.py          # Enhanced CLI commands
│   ├── cli_utils_fixed.py       # Sandbox management commands
│   ├── api.py                   # FastAPI router
│   ├── schemas.py               # Pydantic models
│   ├── docker_manager.py        # Docker SDK wrapper
│   ├── job_runner.py            # Job execution engine
│   ├── sandbox_runner.py        # Sandbox lifecycle management
│   ├── sandbox_registry.py      # Sandbox tracking (~/.orcaops/)
│   └── sandbox_templates_simple.py  # Template system
├── docs/
│   ├── ROADMAP.md               # Product roadmap overview
│   ├── SPRINT-01.md             # Foundation & Job API
│   ├── SPRINT-02.md             # MCP Server Integration
│   ├── SPRINT-03.md             # Observability
│   ├── SPRINT-04.md             # Workflow Engine
│   ├── SPRINT-05.md             # Multi-Tenant & Security
│   └── SPRINT-06.md             # AI-Driven Optimization
├── tests/                       # Test suite (86 tests)
├── sandboxes.yml                # Sandbox job definitions
├── main.py                      # FastAPI app
├── run_api.py                   # API server launcher
├── CLAUDE.md                    # Claude Code guidance
└── pyproject.toml               # Package configuration
```

## 🔧 Configuration

### Sandbox Templates

Templates generate complete project scaffolding:

| Template | Services | Description |
|----------|----------|-------------|
| `web-dev` | nginx, node, postgres | Full-stack web development |
| `python-ml` | jupyter | Machine learning with Jupyter |
| `api-testing` | node, redis, postgres | API testing environment |

### Sandbox Jobs (`sandboxes.yml`)

For single-container jobs with cleanup policies:

```yaml
sandboxes:
  - name: "python_script"
    image: "python:3.9-slim"
    command: ["python", "-c", "print('Hello!')"]
    timeout: 60
    cleanup_policy: "remove_on_completion"
    success_exit_codes: [0]
```

**Cleanup Policies:**
- `always_remove` - Remove regardless of outcome
- `remove_on_completion` - Remove on success only
- `keep_on_completion` - Keep after completion
- `remove_on_timeout` - Remove only on timeout
- `never_remove` - Never auto-remove

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=orcaops

# Run specific test file
pytest tests/test_docker_manager.py -v
```

## 🛣️ Roadmap

Development is organized into 6 sprints (~15 weeks total):

| Sprint | Focus | Status |
|--------|-------|--------|
| [Sprint 01](docs/SPRINT-01.md) | Foundation & Job Execution API | Next |
| [Sprint 02](docs/SPRINT-02.md) | MCP Server Integration | Planned |
| [Sprint 03](docs/SPRINT-03.md) | Observability & Run Records | Planned |
| [Sprint 04](docs/SPRINT-04.md) | Workflow Engine | Planned |
| [Sprint 05](docs/SPRINT-05.md) | Multi-Tenant & Security | Planned |
| [Sprint 06](docs/SPRINT-06.md) | AI-Driven Optimization | Planned |

See [docs/ROADMAP.md](docs/ROADMAP.md) for detailed milestones and timeline.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes and add tests
4. Run tests: `pytest`
5. Commit: `git commit -am 'Add feature'`
6. Push: `git push origin feature/your-feature`
7. Submit a Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**[⭐ Star this repo](https://github.com/treksavvysky/OrcaOps)** if you find OrcaOps helpful!

Made with ❤️ for the AI-powered DevOps future

</div>
