# M011 — Knowledge defense checklist

- Date: 2026-07-24
- Status: verified

## Scope and acceptance

Create a Vietnamese self-assessment checklist that specifies how deeply the project author must
understand the system after each sprint. It complements the existing implementation/evidence
scorecard and must distinguish familiarity with terms from the ability to reason, calculate,
debug and defend unseen cases.

Acceptance requires:

- a D0–D4 observable depth rubric and a closed-note review method;
- explicit Sprint 1, Sprint 2, Sprint 3 and final-project knowledge gates;
- detailed Sprint 1 coverage of grain/entity/order, event/knowledge time, cutoff/window
  semantics, leakage, oracle design, storage and engineering fundamentals;
- reasoning drills that require hand calculation, mutation prediction, incident diagnosis,
  evidence links and trade-off defense;
- final oral-defense prompts, non-compensable hard concepts and red flags for shallow
  tool-oriented understanding;
- cross-linking with the implementation/evidence checklist.

## Decisions and rationale

- Keep knowledge maturity separate from artifact maturity: working code is neither necessary nor
  sufficient evidence that its author can explain why it is correct.
- Use four observable actions for every concept: explain, draw/calculate, break with a
  counterexample, and prove with project evidence.
- Require D3 for core concepts after the relevant sprint and D4 synthesis after Sprint 3.
- Give Sprint 1 the most detailed treatment because an incorrect temporal contract makes later
  platform automation consistently wrong.
- Map the source expectation's learning sequence—correct code, data understanding, storage,
  change handling, incident operations and scale reasoning—onto the three project sprints.
- Add unseen variants and follow-up questions so memorized fixture answers do not pass.

## Files changed

- `docs/reports/knowledge-defense-checklist.md`
- `docs/reports/project-self-review-checklist.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification evidence

```text
Knowledge checklist structure: D0-D4 rubric, four-layer test, three sprint gates,
24 final oral-defense prompts, non-compensable pass conditions, red flags and review template
Required concept scan: pass
Relative local links: verified
Milestone changelog guard tests: pass
git diff --check: pass
```

## Deviations, gaps and next step

- This artifact does not claim the author currently passes the knowledge gates; it defines the
  standard and review method.
- The oral score is intentionally separate from the 100-point implementation scorecard.
- Next step: run the Sprint 1 closed-note review after the remaining PaySim EDA and ADR decisions,
  record weak concepts, and repeat with an unseen temporal fixture.
