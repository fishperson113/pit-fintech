# M015 — Destination-centric PaySim leakage prototype

- Date: 2026-07-27
- Updated: 2026-07-27 10:47:47 +07:00
- Status: verified

## Scope and acceptance

Replace the stale origin-centric leakage notebook with a recipient-history audit aligned to
ADR-002. The implementation must:

- use customer `nameDest` as the history entity;
- keep strict PIT, current-inclusive, future-inclusive and deliberately leaky controls separate;
- implement conservative 1h/24h/168h windows with `prior_step < current_step`;
- keep label, balance and policy-output fields outside the safe PIT projection;
- provide a non-empty deterministic example and event timeline;
- move reusable computation from the notebook into `src/`;
- cover same-step exclusion, window boundaries, cold starts, origin/entity separation,
  deterministic reruns and forbidden lineage with a hand-calculated fixture.

Static review is not runtime verification. The milestone remains implemented until the user runs
the new tests and notebook on the frozen PaySim snapshot.

## Technical decisions

- Freeze application split defaults at train end step 520 and validation end step 631. Tests may
  inject explicit boundaries for their smaller fixture.
- Use DuckDB `RANGE ... PRECEDING` over hourly `step`, excluding the complete current hour from
  model-utility claims.
- Use every event for the selected destinations as history, then join the deterministic target
  cohort. Do not filter history down to fraud types or sampled target rows before aggregation.
- Include every customer-destination fraud `CASH_OUT`/`TRANSFER` row and at most 5,000
  deterministic non-fraud rows per split/type in the diagnostic cohort.
- Treat cohort percentages and means as diagnostic-sample metrics, not full-population estimates.
- Maintain separate column allowlists for strict PIT output and positive controls.
- Add `recipient_has_history_{1,24,168}h` as explicit cold-start indicators.
- Join target/history identity on source row, step, type, destination and amount, then require
  exact target/vector row-count parity.
- Emit compact JSON strings for key notebook evidence so PyArrow text truncation cannot hide
  gate values.

## Files changed

- `src/pit_fintech/features/paysim_recipient.py`
- `tests/fixtures/paysim_recipient_temporal.csv`
- `tests/temporal/test_paysim_recipient.py`
- `notebooks/03_leakage_prototype.ipynb`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Implemented behavior

The reusable module provides:

- deterministic target/vector materialization;
- fixed strict-PIT feature projection without labels or leaky controls;
- compact three-window leakage gate;
- split/type/label diagnostic breakdown;
- one guaranteed warm cutoff with future context;
- a ±168-hour timeline labelled `PIT_PRIOR`, `TARGET_CURRENT`,
  `SAME_STEP_EXCLUDED` or `FUTURE_UNAVAILABLE`.

The hand-calculated fixture expects destination `C9` to produce these 168-hour PIT vectors:

```text
step 1 row 1: count 0, amount 0
step 1 row 2: count 0, amount 0
step 2:       count 2, amount 30
step 169:     count 3, amount 60
step 170:     count 2, amount 70
step 200:     count 2, amount 90
```

The test suite also checks explicit cold defaults, repeated-origin isolation, split assignment,
safe-column lineage, deterministic rematerialization and invalid configuration rejection.

## Verification

```text
Notebook JSON parse: pass
Notebook cells: 16 total, 8 code
Duplicate cell IDs: 0
Saved code-cell execution counts: 1,2,3,4,5,6,7,8
Saved code-cell error outputs: 0
Python source lines over 100 characters: 0
Independent static audits: no remaining blocker
```

The agent did not execute a notebook, test or pipeline. The user supplied these verification
results:

```text
.\make.ps1 test-temporal
synthetic snapshot: synthetic-temporal-v1:1ef70772400a1d8e
pytest result: 23 passed in 2.11s
exit code: 0
deprecated DuckDB warning: absent

.\make.ps1 test-notebooks
PASS 01_data_profile.ipynb
PASS 02_entity_temporal_analysis.ipynb
PASS 03_leakage_prototype.ipynb
verified 3 notebooks
exit code: 0
```

The Windows Proactor/ZMQ and unencrypted local TCP kernel messages emitted by the headless
notebook runner are warnings and did not change the successful notebook verification result.

Saved full-data notebook 03 evidence:

```text
diagnostic cohort rows: 38,213
strict-PIT cutoff violations at 1h/24h/168h: 0 / 0 / 0
future-read rows at 1h/24h/168h: 1,672 / 9,008 / 15,376
future-read percent at 1h/24h/168h: 4.3755 / 23.5731 / 40.2376
current-inclusive changed rows: 38,197
timeline relations:
  PIT_PRIOR
  TARGET_CURRENT
  SAME_STEP_EXCLUDED
  FUTURE_UNAVAILABLE
```

The safe strict-PIT projection contains no label, balance or `isFlaggedFraud` field. The
positive controls change observable outputs, so the zero-violation result is not a vacuous
comparison.

## Known gaps and next step

- The PaySim 10–15 versioned FeatureSpec migration is a separate follow-up.
- Static/PIT model baseline and MLflow evidence remain a separate Sprint 1 deliverable.
- PaySim has no real created-time field; late-arrival/knowledge-time correctness continues to
  rely on the independent synthetic temporal oracle.
- Next: freeze the PaySim FeatureSpecs and implement the static/PIT temporal model baseline with
  MLflow evidence.
