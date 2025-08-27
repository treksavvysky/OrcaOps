# OrcaOps 🐳⚙️
*A lightweight, Python-first wrapper around the Docker Engine for DevOps automation and sandbox management.*

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com/)

**Why "Orca"?**  
Docker's logo is a whale; an orca is the apex whale. OrcaOps aims to give your containers the same edge—fast, smart, streamlined.

## 🚀 Features

- **Advanced Container Management**: Streamlined Docker operations with intelligent automation
- **Sandbox Orchestration**: YAML-configured containerized environments for testing and development
- **Interactive CLI**: Rich terminal interface with progress bars, status indicators, and intuitive commands
- **REST API Interface**: FastAPI-powered web API for programmatic container management
- **Docker Health Monitoring**: System diagnostics and container health checks
- **Template System**: Pre-configured sandbox templates for common development scenarios
- **Cleanup Policies**: Intelligent container lifecycle management with configurable cleanup strategies
- **Multi-Environment Support**: Manage multiple isolated development environments simultaneously

## 📋 Prerequisites

- **Python 3.8+** - Modern Python environment
- **Docker Desktop** or **Docker Engine** - Running Docker daemon
- **Sufficient system resources** - Varies based on containerized workloads

## ⚡ Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/treksavvysky/OrcaOps.git
cd OrcaOps

# Install OrcaOps in development mode
pip install -e .

# Verify installation
orcaops --version
```

### Basic Usage

```bash
# Check Docker environment health
orcaops doctor

# Build and tag the project image
orcaops build

# List available sandboxes
orcaops list

# Run sandbox environments defined in sandboxes.yml
orcaops up

# Interactive container management
orcaops interactive

# Tear down all environments
orcaops down

# Clean up Docker resources
orcaops cleanup
```

### FastAPI Web Server

Start the REST API server for web-based container management:

```bash
# Start API server (default: http://127.0.0.1:8000)
python run_api.py

# Start with custom configuration
python run_api.py --host 0.0.0.0 --port 3005 --reload

# Or use uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**API Endpoints:**
- `GET /` - Welcome message
- `GET /orcaops/ps` - List containers (supports `?all=true`)
- `GET /orcaops/logs/{container_id}` - Get container logs
- `GET /orcaops/inspect/{container_id}` - Inspect container details
- `POST /orcaops/cleanup` - Stop and remove all containers  
- `GET /orcaops/templates` - List available sandbox templates

**Interactive Documentation:**
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

```

## 🏗️ Project Structure

```
OrcaOps/
├── orcaops/                    # Main package
│   ├── __init__.py            # Package initialization and logging
│   ├── main_cli.py            # Primary CLI entry point
│   ├── cli_enhanced.py        # Enhanced CLI with rich UI
│   ├── docker_manager.py      # Docker API wrapper and operations
│   ├── sandbox_runner.py      # Sandbox execution engine
│   ├── sandbox_templates.py   # Template management system
│   └── interactive_mode.py    # Interactive shell mode
├── sandboxes.yml              # Sandbox environment definitions
├── pyproject.toml             # Package configuration and dependencies
├── tests/                     # Test suite
├── scripts/                   # Utility scripts
└── README.md                  # Project documentation
```

## 🔧 Configuration

### Sandbox Configuration (`sandboxes.yml`)

Define your containerized environments with flexible YAML configuration:

```yaml
sandboxes:
  - name: "development_env"
    image: "python:3.9-slim"
    command: ["python", "-c", "print('Development environment ready!')"]
    timeout: 60
    cleanup_policy: "remove_on_completion"
    ports:
      "8000/tcp": 8000
    volumes:
      "/host/path": 
        bind: "/container/path"
        mode: "rw"
    environment:
      - "ENV_VAR=production"
      - "DEBUG=true"
    success_exit_codes: [0]
