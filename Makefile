SHELL   := /bin/bash
.DEFAULT_GOAL := help

VENV    := .venv
PYTEST  := $(VENV)/bin/pytest
RUFF    := $(VENV)/bin/ruff

# Sentinel: rebuild only when requirements files change
$(VENV)/.installed: requirements.txt requirements-dev.txt
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements.txt -r requirements-dev.txt
	@touch $@

# ==============================================================================
# Help
# ==============================================================================

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ==============================================================================
# Quickstart
# ==============================================================================

.PHONY: quickstart
quickstart: ## First-time setup: create .env, build images, start services, seed data
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo ""; \
	  echo "  .env created from .env.example."; \
	  echo "  Set ANTHROPIC_API_KEY in .env, then re-run: make quickstart"; \
	  echo ""; \
	  exit 1; \
	fi
	@if grep -q 'sk-ant-\.\.\.' .env 2>/dev/null; then \
	  echo "  ANTHROPIC_API_KEY still has the placeholder value."; \
	  echo "  Edit .env and set a real key, then re-run: make quickstart"; \
	  exit 1; \
	fi
	docker compose build
	docker compose up -d
	@echo "Waiting 45 s for services to become healthy…"
	@sleep 45
	docker compose exec app python scripts/seed_demo_data.py
	@echo ""
	@echo "  Ready — open http://localhost:3000"

.PHONY: build
build: ## Build (or rebuild) all Docker images
	docker compose build

.PHONY: up
up: ## Start services (images must already be built)
	docker compose up -d

.PHONY: seed
seed: ## Seed the Chroma knowledge base (run once after first start)
	docker compose exec app python scripts/seed_demo_data.py

.PHONY: reset
reset: ## Wipe all data, restart services, and re-seed (clean demo state)
	bash scripts/reset_demo.sh

# ==============================================================================
# Test
# ==============================================================================

.PHONY: test
test: $(VENV)/.installed ## Run all tests (unit + integration)
	$(PYTEST) tests/ -q

.PHONY: test-unit
test-unit: $(VENV)/.installed ## Run unit tests only
	$(PYTEST) tests/unit/ -q

.PHONY: test-integration
test-integration: $(VENV)/.installed ## Run integration tests only
	$(PYTEST) tests/integration/ -q

.PHONY: lint
lint: $(VENV)/.installed ## Lint and format-check with ruff
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/

# ==============================================================================
# Shutdown
# ==============================================================================

.PHONY: down
down: ## Stop and remove all containers
	docker compose down

.PHONY: stop
stop: ## Pause containers without removing them (resume with: make up)
	docker compose stop

.PHONY: clean
clean: ## Remove containers and delete all persisted data (chroma + sqlite)
	docker compose down
	rm -rf data/chroma/* data/sqlite/*

# ==============================================================================
# Utility
# ==============================================================================

.PHONY: logs
logs: ## Tail logs from all services
	docker compose logs -f

.PHONY: health
health: ## Print all service health statuses
	@curl -s http://localhost:8000/health | python3 -m json.tool
