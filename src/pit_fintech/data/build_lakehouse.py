"""Bronze/Silver Delta builder for the verified synthetic path."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.contracts.manifests import (
    DeltaTableSnapshot,
    LakehouseManifest,
)
from pit_fintech.data.canonical import deduplicate_events, ordered_event_timestamps
from pit_fintech.data.sample import (
    PARQUET_PATH,
    PROJECT_ROOT,
    build_sample_fixture,
)

DEFAULT_LAKEHOUSE_ROOT = PROJECT_ROOT / "data" / "lakehouse"
LAKEHOUSE_MANIFEST_PATH = PROJECT_ROOT / "artifacts" / "sample" / "lakehouse-manifest.json"
FIXTURE_INGESTED_AT = datetime(2026, 7, 21, tzinfo=UTC)


def _current_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNCOMMITTED"


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def logical_table_checksum(table: pa.Table) -> str:
    """Hash logical rows independent of Parquet filenames and Delta commit metadata."""

    rows = [
        json.dumps(_json_value(row), allow_nan=False, separators=(",", ":"), sort_keys=True)
        for row in table.to_pylist()
    ]
    canonical = "\n".join(sorted(rows))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_checksum(table: pa.Table) -> str:
    fields = [
        {"name": field.name, "nullable": field.nullable, "type": str(field.type)}
        for field in table.schema
    ]
    canonical = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_rows(input_path: Path, dataset_snapshot_id: str) -> list[dict[str, Any]]:
    rows = pq.read_table(input_path).to_pylist()
    for row in rows:
        row["dataset_snapshot_id"] = dataset_snapshot_id
        row["synthetic_event_date"] = row["event_timestamp"].date()
        row["ingested_at"] = FIXTURE_INGESTED_AT
    return rows


def _silver_tables(
    bronze_rows: list[dict[str, Any]], dataset_snapshot_id: str
) -> tuple[pa.Table, pa.Table]:
    event_fields = set(TemporalEvent.model_fields)
    events = [
        TemporalEvent.model_validate(
            {key: value for key, value in row.items() if key in event_fields}
        )
        for row in bronze_rows
    ]
    canonical_events = deduplicate_events(events)
    ordered = ordered_event_timestamps(canonical_events)
    source_hashes = {row["transaction_id"]: row["source_row_hash"] for row in bronze_rows}

    transaction_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    for event in canonical_events:
        row = event.model_dump(mode="python")
        label = row.pop("label_is_fraud")
        row.update(
            {
                "ordered_event_timestamp": ordered[event.transaction_id],
                "source_row_hash": source_hashes[event.transaction_id],
                "dataset_snapshot_id": dataset_snapshot_id,
                "synthetic_event_date": event.event_timestamp.date(),
            }
        )
        transaction_rows.append(row)
        label_rows.append(
            {
                "transaction_id": event.transaction_id,
                "ordered_event_timestamp": ordered[event.transaction_id],
                "label_is_fraud": label,
                "dataset_snapshot_id": dataset_snapshot_id,
                "synthetic_event_date": event.event_timestamp.date(),
            }
        )

    transactions_schema = pa.schema(
        [
            ("transaction_id", pa.int64()),
            ("event_timestamp", pa.timestamp("us", tz="UTC")),
            ("created_timestamp", pa.timestamp("us", tz="UTC")),
            ("card_entity_id", pa.string()),
            ("transaction_amount", pa.float64()),
            ("product_code", pa.string()),
            ("address_code", pa.string()),
            ("ordered_event_timestamp", pa.timestamp("us", tz="UTC")),
            ("source_row_hash", pa.string()),
            ("dataset_snapshot_id", pa.string()),
            ("synthetic_event_date", pa.date32()),
        ]
    )
    labels_schema = pa.schema(
        [
            ("transaction_id", pa.int64()),
            ("ordered_event_timestamp", pa.timestamp("us", tz="UTC")),
            ("label_is_fraud", pa.int8()),
            ("dataset_snapshot_id", pa.string()),
            ("synthetic_event_date", pa.date32()),
        ]
    )
    return (
        pa.Table.from_pylist(transaction_rows, schema=transactions_schema),
        pa.Table.from_pylist(label_rows, schema=labels_schema),
    )


def _write_snapshot(
    table: pa.Table,
    path: Path,
    *,
    layer: str,
    table_name: str,
) -> DeltaTableSnapshot:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "overwrite" if (path / "_delta_log").exists() else "error"
    write_deltalake(
        path,
        table,
        mode=mode,
        partition_by="synthetic_event_date",
        schema_mode="overwrite" if mode == "overwrite" else None,
        name=f"pit_{layer}_{table_name}",
        description="Synthetic PIT correctness fixture; dates have no business meaning",
    )
    delta_table = DeltaTable(path)
    materialized = delta_table.to_pyarrow_table()
    return DeltaTableSnapshot(
        layer=layer,
        table=table_name,
        path=str(path),
        version=delta_table.version(),
        rows=materialized.num_rows,
        schema_checksum=schema_checksum(materialized),
        logical_checksum=logical_table_checksum(materialized),
    )


def build_sample_lakehouse(
    lakehouse_root: Path = DEFAULT_LAKEHOUSE_ROOT,
    *,
    reset: bool = False,
) -> LakehouseManifest:
    """Build versioned Bronze/Silver Delta tables from the synthetic fixture."""

    dataset_manifest = build_sample_fixture()
    if reset and lakehouse_root.exists():
        resolved_root = lakehouse_root.resolve()
        default_root = DEFAULT_LAKEHOUSE_ROOT.resolve()
        if resolved_root == default_root or PROJECT_ROOT.resolve() in resolved_root.parents:
            shutil.rmtree(resolved_root)
        else:
            raise ValueError(f"refusing to reset lakehouse outside project: {resolved_root}")

    bronze_rows = _source_rows(PARQUET_PATH, dataset_manifest.dataset_snapshot_id)
    bronze = pa.Table.from_pylist(bronze_rows)
    silver_transactions, silver_labels = _silver_tables(
        bronze_rows, dataset_manifest.dataset_snapshot_id
    )

    tables = (
        _write_snapshot(
            bronze,
            lakehouse_root / "bronze" / "transactions",
            layer="bronze",
            table_name="transactions",
        ),
        _write_snapshot(
            silver_transactions,
            lakehouse_root / "silver" / "transactions",
            layer="silver",
            table_name="transactions",
        ),
        _write_snapshot(
            silver_labels,
            lakehouse_root / "silver" / "labels",
            layer="silver",
            table_name="labels",
        ),
    )
    manifest = LakehouseManifest(
        dataset_snapshot_id=dataset_manifest.dataset_snapshot_id,
        code_commit=_current_commit(),
        tables=tables,
    )
    if lakehouse_root.resolve() == DEFAULT_LAKEHOUSE_ROOT.resolve():
        LAKEHOUSE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAKEHOUSE_MANIFEST_PATH.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return manifest


def lakehouse_history(lakehouse_root: Path = DEFAULT_LAKEHOUSE_ROOT) -> list[dict[str, Any]]:
    histories: list[dict[str, Any]] = []
    for layer, table_name in (
        ("bronze", "transactions"),
        ("silver", "transactions"),
        ("silver", "labels"),
    ):
        path = lakehouse_root / layer / table_name
        if (path / "_delta_log").exists():
            for commit in DeltaTable(path).history():
                histories.append({"layer": layer, "table": table_name, **commit})
    return histories
