# M016 — Standalone PaySim LightGBM candidate spike

- Date: 2026-07-27
- Updated: 2026-07-27 13:03:36 +07:00
- Status: verified

## Scope and acceptance

Implement the smallest standalone training component that can be built before Sprint 2 without
claiming the final model, feature contract or platform lifecycle.

Acceptance for implementation:

- reusable training logic lives in `src/`, not only in a notebook;
- one command executes E1–E4 with fixed seed/split/threshold semantics;
- MLflow works through local SQLite tracking plus a local artifact directory without Docker or
  an external service;
- every child run logs model, parameters, metrics and feature names;
- one validated manifest records dataset/code/lock/dependency/model lineage;
- notebook 04 calls the same reusable workflow and can review CLI-created evidence;
- sampled-cohort metrics are explicitly blocked from production-quality claims;
- tests describe matrix, lineage, PIT table and manifest contracts;
- Feast, Gold, Redis, promotion and serving remain outside this milestone.

Runtime acceptance remains delegated to the user.

## Technical decisions

- Keep LightGBM as a candidate, not a locked model family.
- Run the existing E1–E4 research matrix:
  - E1 static request-time features with temporal split;
  - E2 deliberately leaky controls with random split;
  - E3 strict-PIT recipient history with random split;
  - E4 strict-PIT recipient history with temporal split.
- Reuse `materialize_recipient_leakage_vectors`; do not fork a second PIT implementation.
- Select every eligible fraud row and at most 5,000 deterministic non-fraud rows per split/type.
- Use steps 1–520 / 521–631 / 632–743 and seed `20260727`.
- Select the score threshold on validation at FPR `0.01`; report test PR-AUC, ROC-AUC,
  recall/precision and observed FPR.
- Use a fixed, single-threaded LightGBM configuration for deterministic CPU behavior; no tuning.
- Default MLflow tracking to `artifacts/mlflow/tracking.db` through SQLite and model artifacts to
  `artifacts/mlflow/artifacts/`. A server URI remains an explicit CLI override.
- Store the run manifest under
  `artifacts/experiments/paysim-lightgbm-spike/<parent-run-id>/manifest.json`.
- Leave `RUN_TRAINING = False` in notebook 04 so the normal notebook verification lane remains
  cheap; manual model execution is an explicit user action.

## Files added or changed

- `src/pit_fintech/models/__init__.py`
- `src/pit_fintech/models/paysim_lightgbm.py`
- `src/pit_fintech/contracts/manifests.py`
- `src/pit_fintech/cli.py`
- `tests/unit/test_paysim_lightgbm_spike.py`
- `notebooks/04_model_candidate.ipynb`
- `Makefile`
- `make.ps1`
- `README.md`
- `docs/research-protocol.md`
- `docs/reports/model-candidate-spike.md`
- `AGENTS.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Implemented behavior

The CLI/Make path:

```text
PaySim CSV
  -> exact raw snapshot hash
  -> deterministic destination cohort
  -> static/PIT/leaky candidate matrices
  -> E1/E2/E3/E4 LightGBM child runs
  -> local MLflow models + metrics
  -> validated candidate-spike manifest
