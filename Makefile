# Makefile for FAB - Firewall Access Bot

# Variables
IMAGE_NAME := fab-bot
CONTAINER_NAME := fab-container
PORT := 8080

# Default target
.DEFAULT_GOAL := help

# Docker commands
.PHONY: build
build: ## Build Docker image
	docker build -t $(IMAGE_NAME) .

.PHONY: start
start: build ## Build and start container
	@docker stop $(CONTAINER_NAME) 2>/dev/null || true
	@docker rm $(CONTAINER_NAME) 2>/dev/null || true
	@if [ -f .env ]; then \
		docker run -d --name $(CONTAINER_NAME) -p $(PORT):8080 -v fab-data:/app/data --env-file .env $(IMAGE_NAME); \
		echo "✅ Container started with .env configuration"; \
	else \
		docker run -d --name $(CONTAINER_NAME) -p $(PORT):8080 -v fab-data:/app/data -e MQTT_ENABLED=false $(IMAGE_NAME); \
		echo "✅ Container started with default configuration"; \
	fi

.PHONY: stop
stop: ## Stop container
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

.PHONY: restart
restart: stop start ## Restart container

.PHONY: logs
logs: ## View container logs
	docker logs $(CONTAINER_NAME)

.PHONY: status
status: ## Show container status
	@docker ps -a --filter name=$(CONTAINER_NAME) --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"


# Environment management
.PHONY: env-example
env-example: ## Create .env from template
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ .env created. Edit with your credentials."; \
	else \
		echo "⚠️  .env already exists"; \
	fi

.PHONY: env-check
env-check: ## Check .env status
	@if [ -f .env ]; then \
		echo "✅ .env exists"; \
		grep -E "^[A-Z_]+" .env | head -5; \
	else \
		echo "❌ .env not found. Run 'make env-example'"; \
	fi

# Help
.PHONY: help
help: ## Show available commands
	@echo "FAB - Firewall Access Bot (Docker-only)"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

test: ## Run comprehensive test suite
	@echo "🧪 Running comprehensive test suite..."
	@./run_tests.sh

test-quick: ## Quick syntax and import check  
	@echo "⚡ Running quick tests..."
	@python3 test_suite.py

test-docker: ## Test in Docker environment
	@echo "🐳 Testing in Docker environment..."
	@docker build -t fab-test .
	@docker run --rm -e TELEGRAM_BOT_TOKEN=test_token -e ADMIN_TELEGRAM_IDS=123 -e SITE_URL=http://test fab-test python3 test_suite.py
