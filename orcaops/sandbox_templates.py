#!/usr/bin/env python3
"""
Complete sandbox template system for OrcaOps
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
            "api-testing": {
                "name": "API Testing Environment",
                "description": "Complete API testing setup with databases and monitoring",
                "category": "Testing",
                "services": {
                    "grafana": {
                        "image": "grafana/grafana:latest",
                        "ports": ["3001:3000"],
                        "environment": [
                            "GF_SECURITY_ADMIN_PASSWORD=admin"
                        ],
                        "volumes": ["grafana_data:/var/lib/grafana"]
                    }
                },
                "volumes": {
                    "redis_data": {},
                    "test_db": {},
                    "grafana_data": {}
                }
            },
            
            "microservices": {
                "name": "Microservices Architecture",
                "description": "Multi-service architecture with API gateway and service discovery",
                "category": "Architecture",
                "services": {
                    "gateway": {
                        "image": "nginx:alpine",
                        "ports": ["8080:80"],
                        "volumes": ["./nginx.conf:/etc/nginx/nginx.conf:ro"],
                        "depends_on": ["auth-service", "user-service", "order-service"]
                    },
                    "auth-service": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./auth-service:/app"],
                        "ports": ["3001:3000"],
                        "environment": [
                            "SERVICE_NAME=auth",
                            "PORT=3000",
                            "JWT_SECRET=your-secret-key",
                            "DATABASE_URL=postgresql://auth:authpass@postgres:5432/authdb"
                        ],
                        "depends_on": ["postgres", "redis"]
                    },
                    "user-service": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./user-service:/app"],
                        "ports": ["3002:3000"],
                        "environment": [
                            "SERVICE_NAME=user",
                            "PORT=3000",
                            "DATABASE_URL=postgresql://user:userpass@postgres:5432/userdb"
                        ],
                        "depends_on": ["postgres"]
                    },
                    "order-service": {
                        "image": "node:18-alpine",
                        "working_dir": "/app",
                        "volumes": ["./order-service:/app"],
                        "ports": ["3003:3000"],
                        "environment": [
                            "SERVICE_NAME=order",
                            "PORT=3000",
                            "DATABASE_URL=postgresql://order:orderpass@postgres:5432/orderdb"
                        ],
                        "depends_on": ["postgres", "redis"]
                    },
                    "postgres": {
                        "image": "postgres:15-alpine",
                        "environment": [
                            "POSTGRES_DB=microservices",
                            "POSTGRES_USER=admin",
                            "POSTGRES_PASSWORD=adminpass"
                        ],
                        "ports": ["5432:5432"],
                        "volumes": ["postgres_data:/var/lib/postgresql/data"]
                    },
                    "redis": {
                        "image": "redis:alpine",
                        "ports": ["6379:6379"],
                        "volumes": ["redis_data:/data"]
                    }
                },
                "volumes": {
                    "postgres_data": {},
                    "redis_data": {}
                }
            },
            
            "wordpress": {
                "name": "WordPress Development",
                "description": "WordPress development environment with MySQL and phpMyAdmin",
                "category": "CMS",
                "services": {
                    "wordpress": {
                        "image": "wordpress:latest",
                        "ports": ["8080:80"],
                        "environment": [
                            "WORDPRESS_DB_HOST=mysql:3306",
                            "WORDPRESS_DB_USER=wordpress",
                            "WORDPRESS_DB_PASSWORD=wordpress",
                            "WORDPRESS_DB_NAME=wordpress"
                        ],
                        "volumes": ["./wp-content:/var/www/html/wp-content"],
                        "depends_on": ["mysql"]
                    },
                    "mysql": {
                        "image": "mysql:8.0",
                        "environment": [
                            "MYSQL_DATABASE=wordpress",
                            "MYSQL_USER=wordpress",
                            "MYSQL_PASSWORD=wordpress",
                            "MYSQL_ROOT_PASSWORD=rootpass"
                        ],
                        "ports": ["3306:3306"],
                        "volumes": ["mysql_data:/var/lib/mysql"]
                    },
                    "phpmyadmin": {
                        "image": "phpmyadmin/phpmyadmin:latest",
                        "ports": ["8081:80"],
                        "environment": [
                            "PMA_HOST=mysql",
                            "PMA_USER=wordpress",
                            "PMA_PASSWORD=wordpress"
                        ],
                        "depends_on": ["mysql"]
                    }
                },
                "volumes": {
                    "mysql_data": {}
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
        
        # Create directory structure and sample files
        SandboxTemplates._create_sample_files(template_name, template, output_dir)
        
        # Create OrcaOps configuration
        orcaops_config = SandboxTemplates._generate_orcaops_config(template_name, template)
        (output_dir / "orcaops.yml").write_text(orcaops_config)
    
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
        
        # Add networks if needed
        compose["networks"] = {
            "orcaops-network": {
                "driver": "bridge"
            }
        }
        
        # Add network to all services
        for service_name, service_config in compose["services"].items():
            if "networks" not in service_config:
                service_config["networks"] = ["orcaops-network"]
        
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
        
        # Add template-specific environment hints
        if template_name == "web-dev":
            env_vars.extend([
                "# Frontend Configuration",
                "# REACT_APP_API_URL=http://localhost:5000",
                "",
                "# Backend Configuration", 
                "# JWT_SECRET=your-jwt-secret",
                "# API_PORT=5000",
                ""
            ])
        elif template_name == "python-ml":
            env_vars.extend([
                "# Jupyter Configuration",
                "# JUPYTER_TOKEN=your-custom-token",
                "",
                "# MLflow Configuration",
                "# MLFLOW_TRACKING_URI=http://localhost:5000",
                ""
            ])
        
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

### Using OrcaOps Commands
```bash
# Start all services
orcaops sandbox start

# View running containers
orcaops ps

# View logs for a specific service
orcaops logs <service-name>

# Stop all services
orcaops sandbox stop

# Clean up
orcaops sandbox down
```

### Using Docker Compose Directly
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Using Make Commands
```bash
# Start services
make start

# View status
make status

# View logs
make logs

# Stop services
make stop

# Clean up everything
make clean
```

## Service URLs

After starting the services, you can access:

"""

    @staticmethod
    def _generate_makefile(template_name: str, custom_name: str = None) -> str:
        """Generate Makefile for easy management"""
        project_name = custom_name or f"orcaops-{template_name}"
        
        return f"""# OrcaOps {template_name} Makefile
# Project: {project_name}

.PHONY: start stop restart status logs clean help

# Default target
help:
\t@echo "Available commands:"
\t@echo "  start    - Start all services"
\t@echo "  stop     - Stop all services"
\t@echo "  restart  - Restart all services"
\t@echo "  status   - Show service status"
\t@echo "  logs     - Show service logs"
\t@echo "  clean    - Stop and remove all containers, networks, and volumes"
\t@echo "  help     - Show this help message"

start:
\t@echo "🚀 Starting {project_name} services..."
\tdocker-compose up -d
\t@echo "✅ Services started! Use 'make status' to check status"

stop:
\t@echo "🛑 Stopping {project_name} services..."
\tdocker-compose stop
\t@echo "✅ Services stopped"

restart:
\t@echo "🔄 Restarting {project_name} services..."
\tdocker-compose restart
\t@echo "✅ Services restarted"

status:
\t@echo "📊 Service Status:"
\tdocker-compose ps

logs:
\t@echo "📝 Service Logs (Ctrl+C to exit):"
\tdocker-compose logs -f

clean:
\t@echo "🧹 Cleaning up {project_name}..."
\tdocker-compose down -v --remove-orphans
\t@echo "✅ Cleanup complete"

# Service-specific targets
build:
\t@echo "🔨 Building services..."
\tdocker-compose build

pull:
\t@echo "📥 Pulling latest images..."
\tdocker-compose pull
"""
    
    @staticmethod
    def _generate_orcaops_config(template_name: str, template: Dict) -> str:
        """Generate OrcaOps configuration file"""
        config = {
            "sandbox": {
                "name": template["name"],
                "template": template_name,
                "category": template.get("category", "General"),
                "description": template["description"]
            },
            "services": {}
        }
        
        # Add service configurations for OrcaOps management
        for service_name, service_config in template["services"].items():
            config["services"][service_name] = {
                "image": service_config.get("image", "custom"),
                "ports": service_config.get("ports", []),
                "healthcheck": service_config.get("healthcheck", {}),
                "dependencies": service_config.get("depends_on", [])
            }
        
        return yaml.dump(config, default_flow_style=False, sort_keys=False)
    
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
    "build": "echo 'Building frontend'",
    "start": "echo 'Starting frontend'"
  },
  "dependencies": {
    "react": "^18.0.0"
  }
}""")
            
            (frontend_dir / "index.html").write_text("""<!DOCTYPE html>
