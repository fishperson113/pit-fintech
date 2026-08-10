# M046 — /score reads the event-log store; OpenTelemetry exporter (ADR-008)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; no repo-env / service / collector run)
- **Sprint / task:** Sprint 2, T7 + observability; completes [ADR-008](../../docs/adr/008-serving-owns-the-online-write-path.md)

## Scope

Two follow-ups to M045: (1) switch the `/score` **read** path to the serving-owned event-log store
so online read, online write and the offline oracle share one independent state; (2) add an
OpenTelemetry exporter so the user's external Prometheus/Grafana/Tempo stack can observe scores,
online/offline state and the read-before-write ordering.

## What changed

### Read path -> event-log store
- `serving/online_state.py`: added `read_window_state` (returns the nine features **and** a
  `present` flag, so a cold entity with no log key is told apart from one whose events have aged out
  of the widest window). `read_window_features` now delegates to it.
- `serving/feature_provider.py`: new `WindowStateFeatureProvider` (name `window_state`) computes the
  history vector live from the event log at `request_step`; live reads are never stale
  (`staleness_steps=0`, no watermark); a missing log key is `MISSING` with contract defaults
  (guide s9.4). `build_feature_provider` gained the `window_state` kind. The `FeatureProvider` ABC
  docstring was rewritten: ADR-008 makes read-time computation the design and reverses the
  materialize-only "providers must not compute" rule; `RedisFeatureProvider` is retained for the
  bulk warm-start path.
- `serving/app.py`: `build_scoring_context` builds the `window_state` provider (store backend is
  still Redis, validated as before).

### OpenTelemetry exporter
- `serving/telemetry.py`: `configure_telemetry(service_name, endpoint, enabled) -> Telemetry`.
  Traces + metrics exported over OTLP/HTTP to `endpoint` (or `OTEL_EXPORTER_OTLP_ENDPOINT`);
  `LoggingInstrumentor` correlates logs to the active trace; `Telemetry.instrument_fastapi` attaches
  the ASGI middleware. Instruments: `pit_scores_total`, `pit_online_writes_total`,
  `pit_parity_mismatches_total`, and `pit_score_latency_ms` / `pit_online_read_latency_ms` /
  `pit_online_write_latency_ms`. `Telemetry` is a null-object when disabled or when OTel is not
  installed, so every call site is unconditional.
- `serving/app.py`: `create_app` configures telemetry, instruments FastAPI, wraps scoring in a
  `score` span and the write in a child `online_write` span, and records score / read / write
  metrics.
- `serving/app.py: ServingSettings` gained `otel_enabled` / `otel_service_name` / `otel_endpoint`;
  `cli.py: pit serving up` gained `--otel/--no-otel` and `--otel-endpoint`.
- `scripts/locust_parity.py`: best-effort exports the parity mismatch count to the same collector
  (no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set), so a Grafana panel can alert on parity drift.

## Key decision — OTel is not a project dependency

Adding the OpenTelemetry packages to `pyproject.toml` would move both ADR-004 component fingerprints
(`pyproject.toml` is inside the lakehouse and training boundaries) and force an unrelated Silver
rebuild. They are therefore installed by hand into the serving env, exactly like `locust`:

```
uv pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-logging
```

When the packages are absent or `otel_enabled` is false, telemetry silently no-ops and the service
runs unchanged — observability is never a hard dependency of the scoring path.

## Commands + results

- Agent, sandbox: `ruff check` clean on all of `src`, `tests`, `scripts`; `ast` parses the changed
  serving modules.
- **Not run** (owner gates): the FastAPI service, OTLP export against the external collector, and the
  Grafana dashboards.

### Owner gate commands

```powershell
.\make.ps1 lint
.\make.ps1 test-unit
.\make.ps1 redis-up
# install OTel into the serving env, then start with telemetry on:
uv pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-logging
uv run pit serving up --otel --otel-endpoint http://<collector-host>:4318
# fire load + parity (separate shell); set the endpoint so parity mismatches export too:
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://<collector-host>:4318"
locust -f scripts/locust_parity.py --host http://127.0.0.1:8000
```

## Known gaps / next steps

- The online read span is implicit (the read happens inside `score_transaction`); a dedicated
  `online_read` child span would need telemetry threaded into `scoring.py`. Deferred.
- No Grafana dashboard JSON is shipped here (the stack is hosted externally by the owner); the
  instrument + span names above are what a dashboard binds to.
- Metric export is OTLP/HTTP only; if the collector expects gRPC, swap the exporter package. The
  `serving` group already ships `prometheus-client`, so a direct `/metrics` scrape is an alternative
  the owner can wire if preferred.
- Agent static analysis only; nothing committed, so no commit hash yet.
