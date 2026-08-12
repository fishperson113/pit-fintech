from __future__ import annotations

from decimal import Decimal

from pit_fintech.contracts.served_events import served_event_id


def test_served_event_id_is_stable_across_decimal_string_forms() -> None:
    first = served_event_id(
        destination_entity_id="C100",
        step=10,
        knowledge_step=10,
        transaction_type="TRANSFER",
        amount=Decimal("12.50"),
    )
    second = served_event_id(
        destination_entity_id="C100",
        step=10,
        knowledge_step=10,
        transaction_type="TRANSFER",
        amount="12.50",
    )

    assert first == second
    assert len(first) == 64
