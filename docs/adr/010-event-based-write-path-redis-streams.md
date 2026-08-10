# ADR-010: Event-based write path via Redis Streams + a dedicated worker

- Status: accepted
- Date: 2026-08-10
- Supersedes: the synchronous in-process write path of ADR-009 (ADR-009's async parity
  `pit parity reconcile` is kept; its "write path mutates the store in `/score`" is replaced)
- Amends: [AGENTS.md §11](AGENTS.md) scope guard "Redis Streams" -- owner-directed exception for the
  write-path transport
- Depends on: [ADR-009](009-parity-at-the-online-write-path.md), [ADR-003](003-paysim-feature-contract-v1.md)
- Applies to: Sprint 2 T7 serving, gate G7; the `pit-online-worker` container

## Context

ADR-009 made the write path fast by removing the DuckDB engine from `/score`, but the write path
still ran **synchronously inside the request handler**: `/score` directly mutated Redis
(`apply_event_and_verify`) and appended the Event History. Owner review (correct) identified two
problems for a serving production path:

1. **The write path should be event-based (pub/sub), not a synchronous in-process call.** A request
   should *publish* an event; a separate consumer should own the online-store mutation and the
   offline side-effect. Serving mutating the store directly couples the request to store internals
   and blocks on store I/O.
2. **A request must never score on a stale version.** The previous flow read the aggregate *before*
   the write, so a request arriving while a prior request for the same entity had not yet written
   would score against state missing that prior event. The per-entity update must be **serialized**
   (one event at a time per entity), and the request must wait until its event's feature state is
   current before scoring.

The owner directed: a proper pub/sub write path, with a dedicated instance in Docker, given a
distinct name. This amends the AGENTS.md §11 scope guard that listed "Redis Streams" as excluded
from the MVP: the owner-directed exception is that Redis Streams is used **only** as the write-path
transport, with a single ordered consumer, and no other excluded technology is introduced.

## Decision

1. **Write path is event-based.** `/score` publishes a score event to a Redis Stream
   (`pit:{feature_service_version}:events`). It does **not** mutate the online store directly.

2. **A dedicated worker owns the online-store mutation.** A separate process/container,
   **`pit-online-worker`**, is the single consumer of the stream (`pit-online-worker` consumer
   group, one consumer). A single consumer reads the stream in insertion order, which gives **global
   order and therefore per-entity order** -- no event for an entity is processed before an earlier
   event for the same entity.

3. **The worker computes the fresh feature state under the optimistic lock.** For each event it:
   `WATCH` the entity's winlog + aggregate; capture the **pre-decision** feature vector (the state
   after all prior events, before this event -- so a request never scores on a stale or
   current-inclusive version); apply the deterministic guards (older write, duplicate, not
   warm-started); append/evict/recompute the post-event aggregate; write log + aggregate + the
   result key in one `MULTI`/`EXEC`; then append the Event History (offline path) and `XACK`.

4. **`/score` waits for the worker's result.** It publishes, then polls
   `pit:{feature_service_version}:result:{request_id}` (with a bounded timeout). The result carries
   the **pre-decision** feature vector, so scoring uses the newest state that includes every prior
   event but excludes the current one. A timeout surfaces as `503 online_store_timeout` (fail-closed
   on the online path).

5. **Parity stays asynchronous** (`pit parity reconcile`, ADR-009): the worker does not run the
   offline DuckDB engine per event. The Event History it appends is what the reconcile consumes.

## Consequences

- The online store is mutated **only** by `pit-online-worker`; `/score` is a pure publisher + scorer.
- Per-entity serialization + optimistic lock guarantee no stale scoring: a request blocks until its
  event's pre-decision state is current.
- `pit-online-worker` runs as a Docker service (compose), same image as the API (serving group). It
  must be running for `/score` to succeed; a stopped worker makes requests time out (`503`).
- Scope guard amended (owner-directed): Redis Streams is allowed as the write-path transport with a
  single ordered consumer. No other previously-excluded technology is introduced.
- The synchronous `apply_event_and_verify` / `WritePathResult` write-path API is removed; replaced
  by the worker's `apply_score_event`.
- `scripts/locust_parity.py`, `demo`, and the E2E flow must start the worker before firing requests.

## Anti-patterns recorded

1. **Mutating the online store in `/score`.** The request handler is a publisher, never a store
   mutator (superseded by this ADR).
2. **Scoring on a version that may be stale.** A request must wait for its event to be processed by
   the serialized worker; it must never read an aggregate that might miss a prior in-flight event.
