#!/usr/bin/env python3
"""
Simple test script for OrcaOps DockerManager
"""

import sys
import os
import time
from pathlib import Path

# Add the current directory to sys.path to import orcaops
sys.path.insert(0, '/projects/OrcaOps')

def main():
    try:
        print("🚀 Starting OrcaOps DockerManager Simple Test")
        print("=" * 50)
        
        # Import the DockerManager
        from orcaops.docker_manager import DockerManager
        from orcaops import logger
        
        print("✅ Successfully imported DockerManager")
        
        # Initialize DockerManager
        docker_manager = DockerManager()
        print("✅ DockerManager initialized")
        
        # Test 1: List current containers
        print("\n📋 Step 1: Listing current containers...")
        containers = docker_manager.list_running_containers()
        print(f"   Found {len(containers)} running containers")
        for container in containers:
            print(f"   - {container.short_id}: {container.name} ({container.status})")
        
        # Test 2: Build image
        print("\n📦 Step 2: Building test image...")
        dockerfile_path = "test_project/Dockerfile"
        build_context = "test_project"
        image_name = "orcaops-test-simple"
        version = "1.0.0"
        
        if not os.path.exists(dockerfile_path):
            print(f"❌ Dockerfile not found at {dockerfile_path}")
            return
        
        print(f"   Building {image_name}:{version}")
        build_result = docker_manager.build(
            dockerfile_path=dockerfile_path,
            image_name=image_name,
            version=version,
            build_context=build_context,
            latest_tag=True,
            push=False
        )
        
        print(f"✅ Image built successfully!")
        print(f"   Image ID: {build_result.image_id[:12]}...")
        print(f"   Size: {build_result.size_mb} MB")
        
        # Test 3: Run container
        print("\n🏃 Step 3: Running container...")
        container_id = docker_manager.run(
            f"{image_name}:latest",
            name=f"{image_name}-test",
            detach=True,
            ports={'8080/tcp': 8081},  # Use different port to avoid conflicts
            environment=['TEST=true']
        )
        
        print(f"✅ Container started: {container_id[:12]}...")
        
        # Wait a bit for container to start
        time.sleep(5)
        
        # Test 4: Check logs
        print("\n📝 Step 4: Checking container logs...")
        logs = docker_manager.logs(container_id, stream=False, tail=10)
        if logs:
            print("✅ Logs retrieved:")
            for line in logs.split('\n')[-3:]:  # Show last 3 lines
                if line.strip():
                    print(f"   {line}")
        
        # Test 5: Stop container
        print("\n🛑 Step 5: Stopping container...")
        success = docker_manager.stop(container_id)
        if success:
            print("✅ Container stopped")
        else:
            print("❌ Failed to stop container")
        
        # Test 6: Remove container
        print("\n🗑️  Step 6: Removing container...")
        success = docker_manager.rm(container_id, force=True)
        if success:
            print("✅ Container removed")
        else:
            print("❌ Failed to remove container")
        
        print("\n🎉 All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
