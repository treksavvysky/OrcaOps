#!/usr/bin/env python3
"""
Simplified sandbox template system for OrcaOps
"""

import os
import yaml
from typing import Dict, List, Optional
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

class SandboxTemplates:
    """Sandbox template management system"""
    
    @staticmethod
    def get_templates() -> Dict[str, Dict]:
        """Get all available sandbox templates"""
        return {
            "web-dev": {
                "name": "Web Development Stack",
                "description": "Full-stack web development with nginx, node, and postgres",
                "category": "Development",
                "services": {
                    "nginx": {
                        "image": "nginx:alpine",
                        "ports": ["8080:80"],
                        "volumes": ["./html:/usr/share/nginx/html:ro"]
                    },
                    "frontend": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./frontend:/app"],
                        "command": "npm run dev",
                        "ports": ["3000:3000"],
                        "environment": [
                            "NODE_ENV=development",
                            "API_URL=http://backend:5000"
                        ]
                    },
                    "postgres": {
                        "image": "postgres:15-alpine",
                        "environment": [
                            "POSTGRES_DB=devdb",
                            "POSTGRES_USER=dev", 
                            "POSTGRES_PASSWORD=devpass"
                        ],
                        "ports": ["5432:5432"],
                        "volumes": ["postgres_data:/var/lib/postgresql/data"]
                    }
                },
                "volumes": {
                    "postgres_data": {}
                }
            },
            
            "python-ml": {
                "name": "Python Machine Learning",
                "description": "Python ML environment with Jupyter and data tools",
                "category": "Data Science",
                "services": {
                    "jupyter": {
                        "image": "jupyter/tensorflow-notebook:latest",
                        "ports": ["8888:8888"],
                        "volumes": [
                            "./notebooks:/home/jovyan/work",
                            "./data:/home/jovyan/data"
                        ],
                        "environment": [
                            "JUPYTER_ENABLE_LAB=yes",
                            "JUPYTER_TOKEN=orcaops"
                        ]
                    }
                }
            },
            
            "api-testing": {
                "name": "API Testing Environment", 
                "description": "API testing setup with databases",
                "category": "Testing",
                "services": {
                    "api": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./api:/app"],
                        "command": "npm start",
                        "ports": ["3000:3000"],
                        "environment": [
                            "NODE_ENV=test"
                        ]
                    },
                    "redis": {
                        "image": "redis:alpine",
                        "ports": ["6379:6379"]
                    },
                    "postgres": {
                        "image": "postgres:15-alpine",
                        "environment": [
                            "POSTGRES_DB=testdb",
                            "POSTGRES_USER=test",
                            "POSTGRES_PASSWORD=testpass"
                        ],
                        "ports": ["5432:5432"]
                    }
                }
            }
        }
    
    @staticmethod
    def create_template_files(template_name: str, output_dir: Path, custom_name: str = None):
        """Create template files and directory structure"""
        templates = SandboxTemplates.get_templates()
        
        if template_name not in templates:
            available = ", ".join(templates.keys())
            raise ValueError(f"Template '{template_name}' not found. Available: {available}")
        
        template = templates[template_name]
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create docker-compose.yml
        compose_content = SandboxTemplates._generate_compose_file(template)
        (output_dir / "docker-compose.yml").write_text(compose_content)
        
        # Create .env file
        env_content = SandboxTemplates._generate_env_file(template_name, template, custom_name)
        (output_dir / ".env").write_text(env_content)
        
        # Create README.md
        readme_content = SandboxTemplates._generate_readme(template_name, template, custom_name)
        (output_dir / "README.md").write_text(readme_content)
        
        # Create Makefile for easy management
        makefile_content = SandboxTemplates._generate_makefile(template_name, custom_name)
        (output_dir / "Makefile").write_text(makefile_content)
        
        # Create sample directories
        SandboxTemplates._create_sample_files(template_name, template, output_dir)
    
    @staticmethod
    def _generate_compose_file(template: Dict) -> str:
        """Generate docker-compose.yml content"""
        compose = {
            "version": "3.8",
            "services": template["services"]
        }
        
        # Add volumes if they exist
        if "volumes" in template:
            compose["volumes"] = template["volumes"]
        
        return yaml.dump(compose, default_flow_style=False, sort_keys=False)
    
    @staticmethod
    def _generate_env_file(template_name: str, template: Dict, custom_name: str = None) -> str:
        """Generate .env file content"""
        project_name = custom_name or f"orcaops-{template_name}"
        
        env_vars = [
            "# OrcaOps Sandbox Environment Variables",
            f"COMPOSE_PROJECT_NAME={project_name}",
            f"SANDBOX_NAME={template['name']}",
            f"SANDBOX_CATEGORY={template.get('category', 'General')}",
            "",
            "# Custom environment variables",
            "# Add your project-specific variables below",
            "",
        ]
        
        return "\n".join(env_vars)
    
    @staticmethod
    def _generate_readme(template_name: str, template: Dict, custom_name: str = None) -> str:
        """Generate README.md content"""
        project_name = custom_name or f"orcaops-{template_name}"
        
        services_list = "\n".join([
            f"- **{name}**: {config.get('image', 'Custom')} - "
            f"Port {config.get('ports', ['Not exposed'])[0] if config.get('ports') else 'Not exposed'}"
            for name, config in template['services'].items()
        ])
        
        return f"""# {template['name']} - {project_name}

{template['description']}

## Services

{services_list}

## Quick Start

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## Using Make Commands
```bash
# Start services
make start

# View status
make status

# Stop services
make stop
```
"""

    @staticmethod
    def _generate_makefile(template_name: str, custom_name: str = None) -> str:
        """Generate Makefile for easy management"""
        project_name = custom_name or f"orcaops-{template_name}"
        
        return f"""# OrcaOps {template_name} Makefile
# Project: {project_name}

.PHONY: start stop restart status logs clean help

help:
\t@echo "Available commands:"
\t@echo "  start    - Start all services"
\t@echo "  stop     - Stop all services"
\t@echo "  status   - Show service status"
\t@echo "  clean    - Stop and remove all containers"

start:
\t@echo "🚀 Starting {project_name} services..."
\tdocker-compose up -d

stop:
\t@echo "🛑 Stopping {project_name} services..."
\tdocker-compose stop

status:
\t@echo "📊 Service Status:"
\tdocker-compose ps

clean:
\t@echo "🧹 Cleaning up {project_name}..."
\tdocker-compose down -v --remove-orphans
"""
    
    @staticmethod
    def _create_sample_files(template_name: str, template: Dict, output_dir: Path):
        """Create sample files and directory structure"""
        
        if template_name == "web-dev":
            # Create frontend structure
            frontend_dir = output_dir / "frontend"
            frontend_dir.mkdir(exist_ok=True)
            
            (frontend_dir / "package.json").write_text("""{
  "name": "orcaops-frontend",
  "version": "1.0.0",
  "scripts": {
    "dev": "echo 'Frontend development server'",
    "start": "echo 'Starting frontend'"
  }
}""")
            
            # Create HTML directory
            html_dir = output_dir / "html"
            html_dir.mkdir(exist_ok=True)
            (html_dir / "index.html").write_text("""<!DOCTYPE html>
<html>
<head>
    <title>OrcaOps Web Development</title>
</head>
<body>
    <h1>🐋 Welcome to OrcaOps Web Development Sandbox</h1>
    <p>Your development environment is ready!</p>
</body>
</html>""")
        
        elif template_name == "python-ml":
            # Create directories
            for dir_name in ["notebooks", "data"]:
                dir_path = output_dir / dir_name
                dir_path.mkdir(exist_ok=True)
                
                if dir_name == "notebooks":
                    (dir_path / "welcome.ipynb").write_text("""{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# 🐋 Welcome to OrcaOps ML Sandbox\\n",
    "\\n",
    "Your machine learning environment is ready!\\n",
    "\\n",
    "Access Jupyter Lab at: http://localhost:8888 (token: orcaops)"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python", 
   "name": "python3"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}""")
        
        elif template_name == "api-testing":
            # Create API structure
            api_dir = output_dir / "api"
            api_dir.mkdir(exist_ok=True)
            
            (api_dir / "package.json").write_text("""{
  "name": "orcaops-api-testing",
  "version": "1.0.0",
  "scripts": {
    "start": "echo 'Starting API server'",
    "test": "echo 'Running API tests'"
  }
}""")

