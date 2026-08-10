# M052 — ADR-009: parity at the online write path, observed through telemetry

- **Datetime:** 2026-08-10
- **Status:** implemented (ADR accepted; agent static analysis only; no serving code changed yet)
- **Sprint / task:** Sprint 2 T5/T6/T7, gates G6/G7 — design correction to ADR-008's implementation

## Scope

Owner review concluded that ADR-008's implementation over-corrected ADR-007's "copy-parity is
vacuous" finding in the wrong direction: it made the serving read path recompute window features from
an event log (`winlog`) at request time, which inverts the purpose of an online store (fast
precomputed reads), and it left materialization as a read-only copy that can never be a meaningful
parity gate. The owner's settled direction:

- Materialize stays the bulk offline → online copy; it is **not** a parity gate (a read-only copy is
  always equal to its source).
- Serving reads the materialized aggregate (`RedisFeatureProvider`).
- Parity is verified **at the online write path** — after the post-score update, the online state
  (which now includes event `t`) must match the offline reference for step `t`. That is the only
  place online state is produced by serving logic, so the only place it can genuinely diverge.
- Serving parity **cannot be accepted by a unit test**; it is a live-system property (request
  ordering, concurrency under the optimistic lock, state transitions over time) and is verified
  through observability — Prometheus metrics (`pit_parity_mismatches_total` etc.), Tempo traces
  (`score` → `online_write`), Grafana dashboards. This is why the Grafana + Tempo stack exists at
  this stage.

## What changed

- **New `docs/adr/009-parity-at-the-online-write-path.md`** (accepted): records the context (ADR-007
  → ADR-008 → owner review), the decision (materialize = copy, not a gate; serving reads aggregate;
  serving owns the write path; parity checked post-write; parity verified by observability, not unit
  tests), consequences (read provider returns to `RedisFeatureProvider`; `serving/online_state.py`
  repurposed to an aggregate state transition; parity compare emits
  `pit_parity_mismatches_total`/`pit_parity_checked_total`), and three anti-patterns to never walk
  back into (copy-parity as a gate, recompute-to-manufacture-independence, unit-test acceptance for
  serving parity).
- Amends ADR-008: keeps its serving-owned write path and Locust-parity decision; replaces its
  winlog/read-time-recompute representation and default read path.

### Refinement — runtime parity check scenarios

ADR-009 gained a "Runtime parity check scenarios" section listing the parity cases that can **only**
occur in a running system and are therefore verified through telemetry, not unit tests:

1. Concurrent writes to the same entity — the aggregate after the burst must equal the offline
   computation in deterministic order (no lost update).
2. Out-of-order events under live concurrency — older-write protection holds under the lock.
3. Late-arrival visibility over time — included/excluded at the right advancing cutoff.
4. Window eviction across consecutive writes — drops exactly when offline's window does.

The optimistic lock (`WATCH`/`MULTI`/`EXEC` + read-retry on `WatchError`) is stated as mandatory —
the write path is a read-modify-write on a shared store, and without it a lost update would silently
diverge from offline. Deterministic/code-level cases (duplicate idempotency, same-step counting,
cold-start defaults, window-boundary arithmetic, `REJECTED_OLDER`) are deliberately excluded from
the ADR: they belong to unit tests / code guards, not to the runtime parity observation.

No serving code, tests, dependency groups or frozen contracts changed in this milestone — it is the
design lock that the implementation milestone (M053+) will follow.

## Commands + results

- Agent static analysis only (documentation). No runtime gates.
- **Owner gates:** none for the ADR itself; the implementation milestones that follow will carry
  their own gates.

## Known gaps / next steps

- Implementation (not done here): switch serving default read provider back to
  `RedisFeatureProvider`; repurpose `serving/online_state.py` to an aggregate state transition
  (read aggregate → apply event → write aggregate under `WATCH`/`MULTI`/`EXEC`); add the post-write
  parity compare emitting `pit_parity_mismatches_total`/`pit_parity_checked_total` inside the
  `online_write` span; keep materialize as the warm-start/G8 path.
- Guides/docs referencing the winlog recompute read path (`docs/feature-store/sprint-2-implementation-guide.md`,
  AGENTS.md §7/§11 wording, `deploy/vps/README.md`) need updating to match ADR-009.
- `deploy/vps/grafana-dashboard.json` should gain a parity panel binding
  `pit_parity_mismatches_total` once the implementation lands.
