# M026 — Implement ADR-005: knowledge_step and PaySim FeatureSpec v2

- Date: 2026-07-29
- Status: implemented

## Scope and acceptance

Implement the decision recorded in ADR-005 (`docs/adr/005-knowledge-step-and-featurespec-v2.md`,
accepted): give the knowledge-time half of the temporal predicate
(`prior.created_time <= current.created_time`) a real column to evaluate on the PaySim
application path, and freeze `paysim-fraud-recipient-v2` around it.

This milestone covers:

- Bronze emits a derived `knowledge_step BIGINT NOT NULL` column
  (`src/pit_fintech/data/paysim.py`, `connect_paysim`: `step::BIGINT AS knowledge_step` added to
  the view; `src/pit_fintech/data/paysim_lakehouse.py`: `knowledge_step` added to
  `PAYSIM_BRONZE_COLUMNS` and `_bronze_query`).
- `knowledge_step` propagates unchanged into `silver.paysim_transactions`
  (`PAYSIM_SILVER_TRANSACTION_COLUMNS` and `_silver_transactions_query`), because ADR-003 fixes
  `feature source: silver.paysim_transactions` — if Silver dropped the column the knowledge-time
  predicate would have nothing to read at the feature layer.
- `paysim-fraud-recipient-v1` bumped to `paysim-fraud-recipient-v2`
  (`PAYSIM_FEATURE_DEFINITION_VERSION` in `src/pit_fintech/features/paysim_specs.py`), and
  `created_time_policy` changed from `"source_has_no_created_time"` to
  `"derived_knowledge_step_lte_cutoff"` (new literal added to `FeatureSetContract` in
  `src/pit_fintech/contracts/features.py`).
- Both PIT engines — `src/pit_fintech/features/paysim_recipient.py` (diagnostic/leakage path) and
  `src/pit_fintech/models/paysim_training.py` (training path) — moved from `RANGE BETWEEN ...
  PRECEDING/FOLLOWING` window functions to an explicit range self-join with `GROUP BY` / `FILTER
  (WHERE ...)` aggregates.
- All references to the frozen version string and to `"PaySim FeatureSpec v1"` display text
  updated across live config, CLI, docs and command help (`config.py`, `.env.example`, `cli.py`,
  `README.md`, `CLAUDE.md`, `Makefile`, `make.ps1`, `tests/unit/test_paysim_feature_contract.py`,
  `tests/unit/test_paysim_training.py`); dated changelog/milestone/ADR-003 history left untouched
  as a historical record of what was frozen under v1.

## Why the window functions had to become range joins

`RANGE BETWEEN {w} PRECEDING AND 1 PRECEDING` only orders and bounds one column (`step`) relative
to the current row inside a single `OVER (PARTITION BY ... ORDER BY step)` frame. FeatureSpec v2's
eligibility predicate needs two independent conditions on the source row relative to the cutoff
row at once:

```text
prior.step           <  current.step
AND prior.knowledge_step <= current.knowledge_step
```

A `RANGE` window frame cannot express a second inequality against a second column of the *same*
row pair — the frame bound is defined purely in terms of the `ORDER BY` key. The only way to
evaluate a two-column row-pair condition per destination is a self-join with both conditions in
the `ON`/`WHERE` clause, aggregated with `FILTER (WHERE ...)` or `GROUP BY` instead of `OVER (...)`.
Both engines now do exactly that: `s` (source rows) joined to `c` (cutoff/current row) on
`s.destination_entity_id = c.destination_entity_id AND s.step >= c.step - {window} AND s.step <=
c.step - 1 AND s.knowledge_step <= c.knowledge_step`, with `pit_prior_count_*h` /
`pit_prior_amount_*h` / `max_pit_source_step_*h` computed via `FILTER (WHERE ...)` over that
joined set. On clean data (`knowledge_step = step`), the added condition is implied by
`s.step <= c.step - 1` and is a no-op — but that claim is not yet regression-proven (see gaps
below).

