# M108 — Slide 7 ML decision flow

- Timestamp: 2026-08-26 09:59 +0700
- Status: implemented and verified
- Scope: replace slide 7's notebook inventory with a clear Andrew Ng-style machine-learning workflow in which each notebook answers one decision question.

## Acceptance and content

The output is `docs/reports/pit-fintech-final-report-template-12-slides-ml-workflow.pptx`.
Slide 7 now maps the five modeling notebooks to a cumulative workflow:

1. NB08 diagnoses whether the data is usable and where leakage can occur.
2. NB09 determines which features add signal while remaining PIT-safe.
3. NB10 tests stability through time using walk-forward validation and embargoes.
4. NB11 selects parameters and the decision threshold on development/validation evidence.
5. NB12 opens the sealed test once and explains the final model with SHAP.

Each column also states the decision locked and the artifact produced. The visible narrative makes
train/dev iteration distinct from final test evaluation rather than presenting the notebooks as a
flat inventory.

## Technical decisions

- Preserved the prior deck and exported a new copy.
- Reused slide 7's inherited Highlight layout, title/text slots, and native 5x5 table; no new
  primitives, overlays, or external visual assets were added.
- Kept the original table styling and rewritten cell values within the existing table geometry.
- Corrected the inherited page marker from `08` to `07`.
- Updated slide 7 speaker notes with notebook provenance and the official Machine Learning Yearning
  resource link.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-12-slides-ml-workflow.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M108-slide-7-ml-decision-flow.md`

## Verification

- Final slide count: 12.
- All 12 slides rendered; slide 7 inspected at full size.
- `slides_test.py`: PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty placeholders.
- Speaker notes: 12/12 slides contain `[Sources]` blocks.
- Theme SHA-256 source/final:
  `66bf8b7e263abb241da328f6867c9f2c07e824b3320c98e7841ec759356b8803`.
- Final artifact size: 12,448,976 bytes.

## Known gap

The slide intentionally uses concise bilingual ML vocabulary (`dev`, `sealed test`, `PIT-safe`)
to match the surrounding technical deck; these terms are explained orally rather than expanded in
the table.
