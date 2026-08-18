# M073 — Feature & model validity notebooks (nb09–nb13) + findings report

- **Datetime:** 2026-08-18
- **Status:** implemented (agent code + owner-run MLflow evidence); **exploratory / non-promotable**
  — no promotion gate claimed. Numbers are learning/steering evidence on PaySim (AMBER), not a
  contract verification.
- **Scope / gate:** stand up the Sprint 3 "data → feature → model validity" investigation as
  exploratory notebooks that log to MLflow (`pit-fintech-notebook-exploration`,
  `manifest_backed=false`), and write a findings report. Owner ran every notebook; agent read the
  MLflow runs + notebook outputs and interpreted.

## What was built

- **nb09 — feature ablation** (natural prevalence; relative signal): leakage-control arm, event_step
  overfit probe, leave-one-out / additive ablation, gain-share. Reproducibility fixed earlier
  (`ORDER BY source_row_number` + `force_row_wise`).
- **nb10 — LightGBM vs XGBoost** (fair config): temporal 3-way split, `scale_pos_weight=√(neg/pos)`,
  matched `reg_lambda=1.0`; metric primer (PR-AUC/ROC/logloss/Brier/precision@k/recall@FPR);
  reproducible ×2. MLflow: parent `nb10-model-comparison` + nested per model.
- **nb11 — Optuna tuning** (30 trials, TPE seeded) + threshold tuning (FPR=1% / max-F1 /
  precision≥target). MLflow: parent `nb11-tuning` + nested per trial. `scale_pos_weight` held at √
  (not tuned) to avoid the saturation bug.
- **nb12 — final test eval + SHAP** using tuned params + val-selected threshold. SHAP via
  **LightGBM native `pred_contrib=True`** (no `shap`/`numba` dependency — numpy 2.4 makes `shap`'s
  numba unresolvable), with matplotlib beeswarm fallback; 3-source importance cross-check
  (SHAP/gain/permutation). MLflow: `nb12-final-eval` + `importance_compare.csv` artifact.
- **nb13 — walk-forward CV** (5 temporal folds) + embargo (E=0 vs 168) + warm/cold entity slices.
  MLflow: parent `nb13-walkforward-cv` + nested per fold (warm/cold is display-only).
- **docs/reports/sprint-3-feature-model-validity-findings.md** — consolidated findings report (VN).

## Owner-run MLflow evidence (experiment `pit-fintech-notebook-exploration`)

- **nb10:** LightGBM test PR-AUC **0.3762**, XGBoost **0.3652** (fair; reproducible across two runs).
  log_loss ~0.17 after the √ fix (was 9.39 under full-ratio saturation).
- **nb11:** baseline val PR-AUC **0.30006** → best **0.31117** (+0.011). Best params
  `n_estimators=500, learning_rate=0.023, num_leaves=38, max_depth=6, min_child_samples=100,
  subsample=0.687, colsample_bytree=0.768, reg_lambda=5.30`.
- **nb12:** test PR-AUC **0.3768** (untuned 0.3762 → +0.0006: tuning did NOT transfer to test).
  @thr 0.595: TP 396 / FP 472 / FN 856; precision 0.456, recall 0.316. Budget: top 0.5% precision
  1.00 recall 15.1%; top 1% precision 0.749 recall 22.7%.
- **nb13 Part 1:** E=0 mean PR-AUC **0.379 ± 0.107** (range 0.28–0.51), E=168 **0.367 ± 0.111**,
  Δ(168−0) = **−0.0125** (small → low near-boundary dependence).
- **nb13 Part 2 (warm/cold):** warm **0.408 ± 0.043** vs cold **0.350 ± 0.124**; on lift, warm >
  cold in every fold (cold recipients have all `pit_prior_*` = 0).
- **nb09 (natural prevalence, relative deltas):** leakage arm PR-AUC **0.8827** (true signal in
  forbidden balance cols); dropping `event_step` 0.045 → 0.092 (gain-share 0.298, train/test step
  overlap = 0); `current_amount` gain-share 0.431; has_history flags ≈ 0 gain (redundant).

