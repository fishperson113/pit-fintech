from __future__ import annotations

from datetime import UTC, datetime

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.data.canonical import (
    NULL_SENTINEL,
    canonical_entity_id,
    canonicalize_category,
    ordered_event_timestamps,
)


def test_number_like_categories_have_one_representation() -> None:
    assert canonicalize_category(123) == "123"
    assert canonicalize_category(123.0) == "123"
    assert canonicalize_category("123.0") == "123"
    assert canonicalize_category(None) == NULL_SENTINEL
    assert canonicalize_category("") == NULL_SENTINEL


def test_entity_hash_is_unambiguous_and_versioned() -> None:
    first = canonical_entity_id(1001, 111.0, None, "226")
    equivalent = canonical_entity_id("1001.0", "111", "", 226)
    different = canonical_entity_id(1001, 111, None, 227)
    assert first == equivalent
    assert first != different
    assert first == "dc4b0d531239b85689de4297af6ef6cbc4c585e32384e5ea1514e0ff74466494"


def test_ordered_timestamp_tie_break_is_input_order_independent() -> None:
    common = {
        "event_timestamp": datetime(2024, 1, 1, tzinfo=UTC),
        "created_timestamp": datetime(2024, 1, 1, tzinfo=UTC),
        "card_entity_id": "entity",
        "transaction_amount": 1.0,
        "product_code": "P",
        "address_code": "A",
    }
    later_id = TemporalEvent(transaction_id=2, **common)
    earlier_id = TemporalEvent(transaction_id=1, **common)
    ordered = ordered_event_timestamps([later_id, earlier_id])
    assert ordered[1] == common["event_timestamp"]
    assert ordered[2] > ordered[1]
