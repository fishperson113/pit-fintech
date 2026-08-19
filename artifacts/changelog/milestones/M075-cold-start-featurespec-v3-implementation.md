# M075 — Implement ADR-011 cold-start FeatureSpec v3 (contract + engines + Gold + serving + tests)

- 2026-08-19 — **implemented** (agent-run pytest lanes green + ruff clean + fixture rebuilt;
  owner `.\make.ps1` gates + full backfill/serving still pending).

## Scope / gate

Land the ADR-011 v3 contract as one coordinated change set (import-time guards red-bar the suite
until every consumer moves together). Owner gates for verification: `.\make.ps1 lint`,
`test-temporal`, `test-unit`, `test-lakehouse`, then the Track-B backfill runbook
(`docs/reports/sprint-3-track-b-cold-start-v3-plan.md` §5) and the online rollout.

## What changed (v2 → v3)

Frozen `paysim-fraud-recipient-v3` / `paysim-fraud-scoring-v3`, 10 model fields (was 12):
- **Dropped** `event_step`, `pit_prior_count_168h`, `recipient_has_history_{1h,24h,168h}`.
- **Added** `pit_distinct_senders_24h/168h` (fan-in = `COUNT(DISTINCT origin_entity_id)`) and
  `pit_steps_since_last_event` (recency, default sentinel `PAYSIM_RECENCY_SENTINEL_STEPS=999`).
- Entity, scope, temporal semantics, `DECIMAL(18,2)` money, derived timestamps, and the forbidden
  balance/label set are unchanged.

## Files touched

**Contract / engines / oracle:** `features/paysim_specs.py` (v3 specs, sentinel),
`features/paysim_reference.py` (oracle: `origin_entity_id` on `PaySimSourceEvent`, spec-driven
alignment, v3 compute), `features/paysim_recipient.py` (v3 pre-decision SQL: distinct + recency +
`origin_entity_id` source col; leakage `STRICT_PIT_FEATURE_COLUMNS` decoupled to its own v2 shape),
`features/build_offline.py` (v3 pre/post Gold schemas, `origin_entity_id` on post-event for winlog
seeding, v3 post SQL + shift-relation recency, alignment guard), `models/paysim_gold.py` (E1-E4
v3 join).
**Training / serving / materialization:** `models/paysim_training.py` (Silver E1/E4 cohort SQL → v3),
`models/paysim_lightgbm.py` (M016 spike columns decoupled to frozen v2 evidence),
`training/dataset.py` (drop `event_step`), `serving/scoring.py` (`derive_request_features` drops
`event_step`), `serving/online_state.py` (winlog `LoggedEvent.origin_entity_id`, 4-tuple
serialization, v3 `compute_window_features`, DuckDB-ref origin, `apply_score_event`/
`append_event_history` thread origin), `serving/events.py`+`worker.py`+`app.py` (publish/consume
`origin_entity_id` from `ScoreRequest.name_orig`), `materialization/materializer.py` (warm-start
seeds origin, `_contract_defaults` recency sentinel).
**Feast / config / cli:** `feature_repo/definitions.py` (v3 objects), `config.py` (service default),
`.env.example`, `cli.py` (title).
**Tests:** `tests/unit/test_paysim_feature_contract.py`, `tests/unit/test_online_write_path.py`,
`tests/temporal/test_paysim_oracle_sql_parity.py` (recipient engine **repointed** from the leakage
table to the real `paysim_pre_decision_feature_sql`; v3 expectations), `tests/temporal/
test_injected_pit_fixtures.py`, `tests/integration/{test_gold_partition_overwrite,test_paysim_lakehouse,
test_paysim_fixture,test_gold_offline_features,test_feast_registry_g1}.py`.
**Regenerated committed fixture** (`data/fixtures/paysim_*.parquet|json|jsonl`) via
`pit data build-fixture --dataset paysim` (deterministic; 15 source / 11 feature rows).

## Commands + results (agent-run via `uv run --frozen`)

- Import-time alignment asserts pass on every changed module.
- **Runnable parity proof:** oracle == `paysim_pre_decision_feature_sql` (0/10 field diffs on a
  hand-built fan-in/recency/cold scenario); shift relation holds — offline post SQL == oracle(cutoff
  s+1) == online `compute_window_features(s+1)` (0 diffs).
