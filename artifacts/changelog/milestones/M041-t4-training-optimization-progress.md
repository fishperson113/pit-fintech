# M041 — Optimize T4 training path and add Colab-style progress

- Date: 2026-08-05
- Status: **implemented, verified**.
- Scope: make the Gold-to-training path (entity dataframe -> retrieval -> split -> LightGBM)
  efficient at 2.7M rows and print phase progress like the Gold build/promote paths.

## Problem

The T4 path runs on the full Gold range (2.7M pre-decision rows). The old code materialized
full columns through `to_pylist()` several times over millions of rows (retrieval duplicates/max,
future-read audit, three split profiles), and the label table was loaded with every column before
a join that only needs `source_row_number` and `isFraud`. No O(n^2) existed, but repeated Python
list materialization dominated runtime and RSS. There was also no progress output, so a long
training run looked hung.

## Changes

`src/pit_fintech/training/dataset.py`:

- `build_entity_dataframe`: narrows Silver labels to `(source_row_number, isFraud)` before the
  DuckDB join; adds `progress` flag with `[t4 +Xs]` phase lines.
- `retrieve_historical_features`: replaces `to_pylist()` duplicate/max/fraud counts with
  `pa.compute.unique/max/sum`; adds `progress` flag.
- `_future_read_count`: Arrow `greater_equal + fill_null + sum` instead of three `to_pylist()`
  passes over 2.7M rows.
- `_split_profile` and `split_temporal`: Arrow masks/counts instead of `to_pylist()`; `progress`
  flag added.

`src/pit_fintech/training/pipeline.py`:

- `train_candidate` gains `progress: bool = False`; when enabled it prints phase lines and adds
  `lightgbm.log_evaluation(period=10)` so the fit prints every-10-rounds training log like a
  notebook/Colab run.

`scripts/run_t4_training.py`:

- Enables `progress=True` on all four stages.

Contract impact: none. Defaults preserve prior behavior (progress off, same columns, same
checksums/assertions). `log_evaluation` only prints; it does not change training.

## Verification

- Ruff check and format: pass on all changed files.
- `tests/integration/test_t4_training.py` + `tests/integration/test_gold_offline_features.py`:
  6 passed.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 21 passed, 4 known warnings.
- Real training now verified on committed Gold v6: two independent `train-gold-candidate` E4/pit
  runs both produced `test_pr_auc 0.362883` with complete MLflow tags/artifacts (runs
  `169f5d8a...`, `8f9c7097...`), confirming deterministic reproducible T4 training on the real
  lakehouse. T4 is ready for T5 materialization.
- Warning cleanup: `train_candidate` passes feature-named DataFrames and LightGBM
  `eval_X`/`eval_y`, removing the `eval_set` deprecation and sklearn feature-name warnings from
  the T4 path (only the pre-existing Ibis `fetch_arrow_table()` deprecation remains, from the
  Feast G1 lane).
