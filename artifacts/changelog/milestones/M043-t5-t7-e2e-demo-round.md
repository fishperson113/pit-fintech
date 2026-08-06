# M043 — T5 materialization (Redis backend), T7 serving, CLI/Make wiring and e2e demo round

- Date: 2026-08-06
- Status: **implemented, verified on happy path** (NOT claimed: gates G5/G7/G9 pass — there is no
  test lane pinning their criteria yet; the e2e tests in `tests/e2e/` are still skipped).
- Scope: close the Sprint 2 online path on the happy path — materialize Gold post-event state into
  Redis (T5), serve it through FastAPI (T7), wire CLI + Make targets + one demo script, and prove
  the chain end to end on the real lakehouse. Backend: Redis only; SQLite, G8 recovery and the
  Feast PushSource path stay NotImplementedError.

## Context

- The Gold tables were committed at v6 (`post_event_state_updates`, 6,362,620 rows, step 1..743,
  2,722,362 distinct destinations). T4 training is deterministic on them (M041: two runs, both
  `test_pr_auc 0.362883`).
- All of this round's work lives in the working tree, **uncommitted** at the time of writing:
  `src/pit_fintech/materialization/{records,materializer}.py`,
  `src/pit_fintech/serving/{schemas,feature_provider,scoring,app}.py`, `cli.py`, `Makefile`,
  `make.ps1`, `scripts/run_demo_e2e.py`.

## Changes

### T5 — materialization (`materialization/records.py`, `materialization/materializer.py`)

- `records.py`: `online_record_key()` implemented (template format + `:` guard); new
  `online_watermark_key()` / `online_run_key()` helpers. Dataclasses, enums and the three key
  templates are unchanged.
- `materializer.py`:
  - `OnlineStoreConfig` gains `host/port/db` defaults `127.0.0.1/6379/0` (match `compose.yaml`);
    `uri` kept for the run result's `store_uri`.
  - Backend is Redis only; the redis-py client is built inside function bodies (optional
    dependency group). SQLITE raises NotImplementedError.
  - `materialize_to_watermark()`: reads `gold.post_event_state_updates` through
    `DeltaTable(path, version).to_pyarrow_table()` + DuckDB (path resolved via
    `build_offline.gold_table_path`, snapshot prefix from the lakehouse manifest; version pinned
    once at run start). Filters `step <= watermark`, keeps the latest row per entity with
    `row_number() OVER (PARTITION BY destination_entity_id ORDER BY step DESC, source_row_number
    DESC)`. The nine `post_*` fields are renamed through `POST_EVENT_TO_CONTRACT_FIELD` (the single
    crossing point; never hand-typed). Writes go through Redis pipelines in batches of 5000, each
    candidate evaluated by `evaluate_write` against the stored value (MGET first). Watermark key is
    written last; run key and a run manifest (`<artifact_root>/runs/<run_id>/materialization-
    manifest.json`) are also written. Progress prints `[materialize +Xs] <viec>` every 10 s / at
    milestones. Returns a fully populated `MaterializationRunResult`.
  - Stored value is one JSON string per key with dataclass field names; the three amount fields
    are serialized as decimal strings (never binary floats), so `float(str(v)) == v` exactly.
  - `evaluate_write()`: REJECTED_FUTURE (`feature_step > watermark`), REJECTED_OLDER
    (`incoming < stored` by feature_step), NOOP_IDENTICAL (same service version + feature_step +
    values), REJECTED_VERSION_MISMATCH, else WRITTEN.
  - `write_record()`: atomic per key via Redis WATCH/MULTI/EXEC with WatchError retry.
  - `read_online_features()`: MISSING -> contract defaults (counts 0 / amounts 0.0) with
    `status="missing"`; FRESH when `request_step - feature_step <= stale_after_steps` (default 1),
    else STALE. `read_watermark()` / `reset_online_store()` (SCAN-scoped to the
    `pit:<feature_service_version>:` prefix, never FLUSHDB) implemented.
  - `rematerialize_after_reset()` and `push_to_feast_online_store()` remain NotImplementedError
    with an explicit out-of-scope comment.
  - `source_checksum` hashes the record payloads with run-local metadata
    (`written_at`, `materialization_run_id`) excluded, so the same Gold version + watermark always
    yields the same checksum. (First version hashed everything and drifted between runs; caught
    during verification, fixed, and re-proven stable.)

