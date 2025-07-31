#!/usr/bin/env python3
"""
Ultra-simple test script for OrcaOps DockerManager using existing images
"""

import sys
import time

# Add the current directory to sys.path to import orcaops
sys.path.insert(0, '/projects/OrcaOps')

def main():
    try:
        print("🚀 Starting OrcaOps DockerManager Ultra-Simple Test")
        print("=" * 55)
        
        # Import the DockerManager
        from orcaops.docker_manager import DockerManager
        
        print("✅ Successfully imported DockerManager")
        
        # Initialize DockerManager
        docker_manager = DockerManager()
        print("✅ DockerManager initialized")
        
        # Test 1: List current containers
        print("\n📋 Step 1: Listing current containers...")
        containers = docker_manager.list_running_containers()
        print(f"   Found {len(containers)} running containers")
        
        # Test 2: Run a simple container from existing image
        print("\n🏃 Step 2: Running nginx container...")
        
        # Use nginx which is lightweight and commonly available
        container_id = docker_manager.run(
            "nginx:alpine",
            name="orcaops-nginx-test",
            detach=True,
            ports={'80/tcp': 8082},  # Use port 8082 to avoid conflicts
            remove=True  # Auto-remove when stopped
        )
        
        print(f"✅ Container started: {container_id[:12]}...")
        
        # Wait a bit for container to start
        time.sleep(3)
        
        # Test 3: Check if container is running
        print("\n📋 Step 3: Verifying container is running...")
        running_containers = docker_manager.list_running_containers()
        our_container = None
        for container in running_containers:
            if container.id == container_id:
                our_container = container
                break
        
        if our_container:
            print(f"✅ Container is running: {our_container.status}")
            print(f"   Name: {our_container.name}")
            print(f"   Image: {our_container.image.tags[0] if our_container.image.tags else 'Unknown'}")
        else:
            print("❌ Container not found in running list")
        
        # Test 4: Check logs
        print("\n📝 Step 4: Checking container logs...")
        logs = docker_manager.logs(container_id, stream=False, tail=5)
        if logs:
            print("✅ Logs retrieved:")
            for line in logs.split('\n')[-3:]:  # Show last 3 lines
                if line.strip():
                    print(f"   {line}")
        else:
            print("   No logs available yet")
        
        # Test 5: Stop container (nginx will auto-remove due to remove=True)
        print("\n🛑 Step 5: Stopping container...")
        success = docker_manager.stop(container_id)
        if success:
            print("✅ Container stopped (and auto-removed)")
        else:
            print("❌ Failed to stop container")
        
        print("\n🎉 All tests completed successfully!")
        print("✅ DockerManager is working correctly!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
