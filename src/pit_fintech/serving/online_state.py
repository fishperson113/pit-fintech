"""ADR-009 -- the serving-owned online write path: aggregate transition + two-path parity.

The online store is a **precomputed aggregate** for fast business reads (materialized from offline
Gold, `materialization/records.py: ONLINE_KEY_TEMPLATE`). Serving reads that aggregate
(`serving/feature_provider.py: RedisFeatureProvider`). This module owns the **write path**: when a
scored event arrives, it transitions the entity's aggregate to the post-event state that includes
the new event, under the optimistic lock, and then **verifies offline/online parity** at that write
(ADR-009).

**Two-path fan-out (ADR-009).** After scoring, the event fans out to BOTH paths:

1. **Online** -- appended to the per-entity ``winlog`` and the nine window features are recomputed
   in Python (`compute_window_features`) into the post-event aggregate at step ``t``.
2. **Offline** -- appended to the append-only **Event History** (the offline-visible record) and the
   same post-event state is computed by the **offline DuckDB engine**
   (`features/build_offline.py: paysim_post_event_state_sql`), the same SQL that builds
   ``gold.post_event_state_updates``.

Parity is the comparison of the two engines (online / Python vs offline / DuckDB SQL) on the same
event set; the pure-Python oracle (`features/paysim_reference.py`) stays the project's correctness
ground truth and is what verifies the DuckDB engine offline, not something duplicated on the serving
path.

Parity is checked at the write path, not at the materialize step, because materialization is a
read-only copy -- a copy is always equal to its source, so comparing there is vacuous (ADR-007's
rut). The write path is the one place online state is produced by serving logic, so it is the only
place online can genuinely diverge from offline.

The transition keeps a compact per-entity event log (``winlog``) as its working state so that
window eviction and the knowledge-time predicate are exact; the log is an implementation detail of
the write path, never the serving read path. The stored aggregate is the post-event state at the
newest event's step: ``post_event_state(entity, step=t) == pre_decision_history(cutoff=t+1)``
(`features/build_offline.py: GOLD_SHIFT_RELATION`), so a subsequent in-order read at step ``t+1``
gets exactly the vector that request needs.

The write path runs in the ``pit-online-worker`` (ADR-010), not in ``/score``. The worker's
:func:`apply_score_event` captures the **pre-decision** feature vector (the state after every prior
event, before this one) so the served vector equals the offline ``pre_decision_features`` of the
request -- a request never scores on a stale or current-inclusive version.

``redis`` is an optional dependency group; it is imported inside function bodies, never at module
scope.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from pit_fintech.features.paysim_reference import PAYSIM_WINDOW_STEPS
from pit_fintech.features.paysim_specs import (
    PAYSIM_HISTORY_FEATURE_NAMES,
    PAYSIM_RECENCY_SENTINEL_STEPS,
)
from pit_fintech.materialization.materializer import (
    OnlineStoreConfig,
    _record_from_payload,
    _record_payload,
    read_online_features,
    read_watermark,
)
from pit_fintech.materialization.records import OnlineFeatureRecord, online_record_key
from pit_fintech.platform.lifecycle_logging import log_lifecycle

logger = logging.getLogger(__name__)

#: Per-entity event-log key. A distinct ``winlog`` prefix so it never collides with the materialized
#: aggregate records (`materialization/records.py: ONLINE_KEY_TEMPLATE`). This log is the write
#: path's working state, not a serving read path (ADR-009).
WINLOG_KEY_TEMPLATE: Final = "pit:{feature_service_version}:winlog:{entity}:{entity_id}"

#: Money is accumulated at this precision, matching the offline `PAYSIM_AMOUNT_DECIMAL_TYPE`.
_MONEY_QUANTUM: Final = Decimal("0.01")


@dataclass(frozen=True, slots=True, kw_only=True)
class LoggedEvent:
    """One event in an entity's online history log.

    ``knowledge_step`` is carried so the knowledge-time predicate (ADR-005 decision 5) applies at
    write/read time -- it is what makes a late-arriving correction visible to later cutoffs but not
    to earlier ones. On clean PaySim data ``knowledge_step == step`` and the predicate is a no-op.

    ``origin_entity_id`` (the sender, PaySim ``nameOrig``) is carried so the fan-in feature
    ``pit_distinct_senders_*`` (ADR-011) can be recomputed online exactly as the offline engine
    computes it from ``silver.paysim_transactions.origin_entity_id``. It is the reason the winlog
    serialization moved from a 3-tuple to a 4-tuple.
    """

    step: int
    knowledge_step: int
    amount: Decimal
    origin_entity_id: str


def winlog_key(*, store: OnlineStoreConfig, entity_id: str) -> str:
    """Build the per-entity event-log key; rejects a ``:`` in any component (injection guard)."""

    for component in (store.feature_service_version, store.entity, entity_id):
        if ":" in component:
            raise ValueError(f"winlog key component must not contain ':': {component!r}")
    return WINLOG_KEY_TEMPLATE.format(
        feature_service_version=store.feature_service_version,
        entity=store.entity,
        entity_id=entity_id,
    )


def compute_window_features(
    *,
    events: list[LoggedEvent],
    cutoff_step: int,
    cutoff_knowledge_step: int,
) -> dict[str, int | float]:
    """Compute the eight ADR-011 v3 history fields from an event log, at one cutoff.

    Independent re-implementation of ``paysim_reference.compute_paysim_feature_row``'s history half:
    eligibility ``e.step < cutoff_step AND e.knowledge_step <= cutoff_knowledge_step``; each window
    ``w`` keeps ``e.step >= cutoff_step - w``. Counts and distinct-sender counts are exact; amounts
    are summed as ``Decimal`` and cast to float once, matching the offline ``DECIMAL(18,2)`` sum
    bit-for-bit within range. Recency is ``cutoff_step - max(prior step)`` within the widest window,
    or ``PAYSIM_RECENCY_SENTINEL_STEPS`` when there is no eligible prior event there.

    Post-event state at step ``t`` is the history **inclusive of** event ``t``, which this function
    yields by passing ``cutoff_step = t + 1`` (``GOLD_SHIFT_RELATION``).
    """

    eligible = [
        event
        for event in events
        if event.step < cutoff_step and event.knowledge_step <= cutoff_knowledge_step
    ]
    count_by_window: dict[int, int] = {}
    amount_by_window: dict[int, float] = {}
    senders_by_window: dict[int, int] = {}
    for window_steps in PAYSIM_WINDOW_STEPS:
        lower_bound = cutoff_step - window_steps
        window = [event for event in eligible if event.step >= lower_bound]
        prior_amount = sum((event.amount for event in window), start=Decimal("0")).quantize(
            _MONEY_QUANTUM
        )
        count_by_window[window_steps] = len(window)
        amount_by_window[window_steps] = float(prior_amount)
        senders_by_window[window_steps] = len({event.origin_entity_id for event in window})

    widest_window = max(PAYSIM_WINDOW_STEPS)
    recency_steps = [event.step for event in eligible if event.step >= cutoff_step - widest_window]
    steps_since_last = (
        cutoff_step - max(recency_steps) if recency_steps else PAYSIM_RECENCY_SENTINEL_STEPS
    )

    values: dict[str, int | float] = {
        "pit_prior_count_1h": count_by_window[1],
        "pit_prior_amount_1h": amount_by_window[1],
        "pit_prior_count_24h": count_by_window[24],
        "pit_prior_amount_24h": amount_by_window[24],
        "pit_prior_amount_168h": amount_by_window[168],
        "pit_distinct_senders_24h": senders_by_window[24],
        "pit_distinct_senders_168h": senders_by_window[168],
        "pit_steps_since_last_event": steps_since_last,
    }
    # Emit in the frozen contract order (assert alignment so a spec reorder is caught here).
    ordered = {name: values[name] for name in PAYSIM_HISTORY_FEATURE_NAMES}
    if set(ordered) != set(values):
        raise RuntimeError("computed history fields do not match PAYSIM_HISTORY_FEATURE_NAMES")
    return ordered


def recompute_pre_decision_features(
    *,
    events: list[LoggedEvent],
    request_step: int,
    request_knowledge_step: int,
) -> dict[str, int | float]:
    """Recompute history immediately before an arbitrary request cutoff.

    An out-of-order request cannot use the latest post-event aggregate because that aggregate may
    include events after the request. Using the request step as the exclusive cutoff preserves the
    strict PIT predicate.
    """

    return compute_window_features(
        events=events,
        cutoff_step=request_step,
        cutoff_knowledge_step=request_knowledge_step,
    )


def latest_prior_event_step(*, events: list[LoggedEvent], request_step: int) -> int | None:
    """Return the latest event step included by a strict pre-decision cutoff."""

    prior_steps = [event.step for event in events if event.step < request_step]
    return max(prior_steps) if prior_steps else None


def count_parity_mismatches(online: dict[str, int | float], offline: dict[str, int | float]) -> int:
    """Count the nine history fields that disagree, with the locked comparison rules.

    Integers (counts and history flags) must be exactly equal; the three amount fields are compared
    with the locked float tolerance ``1e-6`` (AGENTS.md s9). A mismatch is never resolved by
    widening the tolerance (guide s8.4).
    """

    mismatches = 0
    for name in PAYSIM_HISTORY_FEATURE_NAMES:
        online_value = online[name]
        offline_value = offline[name]
        if "_amount_" in name:
            if abs(float(online_value) - float(offline_value)) > 1e-6:
                mismatches += 1
        elif online_value != offline_value:
            mismatches += 1
    return mismatches


def offline_post_event_reference(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    step: int,
    knowledge_step: int,
) -> dict[str, int | float]:
    """The independent offline reference for post-event state at ``step`` (ADR-009).

    Reads the entity's winlog (the serving-owned state) and computes the post-event history with the
    **offline DuckDB engine** (``features/build_offline.py: paysim_post_event_state_sql``) -- the
    same SQL implementation that builds ``gold.post_event_state_updates``, not a pure-Python oracle
    duplicated on the serving path. Comparing :func:`compute_window_features` (online / Python)
    against this DuckDB reference is what catches implementation drift between the two engines.
    """

    events = _read_winlog(store=store, entity_id=entity_id)
    return _duckdb_reference_over(
        events=events,
        entity_id=entity_id,
        step=step,
        knowledge_step=knowledge_step,
    )


def apply_score_event(
    *,
    store: OnlineStoreConfig,
    request_id: str,
    entity_id: str,
    step: int,
    knowledge_step: int | None,
    transaction_type: str,
    amount: Decimal,
    origin_entity_id: str,
    transaction_id: str | None = None,
    event_id: str | None = None,
) -> dict:
    """ADR-010 worker-side write: capture the pre-decision vector, apply the event, publish result.

    Runs in the ``pit-online-worker`` process (never in ``/score``). Under ``WATCH``/``MULTI``/
    ``EXEC`` it:

    1. reads the entity's winlog + aggregate;
    2. captures the **pre-decision** feature vector -- the aggregate state after every prior event
       but before this one (or contract defaults for a cold entity). This is what the request scores
       on, so it is never stale and never current-inclusive;
    3. applies the deterministic guards (older write, duplicate, not warm-started) and, when the
       write is refused, publishes a result carrying the refusal (state unchanged);
    4. on an accepted write, appends/evicts the winlog, recomputes the post-event aggregate in
       Python, and writes log + aggregate + the result key in one transaction;
    5. appends the Event History (offline path) and returns the result dict.

    The offline DuckDB engine is not run here -- parity is verified asynchronously by
    :func:`reconcile_parity` (ADR-009). The result key is retained as a short-lived diagnostic
    artifact; scoring no longer polls it.
    """

    import json as _json

    import redis as redis_py

    from pit_fintech.features.paysim_specs import (
        PAYSIM_FEATURE_DEFINITION_VERSION,
        paysim_feature_contract_checksum,
        paysim_step_to_timestamp,
    )
    from pit_fintech.materialization.materializer import _contract_defaults
    from pit_fintech.serving.events import SCORE_RESULT_TTL_SECONDS, score_result_key

    started = time.perf_counter()
    resolved_knowledge = knowledge_step if knowledge_step is not None else step
    client = _redis_client(store)
    log_key = winlog_key(store=store, entity_id=entity_id)
    record_key = online_record_key(
        feature_service_version=store.feature_service_version,
        entity=store.entity,
        entity_id=entity_id,
    )
    result_key = score_result_key(
        feature_service_version=store.feature_service_version, request_id=request_id
    )
    contract_checksum = paysim_feature_contract_checksum()
    watermark = read_watermark(store=store)
    watermark_step = watermark[0] if watermark is not None else step

    def publish_result(
        *,
        status: str,
        pre_values: dict,
        pre_step: int | None,
        pre_status: str,
        pre_timestamp,
        outcome: str,
        log_length: int,
        detail: str,
    ) -> dict:
        payload = {
            "status": status,
            "feature_values": pre_values,
            "feature_step": pre_step,
            "feature_status": pre_status,
            "feature_timestamp": pre_timestamp.isoformat() if pre_timestamp is not None else None,
            "post_event_step": step,
            "outcome": outcome,
            "feature_service_version": store.feature_service_version,
            "feature_definition_version": PAYSIM_FEATURE_DEFINITION_VERSION,
            "feature_contract_checksum": contract_checksum,
            "materialization_watermark_step": watermark_step,
            "materialization_watermark": paysim_step_to_timestamp(watermark_step).isoformat(),
            # Freshness is the step distance from the request step to the pre-decision feature step
            # (the same definition as read_online_features): 0 when the stored aggregate is current,
            # > 0 when the served vector is behind the request step.
            "staleness_steps": max(0, step - pre_step) if pre_step is not None else None,
            "log_length": log_length,
            "write_latency_ms": round((time.perf_counter() - started) * 1000.0, 6),
            "detail": detail,
        }
        client.set(
            result_key,
            _json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ex=SCORE_RESULT_TTL_SECONDS,
        )
        return payload

    for _attempt in range(store.max_retries + 1):
        client.watch(log_key, record_key)
        events = _decode_log(client.get(log_key))
        record_payload = client.get(record_key)
        stored = _record_from_payload(record_payload) if record_payload is not None else None

        # Pre-decision vector: state before this event (every prior event already applied).
        if stored is not None:
            pre_values = dict(stored.feature_values)
            pre_step = stored.feature_step
            pre_status = "fresh"
            pre_timestamp = stored.feature_timestamp
        else:
            pre_values = _contract_defaults()
            pre_step = None
            pre_status = "missing"
            pre_timestamp = None

        if stored is not None and not events:
            client.unwatch()
            return publish_result(
                status="not_warm_started",
                pre_values=pre_values,
                pre_step=pre_step,
                pre_status=pre_status,
                pre_timestamp=pre_timestamp,
                outcome="not_warm_started",
                log_length=0,
                detail=(
                    f"entity {entity_id!r} has a materialized aggregate (feature_step "
                    f"{stored.feature_step}) but no serving event log; a live write would drop its "
                    "history. Seed the entity's event log (warm-start) before live writes; online "
                    "state left unchanged."
                ),
            )
        if stored is not None and step < stored.feature_step:
            client.unwatch()
            # Do not return the newer stored aggregate: it contains future history for this
            # request. Recompute the strict pre-decision vector from the serving winlog at the
            # request cutoff and align metadata with that cutoff.
            pre_values = recompute_pre_decision_features(
                events=events,
                request_step=step,
                request_knowledge_step=resolved_knowledge,
            )
            pre_step = latest_prior_event_step(events=events, request_step=step)
            pre_status = "fresh" if pre_step is not None else "missing"
            pre_timestamp = paysim_step_to_timestamp(pre_step) if pre_step is not None else None
            return publish_result(
                status="rejected_older",
                pre_values=pre_values,
                pre_step=pre_step,
                pre_status=pre_status,
                pre_timestamp=pre_timestamp,
                outcome="rejected_older",
                log_length=len(events),
                detail=(
                    f"incoming step {step} is older than stored feature_step "
                    f"{stored.feature_step}; state unchanged"
                ),
            )
        is_duplicate = any(
            event.step == step
            and event.knowledge_step == resolved_knowledge
            and event.amount == amount
            for event in events
        )
        if is_duplicate:
            client.unwatch()
            # A duplicate request must be scored on the same pre-decision vector as the original
            # event. The stored aggregate is post-event state at ``step`` and would be
            # current-inclusive if returned here. Recompute strictly before this event, excluding
            # all same-step and future events from the winlog.
            pre_values = recompute_pre_decision_features(
                events=events,
                request_step=step,
                request_knowledge_step=resolved_knowledge,
            )
            pre_step = latest_prior_event_step(events=events, request_step=step)
            pre_status = "fresh" if pre_step is not None else "missing"
            pre_timestamp = paysim_step_to_timestamp(pre_step) if pre_step is not None else None
            return publish_result(
                status="noop_identical",
                pre_values=pre_values,
                pre_step=pre_step,
                pre_status=pre_status,
                pre_timestamp=pre_timestamp,
                outcome="noop_identical",
                log_length=len(events),
                detail=(
                    f"duplicate event (step {step}, knowledge_step {resolved_knowledge}); "
                    "idempotent no-op"
                ),
            )

        # Accepted write: append, evict, recompute the post-event aggregate at step t.
        events.append(
            LoggedEvent(
                step=step,
                knowledge_step=resolved_knowledge,
                amount=amount,
                origin_entity_id=origin_entity_id,
            )
        )
        events.sort(key=lambda event: (event.step, event.knowledge_step))
        events = _evict(events, current_step=step)
        online_values = compute_window_features(
            events=events,
            cutoff_step=step + 1,
            cutoff_knowledge_step=resolved_knowledge,
        )
        record = OnlineFeatureRecord(
            entity_id=entity_id,
            entity=store.entity,
            feature_service_version=store.feature_service_version,
            feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
            feature_contract_checksum=contract_checksum,
            feature_values=online_values,
            feature_step=step,
            feature_timestamp=paysim_step_to_timestamp(step),
            feature_knowledge_step=resolved_knowledge,
            materialization_watermark_step=watermark_step,
            materialization_watermark=paysim_step_to_timestamp(watermark_step),
            source_row_number=0,
            source_checksum="",
            gold_post_event_version=stored.gold_post_event_version if stored is not None else 0,
            materialization_run_id="",
            written_at=datetime.now(UTC),
        )
        result_payload = _json.dumps(
            {
                "status": "done",
                "feature_values": pre_values,
                "feature_step": pre_step,
                "feature_status": pre_status,
                "feature_timestamp": (
                    pre_timestamp.isoformat() if pre_timestamp is not None else None
                ),
                "post_event_step": step,
                "outcome": "written",
                "feature_service_version": store.feature_service_version,
                "feature_definition_version": PAYSIM_FEATURE_DEFINITION_VERSION,
                "feature_contract_checksum": contract_checksum,
                "materialization_watermark_step": watermark_step,
                "materialization_watermark": paysim_step_to_timestamp(watermark_step).isoformat(),
                "staleness_steps": max(0, step - pre_step) if pre_step is not None else None,
                "log_length": len(events),
                "write_latency_ms": round((time.perf_counter() - started) * 1000.0, 6),
                "detail": (
                    f"pre-decision features at step {step} captured and post-event aggregate "
                    "written; parity verified asynchronously by reconcile_parity"
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        pipeline = client.pipeline(transaction=True)
        pipeline.multi()
        pipeline.set(log_key, _encode_log(events))
        pipeline.set(record_key, _record_payload(record))
        pipeline.set(result_key, result_payload, ex=SCORE_RESULT_TTL_SECONDS)
        try:
            pipeline.execute()
        except redis_py.WatchError:
            # Another writer touched the log or the aggregate between WATCH and EXEC; re-read and
            # re-decide (the optimistic lock ADR-010 requires).
            time.sleep(0)
            continue

        # Two-path fan-out (ADR-009): append the event to the offline-visible Event History.
        # Best-effort -- a failure must not fail the already-computed result.
        try:
            append_event_history(
                entity_id=entity_id,
                step=step,
                knowledge_step=resolved_knowledge,
                transaction_type=transaction_type,
                amount=amount,
                origin_entity_id=origin_entity_id,
                request_id=request_id,
                transaction_id=transaction_id,
                event_id=event_id,
            )
        except Exception as exc:  # pragma: no cover - defensive; never break the write path
            import logging

            logging.getLogger(__name__).warning(
                "Event History append failed for entity_id=%s step=%s: %s",
                entity_id,
                step,
                exc,
            )
        return _json.loads(result_payload)
    raise RuntimeError(
        f"apply_score_event exhausted {store.max_retries + 1} optimistic-lock attempts "
        f"for {entity_id!r}"
    )


def reset_online_log(*, store: OnlineStoreConfig) -> int:
    """Delete every event-log key in this service version's namespace; return how many were removed.

    Scoped to the ``pit:<fsv>:winlog:`` prefix via ``SCAN`` -- never ``FLUSHDB`` and never another
    service version's keyspace (mirrors ``materializer.reset_online_store``).
    """

    client = _redis_client(store)
    prefix = f"pit:{store.feature_service_version}:winlog:"
    removed = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=prefix + "*", count=1000)
        if keys:
            removed += client.delete(*keys)
        if cursor == 0:
            break
    return removed


# --------------------------------------------------------------------------------------------
# Redis plumbing
# --------------------------------------------------------------------------------------------


def _redis_client(store: OnlineStoreConfig):
    """Build a redis-py client (optional dependency; imported here)."""

    import redis as redis_py

    return redis_py.Redis(
        host=store.host,
        port=store.port,
        db=store.db,
        decode_responses=True,
        socket_connect_timeout=store.connect_timeout_seconds,
        socket_timeout=store.operation_timeout_seconds,
    )


def _read_winlog(*, store: OnlineStoreConfig, entity_id: str) -> list[LoggedEvent]:
    client = _redis_client(store)
    return _decode_log(client.get(winlog_key(store=store, entity_id=entity_id)))


def _decode_log(payload: str | None) -> list[LoggedEvent]:
    if payload is None:
        return []
    data = json.loads(payload)
    # ADR-011 bumped the winlog element from a 3-tuple to a 4-tuple carrying the sender id. The v3
    # rollout resets the winlog namespace and re-warm-starts, so only 4-tuples are expected here; a
    # stale 3-tuple is a rollout error, not something to silently pad.
    return [
        LoggedEvent(
            step=int(step),
            knowledge_step=int(knowledge_step),
            amount=Decimal(str(amount)),
            origin_entity_id=str(origin_entity_id),
        )
        for step, knowledge_step, amount, origin_entity_id in data["events"]
    ]


def _encode_log(events: list[LoggedEvent]) -> str:
    return json.dumps(
        {
            "events": [
                [event.step, event.knowledge_step, str(event.amount), event.origin_entity_id]
                for event in events
            ]
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _evict(events: list[LoggedEvent], *, current_step: int) -> list[LoggedEvent]:
    """Drop events that no future cutoff (``>= current_step``) could read.

    The widest window is ``max(PAYSIM_WINDOW_STEPS)``; a future cutoff at step ``c >= current_step``
    reaches back to ``c - w >= current_step - w``. Keeping ``step > current_step - w`` loses nothing
    a later request could need, and bounds the log to the last ``w`` hours.
    """

    horizon = current_step - max(PAYSIM_WINDOW_STEPS)
    return [event for event in events if event.step > horizon]


def _events_to_duckdb_rows(events: list[LoggedEvent], *, entity_id: str) -> list[dict]:
    """Map winlog events onto the DuckDB relation columns ``paysim_post_event_state_sql`` expects.

    History counts every prior event to a destination regardless of transaction type or destination
    kind (the SQL ``scoped_history`` CTE), so the placeholder ``transaction_type`` does not affect
    the computed values -- it exists only to satisfy the SQL projection. ``origin_entity_id`` is the
    real sender though: ``pit_distinct_senders_*`` counts distinct senders (ADR-011), so it must be
    the value the winlog recorded. Amounts are passed as decimal strings so
    ``CAST(amount AS DECIMAL(18,2))`` is exact.
    """

    return [
        {
            "destination_entity_id": entity_id,
            "source_row_number": index + 1,
            "step": event.step,
            "knowledge_step": event.knowledge_step,
            "transaction_type": "CASH_OUT",
            "origin_entity_id": event.origin_entity_id,
            "amount": str(event.amount),
        }
        for index, event in enumerate(events)
    ]


def _duckdb_reference_over(
    *,
    events: list[LoggedEvent],
    entity_id: str,
    step: int,
    knowledge_step: int,
) -> dict[str, int | float]:
    """Offline DuckDB reference for post-event state at ``step`` over a given event list (ADR-009).

    Runs the real offline SQL engine (``paysim_post_event_state_sql``) over the event list and
    returns the nine history fields under their contract names. This is the same implementation that
    builds ``gold.post_event_state_updates``; comparing the online Python computation against it is
    the meaningful online-vs-offline parity check. ``transaction_type`` is not used by the history
    aggregation, so a placeholder is safe.
    """

    import duckdb
    import pyarrow as pa

    from pit_fintech.features.build_offline import (
        POST_EVENT_TO_CONTRACT_FIELD,
        paysim_post_event_state_sql,
    )

    rows = _events_to_duckdb_rows(events, entity_id=entity_id)
    if not rows:
        raise RuntimeError(f"offline reference requires at least one event for {entity_id!r}")
    # DuckDB replacement scans do not accept a raw list-of-dicts; register a pyarrow Table
    # (pyarrow is a core dependency, so no new group/ADR-004 fingerprint moves).
    table = pa.Table.from_pylist(rows)
    connection = duckdb.connect()
    try:
        connection.register("evt", table)
        cursor = connection.execute(
            f"""
            SELECT * FROM (
                {paysim_post_event_state_sql("evt")}
            )
            WHERE step = ? AND knowledge_step = ?
            """,
            [step, knowledge_step],
        )
        column_names = [description[0] for description in cursor.description]
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(
                f"offline reference produced no row for {entity_id!r} at step {step} "
                f"knowledge_step {knowledge_step}"
            )
        data = dict(zip(column_names, row, strict=True))
    finally:
        connection.close()
    return {
        contract_name: data[post_name]
        for post_name, contract_name in POST_EVENT_TO_CONTRACT_FIELD.items()
    }


def append_event_history(
    *,
    entity_id: str,
    step: int,
    knowledge_step: int,
    transaction_type: str,
    amount: Decimal,
    origin_entity_id: str,
    source_row_number: int | None = None,
    request_id: str | None = None,
    transaction_id: str | None = None,
    event_id: str | None = None,
) -> int:
    """Append one served event to the offline-visible **Event History** (ADR-009 two-path fan-out).

    The Event History is the offline-visible, append-only record of what the online path observed;
    the offline DuckDB path consumes it and eventually lands it into Gold Delta. Stored as one JSON
    line per event under ``<artifact_root>/event_history/served_events.jsonl`` (gitignored runtime
    artifact). The write is best-effort from the caller's perspective -- the online winlog/aggregate
    are the source of truth, and an Event History append failure is logged, never a scored-request
    failure.
    """

    from pit_fintech.config import get_settings

    path = get_settings().artifact_root / "event_history" / "served_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if source_row_number is None:
        source_row_number = _next_event_history_row_number(path)
    if event_id is None:
        from pit_fintech.contracts.served_events import served_event_id

        event_id = served_event_id(
            destination_entity_id=entity_id,
            step=step,
            knowledge_step=knowledge_step,
            transaction_type=transaction_type,
            amount=amount,
        )
    record = {
        "event_id": event_id,
        "source_row_number": source_row_number,
        "destination_entity_id": entity_id,
        "origin_entity_id": origin_entity_id,
        "step": step,
        "knowledge_step": knowledge_step,
        "transaction_type": transaction_type,
        "amount": str(amount),
        "served_at": datetime.now(UTC).isoformat(),
    }
    if request_id is not None:
        record["request_id"] = request_id
    if transaction_id is not None:
        record["transaction_id"] = transaction_id
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    return source_row_number


def _next_event_history_row_number(path: Path) -> int:
    """Synthesize the next append-only source row number by counting existing lines."""

    if not path.exists():
        return 1
    with open(path, encoding="utf-8") as handle:
        return sum(1 for _ in handle) + 1


@dataclass(frozen=True, slots=True, kw_only=True)
class ParityReconcileResult:
    """Outcome of one asynchronous offline/online parity reconcile (ADR-009 as amended).

    The write path never runs the offline engine; :func:`reconcile_parity` does, over the Event
    History, and compares each entity's online aggregate against the offline DuckDB reference.
    ``field_mismatches`` counts the nine history fields that disagreed (a single entity can
    contribute more than one); ``missing_online`` lists entities in the Event History with no online
    aggregate yet; ``passed`` is ``field_mismatches == 0 and not missing_online``.
    """

    checked_entities: int
    field_mismatches: int
    missing_online: tuple[str, ...]
    mismatched_entities: dict[str, int]
    passed: bool
    details: tuple[str, ...]


def reconcile_parity(
    *,
    store: OnlineStoreConfig,
    artifact_root: Path,
    event_history_path: Path | None = None,
) -> ParityReconcileResult:
    """Compare online aggregates against the offline DuckDB reference over the same winlog.

    ADR-009 (as amended): the write path is fast/non-blocking; offline/online parity is verified
    here, asynchronously. The Event History names which entities had live writes; for each, the
    online aggregate (maintained by the worker) is compared against the offline DuckDB engine
    computed over the **entity's winlog** -- the same event set the online aggregate was built
    from -- at the aggregate's stored step. Using the winlog (not the Event History) is essential:
    the Event History only records live writes, so it would under-count a warm-started entity's
    history and the check would falsely fail.

    ``event_history_path`` defaults to ``<artifact_root>/event_history/served_events.jsonl``.
    """

    path = event_history_path or (artifact_root / "event_history" / "served_events.jsonl")
    event_ids: list[str] = []
    log_lifecycle(
        logger,
        "offline.parity.reconcile.started",
        event_history_path=path,
        feature_service_version=store.feature_service_version,
    )
    if not path.exists():
        result = ParityReconcileResult(
            checked_entities=0,
            field_mismatches=0,
            missing_online=(),
            mismatched_entities={},
            passed=True,
            # Trailing comma makes this a one-element tuple, not a string (a string would be
            # iterated character-by-character by the CLI's `for detail in result.details`).
            details=(f"no event history at {path}",),
        )
        log_lifecycle(
            logger,
            "offline.parity.reconcile.completed",
            checked_entities=result.checked_entities,
            event_id_first=event_ids[0] if event_ids else None,
            event_id_last=event_ids[-1] if event_ids else None,
            field_mismatches=result.field_mismatches,
            passed=result.passed,
            status="no_input",
        )
        return result

    # Group the served events by entity, to know which entities had live writes.
    by_entity: dict[str, list[LoggedEvent]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("event_id"):
                event_ids.append(str(record["event_id"]))
            entity_id = record["destination_entity_id"]
            # These events are used only to group by entity (which entities had live writes); the
            # offline reference is recomputed from the winlog below, not from this list, so a record
            # written before the ADR-011 origin field is tolerated with an empty sender here.
            by_entity.setdefault(entity_id, []).append(
                LoggedEvent(
                    step=int(record["step"]),
                    knowledge_step=int(record["knowledge_step"]),
                    amount=Decimal(str(record["amount"])),
                    origin_entity_id=str(record.get("origin_entity_id", "")),
                )
            )

    missing_online: list[str] = []
    mismatched: dict[str, int] = {}
    details: list[str] = []
    total_mismatches = 0

    for entity_id in by_entity:
        read = read_online_features(store=store, entity_id=entity_id, request_step=1)
        if read.record is None:
            missing_online.append(entity_id)
            details.append(f"{entity_id}: online aggregate missing")
            continue
        record = read.record
        # The offline reference must use the SAME event set the online aggregate was built from --
        # the entity's winlog (warm-started from Gold, then advanced by the worker). The Event
        # History only records live writes and would under-count history. Read the winlog from
        # Redis and compute the DuckDB post-event state over it.
        winlog_events = _read_winlog(store=store, entity_id=entity_id)
        if not winlog_events:
            missing_online.append(entity_id)
            details.append(f"{entity_id}: no winlog to reconcile against")
            continue
        try:
            offline = _duckdb_reference_over(
                events=winlog_events,
                entity_id=entity_id,
                step=record.feature_step,
                knowledge_step=record.feature_knowledge_step,
            )
        except Exception as exc:  # pragma: no cover - defensive; report as an entity-level mismatch
            mismatched[entity_id] = len(PAYSIM_HISTORY_FEATURE_NAMES)
            total_mismatches += len(PAYSIM_HISTORY_FEATURE_NAMES)
            details.append(f"{entity_id}@{record.feature_step}: offline reference failed: {exc}")
            continue
        mismatches = count_parity_mismatches(online=record.feature_values, offline=offline)
        if mismatches:
            mismatched[entity_id] = mismatches
            total_mismatches += mismatches
            details.append(
                f"{entity_id}@{record.feature_step}: {mismatches} history field(s) disagree "
                "between online aggregate and offline DuckDB reference"
            )

    passed = total_mismatches == 0 and not missing_online
    result = ParityReconcileResult(
        checked_entities=len(by_entity),
        field_mismatches=total_mismatches,
        missing_online=tuple(missing_online),
        mismatched_entities=mismatched,
        passed=passed,
        details=tuple(details),
    )
    log_lifecycle(
        logger,
        "offline.parity.reconcile.completed",
        checked_entities=result.checked_entities,
        event_id_first=event_ids[0] if event_ids else None,
        event_id_last=event_ids[-1] if event_ids else None,
        field_mismatches=result.field_mismatches,
        missing_online=len(result.missing_online),
        passed=result.passed,
        status="success" if result.passed else "mismatch",
    )
    return result
