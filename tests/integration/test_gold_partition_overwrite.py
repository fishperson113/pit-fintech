from __future__ import annotations

import datetime
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable

from pit_fintech.features.build_offline import (
    PRE_DECISION_FEATURE_SCHEMA,
    GoldColumn,
    _schema_for,
    _write_gold_table,
)
from pit_fintech.features.paysim_specs import PAYSIM_RECENCY_SENTINEL_STEPS


def _pre_decision_row(*, step: int, event_day: int, source_row_number: int) -> dict[str, object]:
    timestamp = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(
        hours=step - 1
    )
    return {
        "destination_entity_id": "C100",
        "event_timestamp": timestamp,
        "created_timestamp": timestamp,
        "current_amount": 10.0,
        "transaction_type_transfer": 0.0,
        "pit_prior_count_1h": 0,
        "pit_prior_amount_1h": 0.0,
        "pit_prior_count_24h": 0,
        "pit_prior_amount_24h": 0.0,
        "pit_prior_amount_168h": 0.0,
        "pit_distinct_senders_24h": 0,
        "pit_distinct_senders_168h": 0,
        "pit_steps_since_last_event": PAYSIM_RECENCY_SENTINEL_STEPS,
        "source_row_number": source_row_number,
        "step": step,
        "knowledge_step": step,
        "transaction_type": "CASH_OUT",
        "event_day": event_day,
    }


LEGACY_PRE_DECISION_SCHEMA = (
    *PRE_DECISION_FEATURE_SCHEMA[:4],
    GoldColumn("event_step", "double", False),
    *PRE_DECISION_FEATURE_SCHEMA[4:6],
    GoldColumn("recipient_has_history_1h", "int64", False),
    *PRE_DECISION_FEATURE_SCHEMA[6:7],
    GoldColumn("recipient_has_history_24h", "int64", False),
    GoldColumn("pit_prior_count_168h", "int64", False),
    GoldColumn("pit_prior_amount_168h", "double", False),
    GoldColumn("recipient_has_history_168h", "int64", False),
    *PRE_DECISION_FEATURE_SCHEMA[14:],
)


def test_write_gold_table_partition_overwrite_retains_existing_partitions(tmp_path: Path) -> None:
    """Expose the known Gold overwrite bug: partition_by does not scope replacement.

    ``_write_gold_table`` writes a second range with ``mode="overwrite"`` and only passes
    ``partition_by``. Delta's ``partition_by`` controls directory layout; it is not an overwrite
    predicate. The second write must therefore retain the first row in event_day 1 as well as the
    new row in event_day 2. The current implementation replaces the whole table, so this test is
    intentionally a failing bug reproduction until the writer passes the audit predicate through.
    """

    path = tmp_path / "gold"
    schema = _schema_for(PRE_DECISION_FEATURE_SCHEMA)
    first = pa.Table.from_pylist(
        [_pre_decision_row(step=1, event_day=1, source_row_number=1)], schema=schema
    )
    second = pa.Table.from_pylist(
        [_pre_decision_row(step=25, event_day=2, source_row_number=2)], schema=schema
    )

    _write_gold_table(path, first, PRE_DECISION_FEATURE_SCHEMA)
    _write_gold_table(path, second, PRE_DECISION_FEATURE_SCHEMA)

    head = DeltaTable(path).to_pyarrow_table()

    assert set(head.column("event_day").to_pylist()) == {1, 2}
    assert head.num_rows == 2


def test_write_gold_table_non_contiguous_overwrite_does_not_remove_middle_partition(
    tmp_path: Path,
) -> None:
    """Expose the non-contiguous overwrite bug caused by using ``BETWEEN``.

    After partitions 1, 2, and 3 exist, rewriting only partitions 1 and 3 must leave partition 2
    untouched. A ``BETWEEN min(partitions) AND max(partitions)`` predicate would incorrectly scan
    and replace partition 2 in the middle; the exact ``IN`` predicate must retain all three rows.
    ``BETWEEN`` was tested and returned ``{1, 3}`` instead of ``{1, 2, 3}``, so this is the only
    test that prevents regressing to that predicate.
    """

    path = tmp_path / "gold"
    schema = _schema_for(PRE_DECISION_FEATURE_SCHEMA)

    for event_day in (1, 2, 3):
        table = pa.Table.from_pylist(
            [
                _pre_decision_row(
                    step=1 + (event_day - 1) * 24,
                    event_day=event_day,
                    source_row_number=event_day,
                )
            ],
            schema=schema,
        )
        _write_gold_table(path, table, PRE_DECISION_FEATURE_SCHEMA)

    rewritten = pa.Table.from_pylist(
        [
            _pre_decision_row(step=1, event_day=1, source_row_number=101),
            _pre_decision_row(step=49, event_day=3, source_row_number=103),
        ],
        schema=schema,
    )
    _write_gold_table(path, rewritten, PRE_DECISION_FEATURE_SCHEMA)

    head = DeltaTable(path).to_pyarrow_table()

    assert set(head.column("event_day").to_pylist()) == {1, 2, 3}
    assert head.num_rows == 3


def test_write_gold_table_replaces_legacy_schema_without_event_step_error(tmp_path: Path) -> None:
    """A v2 committed table can be promoted to the ADR-011 v3 column set."""
    path = tmp_path / "gold"
    row = _pre_decision_row(step=1, event_day=1, source_row_number=1)
    legacy_row = {
        **row,
        "event_step": 1.0,
        "recipient_has_history_1h": 0,
        "recipient_has_history_24h": 0,
        "pit_prior_count_168h": 0,
        "recipient_has_history_168h": 0,
    }
    legacy_table = pa.Table.from_pylist(
        [legacy_row], schema=_schema_for(LEGACY_PRE_DECISION_SCHEMA)
    )
    current_table = pa.Table.from_pylist([row], schema=_schema_for(PRE_DECISION_FEATURE_SCHEMA))

    _write_gold_table(path, legacy_table, LEGACY_PRE_DECISION_SCHEMA)
    _write_gold_table(path, current_table, PRE_DECISION_FEATURE_SCHEMA)

    committed = DeltaTable(path).to_pyarrow_table()
    assert tuple(committed.column_names) == tuple(
        column.name for column in PRE_DECISION_FEATURE_SCHEMA
    )
    assert committed.num_rows == 1
