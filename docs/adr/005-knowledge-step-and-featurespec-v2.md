# ADR-005: Add a derived knowledge_step column and freeze PaySim FeatureSpec v2

- Status: accepted
- Date: 2026-07-29
- Depends on: [ADR-002](002-paysim-dataset-entity-scope.md), [ADR-003](003-paysim-feature-contract-v1.md)

## Context

ADR-003 states that "PaySim has no source created-time field. Raw snapshot and ingestion lineage
are recorded, while late-arrival knowledge-time correctness remains grounded in the synthetic
oracle."

That decision left the second half of the temporal invariant unexercised on the application path.
The contract has two independent eligibility conditions:

```text
prior.order_key      <  current.order_key            -- event time
prior.created_time   <= current.created_time         -- knowledge time
```

Only the first is enforced on PaySim. The evidence is therefore asymmetric:

| Layer of evidence | Event time | Knowledge time |
|---|---|---|
| Synthetic oracle fixtures | yes | yes |
| PaySim boundary and mutation tests | yes | no |
| PaySim full-run audit | yes | no |
| Determinism and reproducibility | yes | no |
| Positive control | yes | no |

Sprint 2 section 5.4 (task T3) requires a late-arrival correction path that must "inject event có
event time < T nhưng created time > T". There is currently no column in which such an event can
carry a knowledge time, so that fault-injection path cannot be built without either changing the
schema or building a parallel test-only data path.

A parallel test-only path is the failure mode this project already carries once: the synthetic
oracle and the DuckDB implementation are two independent code paths with two separate fixtures,
both green, with no cross-check binding them. Repeating that shape for knowledge time would add a
second unverified seam rather than closing the first.

## Decision

Add a derived `knowledge_step` column at the Bronze layer and freeze a new feature version.

1. Bronze gains `knowledge_step BIGINT NOT NULL`. For every row ingested from the frozen snapshot,
   `knowledge_step = step`.
2. `knowledge_step` must carry through to `silver.paysim_transactions` unchanged. ADR-003 fixes
   `feature source: silver.paysim_transactions`, so if Silver drops the column the knowledge-time
   predicate has nothing to read from and cannot be evaluated at the feature layer.
3. The raw snapshot is not modified. `dataset_snapshot_id: paysim1:16910f90577b0d98` and its
   sha256 remain unchanged, and no column is written back to the source CSV.
4. `knowledge_step` is a derived column of the same class as `source_row_number`: produced during
   ingestion, recorded in lineage, and never presented as a source field of PaySim.
5. Historical eligibility becomes:

   ```text
   prior.step           <  current.step
   AND prior.knowledge_step <= current.knowledge_step
   ```

6. On clean data the second predicate is implied by the first and changes no value. This must be
   proven, not assumed: a regression run on the existing Silver must reproduce exactly
   `0.258342` (E1) and `0.102766` (E4) from M019.
7. Late arrivals exist only in labelled test fixtures. Every value is chosen by hand so that at
   least one row sits exactly on the `<=` boundary. Late arrivals are never generated randomly,
   never written into the main dataset, and never tied to the train/validation/test split.
8. Freeze `paysim-fraud-recipient-v2`. The twelve features keep their names, order, dtypes and
   defaults; only the cutoff semantics change. A new canonical checksum is issued, per the change
   policy in ADR-003.
9. `knowledge_step` is never null. A null knowledge time would make the eligibility predicate
   evaluate to unknown under three-valued logic and drop rows silently.

### What this decision does not claim

- PaySim does not become a bitemporal dataset. `knowledge_step` carries no information that was
  not already in `step`.
- Injected late arrivals do not model real arrival behaviour of any production system. They are
  labelled synthetic faults whose only purpose is to exercise a predicate.
- The synthetic temporal oracle remains the correctness ground truth for bitemporal semantics, as
  established in ADR-001 and reaffirmed in ADR-002.

## Alternatives considered

**Overlay table.** Keep Bronze unchanged and join a separate `late_arrivals` table during tests
only. Rejected: the fault-injection path would execute different SQL from production, so a passing
test would not constrain production behaviour. This is the same defect the project already has
between the oracle and the DuckDB implementation.

**Delta commit version as knowledge time.** Treat "known at time T" as "present in Delta version
V". Rejected: the resolution is per commit batch rather than per row, and the notion cannot be
expressed inside the eligibility predicate, so window functions could not enforce it.

**Do nothing.** Rejected: section 5.4 of the Sprint 2 guide cannot be implemented, and G6 parity
evidence would cover event time only while the contract claims both halves.

## Consequences

- The knowledge-time predicate executes on the application path for the first time. On clean data
  it is a no-op; the regression in decision 5 is what proves that.
- The T3 late-arrival correction path runs through the same SQL as production, so its result
  constrains production behaviour.
- Per ADR-003 change policy, v2 requires a new feature version, backfill under that version,
  offline/online parity evidence, and a new model run bound to the new checksum.
- The Bronze build version is bumped. Doing this before T2 is the cheapest point in the project:
  no Gold table, training artifact or serving artifact currently references v1.
- Boundary and mutation coverage now applies to both halves of the invariant on PaySim, closing
  the asymmetry in the table above for rows one through three.
- The existing audit result stays scoped as before: `future-read violations = 0` was measured on
  the experiment cohort, which retains every fraud row and down-samples only non-fraud rows, and
  therefore carries a much higher fraud rate than the population. It was not measured across all
  6,362,620 rows. Reports must keep stating that scope.

## Revisit conditions

Create v3 rather than mutating v2 if:

- an application dataset with a genuine created-time field replaces or supplements PaySim;
- knowledge time requires a resolution finer than the hourly `step` ordinal;
- fault injection must model corrections other than late arrival, such as retraction or amendment;
  or
- the eligibility predicate changes in any other way.
