# ADR-009: Parity is verified at the online write path, observed through telemetry

- Status: accepted
- Date: 2026-08-10
- Amends: [ADR-008](008-serving-owns-the-online-write-path.md) (its online-state representation and
  read path; keeps ADR-008's serving-owned write path and its supersession of ADR-007)
- Depends on: [ADR-003](003-paysim-feature-contract-v1.md), [ADR-006](006-feast-time-mapping-and-service-v2.md),
  [ADR-008](008-serving-owns-the-online-write-path.md)
- Applies to: Sprint 2 tasks T5/T6/T7 and gates G6/G7; serving and the observability stack
  (`deploy/vps/`)

## Context

AGENTS.md invariant #2 is that the offline training vector and the online serving vector must be
identical for the same entity/cutoff/version. Two prior pivots recorded the lessons that led here:

- **ADR-007** (superseded): comparing a read-only, materialized copy of offline Gold with its own
  offline source is near-vacuous — a value compared with a copy of itself cannot diverge, so it
  proves nothing about train/serve skew.
- **ADR-008** (accepted): the serving `/score` pipeline owns the online write path, and parity was
  redefined as comparing the serving-maintained online state against an offline recompute, exercised
  through a live service (Locust) rather than pytest.

Owner review of ADR-008's implementation in practice surfaced two errors in how it was built:

1. **The online store's purpose is fast, precomputed reads for the business — not per-request
   recomputation.** ADR-008's implementation stored a per-entity **event log** (`winlog`) and
   recomputed the nine window features at every read (`WindowStateFeatureProvider`). That inverts the
   nature of an online store: it exists to serve already-computed feature state at sub-millisecond
   latency, not to re-derive rolling windows on every request just so the parity comparison has "two
   independent sides". Recomputing inside Redis/at request time to manufacture a meaningful comparison
   is complexity for correctness theatre, not for the product.
2. **The materialize stage is a read-only copy; it can never be a parity gate.** Pouring
   `gold.post_event_state_updates` into Redis is a copy. A copy is always equal to its source, so
   claiming "parity" at the materialize step is the same vacuous trap ADR-007 already flagged — and
   ADR-008's recompute approach was an over-correction in the opposite direction.

The conclusion is that there is exactly **one** place online state is genuinely produced by serving
logic — the post-score write path that transitions an entity's stored state because a new event was
observed — and that is the only place a real divergence can occur. Parity must therefore be checked
there. And because that behaviour is a property of a live system (request ordering, concurrency under
the optimistic lock, state transitions over time), it cannot be accepted by a unit test; it is
verified through observability. This is the concrete reason the Grafana + Tempo stack exists at this
stage of the project.

## Decision

1. **Materialization is the bulk offline → online copy, and it is not a parity gate.**
   `materialize_to_watermark` loads Redis from offline Gold (post-event aggregate state per entity,
   versioned/watermarked). It is read-only with respect to offline, so it is never used as a
   correctness comparison. Its role is to warm the online store for fast business reads and to be the
   G8 recovery path.

2. **Serving reads the materialized aggregate.** The default read path is the materialized provider
   (`RedisFeatureProvider`). The read-time recompute path (`WindowStateFeatureProvider` + `winlog`)
   introduced by ADR-008 is removed as the default; per-request window recomputation inside the
   online store is an anti-pattern (below).

3. **Serving owns the write path (kept from ADR-008).** After scoring a request, `/score` updates the
   entity's online state in Redis — the incremental state transition that reflects event `t` having
   been observed. This is the one place online state is produced by serving logic, so it is the only
   place online can genuinely diverge from offline.

4. **Parity is verified asynchronously, never on the request path.** The write path must be fast
   and non-blocking: running the offline DuckDB engine inside `/score` would stall every later
   request, which is unacceptable in a serving production path. The write path therefore only
   transitions the aggregate and appends the Event History; offline/online parity is verified
   afterwards by `pit parity reconcile`, which compares the online state against the **offline
   reference for the same step** — the offline computation that includes event `t` (`post_event_state`
   / post-event state for that entity at step `t`), run with the real DuckDB engine over the served
   events. A mismatch there is a real train/serve skew in the serving update logic. The materialize
   stage is explicitly not re-asserted as "parity".

## Two-path fan-out: the event flows into both the online and the offline path

After scoring, the event `t` is **not** handled by one path alone — it fans out into both, and parity
is the check that the two independent computations on the same event set agree:

```
request t ──► /score
   │
   ├── (read)  Redis aggregate (history < t)  ──► score t
   │
   └── (write, strictly after the score)  event t fans out to TWO paths:
        ① Online write path:  append t to winlog ──► recompute ──► Redis aggregate (has t)
        ② Offline write path: append t to Event History ──► DuckDB compute ──► Gold Delta (has t)
```

* **Online path** (`serving/online_state.py`): the per-entity event log (`winlog`) is updated and the
  nine window features are recomputed in Python (`compute_window_features`) to produce the post-event
  aggregate at step `t`. This is the only work the `/score` request handler does after scoring — it
  is fast and non-blocking.
* **Offline path**: the event is appended to the append-only **Event History** (the offline-visible
  record of what serving observed). The same post-event state is computed by the **offline DuckDB
  engine** (`features/build_offline.py: paysim_post_event_state_sql`) — the same SQL implementation
  that builds `gold.post_event_state_updates`, and the same engine that feeds Gold Delta — but that
  computation runs **asynchronously** in `pit parity reconcile`, never inside the request handler.

**Parity is the comparison of these two engines, done off the request path**: online (winlog /
Python window aggregation) vs offline (DuckDB SQL). Both compute post-event state for the entity at
step `t` from the same event set. The parity reference is the **DuckDB SQL engine**, not a pure-Python
oracle running inside serving — the SQL is the actual offline implementation, so agreement is
meaningful (implementation drift in either engine is caught). The pure-Python oracle
(`features/paysim_reference.py`) remains the correctness ground truth of the project and is what the
DuckDB engine is itself verified against in `tests/temporal/test_paysim_oracle_sql_parity.py`; it is
not duplicated on the serving write path.

"Write to Gold Delta" is the offline sink of the same computation: the Event History is what a later
materialize/build step consumes to land live events into `gold.post_event_state_updates`. Writing a
Delta version per request is intentionally not done on the request path (that would put a lakehouse
commit inside a sub-millisecond online write).

5. **Serving parity is observed, not unit-tested.** Correct serving behaviour depends on live request
   ordering, concurrency under `WATCH`/`MULTI`/`EXEC`, and state transitions over time; a unit lane
   cannot faithfully represent a running service. Parity in serving is therefore verified by
   observability:
   - Prometheus metrics scraped from `/metrics` — `pit_parity_mismatches_total`,
     `pit_parity_checked_total`, `pit_online_writes_total`, latency — into Grafana;
   - Tempo traces showing the `score` span containing its child `online_write` span, making the
     read-before-write ordering visible and diagnosable;
   - Grafana dashboards (`deploy/vps/grafana-dashboard.json`) that surface mismatch counts and drift
     over time.
   Unit tests still cover the **pure** state-transition logic (old state + event → new state), but a
   green `pytest` is never the acceptance for serving parity — the live observability path (Locust
   load + Grafana/Tempo) is.

## Runtime parity check scenarios

The write-path parity compare must hold under the scenarios that can **only** be encountered in a
running system — the ones whose correctness depends on live request ordering, concurrency and
timing. These are what the observability-verified parity check is for. The optimistic lock
(`WATCH`/`MULTI`/`EXEC` with read-retry on `WatchError`) is mandatory: the write path is a
read-modify-write on a shared store, and without it a lost update would silently drop an event and
the aggregate would diverge from offline with no failing test.

1. **Concurrent writes to the same entity.** Two or more `/score` requests for one entity overlap in
   time. The aggregate after the burst must equal the offline computation over the same events in
   deterministic order — no event may be lost to a lost update, and the optimistic lock must converge
   under contention.
2. **Out-of-order events under live concurrency.** A stream delivers events not in step order (an
   older event arrives after a newer one) while writes to the same entity continue. The
   older-write protection must hold under the lock, and the aggregate must match the offline
   reference, which processes events in canonical order.
3. **Late-arrival visibility over time.** An event with `knowledge_step > step` arrives while the
   stream advances. Post-write parity at each advancing cutoff must show it included from the first
   cutoff whose knowledge time covers it, and excluded before — the knowledge-time predicate
   exercised as a sequence, not as a single computation.
4. **Window eviction as cutoffs advance.** As the stream moves an event past the 168h horizon, the
   aggregate must drop it exactly when offline's window `[cutoff - w, cutoff)` does, observed across
   consecutive writes rather than one pure call.

Deliberately **not** listed here — deterministic, code-level, covered by unit tests and guards, not
by the runtime parity observation: duplicate-event idempotency, same-step counting, cold-start
defaults, window-boundary arithmetic, and the `REJECTED_OLDER` write rule.

## Consequences

- Serving's default read provider returns to `RedisFeatureProvider` (materialized aggregate);
  `WindowStateFeatureProvider`/`winlog` recompute is removed from the default path.
- `serving/online_state.py` is repurposed from "event log + read-time recompute" to an **aggregate
  state transition**: read aggregate → apply event → write aggregate, under the optimistic lock. The
  offline reference for the parity compare is the post-event state for step `t` (which includes `t`),
  i.e. what offline would have produced had it seen `t`.
- The write path fans the event out to the offline side: it appends to the append-only **Event
  History** (the offline-visible record). It does **not** run the offline DuckDB engine on the
  request path — that would block every later request, which is unacceptable in serving production.
- Parity is verified by `pit parity reconcile`, which compares each entity's online aggregate against
  the offline DuckDB reference (`paysim_post_event_state_sql`) over the served events. The pure-Python
  oracle stays the project's correctness ground truth (used to verify the DuckDB engine offline); it
  is not duplicated on the serving path.
- The reconcile exports `pit_parity_mismatches_total` / `pit_parity_checked_total` (OTel, best-effort)
  so Grafana can show drift; the `online_write` span still shows the write ordering in Tempo.
- Materialize remains the bulk warm-start and the G8 recovery path; it is not re-labelled as parity.
- The locked float tolerance (1e-6) and integer-exact rule (AGENTS.md §9) are unchanged; a mismatch is
  never resolved by widening the tolerance (guide §8.4).

## Anti-patterns recorded — do not walk back into these

1. **Copy-parity as a gate.** Claiming parity by comparing a read-only, materialized online store
   against its offline source. A copy is always equal; the check cannot fail, so it proves nothing
   (ADR-007's rut).
2. **Recompute-to-manufacture-independence.** Recomputing window features inside the online store at
   request time purely to give the parity comparison a "second independent implementation". It inverts
   the online store's purpose and adds complexity for correctness theatre.
3. **Unit-test acceptance for serving parity.** Treating a green unit test as proof that the running
   service produces parity-correct state. The runtime, concurrent, ordered behaviour that parity
   protects is only observable through the live service and telemetry.
