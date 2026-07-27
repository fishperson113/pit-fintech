# PaySim LightGBM candidate spike

Status: **standalone E1–E4 run verified; review-first notebook revision awaits notebook
verification**.

## Purpose

This is a standalone Sprint 1 model-family and pipeline-feasibility spike. It answers:

1. Does a fixed CPU LightGBM workflow execute end to end with versioned evidence?
2. Do strict-PIT recipient features change results relative to request-time fields?
3. How optimistic is the deliberately leaky positive control?

It does not lock the final feature contract, promote a model, or claim production fraud
performance.

## Frozen matrix

| ID | Features | Split | Role |
|---|---|---|---|
| E1 | static request-time | temporal | deployable non-history baseline |
| E2 | current/future/lifetime controls | random | deliberately leaky positive control |
| E3 | strict-PIT recipient history | random | isolate PIT-feature effect from split effect |
| E4 | strict-PIT recipient history | temporal | candidate deployable semantics |

Every experiment uses the same candidate cohort:

- all customer-destination fraud `CASH_OUT` and `TRANSFER` rows;
- at most 5,000 deterministic non-fraud rows per split and transaction type;
- train steps `1–520`, validation `521–631`, test `632–743`;
- fixed seed `20260727`;
- threshold selected on validation at FPR `0.01`.

The cohort intentionally oversamples fraud. Absolute PR-AUC therefore describes this pinned
diagnostic cohort, not PaySim's natural fraud prevalence.

## Feature boundaries

Safe candidate columns contain only:

- current amount, event step and transaction-type indicator;
- recipient history counts, amount sums and cold-start flags for 1h, 24h and 168h.

Balance columns, `isFraud` and `isFlaggedFraud` are forbidden model inputs. E2 separately uses
current-inclusive, future-inclusive and lifetime aggregates so leakage remains visible and cannot
silently enter E4.

These are candidate column lists, not the final PaySim FeatureSpec. The contract is frozen only
after reviewing model evidence together with lineage, cold-start coverage and resource cost.

## Execution

Preferred non-notebook path:

```powershell
.\make.ps1 model-spike
```

Equivalent GNU Make target:

```bash
make model-spike
```

Interactive path:

```powershell
.\make.ps1 lab-training
```

Then open `notebooks/04_model_candidate.ipynb`. It defaults to `RUN_TRAINING = False` and reviews
the latest validated manifest without retraining. Set the flag to `True` only when intentionally
creating another MLflow parent run; the notebook calls the same function used by the CLI.

No MLflow container is required. The default tracking backend is the local SQLite database
`artifacts/mlflow/tracking.db`; model artifacts use
`artifacts/mlflow/artifacts/`.

## Expected evidence

Each successful execution writes:

```text
artifacts/
  experiments/
    paysim-lightgbm-spike/
      <parent-run-id>/
        manifest.json
  mlflow/
    tracking.db
    artifacts/
      ...
```

The manifest records:

- raw PaySim checksum and snapshot ID;
- candidate-table checksum and per-experiment training-dataset checksum;
- validation threshold policy, including an explicit zero-positive fallback when no finite
  positive-prediction threshold can satisfy the fixed-FPR budget;
- pickle-free `skops` model serialization with an explicit allowlist limited to the expected
  LightGBM classifier, booster and ordered parameter mapping types;
- code commit and `uv.lock` checksum;
- LightGBM, MLflow, NumPy and scikit-learn versions;
- sampling, split, seed and fixed-FPR policy;
- E1–E4 feature names, row counts and fraud rates;
- PR-AUC, ROC-AUC, recall/precision and observed FPR;
- training time, process RSS before/after and MLflow model URI;
- explicit claim boundaries.

## Review after execution

- Compare E4 against E1 under the same temporal split.
- Compare E2 against E4 only as leakage optimism evidence.
- Use E3 to distinguish split-policy optimism from feature-computation effects.
- Do not tune LightGBM to hide weak recipient history.
- If E4 is not better than E1, retain the result; the platform correctness contribution remains
  valid.
- Freeze PaySim FeatureSpec v1 only after the output and resource footprint are reviewed.
