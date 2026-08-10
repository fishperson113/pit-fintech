# M057 — Warm-start the online write path from Gold (seed winlog; add `amount` to Gold post-event)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T5/T7 — closes the `not_warm_started` gap so live writes after
  materialize are applied and Event History / parity reconcile actually populate

## Scope

The `pit-online-worker` (ADR-010) refused live writes with `not_warm_started` whenever an entity
had a materialized aggregate but an empty event log (`winlog`), and false `noop_identical` when a
stale winlog contained an event that looked like a duplicate. Root cause: materialization wrote the
aggregate but **never seeded the winlog**. Fix: materialize now warm-starts each entity's winlog.

Owner review also corrected an earlier draft that read **Silver** to seed the winlog: that breaks
medallion layering (Silver = canonical, Gold = business-serving). The fix must let **Gold** serve the
need. Because `gold.post_event_state_updates` is already one row per source event but lacked the
per-event `amount`, the decision (option A) is to add `amount` to Gold and read Gold for warm-start.

## What changed

### `src/pit_fintech/features/build_offline.py`
- `POST_EVENT_STATE_SCHEMA` gains `GoldColumn("amount", "double", False)` (raw per-event amount,
  placed before `source_row_number`). It is not one of the nine contract fields; it exists so the
  online write-path warm-start can seed the winlog from Gold alone (medallion layering).
- `paysim_post_event_state_sql` SELECTs and GROUP BYs `c.amount`, so a Gold rebuild carries the
  per-event amount. The Gold build's `.select(POST_EVENT_STATE_SCHEMA)` keeps it.

### `src/pit_fintech/materialization/materializer.py`
- Warm-start now reads **Gold** (`gold_post_event`, the same table the materialization consumed),
  joined to the latest-per-entity rows, restricted to each entity's widest window (168h):
  `c.step >= l.step - 167 AND c.step <= l.step` (so the winlog holds every event the write path
  could still need, all within the materialization watermark). Removed the Silver read.
- During the batch write, for each WRITTEN or NOOP_IDENTICAL aggregate the entity's winlog is also
  written (`winlog_key`), so a re-materialize fills the winlog gap left by older code.
- `_build_winlog_by_entity` encodes per-entity `[step, knowledge_step, amount]` via `exact_money`
  (decimal-string amounts match the offline `DECIMAL(18,2)` sum exactly).

### No change
- The write path (`apply_score_event`) and parity reconcile are unchanged; this milestone just makes
  them reachable after materialize.

## Commands + results

- Agent static analysis only: `py_compile` clean on all changed Python files; all lines <= 100; no
  stale `_silver_source` reference remains in the materializer; integration tests are data-driven
  (schema constant compared against the committed table, so the added `amount` column is expected).
- **Owner run (verified):** after promoting the rebuilt Gold (`gold_post_event_version 7`) and
  `.\make.ps1 materialize`, the warm-start seeded winlogs for **2,722,362 entities** (`records_written
  0 / noop 2,722,362 / rejected 0` — the aggregates were already present from a prior materialize, so
  `NOOP_IDENTICAL` is expected, but the winlog was re-seeded). A `demo-score` at step 744 returned
  `feature_provider: pit-online-worker`, `feature_step: 743` (correct pre-decision). `.\make.ps1
  parity-reconcile` then reported **`passed yes, field_mismatches 0`** — the online aggregate
  (worker-maintained) matches the offline DuckDB reference computed over the same winlog. The first
  reconcile run in the session failed (4 fields) because it used the pre-fix code path (offline
  reference from Event History); the second run (fixed code) passed.
- **Important workflow:** Gold must be **rebuilt/promoted** with the new schema before
  materialize+warm-start can read `c.amount`. The existing committed Gold table (built before this
  change) lacks `amount` and would make the warm-start SQL fail with a missing-column error.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # rebuild Gold with the new schema, then materialize (which now seeds winlog):
  .\make.ps1 gold            # or promote an existing staged run
  .\make.ps1 promote-gold -RunId <run-id>
  .\make.ps1 materialize
  # then live:
  .\make.ps1 worker-up
  .\make.ps1 serve
  .\make.ps1 demo-score      # worker should now report written (not not_warm_started/noop)
  .\make.ps1 parity-reconcile  # now has entities to compare
  ```

## Refinement (same date) — promote failed on schema mismatch

Owner `promote-gold` over the committed Gold (built before the `amount` column) failed with
`SchemaMismatchError: Cannot cast schema, number of fields does not match: 18 vs 17` — the staged
table has 18 columns (new schema incl. `amount`) while the committed table still has 17.
`_write_gold_table` now passes `schema_mode="overwrite"` to `write_deltalake` so the committed Gold
schema can evolve. Safe here because the promote is a full-range rebuild (predicate covers every
partition, so every file is rewritten with the new schema); after the migration, incremental promotes
write the same schema, making `schema_mode="overwrite"` a no-op.

## Refinement — parity reconcile used the wrong event source

After warm-start + a live write, `pit parity reconcile` reported a false failure for
`C1470998563@744` (4 history fields disagreed). Root cause: `reconcile_parity` built the offline
DuckDB reference from the **Event History**, which only records live writes (the single event 744),
while the online aggregate was warm-started from Gold (the full 168h winlog). The two sides compared
different event sets. Fixed: the offline reference is now computed over the entity's **winlog** (read
from Redis) — the same event set the online aggregate was built from — at the aggregate's stored
step. `transaction_types` collection (now unused) removed. This is an engine-agreement check (online
Python vs offline DuckDB over the same events), which is what reconcile is meant to verify.

## Refinement — staleness_steps in the worker result

`apply_score_event` set `staleness_steps: None` in both the refused-write and accepted-write result
payloads, so `/score` responses carried `staleness_steps: null` even when `feature_status: fresh`.
Now computed like `read_online_features`: `staleness_steps = step - pre_step` when the pre-decision
vector has a stored step, else `None`. A fresh current write returns `0` (e.g. request step 744 over a
stored 744 aggregate).

## Known gaps / next steps

- Gold schema change means a **Gold rebuild/backfill** is required once (schema checksum changes);
  the frozen FeatureSpec v2 contract is unchanged.
- Event History is still not wired into the offline build (DuckDB -> Gold Delta) to land live events
  into `gold.post_event_state_updates`; `pit parity reconcile` remains the async parity path.
- `reset_online_log`/`reset_online_store` use `SCAN`, which the owner's custom Redis build reports
  as `unknown command`; reset by `DEL` of the specific keys until that is resolved.
