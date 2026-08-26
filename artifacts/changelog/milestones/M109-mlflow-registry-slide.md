# M109 — MLflow Registry evidence slide

- Timestamp: 2026-08-26 10:56 +0700
- Status: implemented and verified
- Scope: replace the sparse conclusion slide with concrete MLflow Registry evidence in the owner-designated compact-load-test deck.

## Acceptance and content

The output is `docs/reports/pit-fintech-final-report-template-12-slides-compact-load-test-mlflow.pptx`.
Slide 11 now uses the supplied MLflow UI screenshot to show:

- registered model `paysim-fraud-lightgbm`;
- model Version 2 and its source run;
- a ten-input schema matching the serving contract;
- the registry as the handoff from notebook training to FastAPI serving.

The speaker notes explain that serving resolves the configured model URI/run, pulls and caches the
artifact, validates the schema, and applies the logged model/threshold. Slide 10 retains its Grafana
load-test evidence and slide 12 remains the closing slide.

## Technical decisions

- Used `pit-fintech-final-report-template-12-slides-notebook-graphs-compact-load-test.pptx` as the
  authoritative source per owner correction.
- Reused the inherited image-led frame from source slide 10 for output slide 11, changed only its
  title/page marker/image/notes, and omitted the sparse source conclusion slide.
- Added the MLflow screenshot as a distinct image element and moved the duplicated inherited image
  frame off-canvas; this avoided mutating slide 10 through the imported shared image asset.
- Restored the source theme XML byte-for-byte after artifact-tool export.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-12-slides-compact-load-test-mlflow.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M109-mlflow-registry-slide.md`

## Verification

- Final slide count: 12.
- All slides rendered; slide 11 inspected at full size and the full montage reviewed.
- `slides_test.py`: PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty placeholders.
- Speaker notes: 12/12 slides contain `[Sources]` blocks.
- Theme SHA-256 source/final:
  `24ee84908f76a09982c529e559ec0135e26b448d5559d59e73794439931c61bd`.
- Final artifact size: 12,479,463 bytes.

## Known gap

The screenshot demonstrates the registered version and schema. It does not by itself prove a live
pull during a specific request; that behavior remains evidenced by the serving configuration,
loader implementation, cache behavior, and runtime tests.
