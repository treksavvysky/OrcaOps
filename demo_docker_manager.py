#!/usr/bin/env python3
"""
Demonstration script showing how to use OrcaOps DockerManager.
This script shows the proper way to import and use the DockerManager class.
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path so we can import orcaops
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def demonstrate_docker_manager():
    """Demonstrate DockerManager usage."""
    
    print("🐋 OrcaOps DockerManager Demonstration")
    print("=" * 50)
    
    # Test import
    try:
        from orcaops.docker_manager import DockerManager, BuildResult
        from orcaops import logger
        print("✅ Successfully imported DockerManager and dependencies")
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    
    print(f"✅ Found MinimalDockerfile: {os.path.exists('tests/MinimalDockerfile')}")
    
    # Show the Dockerfile content
    if os.path.exists('tests/MinimalDockerfile'):
        print("\\n📄 MinimalDockerfile contents:")
        with open('tests/MinimalDockerfile', 'r') as f:
            for i, line in enumerate(f, 1):
                print(f"    {i}: {line.rstrip()}")
    
    print("\\n🏗️  How to use DockerManager:")
    print("""
    # Initialize the manager
    docker_manager = DockerManager()
    
    # Build an image
    result = docker_manager.build(
        dockerfile_path="tests/MinimalDockerfile",
        image_name="orcaops-test",
        version="1.0.0",
        build_context=".",            # Build from project root
        push=False,                   # Don't push to registry
        latest_tag=True              # Also tag as 'latest'
    )
    
    # The result contains:
    # - result.image_id: Docker image ID
    # - result.tags: List of applied tags
    # - result.size_mb: Image size in MB
    # - result.logs: Build logs (optional)
    """)
    
    print("\\n🎯 Expected behavior:")
    print("1. Validates Dockerfile exists and is in build context")
    print("2. Determines version (uses provided or falls back to package.__version__)")
    print("3. Creates semantic version tags (1.0.0 format)")
    print("4. Builds the Docker image using Docker API")
    print("5. Optionally tags as 'latest'")
    print("6. Returns BuildResult with image details")
    print("7. Can optionally push to configured registry")
    
    print("\\n✨ This would create tags:")
    print("   - orcaops-test:1.0.0")
    print("   - orcaops-test:latest")
    
    return True

def show_project_structure():
    """Show the relevant project structure."""
    print("\\n📁 Relevant Project Structure:")
    print("OrcaOps/")
    print("├── orcaops/")
    print("│   ├── __init__.py          # Logger setup")
    print("│   ├── docker_manager.py    # Main DockerManager class")
    print("│   └── cli.py              # Command-line interface")
    print("├── tests/")
    print("│   ├── MinimalDockerfile    # Simple test Dockerfile")
    print("│   └── test_*.py           # Test files")
    print("├── pyproject.toml          # Dependencies: docker, packaging")
    print("└── README.md               # Project documentation")

def main():
    """Main demonstration function."""
    success = demonstrate_docker_manager()
    show_project_structure()
    
    print("\\n" + "=" * 50)
    if success:
        print("🎉 Demonstration complete!")
        print("\\nTo actually run the build (when Docker is available):")
        print("   python3 test_docker_build.py")
        return 0
    else:
        print("❌ Demonstration failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
