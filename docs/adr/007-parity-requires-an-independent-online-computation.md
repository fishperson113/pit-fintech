# ADR-007: Offline/online parity is only meaningful against an independent online computation

- Status: superseded by [ADR-008](008-serving-owns-the-online-write-path.md)
- Date: 2026-08-10
- Depends on: [ADR-003](003-paysim-feature-contract-v1.md), [ADR-006](006-feast-time-mapping-and-service-v2.md)
- Applies to: Sprint 2 task T6 and gate G6 (guide §8), and the T5 online write path (guide §7)

## Context

Gate G6 (guide §13) is described as the sprint's most important correctness gate: "the same
entity/cutoff/version must produce the same feature vector offline and in online replay" (guide
§12). T6 (M044) built the replay driver and a parity harness that replays events through the online
store and compares, at required checkpoints, the online-read vector against the offline
`gold.pre_decision_features` vector.

Reviewing that harness surfaced a problem with what G6, as currently built, actually proves.

### The online store holds a copy of offline output, not an independent result

In the current MVP architecture:

- the online store (Redis) is populated by **materializing** `gold.post_event_state_updates`, which
  is computed offline by `features/build_offline.py: paysim_post_event_state_sql` (guide §7.1, M043);
- online serving performs **no feature computation** — it is a keyed `GET` of the materialized
  record (`serving/feature_provider.py: RedisFeatureProvider`), with request-time fields derived
  trivially from the request (guide §9.3);
- the M044 parity handler's `commit_post_event_state` writes the pre-computed offline `post_*` row
  into Redis rather than computing new state on write.

So both sides of the comparison originate from the **same offline Gold build, produced by the same
SQL codebase over the same Silver**. Comparing them is comparing a value to a copy of itself. The
only non-trivial content left is: (a) the shift relation between two offline tables
(`post_event_state(s) == pre_decision_history(s+1)`, `GOLD_SHIFT_RELATION`), and (b) the
materialize/rename/serialize/key plumbing (`POST_EVENT_TO_CONTRACT_FIELD`, decimal-string amounts,
version-namespaced keys). Those are worth a regression test, but they are an **integration test of
the materialization pipeline**, not the train/serve-skew correctness proof G6 is presented as.

### Why train/serve skew is normally the point

The offline/online parity problem (Liu et al., PVLDB 2023, which this project adapts) matters when
offline and online feature values are produced by **two independent implementations** — a batch
pipeline offline, and a separate real-time path online — which can drift. Parity is the machine
check that they have not. When the online path is a materialized copy of the offline output, there
is by construction nothing to drift, and the gate is close to vacuous as a correctness signal.

### The one thing that is not vacuous today

Because the online store keeps only the latest state per entity, a checkpoint whose cutoff entity's
most recent prior event is more than one step back reads STALE, and a same-step tie reads a prior
same-step event that offline's strict-prior-step rule excludes. The M044 harness surfaces both as
classified mismatches (`GOLD_SHIFT_RELATION` "Open item for T5/T6"). These are real offline/online
skews, but they arise from freshness/timing, not from an independent feature computation.

## Decision

Record the finding and **do not present the materialize-copy parity as a correctness gate.** Choose
one direction for Sprint 2 (owner to confirm):

### Option A — keep MVP scope; rename the check honestly

Keep the online path as materialize-only (Feast thin registry, guide §3). Reclassify the M044
harness as an **integration/consistency test of materialization + the shift relation**, not gate
G6-as-correctness. G6 is then explicitly deferred until an independent online computation exists
(Option B or the Sprint 3 TypeScript scorer). PROJECT_STATUS and the guide §8/§13 wording are
updated so nobody reads a passing run as a train/serve-skew proof.

### Option B — make parity meaningful: independent online feature maintenance

Give the write path its **own** feature computation: on each event, `read old state -> score ->
compute new windowed state incrementally (increment count/sum, evict rows outside 1h/24h/168h) ->
write`. This incremental maintainer is a second implementation, independent of the offline batch
SQL. Parity then compares the online-maintained state against the offline `pre_decision_features`
and genuinely catches implementation drift (window eviction, ordering, double-count). This is more
work and adds an online aggregation component, which must stay inside the Sprint 2 scope guards (no
Kafka/streaming service; the one-producer replay remains the acceptance path).

Whichever is chosen, the locked float tolerance (1e-6) and the integer-exact rule (AGENTS.md §9) are
unchanged, and a mismatch is never resolved by widening the tolerance (guide §8.4).

## Consequences

- G6's status is downgraded from "the parity gate" to either an integration guard (Option A) or a
  not-yet-built independent-computation gate (Option B) until the owner decides.
- M044's harness and its pure primitives (`canonicalize_vector`, `classify_mismatch`,
  `plan_checkpoints`, the ordered `ReplayDriver`) are reused unchanged under either option — only the
  handler's `commit_post_event_state` differs (copy offline row vs compute incrementally).
- This ADR is `proposed`; it changes no frozen contract and no code. Accepting it, and the A/B
  choice, is the next decision.
