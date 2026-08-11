from __future__ import annotations

import json
from pathlib import Path

from deltalake import DeltaTable

from pit_fintech.ingest.event_history import ingest_event_history


def _write_history(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_event_history_ingestion_appends_once_and_advances_checkpoint(tmp_path: Path) -> None:
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
    }
    _write_history(history, [row, row])

    first = ingest_event_history(
        history_path=history, bronze_path=bronze, checkpoint_path=checkpoint
    )
    second = ingest_event_history(
        history_path=history, bronze_path=bronze, checkpoint_path=checkpoint
    )

    assert first.rows_read == 2
    assert first.rows_appended == 1
    assert second.rows_read == 0
    assert second.rows_appended == 0
    table = DeltaTable(str(bronze)).to_pyarrow_table()
    assert table.num_rows == 1
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["line_number"] == 2


def test_event_history_ingestion_resumes_from_checkpoint(tmp_path: Path) -> None:
    history = tmp_path / "served_events.jsonl"
    bronze = tmp_path / "bronze" / "served_events"
    checkpoint = tmp_path / "checkpoint.json"
    base = {
        "destination_entity_id": "C100",
        "step": 10,
        "knowledge_step": 10,
        "transaction_type": "TRANSFER",
        "amount": "12.50",
        "served_at": "2026-01-01T00:00:00+00:00",
    }
    _write_history(history, [{**base, "source_row_number": 1}])
    ingest_event_history(history_path=history, bronze_path=bronze, checkpoint_path=checkpoint)
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**base, "source_row_number": 2, "step": 11}) + "\n")

    report = ingest_event_history(
        history_path=history, bronze_path=bronze, checkpoint_path=checkpoint
    )

    assert report.rows_read == 1
    assert report.rows_appended == 1
    assert DeltaTable(str(bronze)).to_pyarrow_table().num_rows == 2
