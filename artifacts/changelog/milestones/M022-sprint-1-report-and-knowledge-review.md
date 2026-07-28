# M022 — Sprint 1 report deck and knowledge review

- Date: 2026-07-27
- Updated: 2026-07-28
- Status: implemented; deck visual verification passed, knowledge gate does not pass

## Scope and acceptance

Create a Sprint 1 HTML report that reuses the proposal deck's visual language while reporting
only verified outcomes, honest limitations and the Sprint 2 handoff. Prepare a closed-note
knowledge interview based on the self-review and knowledge-defense checklists.

Acceptance:

- seven 16:9 HTML slides with keyboard/button navigation and print layout;
- claim → evidence → limitation → handoff narrative;
- no claim that Sprint 2 serving/parity/backfill is implemented;
- model comparison reports the negative E4 result honestly;
- knowledge gate distinguishes engineering completion from author understanding;
- ten-question D0–D4 review with hard-invariant pass criteria.

## Decisions

- Reuse the proposal deck's dark green grid, condensed typography and evidence color system.
- Use CSS-native diagrams and bars so the report remains portable and offline.
- Keep the target architecture out of the evidence path; the deck shows only the Sprint 1 slice
  that was actually built.
- Mark knowledge status `unassessed` until the user answers closed-note questions.
- Ask one question at a time and record remediation after evidence review.

## Files added or changed

- `docs/reports/pit-fintech-sprint-1-report-slides.html`
- `docs/reports/sprint-1-knowledge-review.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

- Static verification passes: seven slide sections, two navigation buttons, hash routing,
  keyboard navigation, fullscreen support, responsive rules and print layout are present.
- `git diff --check` passes.
- Every numeric claim was reconciled against committed Sprint 1 evidence, including the release
  gate, EDA ratios, feature checksum, lakehouse resource figures and E1/E4 metrics.
- The in-app browser rejected direct `file://` navigation under its URL policy, so visual
  overflow/console verification remains pending until the local deck is opened by the user.
- No model, notebook, pytest or data pipeline command was run for this documentation milestone.

## Known gaps and next step

- The deck reports the verified M019 baseline; M021's post-commit fingerprint training run is a
  separate pending evidence update.
- Knowledge review is in progress: Q1 scored D2. The user correctly prioritized zero future
  reads over metric lift and recalled the main implementation slice, but did not map evidence to
  each invariant, described parity at the store/contract level instead of equal versioned vectors,
  omitted atomic/idempotent/exact-manifest backfill requirements and treated MLflow experiment
  tracking as if promotion aliases were already complete.
- Q2 scored D2. The user correctly selected eligible history, computed count/sum/history and
  excluded the late-created and wrong-entity rows. The answer incorrectly collapsed canonical
  rows into eligible rows, did not retain one copy after exact deduplication, and omitted recency
  plus the post-score state transition.
- Q3 scored D1. The user correctly rejected an event that was unknowable at the decision cutoff,
  but defined event time as request arrival, conflated knowledge time with queue waiting, treated
  processing time as completion, and could not explain watermark or same-cutoff reconstruction.
- Q4 scored D2. The user correctly used origin singleton sparsity to defend destination history,
  interpreted AMBER as engineering-correctness viability with limited model utility, and limited
  the main claim to PIT feasibility. Only one numeric result was recalled and the forbidden model
  claim needs to be stated as no consistent history lift/generalization, not vague inaccuracy.
- Q5 scored D2. The user correctly explained that feature computation and dataset splitting are
  independent operations, so a full-history value already contaminated by future rows survives
  any split boundary, and correctly named this a violation of the no-future-read invariant. The
  user initially inverted the positive control by stating a low E2 score would indicate leakage,
  then self-corrected after being shown the M016 numbers. The answer did not separate within-row
  leakage from across-split leakage that a temporal split does bound, omitted the
  training/serving parity consequence, and drifted into Q4 material on nameOrig singletons. On
  the changed-assumption case where E2 drops to 0.30 while E3 and E4 hold, the user diagnosed
  label sparsity instead of applying control logic, and labeled leakage as overfitting.
- Q6 scored D2. The user correctly explained that changing `<` to `<=` pulls the scored
  transaction into its own history window and named the resulting violation, but misidentified
  the oracle as an online store, described oracle-versus-optimized divergence as offline/online
  parity, listed only clock-skew causes while omitting tie-breaking, RANGE versus ROWS, boundary
  conventions, duplicate handling and float accumulation order, and did not design a boundary
  test or correctly explain why a random fixture is blind to the mutation.
- Q7 scored D2. The user correctly described the raw-to-Gold transformation flow and separated
  DuckDB, Delta and Parquet by capability, but answered transformation instead of grain so the
  Gold entity/cutoff grain shift was missed, placed the three tools in one category,
  mischaracterized Parquet as JSON-like instead of binary columnar with row groups, statistics
  and predicate pushdown, did not state Delta as Parquet plus a transaction log, and did not name
  atomicity/version pinning as what is lost without Delta.
- Q8 scored D2. The user correctly identified Git commit, Delta version, snapshot ID and
  checksum, but misdescribed the component fingerprint as a build-blocking version lock rather
  than stale-artifact lineage detection, did not explain the ADR-004 rationale for replacing
  commit equality, and did not separate the reproduction-coordinate group (Git commit, Delta
  version) from the drift-detector group (checksum, fingerprint, snapshot ID).
- Q9 scored D2. The user correctly read E4's higher ROC-AUC as better global separation and kept
  the claim inside PIT feasibility, but did not explain the FPR-versus-precision denominator
  mechanism, contradicted the recorded FPR numbers, treated a threshold property as the reason
  for a threshold-free metric gap, inverted the E1/E4 subset relation, and did not name the
  PaySim-specific static amount/oldbalanceOrg signal.
- Q10 scored D1. The user honestly flagged the unknown evidence surface but only named generic
  metric drift without direction, did not predict the zero-history case as the first failing
  evidence, did not compute the exact plus-one/plus-amount offset, did not distinguish
  single-row from n-row contamination, did not note that this leak inflates rather than degrades
  metrics, and proposed no regression test.
- Interview complete at 10/10 assessed, total score 18/40. Hard-invariant questions Q1, Q2, Q3,
  Q5, Q6 and Q10 remain below D3, so the Sprint 1 knowledge gate does not pass under its own pass
  criteria (no hard-invariant answer below D3, and temporal calculation confirmed on two
  different fixtures — only one fixture has been run). Remediation is required before Sprint 1
  can be called knowledge-pass.
- Next: rebuild layers 2 and 3 first — boundary fixture for Q6, zero-history fixture for Q10 and
  control logic for Q5 — then re-test Q1, Q2 and Q3 with evidence and a second temporal fixture.

## Deck visual verification (2026-07-28)

User confirmed by direct visual inspection that
`docs/reports/pit-fintech-sprint-1-report-slides.html` renders correctly: no overflow, no
console errors. This closes the deck half of this milestone's acceptance.

The knowledge-review half is unaffected by this confirmation: the interview remains complete at
10/10 assessed (18/40) with Q1, Q2, Q3, Q5, Q6 and Q10 below D3, so the Sprint 1 knowledge gate
still does not pass. M024 has since added the test artifacts that Q5/Q6/Q10 remediation asked
for (see `artifacts/changelog/milestones/M024-knowledge-review-remediation-tests.md`), but the
interview itself has not been re-scored and this conclusion is intentionally left unchanged here.
