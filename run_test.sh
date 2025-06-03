#!/bin/bash
cd /projects/OrcaOps
echo "Starting OrcaOps DockerManager Test..."
echo "Current directory: $(pwd)"
echo "Python version: $(python --version)"
echo "Running test script..."
echo "=========================="
uv run python test_docker_manager.py
