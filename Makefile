.DEFAULT_GOAL := help

PYTHON ?= 3.11
HOST ?= 127.0.0.1
PORT ?= 8000
JUPYTER_PORT ?= 8888
DATASET ?= sample
MODEL_NONFRAUD_SAMPLE ?= 5000
MODEL_SEED ?= 20260727
MODEL_FIXED_FPR ?= 0.01
TRAIN_NONFRAUD_PER_TYPE ?= 100000
T4_EXPERIMENT ?= E4
T4_FEATURE_SET ?= pit

help: ## Show implemented targets and their purpose
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked core + development dependencies and hooks
	uv sync --frozen --group dev
	uv run pre-commit install

doctor: ## Inspect Python, Docker, resources, ports, Delta and credentials
	uv run pit doctor

lab: ## Start JupyterLab locally with the project kernel
	uv run --group dev jupyter lab --ip=$(HOST) --port=$(JUPYTER_PORT) --no-browser

lab-training: ## Start JupyterLab with development and model-training dependencies
	uv run --group dev --group training jupyter lab --ip=$(HOST) --port=$(JUPYTER_PORT) --no-browser

lab-container: ## Start the isolated JupyterLab Compose profile
	docker compose --profile lab up --build jupyter

data-sample: ## Materialize and validate the committed synthetic temporal oracle
	uv run pit data sample

data-snapshot: ## Freeze the PaySim raw file identity and write its manifest
	uv run pit data snapshot --dataset paysim

profile: data-sample ## Generate the decision-oriented profile for DATASET
	uv run pit data profile --dataset $(DATASET)

build-lakehouse: test-temporal ## Build versioned Bronze/Silver Delta tables for the verified dataset
	uv run pit data build-lakehouse --dataset $(DATASET)

lakehouse-history: ## Inspect local Bronze/Silver Delta history for DATASET
	uv run pit data lakehouse-history --dataset $(DATASET)

build-fixture: ## Extract and score a small real-Silver PaySim temporal fixture
	uv run pit data build-fixture --dataset paysim

features: ## Inspect the frozen PaySim FeatureSpec v2 and checksum
	uv run pit features show --dataset paysim

gold: ## Build Gold pre-decision and post-event tables into staging
	uv run pit features build-gold --start $(START) --end $(END)

promote-gold: ## Promote a staged Gold run into the committed tables
	uv run pit features promote-gold --run-id $(RUN_ID)

test-temporal: data-sample ## Run exhaustive point-in-time correctness tests
	uv run pytest -q -m temporal tests/temporal

test-unit: ## Run fast non-temporal unit tests
	uv run pytest -q tests/unit

test-lakehouse: data-sample ## Run fixture Delta snapshot, schema, quality, and time-travel tests
	uv run pytest -q tests/integration

test-t3-smoke: ## Run the T3 backfill seam smoke lane on an isolated fixture
	UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/integration/test_gold_offline_features.py::test_t3_smoke_backfill_rerun_and_late_arrival_guard -q

test-t4-dataset: test-t3-smoke ## Run the T4 Gold-to-training dataset fixture lane
	UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/integration/test_gold_offline_features.py::test_t4_gold_to_training_dataset_fixture -q

train-gold-candidate: ## Train one E1/E4 candidate from committed Gold into local MLflow
	UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python scripts/run_t4_training.py --experiment $(T4_EXPERIMENT) --feature-set $(T4_FEATURE_SET)

test-notebooks: data-sample ## Execute all Sprint 1 notebooks in memory
	uv run --group dev pit notebooks verify

model-spike: ## Run the standalone PaySim LightGBM E1-E4 candidate matrix
	uv run --group training pit model spike --dataset paysim \
		--nonfraud-sample-per-group $(MODEL_NONFRAUD_SAMPLE) \
		--seed $(MODEL_SEED) \
		--fixed-fpr $(MODEL_FIXED_FPR)

train: ## Train locked E1/E4 baselines from exact PaySim Silver Delta versions
	uv run --group training pit model train --dataset paysim \
		--train-nonfraud-sample-per-type $(TRAIN_NONFRAUD_PER_TYPE) \
		--seed $(MODEL_SEED) \
		--fixed-fpr $(MODEL_FIXED_FPR)

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

.PHONY: help bootstrap doctor lab lab-training lab-container data-sample data-snapshot profile build-lakehouse lakehouse-history build-fixture features gold promote-gold test-temporal test-unit test-lakehouse test-t3-smoke test-t4-dataset train-gold-candidate test-notebooks model-spike train test lint format check changelog-check lock up-core status logs down
