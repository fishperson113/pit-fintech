# PaySim Silver training baseline

Status: **verified**.
Milestone: M019.

Verified run:

- parent MLflow run `e1ebc167813e40b88f16c6e611decea7`;
- clean code and lakehouse commit `6e93e7f43df4c00ce438ca66ccc31f3e0f4870b5`;
- Silver transaction/label version `1`;
- 322,461 vectors and all 8,213 PaySim fraud rows;
- vector checksum `c7f07593038c2d67b325254702073864f6eb3f193ee34031855ebc1fbd93b8b8`;
- future-read violations `0`.

Test results:

| Experiment | Test PR-AUC | Test ROC-AUC | Recall | Precision | Observed FPR |
|---|---:|---:|---:|---:|---:|
| E1 static/temporal | 0.258342 | 0.601620 | 0.275559 | 0.541601 | 0.007951 |
| E4 PIT/temporal | 0.102766 | 0.784978 | 0.036741 | 0.243386 | 0.003894 |

Test prevalence is 0.032966. E1 and E4 are therefore both above the random-ranking PR baseline,
but E4 underperforms E1 on PR-AUC and the fixed-FPR operating point despite its higher ROC-AUC.
This is accepted evidence of PaySim's temporal/entity limitations, not a correctness failure.

## What this pipeline proves

M019 closes the remaining Sprint 1 baseline gap without turning the notebook into a second
implementation:

```text
exact Silver Delta versions
  -> frozen strict-PIT vectors
  -> chronological E1 / E4
  -> natural-prevalence validation and test
  -> MLflow + validated manifest
```

E1 and E4 answer one narrow question under the same data periods and LightGBM configuration:

- **E1**: how well can request-time amount, step and transaction type rank fraud without
  recipient history?
- **E4**: what changes when the frozen 1h/24h/168h recipient-history vector is added with
  `prior_step < current_step`?

The difference `E4 − E1` is evidence about the value of the PIT history on this PaySim setup. It
is not a guarantee that E4 must win. A weak or negative difference remains useful evidence,
especially because ADR-002 already identifies sparse recipient history and cold-start behavior.

## Data and leakage boundary

The trainer does not read the raw CSV directly. It loads the latest or explicitly supplied
application-lakehouse manifest, then opens:

- the exact recorded version of `silver.paysim_transactions`;
- the exact recorded version of `silver.paysim_labels`.

Before feature computation it checks:

- FeatureSpec/entity versions and canonical checksum;
- Delta version, schema checksum and row count;
- transaction/label source identity and row alignment;
- dataset snapshot and source-file SHA lineage.

Model inputs are limited to the frozen FeatureSpec:

```text
current_amount
event_step
transaction_type_transfer
pit_prior_count_1h
pit_prior_amount_1h
recipient_has_history_1h
pit_prior_count_24h
pit_prior_amount_24h
recipient_has_history_24h
pit_prior_count_168h
pit_prior_amount_168h
recipient_has_history_168h
```

Labels, `isFlaggedFraud`, balance fields, current-inclusive values and future values are not
candidate model columns. Each historical window also carries an audit-only maximum source step;
publication stops unless all sources satisfy `max_source_step < prediction_step`.

## Split and sampling policy

The temporal boundary is fixed:

| Split | PaySim steps | Sampling |
|---|---:|---|
| Train | 1–520 | all fraud; at most 100,000 deterministic non-fraud rows per transaction type |
| Validation | 521–631 | every eligible row, natural prevalence |
| Test | 632–743 | every eligible row, natural prevalence |

Training negatives are bounded for single-machine CPU/RAM feasibility. Validation and test are
never downsampled, so PR-AUC, ROC-AUC and operating-point metrics describe the untouched
chronological evaluation populations.

## Model and metric policy

Both experiments use one deterministic CPU-only `LGBMClassifier` configuration. There is no
hyperparameter search. Early stopping observes validation binary log loss.

Threshold selection uses validation only:

1. compute the validation ROC curve;
2. select the threshold with maximum validation recall while validation FPR stays below the
   fixed budget, default `0.01`;
3. apply that frozen threshold once to test;
4. report test recall, precision and observed FPR.

