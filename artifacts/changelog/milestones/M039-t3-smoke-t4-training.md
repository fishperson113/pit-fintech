# M039 — Add T3 smoke lane and T4 Gold training path

- Date: 2026-08-05
- Status: **implemented, partially verified**.
- Scope: isolated T3 smoke evidence, reproducible Make/PowerShell wiring, and T4 Gold-to-MLflow
  candidate path.

## T3 smoke

Added `tests/integration/test_gold_offline_features.py::test_t3_smoke_backfill_rerun_and_late_arrival_guard`.
It runs on an isolated temporary PaySim fixture and verifies:

- `plan_backfill` → `execute_backfill` reaches committed state;
- `compare_reruns` preserves matching output checksums;
- late-arrival injection is refused safely when the strict future-read guard detects a future-known
  row. This is an expected refusal smoke result, not correction-success evidence.

The late-arrival impacted range is rounded to an event-day boundary so the new Gold granularity guard
is respected. `BackfillPlan` now carries the exact Silver manifest path into execution instead of
re-resolving an ambiguous "latest" manifest, and the injected template row is selected deterministically
from in-scope customer CASH_OUT/TRANSFER rows.

## T4 implementation

- `training/dataset.py`: exact Gold/Silver label join, entity dataframe Parquet, retrieval assertions,
  frozen temporal split and deterministic Arrow checksum.
- `training/pipeline.py`: LightGBM temporal candidate, validation threshold at fixed FPR, natural
  prevalence validation/test metrics, MLflow required tags/artifacts and MLflow 3 logged-model
  verification.
- `scripts/run_t4_training.py`: reproducible real-Gold runner for E1/E4 candidates.

## Reproducible commands

- `make test-t3-smoke` / `make.ps1 test-t3-smoke`
- `make test-t4-dataset` / `make.ps1 test-t4-dataset`
- `make train-gold-candidate T4_EXPERIMENT=E4 T4_FEATURE_SET=pit`
- `make.ps1 train-gold-candidate -T4Experiment E4 -T4FeatureSet pit`

The Makefile commands use the frozen `.venv`/all-groups prefix for the new lanes. GNU Make was not
available in the verification shell; the PowerShell `test-t4-dataset` target passed.

## Verification

- T3 smoke: passed.
- T4 dataset fixture: passed.
- T4 LightGBM/MLflow temporary fixture: passed.
- `train-gold-candidate --help`: passed.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 20 passed, four warnings (existing Ibis deprecation plus LightGBM/sklearn warnings).
- Ruff check: all checks passed.
- Ruff format check: 88 files already formatted.
- No real T4 training was run.

## Open gates

- Full T3 G2/G3 evidence remains open: correction-success semantics, recovery and complete rerun
  evidence on the intended fixture/data path.
- Full-scale T4 training on committed real Gold remains unverified.
- T4 lifecycle promotion/rollback and T5 materialization remain future work.
