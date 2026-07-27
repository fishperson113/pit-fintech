# M020 — Sprint 1 closure

- Date: 2026-07-27
- Status: verified

## Scope and acceptance

Close Sprint 1 only after reconciling the guide, gate report, immutable runtime manifests and
user-provided command outputs. The closure must:

- map every Sprint 1 gate to concrete evidence;
- freeze the dataset, Silver, FeatureSpec, code and MLflow lineage handed to Sprint 2;
- keep weak E4 model utility as an honest result;
- remove saved runtime output from notebook 05;
- distinguish Sprint 1 completion from completion of the full platform;
- synchronize project status, changelog, handoff and human-readable reports.

## Decisions

- M001–M019 contain the implementation history; M020 does not introduce a new pipeline.
- The guide's provisional IEEE-CIS assumptions are superseded by accepted ADR-002/003 PaySim
  decisions, not treated as missing work.
- Runtime manifests and MLflow artifacts are authoritative. Notebook output is review material
  and must not be committed.
- The final project self-review hard gates for online parity, atomic incremental backfill,
  serving and incident recovery remain open because they belong to Sprint 2/3.
- Sprint 2 must add probability scoring plus a manifest-bound threshold before model promotion.

## Files added or changed

- `docs/reports/sprint-1-completion-report.md`
- `docs/reports/paysim-data-profile.md`
- `docs/reports/sprint-1-gate.md`
- `docs/reports/paysim-silver-training-baseline.md`
- `docs/research-protocol.md`
- `README.md`
- `AGENTS.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M019-silver-training-baseline.md`
- this milestone log

Notebook `notebooks/05_silver_training_baseline.ipynb` was mechanically cleared and restored to
the exact committed output-free content; it is not part of the closure change set.

## Verification

No model, notebook, pytest or data pipeline was executed by the agent. Closure relies on the
user-run evidence already persisted and audited in M019:

```text
test-temporal:   23 passed, exit 0
test-unit:       34 passed, exit 0
test-lakehouse:   4 passed, exit 0
test-notebooks:   5 passed, exit 0
lakehouse:        3 Delta v1 tables, 8/8 gates
training:         E1/E4 completed, future-read violations 0
```

Static closure checks confirmed that the raw snapshot manifest, latest lakehouse manifest,
training manifest, temporal fixture, CI workflow, dependency lock, architecture and required
reports exist. The notebook working-tree object hashes to the committed output-free object.

Frozen handoff:

```text
dataset snapshot: paysim1:16910f90577b0d98
Silver:           transactions v1 / labels v1
FeatureSpec:      paysim-fraud-recipient-v1
feature checksum: 5b4e2b6db613f28dd6da209c50a5c3beb82969247e0248d39007bea9c9c26cf4
clean code:       6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5
training vector:  c7f07593038c2d67b325254702073864f6eb3f193ee34031855ebc1fbd93b8b8
MLflow parent:    e1ebc167813e40b88f16c6e611decea7
```

## Deviations, gaps and next step

- The original guide names IEEE-CIS in provisional examples; PaySim is the accepted application
  path and its ADRs are authoritative.
- Hosted CI and Compose image runtime are not required Sprint 1 gates and are not claimed as
  verified.
- The full project is not yet portfolio/thesis complete. Sprint 2 owns Gold/backfill, Feast,
  Redis, serving, replay, parity and model lifecycle.
- Next milestone: implement the smallest versioned Gold full-backfill slice from exact Silver v1
  before adding Redis or FastAPI.
