# M019 — Silver-based LightGBM training baseline

- Date: 2026-07-27
- Updated: 2026-07-27 14:53:55 +07:00
- Status: verified

## Scope and acceptance

Implement the final Sprint 1 model baseline from exact PaySim Silver Delta versions:

```text
silver.paysim_transactions + silver.paysim_labels
  -> strict PIT training vectors
  -> chronological train / validation / test
  -> E1 static baseline + E4 PIT baseline
  -> MLflow runs + immutable training manifest
```

Acceptance for implementation:

- open the exact transaction and label Delta versions recorded by one application-lakehouse
  manifest;
- reject dataset, snapshot, row-count, source-checksum, entity-version, feature-version or
  feature-checksum mismatches before training;
- compute the frozen 12-field `paysim-fraud-recipient-v1` vector without label, balance,
  policy-output, same-step or future inputs;
- use chronological steps 1–520 / 521–631 / 632–743;
- preserve natural fraud prevalence in validation and test;
- permit deterministic non-fraud downsampling only in the training partition and record that
  policy explicitly;
- train one fixed CPU-only LightGBM configuration for both E1 and E4;
- choose the fixed-FPR threshold on validation only and report test PR-AUC, ROC-AUC, recall,
  precision and observed FPR;
- log exact Delta/schema/logical checksums, FeatureSpec checksum, training-vector checksum,
  dependency lock, code commit, MLflow run IDs and model artifacts;
- expose the reusable pipeline through CLI, Make and PowerShell;
- add a thin notebook that calls reusable `src/` functions and teaches how to inspect lineage,
  split health, E1/E4 metrics and feature importance.

All runtime commands remain delegated to the user.

## Decisions

- Keep M016 as an exploratory positive-control spike; M019 only runs deployable temporal
  semantics E1 and E4.
- Read Delta through `DeltaTable(path, version=...)` and its PyArrow dataset so time travel is
  explicit without requiring a DuckDB Delta extension.
- Compute recipient history over the complete Silver event history for destinations appearing
  in the selected scoring population, then join labels by deterministic source identity.
- Keep validation and test at natural prevalence so their metrics are interpretable for this
  PaySim snapshot.
- Keep notebook code observational. It must not own an alternative training implementation.

## Files added or changed

- `src/pit_fintech/models/paysim_training.py`
- `src/pit_fintech/models/__init__.py`
- `src/pit_fintech/contracts/manifests.py`
- `src/pit_fintech/cli.py`
- `src/pit_fintech/platform/notebooks.py`
- `tests/unit/test_paysim_training.py`
- `tests/integration/test_paysim_lakehouse.py`
- `notebooks/05_silver_training_baseline.ipynb`
- `notebooks/04_model_candidate.ipynb`
- `Makefile`
- `make.ps1`
- `README.md`
- `docs/reports/paysim-silver-training-baseline.md`
- `docs/reports/sprint-1-gate.md`
- `docs/research-protocol.md`
- `AGENTS.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Implemented behavior

The M019 pipeline now:

1. loads and validates one `ApplicationLakehouseManifest`;
2. opens exact historical Delta versions with `DeltaTable(path, version=...)`;
3. checks Silver schema checksum, row count, snapshot/source lineage, uniqueness and
   transaction/label identity;
4. selects the FeatureSpec scoring scope and applies deterministic negative sampling only to
   train;
5. computes 1h/24h/168h recipient windows over complete relevant Silver history with strict
   `RANGE ... 1 PRECEDING`;
6. fails if any audit maximum source step reaches or exceeds the prediction step;
7. trains E1 and E4 with the same fixed LightGBM configuration and pandas frames so feature
   names remain valid through fit and prediction;
8. selects the fixed-FPR threshold on validation and applies it once to natural-prevalence test;
9. logs metrics, feature sets, gain importance, exact Silver lineage and pickle-free `skops`
   model artifacts to MLflow;
10. publishes a validated training manifest with Delta/FeatureSpec/vector/code/lock/dependency
    lineage;
11. rejects dirty or mismatched trainer/lakehouse commits by default;
12. exposes the same function through `pit model train`, `train` Make/PowerShell targets and
    review-first notebook 05.

Notebook 05 reads `PIT_NOTEBOOK_RUN_TRAINING` instead of requiring a saved code-cell edit. This
keeps clean Git lineage possible during an intentional notebook run. Notebook 04's execution
flag was restored to false so the notebook verifier does not repeat the exploratory four-model
spike. The verifier also forces the environment flag to false for its child kernels and restores
the caller's value afterward.

The fixture additions cover exact Delta-version retrieval, seven eligible scoring vectors,
chronological partitioning, one known recipient-history vector, cold-start defaults and zero
future reads. Unit contracts cover the locked E1/E4 matrix, forbidden inputs, CLI missing-source
behavior, training-manifest round trip, summaries and E4 importance ordering.
The unit lane also checks that notebook verification cannot accidentally train and does not
mutate the caller's lasting environment.

## Verification state

No model, pytest, notebook, formatter, linter or pipeline command was executed by the agent.

User-run implementation gates:

```text
.\make.ps1 test-unit
  34 passed in 5.72s
  exit 0

.\make.ps1 test-lakehouse
  4 passed in 3.59s
  exit 0

