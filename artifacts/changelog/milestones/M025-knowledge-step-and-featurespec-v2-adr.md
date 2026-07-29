# M025 — ADR-005: knowledge_step and PaySim FeatureSpec v2 (proposed)

- Date: 2026-07-29
- Status: implemented

## Scope and acceptance

Open ADR-005 to close the asymmetry ADR-003 left in place: the temporal contract has two
independent eligibility conditions (event time `prior.order_key < current.order_key` and
knowledge time `prior.created_time <= current.created_time`), but only event time is exercised on
the PaySim application path. Sprint 2 section 5.4 (task T3) requires a late-arrival correction
path that needs a real knowledge-time column to inject against; none exists today.

Acceptance for this milestone is documentation-only:

- `docs/adr/005-knowledge-step-and-featurespec-v2.md` records the decision, alternatives
  considered, consequences and revisit conditions;
- the decision proposes a derived `knowledge_step` column at Bronze and a frozen
  `paysim-fraud-recipient-v2` FeatureSpec, without touching `src/`, `tests/`, or the Bronze/Silver
  build;
- project status and changelog reflect that the ADR is `proposed`, not `accepted`, and that no
  implementation exists yet.

## Decision

Record ADR-005 as `proposed`:

1. Bronze gains a derived `knowledge_step BIGINT NOT NULL` column, `knowledge_step = step` for
   every row ingested from the frozen snapshot. The raw CSV and its snapshot ID/checksum
   (`paysim1:16910f90577b0d98`) are not modified.
2. Historical eligibility becomes `prior.step < current.step AND prior.knowledge_step <=
   current.knowledge_step`. On clean data the second predicate is implied by the first and must be
   proven, not assumed, by a regression run reproducing exactly `0.258342` (E1) and `0.102766`
   (E4) from M019.
3. Late arrivals exist only in hand-chosen labelled test fixtures, never generated randomly, never
   written into the main dataset, never tied to the train/validation/test split.
4. Freeze `paysim-fraud-recipient-v2`: same 12 fields, names, order, dtypes and defaults as v1;
   only cutoff semantics change and a new canonical checksum is issued per the ADR-003 change
   policy.
5. Rejected alternatives: an overlay late-arrivals table joined only in tests (would let a passing
   test diverge from production SQL — the same defect the project already has between the
   synthetic oracle and the DuckDB implementation), treating the Delta commit version as knowledge
   time (per-batch, not per-row, so it cannot sit inside the window predicate), and doing nothing
   (blocks Sprint 2 T3 and leaves G6 parity evidence covering event time only).

## Files added or changed

- `docs/adr/005-knowledge-step-and-featurespec-v2.md` (new, copied verbatim from the prepared
  draft; ADR status is `proposed`)
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

Documentation only. No command was executed by the agent for this milestone; there is no gate to
run yet because no code changed.

## Known gaps and next steps

- **ADR-005 status is `proposed`, not `accepted`.** Nothing in this milestone binds Bronze,
  FeatureSpec, or any test to the new semantics.
- **No implementation exists yet**: Bronze has not been changed to emit `knowledge_step`,
  `paysim-fraud-recipient-v2` has not been created in `src/pit_fintech/features/`, and no
  regression test exists to prove the no-op claim in decision 2 above.
- Four steps remain before this can be called implemented, in order:
  1. Get ADR-005 accepted (user decision).
  2. Freeze `paysim-fraud-recipient-v2` in the feature contract module and public feature
     repository exports, per the ADR-003 change policy (new version, new checksum).
  3. Run the no-op regression: rebuild Bronze/Silver with `knowledge_step` and confirm E1/E4
     reproduce exactly `0.258342`/`0.102766` from M019 on clean data before any late-arrival
     fixture is added.
  4. Build the hand-chosen knowledge-time fixture (late arrivals, including at least one row
     exactly on the `<=` boundary) and the boundary/mutation tests that exercise it, mirroring the
     event-time coverage M024 already added for the synthetic oracle.
- Until step 1 happens, this milestone does not change Sprint 1 or Sprint 2 gate status anywhere
  else in the changelog.
