# M106 — async post-score online write path

- Date: 2026-08-25
- Status: implemented and unit-verified; live host API restart/demo verification pending owner action.

## Scope and acceptance

Refactor `/score` so online worker lag does not turn an already-computed prediction into `503 online_store_timeout`.
The synchronous request path is now `read materialized online state -> validate/version-check -> score model`.
The Redis Stream event is published after scoring and the route does not poll the worker result.

Acceptance:

- scoring returns when feature retrieval/model inference completes even if the worker is slow;
- publish order is score before enqueue;
- enqueue failure is exposed as `online_write_status=failed`, not as a scoring error;
- successful enqueue returns `online_write_status=queued` and the Redis stream message id;
- worker keeps global stream ordering, optimistic locking, idempotency, event history and async parity responsibilities.

## Changes

- `src/pit_fintech/serving/app.py`: removed worker-result wait from `/score`; scoring reads through the configured FeatureProvider, then publishes the post-score event; added queued/failed write status and event id to the response.
- `src/pit_fintech/serving/schemas.py`: added `online_write_status` and `online_write_event_id` response lineage fields.
- `src/pit_fintech/serving/events.py`: removed the obsolete 5-second polling API and timeout constants; result keys remain short-lived diagnostic artifacts for worker observability.
- `src/pit_fintech/serving/worker.py`, `online_state.py`, `scoring.py`, `compose.yaml`: updated semantics/comments to describe score-first and non-blocking write behavior.
- `tests/unit/test_serving_async_write.py`: regression test verifies HTTP 200, score-before-publish order, and queued write metadata even when no worker result is awaited.

## Verification

- TDD RED: the new regression test first failed with HTTP 503 because the route called `wait_for_score_result` before scoring.
- TDD GREEN: focused test passed: `1 passed`.
- Full unit lane passed: `123 passed` (one existing FastAPI/httpx deprecation warning).
- Ruff check passed for all touched Python files.
- `git diff --check` passed.
- Live Uvicorn process was not running during verification; owner must restart the host API and rerun `demo-score`/load test to verify the deployed process uses the new code.

## Known gaps and next step

- The single Redis Stream worker still serializes writes globally; write lag should be monitored separately from scoring latency.
- Async write means a later request can observe state before an earlier queued event is applied; existing worker ordering/idempotency guards remain in place, but a future high-concurrency correctness lane should explicitly measure read-after-enqueue lag per entity.
- Restart the host API before live verification; do not flush Redis again.
