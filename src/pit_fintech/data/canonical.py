"""Deterministic entity and event-order canonicalization."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pit_fintech.contracts.events import TemporalEvent

NULL_SENTINEL = "<NULL:v1>"
ENTITY_HASH_VERSION = "entity-hash-v1"
_NUMERIC_TEXT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def canonicalize_category(value: Any) -> str:
    """Normalize number-like categories and missing values before entity hashing."""

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return NULL_SENTINEL
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".15g")

    text = str(value).strip()
    if not text:
        return NULL_SENTINEL
    if _NUMERIC_TEXT.fullmatch(text):
        try:
            numeric = Decimal(text)
            if numeric == numeric.to_integral_value():
                return str(numeric.to_integral_value())
            return format(numeric.normalize(), "f")
        except InvalidOperation:
            pass
    return text


def canonical_entity_id(*values: Any, version: str = ENTITY_HASH_VERSION) -> str:
    """Hash an unambiguous canonical JSON tuple into a versioned proxy entity ID."""

    payload = {
        "values": [canonicalize_category(value) for value in values],
        "version": version,
    }
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def deduplicate_events(events: Iterable[TemporalEvent]) -> list[TemporalEvent]:
    """Drop exact duplicate transaction rows and reject conflicting duplicates."""

    by_transaction: dict[int, TemporalEvent] = {}
    for event in events:
        existing = by_transaction.get(event.transaction_id)
        if existing is None:
            by_transaction[event.transaction_id] = event
            continue
        if existing != event:
            raise ValueError(f"conflicting duplicate transaction_id={event.transaction_id}")
    return sorted(by_transaction.values(), key=lambda event: event.order_key)


def ordered_event_timestamps(events: Iterable[TemporalEvent]) -> dict[int, datetime]:
    """Create unique microsecond tie-break timestamps independent of input order."""

    canonical = deduplicate_events(events)
    by_timestamp: dict[datetime, list[TemporalEvent]] = defaultdict(list)
    for event in canonical:
        by_timestamp[event.event_timestamp].append(event)

    ordered: dict[int, datetime] = {}
    for timestamp, tied_events in by_timestamp.items():
        for rank, event in enumerate(sorted(tied_events, key=lambda item: item.transaction_id)):
            if rank >= 1_000_000:
                raise ValueError(f"too many events share timestamp {timestamp.isoformat()}")
            ordered[event.transaction_id] = timestamp + timedelta(microseconds=rank)
    return ordered
