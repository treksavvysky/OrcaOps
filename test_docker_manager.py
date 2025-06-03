#!/usr/bin/env python3
"""
Comprehensive test script for OrcaOps DockerManager
Tests building, running, monitoring, and cleanup of Docker containers
"""

import sys
import os
import time
import requests
from pathlib import Path

# Add the parent directory to sys.path to import orcaops
sys.path.insert(0, str(Path(__file__).parent.parent))

from orcaops.docker_manager import DockerManager
from orcaops import logger

class DockerManagerTester:
    def __init__(self):
        """Initialize the tester with a DockerManager instance"""
        self.docker_manager = DockerManager()
        self.image_name = "orcaops-test-api"
        self.version = "1.0.0"
        self.container_id = None
        self.container_name = f"{self.image_name}-test-container"
        
    def run_full_test(self):
        """Run the complete test suite"""
        print("🚀 Starting OrcaOps DockerManager Test Suite")
        print("=" * 60)
        
        try:
            # Step 1: Build the image
            self.test_build_image()
            
            # Step 2: Check if container is already running
            self.test_list_containers()
            
            # Step 3: Run the container if not running
            self.test_run_container()
            
            # Step 4: Test the running application
            self.test_application_endpoints()
            
            # Step 5: Monitor logs
            self.test_container_logs()
            
            # Step 6: Stop the container
            self.test_stop_container()
            
            # Step 7: Remove the container
            self.test_remove_container()
            
            print("\n✅ All tests completed successfully!")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
            print(f"\n❌ Test failed: {e}")
            self.cleanup()
            sys.exit(1)
    
    def test_build_image(self):
        """Test building the Docker image"""
        print("\n📦 Step 1: Building Docker image...")
        
        dockerfile_path = "test_project/Dockerfile"
        build_context = "test_project"
        
        # Check if Dockerfile exists
        if not os.path.exists(dockerfile_path):
            raise FileNotFoundError(f"Dockerfile not found at {dockerfile_path}")
        
        print(f"   Building {self.image_name}:{self.version}")
        
        build_result = self.docker_manager.build(
            dockerfile_path=dockerfile_path,
            image_name=self.image_name,
            version=self.version,
            build_context=build_context,
            latest_tag=True,
            push=False
        )
        
        print(f"   ✅ Image built successfully!")
        print(f"   📍 Image ID: {build_result.image_id[:12]}...")
        print(f"   🏷️  Tags: {', '.join(build_result.tags)}")
        print(f"   📏 Size: {build_result.size_mb} MB")
        
        return build_result
    
    def test_list_containers(self):
        """Test listing containers to check if our test container exists"""
        print("\n📋 Step 2: Checking existing containers...")
        
        # Check running containers
        running_containers = self.docker_manager.list_running_containers()
        print(f"   Found {len(running_containers)} running containers")
        
        # Check if our test container is already running
        for container in running_containers:
            if container.name == self.container_name:
                print(f"   ⚠️  Test container already running: {container.short_id}")
                print("   Stopping existing container first...")
                self.docker_manager.stop(container.id)
                self.docker_manager.rm(container.id, force=True)
                print("   ✅ Cleaned up existing container")
                break
        else:
            print("   ✅ No conflicting containers found")
    
    def test_run_container(self):
        """Test running the container"""
        print("\n🏃 Step 3: Running the container...")
        
        # Container configuration
        container_config = {
            'name': self.container_name,
            'detach': True,
            'ports': {'8080/tcp': 8080},
            'environment': [
                'ENVIRONMENT=test',
                'API_VERSION=1.0.0',
                'DEBUG=false'
            ],
            'volumes': {
                # Create a temporary volume for logs
                f"{os.getcwd()}/test_logs": {
                    'bind': '/app/logs',
                    'mode': 'rw'
                }
            }
        }
        
        # Ensure log directory exists
        os.makedirs("test_logs", exist_ok=True)
        
        print(f"   Starting container from {self.image_name}:latest")
        print(f"   Port mapping: 8080 -> 8080")
        print(f"   Environment: {len(container_config['environment'])} variables")
        
        self.container_id = self.docker_manager.run(
            f"{self.image_name}:latest",
            **container_config
        )
        
        print(f"   ✅ Container started successfully!")
        print(f"   📍 Container ID: {self.container_id[:12]}...")
        
        # Wait for the application to start
        print("   ⏳ Waiting for application to start...")
        time.sleep(8)
        
        return self.container_id
    
    def test_application_endpoints(self):
        """Test the running application endpoints"""
        print("\n🌐 Step 4: Testing application endpoints...")
        
        base_url = "http://localhost:8080"
        
        # Test health endpoint
        try:
            print("   Testing /health endpoint...")
            response = requests.get(f"{base_url}/health", timeout=5)
            if response.status_code == 200:
                health_data = response.json()
                print(f"   ✅ Health check passed: {health_data['status']}")
                print(f"   ⏱️  Uptime: {health_data['uptime_seconds']}s")
            else:
                print(f"   ❌ Health check failed: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Health check failed: {e}")
        
        # Test system info endpoint
        try:
            print("   Testing /api/system endpoint...")
            response = requests.get(f"{base_url}/api/system", timeout=5)
            if response.status_code == 200:
                system_data = response.json()
                print(f"   ✅ System info retrieved")
                print(f"   🖥️  Hostname: {system_data['hostname']}")
                print(f"   💾 Memory usage: {system_data['memory']['percent']:.1f}%")
                print(f"   📊 CPU usage: {system_data['cpu_percent']:.1f}%")
            else:
                print(f"   ❌ System info failed: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ System info failed: {e}")
        
        # Test stress endpoint
        try:
            print("   Testing /api/stress/3 endpoint...")
            response = requests.get(f"{base_url}/api/stress/3", timeout=10)
            if response.status_code == 200:
                stress_data = response.json()
                print(f"   ✅ Stress test initiated: {stress_data['message']}")
            else:
                print(f"   ❌ Stress test failed: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Stress test failed: {e}")
        
        # Test logs endpoint
        try:
            print("   Testing /api/logs endpoint...")
            response = requests.get(f"{base_url}/api/logs", timeout=5)
            if response.status_code == 200:
                logs_data = response.json()
                print(f"   ✅ Logs retrieved: {logs_data['showing_lines']} lines")
            else:
                print(f"   ❌ Logs retrieval failed: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Logs retrieval failed: {e}")
    
    def test_container_logs(self):
        """Test fetching container logs"""
        print("\n📝 Step 5: Testing container logs...")
        
        if not self.container_id:
            print("   ❌ No container ID available")
            return
        
        print("   Fetching recent logs...")
        
        # Get logs without streaming
        logs = self.docker_manager.logs(
            self.container_id,
            stream=False,
            tail=20,
            timestamps=True
        )
        
        if logs:
            print("   ✅ Logs retrieved successfully")
            log_lines = logs.strip().split('\n')
            print(f"   📄 Showing last {min(5, len(log_lines))} lines:")
            for line in log_lines[-5:]:
                print(f"      {line}")
        else:
            print("   ⚠️  No logs available")
    
    def test_stop_container(self):
        """Test stopping the container"""
        print("\n🛑 Step 6: Stopping the container...")
        
        if not self.container_id:
            print("   ❌ No container ID available")
            return
        
        print(f"   Stopping container {self.container_id[:12]}...")
        
        success = self.docker_manager.stop(self.container_id, timeout=10)
        
        if success:
            print("   ✅ Container stopped successfully")
        else:
            print("   ❌ Failed to stop container")
        
        # Verify it's stopped
        time.sleep(2)
        containers = self.docker_manager.list_running_containers(all=True)
        for container in containers:
            if container.id == self.container_id:
                print(f"   📊 Container status: {container.status}")
                break
    
    def test_remove_container(self):
        """Test removing the container"""
        print("\n🗑️  Step 7: Removing the container...")
        
        if not self.container_id:
            print("   ❌ No container ID available")
            return
        
        print(f"   Removing container {self.container_id[:12]}...")
        
        success = self.docker_manager.rm(self.container_id, force=True)
        
        if success:
            print("   ✅ Container removed successfully")
        else:
            print("   ❌ Failed to remove container")
        
        # Cleanup local test logs
        try:
            import shutil
            if os.path.exists("test_logs"):
                shutil.rmtree("test_logs")
                print("   🧹 Cleaned up test logs directory")
        except Exception as e:
            print(f"   ⚠️  Could not clean up test logs: {e}")
    
    def cleanup(self):
        """Emergency cleanup in case of test failure"""
        print("\n🧹 Emergency cleanup...")
        
        if self.container_id:
            try:
                self.docker_manager.stop(self.container_id)
                self.docker_manager.rm(self.container_id, force=True)
                print("   ✅ Container cleaned up")
            except Exception as e:
                print(f"   ⚠️  Cleanup warning: {e}")


def main():
    """Main function to run the test suite"""
    print("OrcaOps DockerManager Test Suite")
    print("This test will build a Flask API container and test all DockerManager features")
    print()
    
    # Change to the OrcaOps directory
    os.chdir(Path(__file__).parent.parent)
    
    try:
        tester = DockerManagerTester()
        tester.run_full_test()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
