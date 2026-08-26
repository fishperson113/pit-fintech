# M101 — VSF-template full-project PowerPoint report

- Timestamp: 2026-08-25 13:56 +0700
- Status: implemented and verified
- Scope: convert the current full-project HTML report into a 12-slide editable PowerPoint deck that
  follows the owner-supplied VSF template, with a cover first slide and a `THANK FOR LISTENING`
  closing slide.

## Acceptance and narrative

The output is `docs/reports/pit-fintech-final-report-template-12-slides.pptx` and contains exactly
12 slides:

1. cover and project thesis;
2. problem and three correctness invariants;
3. PaySim workload, entity scope, and leakage boundary;
4. offline/online architecture and read-before-write contract;
5. two-axis temporal and FeatureSpec v3 contract;
6. Raw/Bronze/Silver/Gold plus reproducible backfill;
7. notebook 08–12 experiment sequence and decision locks;
8. sealed temporal-test LightGBM evidence;
9. SHAP interpretation and MLflow promotion lifecycle;
10. online scoring order and observability path;
11. load/resource evidence and bounded conclusion;
12. `THANK FOR LISTENING`.

The conclusion from the previous HTML slide 12 was condensed into slide 11 so the final slide can be
the requested thank-you close without increasing the slide count.

## Technical decisions

- Used the supplied `[VSF] Templet.pptx` as the visual source and duplicated mapped source slides;
  no alternative theme or layout library was mixed in.
- Rewrote inherited textboxes/tables in place and preserved their original typography, spacing, and
  geometry. The architecture visual uses the inherited image frame from template slide 15.
- Deleted the unrelated inherited sample table on the architecture slide and zero-sized title
  placeholders instead of overlaying new content.
- Added `[Sources]` blocks to speaker notes on all slides. Project facts point to the current HTML
  report; the research-framing slide also cites the PVLDB feature-store paper.
- Restored `ppt/theme/theme1.xml` from the source template after artifact-tool export, as the export
  normalized that file even though the visible design remained intact.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-12-slides.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M101-vsf-template-project-pptx.md`

## Verification

- Artifact-tool template inspection: 21 source slides, complete non-truncated inventory.
- Template frame-map validation: PASS, zero issues.
- Final slide count: 12.
- Final render: all 12 slides exported to PNG and individually inspected at full size.
- Overflow gate: `slides_test.py` PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty `<p:ph>` shapes in final slide XML.
- Speaker notes: 12 notes slides with `[Sources]` blocks.
- Theme preservation: source and final `ppt/theme/theme1.xml` SHA-256 both
  `617f40cb77f46abc81c064fefab640f84620ebc9e26c4e94ab2c4f8d41952862`.
- Architecture image fit: contained in the inherited frame without crop.

## Deviations and known gaps

- The deck is designed for a concise project defense, but the owner's speaking pace has not been
  rehearsed against the final PPTX.
- The load conclusion remains intentionally bounded: it does not claim maximum users/RPS without
  repeated runs, sustained/soak evidence, backlog capture, and a separate load-generator host.

## Next step

Owner review in PowerPoint, then optionally tune presenter notes or shorten copy based on a timed
practice run without changing the verified evidence values.
