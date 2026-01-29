# OrcaOps web-dev Makefile
# Project: test-site

.PHONY: start stop restart status logs clean help

help:
	@echo "Available commands:"
	@echo "  start    - Start all services"
	@echo "  stop     - Stop all services"
	@echo "  status   - Show service status"
	@echo "  clean    - Stop and remove all containers"

start:
	@echo "🚀 Starting test-site services..."
	docker-compose up -d

stop:
	@echo "🛑 Stopping test-site services..."
	docker-compose stop

status:
	@echo "📊 Service Status:"
	docker-compose ps

clean:
	@echo "🧹 Cleaning up test-site..."
	docker-compose down -v --remove-orphans