class TemplateManager:
    """Manager for template operations and CLI integration"""
    
    @staticmethod
    def list_templates_table() -> Table:
        """Create a formatted table of available templates"""
        templates = SandboxTemplates.get_templates()
        
        table = Table(title="🏗️ Available Sandbox Templates", show_header=True, header_style="bold magenta")
        table.add_column("Template", style="cyan", min_width=15)
        table.add_column("Name", style="blue", min_width=25)
        table.add_column("Category", style="green", min_width=12)
        table.add_column("Services", style="yellow")
        table.add_column("Description", style="dim")
        
        for template_id, template_info in templates.items():
            services = ", ".join(template_info["services"].keys())
            table.add_row(
                template_id,
                template_info["name"],
                template_info.get("category", "General"),
                services,
                template_info["description"]
            )
        
        return table
    
    @staticmethod
    def create_sandbox_from_template(template_name: str, project_name: str, output_dir: str) -> bool:
        """Create a new sandbox from template"""
        try:
            output_path = Path(output_dir)
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                
                task = progress.add_task(f"Creating {template_name} sandbox...", total=None)
                
                # Create template files
                SandboxTemplates.create_template_files(template_name, output_path, project_name)
                
                progress.update(task, description=f"✅ {template_name} sandbox created successfully!")
            
            return True
            
        except Exception as e:
            console.print(f"❌ [red]Error creating sandbox: {e}[/red]")
            return False
    
    @staticmethod
    def get_template_info(template_name: str) -> Optional[Dict]:
        """Get detailed information about a specific template"""
        templates = SandboxTemplates.get_templates()
        return templates.get(template_name)
    
    @staticmethod
    def validate_template_name(template_name: str) -> bool:
        """Validate if template name exists"""
        templates = SandboxTemplates.get_templates()
        return template_name in templates
