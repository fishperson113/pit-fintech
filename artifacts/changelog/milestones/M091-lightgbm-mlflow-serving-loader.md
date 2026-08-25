# M091 — Flavor-aware MLflow serving loader for notebook LightGBM

- Timestamp: 2026-08-25 00:04:41 +0700
- Status: implemented and verified

## Scope and gate

Make `make.ps1 serve` load the native LightGBM model registered by notebooks 08–12 while preserving legacy sklearn/Random Forest loading, immutable run-id caching, decision-threshold resolution, and the explicit shared-to-local tracking fallback boundary.

Acceptance:

- `models:/paysim-fraud-lightgbm/1` loads as `lightgbm.sklearn.LGBMClassifier` with `predict_proba`;
- a model flavor/deserialization error is not mislabeled as shared MLflow unreachability and does not trigger fallback;
- the public `make.ps1 serve` command reaches ready state using the registered LightGBM run;
- existing unit tests and focused static checks remain green.

## Root cause

The notebook final model was correctly logged with native MLflow flavors `lightgbm` and `python_function`. Serving downloaded it successfully, but `_load_sklearn_model_cached` always called `mlflow.sklearn.load_model`, which requires an `sklearn` flavor. The legacy RF model worked because its `MLmodel` has `sklearn`; the LightGBM model failed because its native metadata has `lightgbm` instead.

`_load_model_by_uri` also caught every exception around resolution, download, and deserialization. It therefore reported the flavor mismatch as “shared MLflow unreachable” and retried against the local SQLite store, obscuring the real cause and potentially selecting a different model lineage.

## Implementation

Changed:

- `src/pit_fintech/serving/app.py`
  - split registry resolution/artifact caching from estimator deserialization;
  - inspect `MLmodel.flavors` and call `mlflow.lightgbm.load_model` for native LightGBM or `mlflow.sklearn.load_model` for legacy sklearn models;
  - keep the original estimator rather than using pyfunc because scoring requires `predict_proba`;
  - restrict tracking fallback to registry resolution/artifact-download failures; model flavor/deserialization errors now fail directly;
  - preserve cache identity at `cache_root/<run_id>`.
- `tests/unit/test_serving_model_cache.py`
  - regression for native LightGBM flavor selection;
  - regression proving deserialization/flavor failures do not trigger tracking fallback.

No dependency, lockfile, model registry, config, feature contract, Gold, Redis state, or model version was modified.

## Verification evidence

1. RED before implementation:
   - `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit/test_serving_model_cache.py`
   - result: `2 failed`; `_load_mlflow_model_cached` did not exist.
2. Focused GREEN:
   - same command after implementation: `2 passed in 4.17s`.
3. Real cached model-flavor probe:
   - run `ef918e30a6f3459f9c524ec4c8fc1a7d` loaded as `lightgbm.sklearn.LGBMClassifier`, `predict_proba=True`;
   - legacy run `80af4d14dd4c44a0b7e924bd23f5a9f1` loaded as `sklearn.ensemble._forest.RandomForestClassifier`, `predict_proba=True`.
4. Exact registry loader probe:
   - `models:/paysim-fraud-lightgbm/1` against `http://100.116.36.6:5000` returned run `ef918e30a6f3459f9c524ec4c8fc1a7d` as `LGBMClassifier`, `predict_proba=True`, without local fallback.
   - estimator `feature_name_` exactly matched the locked `PAYSIM_MODEL_FEATURE_ORDER` (`10` fields).
5. Registry metadata:
   - model `paysim-fraud-lightgbm`, version `1`;
   - run `ef918e30a6f3459f9c524ec4c8fc1a7d`;
   - `model_family=lightgbm`, `threshold=0.937262`;
   - top-level run artifact `evaluation_nb12_final_lgbm_test.json`.
6. Unit lane:
   - `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit`
   - result: `114 passed in 10.54s`.
7. Static checks:
   - Ruff check and format-check on the changed source/test: PASS.
8. Public startup verification:
   - `powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\workspace\pit-fintech\make.ps1' serve`;
   - log: cache hit for run `ef918e30a6f3459f9c524ec4c8fc1a7d`;
   - `/health/ready`: HTTP 200, `ready=true`, `model_loaded=true`, `online_store_reachable=true`, `model_version=ef918e30a6f3459f9c524ec4c8fc1a7d`, watermark step `743`;
   - the session-owned server was stopped and port 8000 was confirmed free.

## Deviations and gaps

- This fix does not promote or retrain a model; it serves the already registered version 1.
- The notebook run does not log `ordered_feature_names.json`; serving records this and uses the locked `PAYSIM_MODEL_FEATURE_ORDER`. The ready probe verifies startup, but adding that artifact to future notebook runs would strengthen independent model-contract evidence.
- No full E2E replay or prediction-parity gate was rerun; this milestone verifies model loading and serving readiness only.