In `paysim_recipient.py` the future-facing E2 positive-control columns
(`future_count_*h`/`future_amount_*h`) deliberately keep only the step-range condition and omit
the knowledge-time condition, since their entire purpose is to read across the cutoff as a
leakage control; adding a knowledge-time restriction there would defeat the control.

## Verification state

User-confirmed clean on 2026-07-29 (agent did not execute these commands):

- `lint` — user-confirmed clean.
- `test-temporal` — user-confirmed clean.
- `test-unit` — user-confirmed clean.

Exact pass counts were not reported by the user and are not fabricated here.

**Not run:** `build-lakehouse`, `train`, `test-lakehouse`. No Bronze/Silver rebuild and no model
run have happened against this code. The clean-data no-op regression required by ADR-005 decision
6 (E1 `0.258342` / E4 `0.102766` reproduced exactly) has **not** been executed and is therefore
unverified.

## Files changed

- `docs/adr/005-knowledge-step-and-featurespec-v2.md` (Decision list: inserted the Bronze->Silver
  propagation item after item 1, renumbered the rest)
- `src/pit_fintech/data/paysim.py`
- `src/pit_fintech/data/paysim_lakehouse.py`
- `src/pit_fintech/features/paysim_specs.py`
- `src/pit_fintech/contracts/features.py`
- `src/pit_fintech/features/paysim_recipient.py`
- `src/pit_fintech/models/paysim_training.py`
- `src/pit_fintech/config.py`
- `src/pit_fintech/cli.py`
- `.env.example`
- `README.md`, `CLAUDE.md`, `Makefile`, `make.ps1`
- `tests/unit/test_paysim_feature_contract.py`
- `tests/unit/test_paysim_training.py`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Known gaps and next steps

1. **The clean-data no-op regression has not been run.** Until `train` reproduces exactly
   `0.258342` (E1) and `0.102766` (E4) from M019, the claim "the knowledge-time condition is a
   no-op on clean data" is a design intent, not evidence.
2. **`train` will be blocked until `build-lakehouse` runs again.** The Silver tables currently on
   disk were built before `knowledge_step` existed, and the component-lineage guard
   (`platform/lineage.py`, ADR-004) requires the manifest to come from a clean, matching component
   fingerprint — a stale Silver cannot satisfy that gate.
3. **Known numerical risk:** `sum(amount)` moved from a window aggregate to a hash-based
   `GROUP BY`/`FILTER` aggregate, which does not guarantee the same floating-point summation
   order. `pit_prior_amount_*h` may differ from the pre-M026 values in the last ulp, and E4 could
   in principle shift in a far decimal place. E1 does not read through this path at all, so its
   metric must match bit-exact; any E1 drift would indicate a real regression, not summation
   order.
4. **No knowledge-time boundary fixture or mutation test yet** — step 4 of the ADR-005 plan
   (hand-chosen late-arrival fixture with a row exactly on the `<=` boundary, plus boundary/
   mutation coverage mirroring what M024 already did for event time) is still outstanding.
5. **Two pre-existing, unintended differences between the two PIT engines remain**, unrelated to
   this milestone's change and not introduced by it:
   - scope-rule source: `paysim_recipient.py` hardcodes `starts_with(nameDest, 'C')` and an
     inline transaction-type list, while `paysim_training.py` reads scope from
     `PAYSIM_FEATURE_CONTRACT`;
   - dtype: `recipient_has_history_*` is typed differently between the two paths (`INTEGER` vs
     `BIGINT`).
6. **Not done: extract a shared `features/pit_sql.py`.** The prior-window predicate
   (`prior_window_predicate()`) and the aggregate-column builder (`pit_window_aggregates()`) now
   exist as two hand-synchronized, textually identical copies in `paysim_recipient.py` and
   `paysim_training.py`. A shared module plus a differential test that runs both paths against the
   same fixture would remove the duplication and make future drift impossible to miss silently.
