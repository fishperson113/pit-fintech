# Data access and immutable raw policy

## Credential-free acceptance path

`make data-sample` or `.\make.ps1 data-sample` validates the committed temporal source against
hand-calculated vectors, writes `data/fixtures/temporal_cases.parquet`, and records a runtime
manifest under `artifacts/sample/`. This path is sufficient for correctness and CI.

## IEEE-CIS primary path (planned)

1. Accept the IEEE-CIS Fraud Detection competition rules in Kaggle.
2. Configure Kaggle credentials outside this repository.
3. Use the future `data` command to download into `data/raw/`.
4. Verify filename, byte count, and SHA-256 before extraction or processing.
5. Never overwrite a matching immutable raw archive.

No credential value is printed by `doctor`; it reports presence only. Raw competition data is
gitignored and must not be republished.

## Day-2 go/no-go

IEEE-CIS remains the primary candidate until entity sensitivity compares at least C1
(`card1|card2|card3|card5`) and C2 (C1 plus `addr1`). If access or repeated-history viability
fails by Day 2, record the reason in a new ADR and switch the application path to PaySim. The
synthetic oracle continues unchanged in either case.
