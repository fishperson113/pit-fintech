# M053 — Implement ADR-009: read aggregate, write-path parity, telemetry

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T5/T6/T7, gates G6/G7 — implements ADR-009

## Scope

Turn ADR-009 into code: the serving read path returns to the materialized aggregate
(`RedisFeatureProvider`), the write path transitions the aggregate to post-event state and
**parity-checks it at write time**, and the parity observation is surfaced through telemetry
(Prometheus + Tempo) so it is verified at runtime, not by a unit test.

## What changed

### `serving/online_state.py` — write path = aggregate transition + parity
- Removed the read-time recompute (`read_window_state`/`read_window_features`) and the
  `apply_event` append-only path.
- **New `apply_event_and_verify(...) -> WritePathResult`** — the ADR-009 write path. Under
  `WATCH`/`MULTI`/`EXEC` (optimistic lock, retry on `WatchError`) it:
  1. reads the entity's `winlog` event log + the materialized aggregate;
  2. applies the deterministic guards — `not_warm_started` (materialized aggregate exists but the
     log is empty → refuse loudly, never silently drop history), `rejected_older`
     (`step < stored.feature_step`), `noop_identical` (exact duplicate);
  3. appends, evicts (168h), recomputes the **post-event** aggregate at `step` via
     `compute_window_features(cutoff_step=step + 1)` (the `GOLD_SHIFT_RELATION` shift);
  4. computes the independent offline reference (`_oracle_reference_over` → the pure-Python oracle
     `paysim_reference.compute_paysim_feature_row` at cutoff `step + 1`) and counts mismatches with
     `count_parity_mismatches` (integer-exact, float tolerance `1e-6`);
  5. writes the log + the new aggregate in one transaction.
- `offline_post_event_reference(...)` — public helper computing the oracle reference over the
  store's current log (used by the Locust harness).
- `WritePathResult` records `outcome`, `feature_step`, `parity_checked`, `parity_mismatches`,
  `log_length`, `write_latency_ms`, `detail`.

### `serving/feature_provider.py` — read path back to the aggregate
- Removed `WindowStateFeatureProvider`; `build_feature_provider` no longer accepts `kind="window_state"`.
- `RedisFeatureProvider` is the only wired adapter (ADR-009: read-time recomputation is an
  anti-pattern). Module/ABC docstrings updated.

### `serving/app.py` — wire the write path + parity telemetry
- `build_scoring_context` builds `kind="redis"`.
- `/score` write path calls `apply_event_and_verify`; on parity mismatches or a refused write it
  logs (structured, with request context) and records telemetry — never fails an already-computed
  score.

### `serving/telemetry.py` — parity observation
- New `record_parity_check(checked, mismatches)`; new counter `pit_parity_checked_total`.
  `pit_parity_mismatches_total` is incremented with the field mismatch count.

### `scripts/locust_parity.py` — parity check is now post-write aggregate vs oracle
- `check_parity` compares, per entity, the stored aggregate (`read_online_features`) against
  `offline_post_event_reference` at the stored step, using `count_parity_mismatches`. Removed the
  now-unused `_CHECKPOINTS` and `Decimal` import.

### `tests/unit/test_online_write_path.py` — pure logic
- `compute_window_features` shift relation, late-arrival knowledge-time predicate, window eviction,
  `count_parity_mismatches` rules (integer-exact / float tolerance), contract-order emission.

### `deploy/vps/grafana-dashboard.json`
- New "Write-path parity (ADR-009)" timeseries panel: `rate(pit_parity_checked_total[5m])` and
  `rate(pit_parity_mismatches_total[5m])`.

### `tests/e2e/test_sprint2_e2e.py`
- Docstring now references `apply_event_and_verify` / write-path parity (ADR-009).

## Commands + results

- Agent static analysis only: `python3 -m py_compile` passes on all changed Python files; the
  Grafana dashboard JSON parses (5 panels); grep confirms no stale references to
  `read_window_state`/`read_window_features`/`WindowStateFeatureProvider`/`window_state`.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # then live, with Redis up + a trained model + materialized Gold:
  .\make.ps1 redis-up
  .\make.ps1 materialize        # warm the aggregate store (G5 path)
  .\make.ps1 serve-otel         # reads aggregate, write-path parity on each /score
  # fire the demo/locust stream, then check Grafana:
  #   - parity panel shows checks/s and mismatches/s (pit_parity_*)
  #   - Tempo shows score -> online_write spans
  ```

## Known gaps / next steps

- The `not_warm_started` guard means a live write to an entity that was materialized but whose
  event log is empty is refused until its history is seeded. The materializer currently writes only
  the aggregate (not the `winlog`), so a full warm-start (seed recent events per entity) is a
  follow-up before live writes are meaningful against a real materialized store.
- `SqliteFeatureProvider`/`FeastFeatureProvider`/`UpstashFeatureProvider` remain round-0 skeletons
  (unchanged).
- The parity compare uses the serving-owned `winlog` as the source for the oracle reference; a
  fully independent parity harness would recompute the reference from Gold/Silver instead. Recorded
  as a known limitation, not a silent shortcut.
