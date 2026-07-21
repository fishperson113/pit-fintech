.DEFAULT_GOAL := help

PYTHON ?= 3.11
HOST ?= 127.0.0.1
PORT ?= 8000
JUPYTER_PORT ?= 8888
DATASET ?= sample

help: ## Show implemented targets and their purpose
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked core + development dependencies and hooks
	uv sync --frozen --group dev
	uv run pre-commit install

doctor: ## Inspect Python, Docker, resources, ports, Delta and credentials
	uv run pit doctor

lab: ## Start JupyterLab locally with the project kernel
	uv run --group dev jupyter lab --ip=$(HOST) --port=$(JUPYTER_PORT) --no-browser

lab-container: ## Start the isolated JupyterLab Compose profile
	docker compose --profile lab up --build jupyter

data-sample: ## Materialize and validate the committed synthetic temporal oracle
	uv run pit data sample

profile: data-sample ## Generate the decision-oriented profile for DATASET
	uv run pit data profile --dataset $(DATASET)

build-lakehouse: test-temporal ## Build versioned Bronze/Silver Delta tables for the verified dataset
	uv run pit data build-lakehouse --dataset $(DATASET)

lakehouse-history: ## Inspect local Bronze/Silver Delta commit history
	uv run pit data lakehouse-history

test-temporal: data-sample ## Run exhaustive point-in-time correctness tests
	uv run pytest -q -m temporal tests/temporal

test-unit: ## Run fast non-temporal unit tests
	uv run pytest -q tests/unit

test-lakehouse: data-sample ## Run Delta snapshot, idempotency, and time-travel tests
	uv run pytest -q tests/integration/test_sample_lakehouse.py

test-notebooks: data-sample ## Execute all Sprint 1 notebooks in memory
	uv run --group dev pit notebooks verify

test: data-sample ## Run the complete local test suite
	uv run pytest -q

lint: ## Check Python and notebook code with Ruff
	uv run ruff check src tests feature_repo notebooks scripts
	uv run ruff format --check src tests feature_repo notebooks scripts

format: ## Apply Ruff fixes and formatting
	uv run ruff check --fix src tests feature_repo notebooks scripts
	uv run ruff format src tests feature_repo notebooks scripts

check: lint test ## Run the local CI fast lane

changelog-check: ## Verify staged implementation changes include milestone audit logs
	uv run python scripts/verify_milestone_changelog.py

lock: ## Resolve and refresh the exact uv dependency lock
	uv lock

up-core: ## Start Redis and MLflow local infrastructure
	docker compose up -d redis mlflow

status: ## Show Compose service state
	docker compose ps

logs: ## Follow core service logs
	docker compose logs --tail=200 -f redis mlflow

down: ## Stop services without deleting data volumes
	docker compose down

.PHONY: help bootstrap doctor lab lab-container data-sample profile build-lakehouse lakehouse-history test-temporal test-unit test-lakehouse test-notebooks test lint format check changelog-check lock up-core status logs down
