# M098 — 10-minute, 12-slide project report deck

- Timestamp: 2026-08-25 11:11:43 +0700
- Status: implemented and browser-verified
- Scope: condense the full-project report into a presentation that fits a ten-minute speaking slot and embed the owner-supplied architecture diagram.

## What changed

Created `docs/reports/pit-fintech-final-report-10min-slides.html` as a new self-contained revision, preserving the earlier 24-slide full report. The new deck has exactly 12 slides and explicit per-slide time boxes totaling ten minutes:

1. title and thesis;
2. problem statement and three invariants;
3. PaySim dataset and leakage boundary;
4. owner-supplied system architecture;
5. temporal and feature contract;
6. medallion ETL;
7. notebook 08–12 modeling experiments;
8. sealed temporal-test LightGBM result;
9. SHAP and MLflow lifecycle;
10. online serving and observability;
11. 100-user load-test and monitored-node resource evidence;
12. conclusion and the missing context needed for a defensible capacity claim.

The architecture slide embeds `docs/architecture/pipeline.png` rather than linking it. It labels the diagram's transitional elements so the presentation does not misstate current state: the crossed feature platform represents Feast removal under ADR-012, and the diagram's `MODEL TBD` has since been resolved to LightGBM. The slide retains the read-before-write message: score transaction `t`, then update state and append history.

## Evidence retained

The condensed deck keeps the current repository/notebook evidence without inventing numbers:

- PaySim: 6,362,620 rows, 8,213 fraud, 0.129% raw prevalence, steps 1–743.
- FeatureSpec v3: 10 model inputs and a separate boundary for temporal controls, labels, threshold, freshness, and lineage metadata.
- Final saved notebook result: 37,979 test rows, 1,252 fraud, PR-AUC 0.3622, ROC-AUC 0.8210, precision 0.2159, recall 0.4848, threshold 0.93726, TP/FP/FN/TN 607/2,204/645/34,523.
- Load evidence: 100 users, 10 users/s spawn rate, 10 requests/user, 1,000 successful `/score` requests, zero errors, average 12.10 ms, p50 8.75 ms, p95 37.28 ms, p99 73.40 ms.
- Resource screenshot: CPU busy 5.9%, RAM 43.6% (approximately 5.23/12 GiB), swap 4.9%, with the monitored-node versus Windows scoring-host caveat retained.

## Capacity-evidence boundary

The final slide records the server context still needed before presenting a capacity/efficiency claim rather than a functional load result:

- CPU model, physical/logical cores, total RAM, and OS of the actual scoring host;
- FastAPI/Uvicorn worker count and placement of FastAPI, Redis, and the PIT worker;
- load-generator placement and network RTT;
- warm/cold model-cache state;
- API-host process CPU/RSS during the exact run;
- Redis memory and stream/worker backlog;
- actual run wall time and Locust client-side RPS;
- repeated 5–15 minute sustained/soak lanes.

## Verification

- Static contract: exactly `s01`–`s12`, 12 timing labels, and three embedded PNG data URIs.
- Embedded image byte sizes: architecture 96,748 bytes; scoring dashboard 80,280 bytes; resource dashboard 67,510 bytes.
- Browser layout inspection found 12 slides, no `scrollWidth`/`scrollHeight` overflow, and all three images complete at their natural dimensions.
- Visual inspection passed for the architecture slide after repairing image containment, the combined load/resource slide, and the conclusion/server-context slide.
- Direct hash navigation and keyboard navigation remain enabled; browser console reported zero messages and zero JavaScript errors.
- `git diff --check` passed before changelog synchronization and is rerun afterward.

## Known gaps

- The deck is paced for ten minutes but has not yet been timed against the owner's live delivery speed.
- Capacity claims remain intentionally bounded until the actual scoring-host metadata and sustained-run evidence are supplied.
