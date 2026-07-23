# M009 — PaySim EDA notebooks and profile boundary

- Date: 2026-07-23
- Status: implemented

## Scope and acceptance

Replace the three Sprint 1 mock/synthetic notebooks with decision-oriented PaySim EDA while
preserving the synthetic temporal fixture as the independent correctness oracle. The notebooks
must consume the authorized PaySim CSV, fail visibly when it is absent, avoid loading the full
dataset into pandas memory, and provide evidence for snapshot, entity/time, split and leakage
decisions.

The full application-data gate is not complete until the Kaggle snapshot is present, its SHA-256
is frozen, all queries are executed on that snapshot, and the resulting dataset/entity ADR is
reviewed.

## Technical and research decisions

- Use DuckDB directly over the CSV for local CPU profiling and Arrow result display.
- Resolve the dataset from an explicit CLI path, `PAYSIM_CSV`, `.env` `PIT_PAYSIM_CSV`, or the
  default `data/raw/paysim/PS_20174392719_1491204439457_log.csv` path.
- Validate the exact PaySim 11-column header before any query and never substitute the synthetic
  fixture.
- Treat `step` as an hourly ordinal rather than claiming a real wall-clock timestamp.
- Use original CSV row order as a provisional same-step tie-break candidate and require Bronze
  ingestion to persist the assigned `source_row_number` once.
- Evaluate `nameOrig` as primary behavioral entity and `nameDest` as recipient context; do not
  lock the ADR until full-data history-depth results are reviewed.
- Exclude `oldbalanceOrg`, `newbalanceOrig`, `oldbalanceDest` and `newbalanceDest` from the
  deployable baseline because the dataset source documents fraud cancellation/post-outcome risk.
- Keep `isFraud` label-only and exclude `isFlaggedFraud` from the baseline as an existing policy
  output.
- Demonstrate future leakage with strict prior-history versus deliberately leaky full-history
  aggregates on repeated origins. This is a positive control, not the production window logic.
- Resolve the repository root by walking from the kernel working directory to `pyproject.toml`;
  never assume `Path.cwd()` is the project root when Jupyter opens a notebook.

## Files changed

- `notebooks/01_data_profile.ipynb`
- `notebooks/02_entity_temporal_analysis.ipynb`
- `notebooks/03_leakage_prototype.ipynb`
- `src/pit_fintech/data/paysim.py`
- `src/pit_fintech/cli.py`
- `src/pit_fintech/config.py`
- `src/pit_fintech/platform/notebooks.py`
- `tests/unit/test_paysim.py`
- `tests/fixtures/paysim_schema_sample.csv`
- `.env.example`
- `make.ps1`
- `README.md`
- `docs/data-access.md`
- project status, cumulative changelog and this log

## Commands and verification evidence

```text
uv run --frozen pytest -q tests/unit/test_paysim.py tests/unit/test_feature_contract.py
5 passed

uv run --frozen --group dev pit notebooks verify
3 notebooks passed with no PaySim CSV; every query was explicitly skipped and setup instructions
were shown. No synthetic fallback was used.

PAYSIM_CSV=tests/fixtures/paysim_schema_sample.csv PAYSIM_CHECKSUM=0 \
  uv run --frozen --group dev pit notebooks verify
3 notebooks passed; all DuckDB query cells executed.

uv run --frozen pit data profile --dataset paysim \
  --path tests/fixtures/paysim_schema_sample.csv --checksum
12 rows; steps 1–6; 3 origin entities; 10 destination entities; 3 fraud rows;
snapshot paysim1:b40a4eb1c8971b54.

uv run --frozen pytest -q
26 passed.

uv run --frozen ruff check src tests feature_repo notebooks scripts
All checks passed.

uv run --frozen ruff format --check src tests feature_repo notebooks scripts
33 files already formatted.

git diff --check
Pass; existing LF-to-CRLF working-copy warnings only.
```

Notebook execution on Windows emitted the known local ZMQ selector-thread/TCP warnings; kernels
completed successfully and no notebook output was written into the tracked files.

2026-07-23 notebook working-directory regression fix:

```text
uv run --frozen pytest -q tests/unit/test_paysim.py
5 passed, including project-root resolution from a nested notebooks directory.

PAYSIM_CSV=tests/fixtures/paysim_schema_sample.csv PAYSIM_CHECKSUM=0 \
  uv run --frozen --group dev pit notebooks verify
3 notebooks passed; full user PaySim data was not read.

uv run --frozen ruff check src/pit_fintech/data/paysim.py \
  tests/unit/test_paysim.py notebooks
All checks passed.
```

## Source evidence

- Kaggle dataset: `https://www.kaggle.com/datasets/ealaxi/paysim1`
- The dataset page describes `step` as one hour, documents the five transaction types, and warns
  against using the four balance columns for fraud detection because detected fraudulent
  transactions are cancelled.
- Current DuckDB documentation confirms direct Python CSV relations, Arrow result retrieval, and
  CSV order preservation when `preserve_insertion_order` is enabled.

## Deviations, gaps and next step

- The authorized full PaySim CSV is not present in the workspace and was not downloaded. No
  full-data row count, checksum, distribution or entity-viability result is claimed.
- `source_row_number` is only a candidate tie-break until Bronze ingestion persists it and the ADR
  is accepted.
- The schema fixture exists only to execute notebook SQL in tests; notebooks never select it
  automatically.
- Fixed: interactive kernels starting in `notebooks/` no longer derive the invalid
  `notebooks/data/raw/` path.
- Next step: place the Kaggle CSV at the configured path, run `data-snapshot` and all three
  notebooks, save machine-readable EDA outputs, then write the PaySim dataset/entity ADR.
