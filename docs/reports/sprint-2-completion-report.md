# Sprint 2 completion report

Date: 2026-08-13
Outcome: **CLOSED (owner-accepted) — enter Sprint 3.** Five of six MVP invariant lanes are clean.
The Redis-recovery lane (Lane 4) verified materialization determinism (5,444,725 of 5,444,726
records bit-identical across reset + rematerialize) with one concurrent-write outlier; this is
recorded as an **accepted limit**, not a blocker. The owner accepted Sprint 2 as closed on
2026-08-13.

This is an MVP-invariant Sprint 2 release gate, not a claim that the full six-week platform is
complete. All command evidence below was produced by the project owner in this workspace; the
agent wrote code, prepared commands and read back results (hard rule #1).

## Owner-run invariant evidence

| # | Lane | Command | Result |
|---|---|---|---|
| 1 | Serving + OTel | `demo-score` | HTTP 200; `feature_provider=pit-online-worker`; `model=paysim-fraud-lightgbm@1`; worker applied events; telemetry visible in Grafana |
| 2 | Backfill idempotency | `backfill --mode range --start 697 --end 720` ×2 | Same `idempotency_key=d063fa0e…`, `source_silver_version=7`; 2nd run short-circuited (no rebuild, no new Delta version, 0 duplicate); `future_read_violations=0` |
| 3 | Full backfill | `backfill --mode full --start 1 --end 743` | `future_read_violations=0`; `pre_rows=2,770,409` (`7d1f4c78…`), `post_rows=6,362,620` (`e3e6d162…`); promoted `pre_v10`/`post_v9`; committed |
| 4 | Redis recover | `materialize recover --watermark 743 --gold-post-event-version 9` | Determinism verified: `records_identical=5,444,725 / 5,444,726`; `watermark_restored=True`; `differing_entities=1` (concurrent worker live-write). **Not** a clean `passed=yes`. |
| 5 | Async parity | `pit parity reconcile` (via worker consumer during Lane 1) | `checked_entities=5 field_mismatches=0 missing_online=0 passed=True` |
| 6 | Served-event candidate | `pit ingest event-history` | Bronze → `served_events_silver` (17 rows) → `served_events_gold_candidate` (17 rows); `quarantined_rows=0`; candidate `label_status=unlabeled` |

Regression, owner-run 2026-08-13:

```text
lint        ruff check: All checks passed; ruff format: 118 files already formatted
test-unit   110 passed in 10.88s
```

## Frozen offline lineage (this session)

| Boundary | Value |
|---|---|
| Dataset snapshot | `paysim1:16910f90577b0d98` (6,362,620 rows, steps 1–743) |
| Source Silver version | 7 |
| Gold full-rebuild | `pre_decision_features` v10, `post_event_state_updates` v9 |
| Gold pre-decision rows / checksum | 2,770,409 / `7d1f4c78a776cd574cc34ddcb1074ced38cd24f9bb401d6993da5a217d12ae7d` |
| Gold post-event rows / checksum | 6,362,620 / `e3e6d1628d5da1977dcc32be5831bc2cee01bca85a2a564c4dea6b523768d2c3` |
| Full-backfill idempotency key | `38e8f854487c3c7b8757d7e55a8153db77fbc0d615a1c6a496d202ce1b9ca0d8` |
| Online store (clean v9) | 2,722,362 entities × 2 keys + 2 metadata = 5,444,726 keys |
| Feature service | `paysim-fraud-scoring-v2` |

## Code changes this session

- **Recovery snapshot performance (`materialization/materializer.py`):** `rematerialize_after_reset`
  read the whole online store back with one `GET` per key — ~5.4M sequential round-trips at
  ~700 ops/s, so a single snapshot took ~1 hour. Replaced with batched `MGET`
  (`_SNAPSHOT_BATCH=5000`), consistent with the existing `client.mget` read path (line 413). One
  snapshot pass dropped to ~180 s (~30k records/s), a ~40× improvement. Semantics unchanged: same
  key filter, same field stripping, same result dict.
- **Recovery progress logging (same file):** added `[recover +Ns]` phase logs (snapshot before →
  reset → re-materialize → snapshot after → compare), throttled at `_PROGRESS_INTERVAL_SECONDS`,
  mirroring the `[materialize +Ns]` style, so a long recovery run is observable.
- **Recovery diagnosability (`cli.py`):** `materialize recover` now prints the differing key ids
  (first 20) on mismatch; the non-zero exit on failure is preserved (a failed gate must fail).
- **Delta time-travel notebook (`notebooks/06_delta_time_travel.ipynb`):** review-only viewer to
  re-read historical Delta versions (Bronze/Silver/Gold), diff two versions and inspect any Delta
  path, calling `src/` helpers. Output-free per AGENTS §13.

## Known findings and accepted limits

- **Recovery reproduces the materialized baseline, not live event-log state.** The first recover
  on the pre-existing store reported 2,722,376 differing winlogs because the online store had
  accreted stale/live-written winlog events across many prior sessions that `materialize run`
  does not overwrite (it NOOPs existing aggregates). After a clean reset+rematerialize the store
  is exactly 5,444,726 keys, and a second recover reduced the difference to a single entity — a
  concurrent worker live-write during the ~30-minute run, not a determinism defect. Live winlog
  events are restored by Event-History replay, not by Gold materialization. **Sprint 3 item:** run
  recover against a quiescent store (worker stopped) for a clean `differing_entities=0`, and/or add
  a `materialize run --refresh` that reconciles stale winlogs to a pinned Gold version.
- **OTel-to-Grafana** was verified via the owner's `serve-otel` (foreground uvicorn) export; the
  containerized `INSTALL_OTEL` image path (M069) was not rebuilt this session.
- **T9 broad synthetic E2E** remains skipped by design; MVP closure uses the invariant-focused
  lanes above (per M071).
- Model/feature version-mismatch rejection (fail-closed champion, M064) and promote/rollback audit
  manifests exist but were not re-exercised in this closure session.

## What is not done — model quality (the real remaining gap)

The heavy platform work is complete; the remaining bottleneck is **model quality, not the
pipeline**:

- **Class imbalance is not addressed systematically.** Fraud is extremely rare; the model is still
  a baseline with no deliberate balancing/threshold strategy.
- **Feature relationships are not validated.** Deeper signal (e.g. transaction `amount`, feature
  interactions/transforms) has not been exploited, and no analysis shows which features actually
  help.
- **The model is baseline only** — no tuning, no feature ablation, no explanation of why metrics
  are low.

## Sprint 3 entry

Sprint 3 (weeks 5–6) starts from the frozen Gold v9/v10 lineage above. **The primary goal is model
quality;** everything else is optional hardening that supports it.

- **Primary — polish the model:** handle class imbalance, feature engineering around `amount` and
  feature relationships, E1–E4 ablation to learn which features are worth keeping, and tuning.
  (E1–E4 exist today; E5 = E4 model + stale/skew injection is a reliability experiment, listed
  under fault injection below, not yet built.)
- **Optional — review & test:** audit the AI-generated code; mutation-test the correctness modules
  (`features/reference.py` + `paysim_reference.py` PIT oracle, `serving/online_state.py` write
  path, `features/build_offline.py` Gold engine) to prove the tests actually catch defects;
  property-based tests (Hypothesis) asserting the PIT invariant under random event orderings;
  chaos/crash tests (kill worker mid-batch, Redis restart) to verify recovery and no double-apply.
- **Optional — load & fault:** Locust scenarios (late-arrival, out-of-order, burst), edge cases
  (cold-start, tie, window boundary), fault injection (stale / version-mismatch / recovery).
- **Optional — serving to cloud:** smoke deployment (Modal / Upstash); close-out with clean-room
  reproduction, architecture-as-built and final report/demo.

The recover-quiescence clean pass and an optional `materialize run --refresh` remain accepted
limits, not blockers.
