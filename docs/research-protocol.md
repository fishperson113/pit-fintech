# Research protocol v0

The full protocol is frozen before final experiments. Current pre-registered rules are:

- Primary correctness metric: future-read violations, target `0`.
- Offline/online integer and categorical mismatches: target `0`.
- Float parity tolerance: absolute difference `<= 1e-6` unless versioned before experiments.
- Backfill identity: dataset snapshot + entity version + feature version + cutoff range.
- Model primary metric: PR-AUC; ROC-AUC and recall at fixed FPR are secondary.
- Main deployable result: PIT history with temporal split (E4).
- Leaky full-history/random split (E2) is a positive control and never deployable.
- Pipeline comparison keeps storage format fixed for the main P3-vs-P4 conclusion.
- Runtime benchmarks use one warm-up and at least three measured runs; report median and
  dispersion with machine/data/version manifests.
- An inconclusive or lower model score remains reportable; correctness may not be traded for
  model tuning.

The complete E1–E5/P1–P5 matrix is maintained in the source implementation guides under
`docs/feature-store/` and will become `experiments/manifest.yaml` in Sprint 3.

## Verified LightGBM candidate spike and FeatureSpec decision

Sprint 1 completed one explicitly exploratory model-family spike with these locked rules:

- Model family: LightGBM candidate with one fixed CPU configuration and seed `20260727`.
- Cohort: every customer-destination fraud `CASH_OUT`/`TRANSFER` row plus at most 5,000
  deterministic non-fraud rows per temporal split and transaction type.
- Split boundaries: train `1–520`, validation `521–631`, test `632–743`.
- E1: static request features with temporal split.
- E2: deliberately leaky controls with random split.
- E3: strict-PIT recipient features with random split.
- E4: strict-PIT recipient features with temporal split.
- Threshold: chosen on validation at fixed FPR `0.01`; test is not used for threshold selection.
- Primary comparison metric: PR-AUC; ROC-AUC and recall at the fixed-FPR threshold are secondary.
- Tracking: one MLflow parent run, four child runs, and one machine-readable local manifest.

Because the cohort samples non-fraud rows, absolute PR-AUC is not a production-prevalence
estimate. E2 is never deployable. The verified E4 evidence informed ADR-003 and the frozen
`paysim-fraud-recipient-v1` FeatureSpec. E4 cannot become a champion until the Silver-based clean
temporal baseline and Sprint 2 promotion gates exist.

The FeatureSpec decision freezes:

- three request-time fields and nine strict-PIT destination-history fields;
- 1h, 24h and 168h windows with `prior_step < current_step`;
- label/policy/balance exclusions;
- ordered model-vector semantics, cold defaults and `score_then_update`;
- a canonical contract checksum that must be carried by downstream artifacts.

## PaySim application source path

M018 implements the source tables named by ADR-003:

```text
raw PaySim snapshot
  -> bronze.paysim_transactions
  -> silver.paysim_transactions
  -> silver.paysim_labels
```

The Silver transaction table excludes labels, policy output and balance fields. The application
manifest binds exact Delta versions to the raw snapshot, entity/feature versions, canonical
FeatureSpec checksum, code state, quality-gate observations and local resource evidence. Fixture
and full-data execution remain user-run gates; no M018 runtime result is predeclared.

## Implemented Silver baseline protocol

M019 implements, but has not yet runtime-verified, the clean Sprint 1 model baseline:

- sources are exact manifest-recorded versions of `silver.paysim_transactions` and
  `silver.paysim_labels`;
- E1 and E4 both use chronological steps `1–520 / 521–631 / 632–743`;
- E1 uses the frozen three request-time fields;
- E4 uses all 12 frozen strict-PIT fields;
- both use the same deterministic CPU-only LightGBM configuration and seed;
- train retains all fraud and at most 100,000 deterministic non-fraud rows per transaction type;
- validation and test retain all eligible rows at natural prevalence;
- threshold selection uses validation only at fixed FPR `0.01`;
- test PR-AUC is primary; ROC-AUC, recall, precision and observed FPR are reported together;
- exact Delta versions/checksums, FeatureSpec checksum, vector checksum, code/lock identity,
  MLflow runs and model URIs are required evidence;
- clean baseline publication rejects dirty or mismatched trainer/lakehouse Git lineage.

Notebook 05 is a thin caller and interpretation surface. The non-notebook `train` command is the
acceptance path. No M019 metric or runtime result is predeclared.
