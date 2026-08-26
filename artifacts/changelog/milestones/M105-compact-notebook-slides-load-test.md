# M105 — Compact notebook slides and load-test result

- Timestamp: 2026-08-25
- Status: implemented; HTML browser-verified; PPTX package/XML verified; native render validation blocked by missing `lxml`/LibreOffice in this environment.
- Scope: condense the notebook-heavy ending of the report and add the observed platform load-test result.

## Changes

- Added `docs/reports/pit-fintech-final-report-template-12-slides-notebook-graphs-compact-load-test.pptx` as a non-destructive revision of M104.
- Slides 8–9 now keep only the decision-relevant notebook graph summaries: PIT-history uplift and temporal validation drift.
- Slide 10 is now a compact load-test result: 1,080 completed, 0 errors, p95 32.42 ms, p99 49.30 ms, with the explicit conclusion that p95 stayed below 100 ms.
- Slide 11 is now a compact conclusion rather than another dense notebook output slide.
- Updated `docs/reports/pit-fintech-final-report-10min-slides.html` to hide the detailed resource/screenshot blocks on the load and conclusion slides and to foreground the same p95 < 100 ms / zero-error result.

## Evidence and verification

- Source evidence: `artifacts/reports/load-resource-20260825-120757-summary.json` (`requests=1080`, `completed=1080`, `errors=0`, `p95_latency_ms=32.421875`, `p99_latency_ms=49.296875`).
- PPTX ZIP test passed; all PPTX XML and relationship parts parsed successfully; edited slides contain the intended copy and slide 10 contains no residual graph image.
- HTML browser verification: exactly 12 slide IDs, no slide overflow, slide `#s11` shows the compact load-test message, and no console errors were reported.
- Native PowerPoint validator could not run because the environment lacks `lxml`; LibreOffice renderer is also unavailable on PATH. No claim of full visual PPTX render verification is made.

## Known boundary

- The report states the observed load-test run result, not a maximum-capacity or sustained-soak claim. The full resource/topology caveat remains available in the evidence report and changelog.
