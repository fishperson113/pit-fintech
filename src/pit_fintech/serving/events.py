"""ADR-010 -- the event-based write path: publish to a Redis Stream, wait for the worker result.

`/score` is a **publisher**, never a store mutator. It publishes a score event to a Redis Stream
(`pit:{feature_service_version}:events`) and waits for the dedicated `pit-online-worker` container
to apply the event (compute the fresh pre-decision feature state under the optimistic lock, update
the online store, append the Event History) and publish a result the request polls. This guarantees
a request never scores on a stale or current-inclusive version: the worker is a single ordered
consumer, so by the time a request's result is ready, every prior event for the entity has been
applied and the result carries the **pre-decision** feature vector.

``redis`` is an optional dependency group; it is imported inside function bodies.
"""

from __future__ import annotations

import json
import time
from typing import Any, Final

#: Stream carrying score events. One stream per feature service version so a version bump isolates
#: traffic; ``XADD`` with an auto id preserves insertion order, which a single consumer reads in
#: order (global order => per-entity order).
SCORE_EVENT_STREAM_TEMPLATE: Final = "pit:{feature_service_version}:events"
#: Consumer group. One group, one consumer => strictly ordered processing.
CONSUMER_GROUP: Final = "pit-online-worker"
#: Consumer name for the single ordered consumer.
CONSUMER_NAME: Final = "pit-online-worker-1"
#: Result key the worker writes the pre-decision feature vector to, polled by the request.
SCORE_RESULT_KEY_TEMPLATE: Final = "pit:{feature_service_version}:result:{request_id}"
#: Result TTL (seconds): long enough for `/score` to poll, short enough to not leak keys.
SCORE_RESULT_TTL_SECONDS: Final = 60
#: How long `/score` waits for the worker before giving up (``503 online_store_timeout``).
WAIT_TIMEOUT_SECONDS: Final = 5.0
#: Poll interval while waiting.
WAIT_POLL_INTERVAL_SECONDS: Final = 0.01


def score_event_stream_key(*, feature_service_version: str) -> str:
    return SCORE_EVENT_STREAM_TEMPLATE.format(feature_service_version=feature_service_version)


def score_result_key(*, feature_service_version: str, request_id: str) -> str:
    return SCORE_RESULT_KEY_TEMPLATE.format(
        feature_service_version=feature_service_version, request_id=request_id
    )


def publish_score_event(
    *,
    store: Any,
    feature_service_version: str,
    request_id: str,
    transaction_id: str,
    entity_id: str,
    step: int,
    knowledge_step: int | None,
    transaction_type: str,
    amount: Any,
) -> str:
    """``XADD`` one score event to the stream. Returns the message id.

    The amount is serialized as a decimal string so the worker's ``Decimal(amount)`` is exact.
    """

    from pit_fintech.serving.online_state import _redis_client

    client = _redis_client(store)
    fields = {
        "request_id": request_id,
        "transaction_id": transaction_id,
        "entity_id": entity_id,
        "step": str(step),
        "knowledge_step": str(knowledge_step if knowledge_step is not None else step),
        "transaction_type": transaction_type,
        "amount": str(amount),
        "feature_service_version": feature_service_version,
    }
    try:
        from opentelemetry.propagate import inject

        carrier: dict[str, str] = {}
        inject(carrier)
        if carrier.get("traceparent"):
            fields["traceparent"] = carrier["traceparent"]
    except Exception:  # OTel is optional; the worker still processes the event without propagation.
        pass
    return client.xadd(
        score_event_stream_key(feature_service_version=feature_service_version),
        fields,
    )


def wait_for_score_result(
    *,
    store: Any,
    feature_service_version: str,
    request_id: str,
    timeout_seconds: float = WAIT_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Poll the result key until the worker publishes it or the timeout elapses.

    Returns ``None`` on timeout -- the caller maps that to ``503 online_store_timeout``.
    """

    from pit_fintech.serving.online_state import _redis_client

    client = _redis_client(store)
    key = score_result_key(feature_service_version=feature_service_version, request_id=request_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = client.get(key)
        if payload is not None:
            return json.loads(payload)
        time.sleep(WAIT_POLL_INTERVAL_SECONDS)
    return None
