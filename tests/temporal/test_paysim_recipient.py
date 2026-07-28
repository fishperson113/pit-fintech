from __future__ import annotations

from pathlib import Path

import pytest

from pit_fintech.data.paysim import (
    BALANCE_COLUMNS,
    EXPECTED_COLUMNS,
    LABEL_COLUMNS,
    POLICY_OUTPUT_COLUMNS,
    connect_paysim,
)
from pit_fintech.features.paysim_recipient import (
    PAYSIM_RECIPIENT_FEATURE_VERSION,
    POSITIVE_CONTROL_COLUMNS,
    STRICT_PIT_FEATURE_COLUMNS,
    materialize_recipient_leakage_vectors,
    recipient_leakage_example,
    recipient_leakage_timeline,
    recipient_leakage_window_gate,
    recipient_strict_pit_features,
)
from pit_fintech.models.paysim_lightgbm import EXPERIMENT_MATRIX

pytestmark = pytest.mark.temporal

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "paysim_recipient_temporal.csv"


def _materialized_connection():
    connection = connect_paysim(FIXTURE_PATH)
    materialize_recipient_leakage_vectors(
        connection,
        nonfraud_sample_per_group=100,
        train_end_step=140,
        validation_end_step=170,
    )
    return connection


def _write_recipient_csv(path: Path, *rows: str) -> None:
    path.write_text(",".join(EXPECTED_COLUMNS) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_strict_recipient_history_excludes_same_step_current_and_future() -> None:
    connection = _materialized_connection()
    rows = (
        connection.sql(
            """
        SELECT
            source_row_number,
            step,
            pit_prior_count_168h,
            pit_prior_amount_168h,
            max_pit_source_step_168h,
            recipient_has_history_168h,
            current_inclusive_amount_168h,
            future_count_168h,
            future_amount_168h
        FROM paysim_recipient_leakage_vectors
        WHERE destination_entity_id = 'C9'
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert [row["pit_prior_amount_168h"] for row in rows] == [
        0.0,
        0.0,
        30.0,
        60.0,
        70.0,
        90.0,
    ]
    assert [row["pit_prior_count_168h"] for row in rows] == [0, 0, 2, 3, 2, 2]
    assert rows[0]["pit_prior_count_168h"] == 0
    assert rows[1]["pit_prior_count_168h"] == 0
    assert rows[0]["recipient_has_history_168h"] == 0
    assert rows[0]["max_pit_source_step_168h"] is None
    assert rows[0]["current_inclusive_amount_168h"] == 10.0
    assert rows[0]["future_amount_168h"] == 70.0
    assert all(
        row["max_pit_source_step_168h"] is None or row["max_pit_source_step_168h"] < row["step"]
        for row in rows
    )


def test_window_lower_bound_is_inclusive_and_old_history_expires() -> None:
    connection = _materialized_connection()
    rows = (
        connection.sql(
            """
        SELECT step, pit_prior_amount_168h
        FROM paysim_recipient_leakage_vectors
        WHERE destination_entity_id = 'C9'
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    amounts_by_step = {row["step"]: row["pit_prior_amount_168h"] for row in rows}

    assert amounts_by_step[169] == 60.0
    assert amounts_by_step[170] == 70.0
    assert amounts_by_step[200] == 90.0


def test_positive_controls_are_detectable_without_pit_cutoff_violations() -> None:
    connection = _materialized_connection()
    gate = {
        row["window_hours"]: row for row in recipient_leakage_window_gate(connection).to_pylist()
    }

    assert set(gate) == {1, 24, 168}
    assert all(row["pit_cutoff_violations"] == 0 for row in gate.values())
    assert all(row["current_inclusive_changed_rows"] > 0 for row in gate.values())
    assert all(row["positive_control_changed_rows"] > 0 for row in gate.values())
    assert gate[168]["future_read_rows"] > 0


def test_e2_feature_set_uses_leaky_columns_not_pit_cutoff_columns() -> None:
    e2 = next(spec for spec in EXPERIMENT_MATRIX if spec.experiment_id == "E2")

    # E2 is the deliberately leaky positive control: its feature set must read the
    # current-inclusive/future/lifetime columns (which see beyond the cutoff), never the
    # `pit_prior_*` columns that E3/E4 use as their cutoff-safe reference. If someone
    # accidentally repoints E2 at `PIT_FEATURE_COLUMNS`, this must fail.
    assert not any(name.startswith("pit_prior_") for name in e2.feature_names)
    assert "future_amount_168h" in e2.feature_names
    assert "leaky_lifetime_amount" in e2.feature_names


def test_example_and_timeline_are_nonempty_and_deterministic() -> None:
    connection = _materialized_connection()
    example = recipient_leakage_example(connection).to_pylist()
    timeline = recipient_leakage_timeline(connection).to_pylist()

    assert len(example) == 1
    assert example[0]["feature_definition_version"] == PAYSIM_RECIPIENT_FEATURE_VERSION
    assert example[0]["pit_prior_count_168h"] > 0
    assert example[0]["future_count_168h"] > 0
    assert any(row["relation_to_cutoff"] == "TARGET_CURRENT" for row in timeline)
    assert any(row["relation_to_cutoff"] == "PIT_PRIOR" for row in timeline)
    assert any(row["relation_to_cutoff"] == "FUTURE_UNAVAILABLE" for row in timeline)


def test_repeated_origin_does_not_create_recipient_history() -> None:
    connection = _materialized_connection()
    rows = (
        connection.sql(
            """
        SELECT
            destination_entity_id,
            pit_prior_count_168h,
            pit_prior_amount_168h,
            recipient_has_history_168h
        FROM paysim_recipient_leakage_vectors
        WHERE origin_entity_id = 'C_REPEAT'
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert [row["destination_entity_id"] for row in rows] == ["C10", "C11"]
    assert [row["pit_prior_count_168h"] for row in rows] == [0, 0]
    assert [row["pit_prior_amount_168h"] for row in rows] == [0.0, 0.0]
    assert [row["recipient_has_history_168h"] for row in rows] == [0, 0]


def test_unseen_entity_is_cold_start_then_appears_in_next_transactions_history(
    tmp_path: Path,
) -> None:
    """Guards read-history-before-update-state: no entity may keep an empty history forever.

    If the serving order is inverted into update-state -> read-history -> score, a destination's
    very first transaction would already see itself, turning a cold-start entity into one with
    history of 1 on its own first row. The break this test traps is an exact plus-one offset on
    that single unseen-entity row, distinct from the n-row window-boundary shift a `<`-to-`<=`
    mutation would cause.
    """
    csv_path = tmp_path / "zero_history.csv"
    _write_recipient_csv(
        csv_path,
        "10,TRANSFER,25.0,C_ZERO_A,100.0,75.0,C_ZERO,0.0,25.0,0,0",
        "11,CASH_OUT,40.0,C_ZERO_B,100.0,60.0,C_ZERO,25.0,65.0,0,0",
    )
    connection = connect_paysim(csv_path)
    materialize_recipient_leakage_vectors(connection)
    rows = (
        connection.sql(
            """
        SELECT
            step,
            pit_prior_count_1h, pit_prior_amount_1h, recipient_has_history_1h,
            pit_prior_count_24h, pit_prior_amount_24h, recipient_has_history_24h,
            pit_prior_count_168h, pit_prior_amount_168h, recipient_has_history_168h
        FROM paysim_recipient_leakage_vectors
        WHERE destination_entity_id = 'C_ZERO'
        ORDER BY step
        """
        )
        .to_arrow_table()
        .to_pylist()
    )

    # Step 1 -- pre-score: the first-ever transaction to this destination must be cold-start on
    # every window; it cannot see itself.
    first = rows[0]
    for hours in ("1h", "24h", "168h"):
        assert first[f"pit_prior_count_{hours}"] == 0
        assert first[f"pit_prior_amount_{hours}"] == 0.0
        assert first[f"recipient_has_history_{hours}"] == 0

    # Step 2 -- post-score: only after the first transaction has been scored may the second
    # transaction to the same destination see it in its prior history.
    second = rows[1]
    for hours in ("1h", "24h", "168h"):
        assert second[f"pit_prior_count_{hours}"] == 1
        assert second[f"pit_prior_amount_{hours}"] == 25.0
        assert second[f"recipient_has_history_{hours}"] == 1


def test_explicit_split_contract_is_applied() -> None:
    connection = _materialized_connection()
    rows = (
        connection.sql(
            """
        SELECT step, split
        FROM paysim_recipient_leakage_vectors
        WHERE destination_entity_id = 'C9'
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert [row["split"] for row in rows] == [
        "train",
        "train",
        "train",
        "validation",
        "validation",
        "test",
    ]


def test_vector_lineage_excludes_raw_forbidden_columns() -> None:
    connection = _materialized_connection()
    columns = set(recipient_strict_pit_features(connection).column_names)
    forbidden = {*BALANCE_COLUMNS, *LABEL_COLUMNS, *POLICY_OUTPUT_COLUMNS}

    assert columns.isdisjoint(forbidden)
    assert columns.isdisjoint(POSITIVE_CONTROL_COLUMNS)
    assert "target_label" not in columns
    assert set(STRICT_PIT_FEATURE_COLUMNS) <= columns


def test_materialization_is_deterministic() -> None:
    connection = _materialized_connection()
    first = (
        connection.sql(
            """
        SELECT *
        FROM paysim_recipient_leakage_vectors
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    materialize_recipient_leakage_vectors(
        connection,
        nonfraud_sample_per_group=100,
        train_end_step=140,
        validation_end_step=170,
    )
    second = (
        connection.sql(
            """
        SELECT *
        FROM paysim_recipient_leakage_vectors
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert first == second


@pytest.mark.parametrize("invalid_size", [0, 1.5, True])
def test_invalid_nonfraud_sample_size_is_rejected(invalid_size: object) -> None:
    connection = connect_paysim(FIXTURE_PATH)

    with pytest.raises(ValueError, match="positive integer"):
        materialize_recipient_leakage_vectors(
            connection,
            nonfraud_sample_per_group=invalid_size,  # type: ignore[arg-type]
        )
