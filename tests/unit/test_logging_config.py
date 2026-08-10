"""Structured logging pipeline: JSON rendering, request-context correlation, idempotency.

Covers `platform/logging_config.py`. The serving process ships JSON logs whose lines carry
OTel ``trace_id``/``span_id`` (when tracing) plus the per-request correlation fields bound by
:func:`~pit_fintech.platform.logging_config.bind_request_context`. These tests lock the JSON shape
and the request-context merge; the OTel half is exercised only when OTel is installed, so nothing
here requires it.

The handler writes to an explicit ``io.StringIO`` (``configure_logging(..., stream=...)``) rather
than ``sys.stdout``/capsys, so the assertions are deterministic and independent of where
``sys.stdout`` happens to point when the handler is constructed.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from pit_fintech.platform import logging_config

_REQUEST_CONTEXT = {
    "request_id": "req-1",
    "transaction_id": "tx-1",
    "entity_id": "C1001",
    "step": 5,
    "knowledge_step": 5,
    "feature_service_version": "paysim-fraud-scoring-v2",
    "model_version": "run-1",
}


@pytest.fixture
def structured_logger() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    """Install the JSON pipeline writing to a StringIO; return the logger and the buffer."""
    stream = io.StringIO()
    logging_config.configure_logging(level="INFO", json=True, stream=stream)
    yield logging.getLogger("pit_fintech.tests.structured"), stream
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter):
            root.removeHandler(handler)


def _last_record(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue().strip().splitlines()[-1])


def test_json_line_carries_event_level_logger_and_timestamp(structured_logger) -> None:
    logger, stream = structured_logger
    logger.info("hello %s", "world")
    record = _last_record(stream)
    assert record["event"] == "hello world"
    assert record["level"] == "info"
    assert record["logger"] == "pit_fintech.tests.structured"
    assert "timestamp" in record


def test_request_context_is_merged_into_every_line(structured_logger) -> None:
    logger, stream = structured_logger
    logging_config.bind_request_context(**_REQUEST_CONTEXT)
    try:
        logger.warning("stale_features for entity")
        record = _last_record(stream)
        for key, value in _REQUEST_CONTEXT.items():
            assert record[key] == value, f"missing/incorrect {key}"
    finally:
        logging_config.clear_request_context()


def test_context_is_cleared_after_request(structured_logger) -> None:
    logger, stream = structured_logger
    logging_config.bind_request_context(**_REQUEST_CONTEXT)
    logging_config.clear_request_context()
    logger.info("next request")
    record = _last_record(stream)
    for key in _REQUEST_CONTEXT:
        assert key not in record, f"context leaked: {key}"
