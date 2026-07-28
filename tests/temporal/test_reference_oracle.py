from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.data.canonical import deduplicate_events
from pit_fintech.features import reference
from pit_fintech.features.reference import (
    assert_no_future_reads,
    canonical_feature_checksum,
    compute_feature_vectors,
)

pytestmark = pytest.mark.temporal


def _by_id(events: list[TemporalEvent]):
    return {row.transaction_id: row for row in compute_feature_vectors(events)}


BOUNDARY_ENTITY = "entity-boundary"
BOUNDARY_OTHER_ENTITY = "entity-boundary-other"
BOUNDARY_CUTOFF = datetime(2024, 3, 2, tzinfo=UTC)
KNOWLEDGE_CUTOFF = datetime(2024, 3, 9, tzinfo=UTC)


def _boundary_event(
    transaction_id: int,
    event_timestamp: datetime,
    transaction_amount: float,
    *,
    card_entity_id: str = BOUNDARY_ENTITY,
    created_timestamp: datetime | None = None,
) -> TemporalEvent:
    return TemporalEvent(
        transaction_id=transaction_id,
        event_timestamp=event_timestamp,
        created_timestamp=event_timestamp if created_timestamp is None else created_timestamp,
        card_entity_id=card_entity_id,
        transaction_amount=transaction_amount,
        product_code="P1",
        address_code="A",
    )


def _boundary_events() -> list[TemporalEvent]:
    """Pin four record classes to the `order_key <` boundary of one target row."""

    return [
        # exactly on the cutoff: `<` must reject it, `<=` would accept it
        _boundary_event(500, BOUNDARY_CUTOFF, 100.0),
        # one second earlier: accepted by both predicates, so an empty result is never a pass
        _boundary_event(501, BOUNDARY_CUTOFF - timedelta(seconds=1), 70.0),
        # eight days earlier: eligible history, but outside 1h/24h/7d
        _boundary_event(502, BOUNDARY_CUTOFF - timedelta(days=8), 5000.0),
        # same instant, different entity: never eligible
        _boundary_event(503, BOUNDARY_CUTOFF, 9000.0, card_entity_id=BOUNDARY_OTHER_ENTITY),
    ]


def _knowledge_boundary_events() -> list[TemporalEvent]:
    """Pin the `created_timestamp <=` boundary with one arrival knowable exactly at cutoff."""

    return [
        _boundary_event(600, KNOWLEDGE_CUTOFF, 100.0),
        # becomes knowable exactly at the cutoff: `<=` must accept it
        _boundary_event(
            601,
            KNOWLEDGE_CUTOFF - timedelta(minutes=30),
            40.0,
            created_timestamp=KNOWLEDGE_CUTOFF,
        ),
        # knowable one second too late: unreadable at decision time
        _boundary_event(
            602,
            KNOWLEDGE_CUTOFF - timedelta(minutes=20),
            8000.0,
            created_timestamp=KNOWLEDGE_CUTOFF + timedelta(seconds=1),
        ),
    ]


def _eligible_history_self_inclusive(
    cutoff: TemporalEvent, events: list[TemporalEvent]
) -> list[TemporalEvent]:
    """Bug simulation for tests only: `order_key <` weakened to `<=`."""

    return [
        source
        for source in events
        if source.card_entity_id == cutoff.card_entity_id
        and source.order_key <= cutoff.order_key
        and source.created_timestamp <= cutoff.created_timestamp
    ]


def _eligible_history_knowledge_strict(
    cutoff: TemporalEvent, events: list[TemporalEvent]
) -> list[TemporalEvent]:
    """Bug simulation for tests only: `created_timestamp <=` tightened to `<`."""

    return [
        source
        for source in events
        if source.card_entity_id == cutoff.card_entity_id
        and source.order_key < cutoff.order_key
        and source.created_timestamp < cutoff.created_timestamp
    ]


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


