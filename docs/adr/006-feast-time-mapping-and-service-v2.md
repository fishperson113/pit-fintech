# ADR-006: Feast time mapping and PaySim feature service v2

- Status: accepted
- Date: 2026-07-31
- Depends on: [ADR-001](001-temporal-entity-contract.md), [ADR-002](002-paysim-dataset-entity-scope.md),
  [ADR-003](003-paysim-feature-contract-v1.md), [ADR-005](005-knowledge-step-and-featurespec-v2.md)
- Applies to: Sprint 2 task T1 (`feature_repo/`) and gate G1

## Context

Sprint 2 T1 builds the Feast repository: entity, source, feature view, feature service, registry
lifecycle. Feast is a thin control-plane contract over the existing PIT semantics (guide §3); it
does not redefine them. Two facts block T1 before any file is written, and both must be frozen
first because the registry checksum and the online key namespace are derived from them.

### 1. PaySim has no column Feast will accept as event time

Silver carries `step BIGINT` and `knowledge_step BIGINT`, hour ordinals over the frozen range
1–743 (ADR-002 decision 1; ADR-005 decision 1). Feast's `FileSource` requires `timestamp_field`
and `created_timestamp_column` to name real timestamp columns: the source validates that the named
column exists in the schema, and registration inferencing resolves an unset `timestamp_field` by
looking for *the* timestamp column and failing when it finds none or several. The documented
surface has no option to declare an integer column as event time.

So either the Feast-facing table exposes typed timestamp columns, or T1 cannot be built on Feast
at all.

### 2. The service version string no longer matches the feature version

ADR-003 froze `paysim-fraud-recipient-v1` with service `paysim-fraud-scoring-v1`. ADR-005 bumped
the feature version to `paysim-fraud-recipient-v2`; the service string was left at v1 and now
carries v2 semantics. That skew is currently invisible because no Feast registry, Gold table,
materialization key or serving response exists yet. T1 is where it stops being invisible:

- guide §3.3 binds `feast plan/apply -> registry checksum -> feature_service_version`;
- §6.3 makes `feature_service_version` a mandatory MLflow tag;
- §7.1 stores it in the online record and §7.2 namespaces online keys by it;
- §9.2 returns it in every scoring response.

A string that says v1 while the vector is v2 makes every one of those records ambiguous to trace.

Neither question changes what a feature vector contains. Both are presentation-layer decisions
that become expensive after the first registry artifact exists.

## Decision

### 1. Derived timestamp columns for the Feast layer only

Freeze the constant and the mapping:

```text
EPOCH_0           = 2020-01-01T00:00:00Z   (Unix 1577836800)
event_timestamp   = EPOCH_0 + step            hours
created_timestamp = EPOCH_0 + knowledge_step  hours
```

Both derived columns are UTC `TIMESTAMP`. The frozen step range maps to
`step = 1 -> 2020-01-01T01:00:00Z` through `step = 743 -> 2020-01-31T23:00:00Z`
(Unix `1580511600`), so the whole dataset lands inside January 2020.

1. **The mapping is bijective and order-preserving.** `f(n) = EPOCH_0 + n hours` is strictly
   monotone on integers, so `a < b` iff `f(a) < f(b)` and `a <= b` iff `f(a) <= f(b)`. It adds no
   information, removes none, and merges no two distinct steps. No PIT invariant is affected,
   because every invariant is a comparison and every comparison is preserved.
2. **`EPOCH_0` is a presentation convention, not a claim about the data.** ADR-002 decision 1
   fixed `step` as an hourly source ordinal, not a real business timestamp, and that stands.
   Deriving a timestamp does not create a business calendar: the resulting dates carry no weekday,
   month-end, holiday or business-hour meaning. They must never become a feature, a split
   boundary, or a date quoted in a report as if it were real.
3. **The derived columns serve the Feast layer only.** `src/pit_fintech/features/reference.py`
   remains the correctness authority, and it keeps reading `step` and `knowledge_step`. Feast
   output is compared against the oracle; a disagreement is a defect in the Feast layer, never
   evidence about the oracle.
