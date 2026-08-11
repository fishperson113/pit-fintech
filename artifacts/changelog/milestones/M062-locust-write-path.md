# M062 — Locust write-path advancement and retry sequence

- **Datetime:** 2026-08-11
- **Status:** verified (Locust headless smoke against live FastAPI + worker)
- **Sprint / task:** Sprint 2 T5/T7 — load-test the advancing online write path and at-least-once retry behavior

## What changed

- Added `scripts/locust_write_path.py`, a one-sequence-per-user Locust user. Each user gets a fresh
  entity and sends ten requests: seed 700, advance 701/702, exact retry, retry with a different
  transaction ID, gap to 704, out-of-order 703, late-arrival 701 with `knowledge_step=704`,
  conflicting same-step retry, and resume at 705.
- Retry scoring fields are compared against the original step-702 response inside the Locust user.
- Added `locust-write-path` Make/PowerShell targets. The user raises `StopUser` after one sequence so
  a headless smoke does not repeat an already-advanced entity indefinitely.

## Verification

Command:

```text
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups locust -f scripts/locust_write_path.py --host http://127.0.0.1:8000 --headless -u 1 -r 1 -t 30s --csv artifacts/reports/locust-write-path --only-summary
```

Result:

- Locust 2.46.3.
- 10 POST `/score` requests.
- 0 failures (`0.00%`).
- Aggregated average 51 ms, median 39 ms, max 168 ms.
- Locust output: `LOCUST WRITE PATH PASS`.
- CSV evidence: `artifacts/reports/locust-write-path_stats.csv`, `_stats_history.csv`,
  `_failures.csv`, `_exceptions.csv`.

The detailed request/response matrix remains at
`artifacts/reports/live-write-path-matrix.md`; this milestone adds the Locust execution layer on top
of the same advancement/retry scenarios.

## Boundaries

- This is not a network-timeout injection; user requested no timeout simulation.
- One user gives deterministic per-entity sequence coverage. Multiple users can be used for
  cross-entity concurrency, but the sequence then uses separate fresh entities.
- An actual forced Redis WATCH collision was not attempted.
