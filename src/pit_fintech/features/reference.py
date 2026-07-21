"""Readable, independent point-in-time oracle for correctness tests.

This implementation deliberately favors explicit temporal predicates over speed. Full
dataset optimization belongs in a separate DuckDB implementation and must match this
oracle before it is accepted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import timedelta

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.contracts.features import ComputedFeatureRow
from pit_fintech.data.canonical import deduplicate_events
from pit_fintech.features.specs import DAY, FEATURE_DEFINITION_VERSION, HOUR, WEEK


def eligible_history(cutoff: TemporalEvent, events: Iterable[TemporalEvent]) -> list[TemporalEvent]:
    """Return only source events that were both earlier and already knowable."""

    return [
        source
        for source in events
        if source.card_entity_id == cutoff.card_entity_id
        and source.order_key < cutoff.order_key
        and source.created_timestamp <= cutoff.created_timestamp
    ]


def _within_window(
    history: Iterable[TemporalEvent], cutoff: TemporalEvent, window_seconds: int
) -> list[TemporalEvent]:
    lower_bound = cutoff.event_timestamp - timedelta(seconds=window_seconds)
    return [source for source in history if source.event_timestamp >= lower_bound]


def _amount_stats(history: list[TemporalEvent]) -> tuple[float, float, float]:
    if not history:
        return (0.0, 0.0, 0.0)
    amounts = [source.transaction_amount for source in history]
    return (float(sum(amounts)), float(sum(amounts) / len(amounts)), float(max(amounts)))


def compute_feature_row(
    cutoff: TemporalEvent, canonical_events: list[TemporalEvent]
) -> ComputedFeatureRow:
    """Compute the pre-decision vector for one cutoff."""

    history = sorted(eligible_history(cutoff, canonical_events), key=lambda event: event.order_key)
    history_1h = _within_window(history, cutoff, HOUR)
    history_24h = _within_window(history, cutoff, DAY)
    history_7d = _within_window(history, cutoff, WEEK)
    sum_24h, mean_24h, max_24h = _amount_stats(history_24h)
    sum_7d, mean_7d, max_7d = _amount_stats(history_7d)

    previous = history[-1] if history else None
    seconds_since_previous = (
        (cutoff.event_timestamp - previous.event_timestamp).total_seconds()
        if previous is not None
        else -1.0
    )
    ratio = cutoff.transaction_amount / mean_24h if mean_24h > 0 else 0.0

    values: dict[str, int | float] = {
        "txn_count_1h": len(history_1h),
        "txn_count_24h": len(history_24h),
        "txn_count_7d": len(history_7d),
        "amount_sum_24h": sum_24h,
        "amount_mean_24h": mean_24h,
        "amount_max_24h": max_24h,
        "amount_sum_7d": sum_7d,
        "amount_mean_7d": mean_7d,
        "amount_max_7d": max_7d,
        "seconds_since_previous_txn": float(seconds_since_previous),
        "distinct_products_7d": len({source.product_code for source in history_7d}),
        "distinct_addresses_7d": len({source.address_code for source in history_7d}),
        "current_amount_to_mean_24h": float(ratio),
    }

    return ComputedFeatureRow(
        transaction_id=cutoff.transaction_id,
        card_entity_id=cutoff.card_entity_id,
        cutoff_event_timestamp=cutoff.event_timestamp,
        cutoff_created_timestamp=cutoff.created_timestamp,
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        values=values,
        source_transaction_ids=tuple(source.transaction_id for source in history),
        max_source_event_timestamp=previous.event_timestamp if previous else None,
        max_source_transaction_id=previous.transaction_id if previous else None,
    )


def compute_feature_vectors(events: Iterable[TemporalEvent]) -> list[ComputedFeatureRow]:
    canonical_events = deduplicate_events(events)
    return [compute_feature_row(cutoff, canonical_events) for cutoff in canonical_events]


def assert_no_future_reads(rows: Iterable[ComputedFeatureRow]) -> None:
    """Fail if audit lineage shows a source at or after its decision cutoff."""

    for row in rows:
        if row.max_source_event_timestamp is None:
            continue
        max_source_key = (row.max_source_event_timestamp, row.max_source_transaction_id)
        cutoff_key = (row.cutoff_event_timestamp, row.transaction_id)
        if max_source_key >= cutoff_key:
            message = (
                f"future read for transaction {row.transaction_id}: "
                f"{max_source_key} >= {cutoff_key}"
            )
            raise AssertionError(message)


def canonical_feature_checksum(rows: Iterable[ComputedFeatureRow]) -> str:
    """Checksum ordered, canonical JSON rather than storage-specific bytes."""

    payload = [
        row.model_dump(mode="json")
        for row in sorted(rows, key=lambda item: (item.cutoff_event_timestamp, item.transaction_id))
    ]
    serialized = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
