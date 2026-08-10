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
WATERMARK ?= 743
LOCUST_HOST ?= http://127.0.0.1:8000

help: ## Show implemented targets and their purpose
	@awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install locked core + development dependencies and hooks
	uv sync --frozen --group dev
	uv run pre-commit install

setup: ## Install every dependency group (dev, training, tracking, feast, serving) and hooks in one shot
	uv sync --frozen --all-groups
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

## NOTE: this lane runs with exactly the dependency groups CI installs (`uv sync --frozen
## --group dev --group training`), so calling it locally re-syncs .venv to dev + training and
## removes every other group (feast, serving, tracking). That is standard uv behavior, not a bug.
## To run the full integration lane locally with every group installed, use
## `make test-integration-full`.
test-lakehouse: data-sample ## Run fixture Delta snapshot, schema, quality, and time-travel tests
	uv run --group training pytest -q tests/integration

test-integration-full: ## Run the full integration lane locally with every dependency group installed
	UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pit data sample
	UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/integration

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

materialize: ## Materialize Gold post-event state into the online store up to WATERMARK
	uv run pit materialize run --watermark $(WATERMARK)

parity-reconcile: ## Reconcile online aggregates against the offline DuckDB reference (async, ADR-009)
	uv run pit parity reconcile

serve: ## Start the FastAPI scoring service against the local Redis online store
	uv run pit serving up

serve-otel: ## Start FastAPI scoring with OTel traces/metrics (reads PIT_OTEL_ENDPOINT from .env)
	uv run pit serving up --otel

worker: ## Run the pit-online-worker: consume score events and maintain the online store (ADR-010)
	uv run pit serving worker

worker-up: ## Start the pit-online-worker Docker container
	docker compose up -d pit-online-worker

worker-down: ## Stop the pit-online-worker container
	docker compose stop pit-online-worker

tools: ## Install hand-installed dev tools (locust + OpenTelemetry) into the current env
	uv pip install locust
	uv pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-logging

locust: ## Run the Locust web UI (http://localhost:8089) + offline/online parity harness against a running service
	uv run locust -f scripts/locust_parity.py --host $(LOCUST_HOST)

mlflow-ui: ## Run the MLflow server on the Windows HOST (Artifacts tab works); stops the container first
	@echo "Stopping the container MLflow to free port 5000..."
	docker compose stop mlflow
	uv run mlflow server --backend-store-uri sqlite:///artifacts/mlflow/tracking.db --host 127.0.0.1 --port 5000

demo: ## Run the end-to-end demo: Redis -> Gold -> materialize -> serve -> score
	uv run python scripts/run_demo_e2e.py

# --- demo-* quick commands (short, easy to remember for a live demo) ---

demo-score: ## Score one normal and one suspicious transaction against a running API
	uv run python scripts/demo_score.py

demo-bad: ## Prove invalid requests are rejected before scoring (metrics before/after)
	uv run python scripts/demo_bad_request.py

demo-metrics: ## Show the in-process /metrics counters
	uv run python scripts/demo_metrics.py

demo-medallion: ## Show grain (version/rows/cols) of the five medallion tables from Delta
	uv run python scripts/demo_medallion.py

demo-contract: ## Show the frozen PaySim FeatureSpec v2
	uv run pit features show --dataset paysim

demo-history: ## Show Delta version history for Bronze/Silver
	uv run pit data lakehouse-history --dataset paysim

demo-watermark: ## Show the online store materialization watermark
	uv run pit materialize show

demo-lineage: ## Show MLflow run lineage (required tags/metrics/artifacts) from the local sqlite
	uv run python scripts/demo_lineage.py

demo-ablation: ## Show the E1-E4 ablation table from the spike experiment (same cohort)
	uv run python scripts/demo_ablation.py

redis-up: ## Start the local Redis container
	docker compose up -d redis

redis-down: ## Stop the local Redis container
	docker compose stop redis

up-core: ## Start Redis and MLflow local infrastructure
	docker compose up -d redis mlflow

status: ## Show Compose service state
	docker compose ps

logs: ## Follow core service logs
	docker compose logs --tail=200 -f redis mlflow

down: ## Stop services without deleting data volumes
	docker compose down

.PHONY: help bootstrap setup doctor lab lab-training lab-container data-sample data-snapshot profile build-lakehouse lakehouse-history build-fixture features gold promote-gold test-temporal test-unit test-lakehouse test-integration-full test-t3-smoke test-t4-dataset train-gold-candidate test-notebooks model-spike train test lint format check changelog-check lock materialize parity-reconcile serve serve-otel worker worker-up worker-down tools locust mlflow-ui demo demo-score demo-bad demo-metrics demo-medallion demo-contract demo-history demo-watermark demo-lineage demo-ablation redis-up redis-down up-core status logs down
