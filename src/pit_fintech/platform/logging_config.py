"""Structured logging with OTel trace correlation.

The serving process (and any CLI command that opts in) gets JSON logs that carry the active
OpenTelemetry trace/span ids, so a Grafana log line links to its Tempo trace and back. Request
context (``transaction_id``, ``entity_id``, ``step``, ...) is bound with
:func:`structlog.contextvars.bind_contextvars` per request and merged into every log line emitted
while that request is on the stack -- see ``serving/app.py`` ``/score``.

Design points:

* **structlog is a hard dependency** (``pyproject.toml`` ``dependencies``), so this module is always
  importable; no optional group or ADR-004 fingerprint moves.
* **OTel stays optional.** ``_add_otel_trace_context`` imports ``opentelemetry`` lazily and no-ops
  when it is absent or no span is active, exactly like ``serving/telemetry.py``. Structured logs
  still work without OTel; they just carry no ``trace_id``/``span_id``.
* **stdlib loggers keep working.** The existing code logs with ``logging.getLogger(...)``; the
  ``structlog.stdlib.ProcessorFormatter`` is installed on the root handler with a
  ``foreign_pre_chain``, so plain ``logger.info(...)`` calls render through the same structured
  pipeline as structlog loggers.
* ``level``/``json`` default to ``PIT_LOG_LEVEL`` / ``PIT_LOG_JSON`` (``config.Settings``). The
  serving CLI passes ``json=True`` explicitly so a service ships machine-readable logs by default;
  offline commands stay human-readable unless ``PIT_LOG_JSON=true``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog
from structlog import contextvars

from pit_fintech.config import get_settings


def _add_otel_trace_context(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Attach ``trace_id``/``span_id`` of the active OTel span, if one is live (no-op otherwise).

    ``trace_id`` is the 128-bit id formatted as 32 hex chars, ``span_id`` the 64-bit id as 16 hex
    chars -- the same values the Tempo/Grafana UI shows, so a log line and its trace line up.
    """

    try:
        from opentelemetry import trace
    except Exception:  # OTel not installed -- observability is optional
        return event_dict
    try:
        span_context = trace.get_current_span().get_span_context()
    except Exception:  # pragma: no cover - defensive; never break logging on telemetry hiccups
        return event_dict
    if span_context.is_valid:
        event_dict.setdefault("trace_id", format(span_context.trace_id, "032x"))
        event_dict.setdefault("span_id", format(span_context.span_id, "016x"))
    return event_dict


def _shared_processors() -> list[Any]:
    """Processors used both by foreign (stdlib) records and structlog loggers.

    Order matters: contextvars first so bound request fields are available to every later
    processor, then logger name / level / timestamp, then the OTel trace context.
    """

    return [
        contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_otel_trace_context,
    ]


def configure_logging(
    *,
    level: str | None = None,
    json: bool | None = None,
    stream: TextIO | None = None,
) -> None:
    """Install a structlog-backed formatter on the root logger. Idempotent.

    Args:
        level: ``logging`` level name. Defaults to ``PIT_LOG_LEVEL``
            (``config.Settings.log_level``).
        json: ``True`` for JSON lines, ``False`` for a colored console. Defaults to
            ``PIT_LOG_JSON`` (``config.Settings.log_json``).
        stream: Where the handler writes. Defaults to ``sys.stdout``. Pass an explicit stream in
            tests to assert on the rendered output deterministically, instead of depending on
            where ``sys.stdout`` points when the handler is constructed.

    Every existing ``logging.getLogger(...).info/warning/error`` call site starts emitting through
    this pipeline once it runs. Handlers previously installed by this function are removed first,
    so repeated calls (e.g. ``pit serving up`` after the CLI callback) do not stack handlers.
    """

    if level is None or json is None:
        settings = get_settings()
        if level is None:
            level = settings.log_level
        if json is None:
            json = settings.log_json

    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=_shared_processors(),
    )

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing.formatter, structlog.stdlib.ProcessorFormatter):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def bind_request_context(
    *,
    request_id: str,
    transaction_id: str,
    entity_id: str,
    step: int,
    knowledge_step: int | None,
    feature_service_version: str,
    model_version: str,
) -> None:
    """Bind per-request correlation fields into ``structlog.contextvars``.

    Every log line emitted while a request is on the stack carries these fields -- the online half
    of the offline/online correlation story (pair them with the same ``entity_id``/``step`` in
    offline Gold/training logs). Call :func:`clear_request_context` when the request finishes.
    """

    contextvars.bind_contextvars(
        request_id=request_id,
        transaction_id=transaction_id,
        entity_id=entity_id,
        step=step,
        knowledge_step=knowledge_step,
        feature_service_version=feature_service_version,
        model_version=model_version,
    )


def clear_request_context() -> None:
    """Drop the per-request contextvars (call in a ``finally`` after handling one request)."""

    contextvars.clear_contextvars()
