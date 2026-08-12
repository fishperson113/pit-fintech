from __future__ import annotations

import json
from pathlib import Path

from deltalake import DeltaTable

from pit_fintech.ingest.event_history import ingest_event_history


def test_event_history_ingestion_preserves_request_and_transaction_identity(tmp_path: Path) -> None:
    history = tmp_path / "served_events.jsonl"
    bronze = tmp_path / "bronze" / "served_events"
    checkpoint = tmp_path / "checkpoint.json"
    row = {
        "source_row_number": 1,
        "destination_entity_id": "C100",
        "step": 10,
        "knowledge_step": 10,
        "transaction_type": "TRANSFER",
        "amount": "12.50",
        "served_at": "2026-01-01T00:00:00+00:00",
        "request_id": "request-1",
        "transaction_id": "transaction-1",
    }
    history.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = ingest_event_history(
        history_path=history, bronze_path=bronze, checkpoint_path=checkpoint
    )

    assert report.rows_appended == 1
    record = DeltaTable(str(bronze)).to_pyarrow_table().to_pylist()[0]
    assert record["request_id"] == "request-1"
    assert record["transaction_id"] == "transaction-1"
    assert len(record["event_id"]) == 64
