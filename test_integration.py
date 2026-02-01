#!/usr/bin/env python3
"""
Integration test for OrcaOps FastAPI + CLI functionality

This script tests both the CLI and API interfaces to ensure they work together.
"""

import time
import requests
import subprocess
import signal
import os
import sys


def test_cli_functionality():
    """Test basic CLI functionality"""
    print("🔧 Testing CLI functionality...")
    
    try:
        # Test orcaops doctor command
        result = subprocess.run(["./.venv/bin/orcaops", "doctor"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ CLI: orcaops doctor - PASSED")
        else:
            print(f"❌ CLI: orcaops doctor - FAILED: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ CLI test failed: {e}")
        return False
    
    return True


def test_api_functionality():
    """Test FastAPI functionality"""
    print("🌐 Testing API functionality...")
    
    # Start API server in background
    try:
        api_process = subprocess.Popen([
            "./.venv/bin/python", "run_api.py", 
            "--host", "127.0.0.1", "--port", "8081"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server to start
        time.sleep(3)
        
        # Test API endpoints
        base_url = "http://127.0.0.1:8081"
        
        # Test root endpoint
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            print("✅ API: GET / - PASSED")
        else:
            print(f"❌ API: GET / - FAILED: {response.status_code}")
            return False
            
        # Test containers endpoint
        response = requests.get(f"{base_url}/orcaops/ps", timeout=5)
        if response.status_code == 200:
            print("✅ API: GET /orcaops/ps - PASSED")
        else:
            print(f"❌ API: GET /orcaops/ps - FAILED: {response.status_code}")
            return False
            
        # Test templates endpoint  
        response = requests.get(f"{base_url}/orcaops/templates", timeout=5)
        if response.status_code == 200:
            print("✅ API: GET /orcaops/templates - PASSED")
        else:
            print(f"❌ API: GET /orcaops/templates - FAILED: {response.status_code}")
            return False
            
        return True
        
    except requests.RequestException as e:
        print(f"❌ API test failed: {e}")
        return False
    except Exception as e:
        print(f"❌ API test error: {e}")
        return False
    finally:
        # Clean up API process
        try:
            api_process.terminate()
            api_process.wait(timeout=5)
        except Exception:
            try:
                api_process.kill()
            except Exception:
                pass


def main():
    """Run integration tests"""
    print("🧪 OrcaOps Integration Test Suite")
    print("="*50)
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Test CLI
    cli_passed = test_cli_functionality()
    
    # Test API
    api_passed = test_api_functionality()
    
    # Results
    print("\n📊 Test Results:")
    print(f"CLI Tests: {'✅ PASSED' if cli_passed else '❌ FAILED'}")
    print(f"API Tests: {'✅ PASSED' if api_passed else '❌ FAILED'}")
    
    if cli_passed and api_passed:
        print("\n🎉 All tests passed! OrcaOps integration is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please check the error messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