- `pytest tests/temporal` **73 passed**; `tests/unit` **110 passed**; `tests/integration`
  **21 passed** (run separately: the pre-existing duplicate `test_paysim_fixture.py` basename blocks
  a combined collection, M058).
- `ruff check` **All checks passed**; `ruff format --check` clean.
- Contract checksum recomputed (v3): `paysim_feature_contract_checksum()` prefix `33e8a839816fa13f…`.

## Deviations / known gaps / next steps

- **Owner still runs the real gates** (`.\make.ps1 lint/test-temporal/test-unit/test-lakehouse`) to
  confirm; agent-run pytest is evidence, not the owner gate (hard rule #1/#2).
- **No Gold rebuilt / no champion trained yet.** The committed Gold Delta is still v2; the v3 FULL
  backfill (plan §5) + winlog reset/re-warm-start + `parity-reconcile` + a v3 champion (M079) are the
  remaining steps. v2 metrics do NOT carry to v3 (hard rule #5).
- **Served-event candidate path** (`served_event_pipeline.py`, `served-events-gold-candidate-v1`) is
  self-versioned and left at its v2 shape; wiring origin through Event History → Bronze/Silver into a
  v3 candidate is deferred.
- ADR-011 stays **proposed** until the owner-run Gold/lakehouse gates pass, then → accepted.

## Follow-up 2026-08-19 — schema-migration promote fix + backfill progress logging + v3 rollout ordering

- **Promote crashed on the v3 schema change.** After the (real, ~24 min) v3 build staged correctly
  (`backfill-0282a5a6…`, pre_checksum `5bb7b942…`, post_checksum `50e5171d…`,
  future_read_violations=0), `promote_staged_gold` → `_write_gold_table` raised
  `DeltaError: Schema error: No field named recipient_has_history_168h`. Root cause: the write used
  `mode="overwrite"` with a partition `predicate` (`replaceWhere`) + `schema_mode="overwrite"`; a
  predicate-scoped overwrite reconciles the untouched partitions against the old v2 schema and
  cannot drop a column. Fix: `_write_gold_table` reads the committed schema and, when it differs
  from the canonical schema (a contract-version migration, always a full-range promote), does an
  **unpredicated** full overwrite so `schema_mode="overwrite"` swaps the schema cleanly; the
  same-schema path keeps the predicate overwrite for incremental ranges. Delta's atomic write meant
  the crash left committed Gold untouched (still v2), and the staged v3 tables survived (staging is
  cleaned only after a successful commit), so recovery does not require re-running the 24-min build —
  `promote-gold --run-id backfill-0282a5a6…` re-promotes the existing staging under the fix.


- **Backfill was silent on a FULL build.** `execute_backfill` called `build_offline_features` and
  `promote_staged_gold` without their `progress` flag, so a ~25-minute FULL build printed only the
  `offline.backfill.started` line. Added a `progress: bool = False` param to `execute_backfill`,
  forwarded to both calls; `cli.py backfill run` passes `progress=True`. Now emits `[gold +Ns]` /
  `[promote +Ns]` phase reports (read Silver, pre/post query, future-read audit, write staging,
  shift-relation, promote), matching `build-gold`/`promote-gold`. Default stays off so the tests and
  the late-arrival guard (`execute_backfill` at L1076/L1167) print nothing.
- **Owner-run rollout uncovered a manifest-versioning ordering bug in my earlier runbook.** The
  first v3 FULL backfill short-circuited to the 2026-08-13 **v2** run (`backfill-6e18d533…`,
  `feature_definition_version=paysim-fraud-recipient-v2`, checksum `01bba24c…`) because
  `plan_backfill` derives the idempotency key's `feature_definition_version` from the **Silver
  lakehouse manifest** (state_machine L263), which was still stamped v2. Symptom surfaced at
  `materialize`: `BinderException: post_distinct_senders_24h not found` (Gold post still v2). Fix:
  `build-lakehouse -Dataset paysim` first to re-stamp the manifest (Silver v8,
  `feature_definition_version=paysim-fraud-recipient-v3`, checksum `33e8a839…`); the backfill then
  computed a fresh key `0794136…` (`source_silver_version=8`) and built Gold v3 for real. My earlier
  "no Silver rebuild needed" guidance was wrong for a contract-version bump and is corrected in the
  plan §5 runbook.
