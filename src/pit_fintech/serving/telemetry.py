"""ADR-008 -- OpenTelemetry traces, metrics and trace-correlated logs for the serving process.

The user hosts the OTel Collector / Prometheus / Grafana / Tempo/Loki stack on a separate machine;
this module configures the **exporter side** inside the service. Traces, metrics and logs are
shipped
over OTLP/HTTP to a configurable endpoint (``ServingSettings.otel_endpoint`` or the standard
``OTEL_EXPORTER_OTLP_ENDPOINT`` env var). Logs are emitted as JSON with the active trace/span id,
so a Loki log line links to its Tempo trace.

**The OpenTelemetry packages are intentionally not project dependencies.** Adding them to
``pyproject.toml`` would move the ADR-004 component fingerprints (``pyproject.toml`` is inside both
the lakehouse and training boundaries) and force an unrelated Silver rebuild. Instead they are
installed into the serving env by hand, exactly like ``locust`` -- ``.\make.ps1 tools`` (Windows)
or ``make tools`` (POSIX) installs locust plus the four OTel packages in one shot::

    uv pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \\
        opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-logging

When the packages are absent or ``otel_enabled`` is false, :func:`configure_telemetry` returns a
no-op :class:`Telemetry` so the service runs unchanged -- observability is never a hard dependency
of the scoring path (the same rule the correctness lanes follow for Feast/Redis).

Instruments exposed for Grafana dashboards:

* ``pit_scores_total`` (counter; labels ``prediction``, ``feature_status``)
* ``pit_online_writes_total`` (counter)
* ``pit_score_latency_ms`` (histogram)
* ``pit_online_read_latency_ms`` / ``pit_online_write_latency_ms`` (histograms)
* ``pit_parity_checked_total`` / ``pit_parity_mismatches_total`` (counters; the write-path parity
  observation per ADR-009 -- ``checked`` counts parity-compared writes, ``mismatches`` the number
  of the nine history fields that disagreed; the Locust parity harness also increments
  ``pit_parity_mismatches_total`` when it runs with ``OTEL_EXPORTER_OTLP_ENDPOINT`` set)

Spans (Tempo): one ``score`` span per request plus a child ``online_write`` span, so a trace shows
the online store being read (inside scoring) before it is written -- the read-before-write invariant
made visible, not just asserted.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_LOG_PROVIDER_CONFIGURED = False


@dataclass
class Telemetry:
    """A thin facade over the OTel tracer + metric instruments, or a no-op when disabled.

    Every method is safe to call whether or not OTel is active, so the serving code never has to
    branch on ``otel_enabled`` at the call site.
    """

    enabled: bool = False
    _tracer: Any = None
    _instruments: dict[str, Any] = field(default_factory=dict)

    @contextlib.contextmanager
    def span(self, name: str, *, context: Any = None, **attributes: Any) -> Iterator[None]:
        """Open a span (no-op when disabled). Attributes are attached for Tempo/Grafana."""

        if not self.enabled or self._tracer is None:
            yield
            return
        with self._tracer.start_as_current_span(name, context=context) as span:
            for key, value in attributes.items():
                span.set_attribute(key, value)
            yield

    def record_score(self, *, prediction: int, feature_status: str, latency_ms: float) -> None:
        if not self.enabled:
            return
        labels = {"prediction": str(prediction), "feature_status": feature_status}
        self._instruments["scores_total"].add(1, labels)
        self._instruments["score_latency_ms"].record(latency_ms, labels)

    def record_online_read(self, *, latency_ms: float) -> None:
        if not self.enabled:
            return
        self._instruments["online_read_latency_ms"].record(latency_ms)

    def record_online_write(self, *, latency_ms: float, log_length: int) -> None:
        if not self.enabled:
            return
        self._instruments["online_writes_total"].add(1)
        self._instruments["online_write_latency_ms"].record(latency_ms)

    def record_parity_mismatch(self, *, count: int) -> None:
        if not self.enabled:
            return
        self._instruments["parity_mismatches_total"].add(count)

    def record_parity_check(self, *, checked: bool, mismatches: int) -> None:
        """Record one write-path parity observation (ADR-009).

        ``checked`` counts whether the write was parity-compared at all (only accepted writes are,
        older/duplicate/not-warm-started writes are not); ``mismatches`` is the number of the nine
        history fields that disagreed. A Grafana panel can alert on
        ``rate(pit_parity_mismatches_total[5m])`` rising while ``pit_parity_checked_total`` grows.
        """

        if not self.enabled:
            return
        if checked:
            self._instruments["parity_checked_total"].add(1)
        if mismatches:
            self._instruments["parity_mismatches_total"].add(mismatches)

    def instrument_fastapi(self, app: Any) -> None:
        """Attach the FastAPI ASGI instrumentation, if OTel is active and installed."""

        if not self.enabled:
            return
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        except ImportError:
            return
        FastAPIInstrumentor.instrument_app(app)


def configure_telemetry(
    *,
    service_name: str,
    endpoint: str | None,
    enabled: bool,
) -> Telemetry:
    """Build a :class:`Telemetry`. Returns a disabled one if ``enabled`` is false or OTel is absent.

    Traces and metrics are exported over OTLP/HTTP; logging is instrumented so records carry the
    trace/span id. A missing OTel install is not an error -- observability is optional (see docs).
    """

    if not enabled:
        return Telemetry(enabled=False)

    resolved_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    try:
        from opentelemetry import _logs, metrics, trace
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        # OTel not installed in this env -- run without telemetry rather than failing to start.
        import logging

        logging.getLogger(__name__).warning(
            "otel_enabled=True but the OpenTelemetry packages are not installed; "
            "telemetry is disabled for this process"
        )
        return Telemetry(enabled=False)

    resource = Resource.create({"service.name": service_name})

    span_exporter = (
        OTLPSpanExporter(endpoint=f"{resolved_endpoint}/v1/traces")
        if resolved_endpoint
        else OTLPSpanExporter()
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = (
        OTLPMetricExporter(endpoint=f"{resolved_endpoint}/v1/metrics")
        if resolved_endpoint
        else OTLPMetricExporter()
    )
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(metric_exporter)]
    )
    metrics.set_meter_provider(meter_provider)

    _configure_log_exporter(
        logs_module=_logs,
        resource=resource,
        endpoint=resolved_endpoint,
        logger_provider_class=LoggerProvider,
        log_exporter_class=OTLPLogExporter,
        log_processor_class=BatchLogRecordProcessor,
        logging_handler_class=LoggingHandler,
    )
    _instrument_logging()

    tracer = trace.get_tracer("pit_fintech.serving")
    meter = metrics.get_meter("pit_fintech.serving")
    instruments = {
        "scores_total": meter.create_counter(
            "pit_scores_total", description="Scoring requests handled"
        ),
        "online_writes_total": meter.create_counter(
            "pit_online_writes_total", description="Online write-path applies"
        ),
        "parity_checked_total": meter.create_counter(
            "pit_parity_checked_total",
            description="Write-path parity comparisons performed (ADR-009)",
        ),
        "parity_mismatches_total": meter.create_counter(
            "pit_parity_mismatches_total", description="Offline/online parity field mismatches"
        ),
        "score_latency_ms": meter.create_histogram(
            "pit_score_latency_ms", unit="ms", description="End-to-end scoring latency"
        ),
        "online_read_latency_ms": meter.create_histogram(
            "pit_online_read_latency_ms", unit="ms", description="Online feature read latency"
        ),
        "online_write_latency_ms": meter.create_histogram(
            "pit_online_write_latency_ms", unit="ms", description="Online write-path latency"
        ),
    }
    return Telemetry(enabled=True, _tracer=tracer, _instruments=instruments)


def _configure_log_exporter(
    *,
    logs_module: Any,
    resource: Any,
    endpoint: str | None,
    logger_provider_class: Any,
    log_exporter_class: Any,
    log_processor_class: Any,
    logging_handler_class: Any,
) -> None:
    """Attach one OTLP log handler to the root logger (idempotent per process).

    The module flag handles ordinary repeated configuration. The handler marker is also checked so
    a module reload or an application factory lifecycle cannot attach a second exporter to the same
    root logger.
    """

    global _LOG_PROVIDER_CONFIGURED
    root_logger = logging.getLogger()
    if _LOG_PROVIDER_CONFIGURED or any(
        getattr(handler, "_pit_otel_log_handler", False) for handler in root_logger.handlers
    ):
        _LOG_PROVIDER_CONFIGURED = True
        return
    log_exporter = (
        log_exporter_class(endpoint=f"{endpoint}/v1/logs") if endpoint else log_exporter_class()
    )
    logger_provider = logger_provider_class(resource=resource)
    logger_provider.add_log_record_processor(log_processor_class(log_exporter))
    logs_module.set_logger_provider(logger_provider)
    handler = logging_handler_class(logger_provider=logger_provider)
    handler._pit_otel_log_handler = True
    root_logger.addHandler(handler)
    _LOG_PROVIDER_CONFIGURED = True


def _instrument_logging() -> None:
    """Inject the active trace/span id into log records, if the instrumentation is installed.

    ``set_logging_format=False`` (the default) only attaches ``otelTraceID``/``otelSpanID``
    attributes to each record; it does **not** rewrite the message text. The structured-logging
    pipeline (`platform.logging_config._add_otel_trace_context`) is what renders ``trace_id`` /
    ``span_id`` as JSON fields, so the two do not fight over the message format.
    """

    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
    except ImportError:
        return
    LoggingInstrumentor().instrument(
        set_logging_format=False,
        enable_log_auto_instrumentation=False,
    )
