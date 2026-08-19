# ADR-011: Add cold-start fan-in/recency features and freeze PaySim FeatureSpec v3

- Status: proposed
- Date: 2026-08-19
- Depends on: [ADR-002](002-paysim-dataset-entity-scope.md),
  [ADR-003](003-paysim-feature-contract-v1.md),
  [ADR-005](005-knowledge-step-and-featurespec-v2.md),
  [ADR-006](006-feast-time-mapping-and-service-v2.md),
  [ADR-009](009-parity-at-the-online-write-path.md)

## Context

Sprint 3 stood up an exploratory data → feature → model validity investigation (M073, notebooks
nb09–nb13, report `docs/reports/sprint-3-feature-model-validity-findings.md`). Read that report for
the numbers; the three findings that force a contract decision are:

1. **The quality ceiling is set by features and data, not by the algorithm or its hyperparameters.**
   LightGBM ≈ XGBoost when compared fairly; a 30-trial Optuna search moved validation PR-AUC +0.011
   but transferred +0.0006 to test. There is no headroom left in tuning.
2. **The single largest remaining weakness is cold-start.** Walk-forward CV (nb13) splits every fold
   into *warm* recipients (a destination with prior history) and *cold* recipients (a new
   destination, `pit_prior_* = 0`). Warm is strong and stable (PR-AUC 0.408 ± 0.043); cold is weak
   and volatile (0.350 ± 0.124) and loses on lift in **every** fold. The v2 history features can only
   fire where there is history, so a genuinely new recipient carries no historical signal at all.
3. **Five of the twelve v2 fields do not earn their place in the model feed.** `event_step` is an
   overfit absolute-time coordinate (train/test step ranges do not overlap; dropping it roughly
   doubled the natural-prevalence PR-AUC in nb09); the three `recipient_has_history_*` flags are the
   binarisation of the count fields (`gain ≈ 0`); and `pit_prior_count_168h` is redundant with the
   other window counts. nb09/nb12 converged on a **seven-field deployable feed**.

The v2 contract (`paysim-fraud-recipient-v2`, ADR-003 amended by ADR-005) is frozen: twelve stored
fields, referenced by committed Gold Delta tables, the training baseline, the online store and the
parity harness. ADR-003's change policy states that any change to feature set, order, dtype, default
or window requires a **new feature version, a new ADR, a backfill under the new version,
offline/online parity evidence, and a new model run bound to the new checksum**. This ADR is that
decision. It is Track B in the findings report, explicitly deferred there and now authorised by the
owner.

## Decision

Freeze a new feature version `paysim-fraud-recipient-v3` (service `paysim-fraud-scoring-v3`) that
**trims** the five non-earning v2 fields from the stored contract and **adds** three cold-start
features. The entity, scope, source, label source, temporal semantics and forbidden-input set are
all unchanged from v2. Only the feature set, order and the two derived timestamp columns' upstream
are affected.

### The v3 model feature order (ten fields)

