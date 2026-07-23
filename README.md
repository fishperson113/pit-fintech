# PIT Fintech — Point-in-Time Correct Feature Platform

Local-first MLOps codebase for a fraud feature platform whose acceptance path is based on
three invariants: no future reads, offline/online parity, and reproducible backfills. The
project is a paper-inspired adaptation for one CPU machine; it does not claim to reproduce
the FeathrPO/Spark speedups from the source paper.

The repository is intentionally milestone-driven. The current implementation establishes
the Sprint 1 temporal contract and developer platform. Redis/MLflow infrastructure is wired
for the next vertical slice, while Feast, Gold backfill, training, serving, replay, and cloud
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

Alternatively, set `PAYSIM_CSV` in the shell or copy `.env.example` to `.env` and set
`PIT_PAYSIM_CSV`. Freeze the raw input once before running EDA:

```bash
make data-snapshot
make profile DATASET=paysim
make lab
```

```powershell
.\make.ps1 data-snapshot
.\make.ps1 profile -Dataset paysim
.\make.ps1 lab
```

`data-snapshot` writes a machine-readable manifest under
`artifacts/datasets/paysim1/<checksum-prefix>/snapshot-manifest.json`. It does not copy or mutate
the raw CSV.

The notebooks do not fall back to synthetic data. Without the PaySim CSV they show setup
instructions and skip data queries.

## Implemented command contract

| Command | Outcome |
|---|---|
| `bootstrap` | Sync the exact `uv.lock` environment and install pre-commit hooks |
| `doctor` | Read-only host, dependency, Delta, resource, port, Git, and credential checks |
| `lab` | Start JupyterLab with project code importable from the locked environment |
| `lab-container` | Start an isolated, localhost-only JupyterLab Compose profile |
| `data-sample` | Validate hand-calculated vectors and materialize the synthetic Parquet fixture |
| `data-snapshot` | Hash/profile the PaySim raw CSV and persist its immutable identity manifest |
| `profile` | Profile the synthetic fixture or real PaySim CSV through the same CLI boundary |
| `test-temporal` | Exercise future, duplicate, tie, late-arrival, boundary, cold-start, and ordering cases |
| `build-lakehouse` | Write versioned Bronze/Silver Delta tables after the temporal gate |
| `lakehouse-history` | Inspect exact local Delta versions and operations |
| `test-lakehouse` | Verify logical idempotency, label separation, and old-version time travel |
| `test-notebooks` | Execute all Sprint 1 notebooks in memory without storing outputs |
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
notebooks/             Sprint 1 EDA, temporal analysis, and leakage exploration
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

## Dataset policy

The committed synthetic fixture remains the temporal-correctness ground truth. PaySim is the
EDA-first application dataset; IEEE-CIS and Home Credit are ADR-gated alternatives. The PaySim
notebooks must profile temporal/entity viability and leakage before the application contract or
model family is locked. Raw dataset files are never committed. See
[data access](docs/data-access.md).

## Scope guard

No Spark, Kafka, Kubernetes, Airflow, or GPU is required. Feast is a registry/retrieval
contract and will not replace the independent oracle. Cloud and TypeScript serving start only
after Python replay parity and Sprint 2 gates pass.
