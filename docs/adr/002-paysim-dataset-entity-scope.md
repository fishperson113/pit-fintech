# ADR-002: Keep PaySim as the primary pipeline workload

- Status: accepted
- Date: 2026-07-27
- Supersedes: provisional application-dataset assumptions in ADR-001

## Context

The project outcome is an evidence-backed PIT feature pipeline, not the highest possible fraud
model score. The primary gates are temporal correctness, reproducible backfill, offline/online
parity, deterministic replay, version safety and serving behavior.

The frozen PaySim snapshot is:

```text
dataset_snapshot_id: paysim1:16910f90577b0d98
rows: 6,362,620
step range: 1-743
sha256: 16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b
```

Full-data EDA found:

- 99.8537% of origin entities occur only once.
- Only 1,769 customer accounts, or 0.0256%, occur in both origin and destination roles.
- Current-origin prior-history coverage is approximately 0.15%-0.27%.
- No fraudulent cash-out has a linkable earlier incoming transfer by exported account ID.
- Customer destination history is meaningful for some `CASH_OUT` events but effectively absent
  for fraudulent `TRANSFER` events.

The predeclared destination-history gate produced:

| Slice | Train warm fraud | Validation warm fraud | Test warm fraud | Gate |
|---|---:|---:|---:|---|
| `CASH_OUT` | 2,058 (70.9655%) | 186 (31.5254%) | 101 (16.1342%) | AMBER |
| `TRANSFER` | 4 (0.1388%) | 0 (0%) | 0 (0%) | RED |

The dataset-level result is `AMBER_CORRECTNESS_ONLY`.

## Decision

Keep PaySim as the primary application workload for the six-week pipeline implementation.

1. Treat `step` as an hourly source ordinal, not a real business timestamp.
2. Persist `source_row_number` once in Bronze and use `(step, source_row_number)` as the
   deterministic replay/cutoff order with strict `<` semantics.
3. Use `prior_step < current_step` for conservative model-utility and dataset-viability claims;
   same-hour row order remains a reported sensitivity, not the basis of a model claim.
4. Use customer `nameDest` as the recipient-history entity where applicable. Keep `M...`
   merchant destinations separate.
5. Do not use origin or cross-role customer history as the primary behavioral view because its
   coverage is negligible.
6. Use 1-hour, 24-hour and 168-hour recipient windows. The 168-hour window is the frozen
   viability gate; shorter windows remain feature/ablation candidates.
7. Use chronological step ranges 1-520 for training, 521-631 for validation and 632-743 for test.
8. Provide static request-time features for every transaction. Recipient-history features and an
   explicit cold-start/coverage indicator are most relevant to `CASH_OUT`; `TRANSFER` must work
   correctly with cold defaults.
9. Keep fraud labels strictly evaluation-only. Do not use balance or post-outcome fields until a
   separate leakage decision explicitly permits them.
10. Keep model family TBD until the static/PIT baseline evidence is available. Model choice must
    not be used to hide sparse-history or correctness failures.

IEEE-CIS is not adopted for the MVP. A short IEEE-CIS entity-viability spike is optional only if
a later thesis extension requires stronger evidence that historical features improve model
utility.

## Consequences

- PaySim is sufficient for demonstrating the engineering claims: PIT joins, deterministic
  backfill, snapshot/version reproducibility, replay, serving parity and failure gates.
- The project must not claim that historical features improve fraud detection consistently over
  the complete PaySim population.
- Model reports must separate at least `CASH_OUT` warm, `CASH_OUT` cold and `TRANSFER` cold
  behavior in addition to population metrics.
- Low or negative model lift after removing leakage is an acceptable result.
- The synthetic temporal oracle remains the correctness ground truth; PaySim fraud labels remain
  model-evaluation ground truth.
- Feature contracts must now be adapted from provisional IEEE-CIS semantics to PaySim
  transaction and recipient semantics.

## Revisit conditions

Revisit this ADR only if:

- full PaySim Bronze/Silver/Gold builds exceed the accepted CPU/RAM/disk budget;
- PaySim cannot support the required end-to-end replay and parity gates; or
- the project scope explicitly changes from engineering-first to a thesis claim requiring strong
  historical-feature model utility.

Any replacement dataset must pass the same entity-history and temporal-split viability gate
before migration.
