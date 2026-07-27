# PaySim application data profile

Status: **verified**
Dataset snapshot: `paysim1:16910f90577b0d98`

This report consolidates the full-data outputs from notebooks 01–02 into the Sprint 1 handoff.
It is a contract/feasibility profile, not a general-purpose visualization report.

## Snapshot and grain

| Metric | Value |
|---|---:|
| Rows | 6,362,620 |
| Raw bytes | 493,534,783 |
| Step range | 1–743 |
| Distinct origins | 6,353,307 |
| Distinct destinations | 2,722,362 |
| Fraud rows | 8,213 |
| Fraud rate | 0.129082% |
| Existing flagged rows | 16 |

One row represents one simulated mobile-money transaction. PaySim defines one `step` as one
simulated hour. The observed range therefore spans 743 hourly ordinals; it is not a real business
calendar and must not be presented as one.

Raw SHA-256:

```text
16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b
```

## Quality profile

The verified full-data checks found:

| Check | Count |
|---|---:|
| null `step` | 0 |
| null/empty `type` | 0 |
| null `amount` | 0 |
| null/empty origin | 0 |
| null/empty destination | 0 |
| null fraud label | 0 |
| negative amount | 0 |
| invalid binary fraud label | 0 |

These checks support ingestion feasibility. They do not prove temporal correctness or feature
availability; those are enforced separately by the temporal oracle and FeatureSpec.

## Transaction and label distribution

| Type | Rows | Fraud rows | Fraud rate | Median amount |
|---|---:|---:|---:|---:|
| `CASH_OUT` | 2,237,500 | 4,116 | 0.183955% | 147,072.19 |
| `PAYMENT` | 2,151,495 | 0 | 0% | 9,482.19 |
| `CASH_IN` | 1,399,284 | 0 | 0% | 143,427.71 |
| `TRANSFER` | 532,909 | 4,097 | 0.768799% | 486,308.39 |
| `DEBIT` | 41,432 | 0 | 0% | 3,048.99 |

Fraud is rare and exists only in `CASH_OUT` and `TRANSFER` in this snapshot. Accuracy is
therefore not an acceptable primary metric; the frozen model protocol uses PR-AUC plus
recall/precision at a validation-selected FPR budget.

## Temporal and entity viability

- 6,344,009 of 6,353,307 origin entities are singletons: 99.8537%.
- 2,262,704 of 2,722,362 destination entities are singletons: 83.1155%.
- Only 1,769 customer accounts, or 0.0256%, appear in both origin and destination roles.
- Current-origin prior-history coverage is only approximately 0.15%–0.27%.
- The exported identifiers do not preserve a linkable earlier fraudulent `TRANSFER` for a
  fraudulent `CASH_OUT`.

Origin and cross-role histories are therefore rejected as the primary behavioral entity.
Destination-customer history is retained with the following conservative seven-day gate:

| Fraud slice | Train warm | Validation warm | Test warm | Result |
|---|---:|---:|---:|---|
| `CASH_OUT` | 2,058 | 186 | 101 | AMBER |
| `TRANSFER` | 4 | 0 | 0 | RED |

The dataset decision is `AMBER_CORRECTNESS_ONLY`: keep PaySim for engineering evidence, but do
not claim stable history-feature model lift.

## Leakage inventory

Allowed request-time fields under FeatureSpec v1:

```text
step
type
amount
```

Allowed history inputs are strict prior destination aggregates only. The following fields are
forbidden model inputs:

```text
isFraud
isFlaggedFraud
oldbalanceOrg
newbalanceOrig
oldbalanceDest
newbalanceDest
```

`isFraud` is evaluation-only. The PaySim source specifically warns that balance columns reflect
fraud cancellation behavior, while `isFlaggedFraud` is an existing policy output rather than
neutral request context.

## Resulting contract decisions

- order by `(step, source_row_number)`;
- use strict `prior_step < current_step` for model features;
- split steps 1–520 / 521–631 / 632–743;
- use destination customer as the history entity;
- use 1h, 24h and 168h windows with explicit cold-start defaults;
- keep the synthetic temporal fixture as the late-arrival/future-read oracle.

See [ADR-002](../adr/002-paysim-dataset-entity-scope.md) for the accepted dataset/entity decision
and [ADR-003](../adr/003-paysim-feature-contract-v1.md) for the frozen model vector.
