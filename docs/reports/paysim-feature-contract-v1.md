# PaySim FeatureSpec v1

Status: **verified**. Contract CLI, corrected unit suite, temporal suite and notebooks 01–04
passed in user-run verification.

The application contract is frozen in
`src/pit_fintech/features/paysim_specs.py`. The older `fraud-history-v1` contract remains the
synthetic temporal-oracle contract.

## Contract identity

```text
name: paysim-fraud-recipient-features
version: paysim-fraud-recipient-v1
service: paysim-fraud-scoring-v1
entity: destination_entity_id
scoring scope: CASH_OUT, TRANSFER -> CUSTOMER destination
source: silver.paysim_transactions
label source: silver.paysim_labels
cutoff: prior_step < current_step
online update: score_then_update
```

## Vector shape

The ordered 12-feature vector contains:

- three request-time features: amount, step and transfer indicator;
- recipient count, amount sum and cold-start indicator at 1h, 24h and 168h.

Labels, the existing policy output and all four PaySim balance fields are forbidden. E2 leaky
features are deliberately absent.

## Inspect and verify

```powershell
.\make.ps1 features
$LASTEXITCODE

.\make.ps1 test-unit
$LASTEXITCODE

.\make.ps1 test-temporal
$LASTEXITCODE
```

`features` prints the canonical checksum and all fields in model order. Unit tests require the
contract, LightGBM E4 vector and configuration defaults to share exactly the same version and
ordering.

## Downstream contract

Sprint 1 next creates:

```text
PaySim CSV
  -> Bronze raw snapshot
  -> Silver paysim_transactions
  -> Silver paysim_labels
  -> PIT Gold vector using paysim-fraud-recipient-v1
```

Sprint 2 materialization and serving must use the same checksum. Redis state is updated only
after the current event has been scored.
