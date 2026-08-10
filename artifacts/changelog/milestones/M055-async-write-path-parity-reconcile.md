# M055 — Async write path; parity via `pit parity reconcile` (non-blocking)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T5/T6/T7, gates G6/G7 — makes the serving write path non-blocking

## Scope

Owner review (correct): running the offline DuckDB engine synchronously inside `apply_event_and_verify`
puts an expensive SQL computation on the `/score` request path, which **blocks every later request** —
unacceptable in a serving production path. ADR-009 is amended: the write path must be fast and
non-blocking; offline/online parity is verified **asynchronously** by a reconcile command that
compares the online aggregates against the offline DuckDB engine over the served Event History.

## What changed

### `docs/adr/009-parity-at-the-online-write-path.md` (accepted, amended)
- Decision 4 now states parity is verified **asynchronously, never on the request path**: the write
  path only transitions the aggregate and appends the Event History; `pit parity reconcile` runs the
  DuckDB engine afterwards. The two-path fan-out section clarifies the DuckDB computation is
  asynchronous, not inside `/score`. Consequences updated: the reconcile exports
  `pit_parity_mismatches_total`/`pit_parity_checked_total`.

### `src/pit_fintech/serving/online_state.py`
- `WritePathResult` no longer carries `parity_checked`/`parity_mismatches` — the write path does not
  run parity. `apply_event_and_verify` is reduced to: append to `winlog`, evict, recompute the
  post-event aggregate in Python, write log + aggregate under `WATCH`/`MULTI`/`EXEC`, then append the
  Event History (best-effort). No DuckDB, no offline engine on the request path.
- **New `ParityReconcileResult` + `reconcile_parity(store, artifact_root, event_history_path)`** —
  the async parity check. Reads the served Event History JSONL, groups by entity, reads each entity's
  online aggregate, runs `_duckdb_reference_over` (the offline DuckDB engine) at the aggregate's
  stored step, and counts mismatches with `count_parity_mismatches`. Reports `checked_entities`,
  `field_mismatches`, `missing_online`, `mismatched_entities`, `passed`, `details`.
- `_duckdb_reference_over` / `offline_post_event_reference` are retained for the reconcile / Locust
  harness (they are the offline engine, not on the request path).

### `src/pit_fintech/serving/app.py`
- `/score` write path no longer records parity: the `metrics.record_parity` call and the parity
  log/warning blocks are removed (the write path is non-blocking). `_MetricsState` drops the
  `pit_parity_*` counters; the `/metrics` text now only exposes the scoring counters. The
  `online_write` info log line remains (one structured line per write outcome).
- `telemetry.record_parity_check` is no longer called from serving (it is called by the reconcile
  CLI).

### `src/pit_fintech/cli.py`
- New `pit parity reconcile` command group: builds the Redis store, calls `reconcile_parity`, prints a
  report table + details, and best-effort exports `pit_parity_*` OTel metrics when
  `PIT_OTEL_ENDPOINT`/`OTEL_EXPORTER_OTLP_ENDPOINT` is set. Exits non-zero when parity fails.

### Make targets
- `Makefile` + `make.ps1`: new `parity-reconcile` target (`uv run pit parity reconcile`); documented
  in README command contract.

### `deploy/vps/`
- `README.md`: parity is verified asynchronously by `pit parity reconcile` (never on `/score`);
  parity counters reach Grafana through the OTel collector (with a note that Prometheus-backed panels
  need the collector's remote-write exporter wired).
- `grafana-dashboard.json`: the parity panel is retitled "Parity (async reconcile, ADR-009)" with a
  note that the authoritative pass/fail is `pit parity reconcile`.

## Commands + results

- Agent static analysis only: `python3 -m py_compile` passes on `online_state.py`, `app.py`, `cli.py`;
  all lines <= 100; dashboard JSON parses (5 panels); grep confirms no stale
  `write_result.parity_checked`/`parity_mismatches` references.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # then live, after traffic:
  .\make.ps1 redis-up
  .\make.ps1 serve           # /score is now non-blocking (no DuckDB on the request path)
  .\make.ps1 parity-reconcile  # async offline/online parity over the Event History
  ```

## Known gaps / next steps

- The Event History is written by the write path and consumed by `pit parity reconcile`, but it is
  not yet wired into the offline build (DuckDB → Gold Delta) to land live events into
  `gold.post_event_state_updates` — the "write to Gold Delta" sink of the two-path fan-out.
- `not_warm_started` guard (M053) still stands: a materialized entity whose winlog is empty is
  refused for live writes until its history is seeded (warm-start follow-up).
- Parity counters are exported via OTel (best-effort); getting them into a Prometheus-backed Grafana
  panel requires wiring the collector's remote-write exporter (documented in `deploy/vps/README.md`).