## Decisions + rationale

- **12 stored → 7 deployable *feed* set** (drop `event_step`, `pit_prior_count_168h`, three
  `recipient_has_history_*`). This is a model-input choice, **reversible**, and does NOT touch the
  frozen FeatureSpec `paysim-fraud-recipient-v2`; removing a stored feature would need ADR + v3 +
  backfill (deferred, Track B).
- **`scale_pos_weight = √(neg/pos)`, not full `neg/pos`.** Full ratio (~458) saturated probabilities
  (log_loss 9.39); √ (~20.5) restored calibration (0.17) with equal ranking. Applied consistently in
  nb10–nb13; supersedes nb10's earlier rough CV cell that used the full ratio.
- **SHAP via LightGBM native TreeSHAP**, not the `shap` library. `shap` pulls `numba`/`llvmlite`
  which cannot resolve against `numpy>=2.4` on Python 3.11; native `pred_contrib=True` gives exact
  TreeSHAP with zero new deps. `optuna` added to `dev` group (pure-python, safe); `shap` intentionally
  NOT added to the lock.
- **Embargo reframed** (owner challenge): it does NOT protect against future leakage (labels are
  point-in-time, nothing to purge). It measures near-time sample dependence; warm/cold measures
  entity dependence. Purged-Group time split is not adopted (production re-scores recurring
  recipients); entity dependence is measured via warm/cold instead of hard group-splitting.

## Files touched

- `notebooks/09_feature_engineering_ablation.ipynb` (modified), `10_model_comparison_metrics.ipynb`,
  `11_hyperparameter_tuning.ipynb`, `12_shap_final_evaluation.ipynb`,
  `13_walkforward_cv_validation.ipynb` (new), plus `07_feature_correlation.ipynb`,
  `08_paysim_eda.ipynb` (new, EDA).
- `docs/reports/sprint-3-feature-model-validity-findings.md` (new report),
  `docs/reports/sprint-3-feature-model-validity-plan.md` (plan, added earlier this session).
- `pyproject.toml` / `uv.lock` — `optuna>=4.9` added to `dev` group (owner ran `uv add`/`uv sync`);
  ruff `per-file-ignores` for `notebooks/*.ipynb` extended to `E402,E501,E702,F401,I001` (EDA
  surfaces; `src/`/`tests/` stay strict).

## Commands + results

- Owner ran each notebook (Run All) in the `.venv`; agent read results from MLflow REST
  (`/api/2.0/mlflow/runs/search`, experiment id 6) and from notebook cell outputs (warm/cold).
- nb10 and nb13 Part 1 reproduced bit-for-bit across two runs (determinism confirmed).
- No `lint`/`test` gate run under this milestone (notebooks are EDA surface; correctness lanes
  unchanged). Regression lanes not claimed.

## Deviations

- `shap` could not be installed (numba vs numpy 2.4); pivoted to native TreeSHAP. `optuna` landed in
  `pyproject.toml` via `uv add` before the combined command failed on `shap`; reconciled with
  `uv sync`.
- nb09 runs at natural prevalence (relative deltas only); its absolute PR-AUC (~0.045) is not
  comparable to nb10–13 (~0.38, √-weighted). Only within-notebook ordering is read.

## Known gaps / next steps

- Notebooks currently carry outputs (owner ran them); **must be cleared before commit** (output-free
  in git, hard rule #4).
- Move harness baseline/ablation into `src/pit_fintech/training/` with a deterministic experiment
  manifest + multi-seed to firm up the ±std; notebooks stay EDA-only.
- Fill `SlicedMetrics` (`population / cash_out_warm / cash_out_cold / transfer_cold`, ADR-002) —
  nb13 warm/cold is the seed.
- Decide **Track B** cold-start features (ADR + FeatureSpec v3 + backfill) — the real quality lever.
- Optionally log nb13 warm/cold to MLflow (display-only today).
- Governance: this milestone ships with `PROJECT_STATUS.md` + `CHANGELOG.md` updates in the same
  commit (this file is one of the three).