```

The manifest captures:

- PaySim snapshot ID and full SHA-256;
- candidate-table and per-experiment training-dataset checksums;
- entity and candidate-feature versions;
- code commit and `uv.lock` checksum;
- dependency versions;
- seed, FPR, cohort policy and row counts;
- feature names, split rows and class rates per experiment;
- model metrics, chosen threshold, training time and process RSS;
- child run IDs/model URIs and non-promotable claim boundaries.

## Static verification

```text
Notebook 04 JSON parse: pass
Notebook 04 cells: 9 total, 5 code
Duplicate notebook cell IDs: 0
Saved notebook error outputs: 0
Python source line-length scan: pass after one CLI wrap
git diff --check: pass with working-copy line-ending warnings only
```

MLflow API usage follows the current documented manual tracking pattern:

- explicit tracking URI and experiment;
- parent/child `start_run`;
- `log_params`, `log_metrics`, `log_dict`;
- `mlflow.sklearn.log_model` with an input example.

No model, notebook, pytest target, Make target, CLI command, formatter, linter or pipeline was
executed by the agent.

## First user runtime attempt and wiring fix

The user's first command reached the new command boundary but stopped before dataset discovery
or training:

```text
.\make.ps1 model-spike
NameError: name 'resolve_project_root' is not defined
PowerShell exit code: 1
```

Root cause: `model_spike` called the existing `pit_fintech.data.paysim.resolve_project_root`
helper, but `src/pit_fintech/cli.py` did not import that symbol. The CLI import was added and a
regression smoke test now invokes `pit model spike` with dataset discovery stubbed as missing.
The test requires the command to reach discovery, emit the expected setup guidance and exit `2`
without beginning model training.

The failed attempt produced no E1–E4 or MLflow evidence and does not change M016 from
`implemented` to `verified`. The fix has only been checked statically by the agent; runtime
verification remains delegated to the user.

## Second user runtime attempt and MLflow backend fix

The second user run passed project-root and dataset discovery, loaded the training dependency
group and inspected the PaySim snapshot. It then stopped at `mlflow.set_experiment` before cohort
construction or training:

```text
MlflowException: The filesystem tracking backend ... is in maintenance mode
PowerShell exit code: 1
```

MLflow's current runtime rejects the legacy filesystem tracking backend unless
`MLFLOW_ALLOW_FILE_STORE=true`. The project does not opt out of that safety check. The standalone
default now follows the documented local-development path:

```text
tracking metadata -> artifacts/mlflow/tracking.db (SQLite)
model artifacts   -> artifacts/mlflow/artifacts/ (file artifact repository)
```

The code creates or reuses the named experiment with the explicit artifact location and retains
the existing `--tracking-uri` override for an external MLflow server. Unit contracts now require
the SQLite URI and explicit artifact-root wiring. This attempt created no completed MLflow run or
E1–E4 manifest, so M016 remains `implemented` pending another user run.

## Third user runtime attempt and fixed-FPR fallback

The third user run successfully initialized the SQLite schema, built the deterministic PaySim
candidate cohort and started LightGBM training. It stopped during threshold selection for the
first experiment:

```text
RuntimeError: No finite validation threshold satisfies the fixed FPR
PowerShell exit code: 1
```

At fixed FPR `0.01`, the validation ROC curve can legitimately have only its initial
infinite-threshold point inside the budget. That point means “predict no positives”, with FPR `0`
and recall `0`; it is a valid constrained operating point, but the original implementation
rejected it because the manifest requires a finite threshold.

The selector now converts that case to the next finite floating-point value above the maximum
validation score. This preserves the exact zero-positive behavior and records
`validation_threshold_policy=zero-positive-fallback` in MLflow and the manifest. Normal
experiments remain `max-tpr-within-fpr`. A unit case fixes the expected FPR/recall/precision at
zero for this edge case.

The same patch adopts the installed LightGBM validation API (`eval_X`/`eval_y`) instead of its
deprecated `eval_set` compatibility argument. Scikit-learn feature-name messages remain
non-blocking warnings. The failed parent run is useful failure history in SQLite but is not a
completed candidate manifest; M016 remains `implemented`.

## Fourth user runtime attempt and safe model serialization

The fourth user run passed SQLite initialization, cohort construction, LightGBM training and the
fixed-FPR threshold edge case. It stopped while logging the first trained model:

```text
MlflowException: The saved sklearn model references untrusted types
Untrusted: collections.OrderedDict, lightgbm.basic.Booster,
           lightgbm.sklearn.LGBMClassifier
PowerShell exit code: 1
```

This is an expected `skops` safety boundary for third-party estimator types, but an unsuccessful
pipeline result. Following MLflow's documented pickle-free LightGBM pattern, `log_model` now
keeps `serialization_format=skops` and explicitly trusts only the three fully qualified types
reported by the runtime. The implementation does not switch to unrestricted pickle, wildcard
trust or a global safety bypass. A unit contract freezes the minimal allowlist.

The scikit-learn feature-name messages are warnings and did not cause the failure. No completed
E1–E4 manifest exists yet, so M016 remains `implemented` pending another user run.

## Successful user runtime and verified evidence

The next user-run command completed with exit code `0`:

```text
.\make.ps1 model-spike
MLflow parent run: 0407debd24294c01a1d040f6aa33cc95
manifest: artifacts/experiments/paysim-lightgbm-spike/
          0407debd24294c01a1d040f6aa33cc95/manifest.json
