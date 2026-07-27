# M009 — PaySim EDA notebooks and profile boundary

- Date: 2026-07-23
- Updated: 2026-07-27 09:48:01 +07:00
- Status: verified

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
- Refined on 2026-07-27: separate column cardinality is insufficient because the same `C...`
  customer may receive as `nameDest` before sending or cashing out as `nameOrig`. Entity viability
  must therefore include a unified, direction-aware customer account history. `M...` merchant
  identifiers remain a separate entity type.
- Treat the PaySim lost-account `TRANSFER -> CASH_OUT` sequence as a diagnostic hypothesis to test
  against the exported CSV, not an assumed link. Labels may measure retrospective coverage but
  never enter deployable features.
- Use current-destination history as the final PaySim viability gate. Report conservative
  1-hour/24-hour/7-day coverage by destination kind, transaction type, label and temporal split;
  report same-hour CSV-order coverage separately as tie-break sensitivity.
- Freeze the GREEN/AMBER/RED decision rule before execution. Evaluate customer
  `CASH_OUT`/`TRANSFER` slices using absolute warm fraud/non-fraud counts, coverage and
  validation/test stability; RED triggers an IEEE-CIS viability spike rather than a blind switch.
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

2026-07-27 refinement files:

- `notebooks/02_entity_temporal_analysis.ipynb`
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

2026-07-27 full-data evidence supplied by the user before the cross-role refinement:

```text
.\make.ps1 data-snapshot
dataset_snapshot_id: paysim1:16910f90577b0d98
sha256: 16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b
bytes: 493534783
rows: 6362620
step range: 1-743

.\make.ps1 profile -Dataset paysim
rows: 6362620
origin_entities: 6353307
destination_entities: 2722362
fraud_rows: 8213
fraud_rate: 0.001290820448180152

.\make.ps1 test-notebooks
PASS 01_data_profile.ipynb
PASS 02_entity_temporal_analysis.ipynb
PASS 03_leakage_prototype.ipynb
verified 3 notebooks
LASTEXITCODE: 0
```

These results verify the notebook version that existed before the new cross-role cells. The new
account-role overlap, row-level history coverage and mule-sequence diagnostic remain
**implemented, not verified**, until the user executes the updated notebook.

2026-07-27 static verification of the refined notebook:

```text
Notebook JSON parse: pass; nbformat 4
Cells: 18 total, 10 code
New EDA code cells: 3/3 present
Duplicate cell IDs: 0
New-cell execution counts: null
New-cell saved outputs: 0
Trailing whitespace across changed files: 0
git diff --check: pass; expected LF-to-CRLF working-copy warnings only
```

No notebook, SQL query, test suite or Make target was executed by the agent. Runtime verification
is intentionally delegated to the user.

2026-07-27 user-run output verification of the refined notebook:

```text
All 10 code cells completed; no error outputs.

Cross-role accounts:
customer_accounts=6,923,499
origin_only_accounts=6,351,538
destination_only_accounts=570,192
accounts_seen_in_both_roles=1,769 (0.0256%)

Current-origin prior-any-role coverage:
fraud CASH_OUT: 11/4,116 (0.2672%)
fraud TRANSFER: 7/4,097 (0.1709%)
non-fraud groups: 0.1545%–0.1625%

Linkable mule-sequence diagnostic:
fraud_cashouts=4,116
with_prior_incoming_transfer=0
prior_incoming_percent=0%
```

Interpretation:

- Combining origin and destination roles does not recover meaningful behavioral history for the
  current origin in this PaySim export.
- A fraudulent cash-out cannot be linked to a strictly earlier incoming transfer by account ID in
  the exported CSV. This is a dataset-observability result, not evidence that the published PaySim
  fraud scenario never used mule accounts.
- Recipient/destination history remained the final candidate after this stage; its row-level
  window coverage is evaluated by the destination gate documented below.
