# M092 — MLflow input/output model signatures for notebook LightGBM

- Timestamp: 2026-08-25 06:46:07 +0700
- Status: implemented and verified locally; owner rerun/register pending

## Scope and acceptance

Persist a concrete MLflow input example plus input/output model signature whenever notebooks 08–12 log a native LightGBM model, so the final version registered by notebook 12 exposes its schema in Model Registry.

Acceptance:

- logged `MLmodel` contains an ordered, named input schema and an output schema;
- the model artifact contains both `input_example.json` and `serving_input_example.json`;
- notebook 12 passes the exact final test feature DataFrame when logging/registering;
- notebooks 09–11 follow the same logging contract for consistency;
- feature order mismatch fails before a misleading model artifact is logged;
- native LightGBM loading and `predict_proba` compatibility remain intact.

## Technical decision

MLflow signatures belong to the model artifact created by `mlflow.lightgbm.log_model`; Model Registry references that artifact and does not infer a missing signature merely because `registered_model_name` is supplied. Therefore the notebook logging helper, and especially notebook 12's final register call, must provide the signature and input example at log time.

The helper infers the signature from:

- input: up to five real rows from the exact named DataFrame used by the fitted model, preserving column order and pandas dtypes;
- output: `model.predict(input_example)`, because the native MLflow LightGBM pyfunc flavor invokes `predict` and returns class labels.

The custom PIT FastAPI serving boundary intentionally loads the native estimator and calls `predict_proba(... )[:, 1]`; that probability response contract is separate from the native MLflow pyfunc output signature. Logging a probability output signature against a pyfunc model that actually returns labels would be incorrect.

## Implementation

Changed notebooks:

- `notebooks/08_paysim_eda.ipynb`
- `notebooks/09_feature_engineering_selection.ipynb`
- `notebooks/10_walkforward_cv_split.ipynb`
- `notebooks/11_optuna_tuning.ipynb`
- `notebooks/12_shap_final_evaluation.ipynb`

The shared self-contained helper now:

1. requires a non-empty `input_frame`;
2. stores the first five rows as a reset-index input example;
3. verifies its ordered columns exactly match `model.feature_name_`;
4. calls `MLFLOW.models.infer_signature(input_example, model.predict(input_example))`;
5. passes both `signature` and `input_example` to `MLFLOW.lightgbm.log_model` for MLflow 3 (`name`) and older (`artifact_path`) APIs.

Evaluation calls now provide:

- notebook 09: the corresponding baseline/history validation frame;
- notebook 10: `splits["val"][FEATURES]`;
- notebook 11: `Xval`;
- notebook 12: `test[FEATURES]` before `register=True`.

The stale local `mlruns` directory creation was removed from the shared remote-only helper cell.

Added:

- `tests/unit/test_notebook_mlflow_signature.py`
  - static contract for signature and input-example arguments in all five notebooks;
  - contract that every model-evaluation log call in notebooks 09–12 supplies its input frame.

No dependency, lockfile, dataset, model registry version, serving configuration, Gold artifact, or Redis state was modified.

## Verification evidence

1. RED contract:
   - `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit/test_notebook_mlflow_signature.py`
   - result before implementation: `2 failed` (signature/input example and input-frame calls absent).
2. Focused GREEN:
   - same command after implementation: `2 passed in 0.41s`.
3. Real native-LightGBM MLflow smoke log using the notebook 12 helper:
   - fitted `LGBMClassifier` with the locked 10 named serving features;
   - stored input schema: 10 ordered required columns;
   - stored output schema: tensor `int64`, shape `[-1]`;
   - `input_example.json`: present;
   - `serving_input_example.json`: present;
   - native reload type: `lightgbm.sklearn.LGBMClassifier`, `predict_proba=True`.
4. Notebook static validation:
   - notebooks 08–12 parse as JSON;
   - every code cell parses as Python after stripping notebook magics;
   - signature contract present and no `pit_fintech` runtime import;
   - result: PASS for all five notebooks.
5. Unit lane:
   - `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit`
   - result: `116 passed in 9.16s`.
6. Diff whitespace check: PASS.

## Lint follow-up — 2026-08-25 07:09:06 +0700

The first repository-wide lint attempt exposed 73 notebook findings introduced or surfaced by the
self-contained cells: 67 legacy percent-format (`UP031`) findings, repeated feature-importance
`zip()` calls without `strict=` (`B905`), two pre-existing notebook-local instances of the same
patterns, and one unused local (`F841`). The cleanup preserved model/data semantics:

- converted the shared MLflow helper's percent formatting to f-strings;
- added `strict=True` only where collection lengths are already explicitly equal or statically
  paired;
- removed the unused EDA local without changing the returned classification;
- applied Ruff formatting to notebooks 08–12 and cleared outputs only in edited cells.

Verification after cleanup:

- direct repository lane with the required environment contract:
  `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff check src tests notebooks scripts`
  followed by `ruff format --check ...` — PASS, `123 files already formatted`;
- public Windows runner:
  `make.ps1 lint` with the existing `.venv` and sync disabled for verification — PASS, both Ruff
  commands exit 0 and report `123 files already formatted`;
- notebook JSON/AST validation: PASS for all five notebooks;
- focused signature contract: `2 passed in 0.48s`;
- full unit lane after cleanup: `116 passed in 8.25s`;
- `git diff --check`: PASS.

## Notebook cache hygiene

The notebook handoff directory `notebooks/_cache/` contains regenerable local runtime artifacts,
including the large `modeling_frame.parquet`. It is now ignored as a directory and the four
previously staged cache files were removed from the Git index with `git rm --cached`; their local
working files remain available for notebook 12 reuse. This resolves the pre-commit
`check-added-large-files` rejection without deleting local training cache data.

## Owner rerun and remaining gap

The currently registered `paysim-fraud-lightgbm/1` artifact predates this change and remains unchanged. Rerunning notebook 12's final MLflow cell after training will log/register a new model version containing the input/output signature and examples. The shared remote registry was not mutated during local verification.

Full PaySim notebooks 08–12 were not rerun end to end in this milestone; the owner rerun remains the verification required for the real-data schema shown in shared Model Registry.
