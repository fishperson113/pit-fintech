# M104 — Notebook graphs on slides 8–11

- Timestamp: 2026-08-25 15:58 +0700
- Status: implemented and verified
- Scope: replace slides 8–11 of the owner's latest 12-slide VSF report with saved modeling-notebook evidence and direct notebook-output graphs.

## Acceptance and content

The output is `docs/reports/pit-fintech-final-report-template-12-slides-notebook-graphs.pptx`.
The cover remains slide 1 and `THANK FOR LISTENING` remains slide 12. Slides 8–11 now contain:

1. NB09–10: PIT-safe history uplift plus the saved validation PR and ROC curves.
2. NB10: walk-forward PR-AUC across temporal cuts and 0h/24h/168h embargoes.
3. NB11: Optuna summary and the saved precision/recall/F1 threshold curve at 0.93726.
4. NB12: sealed-test metrics and the saved global SHAP importance bar chart.

All graphs were decoded from existing PNG outputs embedded in the executed notebooks; none was
redrawn from invented data. The slide copy uses the matching saved notebook metrics and JSON
handoff files.

## Technical decisions

- Treated the owner's currently edited 12-slide cutoff-impact deck as the source of truth even
  though its filename still contains `13-slides`.
- Reused the inherited VSF image-led frame for slides 8–11. Artifact-tool imports shared the
  inherited image asset across duplicated frames, so each notebook graph was added as its own
  image element and the inherited image frame was moved off-canvas. This kept the template style
  while avoiding repeated-image aliasing.
- Preserved editable title/body/page-number text and added notebook/file provenance to speaker
  notes using `[Sources]` blocks.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-12-slides-notebook-graphs.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M104-notebook-graphs-slides-8-11.md`

## Verification

- Final slide count: 12.
- All 12 slides rendered; slides 8–11 inspected at full size and the full-deck montage reviewed.
- `slides_test.py`: PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty placeholders.
- Speaker notes: 12/12 slides contain `[Sources]` blocks.
- Theme SHA-256 source/final:
  `66bf8b7e263abb241da328f6867c9f2c07e824b3320c98e7841ec759356b8803`.
- Final artifact size: 12,448,564 bytes.

## Known gap

The graphs use the notebooks' saved rendering and labels verbatim. Some plot labels therefore
remain in the original Vietnamese/English mix rather than being re-authored as editable chart text.
