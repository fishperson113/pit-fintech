# Sprint 1 gate status

Date: 2026-07-27. Overall status: **IN PROGRESS**, pending the clean Silver-based baseline.

| Gate | Current evidence | Status |
|---|---|---|
| G1 Data access | Full PaySim snapshot `paysim1:16910f90577b0d98`, 6,362,620 rows and raw SHA-256 verified | pass |
| G2 Lakehouse | Full PaySim Bronze/Silver v0 plus synthetic/fixture rerun and time-travel evidence verified | pass |
| G3 Entity viability | ADR-002 retains destination customer history with `AMBER_CORRECTNESS_ONLY` | pass |
| G4 PIT correctness | Latest temporal suite passed 23/23; future-read violations `0` | pass |
| G5 Leakage control | Notebook 03/M017 exclude current/future reads; full M018 Silver source separates label and forbidden fields | pass |
| G6 Feature scope | M017 freezes 12 ordered E4-safe fields and canonical checksum | pass |
| G7 Feasibility | Full build: 56.29s, 113,030 rows/s, 649,248,646 Delta bytes, 31 partitions; RSS before/after recorded | pass |
| G8 Baseline | M016 E1–E4 spike verified; clean locked baseline from Silver remains | implemented |
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
.\make.ps1 test-notebooks        # notebooks 01–04 pass
.\make.ps1 model-spike           # E1–E4 + MLflow manifest pass
.\make.ps1 features              # FeatureSpec checksum pass
.\make.ps1 test-unit             # corrected suite confirmed pass by user
```

Next gate work:

1. commit the verified M016–M018 implementation;
2. rerun the locked LightGBM temporal baseline from exact Silver Delta version 0;
3. freeze its clean dataset/model lineage before declaring Sprint 1 complete.