Primary metric is test PR-AUC. ROC-AUC is secondary. Accuracy is intentionally absent.

## How to read notebook 05

Notebook [05_silver_training_baseline.ipynb](../../notebooks/05_silver_training_baseline.ipynb)
is organized as a reading sequence.

### Cell group 1 — Imports and mental model

The notebook resolves the repository and latest lakehouse manifest. Training logic is imported
from `src/pit_fintech/models/paysim_training.py`; there is no notebook-only SQL or model fit.

Read the mental-model cell before running:

- Silver transaction rows provide `X`;
- Silver labels provide only `y`;
- E1 and E4 differ by recipient history, not by split or model settings.

### Cell group 2 — Explicit execution control

`RUN_TRAINING` is read from `PIT_NOTEBOOK_RUN_TRAINING` and defaults to false. This guarantees
that normal review never launches a full model run. The notebook verifier additionally forces
the flag to false for child kernels and restores the caller's environment afterward.

Clean training must not be enabled by editing and saving the notebook: saving would dirty the
Git tree. Set the environment variable before starting JupyterLab instead.

### Cell group 3 — Lineage before metrics

Read these values first:

- `dataset_snapshot_id`;
- exact Silver versions and their schema/logical checksums;
- FeatureSpec version and checksum;
- training and lakehouse Git commits;
- training-vector checksum;
- `future_read_violations`.

The baseline is clean only when both commits are identical, neither ends in `-dirty`, and
future-read violations equal zero.

### Cell group 4 — Chronological population

Check split ranges, rows, fraud rows and fraud rate. Train must be marked `train-sampled`;
validation and test must be marked `natural`.

Do not compare the train fraud rate directly with the test fraud rate. Sampling deliberately
changes the train class mix.

### Cell group 5 — E1/E4 metrics

Read the metrics together:

- PR-AUC answers ranking quality under rare fraud;
- ROC-AUC is supporting ranking evidence;
- recall says how much fraud is caught;
- precision says how concentrated the alerts are;
- observed FPR confirms the test-period cost of the validation-selected threshold.

The notebook computes `E4 − E1` for PR-AUC and recall. This is the direct history-feature
comparison.

### Cell group 6 — Feature importance

Gain importance shows which fields the fitted E4 model used most. It does not prove causality,
generalization or temporal correctness. Correctness comes from FeatureSpec and cutoff gates.

### Cell group 7 — Claim boundary

The final cell repeats limitations stored in the manifest. This baseline closes Sprint 1
feasibility only. Model promotion, Redis materialization, offline/online parity and serving
remain Sprint 2 gates.

## User execution sequence

Before the clean full-data run, execute the implementation gates:

```powershell
.\make.ps1 test-unit
.\make.ps1 test-lakehouse
.\make.ps1 test-notebooks
```

After M019 is committed, rebuild PaySim lakehouse once so its new Delta versions carry the same
clean commit as the trainer:

```powershell
.\make.ps1 build-lakehouse -Dataset paysim
```

Then choose one training surface.

CLI:

```powershell
.\make.ps1 train
```

Notebook:

```powershell
$env:PIT_NOTEBOOK_RUN_TRAINING = "1"
.\make.ps1 lab-training
```

Open notebook 05 and run all cells. Remove the session variable afterwards if desired:

```powershell
Remove-Item Env:PIT_NOTEBOOK_RUN_TRAINING
```

The CLI and notebook call the same function and produce the same manifest schema under:

```text
artifacts/experiments/paysim-silver-training/<mlflow-parent-run-id>/manifest.json
```

After reviewing a full run, clear notebook outputs before committing. Runtime manifests and
MLflow artifacts—not saved notebook output—are the source of truth.

## Acceptance result

M019 was marked verified after user-provided evidence confirmed:

- fixture/unit/notebook gates pass;
- a clean lakehouse rebuild succeeds;
- E1 and E4 both complete;
- future-read violations are zero;
- validation/test remain natural prevalence;
- exact Silver versions/checksums, clean code commit, vector checksum, MLflow run IDs and model
  URIs exist in the persisted manifest.
