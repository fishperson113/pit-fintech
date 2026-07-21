# M002 — Milestone audit governance and documentation layout

- Date: 2026-07-21
- Status: verified

## Scope and acceptance

Make milestone implementation history durable, agent-enforced, and reviewable. Human reports
must live under `docs/reports/`; runtime artifacts remain ignored except for tracked changelog
governance.

## Technical decisions

- Use three synchronized audit layers: current status, cumulative changelog, and detailed
  milestone logs.
- Keep governance inside `artifacts/changelog/` as a gitignored-folder exception.
- Use a local, dependency-free Python pre-commit guard so it works on Windows and CI-capable
  hosts without importing the application package.
- Require logs for changes to code, tests, notebooks, infrastructure, ADRs, and milestone
  reports. General documentation-only edits do not create unnecessary milestone noise.

## Files changed

- `AGENTS.md`, `.gitignore`, `.pre-commit-config.yaml`, Make/PowerShell task runners.
- `scripts/verify_milestone_changelog.py` and hook unit tests.
- `artifacts/changelog/` audit structure.
- Reports moved from root `reports/` to `docs/reports/`; documentation links updated.

## Verification evidence

```text
uv run pre-commit install                              -> hook installed
uv run pytest -q                                       -> 23 passed
uv run ruff check src tests feature_repo notebooks scripts -> pass
uv run ruff format --check ...                         -> pass
python scripts/verify_milestone_changelog.py           -> pass with no staged changes
```

## Deviations, gaps, and next step

The guard checks staged paths; it cannot infer whether prose is factually complete. Reviewers
and agents must still verify evidence content. Future milestone commands should update the
active milestone log incrementally and finalize it only when acceptance gates pass.
