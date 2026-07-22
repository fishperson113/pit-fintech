# M003 — PIT Fintech proposal HTML deck

- Date: 2026-07-21
- Updated: 2026-07-22 12:07:53 +07:00
- Status: verified

## Scope and acceptance

Create a concise three-to-four-slide HTML presentation answering: project name/objective,
solution and technology flow, and whether the intended output serves Fintech employment,
research proposal, or exploratory experience.

## Content and design decisions

- Use four slides following a problem–solution–benefit structure.
- Lead with the three project invariants rather than model metrics.
- Present the implementation flow from raw data to replay/serving as a compact architecture.
- Frame the outcome as dual-purpose: Fintech/MLOps portfolio first, research-backed proposal
  second; experimentation is supporting practice, not the primary deliverable.
- Use a self-contained dark fintech visual system without external fonts or chart CDN.
- In the 2026-07-22 refinement, replace the text-heavy architecture cards on slide 3 with the
  user's finalized high-level architecture image. Keep the image unmodified, repo-local and
  dominant within the 16:9 safe area.
- Reframe slide 4 as a progression rather than three competing options: Engineering/MLOps is the
  immediate career outcome, while a complete E2E thesis is the second-stage extension. The
  e-commerce prediction baseline is a reference for thesis completeness, not a commitment to its
  domain or stack. “Experience” is an enabler and no longer a standalone output direction.
- Reframe slide 2 as two explicit execution problems: offline fraud-model training and online
  fraud-score serving. Present the PIT Feature Platform as their shared contract/semantics bridge;
  leave component topology to the user-authored architecture image on slide 3.
- Add observability as a third, cross-cutting concern on slide 2 rather than presenting it as a
  third business pipeline. Show the high-level telemetry path `OTel -> Prometheus -> Grafana` and
  limit its purpose to freshness, parity, latency, errors and version-mismatch visibility.
- Make slide 2 speaker-friendly without returning to dense prose: show the full project name,
  state the leakage-free training/cutoff-correct serving objective, and add four compact scope
  anchors for dataset, resources/cost, timeline and Engineering-to-thesis direction.

## Files changed

- `docs/reports/pit-fintech-proposal-slides.html`.
- `docs/architecture/pipeline.png` is the user-authored source image consumed by the deck; the
  deck edit does not modify the image itself.
- Project status, cumulative changelog, and this milestone log.

## Verification evidence

```text
Static HTML: 4 slides, 8 unique IDs, no external scripts
Browser: all slides render at 1440x810 with no content overflow
Transitions: inactive slides are hidden after the 360 ms transition
Navigation: Next button and ArrowLeft keyboard navigation pass
Browser console: 0 warnings and 0 errors
Regression: 23 pytest cases pass; Ruff check and format check pass

2026-07-22 architecture-image refinement:
Source image: 1457x626 PNG, 320322 bytes
Repo-relative HTML reference: ../architecture/pipeline.png
Rendered slide/deck: 1440x810
Rendered image box: approximately 1282x551
Image complete/natural dimensions: pass, 1457x626
Slide overflow: false
Figure inside slide bounds: true
Browser console/page errors: 0

2026-07-22 two-problem framing refinement:
Slide 2 execution cards: 2
Slide 2 scope chips: 4
Rendered card boxes: 639x218 each
Shared PIT Feature Platform bridge: visible
Card overflow: false
Slide overflow: false
Browser console/page errors: 0

2026-07-22 observability refinement:
Slide 2 cards: 3 (Offline Training, Online Serving, Observability)
Telemetry path: OTel -> Prometheus -> Grafana
Rendered card boxes: 421x216 each
Slide 2 scope chips: 4
Card/chip overflow: false
Slide overflow: false
Browser console/page errors: 0

2026-07-22 output-direction refinement:
Slide 4 outcome cards: 2 sequential stages
Rendered card boxes: 639x248 each
Card overflow: false
Slide overflow: false
Browser console/page errors: 0
```

## Known gaps and next step

No numeric benchmark chart is included because final experiment results do not exist yet. After
the Sprint 3 experiments, update the deck only from versioned report evidence; do not insert
speculative performance numbers.
