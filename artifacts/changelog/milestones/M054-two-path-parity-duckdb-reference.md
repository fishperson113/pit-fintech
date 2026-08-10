# M054 — Two-path fan-out: event flows to online AND offline; parity via DuckDB engine

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T5/T6/T7, gates G6/G7 — corrects M053's parity reference and wires
  the offline path of ADR-009

## Scope

Owner review corrected M053: saying "the event never touches the offline path" contradicts the
architecture in AGENTS.md, which routes the served event into the offline store. After scoring, the
event must fan out to BOTH paths — online (winlog → Redis aggregate) and offline (Event History →
DuckDB compute → Gold Delta) — and parity is the check that the two independent engines agree.
M053's parity reference was a pure-Python oracle running inside serving; the correct reference is
the actual offline **DuckDB SQL engine**.

## What changed

### `docs/adr/009-parity-at-the-online-write-path.md` (accepted, updated)
- New **"Two-path fan-out"** section: after scoring, event `t` fans out to ① the online write path
  (append to winlog → recompute → Redis aggregate) and ② the offline write path (append to Event
  History → DuckDB compute → Gold Delta). Parity = online (winlog / Python `compute_window_features`)
  vs offline (DuckDB `paysim_post_event_state_sql`) on the same event set.
- Clarified the parity reference is the **DuckDB SQL engine** (the actual offline implementation),
  not a pure-Python oracle duplicated on the serving path. The oracle stays the project's
  correctness ground truth (it verifies the DuckDB engine offline, in
  `tests/temporal/test_paysim_oracle_sql_parity.py`).
- "Write to Gold Delta" is the offline sink: the Event History is what a later materialize/build
  consumes to land live events into `gold.post_event_state_updates`; a Delta commit per request is
  intentionally not on the online request path.
- Consequences updated to match.

### `src/pit_fintech/serving/online_state.py`
- **Parity reference switched from pure-Python oracle to the DuckDB SQL engine.**
  `_oracle_reference_over` / `_events_to_oracle_pool` removed; new `_duckdb_reference_over(events,
  entity_id, step, knowledge_step)` registers the event list as a DuckDB relation, runs
  `paysim_post_event_state_sql("evt")`, filters to the current event row
  (`step = <step> AND knowledge_step = <knowledge_step>`), and maps `post_*` → contract names via
  `POST_EVENT_TO_CONTRACT_FIELD`.
- `offline_post_event_reference` (used by the Locust harness) now uses the DuckDB reference too.
- **New `append_event_history`** — appends one served event to the offline-visible append-only
  Event History at `<artifact_root>/event_history/served_events.jsonl` (gitignored runtime
  artifact), the record the offline DuckDB path consumes.
- `apply_event_and_verify` gains a `transaction_type` param; on an accepted write it computes the
  DuckDB reference for parity and, after the Redis transaction commits, appends to Event History
  (best-effort — a file-write failure logs a warning, never fails the score). Module docstring
  rewritten for the two-path fan-out.

### `src/pit_fintech/serving/app.py`
- `/score` passes `transaction_type=payload.transaction_type` to `apply_event_and_verify`.

### `tests/unit/test_online_write_path.py`
- New `test_duckdb_offline_reference_matches_online_compute` — the DuckDB engine and the online
  Python computation agree on the same events.
- New `test_duckdb_offline_reference_respects_knowledge_time` — both engines apply the
  knowledge-time predicate identically (a late event with `knowledge_step` above the cutoff is
  excluded from the window by both).

## Commands + results

- Agent static analysis only: `python3 -m py_compile` passes on `online_state.py`, `app.py`, the
  test; all lines <= 100; grep confirms no stale `_oracle_reference_over`/`_events_to_oracle_pool`
  references. The sandbox could not install `duckdb` (no network), so the DuckDB reference was
  verified by analysis against `paysim_post_event_state_sql` semantics (identical window bounds and
  knowledge predicate as `compute_window_features` at cutoff `step+1`); pytest pending the owner.
- **Owner run (2026-08-10):** `.\make.ps1 test-unit` **73 passed** — including the two new
  DuckDB-vs-online tests, confirming the offline DuckDB engine agrees with the online Python
  computation (and the knowledge-time predicate) on real `duckdb`. `.\make.ps1 lint` then caught one
  B905 (`zip()` without explicit `strict=` at `_duckdb_reference_over`); fixed with
  `zip(..., strict=True)` — no behaviour change.
- **Refinement (same date):** a follow-up owner `test-unit` run failed both DuckDB tests with
  `_duckdb.InvalidInputException`: DuckDB replacement scans do not accept a raw `list[dict]` via
  `connection.register`. Fixed `_duckdb_reference_over` to build a `pyarrow.Table` from the event
  rows (`pa.Table.from_pylist`, pyarrow is a core dependency) and register that — no new dependency,
  no ADR-004 fingerprint move. `py_compile` clean.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # then live:
  .\make.ps1 redis-up; .\make.ps1 materialize; .\make.ps1 serve-otel
  # fire load/locust and check:
  #   - Grafana parity panel (pit_parity_checked_total / pit_parity_mismatches_total)
  #   - artifacts/event_history/served_events.jsonl grows with each written event
  #   - Tempo score -> online_write spans
  ```

## Known gaps / next steps

- The Event History is written but **not yet consumed** by the offline build: a follow-up wires the
  Event History into DuckDB → Gold Delta materialization so live served events actually land in
  `gold.post_event_state_updates` (the "write to Gold Delta" sink of the two-path fan-out).
- `paysim_post_event_state_sql` lives in `features/build_offline.py`; a note there already records
  that moving it to `features/paysim_recipient.py` is a mechanical change plus an ADR-004
  fingerprint review. Importing it into `serving/online_state.py` adds no new dependency (duckdb is
  core) and no pyproject/ADR-004 fingerprint move.
- The `not_warm_started` guard (M053) still stands: a materialized entity whose winlog is empty is
  refused for live writes until its history is seeded (warm-start follow-up).
