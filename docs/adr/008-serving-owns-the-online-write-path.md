# ADR-008: Serving owns the online write path; drop the replay harness; parity via Locust

- Status: accepted
- Date: 2026-08-10
- Supersedes: [ADR-007](007-parity-requires-an-independent-online-computation.md)
- Depends on: [ADR-003](003-paysim-feature-contract-v1.md), [ADR-006](006-feast-time-mapping-and-service-v2.md)
- Applies to: Sprint 2 tasks T6/T7 and gate G6 (guide §8, §9); removes the replay package

## Context

ADR-007 recorded the finding that the offline/online parity check, as built in M044, was near
vacuous: the online store was a **materialized copy** of offline Gold and serving performed **no
computation**, so parity compared offline against a copy of itself. It left an A/B choice. Owner
review resolved it and sharpened two further points:

1. **The replay harness is itself biased.** The M044 `ReplayDriver`/parity harness drives a handler
   directly and does **not** go through `serving/app.py`. It tests a parallel re-implementation of
   the write path, not the serving code that would actually run. A test that bypasses the serving
   pipeline cannot prove the serving pipeline is correct.
2. **The interesting behaviour is all at runtime, through serving.** A new transaction on a fresh
   entity, a new transaction that increments an existing entity, a late-arrival under the
   optimistic lock — these are runtime effects of the write path under real (and concurrent)
   requests. A single-threaded, offline replay cannot exercise the optimistic lock at all.

## Decision

1. **The serving `/score` pipeline owns the online write path.** On each request the pipeline does
   `read online state -> score -> compute the new windowed state itself -> write it back`, under the
   existing WATCH/MULTI/EXEC optimistic lock. The new state is computed by an **independent
   windowed-feature maintainer**, not copied from the offline `gold.post_event_state_updates` table.
   This is the second, independent implementation that makes offline/online parity a real
   train/serve-skew check rather than a copy-consistency check.

2. **Drop the replay harness entirely.** `src/pit_fintech/replay/` (the one-producer
   `ReplayDriver` and the parity harness), its unit/integration tests, the `pit replay parity` CLI
   command, and the `test-parity`/`parity` Make targets are removed. Their purpose is subsumed by
   the serving write path plus runtime load testing.

3. **Parity/load testing is a Locust script, run manually.** A `scripts/locust_*.py` fires requests
   at the running service (sequential and concurrent), then compares the online state the service
   produced against an offline batch recompute over the same events. It lives in `scripts/` and is
   triggered by hand — **not** wired into `pytest`, because its value is exercising the live service
   under load and concurrency, which a unit lane cannot represent honestly. Observability
   (structured logs / traces) may complement it for diagnosis but does not replace the assertion:
   the check still fails when online and offline disagree.

## Online state representation

To maintain 1h/24h/168h windows online, an aggregate alone cannot be decremented when an event ages
out. The online record therefore holds a **compact per-entity event log** — `(step, amount)` for
events within the last 168h — from which the nine window features are derived. On each event: append
the current `(step, amount)`, evict entries older than 168h, then recompute count/sum/history-flag at
each window relative to the current step. The frozen twelve-field feature **contract** (ADR-003,
ADR-005/006) is unchanged; what changes is only how the online store holds state.

The read-before-write ordering (AGENTS.md §11) is preserved: the vector served for transaction `e`
is read before `e` is appended, so it equals the offline `pre_decision_features(e)`.

## Consequences

- The replay package and its tests are gone; guide §8 (T6 "replay và parity harness") and the
  AGENTS.md one-producer-replay scope note are now **stale** and should be revised to describe the
  serving-owned write path + Locust parity. Flagged, not rewritten here.
- G6 is redefined: offline/online parity is measured by comparing the **serving-maintained** online
  state against an offline batch recompute over the same request stream, exercised through the live
  service. It is no longer a pytest gate; it is a manual Locust run with a machine-checkable
  assertion.
- The online record schema changes from pre-baked aggregates to an event log; M043's
  `materialize_to_watermark` copy path is superseded for the acceptance flow (it may remain as a
  bulk warm-start, to be decided when the maintainer lands).
- The locked float tolerance (1e-6) and integer-exact rule (AGENTS.md §9) are unchanged; a mismatch
  is never resolved by widening the tolerance (guide §8.4).
