# Web Development Stack - test-site

Full-stack web development with nginx, node, and postgres

## Services

- **nginx**: nginx:alpine - Port 8080:80
- **frontend**: node:18-alpine - Port 3000:3000
- **postgres**: postgres:15-alpine - Port 5432:5432

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
