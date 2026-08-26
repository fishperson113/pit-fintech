"""ADR-010 -- the `pit-online-worker`: a single ordered consumer of the score-event stream.

Runs in its own container (`pit-online-worker` in compose.yaml), in its own process. It reads the
Redis Stream in insertion order (one consumer in the `pit-online-worker` group => global order =>
per-entity order), applies each event to the online store under the optimistic lock
(`online_state.apply_score_event`), and publishes a short-lived write result for diagnostics and
backward-compatible consumers. FastAPI `/score` reads and scores first, then publishes without
waiting for this worker result.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from typing import Any

from pit_fintech.serving.events import (
    CONSUMER_GROUP,
    CONSUMER_NAME,
    SCORE_RESULT_TTL_SECONDS,
    score_event_stream_key,
    score_result_key,
)

logger = logging.getLogger(__name__)


def _decode_message(fields: dict[Any, Any]) -> dict[str, str]:
    """Redis stream fields come back as bytes; decode to str."""

    def _dec(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    return {_dec(key): _dec(value) for key, value in fields.items()}


def run_worker(
    *,
    store: Any,
    feature_service_version: str,
    batch_size: int = 32,
    block_ms: int = 1000,
    telemetry: Any | None = None,
    artifact_root: Path | None = None,
) -> None:
    """Consume score events in order, apply each, publish a diagnostic result. Runs forever."""

    import redis as redis_py

    from pit_fintech.serving.online_state import _redis_client, apply_score_event
    from pit_fintech.serving.parity_consumer import AsyncParityConsumer

    client = _redis_client(store)
    stream = score_event_stream_key(feature_service_version=feature_service_version)

    # Ensure the consumer group exists (idempotent; mkstream creates the stream on first event).
    try:
        client.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
    except redis_py.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info(
        "pit-online-worker listening on %s (group=%s consumer=%s)",
        stream,
        CONSUMER_GROUP,
        CONSUMER_NAME,
    )
    parity_consumer = AsyncParityConsumer(
        store=store,
        artifact_root=artifact_root or Path("artifacts"),
        telemetry=telemetry,
    )
    parity_consumer.start()

    while True:
        try:
            response = client.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={stream: ">"},
                count=batch_size,
                block=block_ms,
            )
        except Exception as exc:  # pragma: no cover - keep the worker alive across Redis blips
            logger.warning("xreadgroup failed: %s", exc)
            time.sleep(1.0)
            continue

        if not response:
            continue

        for _stream, entries in response:
            for message_id, raw_fields in entries:
                fields = _decode_message(raw_fields)
                request_id = fields["request_id"]
                entity_id = fields["entity_id"]
                step = int(fields["step"])
                knowledge_step = int(fields["knowledge_step"])
                from pit_fintech.platform.logging_config import (
                    bind_request_context,
                    clear_request_context,
                )

                bind_request_context(
                    request_id=request_id,
                    transaction_id=fields["transaction_id"],
                    entity_id=entity_id,
                    step=step,
                    knowledge_step=knowledge_step,
                    feature_service_version=feature_service_version,
                    model_version="pit-online-worker",
                )
                parent_context = None
                if fields.get("traceparent"):
                    try:
                        from opentelemetry.propagate import extract

                        parent_context = extract({"traceparent": fields["traceparent"]})
                    except Exception:  # OTel is optional; keep processing without trace linkage.
                        parent_context = None
                write_span = (
                    telemetry.span(
                        "online_write",
                        context=parent_context,
                        request_id=request_id,
                        entity_id=entity_id,
                        step=step,
                        knowledge_step=knowledge_step,
                    )
                    if telemetry is not None
                    else nullcontext()
                )
                try:
                    with write_span:
                        result = apply_score_event(
                            store=store,
                            request_id=request_id,
                            transaction_id=fields["transaction_id"],
                            event_id=fields.get("event_id"),
                            entity_id=entity_id,
                            step=step,
                            knowledge_step=knowledge_step,
                            transaction_type=fields["transaction_type"],
                            amount=Decimal(fields["amount"]),
                            origin_entity_id=fields.get("origin_entity_id", ""),
                        )
                    logger.info(
                        "applied event_id=%s transaction_id=%s entity=%s step=%s "
                        "status=%s outcome=%s",
                        fields.get("event_id", "-"),
                        fields["transaction_id"],
                        entity_id,
                        step,
                        result["status"],
                        result.get("outcome", "-"),
                    )
                    parity_consumer.trigger(event_id=fields.get("event_id"))
                except Exception as exc:  # pragma: no cover - never hang the waiting request
                    logger.exception(
                        "apply_score_event failed for message=%s request_id=%s: %s",
                        message_id,
                        request_id,
                        exc,
                    )
                    try:
                        client.set(
                            score_result_key(
                                feature_service_version=feature_service_version,
                                request_id=request_id,
                            ),
                            json.dumps({"status": "error", "error": str(exc)}),
                            ex=SCORE_RESULT_TTL_SECONDS,
                        )
                    except Exception:  # pragma: no cover - best-effort error surfacing
                        logger.exception("could not write error result for %s", request_id)
                finally:
                    clear_request_context()
                    try:
                        client.xack(stream, CONSUMER_GROUP, message_id)
                    except Exception:  # pragma: no cover - ack failure must not stop the loop
                        logger.exception("xack failed for message %s", message_id)