```

Verified manifest identity:

```text
status: completed
dataset_snapshot_id: paysim1:16910f90577b0d98
cohort: 38,213 rows / 8,213 fraud
experiments: E1, E2, E3, E4
tracking: sqlite:///C:/workspace/pit-fintech/artifacts/mlflow/tracking.db
manifest SHA-256: a7085ba4e62bcbfc793f3713c9ee07a8f307519f1f18798251c8aa47176da96a
```

Verified candidate results:

| ID | Features / split | PR-AUC | ROC-AUC | Recall@FPR | Test FPR | Threshold policy |
|---|---|---:|---:|---:|---:|---|
| E1 | static / temporal | 0.176951 | 0.627406 | 0.000000 | 0.000000 | zero-positive-fallback |
| E2 | leaky / random | 0.915528 | 0.967541 | 0.677223 | 0.013831 | max-tpr-within-fpr |
| E3 | PIT / random | 0.892585 | 0.953843 | 0.622412 | 0.012165 | max-tpr-within-fpr |
| E4 | PIT / temporal | 0.324524 | 0.714972 | 0.202875 | 0.001500 | max-tpr-within-fpr |

All four child run IDs exist in the manifest. Artifact inspection found four MLflow logged-model
directories, each containing `model.skops`, `MLmodel`, input/serving examples and environment
files. Dataset, candidate-table, training-dataset and dependency-lock checksums are present; the
parent run ID matches the manifest run ID.

Interpretation boundaries:

- E2 is the deliberately leaky positive control and is never deployable.
- E3 is optimistic because it uses a random split.
- E4 is the main candidate result and improves over E1 under the temporal split, but it is not a
  final production-quality estimate because the cohort oversamples fraud.
- E1's zero-positive fallback is a valid constrained operating point, not a pipeline error.
- The manifest records code commit `115e98d...-dirty`; this is acceptable for the exploratory
  candidate spike, but the final locked baseline must be rerun from a clean commit.
- Scikit-learn feature-name and unpinned-pip conda messages were non-blocking warnings; the
  manifest carries the exact `uv.lock` checksum and MLflow exported 23 project requirements.

M016's standalone model-spike runtime and evidence contract are verified. The broader Sprint 1
gate remains open for the PaySim FeatureSpec v1, application Bronze/Silver path and final clean
baseline.

## Post-verification notebook rewrite

The user manually saved notebook 04 with `RUN_TRAINING = True` and executed it successfully,
producing another manifest. Its output contained repeated scikit-learn feature-name warnings and
MLflow's unpinned-pip conda warning. These messages were non-blocking—the manifest was written—but
the saved state would make every future `Run All` and notebook-verification attempt retrain E1–E4.

Notebook 04 was rewritten as a review-first experiment surface:

- `RUN_TRAINING = False` is restored as the checked-in default;
- all saved execution counts, model logs and warning outputs are removed;
- the optional training cell remains explicit and calls the same reusable function as the CLI;
- the latest Pydantic-validated manifest is loaded regardless of whether Make, PowerShell or the
  notebook created it;
- E1–E4 roles and the three diagnostic PR-AUC differences are explained separately;
- E4 recall/test-FPR, threshold policy, lineage, checksums, best iteration, training time, RSS and
  model URIs are exposed;
- the final cell repeats claim boundaries and the next clean Silver-based baseline decision.

The subsequent user-run `.\make.ps1 test-notebooks` passed notebooks 01–04 with exit code `0`.
Notebook 04's rewritten review path is therefore verified. The Windows ZMQ/TCP messages were
non-blocking local-kernel warnings.

## Known gaps and next step

- The diagnostic cohort oversamples fraud; absolute scores are not PaySim natural-prevalence
  estimates.
- Process RSS before/after is lightweight feasibility evidence, not sampled peak RSS.
- Notebook 04 is a verified review surface; it intentionally does not retrain by default.
- PaySim FeatureSpec v1 was subsequently frozen under M017 from the reviewed E4-safe vector.
- Final full-data/static-PIT baseline, MLflow promotion aliases, model registry lifecycle, Feast,
  Gold, Redis, parity and serving remain future work.
- Next: complete M017 verification, implement the PaySim Bronze/Silver application path, then
  rerun the locked static/PIT baseline from Silver on a clean commit.