4. **Cutoff order and tie-break do not move to timestamp comparison.** Eligibility stays exactly
   as ADR-001/ADR-003/ADR-005 define it:

   ```text
   prior.step           <  current.step
   AND prior.knowledge_step <= current.knowledge_step
   window = [current_step - window_hours, current_step)
   tie-break/replay order = (step, source_row_number)
   ```

   The derived columns are what Feast validates, partitions and joins on. They are not a second
   definition of eligibility, and no query may be rewritten to compare them instead. This is not a
   stylistic preference: hour-resolution timestamps *cannot* express the tie-break at all, because
   every row in the same `step` maps to the same instant. The ordering authority must therefore
   stay on the integer columns.
5. **`EPOCH_0` is frozen.** Changing it changes every derived timestamp, and therefore every
   registry artifact, Gold partition and online key derived from them. It requires a new ADR.
6. **`EPOCH_0` is deliberately distinct** from the provisional IEEE-CIS synthetic epoch in ADR-001
   (`2017-01-01T00:00:00Z`) and from the synthetic temporal fixture calendar (January 2024). A
   PaySim derived timestamp can therefore never be silently read as a synthetic-oracle timestamp,
   and vice versa.
7. **Derivation lives in the Gold projection built by T2**, expressed once, from the same contract
   module, and reused by the fixture builder. Bronze and Silver are not touched: ADR-005 already
   froze their columns, and a column that is re-derivable from `step` by a fixed affine map does
   not justify another 6.3-million-row rebuild. There is exactly one implementation of the mapping;
   the constant is never re-typed into a YAML file.

### 2. Bump the feature service version to `paysim-fraud-scoring-v2`

1. `PAYSIM_FEATURE_SERVICE_VERSION` becomes `paysim-fraud-scoring-v2`, matching
   `paysim-fraud-recipient-v2`.
2. **The twelve fields do not change.** Names, order, dtypes, defaults, availability, windows,
   entity, scoring scope and forbidden inputs are all exactly as ADR-003 froze them and ADR-005
   carried forward. `current_amount, event_step, transaction_type_transfer` then
   `pit_prior_count/pit_prior_amount/recipient_has_history` at 1h, 24h and 168h. Only the version
   string changes.
3. `service_version` is part of the canonical JSON, so the contract checksum changes. That is the
   intended effect: the checksum is what the registry, MLflow tags and materialization records
   bind to, and it should differ from the v1 contract because the cutoff semantics already do.
4. The Feast `FeatureService` is named for the frozen contract, not for the generic
   `fraud_scoring_v1` placeholder used in guide §3.2, which predates ADR-002 and ADR-003.
5. Every existing occurrence of the v1 string moves in the same commit as the constant. They are
   enumerated in Consequences below; none of them is changed by this ADR while it is `proposed`.

### 3. Feast's transitive `uvicorn` pin caps the `serving` dependency group

Every published Feast release (checked through 0.65.0, the current latest) depends on
`uvicorn[standard]>=0.30.6,<=0.34.0`. `uv` resolves every `[dependency-groups]` entry into one
shared universe, not one universe per group, so a bound that Feast's extra requires binds the
whole project, including the `serving` group, even though `serving` and `feast` are never
installed for the same run purpose.

Two escapes were considered and rejected by the project owner:

- **`[tool.uv] conflicts`** to let `feast` and `serving` resolve against different `uvicorn`
  versions in separate lock partitions. Rejected: adds resolver complexity and a second
  partition to reason about for a single transitive pin.
- **Separate environments** for the Feast control plane and the serving path. Rejected: violates
  the "same Python control plane" project convention and would require two lockfiles.

Decision: keep one universe and lower the `serving` group's `uvicorn[standard]` floor to fit
inside Feast's ceiling, pinned at the ceiling itself (`>=0.34,<=0.34.0`, i.e. `0.34.0`). This is
an intentional, accepted constraint, not an oversight: **`serving` cannot move `uvicorn` past
0.34.0 until Feast raises its own pin.** Revisit when a Feast release changes that bound.

## Alternatives considered

