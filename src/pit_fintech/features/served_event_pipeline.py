"""Automatic served-event Silver normalization and Gold candidate computation.

This path intentionally produces a candidate only. It never promotes production Gold and never
turns a model prediction into a fraud label.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from pit_fintech.platform.lifecycle_logging import log_lifecycle

logger = logging.getLogger(__name__)

AMOUNT_TYPE = pa.decimal128(18, 2)


@dataclass(frozen=True, slots=True)
class ServedEventCandidateReport:
    bronze_path: str
    silver_path: str
    candidate_path: str
    quarantine_path: str | None
    silver_rows: int
    candidate_rows: int
    quarantined_rows: int


def _normalize_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    required = (
        "event_id",
        "source_row_number",
        "destination_entity_id",
        "step",
        "knowledge_step",
        "transaction_type",
        "amount",
        "served_at",
    )
    missing = [field for field in required if field not in row or row[field] is None]
    if missing:
        return None, f"missing_fields={','.join(missing)}"
    try:
        amount = Decimal(str(row["amount"])).quantize(Decimal("0.01"))
        source_row_number = int(row["source_row_number"])
        step = int(row["step"])
        knowledge_step = int(row["knowledge_step"])
    except (InvalidOperation, TypeError, ValueError) as exc:
        return None, f"invalid_numeric_field={exc}"
    if amount < 0:
        return None, "amount_must_be_non_negative"
    if source_row_number < 1 or step < 1 or knowledge_step < 1:
        return None, "ordinals_must_be_positive"
    if not str(row["destination_entity_id"]):
        return None, "destination_entity_id_must_not_be_empty"
    normalized = {
        "event_id": str(row["event_id"]),
        "request_id": str(row["request_id"]) if row.get("request_id") is not None else None,
        "transaction_id": (
            str(row["transaction_id"]) if row.get("transaction_id") is not None else None
        ),
        "source_row_number": source_row_number,
        "destination_entity_id": str(row["destination_entity_id"]),
        "step": step,
        "knowledge_step": knowledge_step,
        "transaction_type": str(row["transaction_type"]),
        "amount": amount,
        "served_at": str(row["served_at"]),
        "ingested_at": str(row.get("ingested_at", "")),
        "validation_status": "valid",
        "label_status": "unlabeled",
        "source_layer": "silver.served_events",
    }
    return normalized, None


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_deltalake(str(path), pa.Table.from_pylist(rows), mode="overwrite")


def _candidate_table(silver_rows: list[dict[str, Any]]) -> pa.Table:
    connection = duckdb.connect()
    try:
        source = pa.Table.from_pylist(silver_rows)
        connection.register("served_silver_arrow", source)
        return connection.execute(
            """
            WITH candidates AS (
                SELECT
                    c.*,
                    (count(s.source_row_number) FILTER (
                        WHERE s.step >= c.step - 1
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ))::BIGINT AS pit_prior_count_1h,
                    coalesce(sum(s.amount) FILTER (
                        WHERE s.step >= c.step - 1
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ), CAST(0 AS DECIMAL(18, 2)))::DECIMAL(18, 2) AS pit_prior_amount_1h,
                    (count(s.source_row_number) FILTER (
                        WHERE s.step >= c.step - 24
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ))::BIGINT AS pit_prior_count_24h,
                    coalesce(sum(s.amount) FILTER (
                        WHERE s.step >= c.step - 24
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ), CAST(0 AS DECIMAL(18, 2)))::DECIMAL(18, 2) AS pit_prior_amount_24h,
                    (count(s.source_row_number) FILTER (
                        WHERE s.step >= c.step - 168
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ))::BIGINT AS pit_prior_count_168h,
                    coalesce(sum(s.amount) FILTER (
                        WHERE s.step >= c.step - 168
                          AND s.step <= c.step - 1
                          AND s.knowledge_step <= c.knowledge_step
                    ), CAST(0 AS DECIMAL(18, 2)))::DECIMAL(18, 2) AS pit_prior_amount_168h
                FROM served_silver_arrow AS c
                LEFT JOIN served_silver_arrow AS s
                  ON s.destination_entity_id = c.destination_entity_id
                 AND s.source_row_number <> c.source_row_number
                 AND s.step >= c.step - 168
                 AND s.step <= c.step - 1
                 AND s.knowledge_step <= c.knowledge_step
                GROUP BY ALL
            )
            SELECT
                *,
                CASE WHEN pit_prior_count_1h > 0 THEN 1 ELSE 0 END::BIGINT
                    AS recipient_has_history_1h,
                CASE WHEN pit_prior_count_24h > 0 THEN 1 ELSE 0 END::BIGINT
                    AS recipient_has_history_24h,
                CASE WHEN pit_prior_count_168h > 0 THEN 1 ELSE 0 END::BIGINT
                    AS recipient_has_history_168h,
                CASE WHEN transaction_type = 'TRANSFER' THEN 1 ELSE 0 END::BIGINT
                    AS transaction_type_transfer,
                'served-events-gold-candidate-v1' AS candidate_definition_version
            FROM candidates
            ORDER BY step, source_row_number
            """
        ).to_arrow_table()
    finally:
        connection.close()


def build_served_event_candidate(
    *,
    bronze_path: Path,
    silver_path: Path,
    candidate_path: Path,
    quarantine_path: Path | None = None,
) -> ServedEventCandidateReport:
    """Normalize Bronze served events and write an unpromoted PIT Gold candidate."""

    log_lifecycle(logger, "offline.served_pipeline.started", bronze_path=bronze_path)
    bronze_rows = DeltaTable(str(bronze_path)).to_pyarrow_table().to_pylist()
    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    for row in bronze_rows:
        normalized, error = _normalize_row(row)
        if normalized is None:
            invalid_rows.append({**row, "validation_status": "invalid", "validation_error": error})
        else:
            valid_rows.append(normalized)
    _write_rows(silver_path, valid_rows)
    if invalid_rows and quarantine_path is not None:
        _write_rows(quarantine_path, invalid_rows)
    candidate = _candidate_table(valid_rows) if valid_rows else pa.table({})
    if valid_rows:
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        write_deltalake(str(candidate_path), candidate, mode="overwrite")
    log_lifecycle(
        logger,
        "offline.served_pipeline.completed",
        candidate_path=candidate_path,
        candidate_rows=len(candidate),
        quarantined_rows=len(invalid_rows),
        silver_path=silver_path,
        silver_rows=len(valid_rows),
        status="success",
    )
    return ServedEventCandidateReport(
        bronze_path=str(bronze_path),
        silver_path=str(silver_path),
        candidate_path=str(candidate_path),
        quarantine_path=str(quarantine_path) if quarantine_path else None,
        silver_rows=len(valid_rows),
        candidate_rows=len(candidate),
        quarantined_rows=len(invalid_rows),
    )
