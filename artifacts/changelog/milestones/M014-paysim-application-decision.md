# M014 — PaySim application dataset decision

- Date: 2026-07-27
- Updated: 2026-07-27 09:52:33 +07:00
- Status: verified

## Scope and acceptance

Resolve the Sprint 1 application-dataset gate after full PaySim EDA. The decision must preserve
the engineering-first project outcome, use the predeclared destination-history evidence without
post-hoc threshold changes, and clearly separate pipeline correctness from model utility.

Acceptance requires:

- a frozen PaySim snapshot and full-data notebook outputs;
- an explicit keep/switch decision;
- locked event-time, tie-break, entity, window and split semantics;
- honest constraints on model claims;
- synchronized ADR, project status, cumulative changelog and handoff rules.

## Decision

Keep PaySim as the primary six-week pipeline workload with status
`AMBER_CORRECTNESS_ONLY`.

The outcome means:

- PaySim remains suitable for PIT joins, replay, backfill, reproducibility, offline/online parity,
  serving and failure-gate evidence.
- Recipient history is experimentally meaningful mainly for `CASH_OUT`.
- Fraud `TRANSFER` is effectively a cold-start path.
- The project does not claim stable historical-feature model lift across the full population.
- IEEE-CIS is optional only if a later thesis extension requires stronger model-utility evidence.

## Evidence

```text
snapshot: paysim1:16910f90577b0d98
rows: 6,362,620
steps: 1-743

CASH_OUT warm fraud at 168h:
train 2,058 (70.9655%)
validation 186 (31.5254%)
test 101 (16.1342%)
gate: AMBER

TRANSFER warm fraud at 168h:
train 4 (0.1388%)
validation 0 (0%)
test 0 (0%)
gate: RED

dataset gate: AMBER_CORRECTNESS_ONLY
```

All 13 notebook 02 code cells executed in order and saved no error output. The user explicitly
accepted the engineering-first framing and chose to retain PaySim.

## Technical contract

- Event time: hourly ordinal `step`.
- Deterministic cutoff/replay order: `(step, source_row_number)`, strict `<`.
- Conservative model-utility evidence: `prior_step < current_step`.
- Primary history view: customer `nameDest`; `M...` merchants remain separate.
- Windows: 1 hour, 24 hours and 168 hours; 168 hours is the viability basis.
- Split: steps 1-520 / 521-631 / 632-743.
- Static request features serve every transaction; history includes explicit cold-start coverage.
- Labels are evaluation-only.

## Files changed

- `docs/adr/001-temporal-entity-contract.md`
- `docs/adr/002-paysim-dataset-entity-scope.md`
- `AGENTS.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M009-paysim-eda-notebooks.md`
- this milestone log

## Verification

The decision is backed by user-run notebook outputs already recorded in M009. The agent made no
new notebook, test, Make or pipeline execution.

Static checks:

```text
ADR-002 required headings and decision terms: present
AGENTS.md decision handoff: present
project status and milestone logs: synchronized
```

## Deviations, risks and next step

- The final PyArrow display truncates literal gate columns, although the visible numeric inputs
  uniquely determine the saved SQL classification. Add compact JSON evidence before final release.
- Model family remains TBD; this decision does not preselect LightGBM.
- Next: adapt the feature contract to PaySim, then build full-data Bronze/Silver and execute the
  static/PIT temporal baseline through user-run commands.
