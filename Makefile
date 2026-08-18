# ─────────────────────────────────────────────────────────────────────────────
# Commission Reconciliation — Makefile
# Usage: make <target>
# ─────────────────────────────────────────────────────────────────────────────

PYTHON   ?= python
UV       ?= uv
UVICORN  ?= uvicorn
PORT     ?= 8000

.PHONY: help install install-pip server server-prod legacy analyzer db-init lint clean

## show this help message
help:
	@printf '\n\033[1;36mCommission Reconciliation — available commands\033[0m\n\n'
	@awk 'BEGIN{FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[33m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\n'

## ── Dependencies ─────────────────────────────────────────────────────────────

install: ## Install project dependencies via uv (recommended)
	$(UV) sync

install-pip: ## Install project dependencies via pip
	$(PYTHON) -m pip install -r server/requirements.txt

## ── New pathway — FastAPI + Web UI ──────────────────────────────────────────

server: db-init ## Start the FastAPI dev server with hot-reload (port $(PORT))
	$(UVICORN) server.app.main:app --reload --port $(PORT)

server-prod: db-init ## Start the FastAPI server in production mode (no reload)
	$(UVICORN) server.app.main:app --port $(PORT)

## ── Legacy pathway — Tkinter GUIs ───────────────────────────────────────────

legacy: ## Launch the Tkinter reconciliation GUI (reconciliation_app_v5.py)
	$(PYTHON) scripts/reconciliation_app_v5.py

analyzer: ## Launch the Tkinter service analyser GUI (service_analyzer.py)
	$(PYTHON) scripts/service_analyzer.py

## ── Utilities ────────────────────────────────────────────────────────────────

db-init: ## Ensure the database/ directory exists
	@mkdir -p database

lint: ## Run ruff linter over the project
	$(UV) run ruff check .

clean: ## Remove all __pycache__ directories
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
