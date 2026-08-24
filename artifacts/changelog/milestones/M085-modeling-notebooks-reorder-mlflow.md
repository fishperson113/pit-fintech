# M085 — Re-order modeling notebooks to the correct DS/ML pipeline + MLflow logging

Date: 2026-08-20
Status: implemented; helper unit-verified in `.venv`; notebook execution + MLflow arrival owner-pending

## Problem

The newest modeling notebooks encoded the data-science pipeline in the wrong order. The correct
order is EDA → feature engineering → feature selection → walk-forward CV/split → Optuna tuning →
SHAP, i.e. **CV/split must precede tuning**. Instead:

- `13_walkforward_cv_validation` (the proper walk-forward CV) sat *after* `11_hyperparameter_tuning`
  (Optuna) and `12_shap_final_evaluation`.
- `11`'s Optuna objective iterated `for tr_idx, va_idx in splits:` where `splits` is the 3-way
  `{"train","val","test"}` dict — a runtime bug: it cannot unpack fold indices from a dict, and it
  conceptually needed walk-forward folds that were only defined later in notebook 13.
- `13` hardcoded `BEST_PARAMS` copied from `11`, so the CV notebook depended on the output of the
  tuning notebook that was supposed to consume it (circular).

## Scope / decision

Confirmed with the owner (4-notebook structure, modeling scope only 09-13, MLflow from `config.yaml`):

- **09_feature_engineering_selection** — feature engineering + ablation/selection (former 09).
- **10_walkforward_cv_split** — temporal 3-way split + metric toolkit + LightGBM-vs-XGBoost
  comparison (former 10) merged with walk-forward CV + embargo + warm/cold (former 13). Uses
  **baseline (un-tuned) params** because it runs before tuning; exports the walk-forward protocol.
- **11_optuna_tuning** — Optuna optimizing **mean PR-AUC over the same walk-forward folds** notebook
  10 defines (bug fixed), then threshold tuning on VAL.
- **12_shap_final_evaluation** — final TEST evaluation + SHAP (former 12).
- Deleted the misordered `13_walkforward_cv_validation`; the rough expanding-window CV at the tail of
  the old notebook 10 was dropped in favor of the proper walk-forward CV.

EDA/validity notebooks 01-08 were left untouched (owner choice).

## Data source: Silver, not Gold (owner directive)

Per the owner, the modeling notebooks must **start from Bronze/Silver/raw and not shortcut through
the materialized Gold table**, unified across all modeling notebooks. This also surfaced a v3
mismatch: Gold migrated to the 10-field v3 contract (dropped `event_step`, `pit_prior_count_168h`,
`recipient_has_history_*`; added `pit_distinct_senders_*`, `pit_steps_since_last_event`), while the
notebooks still referenced v2 column names — the `KeyError: 'pit_prior_count_168h'` the owner hit.

Resolution: `load_modeling_frame` now runs the shipped
`features.paysim_recipient.paysim_pre_decision_feature_sql` over the Silver `paysim_transactions`
table — the exact strict pre-cutoff derivation the Gold builder uses — and joins Silver
`paysim_labels`. This honors the directive and stays leakage-free (a naive in-notebook rolling
window would read future rows), at the cost of re-deriving features on each load (slower than
reading Gold — an intentional trade for a learning surface). nb09's feature engineering + ablation
arms were rewritten to the v3 field names, its raw-balance leakage-control arm now reads the raw CSV
(not Gold), and the obsolete `event_step` overfitting probe (Part C) was removed.

## Test-set discipline (owner-flagged, data-centric)

A methodology review (against the Andrew Ng data-centric flow: Data → Split → Ablation on Train+Val
→ freeze features → Walk-Forward CV & Optuna → final Test) found the Test split was being read during
selection/tuning in three places:

1. nb09 ablation trained on Train but scored feature-selection arms on the **Test** period
   (`step > 631`) — feature choice was informed by Test.
2. nb10 ran model comparison, threshold reporting, PR/ROC curves and the budget table on **Test**.
3. Walk-forward `DEFAULT_CUTS=(360,440,520,600,680)` with width 55 produced fold windows up to step
   735 — inside the Test period — so CV and Optuna read Test.

Fixes: nb09 ablation now scores on **Val** (`(520, 631]`); nb10 does every comparison/metric/curve on
**Val**; `DEFAULT_CUTS=(360,420,480,540)` so the widest fold window is `(540,595]` (≤ `VAL_MAX_STEP`
= 631). Test (`step ≥ 632`) is now read exactly once, in nb12. Added
`test_default_cv_folds_never_enter_the_sealed_test_period` to lock this in.

