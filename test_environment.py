#!/usr/bin/env python3
"""
Simple test to check if Docker is available and test basic imports.
"""

import sys
import os
from pathlib import Path

def test_docker_availability():
    """Test if Docker is available."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        print("✅ Docker is available and responsive")
        return True
    except Exception as e:
        print(f"❌ Docker not available: {e}")
        return False

def test_imports():
    """Test if we can import our modules."""
    try:
        from orcaops.docker_manager import DockerManager, BuildResult
        from orcaops import logger
        print("✅ Successfully imported OrcaOps modules")
        return True
    except ImportError as e:
        print(f"❌ Failed to import OrcaOps modules: {e}")
        return False

def main():
    """Main test function."""
    print("🔍 Running OrcaOps environment tests...")
    print()
    
    # Test imports first
    if not test_imports():
        return 1
    
    # Test Docker availability
    if not test_docker_availability():
        print("⚠️  Docker not available - skipping Docker build test")
        print("But the import test passed, so the code structure is correct!")
        return 0
    
    # If both tests pass, we could proceed with actual Docker build
    print("🎉 All tests passed! Ready for Docker operations.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
