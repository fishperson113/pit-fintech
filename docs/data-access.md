# Data access and immutable raw policy

## Credential-free acceptance path

`make data-sample` or `.\make.ps1 data-sample` validates the committed temporal source against
hand-calculated vectors, writes `data/fixtures/temporal_cases.parquet`, and records a runtime
manifest under `artifacts/sample/`. This path is sufficient for correctness and CI.

## PaySim EDA-first path

1. Acquire PaySim from its authorized source and record license/source metadata.
2. Place the CSV at
   `data/raw/paysim/PS_20174392719_1491204439457_log.csv`, set `PAYSIM_CSV` in the shell, or set
   `PIT_PAYSIM_CSV` in `.env`.
3. Run `make data-snapshot` or `.\make.ps1 data-snapshot`. This hashes the raw file, records its
   row count/schema/step range and writes the immutable snapshot manifest.
4. Run `make profile DATASET=paysim` or `.\make.ps1 profile -Dataset paysim`, then run the three
   notebooks to profile event ordering, origin/destination history, class
   imbalance, duplicates and leakage risk.
5. Record the dataset/entity/time policy and the model-family decision in ADRs only after EDA.

Dataset discovery, schema validation, DuckDB profiling and notebook queries are implemented.
Acquisition is intentionally manual/Kaggle-controlled, and the full snapshot has not been
verified until its SHA-256 and EDA evidence are recorded.

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
