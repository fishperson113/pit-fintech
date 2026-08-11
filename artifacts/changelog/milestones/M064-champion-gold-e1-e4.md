# M064 — Champion loading and Gold E1–E4 evaluation

- **Datetime:** 2026-08-11
- **Status:** implemented and verified locally on committed Gold
- **Scope:** MLflow champion alias loading, precision/recall evidence, Gold-backed E1–E4 matrix

## Decisions

- Serving defaults to MLflow Registry alias `champion` for `paysim-fraud-lightgbm` and fails closed
  when the alias is missing. Explicit `mlflow_run_id` remains a diagnostic/test override.
- Because the frozen Gold schema does not contain future/lifetime leakage columns, E2 is defined as
  the Gold `post_event_state_updates` current-inclusive positive control. It is marked non-deployable.
- Gold matrix:
  - E1: static + temporal, deployable baseline
  - E2: post-event/current-inclusive + random, non-deployable control
  - E3: PIT + random, diagnostic join control
  - E4: PIT + temporal, deployable candidate
- Every result reports PR-AUC, ROC-AUC, recall, precision and observed FPR.

## Implementation

- Added `src/pit_fintech/serving/model_loader.py`:
  - resolves `models:/paysim-fraud-lightgbm@champion` via `MlflowClient`;
  - loads the model through the resolved `runs:/<run_id>/model` URI for MLflow 3 Windows local
    artifact compatibility;
  - validates/loads ordered feature names and decision threshold;
  - supports registering a run and moving the `champion` alias.
- Serving `build_scoring_context()` now uses champion by default and returns registry version/deployment
  identity in `model_version`/`deployment_id`.
- Added `src/pit_fintech/models/paysim_gold.py` and CLI commands:
  - `pit model gold-evaluate ...`
  - `pit model promote-champion --run-id ...`
- Added `make gold-evaluate` with overrideable Gold path/Delta version variables:
  `GOLD_ROOT`, `GOLD_PRE_VERSION`, `GOLD_POST_VERSION`, `GOLD_LABELS_VERSION`.
- Added the equivalent Windows `make.ps1 gold-evaluate` target with `-GoldRoot`,
  `-GoldPreVersion`, `-GoldPostVersion`, and `-GoldLabelsVersion` parameters.
- Gold E1–E4 results are logged to MLflow with model artifacts, feature contract and threshold
  artifacts. E4 is the only CLI-eligible champion candidate.
- Candidate CLI output now includes precision alongside recall.

## Evidence

Real Gold run:

- pre-decision Gold v8
- post-event Gold v7
- Silver labels v7
- joined Gold rows: **2,770,409**
- E1 PR-AUC **0.339148**, recall **0.278754**, precision **0.5487...**
- E2 PR-AUC **0.415330**, recall **0.612058**, precision **0.1558...**
- E3 PR-AUC **0.419316**, recall **0.612667**, precision **0.1591...**
- E4 PR-AUC **0.362883**, recall **0.292332**, precision **0.5041...**
- MLflow runs were created for E1/E2/E3/E4; E4 was registered as version 1 and assigned alias
  `champion`.
- Real champion load verified: `predict_proba=True`, 12 ordered features, threshold loaded.

Tests:

- unit suite: **104 passed**
- focused model/Gold/training suite: **15 passed**
- T4 integration training: **2 passed**
- Ruff/format/compile: **pass**

## Known boundaries

- MLflow local artifact loading uses `runs:/<run_id>/model` after alias resolution because MLflow 3
  local Windows `models:/@alias` can embed a `C:` artifact URI that the model loader parses incorrectly.
- Deployment promotion still represents the lightweight MLflow alias path; the larger immutable
  deployment manifest/rollback lifecycle remains a separate unclosed T4/G11 scope.
