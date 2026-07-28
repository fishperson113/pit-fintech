# M024 — Knowledge-review remediation tests (Q5/Q6/Q10 + oracle boundary/mutation debt)

- Date: 2026-07-28
- Status: verified

## Scope and acceptance

Close the code/test portion of the remediation that `docs/reports/sprint-1-knowledge-review.md`
recorded for Q5, Q6 and Q10 (all hard-invariant, all below D3), and pay down the boundary/mutation
coverage debt that `src/pit_fintech/features/reference.py`'s own module docstring calls for: "Full
dataset optimization ... must match this oracle before it is accepted." This milestone adds tests
only; it does not itself re-score the interview.

Acceptance:

- explicit fixtures pin four record classes at the eligibility boundary: exactly-at-cutoff,
  strictly-before-cutoff, outside-window-but-eligible, and same-instant-different-entity;
- at least one mutation test proves the suite goes red if `order_key <` is weakened to `<=`,
  via `monkeypatch` rather than editing `src/`;
- a second mutation test proves the suite goes red if the knowledge-time predicate
  `created_timestamp <=` is tightened to `<`;
- a zero-history regression test separates pre-score (cold-start) from post-score (history now
  visible) assertions for a previously unseen PaySim destination entity;
- a feature-set regression test proves `E2`'s feature list can never silently become the PIT-safe
  column set used by `E3`/`E4`;
- none of the above requires changing `src/`.

## Decisions

- Keep all four boundary record classes inside one fixture builder
  (`_boundary_events`/`_knowledge_boundary_events` in `test_reference_oracle.py`) instead of
  reusing the shared hand-calculated fixture, so the boundary is pinned exactly and does not
  drift if the shared fixture changes later.
- Simulate both mutations (`order_key <` → `<=`, `created_timestamp <=` → `<`) by
  `monkeypatch.setattr`-ing `reference.eligible_history` to a locally defined weakened/tightened
  predicate, so the regression is provable without editing the shipped implementation.
- For the zero-history case, build an isolated two-row PaySim CSV in `tmp_path` rather than
  extending the shared `tests/fixtures/paysim_recipient_temporal.csv`, to avoid perturbing the
  deterministic row selection other `test_paysim_recipient.py` tests already depend on (in
  particular `recipient_leakage_example`'s fraud-first, earliest-step ordering).
- For the E2 feature-set test, assert directly against `EXPERIMENT_MATRIX` in
  `src/pit_fintech/models/paysim_lightgbm.py` rather than comparing a materialized column against
  itself; an earlier draft of this test compared `pit_prior_amount_168h` to itself and was
  rejected during review for being tautologically green regardless of correctness.

## Files added or changed

- `tests/temporal/test_reference_oracle.py`
- `tests/temporal/test_paysim_recipient.py`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## New tests

`tests/temporal/test_reference_oracle.py` (8 new, oracle boundary/mutation coverage):

- `test_source_at_exact_cutoff_order_key_is_excluded` — a record sitting exactly at the cutoff is
  never history (Invariant 1).
- `test_same_instant_other_entity_is_never_eligible` — a shared instant never substitutes for
  entity identity.
- `test_out_of_window_source_stays_in_history_only` — eligibility and window membership are
  different predicates; an old-but-eligible row aggregates to nothing.
- `test_source_knowable_exactly_at_cutoff_is_eligible` — `created_timestamp <=` keeps a row that
  becomes knowable exactly at the cutoff.
- `test_order_key_mutation_makes_transaction_read_itself` — mutation test: weakening `order_key
  <` to `<=` via `monkeypatch` must change the computed vector, not stay silent.
- `test_order_key_mutation_is_caught_by_future_read_audit` — the same mutation must also trip
  `assert_no_future_reads`, the second independent net.
- `test_shipped_order_key_predicate_is_strictly_less_than` — differential check: the shipped
  `reference.eligible_history` and the mutated version must disagree on the boundary record.
- `test_knowledge_time_mutation_drops_arrival_at_cutoff` — mutation test: tightening
  `created_timestamp <=` to `<` via `monkeypatch` must drop a row that was correctly knowable at
  the cutoff, not stay silent.

`tests/temporal/test_paysim_recipient.py` (2 new):

- `test_unseen_entity_is_cold_start_then_appears_in_next_transactions_history` — a PaySim
  destination entity's first-ever transaction must be cold-start (`pit_prior_count/amount = 0`,
  `recipient_has_history = false`) on every window; only the entity's second transaction may see
  the first one in its prior history. Traps a serving-order inversion
  (update-state → read-history → score) as an exact plus-one offset on the unseen-entity row.
- `test_e2_feature_set_uses_leaky_columns_not_pit_cutoff_columns` — `EXPERIMENT_MATRIX`'s `E2`
  entry must never contain any `pit_prior_*` column and must contain the leaky
  `future_amount_168h`/`leaky_lifetime_amount` columns, so a positive-control column swap fails
  loudly instead of silently killing the leakage detector.

## Verification state

User-run evidence (2026-07-28), no command executed by the agent:

```text
.\make.ps1 lint
  ruff check: All checks passed!
  ruff format --check: 47 files already formatted

.\make.ps1 test-temporal
  uv run pit data sample
    validated 7 canonical events from 8 rows
    snapshot: synthetic-temporal-v1:1ef70772400a1d8e
  uv run pytest -q -m temporal tests/temporal
    33 passed in 2.12s
```

Before this milestone the same lane collected 23 tests; 33 − 23 = 10, matching the 10 new test
functions above with none skipped and none added as new parametrize cases.

## Known gaps and next step

- This closes only the code/test half of the Q5/Q6/Q10 remediation instructions in
  `docs/reports/sprint-1-knowledge-review.md`. It does not re-score the interview: Q1, Q2, Q3, Q5,
  Q6 and Q10 remain below D3 in that file's Scoring table and Interview status block until the
  user is re-tested; that conclusion is intentionally left unchanged by this milestone.
- Q1, Q2 and Q3 remediation is answer-only (no test artifact was requested for them) and remains
  fully outstanding.
- The mutation tests exercise `src/pit_fintech/features/reference.py`'s synthetic-oracle
  predicate only; they do not extend to the separate DuckDB/PaySim recipient predicate in
  `src/pit_fintech/features/paysim_recipient.py`, beyond the zero-history and E2 feature-set
  checks above.