### T7 — serving (`serving/schemas.py`, `serving/feature_provider.py`, `serving/scoring.py`, `serving/app.py`)

- FastAPI app with exactly four routes: `POST /score`, `GET /health/live`, `GET /health/ready`,
  `GET /metrics`.
- Model loaded with `mlflow.sklearn.load_model("runs:/<run_id>/model")`; default run is the newest
  FINISHED run of experiment `pit-fintech-gold-training`
  (`8f9c709782704f1eba89cc9e3fde83c1` for the demo round; `model_version` = the MLflow run id).
- No model registry yet: `deployment_id=None` (G11 promotion/rollback is not met).
- Decision threshold read from the run's `confusion_and_cost_curves.json` (fallback 0.5 with a
  logged warning).

### CLI / Make / demo

- `pit materialize run --watermark N` and `pit materialize show`; `pit serving up [--host] [--port]`.
- Make targets: `materialize`, `serve`, `demo`, `redis-up`, `redis-down` (plus existing
  `up-core`); `scripts/run_demo_e2e.py` drives Redis check -> Gold check -> materialize
  (skippable with `--skip-materialize`) -> serve -> score 3 cases -> tear down.

## Verification (all local, Windows, 2026-08-06)

- Ruff: `ruff check src/ scripts/` -> All checks passed; format clean.
- Unit: `pytest -q tests/unit` -> 87 passed. Temporal: `pytest -q -m temporal tests/temporal` ->
  73 passed.
- Real materialization on committed Gold v6 (Redis container up):
  - watermark 24: 249,521 records written in 32.3 s, all WRITTEN, max feature step 24; watermark
    read back as `(24, 2020-01-02T00:00:00Z)`; 3 sample reads + MISSING + STALE probes correct
    (defaults 0/0.0, `staleness_steps` computed from steps).
  - watermark 743 (full): 2,722,362 entities considered, 2,527,816 written / 194,546 NOOP /
    0 rejected in 384.8 s; watermark `(743, 2020-01-31T23:00:00Z)`; entities count matches the
    Gold distinct-entity count exactly; 2,722,362 record keys in Redis after the run.
  - Idempotence: re-running watermark 24 produced 0 written / 249,521 NOOP, same outcome counts;
    a two-run checksum probe on a throwaway keyspace produced identical `source_checksum`
    (`a8bf4b6e...` both runs) and `reset_online_store` removed exactly 249,523 keys (records +
    watermark + run key), proving the namespace-scoped reset.
- Demo (`scripts/run_demo_e2e.py --skip-materialize`, store already at watermark 743): 3/3 cases
  PASS, total 41.95 s. Observed values:
  - case A: entity C1470998563, step 744 -> `feature_status="fresh"`, staleness 1,
    `fraud_probability 2.2674930319146938e-05`, `decision_threshold 0.17100957808137637`;
  - case B: same entity, step 1243 -> `stale`, staleness 500;
  - case C: `name_dest=C0000000000` (unknown entity) -> `missing`, nine history fields all 0.

## Limits (what is NOT done — stated honestly)

- **No gate claim.** G5 (materialization) / G7 (serving) / G9 (e2e) are NOT declared passed: the
  `tests/e2e/test_sprint2_e2e.py` lane (12 tests) is still skipped and no test pins these
  criteria. Status is "verified on happy path" only.
- T6 offline/online parity is not done; no parity report exists.
- `OnlineStoreKind.SQLITE`, `rematerialize_after_reset()` (G8), `push_to_feast_online_store()`
  (Feast PushSource) remain NotImplementedError.
- No real model registry: `model_version` is the MLflow run id, `deployment_id=None`, G11
  promote/rollback not met.
- Serving depends on a reachable MLflow tracking server holding the run (default
  `http://localhost:5000`, the Docker MLflow service); the demo run used
  `8f9c709782704f1eba89cc9e3fde83c1`.
- Work is uncommitted in the working tree at the time of writing; this log will be committed
  together with it by the user.
- NOOP records keep their original payload (including an older `materialization_watermark_step`)
  by design: "NOOP khong ghi lai" — the global watermark key is authoritative.
- Demo entity is picked dynamically (the max-`step` row at or before the watermark); on Gold v6
  that is C1470998563 at step 743.
