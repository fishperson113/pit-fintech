# M059 — duplicate replay strict-PIT fix and live server evidence

- **Datetime:** 2026-08-11
- **Status:** verified (unit, lint, rebuilt worker, live API probe)
- **Sprint / task:** Sprint 2 T5/T7 — make duplicate event replay score on the original pre-decision vector

## Bug observed

A step-745 request for `C1470998563` returned `feature_step=745` and `staleness_steps=0`. Because a
step-745 request must score before step 745, the response was current-inclusive and violated strict
PIT. The issue occurred after the event had already been applied and the request entered the
`noop_identical` duplicate branch.

## Root cause

`apply_score_event` correctly handled `step < stored.feature_step`, but the duplicate branch returned
the stored post-event aggregate. Duplicate detection is based on step, knowledge step and amount,
not `transaction_id`, so changing the transaction ID does not make the request a new event.

## Fix

- Duplicate requests now recompute the pre-decision vector from the serving winlog with
  `request_step` as the exclusive cutoff.
- Same-step and future events are excluded from the recomputation.
- Response metadata uses the latest strictly prior event; a step-745 duplicate after step 744 now
  reports `feature_step=744` and `staleness_steps=1`.
- Added `scripts/debug_strict_pit.py` and `debug-strict-pit` Make/PowerShell targets. The probe sends
  live HTTP requests to `/score`, asserts feature-step/staleness invariants, prints the result, and
  writes `artifacts/reports/out-of-order-debug.md`.

## Verification

- `pytest -q tests/unit/test_online_write_path.py` → **9 passed**.
- `pytest -q tests/unit` → **99 passed**.
- Ruff check and format check → **clean**.
- Rebuilt/recreated worker:
  `docker compose up -d --build --force-recreate pit-online-worker` → exit 0.
- Live probe:
  `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python scripts/debug_strict_pit.py`
  → **strict-PIT live probe: PASS**.
- Evidence report: `artifacts/reports/out-of-order-debug.md`.

## Live evidence summary

- Duplicate step 745 request → HTTP 200, `feature_step=744`, `staleness_steps=1`.
- Out-of-order step 744 request → HTTP 200, `feature_step=744`, `staleness_steps=0`.
- Neither response exposed a future feature step.
