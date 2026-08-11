# M063 — OTLP logs and cross-process trace correlation

- **Datetime:** 2026-08-11
- **Status:** implemented and locally verified; VPS live ingestion pending owner restart/check
- **Sprint / task:** Sprint 3 observability — export structured logs to Loki and link worker spans to API traces

## What changed

- `serving/telemetry.py` now configures an OTLP/HTTP log exporter at `<endpoint>/v1/logs` using the
  already hand-installed `opentelemetry-exporter-otlp-proto-http` package. It attaches one
  `LoggingHandler` to the root logger and remains idempotent/no-op when OTel is unavailable. The
  handler now carries an explicit `_pit_otel_log_handler` marker in addition to the module guard, so
  application-factory/module-reload lifecycles cannot attach a second OTLP exporter to the same
  root logger.
- `serving/events.py` injects the active W3C `traceparent` into each Redis Stream score event when
  OTel is active.
- `serving/worker.py` extracts `traceparent`, creates an `online_write` span with the API request as
  parent, binds request/entity/step/knowledge context to worker JSON logs, and clears context after
  each message.
- Worker CLI configures telemetry as `pit-fintech-online-worker` when `PIT_OTEL_ENDPOINT` is set.
- `compose.yaml` passes `PIT_OTEL_ENDPOINT` to both API and worker containers.
- VPS Collector/Loki configs were completed separately: Collector logs pipeline uses Loki native
  OTLP endpoint `http://loki:3100/otlp`.

- The duplicate-export root cause was identified and fixed: `LoggingInstrumentor.instrument()` defaults
  to `enable_log_auto_instrumentation=True`, which installs an SDK `LoggingHandler`; the service also
  installed its explicit OTLP `LoggingHandler`. The two handlers exported every record twice. The
  service now passes `enable_log_auto_instrumentation=False` and keeps only its explicit handler.
- A local diagnostic after the fix reports exactly two root handlers: one JSON stdout
  `ProcessorFormatter` and one marked OTLP `LoggingHandler`; repeated telemetry configuration does not
  add another handler.

## Verification

- Ruff check: **All checks passed** on telemetry, worker, events and CLI.
- Ruff format: **4 files already formatted**.
- `py_compile`: passed.
- Logging/write-path unit subset: **13 passed**.
- Installed package inspection confirmed `OTLPLogExporter`, `LoggerProvider`,
  `BatchLogRecordProcessor` and `LoggingHandler` are available in the locked serving environment.
- VPS-side Collector/Loki/Compose configs validated independently.

## Owner live activation

Set the endpoint in the PIT application's `.env` or Compose environment:

```env
PIT_OTEL_ENDPOINT=http://<vps-tailscale-ip>:4318
```

Then recreate both API and worker so the new code and endpoint are loaded:

```powershell
.\make.ps1 tools
# host process path:
.\make.ps1 serve-otel
# Compose path:
 docker compose up -d --build --force-recreate api pit-online-worker
```

Expected final path:

```text
API score span -> Redis traceparent -> worker online_write child span -> Tempo
API/worker JSON logs + trace_id/span_id -> OTLP Collector -> Loki
API /metrics -> Prometheus
```

Live VPS arrival/query verification remains owner-side because this session does not operate the VPS
containers directly.
