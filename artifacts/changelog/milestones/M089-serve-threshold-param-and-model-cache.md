# M089 — Serving: read decision threshold from run param + local model cache (HF-hub style)

- 2026-08-24 — **implemented** (static gates pass locally: `ruff check` + `ruff format --check` +
  py syntax clean on the three changed src files). Owner-pending: a live `pit serving up` against
  `models:/paysim-fraud-rf/1` on the shared MLflow, confirming (a) the served threshold equals the
  nb05-selected value and (b) a restart is a cache hit (no re-download).

- 2026-08-24 — **amended (skip doomed artifact probes).** A live serve surfaced a multi-minute hang:
  serving tried to download `ordered_feature_names.json` (and, when the `threshold` param path did
  not short-circuit, `confusion_and_cost_curves.json`) — artifacts the colab RF track never logs —
  and over the home→VPS link MLflow retried for minutes before failing. Added
  `_list_run_artifact_names(run_id)` (one `MlflowClient.list_artifacts` metadata call) and pass the
  set into `_load_ordered_feature_names` / `_load_decision_threshold`; each now attempts an artifact
  download **only when the file is present**, otherwise uses `PAYSIM_MODEL_FEATURE_ORDER` / the
  `threshold` param / `0.5` with no transfer. The LightGBM track (which logs both files) is
  unaffected. Confirmed the hang's cause was the missing-artifact probe, not the network: `tailscale
  status` showed the desktop peer `direct` (not relayed).

## Scope / gate

Owner-directed, two changes on top of M088's serve-pull-by-id:

1. **Threshold contract tolerance (approach A).** The colab RF track logs the decision threshold as
   an MLflow **run param** `threshold` (via `log_rf_evaluation`), while the src LightGBM
   `train_candidate` pipeline logs it inside `confusion_and_cost_curves.json`. Serving only read the
   latter, so a pulled colab RF fell back to `0.5` — not the validated threshold (nb05 chose
   `0.90491`). `_load_decision_threshold` now reads the `threshold` run param first, then the
   LightGBM JSON, then falls back to `0.5`. The threshold is a serving input; hyperparameters are
   not (they are baked into the fitted trees and are lineage-only), so only the threshold gap
   produced wrong serving behaviour.
2. **Local model cache across restarts (HuggingFace-hub style).** `mlflow.sklearn.load_model`
   re-downloads model artifacts on every process start (MLflow has no persistent cross-restart cache
   by default). Serving now caches the pulled model under `serving_model_cache_dir/<run_id>` and
   loads from local disk on a cache hit; only a cache miss downloads from the registry.

Gate (owner-run): `.\make.ps1 lint` / `test-unit` green; then `pit serving up` with
`config.yaml: serving_model_uri = models:/paysim-fraud-rf/1` — first start logs a cache miss +
downloads; a second start logs `serving model cache hit`; readiness/model_version reflect the RF
run and the served threshold equals the nb05 value. Static locally: `ruff check` + `ruff format
--check` + `ast.parse` clean on `serving/app.py`, `config.py`, `cli.py`.

## Design decisions

- **Run param before artifact for the threshold.** Reading the `threshold` run param first makes
  serving tolerant of both producers without caring how the model was trained (M088 principle),
  and the param is guaranteed present on every colab RF run. Order: param → LightGBM JSON → `0.5`.
- **Cache key = backing MLflow run id.** A registry version resolves to exactly one run, so the run
  id is an immutable identity for the model bytes. `models:/name@alias` moving to a new version
  resolves to a different run id → a different cache entry, never a stale hit. `_resolve_run_id`
  still makes one small metadata call per start (not the big artifact download), which also keeps
  an alias current; the expensive model bytes are what the cache saves.
- **Cache hit detection = presence of an `MLmodel` file** (via `rglob`, tolerant of the two model
  URI shapes placing it at the cache root vs a `model/` subdir). A cache dir with no `MLmodel`
  (e.g. a partial/failed download) is treated as a miss and re-downloaded.
- **Default cache dir under the user home** (`~/.cache/pit-fintech/mlflow-models`), not a temp dir,
  because persistence across restarts is the whole point — mirrors HF's `~/.cache/huggingface`.
  `config.yaml: serving_model_cache_dir` overrides it.
- **Scope: pull-by-id + explicit-run-id branches only.** The champion-alias branch
  (`serving/model_loader.py: load_champion_model`) is a separate module and is not what the colab
  track uses; it keeps its own load path in this pass.

## Files touched

- `src/pit_fintech/serving/app.py`:
  - `ServingSettings.serving_model_cache_dir` (new field).
  - `build_scoring_context` resolves `cache_root` and routes the `serving_model_uri` and
    explicit-`mlflow_run_id` branches through the cached loader.
  - `_load_model_by_uri(..., cache_root=)` uses the cached loader (resolves run id first, then
    loads).
  - new `_resolve_model_cache_root()` + `_load_sklearn_model_cached()` helpers.
  - `_load_decision_threshold()` reads the `threshold` run param before the LightGBM JSON.
  - `_list_run_artifact_names()` (new) + both contract loaders take an `available` set and skip a
    download when the artifact is absent (no doomed slow probe).
  - `from pathlib import Path` added.
- `src/pit_fintech/config.py`: `serving_model_cache_dir` setting.
- `config.yaml`: `serving_model_cache_dir: null` key (+ comment). `serving_model_uri` set to
  `models:/paysim-fraud-rf/1` (owner, to serve the registered colab RF).
- `src/pit_fintech/cli.py`: `serving up` passes `serving_model_cache_dir` through to `ServingSettings`.

## Known gaps / next steps

- `ordered_feature_names.json` is still not logged by the colab track, so serving falls back to
  `PAYSIM_MODEL_FEATURE_ORDER`. That is safe here because nb05 trains on exactly those 10 features
  in that order, and `build_scoring_context` re-checks the result against the constant. A colab
  model trained on a different feature set/order remains non-servable by the v3 path (expected).
- The threshold param and the small contract JSONs (ordered_feature_names / confusion curves) are
  still read from the tracking server on every start; only the model bytes are cached. A fully
  offline restart is not a goal of this milestone (the local-fallback tracking URI covers a
  server-down start).
- A cache-hit still calls `_resolve_run_id` (one metadata request); if the shared server is down on
  a `models:/` URI, resolution falls to the configured local fallback tracking store.
- No gate has run against the shared MLflow from this workspace: owner runs the live serve + restart
  to verify the threshold value and the cache-hit log line.
