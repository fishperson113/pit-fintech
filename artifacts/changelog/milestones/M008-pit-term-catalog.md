# M008 — PIT terminology catalog

- Date: 2026-07-23
- Status: verified

## Scope and acceptance

Create `docs/reports/catalog.md` as a beginner-friendly Vietnamese glossary for the English terms
used in the four-slide proposal and ten-minute speaker script. It must explain `temporal view` in
depth, anchor the vocabulary in one fraud-scoring timeline, distinguish easily confused concepts,
state each technology's limited role, and provide presentation-ready Vietnamese alternatives.

## Technical and editorial decisions

- Use one transaction-at-10:00 example to connect event time, knowledge time, cutoff,
  pre-decision features, post-event state, late arrival and future leakage.
- Mark the terms that are essential for the meetup and group the rest by temporal semantics,
  feature contracts, online/offline parity, evidence, backfill, technology and research.
- Explain `temporal view` as a logical point-in-time perspective rather than a SQL `VIEW`.
- Include “what not to claim” for major technologies so the catalog also protects status and
  architecture boundaries.
- Finish with a keyword replacement cheat sheet and five sentences to memorize.

## Files changed

- `docs/reports/catalog.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification evidence

```text
Required-term scan: pass; PIT, cutoff, temporal view, event/knowledge time, pre/post state,
parity, oracle, backfill, atomic/idempotent/reproducible, temporal split and status vocabulary are
present.
Reader aids: pass; one timeline example, technology-role table, Vietnamese cheat sheet and five
meetup-ready sentences are present.
git diff --check: pass; existing LF-to-CRLF working-copy warnings only.
```

## Deviations, gaps and next step

- The source deck and speaker script were not modified.
- The catalog favors project-specific meaning over exhaustive textbook definitions.
- Next step: use the cheat sheet during rehearsal and mark any remaining unfamiliar term for a
  later focused revision.
