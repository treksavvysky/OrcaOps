#!/usr/bin/env python3
"""
Test script to build a simple Docker container using OrcaOps DockerManager.
This script builds the MinimalDockerfile from the tests folder.
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path so we can import orcaops
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from orcaops.docker_manager import DockerManager, BuildResult
    print("✅ Successfully imported DockerManager")
except ImportError as e:
    print(f"❌ Failed to import DockerManager: {e}")
    print("Make sure you're running this from the OrcaOps project root")
    sys.exit(1)

def check_docker_availability():
    """Check if Docker is available before attempting build."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except Exception as e:
        print(f"❌ Docker not available: {e}")
        print("Please ensure Docker is installed and running.")
        return False

def main():
    """Main function to test Docker container building."""
    
    # Check Docker availability first
    if not check_docker_availability():
        print("⚠️  Skipping Docker build test - Docker not available")
        return 1
    
    # Set up paths
    dockerfile_path = "tests/MinimalDockerfile"
    build_context = "."  # Use project root as build context
    image_name = "orcaops-test"
    version = "1.0.0"
    
    print(f"🐳 Starting Docker build test...")
    print(f"   Dockerfile: {dockerfile_path}")
    print(f"   Build context: {build_context}")
    print(f"   Image name: {image_name}")
    print(f"   Version: {version}")
    print()
    
    try:
        # Initialize DockerManager
        print("🔧 Initializing DockerManager...")
        docker_manager = DockerManager()
        
        # Build the container
        print("🏗️  Building Docker image...")
        build_result = docker_manager.build(
            dockerfile_path=dockerfile_path,
            image_name=image_name,
            version=version,
            build_context=build_context,
            push=False,  # Don't push to registry
            latest_tag=True  # Also tag as 'latest'
        )
        
        # Display results
        print("\n✅ Build completed successfully!")
        print(f"   Image ID: {build_result.image_id}")
        print(f"   Tags: {', '.join(build_result.tags)}")
        print(f"   Size: {build_result.size_mb} MB")
        
        if build_result.logs:
            print(f"\n📋 Build logs (last 10 lines):")
            log_lines = build_result.logs.split('\n')
            for line in log_lines[-10:]:
                if line.strip():
                    print(f"    {line}")
        
        print(f"\n🎉 Test completed! You can run the container with:")
        print(f"   docker run --rm {image_name}:latest")
        
    except FileNotFoundError as e:
        print(f"❌ File not found: {e}")
        print("Make sure you're running this script from the OrcaOps project root")
    except Exception as e:
        print(f"❌ Build failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
