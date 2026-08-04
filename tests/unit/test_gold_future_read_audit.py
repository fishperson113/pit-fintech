"""Unit coverage for the Gate G3 future-read audit in ``features/build_offline.py``.

``probe_future_read_violations`` replaces a dead-code branch that hard-coded
``future_reads = 0`` (``if False else 0``), which meant ``no_future_read_violations`` and
``max_source_step_below_every_cutoff`` in ``GOLD_PROMOTION_PRECONDITIONS`` always passed
regardless of the data. These tests exercise the audit directly against a hand-built DuckDB
relation, independent of the frozen ``paysim_pre_decision_feature_sql`` engine.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa

from pit_fintech.features.build_offline import probe_future_read_violations

_COLUMNS = (
    "source_row_number",
    "step",
    "knowledge_step",
    "transaction_type",
    "destination_entity_id",
    "destination_entity_kind",
)


def _connection_with(rows: list[tuple[int, int, int, str, str, str]]) -> duckdb.DuckDBPyConnection:
    table = pa.table({name: [row[i] for row in rows] for i, name in enumerate(_COLUMNS)})
    connection = duckdb.connect()
    connection.register("gold_source", table)
    return connection


def test_probe_future_read_violations_is_zero_on_clean_history() -> None:
    """A history row that is both step-prior and knowledge-prior is not a violation."""

    connection = _connection_with(
        [
            (1, 10, 10, "TRANSFER", "C1", "CUSTOMER"),
            (2, 50, 50, "CASH_OUT", "C1", "CUSTOMER"),
        ]
    )
    try:
        violations = probe_future_read_violations(
            connection=connection,
            relation="gold_source",
            cutoff_start_step=50,
            cutoff_end_step=50,
        )
    finally:
        connection.close()

    assert violations == 0


def test_probe_future_read_violations_catches_a_late_known_history_row() -> None:
    """A row that is step-prior (step 10 < 50) but only knowable at knowledge_step 50 is a
    genuine future read: the cutoff row (step 50) could not actually have known it yet."""

    connection = _connection_with(
        [
            (1, 10, 50, "TRANSFER", "C1", "CUSTOMER"),
            (2, 50, 50, "CASH_OUT", "C1", "CUSTOMER"),
        ]
    )
    try:
        violations = probe_future_read_violations(
            connection=connection,
            relation="gold_source",
            cutoff_start_step=50,
            cutoff_end_step=50,
        )
    finally:
        connection.close()

    assert violations == 1