- Cross-role notebook execution is verified; the dataset/entity ADR remained pending until the
  destination gate could be executed.

2026-07-27 implementation of the final destination-history gate:

```text
Notebook JSON parse: pass; nbformat 4
Cells: 24 total, 13 code
New destination gate code cells: 3/3 present
Duplicate cell IDs: 0
New-cell execution counts: null
New-cell saved outputs: 0
```

The gate materializes one compact split summary after measuring the last earlier destination
step, then reports 1-hour/24-hour/7-day window coverage by type/label and split. A separate
same-hour count exposes dependence on the provisional CSV-row tie-break. The final cell applies
the predeclared GREEN/AMBER/RED rule, rejects missing train/validation/test label groups, and
requires training coverage as well as evaluation coverage. Static review found no remaining
logic blocker after cold groups were made explicitly zero rather than nullable. No notebook, SQL
query, test suite or Make target was executed by the agent. Runtime verification remains
intentionally delegated to the user.

2026-07-27 user-run destination gate evidence:

```text
Notebook 02 code cells: 13/13 executed
Execution counts: 1 through 13
Error outputs: 0

Fraud CASH_OUT, 7-day warm history:
train:      2,058 / 2,900 = 70.9655%
validation:   186 /   590 = 31.5254%
test:         101 /   626 = 16.1342%
slice gate: AMBER

Fraud TRANSFER, 7-day warm history:
train:      4 / 2,881 = 0.1388%
validation: 0 /   590 = 0%
test:       0 /   626 = 0%
slice gate: RED

Dataset gate: AMBER_CORRECTNESS_ONLY
```

Additional evidence:

- Only 21 of 4,116 fraud `CASH_OUT` rows are warm solely because of same-hour CSV ordering, so
  the conservative strict-step conclusion does not depend materially on the provisional
  tie-break.
- Overall fraud `CASH_OUT` destination coverage is 3.2556% at 1 hour, 24.9514% at 24 hours and
  2,345/4,116 at 7 days.
- Fraud `TRANSFER` has only four strict-step warm destination rows over the full snapshot.
- Warm non-fraud `CASH_OUT` rows are 1,799,628/24,575/6,227 across train/validation/test; the
  AMBER result is caused by the frozen fraud-count minima, not missing negative support.

The frozen rule classifies `CASH_OUT` as AMBER because validation and test miss the GREEN minima
of 200 warm fraud rows; it does not hit RED because counts remain above 50 and coverage remains
above 2%. `TRANSFER` is RED. No GREEN plus at least one AMBER yields
`AMBER_CORRECTNESS_ONLY`.

The saved PyArrow `text/plain` representation truncates the final `slice_gate` and `dataset_gate`
columns with an ellipsis. The visible numeric inputs uniquely determine the classifications under
the saved SQL, but a compact non-truncated JSON/table should be added when the gate is promoted
to machine-readable release evidence.

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

- Resolved: the authorized full PaySim CSV is present and its checksum/profile are frozen.
- Resolved: cross-role account-history and mule-sequence outputs were executed and reviewed.
- Resolved: all three current-destination gate cells executed without error; the predeclared
  result is `AMBER_CORRECTNESS_ONLY`.
- Resolved: ADR-002 accepts PaySim as the PIT/MLOps engineering workload with
  `AMBER_CORRECTNESS_ONLY`; an IEEE-CIS viability spike remains optional if a stronger thesis
  claim about model utility is required.
- `source_row_number` is only a candidate tie-break until Bronze ingestion persists it and the ADR
  is accepted.
- The schema fixture exists only to execute notebook SQL in tests; notebooks never select it
  automatically.
- Fixed: interactive kernels starting in `notebooks/` no longer derive the invalid
  `notebooks/data/raw/` path.
- Next step: adapt the feature contract to PaySim semantics, then implement the full-data
  Bronze/Silver feasibility path and static/PIT baselines.
