# M107 — Redis client-pool reuse for scoring latency

- Date: 2026-08-25
- Status: implemented and unit-verified; live load rerun pending API restart/owner execution.

## Finding

The async write refactor removed worker-result waiting, but the latest live dashboard still showed scoring average 150.63 ms across 1,406 requests with zero errors. A single live request reported scoring total 11.94 ms, including 9.51 ms feature retrieval and 2.40 ms inference. Redis itself reported `GET` at 11.90 microseconds per command and no rejected connections/evictions. `read_online_features` was creating a new `redis.Redis` client/connection pool on every request, which amplified connection setup and contention under burst load.

## Change

- Added `_cached_redis_client` with an LRU cache keyed by Redis endpoint and timeout configuration.
- `_redis_client` now reuses the thread-safe redis-py client/connection pool for repeated reads and writes from the same process.
- Added `tests/unit/test_redis_client_pool.py` to lock the reuse behavior.

## Verification

- TDD RED: focused test failed because two `_redis_client` calls returned different objects.
- TDD GREEN: focused test passed: `1 passed`.
- Full unit lane passed: `124 passed` (one existing FastAPI/httpx deprecation warning).
- Ruff check passed for touched files.
- `git diff --check` passed.
- Standalone live read-path probe after the code change: 30 reads, p50 `1.52 ms`, p95 `1.80 ms`; first connection warm-up was `199.75 ms`.
- Existing API process and Locust process were not interrupted. The running API predates this cache change, so its dashboard counters are not evidence for the fix.

## Next step

Restart the host API after the current load run, then execute a clean load run and compare scoring p95 from a reset API process. Do not flush Redis; the worker/online state is already healthy.
