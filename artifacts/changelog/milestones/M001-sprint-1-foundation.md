# M001 — Sprint 1 foundation and temporal correctness slice

- Date: 2026-07-21
- Status: verified partial milestone; overall Sprint 1 remains in progress

## Scope and gates

Implement the developer platform and credential-free correctness path before application-data
download: command contract, synthetic oracle, temporal tests, Jupyter notebooks, and sample
Bronze/Silver Delta snapshots. Relevant gates are Sprint 1 G2, G4, G5, and G6 on the sample.

## Technical decisions

- Makefile is orchestration; the installed `pit` CLI is shared by Make, PowerShell, and CI.
- The readable Python oracle remains independent from future DuckDB/Feast implementations.
- Decision order is `(event_timestamp, transaction_id)` with created-time availability.
- Labels are separated from Silver transactions.
- Logical checksums ignore storage filenames and Delta commit metadata.
- Redis/MLflow are local Compose boundaries; Feast and scoring remain gated for Sprint 2.

## Implemented files and modules

- `src/pit_fintech/contracts`, `data`, `features`, `platform`, and `cli.py`.
- `feature_repo/feature_specs.py`, temporal/unit/integration tests, and three notebooks.
- `Makefile`, `make.ps1`, `compose.yaml`, Dockerfile, CI, lockfile, ADR, and reports.
- Synthetic JSONL, hand-calculated expected vectors, and generated Parquet fixture.

## Verification evidence

```text
uv sync --frozen --group dev             -> pass
uv run pit doctor                        -> pass with documented non-blocking warnings
uv run pytest -q                         -> 19 passed at milestone verification
uv run ruff check ...                    -> pass
uv run ruff format --check ...           -> pass
uv run pit notebooks verify              -> 3 notebooks pass
.\make.ps1 test-temporal                 -> 12 temporal tests pass
.\make.ps1 build-lakehouse               -> Bronze/Silver/labels versioned snapshots
docker compose config --quiet             -> pass
```

Sample evidence:

- snapshot: `synthetic-temporal-v1:c0909688e0e26e20`;
- future-read violations: `0`;
- Bronze rows: `8`;
- Silver transaction rows: `7`;
- Silver label rows: `7`;
- Silver transaction checksum: `7d9935e8450dfc8bb580bf9e64a57bcc7a51e13b8cb4fda092e5dd63ed76e3f3`.

## Deviations and known gaps

- Docker Compose config passes, but the MLflow image build timed out on the host and is not
  verified; no cache prune was performed.
- Kaggle credentials and IEEE-CIS data are not configured.
- Entity sensitivity, final ADR decision, full resource profile, and LightGBM baselines remain
  pending. Therefore Sprint 1 is not marked complete.

## Next step

Verify IEEE-CIS access, run candidate entity sensitivity by Day 2, finalize ADR-001, and only
then implement full-data lakehouse/profile and static/PIT model baselines.
