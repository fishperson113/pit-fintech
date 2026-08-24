.DEFAULT_GOAL := help

HOST ?= 127.0.0.1
JUPYTER_PORT ?= 8888
DATASET ?= sample
MODEL_SEED ?= 20260727
MODEL_FIXED_FPR ?= 0.01
TRAIN_NONFRAUD_PER_TYPE ?= 100000
WATERMARK ?= 743
BACKFILL_MODE ?= range
BACKFILL_START ?= 1
BACKFILL_END ?= 743

help: ## Show implemented targets and their purpose
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Environment ---

bootstrap: ## Install locked core + development dependencies and hooks
	uv sync --frozen --group dev
	uv run pre-commit install

setup: ## Install every dependency group (dev, training, tracking, feast, serving) and hooks in one shot
	uv sync --frozen --all-groups
	uv run pre-commit install

doctor: ## Inspect Python, Docker, resources, ports, Delta and credentials
	uv run pit doctor

lock: ## Resolve and refresh the exact uv dependency lock
	uv lock

lab: ## Start JupyterLab locally with the project kernel
	uv run --group dev jupyter lab --ip=$(HOST) --port=$(JUPYTER_PORT) --no-browser

lab-training: ## Start JupyterLab with the development and model-training dependency groups
	uv run --group dev --group training jupyter lab --ip=$(HOST) --port=$(JUPYTER_PORT) --no-browser

# --- Data / features / model ---

data-sample: ## Materialize and validate the committed synthetic temporal oracle
	uv run pit data sample

build-lakehouse: test-temporal ## Build versioned Bronze/Silver Delta tables for the verified dataset
	uv run pit data build-lakehouse --dataset $(DATASET)

gold: ## Build Gold pre-decision and post-event tables into staging (pass START/END)
	uv run pit features build-gold --start $(START) --end $(END)

promote-gold: ## Promote a staged Gold run into the committed tables (pass RUN_ID)
	uv run pit features promote-gold --run-id $(RUN_ID)

train: ## Train locked E1/E4 baselines from exact PaySim Silver Delta versions
	uv run --group training pit model train --dataset paysim \
		--train-nonfraud-sample-per-type $(TRAIN_NONFRAUD_PER_TYPE) \
		--seed $(MODEL_SEED) \
		--fixed-fpr $(MODEL_FIXED_FPR)

# --- Serving / online store ---

serve: ## Start the FastAPI scoring service against the local Redis online store
	uv run pit serving up

worker: ## Run the pit-online-worker: consume score events and maintain the online store (ADR-010)
	uv run pit serving worker

materialize: ## Materialize Gold post-event state into the online store up to WATERMARK
	uv run pit materialize run --watermark $(WATERMARK)

backfill: ## Run atomic/idempotent Gold backfill with BACKFILL_MODE and range variables
	uv run pit backfill run --mode $(BACKFILL_MODE) --start $(BACKFILL_START) --end $(BACKFILL_END)

mlflow-ui: ## Run the MLflow server on the Windows HOST (Artifacts tab works)
	uv run mlflow server --backend-store-uri sqlite:///artifacts/mlflow/tracking.db --host 127.0.0.1 --port 5000

demo-score: ## Score one normal and one suspicious transaction against a running API
	uv run python scripts/demo_score.py

# --- Compose ops (Redis + pit-online-worker) ---

up-core: ## Start Redis and the pit-online-worker containers
	docker compose up -d redis pit-online-worker

status: ## Show Compose service state
	docker compose ps

logs: ## Follow core service logs
	docker compose logs --tail=200 -f redis pit-online-worker

down: ## Stop services without deleting data volumes
	docker compose down

# --- Quality ---

test-temporal: data-sample ## Run exhaustive point-in-time correctness tests
	uv run pytest -q -m temporal tests/temporal

test-unit: ## Run fast non-temporal unit tests
	uv run pytest -q tests/unit

test: data-sample ## Run the complete local test suite
	uv run pytest -q

lint: ## Check Python and notebook code with Ruff
	uv run ruff check src tests notebooks scripts
	uv run ruff format --check src tests notebooks scripts

format: ## Apply Ruff fixes and formatting
	uv run ruff check --fix src tests notebooks scripts
	uv run ruff format src tests notebooks scripts

check: lint test ## Run the local CI fast lane

changelog-check: ## Verify staged implementation changes include milestone audit logs
	uv run python scripts/verify_milestone_changelog.py

.PHONY: help bootstrap setup doctor lock lab lab-training data-sample build-lakehouse gold promote-gold train serve worker materialize backfill mlflow-ui demo-score up-core status logs down test-temporal test-unit test lint format check changelog-check
