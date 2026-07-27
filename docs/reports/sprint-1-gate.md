# Sprint 1 gate status

Date: 2026-07-27. Overall status: **PASS**.

The frozen handoff, accepted limits and Sprint 2 entry contract are in the
[Sprint 1 completion report](sprint-1-completion-report.md).

| Gate | Current evidence | Status |
|---|---|---|
| G1 Data access | Full PaySim snapshot `paysim1:16910f90577b0d98`, 6,362,620 rows and raw SHA-256 verified | pass |
| G2 Lakehouse | Full PaySim Bronze/Silver v1 rebuilt from clean commit `6e93e7f…`; prior v0 remains time-travel evidence | pass |
| G3 Entity viability | ADR-002 retains destination customer history with `AMBER_CORRECTNESS_ONLY` | pass |
| G4 PIT correctness | Latest temporal suite passed 23/23; future-read violations `0` | pass |
| G5 Leakage control | Notebook 03/M017 exclude current/future reads; full M018 Silver source separates label and forbidden fields | pass |
| G6 Feature scope | M017 freezes 12 ordered E4-safe fields and canonical checksum | pass |
| G7 Feasibility | Full build: 56.29s, 113,030 rows/s, 649,248,646 Delta bytes, 31 partitions; RSS before/after recorded | pass |
| G8 Baseline | clean exact-Silver E1/E4 run `e1ebc…`; 322,461 vectors, 0 future reads, two child runs and skops models; weaker E4 retained | pass |
| G9 Protocol | ADR-002/003 and research protocol lock dataset, entity, split, metrics and version policy | pass |

Representative verified commands:

```text
uv sync --frozen --group dev
pit doctor
pit data sample
pit data profile --dataset sample
pit data build-lakehouse --dataset sample
pit notebooks verify
.\make.ps1 test-temporal         # 23 passed
.\make.ps1 test-unit             # 34 passed
.\make.ps1 test-lakehouse        # 4 passed, includes M019 exact-Silver vectors
.\make.ps1 test-notebooks        # notebooks 01–05 pass
.\make.ps1 model-spike           # E1–E4 + MLflow manifest pass
.\make.ps1 features              # FeatureSpec checksum pass
.\make.ps1 test-unit             # corrected suite confirmed pass by user
```

Sprint 1 is complete. Sprint 2 starts with Gold/backfill/Feast/Redis materialization and must use
an explicit probability-scoring wrapper before any E4 promotion or serving claim.
