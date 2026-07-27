# Sprint 1 completion report

Date: 2026-07-27
Outcome: **PASS — ready to enter Sprint 2**

Sprint 1 has closed the temporal contract, dataset feasibility, application lakehouse and
baseline-training risks. This is a Sprint 1 release gate, not a claim that the full six-week
platform is complete.

## Frozen handoff

| Boundary | Frozen value |
|---|---|
| Dataset | `paysim1:16910f90577b0d98` |
| Raw rows / time range | 6,362,620 rows / steps 1–743 |
| Raw SHA-256 | `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b` |
| Event order | `(step, source_row_number)` |
| Model cutoff | strict `prior_step < current_step` |
| Model entity | destination customer |
| Feature version | `paysim-fraud-recipient-v1` |
| Feature checksum | `5b4e2b6db613f28dd6da209c50a5c3beb82969247e0248d39007bea9c9c26cf4` |
| Silver versions | transactions v1 / labels v1 |
| Clean code/lakehouse commit | `6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5` |
| Training-vector checksum | `c7f07593038c2d67b325254702073864f6eb3f193ee34031855ebc1fbd93b8b8` |
| MLflow parent run | `e1ebc167813e40b88f16c6e611decea7` |

The synthetic fixture remains the correctness oracle. PaySim remains the application workload
with the ADR-002 status `AMBER_CORRECTNESS_ONLY`: suitable for PIT/MLOps engineering evidence,
but not for claiming that historical features consistently improve fraud detection.

## Definition of Done

| Gate | Evidence | Result |
|---|---|---|
| Data access | immutable snapshot manifest, full SHA-256 and profile | pass |
| Temporal/entity contract | ADR-002 fixes time, entity, tie-break, cutoff and split | pass |
| Synthetic oracle | future, duplicate, tie, late-arrival, boundary and cold-start cases | pass |
| Bronze/Silver | exact Delta v1, label separation, 8/8 quality gates | pass |
| Feature scope | 12 ordered fields frozen by ADR-003 and canonical checksum | pass |
| Leakage control | forbidden/post-outcome fields excluded; strict source-step audit | pass |
| PIT implementation | reusable code under `src/` with 0 future-read violations | pass |
| Feasibility | 56.29 s full build, 113,030 rows/s, 31 partitions | pass |
| Baseline | exact-Silver E1/E4 temporal run and MLflow/skops artifacts | pass |
| Reproducible interface | CLI/Make/PowerShell commands and five thin notebooks | pass |

User-provided verification:

```text
test-temporal     23 passed, exit 0
test-unit         34 passed, exit 0
test-lakehouse     4 passed, exit 0
test-notebooks     5 notebooks passed, exit 0
full lakehouse     3 Delta v1 tables, 8 quality gates passed
full training      E1 and E4 completed, 0 future reads
```

The notebook verifier's Windows ZMQ/TCP messages were local-kernel warnings, not failed cells.
Notebook 05 has been returned to an output-free source state. Runtime JSON manifests and MLflow
artifacts remain the authoritative evidence.

## Baseline interpretation

| Experiment | PR-AUC | ROC-AUC | Recall | Observed FPR |
|---|---:|---:|---:|---:|
| E1 static/temporal | 0.258342 | 0.601620 | 0.275559 | 0.007951 |
| E4 PIT/temporal | 0.102766 | 0.784978 | 0.036741 | 0.003894 |

E4 has higher global ROC-AUC but weaker PR-AUC and fixed-FPR recall. This does not invalidate
the PIT implementation. It confirms the already documented PaySim limitation: recipient history
is sparse and its utility shifts across chronological periods. The result is frozen without
post-result tuning.

## Authoritative evidence

- [Sprint 1 gate](sprint-1-gate.md)
- [PaySim application data profile](paysim-data-profile.md)
- [PaySim dataset/entity ADR](../adr/002-paysim-dataset-entity-scope.md)
- [PaySim FeatureSpec ADR](../adr/003-paysim-feature-contract-v1.md)
- [Application lakehouse report](paysim-application-lakehouse.md)
- [Silver training baseline](paysim-silver-training-baseline.md)
- [Research protocol](../research-protocol.md)
- `artifacts/datasets/paysim1/16910f90577b0d98/snapshot-manifest.json`
- `artifacts/datasets/paysim1/16910f90577b0d98/lakehouse/lakehouse-manifest.json`
- `artifacts/experiments/paysim-silver-training/e1ebc167813e40b88f16c6e611decea7/manifest.json`

The three runtime paths are local, immutable evidence and remain gitignored by design.

## Accepted limits

- PaySim has synthetic hourly time and no application-data knowledge-time field; late-arrival
  truth stays grounded in the synthetic oracle.
- E4 is a baseline candidate, not a promoted production model.
- MLflow's current sklearn pyfunc surface predicts labels. Sprint 2 must add an explicit
  probability-scoring wrapper and bind its threshold to a deployment manifest.
- Post-closure ADR-004 replaces coarse Git commit equality with component fingerprints; the
  frozen M019 result remains valid historical evidence under its original clean-commit policy.
- CI is implemented as a fast fixture lane; a hosted clean-clone run is not claimed here.
- Redis materialization, Gold backfill, offline/online parity, serving, replay and
  promotion/rollback are intentionally Sprint 2 work.

## Sprint 2 entry contract

Sprint 2 may start only from the frozen values above. Its first vertical slice is:

```text
exact Silver v1
  -> versioned Gold backfill
  -> thin Feast contract
  -> Redis materialization
  -> FeatureProvider probability scoring
  -> score-before-update replay
  -> offline/online parity evidence
```

Any change to entity, cutoff, feature order, dtype, default, window or forbidden fields requires
a new contract version and a new training run; Sprint 1 evidence must not be mutated in place.
