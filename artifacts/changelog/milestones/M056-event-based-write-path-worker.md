# M056 — Event-based write path via Redis Streams + the `pit-online-worker` (ADR-010)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T7 serving, gate G7 — the write path becomes pub/sub

## Scope

Owner direction (correct): the write path must be event-based (pub/sub), not a synchronous
in-process mutation, and a request must never score on a stale or current-inclusive version. The
synchronous `apply_event_and_verify` in `/score` is replaced by an event-based write path: `/score`
publishes an event to a Redis Stream; a dedicated Docker instance **`pit-online-worker`** consumes
it in order, applies it to the online store under the optimistic lock, and publishes the
**pre-decision** feature vector the request scores on. This also amends the AGENTS.md §11 scope guard
(owner-directed exception: Redis Streams used as the write-path transport with a single consumer).

## What changed

### `docs/adr/010-event-based-write-path-redis-streams.md` (accepted)
- The write path is pub/sub: `/score` publishes, never mutates the store. A dedicated worker owns
  the online-store mutation. A single ordered consumer => global order => per-entity order (no stale
  scoring). The worker computes the fresh pre-decision state under the optimistic lock. `/score`
  waits for the worker result (bounded timeout => `503`). Parity stays async (`pit parity reconcile`).
- Records two anti-patterns: mutating the store in `/score`, and scoring on a possibly-stale version.

### `src/pit_fintech/serving/events.py` (new)
- Stream key `pit:{feature_service_version}:events`; consumer group `pit-online-worker`;
  `publish_score_event` (`XADD`) and `wait_for_score_result` (polls
  `pit:{feature_service_version}:result:{request_id}` with a bounded timeout).

### `src/pit_fintech/serving/online_state.py`
- `WritePathResult` / `apply_event_and_verify` removed. New **`apply_score_event`** (worker-side):
  under `WATCH`/`MULTI`/`EXEC`, reads winlog + aggregate, captures the **pre-decision** vector (state
  after every prior event, before this one — never stale, never current-inclusive), applies the
  guards (older write, duplicate, not warm-started), appends/evicts, recomputes the post-event
  aggregate, writes log + aggregate + result key in one transaction, appends the Event History, and
  returns the result dict.

### `src/pit_fintech/serving/worker.py` (new)
- `run_worker`: the single ordered consumer. Ensures the consumer group exists, `XREADGROUP`s the
  stream in order, calls `apply_score_event` per message, writes an error result on failure (so a
  waiting request never hangs), and `XACK`s.

### `src/pit_fintech/serving/app.py`
- `/score` is now a publisher + scorer: `publish_score_event` -> `wait_for_score_result` ->
  build a `FeatureVectorResponse` from the pre-decision result -> `score_transaction(..., prefetched=...)`.
  A worker timeout or error => `503 online_store_timeout`. Spans `online_publish` / `online_wait`.
  The `apply_event_and_verify` block and `_MetricsState` parity counters are gone (parity is async).
- `_result_to_features` builds the provider response from the worker result.

### `src/pit_fintech/serving/scoring.py`
- `score_transaction` gains `prefetched: FeatureVectorResponse | None = None`; when provided, the
  provider lookup is skipped (ADR-010).

### `src/pit_fintech/cli.py`
- New `pit serving worker` command (Redis host/port/db) that runs `run_worker`.

### `compose.yaml`
- New distinct service **`pit-online-worker`** (same image, `serving` group): consumes the stream,
  depends on redis healthy, restarts unless-stopped, writes the Event History (artifacts mounted
  read-write for this service).

### `Makefile` / `make.ps1` / `README.md`
- New targets: `worker`, `worker-up`, `worker-down`; documented in the command contract.

### `AGENTS.md` §11
- Owner-directed exception recorded: Redis Streams is allowed as the write-path transport with a
  single consumer (ADR-010); no other excluded technology is introduced.

## Commands + results

- Agent static analysis only: `python3 -m py_compile` passes on all changed Python files; all lines
  <= 100; grep confirms no stale `apply_event_and_verify`/`WritePathResult` references. The sandbox
  has no redis/duckdb, so the stream/worker behaviour is verified by analysis; pytest/ruff and the
  live run are the owner's.
- **Owner lint run:** caught one F401 in `reconcile_parity` (`from pit_fintech.config import
  get_settings` unused — the path is derived from `artifact_root` directly); removed the import.
- **Refinement (owner `parity-reconcile` run):** the "no event history" detail rendered
  character-by-character with `[/]` artifacts. Two bugs: (a) `reconcile_parity`'s early return used
  `details=(f"...")` — a **string**, not a one-element tuple, so the CLI's `for detail in
  result.details` iterated it character-by-character; fixed with a trailing comma. (b) the CLI
  printed `[yellow]{detail}[/]` with a Windows path containing backslashes — Rich markup turns `\`
  into `[/]`; fixed by escaping the detail (`rich.markup.escape`) before wrapping. The reconcile
  itself was correct: `checked_entities=0` simply means no Event History exists yet (no served
  events), which is the expected empty state, not a real pass.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # then live (worker MUST be running for /score):
  .\make.ps1 redis-up
  .\make.ps1 worker-up          # start the pit-online-worker container
  .\make.ps1 serve              # /score publishes + waits for the worker
  .\make.ps1 parity-reconcile   # async offline/online parity over the Event History
  ```

## Known gaps / next steps

- The worker is a single ordered consumer => global serialization. Fine for the MVP/one-producer
  scope; a per-entity sharded consumer set would be the scale-out follow-up.
- Event History is written by the worker and consumed by `pit parity reconcile`, but not yet wired
  into the offline build (DuckDB -> Gold Delta) to land live events into
  `gold.post_event_state_updates`.
- `not_warm_started` guard (M053) still stands: a materialized entity whose winlog is empty is
  refused for live writes until its history is seeded (warm-start follow-up).
- The worker's own parity is exported as OTel metrics by `pit parity reconcile` (best-effort), not by
  serving; Prometheus-backed Grafana panels need the collector remote-write exporter.
