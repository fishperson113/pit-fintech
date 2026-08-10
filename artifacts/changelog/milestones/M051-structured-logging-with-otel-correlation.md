# M051 — Structured logging with OTel trace correlation

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** Sprint 2 T7 observability — structured logs correlated with offline/online traces

## Scope

The owner asked for a structured logging setup so that when a request comes in, the log lines can be
correlated between the offline and online paths efficiently. Before this milestone the serving
process used plain stdlib `logging` with human-readable text, `structlog` was a declared hard
dependency but never used, and `LoggingInstrumentor(... set_logging_format=True)` was injecting
`trace_id=.../span_id=...` into the *message text* (unparseable). `config.log_json` / `log_level`
were not wired anywhere.

## What changed

- **New `src/pit_fintech/platform/logging_config.py`** — a structlog-based structured pipeline:
  - `_add_otel_trace_context` processor attaches the active OTel span's `trace_id` (32-hex) and
    `span_id` (16-hex) to every event — the same ids Tempo/Grafana show, so a log line links to its
    trace. OTel imported lazily; no-op when absent or no span active (same optional rule as
    `serving/telemetry.py`).
  - `_shared_processors()` = contextvars merge -> logger name/level -> ISO-UTC timestamp -> OTel
    trace context, used by both the stdlib `foreign_pre_chain` and structlog loggers, so existing
    `logging.getLogger(...).info/warning/error` call sites render through the same JSON pipeline.
  - `configure_logging(*, level=None, json=None)` installs a `structlog.stdlib.ProcessorFormatter`
    on the root `StreamHandler(sys.stdout)`, removes previously-installed handlers (idempotent),
    defaults level/json from `PIT_LOG_LEVEL` / `PIT_LOG_JSON`.
  - `bind_request_context(...)` / `clear_request_context()` bind per-request correlation fields
    (`request_id`, `transaction_id`, `entity_id`, `step`, `knowledge_step`,
    `feature_service_version`, `model_version`) into `structlog.contextvars`.
- **`src/pit_fintech/serving/app.py`**:
  - `/score` binds the request context (entity id via `derive_entity_id`) before handling and clears
    it in a `finally`.
  - `_score_request` helper: the **whole** request body now runs inside the `score` span (not just
    `score_transaction`), so error-handler and write-path log lines also carry the active
    `trace_id`/`span_id`; `online_write` stays a child span, keeping the read-before-write ordering
    visible in Tempo.
- **`src/pit_fintech/cli.py`** — `pit serving up` calls `configure_logging(level=..., json=True)`
  before starting the server, so the service ships JSON logs with request/trace correlation.
- **`src/pit_fintech/serving/telemetry.py`** — `_instrument_logging` now uses
  `set_logging_format=False` (attach attributes only, do not rewrite the message text), leaving the
  JSON rendering to the structured pipeline.
- **Tests** — new `tests/unit/test_logging_config.py`: JSON line shape (event/level/logger/
  timestamp), request-context merged into every line, and context cleared after a request. No OTel
  required.

## Design points

- structlog is already a hard dependency, so no `pyproject.toml` / ADR-004 fingerprint moves.
- Serving always emits JSON (`json=True`). Offline commands keep the console default; any command
  can opt into the same pipeline via `configure_logging()` (honoring `PIT_LOG_LEVEL`/`PIT_LOG_JSON`)
  and bind the same `entity_id`/`step` to correlate with online logs for the same entity.
- The `LoggingInstrumentor(set_logging_format=True)` message-text injection was dropped because it
  fights the JSON renderer; the processor now supplies the ids as real fields.

## Commands + results

- Agent static analysis only: `python3 -m py_compile` passes on all five changed Python files
  (`logging_config.py`, `serving/app.py`, `serving/telemetry.py`, `cli.py`,
  `tests/unit/test_logging_config.py`). The sandbox could not fetch the uv toolchain (no network),
  so `ruff`/pytest were not run by the agent.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  .\make.ps1 test-unit
  # with a trained model + Redis up:
  .\make.ps1 serve-otel
  # then hit /score and check the JSON line carries trace_id/span_id + request fields,
  # and that the log line links to the Tempo trace.
  ```

## Known gaps / next steps

- Offline (Gold/training) commands do not yet bind the correlation fields; doing so (same
  `entity_id`/`step`) is the natural follow-up for cross-path log correlation.
- No integration test asserts the OTel-trace-correlated JSON (needs OTel installed + a span);
  covered by the unit shape tests and manual verification.

## Refinement (same date) — fix the logging unit tests; add `stream` param

Owner `.\make.ps1 test-unit` reported 3 failures in `tests/unit/test_logging_config.py`
(`IndexError: list index out of range`): the fixture installed the handler writing to `sys.stdout`
at a moment when pytest's `capsys` had not yet redirected it, so the JSON went to the real stdout
and `capsys.readouterr()` returned nothing.

Fix (backward-compatible): `configure_logging` gains an explicit `stream: TextIO | None = None`
parameter, defaulting to `sys.stdout` (unchanged production behaviour); the tests pass
`stream=io.StringIO()` so the assertions are deterministic and independent of `sys.stdout` capture
timing. `tests/unit/test_logging_config.py` rewritten to write to a `StringIO` and dropped the
`capsys` dependency. Verified: `py_compile` clean, all lines <= 100. Owner re-ran the lane: `lint`
passes and `test-unit` 92 passed (3 logging tests now green).
