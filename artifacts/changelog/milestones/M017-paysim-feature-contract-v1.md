# M017 — Freeze PaySim FeatureSpec v1

- Date: 2026-07-27
- Updated: 2026-07-27 13:13:54 +07:00
- Status: verified

## Scope and acceptance

Freeze an application FeatureSpec from the safe E4 vector after the verified LightGBM candidate
spike, without mutating the independent synthetic-oracle contract.

Implementation acceptance:

- 10–15 explicit PaySim specs with source, expression, dtype, default and availability;
- entity, source, scoring population, event time, tie-break, same-time and online update policies;
- exact ordered model vector shared by the contract and LightGBM code;
- canonical checksum over all cross-feature and per-feature semantics;
- labels, policy output, balance fields and E2 leaky controls excluded;
- configuration and public feature-repository exports aligned to v1;
- CLI/Make/PowerShell inspection boundary;
- ADR and human-readable report;
- regression tests for identity, order, windows, forbidden inputs, checksum and CLI output.

Runtime verification remains delegated to the user.

## Decisions

The synthetic `fraud-history-v1` contract remains the hand-calculated temporal oracle. The PaySim
application contract is separate:

```text
name: paysim-fraud-recipient-features
version: paysim-fraud-recipient-v1
service: paysim-fraud-scoring-v1
entity: destination_entity_id
entity definition: paysim-destination-customer-v1
scope: CASH_OUT / TRANSFER -> CUSTOMER destination
feature source: silver.paysim_transactions
label source: silver.paysim_labels
```

The 12 ordered model features are the safe E4 inputs:

```text
current_amount
event_step
transaction_type_transfer
pit_prior_count_1h
pit_prior_amount_1h
recipient_has_history_1h
pit_prior_count_24h
pit_prior_amount_24h
recipient_has_history_24h
pit_prior_count_168h
pit_prior_amount_168h
recipient_has_history_168h
```

Temporal policy:

- `step` is an hourly ordinal;
- history requires `prior_step < current_step`;
- windows are `[current_step - window_hours, current_step)`;
- same-step events are excluded;
- `source_row_number` is replay/tie-break lineage only;
- PaySim has no true source created-time field;
- online behavior is `read -> score -> update`.

The forbidden list is `isFraud`, `isFlaggedFraud` and all four balance columns. E2
current-inclusive/future/lifetime fields do not appear in v1.

LightGBM's static and PIT feature tuples now import the contract order. PaySim recipient
materialization emits the contract version rather than the earlier candidate version.

## Files added or changed

- `src/pit_fintech/contracts/features.py`
- `src/pit_fintech/contracts/__init__.py`
- `src/pit_fintech/features/paysim_specs.py`
- `src/pit_fintech/features/paysim_recipient.py`
- `src/pit_fintech/features/__init__.py`
- `src/pit_fintech/models/paysim_lightgbm.py`
- `src/pit_fintech/config.py`
- `src/pit_fintech/cli.py`
- `feature_repo/feature_specs.py`
- `tests/unit/test_paysim_feature_contract.py`
- `tests/unit/test_paysim_lightgbm_spike.py`
- `.env.example`
- `Makefile`
- `make.ps1`
- `README.md`
- `AGENTS.md`
- `docs/research-protocol.md`
- `docs/adr/003-paysim-feature-contract-v1.md`
- `docs/reports/paysim-feature-contract-v1.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

The user ran the requested verification commands:

```text
.\make.ps1 features
  exit 0
  version: paysim-fraud-recipient-v1
  service: paysim-fraud-scoring-v1
  feature rows: 12
  checksum: 5b4e2b6db613f28dd6da209c50a5c3beb82969247e0248d39007bea9c9c26cf4

.\make.ps1 test-temporal
  23 passed in 1.97s
  exit 0

.\make.ps1 test-notebooks
  PASS notebooks 01–04
  exit 0
```

The first `.\make.ps1 test-unit` run produced `29 passed, 1 failed`. The failure was isolated to
the CLI smoke test searching for `pit_prior_count_168h` inside a Rich table captured at
`CliRunner`'s narrower width. The same command's normal terminal output visibly contained that
feature, while all semantic contract tests passed. This was a presentation-width-sensitive test,
not a feature-contract failure.

The CLI now emits the stable scalar `feature_count: 12`, and the smoke test asserts that value
instead of a long rendered table cell. The user subsequently confirmed that the corrected
`.\make.ps1 test-unit` suite passed. Exact count, duration and exit-code text were not supplied,
so this log does not invent those values.

The initial `Parent appears to have exited` message was a shutdown warning from an earlier
Jupyter kernel. The Windows ZMQ/TCP warnings during notebook verification are non-blocking local
kernel warnings; the verifier completed all four notebooks and returned exit code `0`.

Static verification:

```text
git diff --check: pass (working-copy CRLF notices only)
Python source line-length scan at 100 columns: pass
PowerShell parser for make.ps1: 0 errors
old paysim-recipient-v1 literal in active code/config: 0
LightGBM PIT tuple -> PAYSIM_MODEL_FEATURE_ORDER: linked
recipient strict-PIT tuple -> PAYSIM_HISTORY_FEATURE_NAMES: linked
Make/PowerShell/README features command presence: pass
```

M017 is verified: contract inspection, the corrected unit suite, the temporal suite and all four
notebooks pass.

## Known gaps and next step

- `silver.paysim_transactions` and `silver.paysim_labels` are contracted names but the PaySim
  application Bronze/Silver path is not implemented yet.
- Feast, Gold, Redis materialization, parity, serving and model promotion remain Sprint 2 work.
- The verified M016 artifact references the pre-contract candidate version and a dirty commit; it
  remains historical evidence and is not rewritten.
- Next: implement the PaySim Bronze/Silver application path that satisfies the frozen source
  contracts.
