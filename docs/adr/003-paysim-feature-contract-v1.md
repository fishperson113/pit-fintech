# ADR-003: Freeze PaySim FeatureSpec v1

- Status: accepted
- Date: 2026-07-27
- Depends on: ADR-002 and verified M016 LightGBM candidate spike

## Context

ADR-002 retained PaySim as an engineering-first application workload and fixed destination
customer history as the only viable behavioral entity for the MVP. M016 then compared:

| ID | Features / split | PR-AUC | Role |
|---|---|---:|---|
| E1 | static / temporal | 0.176951 | request-only baseline |
| E2 | leaky / random | 0.915528 | invalid positive control |
| E3 | PIT / random | 0.892585 | split-policy diagnostic |
| E4 | PIT / temporal | 0.324524 | main safe candidate |

The spike used a sampled cohort and a dirty commit. It is sufficient to select safe feature
semantics, but not to promote a model or claim production performance.

The existing `fraud-history-v1` contract remains the synthetic temporal oracle contract. It is
not silently repurposed because its provisional card entity and generic transaction source do not
describe PaySim.

## Decision

Freeze the PaySim application contract as:

```text
contract: paysim-fraud-recipient-features
feature version: paysim-fraud-recipient-v1
service version: paysim-fraud-scoring-v1
entity: destination_entity_id
entity definition: paysim-destination-customer-v1
scoring scope: CASH_OUT and TRANSFER with CUSTOMER destination
feature source: silver.paysim_transactions
label source: silver.paysim_labels
```

The model vector order is part of the contract:

| # | Feature | Availability | Window | Dtype | Default |
|---:|---|---|---:|---|---:|
| 1 | `current_amount` | request | — | float64 | 0.0 |
| 2 | `event_step` | request | — | float64 | 0.0 |
| 3 | `transaction_type_transfer` | request | — | float64 | 0.0 |
| 4 | `pit_prior_count_1h` | history | 1h | int64 | 0 |
| 5 | `pit_prior_amount_1h` | history | 1h | float64 | 0.0 |
| 6 | `recipient_has_history_1h` | history | 1h | int64 | 0 |
| 7 | `pit_prior_count_24h` | history | 24h | int64 | 0 |
| 8 | `pit_prior_amount_24h` | history | 24h | float64 | 0.0 |
| 9 | `recipient_has_history_24h` | history | 24h | int64 | 0 |
| 10 | `pit_prior_count_168h` | history | 168h | int64 | 0 |
| 11 | `pit_prior_amount_168h` | history | 168h | float64 | 0.0 |
| 12 | `recipient_has_history_168h` | history | 168h | int64 | 0 |

### Temporal semantics

- `step` is an hourly ordinal.
- Historical eligibility is conservative: `prior_step < current_step`.
- A window is `[current_step - window_hours, current_step)`.
- Events at the same `step` are excluded from model features.
- `source_row_number` is the deterministic replay/tie-break column, not permission to read an
  earlier CSV row from the same hour for model-utility claims.
- PaySim has no source created-time field. Raw snapshot and ingestion lineage are recorded, while
  late-arrival knowledge-time correctness remains grounded in the synthetic oracle.
- Online execution must be `read history -> score current event -> update state`.

### Allowed and forbidden inputs

Request-time inputs are `amount`, `step` and `transaction_type`. History aggregates read only
prior destination events. `recipient_has_history_*` makes cold start explicit. V1 model scoring
is limited to `CASH_OUT` and `TRANSFER` rows with a customer destination, matching the frozen
E1–E4 cohort; other PaySim transaction types remain pipeline data but are outside this model
contract.

The following fields are forbidden model inputs:

```text
isFraud
isFlaggedFraud
oldbalanceOrg
newbalanceOrig
oldbalanceDest
newbalanceDest
```

`isFraud` is stored separately as an evaluation label. The existing policy output and PaySim
balance fields cannot enter Gold features, online vectors or model inputs under v1.

### Version and change policy

The canonical JSON checksum covers cross-feature policy, every feature declaration and model
feature order. Any change to entity, source, window, expression, dtype, default, order, cutoff or
forbidden fields requires:

1. a new feature version;
2. a new ADR or amendment;
3. backfill under the new version;
4. offline/online parity evidence;
5. a new model run tied to the new checksum.

The contract may not be edited in place after a Gold, training or serving artifact references it.

## Consequences

- E4 training no longer owns a copied feature-name list; it imports the frozen contract order.
- PaySim PIT materialization emits the same feature-definition version.
- The public feature repository exposes synthetic and PaySim contracts separately.
- Feast remains a thin Sprint 2 adapter over this contract; it does not redefine PIT semantics.
- The next PaySim Bronze/Silver build must create the named feature and label sources.
- LightGBM remains the selected baseline candidate, not a promoted model family. The clean
  Silver-based temporal run is still required.

## Revisit conditions

Create v2 rather than mutating v1 if:

- the Silver schema renames a contracted source field;
- a new request-time field is admitted;
- window or same-step semantics change;
- another entity becomes viable;
- model serving requires a different dtype or feature order; or
- natural-prevalence evaluation rejects the current feature set.
