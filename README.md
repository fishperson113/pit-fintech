# PIT Fintech — Point-in-Time Correct Feature Platform

Local-first MLOps codebase for a fraud feature platform whose acceptance path is based on
three invariants: no future reads, offline/online parity, and reproducible backfills. The
project is a paper-inspired adaptation for one CPU machine; it does not claim to reproduce
the FeathrPO/Spark speedups from the source paper.

The repository is intentionally milestone-driven. Sprint 1 is complete: the temporal contract,
PaySim feasibility evidence, versioned Bronze/Silver path and exact-Silver E1/E4 baseline are
verified. See the [Sprint 1 completion report](docs/reports/sprint-1-completion-report.md).
Redis/MLflow infrastructure is wired for the next vertical slice. Gold staging and explicit
promotion are now represented by CLI/Make/PowerShell commands; Feast, serving, replay, and cloud
remain explicitly planned rather than represented by placeholder commands.

## Quick start

Requirements: Python 3.11, [uv](https://docs.astral.sh/uv/), and optionally Docker Desktop.

```bash
make bootstrap
make doctor
make data-sample
make test-temporal
make build-lakehouse DATASET=sample
make lab
```

Windows does not ship GNU Make by default. The checked-in PowerShell companion calls the
same Python control plane:

```powershell
.\make.ps1 bootstrap
.\make.ps1 doctor
.\make.ps1 data-sample
.\make.ps1 test-temporal
.\make.ps1 build-lakehouse
.\make.ps1 lab
```

The synthetic path requires no Kaggle token, cloud account, Redis, or MLflow server.

### Run the PaySim EDA notebooks

Download [PaySim](https://www.kaggle.com/datasets/ealaxi/paysim1) into the default raw-data
location:

```text
data/raw/paysim/PS_20174392719_1491204439457_log.csv
```

Alternatively, set `PAYSIM_CSV` in the shell or override `paysim_csv` with
`PIT_PAYSIM_CSV` in `.env`. The committed non-secret defaults live in `config.yaml`. Freeze the raw
input once before running EDA:

```bash
make data-snapshot
make profile DATASET=paysim
make lab
```

```powershell
.\make.ps1 data-snapshot
.\make.ps1 profile -Dataset paysim
.\make.ps1 test-lakehouse
.\make.ps1 build-lakehouse -Dataset paysim
.\make.ps1 lab
```

`data-snapshot` writes a machine-readable manifest under
`artifacts/datasets/paysim1/<checksum-prefix>/snapshot-manifest.json`. It does not copy or mutate
the raw CSV.

`build-lakehouse -Dataset paysim` streams the frozen CSV through DuckDB/Arrow into
`bronze.paysim_transactions`, label-free `silver.paysim_transactions`, and the separate
`silver.paysim_labels` Delta table. It publishes exact table versions and the FeatureSpec
checksum under the same snapshot artifact directory.

The notebooks do not fall back to synthetic data. Without the PaySim CSV they show setup
instructions and skip data queries.

### Run the standalone LightGBM candidate spike

The exploratory spike executes the predeclared E1–E4 matrix through reusable code and logs all
four child runs to a local SQLite-backed MLflow store with a separate local artifact directory.
It does not require Redis, Docker, or an MLflow server:

```bash
make model-spike
```

```powershell
.\make.ps1 model-spike
```

The command writes a validated manifest under
`artifacts/experiments/paysim-lightgbm-spike/<run-id>/manifest.json` and local tracking data under
`artifacts/mlflow/`. Notebook `04_model_candidate.ipynb` can review the latest result. To execute
the same reusable workflow interactively, launch `lab-training`, change `RUN_TRAINING` to
`True`, then Restart Kernel and Run All.

The spike uses a deterministic diagnostic cohort that oversamples fraud. Its metrics compare
static, leaky and PIT variants within the pinned cohort; they are not production-prevalence
model-quality claims and cannot promote a model.

### Run the locked Silver training baseline

M019 reads the exact `silver.paysim_transactions` and `silver.paysim_labels` versions in the
latest application-lakehouse manifest. It trains E1 request-only and E4 strict-PIT baselines
with identical temporal splits and model settings:

```powershell
.\make.ps1 train
```

Validation and test retain natural PaySim prevalence. Only train negatives are deterministically
bounded per transaction type for CPU/RAM feasibility. The command validates exact Silver
versions/checksums and the FeatureSpec contract, then guards only uncommitted training-component
changes. A documentation-only commit does not require rebuilding the lakehouse.

Notebook `05_silver_training_baseline.ipynb` calls the same reusable pipeline and explains how
to read lineage, split health, E1/E4 metrics and feature importance. For an intentional clean
notebook run:

```powershell
$env:PIT_NOTEBOOK_RUN_TRAINING = "1"
.\make.ps1 lab-training
```

Keep the notebook file unchanged; enabling training by environment variable preserves clean Git
lineage. See the [M019 reading guide](docs/reports/paysim-silver-training-baseline.md).

### Build and promote Gold

Gold is built into staging by default. The requested step range must cover complete `event_day`
partitions: use `[1,24]`, `[25,48]`, or the final partial-day range `[721,743]`; `[2,2]` is
rejected. Building does not promote or replace the committed Gold tables; promotion is a separate
explicit command using the staged run manifest:

```bash
make gold START=25 END=48
make promote-gold RUN_ID=<run-id-from-build-output>
```

```powershell
.\make.ps1 gold -Start 25 -End 48
.\make.ps1 promote-gold -RunId <run-id-from-build-output>
```

The `pit features build-gold` command reports both Gold table row counts, written partitions and
logical checksums. `pit features promote-gold` reloads the staged `gold-build-manifest.json`,
promotes both tables, and reports the Delta versions and predicate.

## Implemented command contract

| Command | Outcome |
|---|---|
| `bootstrap` | Sync the exact `uv.lock` environment and install pre-commit hooks |
| `setup` | Sync the full locked environment — every dependency group (`dev`, `training`, `tracking`, `feast`, `serving`) — and install pre-commit hooks |
| `tools` | Install hand-installed dev tools (locust + the ADR-008 OpenTelemetry packages) into the current env |
| `parity-reconcile` | Reconcile online aggregates against the offline DuckDB reference over the Event History (async, ADR-009) |
| `worker` | Run the `pit-online-worker` — consume score events, maintain the online store (ADR-010) |
| `worker-up` / `worker-down` | Start / stop the `pit-online-worker` Docker container |
| `serve-otel` | Start the scoring API with OTel traces/metrics, reading `otel_endpoint` from `config.yaml` or `PIT_OTEL_ENDPOINT` |
| `locust` | Run the Locust web UI + offline/online parity harness against a running service (`LOCUST_HOST`) |
| `doctor` | Read-only host, dependency, Delta, resource, port, Git, and credential checks |
| `lab` | Start JupyterLab with project code importable from the locked environment |
| `lab-training` | Start JupyterLab with the development and training dependency groups |
| `lab-container` | Start an isolated, localhost-only JupyterLab Compose profile |
| `data-sample` | Validate hand-calculated vectors and materialize the synthetic Parquet fixture |
| `data-snapshot` | Hash/profile the PaySim raw CSV and persist its immutable identity manifest |
| `profile` | Profile the synthetic fixture or real PaySim CSV through the same CLI boundary |
| `test-temporal` | Exercise future, duplicate, tie, late-arrival, boundary, cold-start, and ordering cases |
| `build-lakehouse` | Write sample or PaySim Bronze/Silver Delta tables for `DATASET` |
| `lakehouse-history` | Inspect exact local Delta versions and operations for `DATASET` |
| `features` | Inspect the frozen PaySim FeatureSpec v2, model order and checksum |
| `test-lakehouse` | Verify sample/PaySim-fixture schema, quality, rerun, isolation, and time travel |
| `test-notebooks` | Execute all Sprint 1 notebooks in memory without storing outputs |
| `model-spike` | Run the standalone PaySim LightGBM E1–E4 candidate matrix with local MLflow |
| `train` | Train locked E1/E4 baselines from exact PaySim Silver Delta versions |
| `gold` | Build Gold pre-decision and post-event tables into staging for an inclusive step range |
| `promote-gold` | Promote a staged Gold run into the committed tables |
| `lint`, `test`, `check` | Run the same fast quality lane locally and in CI |
| `changelog-check` | Ensure staged implementation changes update milestone audit logs |
| `up-core`, `status`, `logs`, `down` | Operate Redis and MLflow without deleting volumes |

See [project status](artifacts/changelog/PROJECT_STATUS.md) for the exact distinction between planned,
implemented, and verified artifacts.

## Repository layout

```text
src/pit_fintech/       reusable contracts, canonicalization, oracle, CLI, diagnostics
feature_repo/          frozen v1 specs; Feast definitions begin after Sprint 1 gates
data/fixtures/         committed temporal source, hand-calculated vectors, generated Parquet
tests/temporal/        exhaustive PIT correctness lane
tests/unit/            deterministic hashing, ordering, specs, artifact tests
notebooks/             Sprint 1 EDA, temporal/leakage analysis, and candidate model review
docs/                  ADR, architecture, protocol, access, and reports
docs/feature-store/    proposal and implementation guides for all three sprints
artifacts/changelog/   tracked status, cumulative changelog, and milestone implementation logs
artifacts/*            other runtime manifests and immutable run outputs remain gitignored
```

## Temporal semantics

For prediction event `e`, a source event `s` is eligible only when:

```text
(s.event_timestamp, s.transaction_id) < (e.event_timestamp, e.transaction_id)
AND s.created_timestamp <= e.created_timestamp
```

Windows use `[cutoff - window, cutoff)`: the lower boundary is inclusive, while the current
event is excluded. Exact duplicate transaction rows are deduplicated; conflicting duplicates
fail loudly. Scoring/replay must query before updating online state.

## Local infrastructure

`compose.yaml` keeps the core footprint to Redis and MLflow. JupyterLab is an opt-in profile.
All published ports bind to `127.0.0.1`; Jupyter retains token authentication. Runtime volumes
survive `make down` / `.\make.ps1 down`.

## Connecting the scoring API to Prometheus / Grafana

The serving API exposes `/metrics` in Prometheus text format (`pit_scoring_requests_total`,
`pit_scoring_errors_total`, `pit_scoring_latency_ms_avg`) whether or not OTel is enabled.
Prometheus pulls, so the app must be reachable from the Prometheus host:

1. In `config.yaml`, set `api_host: 0.0.0.0` (binds all interfaces; keep `127.0.0.1` for local-only)
   and keep `api_port: 8000`. For a deployment-only override, use `PIT_API_HOST`/`PIT_API_PORT` in
   `.env` or the process environment; environment values take precedence over YAML.
   Allow inbound on that port over Tailscale in the Windows firewall.
2. Start the service: `.\make.ps1 serve` (or `uv run pit serving up --host 0.0.0.0`).
3. On the VPS, add a scrape job to the `prometheus.yml` Prometheus actually mounts (see note
   below) and reload Prometheus:

   ```yaml
   - job_name: 'pit_fintech_scoring'
     scrape_interval: 15s
     static_configs:
       - targets: ['<windows-tailscale-ip>:8000']
   ```

   Find the Windows machine's Tailscale IP with `tailscale ip -4`. Reload with
   `docker compose exec prometheus kill -HUP 1` (or restart the container).

> Note: if your compose mounts `- /etc/prometheus:/etc/prometheus`, the live config is
> `/etc/prometheus/prometheus.yml` on the host, not the file next to `docker-compose.yml`.

4. In Grafana, add Prometheus as a data source (`http://prometheus:9090` from inside the compose
   network, or `http://<vps-ip>:9090` from outside), then build a dashboard on the
   `pit_scoring_*` metrics.

For trace/span-level observability, the optional `PIT_OTEL_ENDPOINT` pushes OTLP traces to an
OTel Collector that forwards them to Tempo; Grafana then shows the read-before-write ordering as a
`score` span containing its child `online_write` span. Prometheus itself only scrapes `/metrics`.
Non-secret sample configs for this hybrid setup (Collector + Tempo + scrape job + dashboard) live
in [`deploy/vps/`](deploy/vps/README.md) — the VPS is the owner's deployment boundary and is
configured by hand from those files.

## Structured logging and trace correlation

The serving process (`pit serving up`) emits structured JSON logs via `structlog`
(`src/pit_fintech/platform/logging_config.py`). Every log line emitted while a `/score` request is
on the stack carries:

* OTel `trace_id` / `span_id` (when started with `--otel` and a span is active), so a Grafana log
  line jumps to its Tempo trace and a trace jumps back to its logs;
* request correlation fields — `request_id`, `transaction_id`, `entity_id`, `step`,
  `knowledge_step`, `model_version`, `feature_service_version`.

Offline commands keep the default console output; any command can opt into the same pipeline by
calling `configure_logging()` from `pit_fintech.platform.logging_config` (it honors `PIT_LOG_LEVEL`
/ `PIT_LOG_JSON`), then bind the same `entity_id`/`step` fields to correlate offline
feature/training logs with online serving logs for the same entity.

## Dataset policy

The committed synthetic fixture remains the temporal-correctness ground truth. PaySim is the
EDA-first application dataset; IEEE-CIS and Home Credit are ADR-gated alternatives. The PaySim
notebooks must profile temporal/entity viability and leakage before the application contract or
model family is locked. Raw dataset files are never committed. See
[data access](docs/data-access.md).

## Frozen PaySim feature contract

ADR-003, amended by ADR-005, freezes `paysim-fraud-recipient-v2`: three request-time fields plus destination-history
count, amount sum and cold-start indicators at 1h, 24h and 168h. Historical features require
`prior_step < current_step`; same-step events, labels, policy output and balance fields are
excluded. Inspect the ordered contract and its canonical checksum with:

```powershell
.\make.ps1 features
```

The existing `fraud-history-v1` spec remains the independent synthetic-oracle contract. It is not
the PaySim serving vector.

## Scope guard

No Spark, Kafka, Kubernetes, Airflow, or GPU is required. Feast is a registry/retrieval
contract and will not replace the independent oracle. Cloud and TypeScript serving start only
after Python replay parity and Sprint 2 gates pass.
