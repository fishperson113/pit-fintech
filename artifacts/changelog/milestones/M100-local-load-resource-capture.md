# M100 — One-second local load-resource capture job

- Timestamp: 2026-08-25 12:08:40 +0700
- Status: implemented, tested, smoke-verified, and live capture running
- Safety boundary: sampler is read-only. It does not restart, stop, delete, reset, or mutate FastAPI, Locust, Redis, the PIT worker, Docker volumes, caches, or project data.

## Scope

Added a background resource sampler for the owner-controlled load-test window. The owner will run Locust and later request a stop; after a graceful stop, the CSV will be analyzed for peaks and added to the presentation/report.

## Implementation

- New script: `scripts/capture_load_resources.py`.
- New tests: `tests/unit/test_capture_load_resources.py`.
- Default interval: one second.
- Output mode: new CSV opened with exclusive creation; an existing file is never overwritten.
- Every row is flushed immediately so evidence remains readable if execution is interrupted.
- SIGINT/SIGTERM request a graceful stop and close only the script-owned `docker stats` reader.

CSV evidence includes:

- local and UTC timestamps plus elapsed seconds;
- host CPU, RAM used/available/percentage, and swap percentage;
- FastAPI listener PID, CPU, RSS, and thread count from port 8000;
- Locust listener PID, CPU, RSS, and thread count from port 8089;
- Redis CPU, memory/limit, and PIDs;
- PIT worker CPU, memory/limit, and PIDs;
- Docker reader error state.

The Docker stream parser tolerates ANSI/control-only refresh lines emitted by Docker Desktop and converts B/kB/MiB/GiB/TiB values into numeric MiB.

## TDD and verification

- Initial RED: 3 expected failures because `scripts/capture_load_resources.py` did not exist.
- Docker ANSI-prefix regression RED: missing decoder failed as expected.
- Docker control-only refresh regression RED: decoder raised instead of ignoring the line.
- Focused GREEN: `5 passed in 0.67s`.
- Ruff check: PASS.
- Ruff format check: 2 files already formatted.
- Full unit lane: `122 passed in 25.97s`.
- `git diff --check`: PASS (line-ending warnings only for pre-existing Windows-authored files).
- Five-second smoke: 5 CSV rows; API PID 9440 and Locust PID 24816 resolved; Redis 7207.936 MiB and worker 150.7 MiB populated; `docker_error` empty.

## Live capture

Started tracked background session `proc_4636c596cfff` with:

```text
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python scripts/capture_load_resources.py --interval 1 --output artifacts/reports/load-resource-20260825-120757.csv
```

Fresh verification after start:

- process status: running;
- CSV exists and is growing;
- 22 samples at inspection;
- latest timestamp: 2026-08-25T12:08:29.279+07:00;
- API PID present;
- Redis and worker memory present;
- Docker error empty.

## Next step

Owner runs the desired Locust load. On the owner's explicit request, gracefully stop the tracked sampler, confirm the final row/sample count, analyze baseline/peak/delta values for the exact load window, then update the report deck and milestone evidence without deleting the raw CSV.
