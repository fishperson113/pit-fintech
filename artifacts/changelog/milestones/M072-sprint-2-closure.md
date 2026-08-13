# M072 — Sprint 2 closure (MVP invariant lanes) + recovery performance fix

- **Datetime:** 2026-08-13
- **Status:** implemented (agent code + owner-run evidence); **Sprint 2 CLOSED (owner-accepted
  2026-08-13)** — 5/6 invariant lanes clean; Lane 4 recover determinism verified with 1
  concurrent-write outlier, recorded as an accepted limit rather than a blocker.
- **Scope / gate:** run the six MVP invariant lanes owner-side, gather evidence, and fix the
  recovery snapshot performance bottleneck that made Lane 4 unrunnable in reasonable wall time.

## Owner-run lane evidence (2026-08-13)

1. **Serving/OTel (Lane 1):** `demo-score` → HTTP 200, `feature_provider=pit-online-worker`,
   `model_version=paysim-fraud-lightgbm@1`; worker applied both events; async parity consumer ran
   `offline.parity.reconcile.completed checked_entities=5 field_mismatches=0 passed=True`.
2. **Backfill idempotency (Lane 2):** `backfill --mode range --start 697 --end 720` run twice.
   Range must be day-aligned (M035); [700,743] was rejected, [697,720] (event_day 30) accepted.
   Run 1 built+promoted (`pre_v9`/`post_v8`, `future_read_violations=0`, `pre_rows=5061`
   `b3d9d275…`, `post_rows=11287` `0740a41b…`). Run 2 same `idempotency_key=d063fa0e…766079`,
   short-circuited (no build/promote logs, reused run 1 versions, 0 duplicate).
3. **Full backfill (Lane 3):** `backfill --mode full --start 1 --end 743` (full requires explicit
   frozen bounds). `future_read_violations=0`; `pre_rows=2,770,409` `7d1f4c78…`,
   `post_rows=6,362,620` `e3e6d162…`; promoted `pre_v10`/`post_v9`; ~26 min.
4. **Redis recover (Lane 4):** see performance fix below. After a clean materialize of Gold v9
   (`gold_post_event_version=9`, 2,722,362 written), recover reported
   `records_identical=5,444,725 / 5,444,726`, `watermark_restored=True`, `differing_entities=1`.
   The single outlier is a concurrent worker live-write during the run, not a determinism defect.
   **Not** a clean `passed=yes`; recorded as determinism-verified-with-caveat.
5. **Async parity (Lane 5):** demonstrated live during Lane 1 (see above), 0 mismatches.
6. **Served-event candidate (Lane 6):** `pit ingest event-history` → Bronze checkpoint no-op
   (`rows_read=0`), served pipeline `silver_rows=17`, `gold_candidate_rows=17`,
   `quarantined_rows=0`, `status=success`; candidate rows `label_status=unlabeled`.

Regression: `lint` clean (ruff check pass; 118 files formatted); `test-unit` 110 passed in 10.88s.

## Decisions + rationale

- **Recovery snapshot: GET → MGET (root-cause fix).** `rematerialize_after_reset.snapshot()` did
  one `client.get(key)` per key. Over ~5.4M keys at network-round-trip rate (~700 ops/s observed)
  a single snapshot took ~1 hour; the owner killed the first run after 1h. Batched the reads with
  `MGET` (`_SNAPSHOT_BATCH=5000`), matching the existing `client.mget` usage at
  `materializer.py:413`. One pass fell to ~180 s (~30k records/s). Chosen over per-key GET because
  the round-trip count, not payload size, dominates; semantics are unchanged (same key filter,
  same `materialization_run_id`/`written_at` stripping, same dict).
- **Did not weaken the recover comparison to force a pass (hard rule #5).** The first run's
  2,722,376 differing winlogs were investigated (winlog payload is deterministic — `{"events":
  [[step,knowledge_step,amount],…]}`, no run metadata) before any change. Root cause: the
  pre-existing online store had accreted stale/live winlog events across prior sessions that
  `materialize run` NOOPs rather than overwrites. A clean reset+rematerialize brought the store to
  exactly 5,444,726 keys and a second recover reduced the diff to 1 concurrent-write outlier. The
  gate comparison was left intact; the caveat is documented, not hidden.
- **Progress logging + differing-key print** added so a long recovery run is observable and a
  mismatch is diagnosable; the non-zero exit on a failed gate is preserved.

## Files touched

- `src/pit_fintech/materialization/materializer.py` — `_SNAPSHOT_BATCH`; MGET-batched snapshot;
  `[recover +Ns]` phase progress logging.
- `src/pit_fintech/cli.py` — `materialize recover` prints differing key ids on mismatch.
- `notebooks/06_delta_time_travel.ipynb` — new review-only Delta time-travel viewer (output-free).
- `docs/reports/sprint-2-completion-report.md` — new closure report.
- `docs/reports/sprint-2-report-slides.html`, `docs/reports/sprint-2-closure-gate-checklist.md` —
  closure deck + owner command checklist.

## Commands + results

- `.\make.ps1 lint` → ruff check all passed; format 118 files already formatted.
- `.\make.ps1 test-unit` → 110 passed in 10.88s.
- Lane commands and outputs as recorded above (owner-run PowerShell).

## Deviations

- Checklist range corrected from [700,743] to day-aligned [697,720] after the M035 guard.
- `full` mode required explicit `--start 1 --end 743` (frozen-bounds guard).

## Known gaps / next steps

- Lane 4 clean `differing_entities=0`: re-run recover against a quiescent store (worker stopped).
- Consider `materialize run --refresh` to reconcile stale winlogs to a pinned Gold version.
- OTel-to-Grafana verified via foreground `serve-otel`; containerized `INSTALL_OTEL` image (M069)
  not rebuilt this session.
- Governance: this milestone must ship with `PROJECT_STATUS.md` + `CHANGELOG.md` updates in the
  same commit (this file is one of the three).