## Implementation

- Added `src/pit_fintech/models/notebook_lab.py`: `resolve_lab_paths`/`LabPaths` (Silver
  `paysim_transactions` + `paysim_labels` + raw CSV), `load_modeling_frame` (v3 PIT features from
  Silver via the shipped SQL, no Gold read), `three_way_temporal_split`,
  `walk_forward_folds`/`WalkForwardFold`
  (with `usable`), `configure_lab_mlflow`, and shared constants (`DEPLOYABLE_CORE`, `PIT12`,
  `TRAIN_MAX_STEP=520`/`VAL_MAX_STEP=631`, `DEFAULT_CUTS`/`DEFAULT_TEST_WIDTH`, `LAB_EXPERIMENT`,
  `MLFLOW_LAB_TAGS`). The four notebooks call into this module instead of copy-pasting ~40-line setup
  blocks (CLAUDE.md: correctness/shared logic lives in `src/`).
- Optuna objective now builds folds via `walk_forward_folds(frame, cuts=DEFAULT_CUTS, embargo=0)` and
  returns the mean PR-AUC across usable folds — the same protocol nb10 reports the distribution of.
- Standardized MLflow across all four notebooks: `configure_lab_mlflow()` points at
  `settings.mlflow_tracking_uri`, experiment `paysim-notebook-modeling`, run tag
  `stage=fe|cv|optuna|shap`, keeping `surface=notebook-exploratory` / `manifest_backed=false` so lab
  runs never masquerade as promotable evidence.
- Added `tests/unit/test_notebook_lab.py` (5 tests: DEPLOYABLE_CORE subset, split partition,
  walk-forward cut/embargo bounds, production-realistic E=0, unusable single-class fold).
- Notebooks were rebuilt output-free via a scratchpad generator; outputs/execution_count stripped.
- Fixed `config.py` YAML resolution: `yaml_file` was CWD-relative, so a Jupyter kernel started in
  `notebooks/` missed the repo-root `config.yaml` and silently used the default
  `mlflow_tracking_uri=localhost:5000` (ConnectionRefused after the owner pointed the URI at the
  VPS). Now resolves CWD-first with a repo-root fallback, evaluated at `Settings()` construction so
  `chdir`-based test overrides still work. Verified from a `notebooks/` CWD that settings resolve
  `http://100.116.36.6:5000`. Kernel restart is required to clear the `get_settings()` lru_cache.

## Files touched

- Added: `src/pit_fintech/models/notebook_lab.py`, `tests/unit/test_notebook_lab.py`,
  `notebooks/10_walkforward_cv_split.ipynb`, `notebooks/11_optuna_tuning.ipynb`,
  `notebooks/09_feature_engineering_selection.ipynb`.
- Rewritten in place: `notebooks/12_shap_final_evaluation.ipynb` (setup/load/MLflow standardized).
- Deleted: `notebooks/09_feature_engineering_ablation.ipynb`,
  `notebooks/10_model_comparison_metrics.ipynb`, `notebooks/11_hyperparameter_tuning.ipynb`,
  `notebooks/13_walkforward_cv_validation.ipynb`.

## Verification

- `.venv/Scripts/python.exe -m pytest tests/unit/test_notebook_lab.py -q` — **5 passed**.
- `ruff check` + `ruff format --check` on the new module and test — clean.
- `python -m py_compile` on the module + test — OK.
- Every notebook: valid JSON, all code cells `compile()` without SyntaxError, output-free.
- No dangling references to the removed setup variables in 09/12.

## Deviations / known gaps

- Notebooks themselves were **not executed** (need the built lakehouse/Gold, heavy deps, and the
  hosted MLflow server); the agent does not run gates. Owner must run them end-to-end and confirm the
  runs land in the `paysim-notebook-modeling` experiment with the `stage` tags.
- Optuna trials use per-fold early stopping on the fold's own test window (mild optimism) — acceptable
  for an exploratory surface; the promotable path stays in `training/` with manifest + multi-seed.
- These notebooks remain exploratory/non-promotable by design (hard rule #4).

## Next steps (owner)

```powershell
.\make.ps1 test-unit          # includes test_notebook_lab
.\make.ps1 lint               # ruff over the new module + test
# then, with the lakehouse/Gold built and MLflow running (config.yaml mlflow_tracking_uri):
#   run notebooks 09 -> 10 -> 11 -> 12 in order; copy BEST_PARAMS + CHOSEN_THRESHOLD from 11 into 12
#   verify runs appear in experiment 'paysim-notebook-modeling' tagged stage=fe|cv|optuna|shap
```