```

#### Configuration Options:

- **`name`**: Unique identifier for the sandbox
- **`image`**: Docker image to use
- **`command`**: Container startup command (optional)
- **`timeout`**: Maximum execution time in seconds
- **`cleanup_policy`**: Container cleanup behavior
  - `always_remove`: Remove container regardless of exit status
  - `remove_on_completion`: Remove on successful completion
  - `remove_on_timeout`: Remove only if timeout occurs
  - `keep_on_completion`: Keep container after completion
  - `never_remove`: Never automatically remove
- **`ports`**: Port mapping from container to host
- **`volumes`**: Volume mounts and bind configurations
- **`environment`**: Environment variables
- **`success_exit_codes`**: List of exit codes considered successful

## 🎯 Command Reference

### Core Commands

| Command | Description | Example |
|---------|-------------|---------|
| `build` | Build and tag project images | `orcaops build` |
| `up` | Start sandbox environments | `orcaops up --sandbox dev_env` |
| `down` | Stop and remove environments | `orcaops down` |
| `list` | Show available sandboxes and containers | `orcaops list --all` |
| `logs` | View container logs | `orcaops logs container_name` |
| `exec` | Execute commands in running containers | `orcaops exec container_name "ls -la"` |

### Management Commands

| Command | Description | Example |
|---------|-------------|---------|
| `doctor` | System health diagnostics | `orcaops doctor` |
| `cleanup` | Clean Docker resources | `orcaops cleanup --volumes` |
| `interactive` | Enter interactive mode | `orcaops interactive` |
| `templates` | Manage sandbox templates | `orcaops templates list` |
| `version` | Show version information | `orcaops --version` |

### Advanced Options

```bash
# Run specific sandbox with custom timeout
orcaops up --sandbox python_dev --timeout 120

# Build with custom Dockerfile
orcaops build --dockerfile ./custom/Dockerfile

# Clean up with force removal
orcaops cleanup --force --all

# Monitor containers in real-time
orcaops list --watch
```

## 🧪 Development and Testing

### Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=orcaops --cov-report=html

# Run specific test file
pytest tests/test_docker_manager.py -v
```

### Development Setup

```bash
# Install development dependencies
pip install -e ".[test]"

# Run pre-commit hooks
pre-commit install

# Format code
black orcaops/
isort orcaops/
```

## 🔍 Troubleshooting

### Common Issues

**Docker Connection Failed**
```bash
# Check Docker daemon status
docker version

# Restart Docker Desktop
# On macOS: Docker Desktop -> Restart
# On Linux: sudo systemctl restart docker

# Run OrcaOps diagnostics
orcaops doctor
```

**Container Build Failures**
```bash
# Check Docker images
docker images

# Clean build cache
docker system prune -f

# Rebuild with no cache
orcaops build --no-cache
```

**Permission Issues**
```bash
# Add user to docker group (Linux)
sudo usermod -aG docker $USER

# Logout and login again
```

### Debug Mode

Enable verbose logging for detailed diagnostics:

```bash
# Set debug environment variable
export ORCAOPS_DEBUG=1

# Run commands with detailed output
orcaops up --verbose
```

## 🤝 Contributing

We welcome contributions! Here's how to get started:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes** and add tests
4. **Run tests**: `pytest`
5. **Commit your changes**: `git commit -am 'Add some feature'`
6. **Push to the branch**: `git push origin feature/your-feature-name`
7. **Submit a Pull Request**

### Development Guidelines

- Follow PEP 8 style guidelines
- Add tests for new functionality
- Update documentation for API changes
- Use meaningful commit messages
- Ensure all tests pass before submitting PR

## 📚 Use Cases

### DevOps Automation
- Automated testing in isolated environments
- CI/CD pipeline integration
- Infrastructure provisioning and testing

### Development Workflows
- Local development environment management
- Multi-service application testing
- Database and service mocking

### Educational Purposes
- Container technology learning
- Docker best practices demonstration
- DevOps tooling exploration

## 🛣️ Roadmap

- [ ] **Kubernetes Integration**: Extend beyond Docker to K8s orchestration
- [ ] **Web Dashboard**: Browser-based management interface
- [ ] **Plugin System**: Extensible architecture for custom integrations
- [ ] **Advanced Networking**: Custom network configurations and service discovery
- [ ] **Resource Monitoring**: Real-time performance metrics and alerts
- [ ] **Multi-Host Support**: Manage containers across multiple Docker hosts

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Docker Community**: For the foundational container technology
- **Typer & Rich**: For excellent CLI development libraries
- **Python Docker SDK**: For comprehensive Docker API integration

---

<div align="center">

**[⭐ Star this repo](https://github.com/treksavvysky/OrcaOps)** if you find OrcaOps helpful!

Made with ❤️ for the DevOps community

</div>
