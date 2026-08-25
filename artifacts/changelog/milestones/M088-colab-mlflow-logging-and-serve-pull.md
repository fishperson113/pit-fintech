# M088 — Colab MLflow logging schema (Data-Centric) + serve-pull by model id

- 2026-08-24 — **implemented** (static gates pass locally; owner-pending: run the notebooks
  against the shared MLflow + a live `pit serving up` against a registered model id).

- 2026-08-24 — **amended** the Colab evaluation logging contract: nb02 now logs the trained
  history/PIT Random Forest itself, and nb03–nb05 log one comparable RF evaluation run each with
  only the confusion-matrix cell metrics (`confusion_tn/fp/fn/tp`), `confusion_matrix.json`, and
  the sklearn model artifact. This replaces the previous notebook-specific PR-AUC/feature-only
  logging as the simple owner-facing metric surface. nb01 remains data-profile-only because it
  does not train/evaluate a Random Forest.

- 2026-08-24 — **amended (v2 metric surface)**: replaced `log_rf_confusion_matrix` with a richer
  `log_rf_evaluation` helper (all 5 schema cells) that logs, per run, the confusion matrix **plus**
  `precision`/`recall`/`f1`/`accuracy`, `pr_auc`/`roc_auc` (when a score is passed), the decision
  `threshold`, and **feature gain** (`gain__<feature>` from `feature_importances_`, + a
  `feature_gain` block in `evaluation_<stage>.json`). nb02 now logs **both** ablation arms
  (baseline vs history) as two runs — `train_eval_cm` returns `_yscore`/`_features`/`_model`; nb03/04
  log the tuned/CV RF on VAL; nb05 logs the final RF on the sealed TEST **and registers**
  `paysim-fraud-rf` (`register=True`). Verified with a fake-MLflow probe: all code cells compile,
  the notebooks parse as JSON, and runs carry P/R/F1, PR-AUC, per-feature gain, threshold + artifact.

## Scope / gate

Owner-directed. Two halves, one contract:

1. **Notebook logging (Data-Centric AI, Andrew Ng).** Add a standard MLflow logging schema to the
   five self-contained colab notebooks (`notebooks/colab/colab_01..05`, Random Forest track, raw
   PaySim CSV, no `pit_fintech` import). Log at the two touchpoints the owner specified: Step 1
   model training/evaluation per data version (nb03 CV, nb04 tuning) and Step 2 registration when
   validation passes (nb05 TEST + SHAP). nb01/nb02 log data-profile / feature-selection runs.
2. **Serve-pull by id.** Serving pulls one explicit model id from the shared MLflow registry
   (`config.yaml: serving_model_uri`), tracking-URI defaulting to the shared server, with a local
   fallback when it is unreachable. Serving does not care how the model was trained.

Gate (owner-run): `.\make.ps1 lint` / `test-unit` green; then run each notebook end-to-end and
confirm runs/artifacts land in experiment `paysim-fraud-rf-colab` on `http://100.116.36.6:5000`,
and `pit serving up` with a set `serving_model_uri` loads the model. Static locally: `py_compile`
+ `ruff check` + `ruff format --check` clean on the three changed src files; all five notebooks'
new cells `py_compile` clean and the `.ipynb` JSON is valid.

## Design decisions

- **Copy-paste cell, at the end.** The schema is a single standard code cell (identical across all
  five notebooks) placed at the END of each notebook, followed by one per-notebook logging cell
  that uses that notebook's already-computed variables. Owner chose copy-paste over a shared
  `mlflow_lab.py` module (colab stays self-contained/portable) and end-of-notebook placement for
  manageability. New cells are output-free (`execution_count: null`, `outputs: []`).
- **Graceful everywhere.** `_mlflow_ready()` returns `None` when mlflow is absent (notebook still
  runs, no logging) and pings the shared server (2s); unreachable → fallback `file:./mlruns`.
- **Data version (Data-Centric).** `data_version()` = CSV sha256 prefix (`csv_sha8`) + row_count +
  step range + fraud_rate + `max_steps`. A cheap, stable data identity for the raw-CSV track.
- **Simple RF metric contract.** `log_rf_confusion_matrix()` uses labels `[0, 1]` and logs the four
  stable cell metrics `confusion_tn`, `confusion_fp`, `confusion_fn`, `confusion_tp`, plus a
  `confusion_matrix.json` artifact and the evaluated sklearn model. The evaluation split is tagged
  explicitly (validation for nb02–nb04, temporal test for nb05); the final test is marked sealed.
- **Notebook-specific analysis.** Existing PR-AUC, SHAP, tuning, and error-analysis cells remain
  exploratory outputs, but are no longer the required MLflow metric contract for the Colab RF run.
- **Registry name / experiment.** RF track logs to experiment `paysim-fraud-rf-colab` (separate
  from the src LightGBM `pit-fintech-gold-training`); nb05 registers `paysim-fraud-rf`.
- **Model id form.** Owner leaves the id shape to config: `serving_model_uri` accepts a registry
  URI `models:/<name>/<version>` (recommended, promotable) or a run URI `runs:/<run_id>/model`.
  Promote/rollback = edit that one line.
- **Serve default tracking = shared registry.** `pit serving up` now defaults its tracking URI to
  `config.yaml: mlflow_tracking_uri` (the shared server) instead of the local SQLite backend; an
  explicit `--mlflow-tracking-uri` still overrides. Local SQLite is the automatic
  `serving_model_local_fallback`.

## Files touched

- `notebooks/colab/colab_01..05_*.ipynb` (gitignored): shared helper updated with the stable RF
  confusion-matrix logger; nb02 retains its trained model in the result and nb02–nb05 call the
  helper at the end of the notebook. Checkpoint files were not edited.
- `src/pit_fintech/config.py`: `serving_model_uri`, `serving_model_local_fallback` settings.
- `config.yaml`: same two keys (both `null` by default → behaviour unchanged until set).
- `src/pit_fintech/serving/app.py`: `ServingSettings.serving_model_uri` /
  `.serving_model_local_fallback`; `build_scoring_context` pull-by-id branch (precedes champion
  alias / run-id); new `_resolve_run_id()` + `_load_model_by_uri()` (shared → local fallback).
- `src/pit_fintech/cli.py`: `serving up` defaults tracking URI to the shared registry and passes
  the two new settings through.

## Known gaps / next steps

- The colab RF is **experimental** (owner): the serving contract guard still requires
  `ordered_feature_names == PAYSIM_MODEL_FEATURE_ORDER`, so a 7-feature ablation model would not be
  servable by the v3 path — expected, not a target. Pull-by-id is the generic mechanism.
- `mlflow.sklearn.log_model` is called `name=`-first with an `artifact_path=` fallback to span
  mlflow 2.x/3 signature changes; confirm against the shared server's mlflow version.
- Owner-pending: actual notebook execution + a live `serving_model_uri` load. No gate has run
  against the shared MLflow from this workspace. Static verification for this amendment: all five
  notebooks parse as JSON; all changed MLflow cells compile; a synthetic fake-MLflow probe produced
  TN=1/FP=1/FN=1/TP=1 and exactly the four required metrics.
