# Data access and immutable raw policy

## Credential-free acceptance path

`make data-sample` or `.\make.ps1 data-sample` validates the committed temporal source against
hand-calculated vectors, writes `data/fixtures/temporal_cases.parquet`, and records a runtime
manifest under `artifacts/sample/`. This path is sufficient for correctness and CI.

## PaySim EDA-first path (planned)

1. Acquire PaySim from its authorized source and record license/source metadata.
2. Download into `data/raw/` through the future `data` command.
3. Verify filename, byte count, and SHA-256 before extraction or processing.
4. Profile event ordering, origin/destination history, class imbalance, duplicates and leakage
   risk in the balance columns.
5. Record the dataset/entity/time policy and the model-family decision in ADRs only after EDA.

## IEEE-CIS alternative path (planned)

1. Accept the IEEE-CIS Fraud Detection competition rules in Kaggle.
2. Configure Kaggle credentials outside this repository.
3. Use the future `data` command to download into `data/raw/`.
4. Verify filename, byte count, and SHA-256 before extraction or processing.
5. Never overwrite a matching immutable raw archive.

No credential value is printed by `doctor`; it reports presence only. Raw competition data is
gitignored and must not be republished.

## Dataset and model go/no-go

PaySim is the first application dataset to profile. IEEE-CIS and Home Credit remain alternatives,
not simultaneous MVP benchmarks. IEEE-CIS viability still requires comparing at least C1
(`card1|card2|card3|card5`) and C2 (C1 plus `addr1`). Home Credit is eligible only when the
selected dataset variant exposes explicit event time and repeated entity history suitable for a
PIT join. The synthetic oracle continues unchanged for every application dataset.

LightGBM is a candidate baseline, not a locked architecture decision. Freeze the model family
only after PaySim EDA has measured schema/cardinality, missingness, imbalance, temporal split
behavior and leakage risk; keep the chosen configuration fixed across E1–E5 afterward.
