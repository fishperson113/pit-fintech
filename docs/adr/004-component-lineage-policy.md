# ADR-004: Use component fingerprints instead of repository-wide commit equality

- Status: accepted
- Date: 2026-07-27
- Applies to: PaySim lakehouse and Silver training lineage

## Context

The original M019 guard required:

```text
training Git commit == application-lakehouse Git commit
```

This rejected a valid CLI training run after commit `729d85f`, even though that commit changed
only Sprint 1 documentation and audit files. Rebuilding 6.3 million rows after an unrelated
documentation change does not improve data correctness or reproducibility.

Git commit identity is useful audit metadata, but it is too broad to decide whether an exact
Delta source remains compatible with a trainer.

## Decision

Use three independent lineage boundaries.

### 1. Exact materialized data

Training continues to validate:

- dataset snapshot and raw SHA-256;
- exact Silver Delta versions;
- row counts, schema checksums and logical checksums;
- transaction/label identity;
- FeatureSpec version and canonical checksum.

These checks decide whether the existing Silver artifact is the expected input. The current
lakehouse builder does not need to share the trainer's Git commit.

### 2. Component-scoped source fingerprints

Each component hashes only its declared source/dependency paths using
`component-fingerprint-v1`.

Lakehouse boundary:

```text
src/pit_fintech/data/paysim_lakehouse.py
src/pit_fintech/data/paysim.py
src/pit_fintech/contracts/manifests.py
src/pit_fintech/features/paysim_specs.py
src/pit_fintech/platform/lineage.py
pyproject.toml
uv.lock
```

Training boundary:

```text
src/pit_fintech/models/paysim_training.py
src/pit_fintech/models/paysim_lightgbm.py
src/pit_fintech/contracts/manifests.py
src/pit_fintech/data/paysim_lakehouse.py
src/pit_fintech/features/paysim_recipient.py
src/pit_fintech/features/paysim_specs.py
src/pit_fintech/platform/lineage.py
pyproject.toml
uv.lock
```

The canonical hash includes the policy version, normalized relative path, byte length and file
content. Missing declared files are represented explicitly.

### 3. Scoped dirty-state guard

- Uncommitted changes inside the training component are rejected before training.
- A new lakehouse manifest records whether its lakehouse component was dirty; dirty component
  builds cannot become clean training inputs.
- Documentation-only changes do not trip either component guard.
- Repository-wide dirty state is still recorded for transparency.
- Git commits remain in manifests and MLflow as audit references; equality is not a gate.

Legacy lakehouse manifests have no component fingerprint. A legacy manifest is accepted only
when its recorded commit is clean; exact Delta/contract checks still apply. A legacy
`UNCOMMITTED` or `-dirty` manifest remains blocked conservatively.

## Rebuild policy

| Change | Required action |
|---|---|
| README, report, ADR or changelog | no lakehouse rebuild |
| Training/model implementation | commit, then train again |
| Training dependency lock | commit, then train again |
| FeatureSpec semantics | new version and affected Gold/Silver rebuild |
| Silver SQL/schema/entity/order logic | rebuild Silver |
| Raw snapshot | rebuild Bronze, Silver and downstream artifacts |

## Consequences

- Exact Silver v1 from clean commit `6e93e7f` remains a valid input after later documentation or
  trainer commits.
- New training manifests expose their component fingerprint, path boundary, scoped dirty flag
  and repository-wide dirty flag.
- New application-lakehouse manifests expose the equivalent lakehouse fields.
- `--allow-dirty` remains an explicit diagnostic escape hatch; it does not create promotable
  evidence.
- Dependency and component boundaries must be reviewed when imports move. A missing path changes
  the fingerprint rather than silently disappearing.
