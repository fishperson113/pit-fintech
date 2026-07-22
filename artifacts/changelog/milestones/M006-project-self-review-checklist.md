# M006 — Project self-review checklist

- Date: 2026-07-22
- Updated: 2026-07-22 12:26:22 +07:00
- Status: verified

## Scope and acceptance

Create a reusable self-review checklist for end-of-sprint, pre-demo and final project review. It
must reflect the project's MLOps/ML Systems outcome while retaining Big-Tech-style evaluation of
data correctness, incremental processing, software engineering, debugging, incident response
and design trade-offs.

Acceptance requires:

- absolute hard gates cannot be hidden by an aggregate score;
- every checked item requires reproducible evidence;
- planned, implemented and verified remain distinct;
- scorecard covers training, serving and cross-cutting observability;
- known proposal gaps are represented without adding mandatory platform services.

## Decisions and rationale

- Put the human-readable checklist in `docs/reports/` per repository governance.
- Separate unscored hard gates from the weighted scorecard so leakage/parity/version failures
  cannot be averaged away.
- Use eight groups totaling 100 points: data understanding; temporal/incremental correctness;
  storage/reconciliation/change; Python/SQL/SWE; model lifecycle; serving/parity;
  operations/incident; and research/scale reasoning.
- Score maturity from 0–4 based on evidence depth, not checkbox count or number of technologies.
- Keep Grafana optional as a visualization surface; require instrumentation, raw metrics/logs and
  actionable fault evidence independently.
- Add explicit reconciliation, compatible/breaking schema evolution, incident/postmortem and
  scale-up design checks identified during the Big Tech comparison.

## Files changed

- `docs/reports/project-self-review-checklist.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M006-project-self-review-checklist.md`

## Verification evidence

```text
Markdown structure: review snapshot, 13 hard gates, 8 weighted groups, total 100 points,
result interpretation, retrospective and sources of truth
Relative local links: 6/6 verified to exist
Milestone changelog guard tests: 4 passed
git diff --check: pass (only expected LF-to-CRLF working-copy warnings)
```

## Deviations, gaps and next step

The checklist is a reusable blank review instrument; it does not assign a current score because
Sprint 2/3 outcomes remain planned. At the end of each sprint, create a dated review artifact or
copy the template into the relevant gate report and link exact machine-readable evidence.
