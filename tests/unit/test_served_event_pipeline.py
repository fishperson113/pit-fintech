from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from pit_fintech.features.served_event_pipeline import build_served_event_candidate


def test_served_events_build_silver_and_pit_gold_candidate(tmp_path: Path) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    candidate = tmp_path / "gold_candidate"
    write_deltalake(
        str(bronze),
        pa.Table.from_pylist(
            [
                {
                    "event_id": "e1",
                    "source_row_number": 1,
                    "destination_entity_id": "C1",
                    "step": 1,
                    "knowledge_step": 1,
                    "transaction_type": "TRANSFER",
                    "amount": "10.00",
                    "served_at": "2026-08-12T00:00:00+00:00",
                    "transaction_id": "tx-1",
                },
                {
                    "event_id": "e2",
                    "source_row_number": 2,
                    "destination_entity_id": "C1",
                    "step": 2,
                    "knowledge_step": 2,
                    "transaction_type": "CASH_OUT",
                    "amount": "5.00",
                    "served_at": "2026-08-12T01:00:00+00:00",
                    "transaction_id": "tx-2",
                },
                {
                    "event_id": "e3",
                    "source_row_number": 3,
                    "destination_entity_id": "C1",
                    "step": 3,
                    "knowledge_step": 3,
                    "transaction_type": "TRANSFER",
                    "amount": "100.00",
                    "served_at": "2026-08-12T02:00:00+00:00",
                    "transaction_id": "tx-3",
                },
            ]
        ),
        mode="overwrite",
    )

    report = build_served_event_candidate(
        bronze_path=bronze,
        silver_path=silver,
        candidate_path=candidate,
    )

    assert report.silver_rows == 3
    assert report.candidate_rows == 3
    rows = DeltaTable(str(candidate)).to_pyarrow_table().to_pylist()
    current = next(row for row in rows if row["event_id"] == "e2")
    assert current["pit_prior_count_1h"] == 1
    assert current["pit_prior_amount_1h"] == Decimal("10.00")
    assert current["pit_prior_count_24h"] == 1
    assert current["pit_prior_amount_24h"] == Decimal("10.00")
    assert current["label_status"] == "unlabeled"
    assert "isFraud" not in current
    assert current["validation_status"] == "valid"
