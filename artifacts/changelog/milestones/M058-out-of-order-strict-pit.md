# M058 — Fix out-of-order strict-PIT serving reads

- **Datetime:** 2026-08-11 09:14 +0700
- **Status:** verified (focused unit and lint lanes)
- **Sprint / task:** Sprint 2 T5/T7 — prevent an older request from receiving a newer stored aggregate

## Scope and acceptance

When `apply_score_event` receives a request with `step < stored.feature_step`, the worker must not
return the stored post-event aggregate because it can contain future history relative to the request.
The request must receive a strict pre-decision vector computed from the serving winlog with
`event.step < request_step` and `event.knowledge_step <= request_knowledge_step`.

## What changed

- Added `recompute_pre_decision_features` in `src/pit_fintech/serving/online_state.py`, using the
  request step as the exclusive cutoff.
- The `rejected_older` branch now recomputes from the winlog instead of returning
  `stored.feature_values`; metadata is aligned to the request cutoff (`feature_step=request_step`,
  request timestamp, `fresh` status).
- Guarded `staleness_steps` with `max(0, ...)` so out-of-order responses cannot expose a negative
  freshness distance.
- Added a regression test covering a winlog containing steps 743 and 745 queried at step 744; the
  step-745 event is excluded while step 743 remains eligible.

## Verification

- RED: focused test initially failed during collection because the new helper did not exist; after
  implementation, the first assertion exposed an incorrect test expectation for the `[step-1, step)`
  one-hour boundary. The expectation was corrected without changing production behavior.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit/test_online_write_path.py`
  → **8 passed**.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/unit`
  → **98 passed**.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff check src tests/unit/test_online_write_path.py`
  → **All checks passed**.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format --check
  src/pit_fintech/serving/online_state.py tests/unit/test_online_write_path.py`
  → **2 files already formatted**.
- Full `pytest -q` was attempted but stopped during collection on the pre-existing duplicate test
  module basename `test_paysim_fixture.py` in `tests/unit` and `tests/integration` (`import file
  mismatch`); no test body ran in that command.

## Known gaps / next steps

- No live Redis worker/demo/parity run was performed in this milestone; the focused regression covers
  the cutoff computation and the production branch is static/lane verified.
- Event History is still not wired into the offline build (DuckDB → Gold Delta).
- Redis reset via `SCAN` remains incompatible with the owner's custom Redis build; use targeted `DEL`
  until that issue is resolved.