def test_source_at_exact_cutoff_order_key_is_excluded() -> None:
    """Invariant 1 (no future reads): the row sitting exactly on the cutoff is not history."""

    row = _by_id(_boundary_events())[500]
    assert row.source_transaction_ids == (502, 501)
    assert row.values["txn_count_1h"] == 1
    assert row.values["txn_count_24h"] == 1
    assert row.values["amount_sum_24h"] == 70.0
    assert row.values["amount_mean_24h"] == 70.0
    assert row.values["amount_max_24h"] == 70.0
    assert row.values["seconds_since_previous_txn"] == 1.0


def test_same_instant_other_entity_is_never_eligible() -> None:
    """Invariant 1: entity identity, not a shared instant, decides eligibility."""

    rows = _by_id(_boundary_events())
    assert 503 not in rows[500].source_transaction_ids
    assert rows[503].source_transaction_ids == ()
    assert rows[503].values["txn_count_24h"] == 0
    assert rows[503].values["amount_sum_24h"] == 0.0
    assert rows[503].values["seconds_since_previous_txn"] == -1.0


def test_out_of_window_source_stays_in_history_only() -> None:
    """Window membership is narrower than eligibility: an old row aggregates to nothing."""

    row = _by_id(_boundary_events())[500]
    assert 502 in row.source_transaction_ids
    assert row.values["txn_count_7d"] == 1
    assert row.values["amount_sum_7d"] == 70.0
    assert row.values["amount_max_7d"] == 70.0


def test_source_knowable_exactly_at_cutoff_is_eligible() -> None:
    """Invariant 1: `created_timestamp <=` keeps a row that becomes knowable at the cutoff."""

    row = _by_id(_knowledge_boundary_events())[600]
    assert row.source_transaction_ids == (601,)
    assert 602 not in row.source_transaction_ids
    assert row.values["txn_count_24h"] == 1
    assert row.values["amount_sum_24h"] == 40.0
    assert row.values["seconds_since_previous_txn"] == 1800.0


def test_order_key_mutation_makes_transaction_read_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Weakening `order_key <` to `<=` must show up as a self-read, not a silent no-op."""

    events = _boundary_events()
    shipped = _by_id(events)[500].values
    monkeypatch.setattr(reference, "eligible_history", _eligible_history_self_inclusive)
    mutated = _by_id(events)[500]
    assert mutated.values != shipped
    assert 500 in mutated.source_transaction_ids
    assert mutated.values["txn_count_1h"] == 2
    assert mutated.values["txn_count_24h"] == 2
    assert mutated.values["amount_sum_24h"] == 170.0
    assert mutated.values["amount_max_24h"] == 100.0
    assert mutated.values["seconds_since_previous_txn"] == 0.0


def test_order_key_mutation_is_caught_by_future_read_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lineage audit is the second net: a self-read is a future read."""

    monkeypatch.setattr(reference, "eligible_history", _eligible_history_self_inclusive)
    with pytest.raises(AssertionError, match="future read"):
        assert_no_future_reads(compute_feature_vectors(_boundary_events()))


def test_shipped_order_key_predicate_is_strictly_less_than() -> None:
    """Fails loudly if the mutated `<=` predicate ever lands in reference.py."""

    canonical = deduplicate_events(_boundary_events())
    target = next(event for event in canonical if event.transaction_id == 500)
    shipped = reference.eligible_history(target, canonical)
    mutated = _eligible_history_self_inclusive(target, canonical)
    assert {source.transaction_id for source in shipped} == {501, 502}
    assert {source.transaction_id for source in mutated} == {500, 501, 502}


def test_knowledge_time_mutation_drops_arrival_at_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tightening `created_timestamp <=` to `<` must empty the history, not stay silent."""

    events = _knowledge_boundary_events()
    shipped = _by_id(events)[600].values
    monkeypatch.setattr(reference, "eligible_history", _eligible_history_knowledge_strict)
    mutated = _by_id(events)[600]
    assert mutated.values != shipped
    assert mutated.source_transaction_ids == ()
    assert mutated.values["txn_count_24h"] == 0
    assert mutated.values["amount_sum_24h"] == 0.0
    assert mutated.values["seconds_since_previous_txn"] == -1.0
