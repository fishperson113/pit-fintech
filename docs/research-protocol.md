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
