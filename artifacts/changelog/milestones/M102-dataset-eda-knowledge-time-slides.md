# M102 — Dataset EDA and knowledge-time predicate slides

- Timestamp: 2026-08-25 14:20 +0700
- Status: implemented and verified
- Scope: revise the VSF-template project report so slide 3 uses Notebook 08 dataset evidence and
  add a dedicated, concrete `event_step` + `knowledge_step` predicate slide.

## Acceptance and narrative

The output is `docs/reports/pit-fintech-final-report-template-13-slides.pptx` and is a
non-destructive revision of the 12-slide M101 deck. The user requested an additional predicate
slide, so the deck now contains 13 slides; slide 1 remains the cover and slide 13 remains
`THANK FOR LISTENING`.

Slide 3 now communicates four EDA conclusions from saved Notebook 08 outputs:

1. 6,362,620 transactions contain only 8,213 frauds: 0.1291%, or roughly one fraud per 775 rows;
2. PR-AUC is the primary metric because accuracy is misleading under this imbalance;
3. fraud counts vary across simulated days, motivating temporal/walk-forward rather than random
   splitting;
4. ten training inputs are separated from domain/control fields. `step`, `knowledge_step`,
   `source_row_number`, and entity identity drive PIT eligibility/order but are not fed to
   LightGBM. Labels, the legacy policy output, and four balance fields remain forbidden.

Slide 4 uses the inherited four-point timeline to show:

- 07:00: the bank creates a transaction (`event_step`);
- 07:05: a score request must exclude it because the platform does not yet know it;
- 07:10: delayed network/ingress makes the event known (`knowledge_step`);
- 07:12: a later score may include it only when both
  `prior.event_step < current.event_step` and `prior.knowledge_step <= cutoff` are true.

## Technical decisions

- Reused the already template-aligned M101 deck and duplicated its existing timeline slide instead
  of introducing a new visual system.
- Edited inherited textboxes and footers in place using `@oai/artifact-tool`; no fresh overlay
  slide or alternative theme was introduced.
- Preserved the original 12-slide output and wrote the revision to a new 13-slide PPTX.
- Kept `knowledge_step` explicitly labeled as a domain/control feature rather than a model input,
  matching the Notebook 08 feature-role cell and the repository PIT contract.
- Replaced the broad phrase "data drift" with the evidence-bounded wording "tín hiệu drift theo
  thời gian": saved Notebook 08 output shows fraud counts varying by simulated day; it does not
  claim a formal drift-test statistic.
- Restored the source `ppt/theme/theme1.xml` after export so the theme checksum remains exact.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-13-slides.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M102-dataset-eda-knowledge-time-slides.md`

## Verification

- Template frame-map validation: PASS, zero issues.
- Final slide count: 13.
- Final render: all 13 slides exported to PNG and individually inspected at full size.
- Overflow gate: `slides_test.py` PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty `<p:ph>` shapes in final slide XML.
- Speaker notes: 13 notes slides with 13 `[Sources]` blocks.
- Theme preservation: source and final `ppt/theme/theme1.xml` SHA-256 both
  `617f40cb77f46abc81c064fefab640f84620ebc9e26c4e94ab2c4f8d41952862`.
- Final artifact size: 12,316,499 bytes.

## Deviations and known gaps

- The user's first request fixed 12 slides, but this follow-up explicitly asks for an additional
  predicate slide. The deck therefore becomes 13 slides rather than compressing away an existing
  project-report topic.
- The 07:00/07:10 example is an explanatory production-time analogy. PaySim's native `step` is an
  hourly simulation index; the slide demonstrates the same two-axis predicate at minute-level
  resolution without claiming PaySim itself records minute timestamps.

## Next step

Owner review in PowerPoint and a timed rehearsal; presenter notes can be shortened later without
changing the verified dataset or predicate semantics.
