# M060 — normalize strict-PIT feature-step metadata

- **Datetime:** 2026-08-11
- **Status:** verified (unit, lint, rebuilt worker, live API probe)
- **Sprint / task:** Sprint 2 T5/T7 — make `feature_step` mean the latest event actually included in the vector

## Problem

The out-of-order branch recomputed the correct vector at cutoff `event.step < request_step`, but set
`feature_step=request_step` and `staleness_steps=0`. This made the metadata look current-inclusive
even though the vector excluded the request event. For request step 744, the correct metadata is the
latest strictly prior event step (743), or `null/missing` if no such event remains in the winlog.

## Fix

- Added `latest_prior_event_step(events, request_step)`.
- Both duplicate and out-of-order recomputation paths now use the latest strictly prior event for
  `feature_step` and timestamp metadata.
- `staleness_steps` now reflects the real distance from request step to the latest included prior
  event. A cold result correctly reports `feature_step=null`, `feature_status=missing`, and
  `staleness_steps=null`.
- Added unit coverage for strict prior-step metadata.
- Updated the live probe to reject current/future feature steps while allowing either a valid prior
  state or an explicit cold result, since the existing Redis winlog can vary by prior demo runs.

## Verification

- `pytest -q tests/unit/test_online_write_path.py` → **10 passed**.
- `pytest -q tests/unit` → **100 passed**.
- Ruff check and format check → **clean**.
- Worker rebuilt/recreated with `docker compose up -d --build --force-recreate pit-online-worker`.
- Live probe → **PASS**.

- Live evidence

- The first reused-entity probe was intentionally recorded as insufficient evidence: its winlog had
  only steps 744 and 745, so step 744 correctly had no prior history and returned `missing`.
- The probe was then changed to generate a fresh entity and seed step 743 before sending steps 745
  and 744.
- Seed step 743 → cold pre-decision result (`feature_step=null`).
- First step 745 → `feature_step=743`, `staleness_steps=2`.
- Duplicate step 745 → `feature_step=743`, `staleness_steps=2`.
- Out-of-order step 744 → `feature_step=743`, `staleness_steps=1`.
- Full request/response evidence and the probe correction are recorded in
  `artifacts/reports/out-of-order-debug.md`.
