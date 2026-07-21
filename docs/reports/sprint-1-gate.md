# Sprint 1 gate status

Date: 2026-07-21. Overall status: **IN PROGRESS**, not yet a Sprint 1 pass.

| Gate | Current evidence | Status |
|---|---|---|
| G1 Data access | Credential-free fixture snapshot is reproducible; Kaggle access not configured | partial |
| G2 Lakehouse | Synthetic Bronze/Silver Delta build, checksums, label separation, rerun, and time travel pass | sample pass |
| G3 Entity viability | Canonical hash contract passes; IEEE-CIS candidate sensitivity not run | pending |
| G4 PIT correctness | 12 temporal tests; future-read violations `0` | pass |
| G5 Leakage control | Label removed from Silver feature source; leaky positive control documented | sample pass |
| G6 Feature scope | 13 versioned history/request-derived specs, unique names, checksum test | pass |
| G7 Feasibility | Tiny fixture path passes; full CPU/RAM/disk benchmark not run | pending |
| G8 Baseline | Static and PIT LightGBM/MLflow runs not implemented | pending |
| G9 Protocol | Research protocol v0 exists; final split/entity decisions await EDA | partial |

Verified commands in this workspace:

```text
uv sync --frozen --group dev
pit doctor
pit data sample
pit data profile --dataset sample
pit data build-lakehouse --dataset sample
pit notebooks verify
pytest -q                         # 23 passed, including 4 changelog-guard cases
ruff check + ruff format --check # pass
docker compose config --quiet    # pass
.\make.ps1 test-temporal         # 12 passed
```

Expected, non-blocking doctor warnings are: DuckDB's optional `delta` extension is not locally
installed (the implemented writer/time-travel path uses `delta-rs`), Kaggle credentials are not
configured, and Git has no first commit yet.

Next gate work is application-data access/profile, entity sensitivity and ADR finalization.
Model baselines start only after those decisions are locked.
