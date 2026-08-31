.PHONY: help install dev-api dev-worker test lint format typecheck seed migrate \
        docker-up docker-down docker-logs frontend-install frontend-dev frontend-build \
        frontend-test frontend-lint bench validate

VENV := .venv/bin

help:
	@echo "SentinelLLM — common developer commands"
	@echo ""
	@echo "  make install          Create .venv and install the backend (+dev deps)"
	@echo "  make migrate          Apply Alembic migrations"
	@echo "  make seed             Seed local demo data (idempotent; --force to reseed)"
	@echo "  make dev-api          Run the API with autoreload on :8000"
	@echo "  make dev-worker       Run the worker process"
	@echo "  make test             Run the backend test suite"
	@echo "  make lint             Run ruff + mypy"
	@echo "  make format           Apply ruff formatting"
	@echo "  make bench            Run the performance benchmark suite"
	@echo "  make frontend-install Install frontend dependencies"
	@echo "  make frontend-dev     Run the Next.js dev server on :3000"
	@echo "  make frontend-test    Run frontend unit tests"
	@echo "  make validate         Run the full local validation suite (backend + frontend)"
	@echo "  make docker-up        docker compose up --build (full stack + seed data)"
	@echo "  make docker-down      docker compose down -v"

install:
	uv venv .venv
	uv pip install -e ".[dev]" --python $(VENV)/python

migrate:
	$(VENV)/alembic upgrade head

seed:
	$(VENV)/python scripts/seed_demo.py

dev-api:
	$(VENV)/uvicorn sentinellm.api.main:app --reload --port 8000

dev-worker:
	$(VENV)/python -m sentinellm.worker.main

test:
	$(VENV)/pytest -q --cov=sentinellm --cov-report=term-missing

lint:
	$(VENV)/ruff check src tests scripts
	$(VENV)/mypy

format:
	$(VENV)/ruff format src tests scripts
	$(VENV)/ruff check --fix src tests scripts

bench:
	$(VENV)/python scripts/run_benchmarks.py

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-test:
	cd frontend && npm test -- --ci

frontend-lint:
	cd frontend && npm run lint

validate: lint test frontend-lint frontend-build frontend-test
	@echo "All checks passed."

docker-up:
	docker compose up --build -d
	@echo "Waiting for services..."
	@echo "Dashboard: http://localhost:3000   API: http://localhost:8000/docs"

docker-down:
	docker compose down -v

docker-logs:
	docker compose logs -f