.\make.ps1 test-notebooks
  PASS 01_data_profile.ipynb
  PASS 02_entity_temporal_analysis.ipynb
  PASS 03_leakage_prototype.ipynb
  PASS 04_model_candidate.ipynb
  PASS 05_silver_training_baseline.ipynb
  verified 5 notebooks
  exit 0
```

The integration lane includes exact Silver Delta version retrieval, transaction/label identity,
strict-PIT fixture vectors and zero future reads. The notebook lane confirms notebook 05 remains
review-only under the verifier. Windows Proactor/ZMQ and unencrypted local-kernel messages were
non-blocking warnings; all five notebooks completed.

The user also included the previously verified full v0 application lakehouse output:
6,362,620 rows in each of three tables, 8/8 gates and the known logical checksums. It remains
M018 feasibility evidence because it is version 0 with the previously recorded dirty lineage;
it is not counted as the required post-M019 clean rebuild.

The first commit attempt ran the mandatory pre-commit suite. Ruff check, large-file,
merge-conflict, TOML/YAML, EOF, whitespace and milestone-changelog guards passed. Ruff format
reformatted the new notebook, training module and two test files, so the hook correctly stopped
the commit for review and restaging. No test or training command was rerun by the agent.

The implementation was then committed cleanly as
`6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5`. All pre-commit guards passed on the retry.

User-run clean full-data sequence:

```text
application lakehouse
  bronze.paysim_transactions v1
  silver.paysim_transactions v1
  silver.paysim_labels v1
  code commit: 6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5

notebook 05 / paysim-silver-lightgbm-v1
  parent run: e1ebc167813e40b88f16c6e611decea7
  status: completed
  code commit: 6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5
  lakehouse code commit: 6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5
  vector rows: 322,461
  vector fraud rows: 8,213
  vector checksum: c7f07593038c2d67b325254702073864f6eb3f193ee34031855ebc1fbd93b8b8
  future-read violations: 0
```

Partition reconciliation:

```text
train       steps 1-520    205,781 rows / 5,781 fraud / sampled negatives
validation  steps 521-631   78,701 rows / 1,180 fraud / natural prevalence
test        steps 632-743   37,979 rows / 1,252 fraud / natural prevalence
sum                         322,461 rows / 8,213 fraud
```

Model results:

```text
E1 static/temporal
  test PR-AUC: 0.258342464675527
  test ROC-AUC: 0.601620215942672
  recall@fixed-FPR: 0.27555910543131
  precision@fixed-FPR: 0.54160125588697
  observed test FPR: 0.00795055408827293
  best iteration: 1
  child run: e9fe5b1f0f90436e88c0e845d4f28a64

E4 PIT/temporal
  test PR-AUC: 0.102766342198827
  test ROC-AUC: 0.784978314654078
  recall@fixed-FPR: 0.036741214057508
  precision@fixed-FPR: 0.243386243386243
  observed test FPR: 0.00389359326925695
  best iteration: 1
  child run: 4ab5f1f4421a459884cec7d9a34c7d40
```

The manifest, MLflow lineage files, two feature-set artifacts and two pickle-free `model.skops`
artifacts exist. Their generated MLmodel files carry the expected E1 three-field and E4
twelve-field signatures plus pinned package requirements.

Notebook cells executed sequentially from 1 through 8 with no error output. The run used
`train-and-review`, loaded the latest application manifest, displayed matching lineage, the
three chronological partitions, E1/E4 metrics, E4 gain importance and all four claim-boundary
statements.

Two non-blocking MLflow warnings were observed:

- integer history fields make MLflow warn about hypothetical missing values; FeatureSpec v1
  requires these fields and defaults them to zero, so Sprint 2's FeatureProvider must preserve
  the non-null dtype contract;
- MLflow could not resolve an installed `pip` version inside the uv environment, although the
  emitted requirements file contains the exact MLflow, LightGBM, scikit-learn, pandas, NumPy and
  skops versions.

No LightGBM feature-name warning, exception, failed cell, lineage mismatch or cutoff violation
occurred.

Static inspection performed by the agent used current official delta-rs documentation to confirm
`DeltaTable(path, version=...)` plus `to_pyarrow_dataset()` time travel, current LightGBM
DataFrame feature-name behavior, and current MLflow `skops`/`pip_requirements` model logging.
This is API-design evidence, not runtime verification.

## Known gaps and next step

- Fixture, unit and notebook gates now pass.
- Clean full-data E1/E4 training now passes and M019 is verified.
- E4 improves global ROC ranking but underperforms E1 on PR-AUC and the fixed-FPR operating
  point. This is retained as valid PaySim/feature-utility evidence and must not be hidden through
  tuning.
- Both models stopped at iteration 1. Sprint 2 may diagnose temporal calibration/drift, but may
  not change the frozen baseline retroactively.
- The MLflow sklearn pyfunc signatures currently expose label `predict` output. Sprint 2 serving
  needs an explicit probability-scoring wrapper plus the manifest threshold before promotion.
- The executed notebook's outputs were reviewed, then mechanically cleared during M020. The
  source notebook again matches its committed output-free object; the JSON training manifest and
  MLflow artifacts are authoritative.
