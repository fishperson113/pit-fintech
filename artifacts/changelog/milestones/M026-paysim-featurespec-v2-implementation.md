# M026 — Implement ADR-005: knowledge_step and PaySim FeatureSpec v2

- Date: 2026-07-29
- Status: verified

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

User-run evidence, 2026-07-29 (`build-lakehouse` then `train` against the rebuilt Silver):

```text
Silver versions: silver.paysim_transactions=v4, silver.paysim_labels=v4
vector checksum: ff52681f1f6b06627b8f8c027a9277fc0bbcc0ab32fb90047effb5e578cc0ee7
training fingerprint: 381de46fb8e3cfea2c2f7ae31f2eb88d50059d74429a9888e47293fa8b498377
MLflow parent run: d9d142db739243299cc1cb59184216a6

E1  PR-AUC 0.258342  ROC-AUC 0.601620  recall@FPR 0.275559
E4  PR-AUC 0.102766  ROC-AUC 0.784978  recall@FPR 0.036741

future-read violations: 0
```

E1 and E4 match the M019 baseline **bit-exact**. This is the regression required by ADR-005
decision 6: it proves, not merely claims, that the knowledge-time condition
(`prior.knowledge_step <= current.knowledge_step`) is a no-op on clean PaySim data, since adding
it to both PIT engines' eligibility predicate changed neither metric from the pre-ADR-005 M019
values.

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

1. **No knowledge-time boundary fixture or mutation test yet** — step 4 of the ADR-005 plan
   (hand-chosen late-arrival fixture with a row exactly on the `<=` boundary, plus boundary/
   mutation coverage mirroring what M024 already did for event time) is still outstanding.
2. **Two pre-existing, unintended differences between the two PIT engines remain**, unrelated to
   this milestone's change and not introduced by it:
   - scope-rule source: `paysim_recipient.py` hardcodes `starts_with(nameDest, 'C')` and an
     inline transaction-type list, while `paysim_training.py` reads scope from
     `PAYSIM_FEATURE_CONTRACT`;
   - dtype: `recipient_has_history_*` is typed differently between the two paths (`INTEGER` vs
     `BIGINT`).
3. **Not done: extract a shared `features/pit_sql.py`.** The prior-window predicate
   (`prior_window_predicate()`) and the aggregate-column builder (`pit_window_aggregates()`) now
   exist as two hand-synchronized, textually identical copies in `paysim_recipient.py` and
   `paysim_training.py`. A shared module plus a differential test that runs both paths against the
   same fixture would remove the duplication and make future drift impossible to miss silently.
4. **The floating-point summation-order risk did not materialize on this run, but nothing guards
   it.** `sum(amount)` moved from a window aggregate to a hash-based `GROUP BY`/`FILTER`
   aggregate, which does not guarantee the same summation order as the pre-M026 window path; E1
   and E4 matched M019 bit-exact this time, so no drift occurred on this Silver/this DuckDB
   version. There is still no test pinning summation order or checksums across repeated runs. If
   `vector_checksum` ever differs between two runs against the same Silver version, this
   aggregation-order change is the first suspect to check.