| # | Feature | Availability | Window | Dtype | Default | Change vs v2 |
|---:|---|---|---:|---|---:|---|
| 1 | `current_amount` | request | — | float64 | 0.0 | kept |
| 2 | `transaction_type_transfer` | request | — | float64 | 0.0 | kept (was #3) |
| 3 | `pit_prior_count_1h` | history | 1h | int64 | 0 | kept |
| 4 | `pit_prior_amount_1h` | history | 1h | float64 | 0.0 | kept |
| 5 | `pit_prior_count_24h` | history | 24h | int64 | 0 | kept |
| 6 | `pit_prior_amount_24h` | history | 24h | float64 | 0.0 | kept |
| 7 | `pit_prior_amount_168h` | history | 168h | float64 | 0.0 | kept |
| 8 | `pit_distinct_senders_24h` | history | 24h | int64 | 0 | **new** |
| 9 | `pit_distinct_senders_168h` | history | 168h | int64 | 0 | **new** |
| 10 | `pit_steps_since_last_event` | history | 168h | int64 | `PAYSIM_RECENCY_SENTINEL_STEPS` | **new** |

Dropped from v2: `event_step`, `pit_prior_count_168h`, `recipient_has_history_1h`,
`recipient_has_history_24h`, `recipient_has_history_168h`.

`current_amount` and `transaction_type_transfer` are the two `request_available` fields; the eight
`historical_only` fields are computed by the frozen PIT engine. `event_step` is removed as a **model
feature** only — the integer `step`/`knowledge_step` ordinals remain the platform's ordering
authority (ADR-006 decision 1.4) and stay on both Gold tables as identity columns, exactly as the
timestamps and `source_row_number` do. Removing `event_step` from the contract removes it from the
*model input vector*, not from the platform's temporal machinery.

### New feature semantics

All three are strict-PIT `historical_only` aggregates over prior destination events, computed by the
**same eligibility predicate and window bounds** as the existing history fields (ADR-003 §Temporal
semantics, ADR-005 decision 5): a source event `s` is eligible for cutoff `c` when
`s.step < c.step AND s.knowledge_step <= c.knowledge_step`, and window `w` keeps
`s.step >= c.step - w`. No new temporal rule is introduced.

1. **`pit_distinct_senders_24h` / `pit_distinct_senders_168h`** —
   `COUNT(DISTINCT origin_entity_id)` over eligible prior events in the 24h / 168h window. This is a
   **fan-in** signal (how many distinct source accounts paid this recipient), structurally distinct
   from the raw event count: a burst from one sender and the same volume spread across many senders
   read identically under `pit_prior_count_*` but differently here. The signal comes from
   `silver.paysim_transactions.origin_entity_id` (the ingested `nameOrig`), which is already a Silver
   column (`data/paysim_lakehouse.py`) and is neither a balance column, a label, nor post-outcome.

2. **`pit_steps_since_last_event`** — `c.step − MAX(s.step)` over eligible prior events (the recency
   gap to the recipient's most recent prior event). When no eligible prior event exists within the
   168h lookback, it takes the sentinel `PAYSIM_RECENCY_SENTINEL_STEPS = 999`, a value strictly
   larger than any in-window gap (max window 168), so the feature is monotone in staleness: a larger
   value always means a colder recipient. The sentinel replaces the information the dropped
   `recipient_has_history_*` flags carried (cold ⟺ sentinel) while adding a recency gradient the flags
   could not express.

### What is unchanged

- Entity `destination_entity_id`, definition `paysim-destination-customer-v1`.
- Scoring scope: `CASH_OUT` / `TRANSFER` with a `CUSTOMER` destination.
- Feature source `silver.paysim_transactions`, label source `silver.paysim_labels`, label `isFraud`.
- Tie-break `source_row_number`; cutoff `strict_prior_event_time`; same-time
  `exclude_same_event_time`; created-time `derived_knowledge_step_lte_cutoff`; online update
  `score_then_update`.
- The forbidden-input set is unchanged and still binding: `isFraud`, `isFlaggedFraud`,
  `oldbalanceOrg`, `newbalanceOrig`, `oldbalanceDest`, `newbalanceDest`. No new field touches a
  balance column, a label, or any post-outcome value.
- `DECIMAL(18,2)` money accumulation (ADR-003 / M027); derived Feast timestamps (ADR-006).

### Version and change policy

`paysim-fraud-recipient-v3` gets a new canonical JSON checksum covering cross-feature policy, every
feature declaration and the model feature order. Per ADR-003, promoting v3 requires, in order: a new
feature version (this ADR), a **full backfill** under the new version, offline/online parity evidence
under the new checksum, and a new model run bound to it. The contract may not be edited in place once
a Gold, training or serving artifact references v3 — a further change requires v4.

## Consequences

- **Both Gold tables change shape and must be fully rebuilt.** `gold.pre_decision_features` carries
  the ten v3 fields (was twelve v2 fields); `gold.post_event_state_updates` carries the post-event
  siblings. A schema change forces a `mode=FULL` promote so every `event_day` partition is rewritten
  under the new schema (`features/build_offline.py: _write_gold_table` already documents this); an
  incremental promote over the old schema would fail on a field-count mismatch. The backfill strategy
  is in `docs/reports/sprint-3-track-b-cold-start-v3-plan.md`.

- **The PIT engine and its independent oracle both gain the three fields.** `distinct_senders`,
  `steps_since_last` and their post-event siblings must be implemented **twice, independently**:
  once in the DuckDB engine (`features/paysim_recipient.py: paysim_pre_decision_feature_sql` and
  `features/build_offline.py: paysim_post_event_state_sql`) and once in the pure-Python oracle
  (`features/paysim_reference.py`). Two independent derivations agreeing is what makes the
  oracle/SQL parity lane evidence rather than a tautology (M029, `build_offline.py` Trap 1). The
  pre-decision source projection must add `origin_entity_id` to
  `PAYSIM_PRE_DECISION_SOURCE_COLUMNS`.

- **The online write path and parity gain a sender dimension.** The winlog
  (`serving/online_state.py: LoggedEvent`) currently stores `(step, knowledge_step, amount)` and has
  no sender identity, so `pit_distinct_senders_*` **cannot** be computed online today. v3 requires:
  (a) `LoggedEvent` carries `origin_entity_id`; (b) the winlog serialization bumps and warm-start
  re-seeds it — which means `gold.post_event_state_updates` must also carry a per-event
  `origin_entity_id` identity column, exactly as it carries per-event `amount` for winlog seeding
  (M057); (c) `compute_window_features` emits the v3 non-uniform field set; (d)
  `_events_to_duckdb_rows` projects the sender so the DuckDB post-event reference matches. Because the
  winlog serialization is backward-incompatible, v3 rollout resets the winlog namespace and
  re-warm-starts from the v3 Gold post-event table. `count_parity_mismatches` iterates the contract
  history-field tuple, so it picks up the new integer fields automatically (exact comparison; only
  `*_amount_*` fields use the 1e-6 float tolerance).

- **`pit_steps_since_last_event`'s sentinel is a modelling choice, recorded, not silent.** A recipient
  with no event in the 168h lookback reads `999`; the model learns "very stale" from a large value
  rather than from a separate binary flag. This is why the three `recipient_has_history_*` flags can
  be dropped without losing the cold/warm distinction.

- **A new champion must be trained and bound to the v3 checksum.** The v2/E4 baseline numbers
  (E1 PR-AUC 0.258342, E4 0.102766 at natural prevalence; the tuned nb-side 0.376) do **not** carry
  over and must not be restated for v3. Metrics may move in either direction; a drop after a
  correctness-motivated feature change is a valid result and must never be tuned away (hard rule #5).
  The purpose of v3 is a **fair test of the cold-start hypothesis**, evaluated on the warm/cold slices
  (`SlicedMetrics`: `population / cash_out_warm / cash_out_cold / transfer_cold`, ADR-002), not a
  headline PR-AUC.

- **Blast radius.** `features/paysim_specs.py` (source of truth), `features/paysim_recipient.py`,
  `features/paysim_reference.py`, `features/build_offline.py`, `models/paysim_gold.py`,
  `data/paysim_fixture.py` (committed fixture + expected vectors), `feature_repo/`,
  `serving/{online_state,feature_provider,scoring,schemas,app}.py`, `materialization/`,
  `training/{dataset,pipeline}.py`, and the temporal/unit/integration tests. Import-time
  contract-alignment guards (`build_offline._assert_contract_alignment`,
  `paysim_recipient.paysim_pre_decision_feature_sql`, `online_state.compute_window_features`) will
  fail loudly until every consumer is moved in lockstep — which is the intended tripwire, and the
  reason v3 lands as one coordinated change set, not a sequence of partial commits.

## Alternatives considered

**Track A only — trim the model feed to seven fields, keep the v2 stored schema frozen.** Reversible,
no ADR, no backfill: just change which stored columns feed the model. Rejected as insufficient on its
own — it cannot address cold-start, which the findings identify as the real lever. Track A's trim is
therefore *folded into* v3 (the drop of the five non-earning fields) rather than shipped separately,
so there is exactly one backfill instead of a trim now and an add later.

**Add an origin-entity history block (sender-side aggregates).** The strongest lever for a genuinely
cold recipient is the *sender's* history, but it introduces a second behavioural entity into the
contract, reopening the ADR-002 entity-scope decision and roughly doubling the online-state and
parity surface (two winlogs, two key spaces). Deferred to a possible v4 if v3's fan-in signal proves
the direction but not enough of it. v3 keeps a single entity and reaches the fan-in signal through the
sender *identity of prior events already in the recipient's window*, not a second entity.

**Recency/velocity only (smallest change).** `pit_steps_since_last_event` plus a velocity ratio, no
fan-in. Rejected as leaving the most promising new structural signal (fan-in) on the table for a
marginal reduction in blast radius; the winlog already needs a sender field for either, so the saving
is small.

## Revisit conditions

Create v4 rather than mutating v3 if: a sender-side entity block is admitted; a genuine created-time
field replaces the derived `knowledge_step`; the eligibility predicate or window bounds change; a new
request-time field is admitted; or model serving requires a different dtype or feature order.