**Build T1 against the existing synthetic fixture oracle instead of PaySim.** The fixture in
`data/fixtures/` already has genuine `event_timestamp` and `created_timestamp` columns, so it makes
the time-typing problem disappear entirely, and guide §3.2/§3.4 literally names `card_entity` and
the synthetic expected vectors. Rejected: that fixture is the `fraud-history-v1` contract — entity
`card_entity_id`, 13 features including `seconds_since_previous_txn`, `distinct_products_7d` and
`current_amount_to_mean_24h`. The application contract is `paysim-fraud-recipient-v2` — entity
`destination_entity_id`, 12 features. They share no entity, no feature name and no source. A Feast
repository built on the fixture would validate an entity and a feature view that T2 must then
delete and rewrite, so T1 would produce throwaway work while leaving the real integration risk
undiscovered. The guide wording here predates ADR-002/ADR-003 and is superseded by them. The
fixture keeps its actual job: it remains the correctness oracle that Feast retrieval is checked
against under G1.

**Configure Feast to accept an integer event-time column.** Rejected: there is no documented
support for it. `FileSource` validates that `timestamp_field` names a column in the schema and
inferencing looks specifically for a timestamp column; nothing in the documented API declares an
integer ordinal as event time. Depending on undocumented behaviour of an offline-store internal
would put a hard project invariant on a surface that can change in any minor release, and Feast is
pre-1.0.

**Keep the service version at v1 and document the skew.** Rejected: the skew would then have to be
re-explained at every point that records the string — registry checksum, MLflow tag, online key
namespace, scoring response — and the one place it matters most is the one place nobody re-reads a
footnote, which is an incident six months later. A version string exists to be read literally. The
bump costs one constant and its call sites, and it costs them now, before any artifact binds to it.

## Consequences

- T1 can proceed: the Feast source has typed `event_timestamp`/`created_timestamp` columns and
  passes source validation, while the PIT computation stays on the integer columns.
- The contract checksum changes with the service version. No Gold table, registry artifact,
  materialization record or serving artifact references the v1 service string today, so nothing
  has to be rebuilt. The frozen E1/E4 metrics are model results bound to the Silver data and the
  feature semantics, not to the service string, and do not change.
- The following call sites must move together with the constant when this ADR is accepted. They
  are listed for review, not changed here:

  ```text
  src/pit_fintech/features/paysim_specs.py:16   PAYSIM_FEATURE_SERVICE_VERSION
  src/pit_fintech/config.py:29                  Settings.feature_service_version default
  .env.example:12                               PIT_FEATURE_SERVICE_VERSION
  tests/unit/test_paysim_feature_contract.py:39 asserted service string
  AGENTS.md:164                                 frozen-contract summary
  docs/reports/paysim-feature-contract-v1.md:15 report header (historical record)
  ```

- Feast enters the dependency set as its own optional group. It is not a runtime dependency of the
  correctness path, and it must not be able to break `test-temporal` or `test-unit` resolution.
- The `serving` group's `uvicorn[standard]` pin is capped at `0.34.0` by Feast's transitive
  requirement (decision 3 above); it cannot move independently while both groups share one
  resolution universe.
- The derived-timestamp expression becomes part of the Gold builder's declared surface, so it is
  covered by the T2 component fingerprint under ADR-004.
- Reports and notebooks must keep describing PaySim time as `step`. A derived January 2020 date is
  never presented as a business date.

## Revisit conditions

Write a new ADR rather than editing this one if:

- `EPOCH_0` has to change for any reason;
- knowledge time or event time needs a resolution finer than the hourly `step` ordinal, which
  would make the affine map lossy at the boundary;
- Feast gains documented support for a non-timestamp event-time column, which would let the
  derived columns be dropped;
- the twelve fields, their order, dtypes or defaults change, which is a feature-version bump under
  ADR-003, not a service-version bump; or
- Feast is dropped after the T1 time-box, in which case the fallback still has to supply the
  versioned `FeatureSpec`, `FeatureProvider`, Redis key contract, materialization manifest and
  parity gates (guide §3).
