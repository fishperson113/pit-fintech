"""Checkpointed ingestion of serving Event History into a Bronze landing Delta table."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from pit_fintech.contracts.served_events import served_event_id
from pit_fintech.platform.lifecycle_logging import log_lifecycle

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "source_row_number",
    "destination_entity_id",
    "step",
    "knowledge_step",
    "transaction_type",
    "amount",
    "served_at",
)


@dataclass(frozen=True, slots=True)
class EventHistoryIngestReport:
    history_path: str
    bronze_path: str
    checkpoint_path: str
    start_line: int
    end_line: int
    rows_read: int
    rows_appended: int
    duplicate_rows: int


def _event_id(row: dict[str, Any]) -> str:
    return served_event_id(
        destination_entity_id=str(row["destination_entity_id"]),
        step=int(row["step"]),
        knowledge_step=int(row["knowledge_step"]),
        transaction_type=str(row["transaction_type"]),
        amount=str(row["amount"]),
    )


def _read_checkpoint(path: Path) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    line_number = payload.get("line_number")
    if not isinstance(line_number, int) or line_number < 0:
        raise ValueError(f"invalid Event History checkpoint: {path}")
    return line_number


def _write_checkpoint(path: Path, line_number: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"line_number": line_number}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_existing_event_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    table = DeltaTable(str(path)).to_pyarrow_table(columns=["event_id"])
    return {str(value) for value in table["event_id"].to_pylist()}


def _parse_row(line: str, line_number: int) -> dict[str, Any]:
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Event History JSON at line {line_number}") from exc
    if not isinstance(row, dict):
        raise ValueError(f"Event History line {line_number} must be a JSON object")
    missing = [name for name in REQUIRED_FIELDS if name not in row]
    if missing:
        raise ValueError(f"Event History line {line_number} missing fields: {missing}")
    return row


def ingest_event_history(
    *,
    history_path: Path,
    bronze_path: Path,
    checkpoint_path: Path,
) -> EventHistoryIngestReport:
    """Append unseen Event History rows to Bronze and advance the checkpoint atomically."""

    start_line = _read_checkpoint(checkpoint_path)
    log_lifecycle(
        logger,
        "offline.bronze.ingest.started",
        bronze_path=bronze_path,
        checkpoint_start=start_line,
        history_path=history_path,
    )
    if not history_path.exists():
        report = EventHistoryIngestReport(
            history_path=str(history_path),
            bronze_path=str(bronze_path),
            checkpoint_path=str(checkpoint_path),
            start_line=start_line,
            end_line=start_line,
            rows_read=0,
            rows_appended=0,
            duplicate_rows=0,
        )
        log_lifecycle(
            logger,
            "offline.bronze.ingest.completed",
            bronze_path=bronze_path,
            checkpoint_end=report.end_line,
            duplicate_rows=report.duplicate_rows,
            rows_appended=report.rows_appended,
            rows_read=report.rows_read,
            status="no_input",
        )
        return report

    parsed: list[dict[str, Any]] = []
    with history_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            if line_number < start_line:
                continue
            if not line.strip():
                continue
            parsed.append(_parse_row(line, line_number + 1))

    with history_path.open(encoding="utf-8") as handle:
        end_line = sum(1 for _ in handle)
    existing_ids = _load_existing_event_ids(bronze_path)
    batch_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    duplicate_rows = 0
    ingested_at = datetime.now(UTC).isoformat()
    for row in parsed:
        event_id = _event_id(row)
        if event_id in existing_ids or event_id in batch_ids:
            duplicate_rows += 1
            continue
        batch_ids.add(event_id)
        record = {
            "event_id": event_id,
            "source_row_number": int(row["source_row_number"]),
            "destination_entity_id": str(row["destination_entity_id"]),
            "step": int(row["step"]),
            "knowledge_step": int(row["knowledge_step"]),
            "transaction_type": str(row["transaction_type"]),
            "amount": str(row["amount"]),
            "served_at": str(row["served_at"]),
            "ingested_at": ingested_at,
        }
        for field in ("request_id", "transaction_id"):
            if field in row:
                record[field] = str(row[field])
        records.append(record)

    if records:
        table = pa.Table.from_pylist(records)
        write_deltalake(
            str(bronze_path),
            table,
            mode="append",
            schema_mode="merge" if any("transaction_id" in row for row in records) else None,
        )
    _write_checkpoint(checkpoint_path, end_line)
    report = EventHistoryIngestReport(
        history_path=str(history_path),
        bronze_path=str(bronze_path),
        checkpoint_path=str(checkpoint_path),
        start_line=start_line,
        end_line=end_line,
        rows_read=len(parsed),
        rows_appended=len(records),
        duplicate_rows=duplicate_rows,
    )
    log_lifecycle(
        logger,
        "offline.bronze.ingest.completed",
        bronze_path=bronze_path,
        checkpoint_end=report.end_line,
        duplicate_rows=report.duplicate_rows,
        event_id_first=records[0]["event_id"] if records else None,
        event_id_last=records[-1]["event_id"] if records else None,
        rows_appended=report.rows_appended,
        rows_read=report.rows_read,
        status="success",
        transaction_id_first=records[0].get("transaction_id") if records else None,
        transaction_id_last=records[-1].get("transaction_id") if records else None,
    )
    return report