<html>
<head>
    <title>OrcaOps Frontend</title>
</head>
<body>
    <h1>🐋 OrcaOps Frontend</h1>
    <p>Welcome to your web development sandbox!</p>
</body>
</html>""")
            
            # Create backend structure
            backend_dir = output_dir / "backend"
            backend_dir.mkdir(exist_ok=True)
            
            (backend_dir / "package.json").write_text("""{
  "name": "orcaops-backend",
  "version": "1.0.0",
  "scripts": {
    "dev": "echo 'Backend development server'",
    "start": "echo 'Starting backend'"
  },
  "dependencies": {
    "express": "^4.18.0"
  }
}""")
            
            # Create HTML directory
            html_dir = output_dir / "html"
            html_dir.mkdir(exist_ok=True)
            (html_dir / "index.html").write_text("""<!DOCTYPE html>
<html>
<head>
    <title>OrcaOps Nginx</title>
</head>
<body>
    <h1>🌐 Welcome to OrcaOps Web Development Sandbox</h1>
    <ul>
        <li><a href="http://localhost:3000">Frontend (React)</a></li>
        <li><a href="http://localhost:5000">Backend API</a></li>
    </ul>
</body>
</html>""")
        
        elif template_name == "python-ml":
            # Create directories
            for dir_name in ["notebooks", "data", "models", "mlruns"]:
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
    "This is your machine learning development environment!\\n",
    "\\n",
    "## Available Services\\n",
    "- **Jupyter Lab**: http://localhost:8888 (token: orcaops)\\n",
    "- **MLflow UI**: http://localhost:5000\\n",
    "- **PostgreSQL**: localhost:5432"
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
                elif dir_name == "data":
                    (dir_path / "README.md").write_text("# Data Directory\n\nPlace your datasets here.")
        
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
  },
  "dependencies": {
    "express": "^4.18.0",
    "redis": "^4.0.0",
    "pg": "^8.7.0"
  }
}""")
        
        elif template_name == "microservices":
            # Create nginx config
            (output_dir / "nginx.conf").write_text("""events {
    worker_connections 1024;
}

http {
    upstream auth {
        server auth-service:3000;
    }
    
    upstream users {
        server user-service:3000;
    }
    
    upstream orders {
        server order-service:3000;
    }
    
    server {
        listen 80;
        
        location /auth/ {
            proxy_pass http://auth/;
        }
        
        location /users/ {
            proxy_pass http://users/;
        }
        
        location /orders/ {
            proxy_pass http://orders/;
        }
        
        location / {
            return 200 '🐋 OrcaOps Microservices Gateway';
            add_header Content-Type text/plain;
        }
    }
}""")
            
            # Create service directories
            for service in ["auth-service", "user-service", "order-service"]:
                service_dir = output_dir / service
                service_dir.mkdir(exist_ok=True)
                
                (service_dir / "package.json").write_text(f"""{{
  "name": "orcaops-{service}",
  "version": "1.0.0",
  "scripts": {{
    "start": "echo 'Starting {service}'",
    "dev": "echo 'Development mode for {service}'"
  }},
  "dependencies": {{
    "express": "^4.18.0"
  }}
}}""")
        
        elif template_name == "wordpress":
            # Create wp-content directory
            wp_content_dir = output_dir / "wp-content"
            wp_content_dir.mkdir(exist_ok=True)
            
            (wp_content_dir / "README.md").write_text("""# WordPress Content Directory

This directory will contain your WordPress themes, plugins, and uploads.

## Access URLs
- **WordPress**: http://localhost:8080
- **phpMyAdmin**: http://localhost:8081

## Database Connection
- **Host**: mysql
- **Database**: wordpress
- **Username**: wordpress  
- **Password**: wordpress
""")

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
