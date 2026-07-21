from __future__ import annotations

from pathlib import Path

import pytest
from deltalake import DeltaTable

from pit_fintech.data.build_lakehouse import (
    build_sample_lakehouse,
    logical_table_checksum,
)

pytestmark = pytest.mark.integration


def _snapshot(manifest, layer: str, table: str):
    return next(item for item in manifest.tables if item.layer == layer and item.table == table)


def test_sample_delta_build_is_versioned_idempotent_and_time_travelable(tmp_path: Path) -> None:
    lakehouse_root = tmp_path / "lakehouse"
    first = build_sample_lakehouse(lakehouse_root)
    second = build_sample_lakehouse(lakehouse_root)

    first_bronze = _snapshot(first, "bronze", "transactions")
    first_transactions = _snapshot(first, "silver", "transactions")
    first_labels = _snapshot(first, "silver", "labels")
    second_transactions = _snapshot(second, "silver", "transactions")

    assert first_bronze.rows == 8
    assert first_transactions.rows == 7
    assert first_labels.rows == 7
    assert first_transactions.logical_checksum == second_transactions.logical_checksum
    assert second_transactions.version == first_transactions.version + 1

    old_table = DeltaTable(
        lakehouse_root / "silver" / "transactions",
        version=first_transactions.version,
    ).to_pyarrow_table()
    assert logical_table_checksum(old_table) == first_transactions.logical_checksum
    assert "label_is_fraud" not in old_table.column_names
