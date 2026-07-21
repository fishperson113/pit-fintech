from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.data.canonical import deduplicate_events
from pit_fintech.features.reference import (
    assert_no_future_reads,
    canonical_feature_checksum,
    compute_feature_vectors,
)

pytestmark = pytest.mark.temporal


def _by_id(events: list[TemporalEvent]):
    return {row.transaction_id: row for row in compute_feature_vectors(events)}


def test_reference_matches_hand_calculated_vectors(
    temporal_events: list[TemporalEvent],
    expected_vectors: dict[int, dict[str, int | float]],
) -> None:
    actual = _by_id(temporal_events)
    assert actual.keys() == expected_vectors.keys()
    for transaction_id, expected in expected_vectors.items():
        assert actual[transaction_id].values == pytest.approx(expected, abs=1e-9)


def test_future_event_cannot_change_past_vectors(temporal_events: list[TemporalEvent]) -> None:
    without_future = [event for event in temporal_events if event.transaction_id != 105]
    past = _by_id(without_future)
    with_future = _by_id(temporal_events)
    assert {key: row.values for key, row in with_future.items() if key != 105} == {
        key: row.values for key, row in past.items()
    }


def test_duplicate_event_is_exactly_once(temporal_events: list[TemporalEvent]) -> None:
    with_duplicate = _by_id(temporal_events)
    without_duplicate = _by_id(deduplicate_events(temporal_events))
    assert with_duplicate == without_duplicate
    assert with_duplicate[103].values["txn_count_7d"] == 3


def test_conflicting_duplicate_is_rejected(temporal_events: list[TemporalEvent]) -> None:
    original = next(event for event in temporal_events if event.transaction_id == 102)
    conflicting = original.model_copy(update={"transaction_amount": 999.0})
    with pytest.raises(ValueError, match="conflicting duplicate"):
        compute_feature_vectors([*temporal_events, conflicting])


def test_same_timestamp_uses_transaction_id_tie_break(temporal_events: list[TemporalEvent]) -> None:
    rows = _by_id(temporal_events)
    assert rows[100].source_transaction_ids == ()
    assert rows[101].source_transaction_ids == (100,)
    assert rows[101].values["seconds_since_previous_txn"] == 0.0


def test_late_arrival_requires_knowledge_time(temporal_events: list[TemporalEvent]) -> None:
    rows = _by_id(temporal_events)
    assert 104 not in rows[102].source_transaction_ids
    assert 104 not in rows[103].source_transaction_ids
    assert 104 in rows[105].source_transaction_ids


def test_window_lower_boundary_is_inclusive(temporal_events: list[TemporalEvent]) -> None:
    rows = _by_id(temporal_events)
    assert rows[102].values["txn_count_1h"] == 2
    assert rows[103].values["txn_count_24h"] == 1
    assert rows[103].source_transaction_ids[-1] == 102


def test_query_happens_before_current_event_update(temporal_events: list[TemporalEvent]) -> None:
    for row in compute_feature_vectors(temporal_events):
        assert row.transaction_id not in row.source_transaction_ids


def test_entity_without_history_gets_explicit_defaults(
    temporal_events: list[TemporalEvent],
) -> None:
    row = _by_id(temporal_events)[200]
    assert row.source_transaction_ids == ()
    assert row.values["txn_count_7d"] == 0
    assert row.values["seconds_since_previous_txn"] == -1.0


def test_input_shuffle_does_not_change_output(temporal_events: list[TemporalEvent]) -> None:
    expected_checksum = canonical_feature_checksum(compute_feature_vectors(temporal_events))
    for seed in range(10):
        shuffled = temporal_events.copy()
        random.Random(seed).shuffle(shuffled)
        assert canonical_feature_checksum(compute_feature_vectors(shuffled)) == expected_checksum


def test_audit_has_zero_future_reads(temporal_events: list[TemporalEvent]) -> None:
    rows = compute_feature_vectors(temporal_events)
    assert_no_future_reads(rows)
    assert all(
        row.max_source_event_timestamp is None
        or (row.max_source_event_timestamp, row.max_source_transaction_id)
        < (row.cutoff_event_timestamp, row.transaction_id)
        for row in rows
    )


def test_explicit_future_injection_is_detected_by_predicate(
    temporal_events: list[TemporalEvent],
) -> None:
    future = TemporalEvent(
        transaction_id=999,
        event_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        created_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        card_entity_id="entity-a",
        transaction_amount=10_000_000,
        product_code="FUTURE",
        address_code="FUTURE",
    )
    before = _by_id(temporal_events)[103].values
    after = _by_id([*temporal_events, future])[103].values
    assert after == before
