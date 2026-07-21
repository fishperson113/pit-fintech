# M003 — PIT Fintech proposal HTML deck

- Date: 2026-07-21
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
- Use a self-contained dark fintech visual system without external images, fonts, or chart CDN.

## Files changed

- `docs/reports/pit-fintech-proposal-slides.html`.
- Project status, cumulative changelog, and this milestone log.

## Verification evidence

```text
Static HTML: 4 slides, 8 unique IDs, no external scripts
Browser: all slides render at 1440x810 with no content overflow
Transitions: inactive slides are hidden after the 360 ms transition
Navigation: Next button and ArrowLeft keyboard navigation pass
Browser console: 0 warnings and 0 errors
Regression: 23 pytest cases pass; Ruff check and format check pass
```

## Known gaps and next step

No numeric benchmark chart is included because final experiment results do not exist yet. After
the Sprint 3 experiments, update the deck only from versioned report evidence; do not insert
speculative performance numbers.
