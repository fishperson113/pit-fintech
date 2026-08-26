# M097 — Full-project HTML report deck

- Timestamp: 2026-08-25 10:50:11 +0700
- Status: implemented and browser-verified
- Scope: one self-contained 16:9 HTML presentation covering the problem, PaySim dataset, temporal contract, as-built architecture, modeling experiments, medallion ETL, feature boundaries, serving, observability, and the supplied 100-user load-test evidence.

## Acceptance and evidence

The requested narrative is implemented in `docs/reports/pit-fintech-final-report-slides.html` as 24 slides:

1. problem statement and the three hard invariants;
2. PaySim profile, application scope, entity choice, and leakage boundary;
3. two-time-axis PIT contract and current architecture after Feast removal;
4. Raw/Bronze/Silver/Gold medallion pipeline and the pre-decision versus post-event Gold products;
5. explicit separation of the ten v3 model inputs from temporal controls, labels, decision threshold, freshness, and lineage metadata;
6. notebook 08–12 experiment sequence with saved-output LightGBM results;
7. MLflow lifecycle, online read-before-write path, observability, and evidence boundaries;
8. the supplied Locust/Grafana run and host-resource screenshots.

No model or dataset metrics were synthesized. The deck cites repository paths on each slide and uses saved notebook outputs for the current LightGBM values. The load slide records the supplied setup as 100 users at 10 users/s: 1,000 `/score` calls because each current user performs ten calls, with a ten-second nominal spawn window. The server dashboard shows 1,000 successes, zero errors, average 12.10 ms, p50 8.75 ms, p95 37.28 ms, and p99 73.40 ms.

The resource slide records CPU busy 5.9%, RAM used 43.6% of 12 GiB (approximately 5.23 GiB), swap 4.9%, and root filesystem 86.1%. It explicitly states the evidence boundary: the checked-in VPS stack's Node Exporter monitors the telemetry node, so the screenshot must not be used as API-host CPU/RAM evidence when FastAPI, Redis, and the worker run on Windows.

## Technical implementation

- Single portable HTML file; both supplied PNG screenshots are embedded as base64 data URIs.
- Fixed 1920×1080 canvas scales to the viewport without clipping.
- Keyboard navigation: left/right arrows, Page Up/Down, Space, Home/End; `F` requests fullscreen.
- Click navigation, persistent current slide, direct hash navigation, progress line, slide numbering, and print CSS are included.
- The deck has no CDN, web-font, JavaScript framework, or runtime-server dependency.

## Verification

- HTML structure check: 24 unique slide IDs (`s01`–`s24`), two embedded PNGs decoded to the exact supplied sizes (80,280 and 67,510 bytes), keyboard navigation and print CSS present.
- Browser load from the local `file:///` URL succeeded; title and accessibility tree were available.
- Browser layout inspection at a 1264×625 viewport found the scaled 16:9 canvas bounded exactly inside the viewport.
- Programmatic inspection found no slide `scrollWidth`/`scrollHeight` overflow, no duplicate IDs, and both images complete with natural sizes 1577×866 and 1576×757.
- Visual inspection completed for title, architecture, final modeling, and resource/load slides; no clipping or overlap was observed.
- `git diff --check` passed before the changelog update and is rerun after synchronization.

## Decisions and deviations

- The deck reports FeatureSpec v3 as the current implemented contract but does not imply that notebook model registration automatically moved the MLflow champion alias.
- Notebook 09 feature-selection metrics are labeled as selection evidence; notebook 12 sealed-test metrics are used for the final current modeling result.
- The load test is described as a one-shot burst distributed over the spawn window, not as sustained 100-user concurrency.
- The supplied CPU/RAM screenshot is included with the monitored-node caveat rather than being misattributed to the scoring host.

## Known gaps and next steps

- Owner presentation review and wording/style changes remain possible; no PDF/PPTX export was requested.
- A defensible capacity claim still needs sustained/soak lanes and CPU/RAM/process metrics from the actual machine running FastAPI, Redis, and the online worker.
- Current notebook model quality remains experimental lifecycle evidence until the repository's explicit promotion gates are run.
