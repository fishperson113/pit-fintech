"""Exercise the real-Silver PaySim fixture builder when a local artifact exists.

``pit_fintech.data.paysim_fixture.build_paysim_temporal_fixture`` reads the real Silver
``paysim_transactions`` Delta table, so it spans a storage boundary (``pytest.mark.integration``)
and needs a PaySim application lakehouse manifest that only exists after a local
``pit data build-lakehouse --dataset paysim`` run against the full PaySim CSV. That CSV is not
committed to the repo (see ``data/raw/paysim`` handling in ``data/paysim.py``) and CI does not
produce it, so this test cannot require the manifest to always be present the way
``tests/temporal`` requires the credential-free synthetic fixture (``pit data sample``, wired
through the ``data-sample`` Make/make.ps1 prerequisite).

The chosen strategy keeps the difference visible instead of the fixture builder staying an
untested branch: skip loudly, with the builder's own actionable message, when no manifest is
found; run the real path and assert on it when one is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pit_fintech.data.paysim_fixture import (
    EXPECTED_PATH,
    FEATURE_TABLE_PATH,
    PARQUET_PATH,
    PAYSIM_FEATURE_TABLE_COLUMNS,
    SOURCE_PATH,
    build_paysim_temporal_fixture,
    load_paysim_expected_features,
    load_paysim_fixture_events,
)
from pit_fintech.data.paysim_lakehouse import PAYSIM_SILVER_TRANSACTION_COLUMNS
from pit_fintech.features.paysim_reference import in_scoring_scope
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY,
    PAYSIM_FEAST_EPOCH_0,
    PAYSIM_MODEL_FEATURE_ORDER,
    paysim_step_to_timestamp,
)

pytestmark = pytest.mark.integration


def test_build_paysim_temporal_fixture_from_real_silver_or_skips_loudly() -> None:
    try:
        result = build_paysim_temporal_fixture()
    except FileNotFoundError as exc:
        pytest.skip(f"no local PaySim Silver artifact to build the fixture from: {exc}")

    assert result["source_rows"] > 0
    assert result["fixture_path"] == str(SOURCE_PATH)
    assert result["expected_path"] == str(EXPECTED_PATH)
    assert SOURCE_PATH.exists()
    assert EXPECTED_PATH.exists()

    events = load_paysim_fixture_events()
    expected = load_paysim_expected_features()

    # The source file is deliberately wider than the expectation file, and asserting equality
    # between the two was wrong. `select_paysim_fixture_events` fetches every row of the chosen
    # destinations (`_fetch_all`/`_fetch_window` filter on destination only) because history is
    # unfiltered by transaction type, while `compute_paysim_feature_vectors` emits a vector only
    # for rows in scoring scope (`scoring_scope_only=True` by default). So the relation to assert
    # is containment plus an exact account of the gap, not equality.
    #
    # The builder's own `_verify_round_trip` cannot catch a drift here: it applies the same
    # scoring-scope filter to both sides, so it stays green whatever the history rows do. This
    # test is the only place the two populations are pinned against each other.
    all_row_numbers = {event.source_row_number for event in events}
    in_scope = {event.source_row_number for event in events if in_scoring_scope(event)}
    history_only = all_row_numbers - in_scope

    assert set(expected) == in_scope
    assert set(expected) < all_row_numbers
    assert history_only, (
        "the fixture carries no out-of-scope history rows, so it could not expose a window bug"
    )


def test_paysim_fixture_parquet_is_a_feast_readable_view_of_the_same_rows() -> None:
    """The Parquet source Feast will read must be the JSONL rows, widened and time-typed.

    T1 needs a `FileSource` with real `event_timestamp`/`created_timestamp` columns (ADR-006
    decision 1), which PaySim has nowhere: Silver carries hour ordinals only. The builder derives
    them. This test pins three separate things: the Parquet is the *same* fifteen rows in the same
    order as the oracle fixture, it keeps every Silver column unchanged, and the derived columns
    follow the frozen affine map rather than some other clock.
    """

    try:
        result = build_paysim_temporal_fixture()
    except FileNotFoundError as exc:
        pytest.skip(f"no local PaySim Silver artifact to build the fixture from: {exc}")

    assert result["parquet_path"] == str(PARQUET_PATH)
    assert PARQUET_PATH.exists()

    table = pq.read_table(PARQUET_PATH)
    events = load_paysim_fixture_events()

    # Same rows, same order, same identities as the JSONL the oracle scores.
    assert table.num_rows == len(events)
    assert table.column("source_row_number").to_pylist() == [
        event.source_row_number for event in events
    ]

    # Every Silver column survives unchanged, and the derived pair is the only addition.
    assert set(PAYSIM_SILVER_TRANSACTION_COLUMNS) <= set(table.column_names)
    assert set(table.column_names) - set(PAYSIM_SILVER_TRANSACTION_COLUMNS) == {
        "event_timestamp",
        "created_timestamp",
    }

    # Feast `FileSource` validation needs a real timestamp column, not an ordinal.
    utc_timestamp = pa.timestamp("us", tz="UTC")
    assert table.schema.field("event_timestamp").type == utc_timestamp
    assert table.schema.field("created_timestamp").type == utc_timestamp

    # Pin the anchor itself against ADR-006 once, written out rather than imported as a number,
    # so a silent edit to the constant fails here instead of quietly moving every timestamp.
    assert datetime(2020, 1, 1, tzinfo=UTC) == PAYSIM_FEAST_EPOCH_0

    # Then check the map on real rows: one worked example first, then the whole column.
    first = table.slice(0, 1).to_pylist()[0]
    assert first["event_timestamp"] == PAYSIM_FEAST_EPOCH_0 + timedelta(hours=first["step"])
    assert first["created_timestamp"] == PAYSIM_FEAST_EPOCH_0 + timedelta(
        hours=first["knowledge_step"]
    )
    for row in table.to_pylist():
        assert row["event_timestamp"] == PAYSIM_FEAST_EPOCH_0 + timedelta(hours=row["step"])
        assert row["created_timestamp"] == PAYSIM_FEAST_EPOCH_0 + timedelta(
            hours=row["knowledge_step"]
        )


# The eleven in-scope cutoffs of the frozen `paysim1:16910f90577b0d98` snapshot. Written as a
# literal rather than derived, so a selection change that silently drops or adds a cutoff fails
# here instead of quietly reshaping the table `feature_repo/` reads.
EXPECTED_FEATURE_ROWS = 11

# Contract dtypes from ADR-003/ADR-005: counts and history flags are int64, everything else
# float64. DuckDB types a bare `CASE ... THEN 1` as int32, so the flags are only int64 because the
# projection casts them; pinning them here is what keeps that cast from being dropped as noise.
_INT64_FIELDS = frozenset(
    name
    for name in PAYSIM_MODEL_FEATURE_ORDER
    if name.startswith(("pit_prior_count", "recipient_has_history"))
)


def test_paysim_feature_table_pins_the_schema_feature_repo_binds_to() -> None:
    """The precomputed feature table: eleven rows, frozen column order, contract dtypes.

    Feast computes no window aggregates (M030 Finding 1), so this table -- not the raw source
    Parquet -- is what a `FeatureView` reads. Its path and its column names are a contract with
    `feature_repo/`, which is why they are pinned literally rather than recomputed here.

    The oracle comparison is repeated even though `build_paysim_temporal_fixture` already runs it
    internally: this one reads the file from disk, so it also covers the write and the Parquet
    round-trip, and it would still fail if the builder's own check were ever weakened.
    """

    try:
        result = build_paysim_temporal_fixture()
    except FileNotFoundError as exc:
        pytest.skip(f"no local PaySim Silver artifact to build the fixture from: {exc}")

    assert result["feature_table_path"] == str(FEATURE_TABLE_PATH)
    assert FEATURE_TABLE_PATH.name == "paysim_feature_table.parquet"
    assert FEATURE_TABLE_PATH.exists()

    table = pq.read_table(FEATURE_TABLE_PATH)
    events = load_paysim_fixture_events()
    expected = load_paysim_expected_features()
    in_scope = [event for event in events if in_scoring_scope(event)]

    # Row count: one per in-scope cutoff, and no history-only row leaked in as a cutoff.
    assert table.num_rows == EXPECTED_FEATURE_ROWS
    assert table.num_rows == len(in_scope) == len(expected)
    assert result["feature_rows"] == EXPECTED_FEATURE_ROWS

    # Column names and their order are the contract. Position matters as much as membership,
    # so this is a tuple comparison, not a set one.
    assert tuple(table.column_names) == PAYSIM_FEATURE_TABLE_COLUMNS
    assert PAYSIM_FEATURE_TABLE_COLUMNS[0] == PAYSIM_ENTITY
    assert PAYSIM_FEATURE_TABLE_COLUMNS[1:3] == ("event_timestamp", "created_timestamp")
    assert PAYSIM_FEATURE_TABLE_COLUMNS[3:15] == PAYSIM_MODEL_FEATURE_ORDER

    utc_timestamp = pa.timestamp("us", tz="UTC")
    assert table.schema.field(PAYSIM_ENTITY).type == pa.string()
    assert table.schema.field("event_timestamp").type == utc_timestamp
    assert table.schema.field("created_timestamp").type == utc_timestamp
    assert table.schema.field("source_row_number").type == pa.int64()
    for name in PAYSIM_MODEL_FEATURE_ORDER:
        expected_type = pa.int64() if name in _INT64_FIELDS else pa.float64()
        assert table.schema.field(name).type == expected_type, name

    # The SQL engine built this table and the pure-Python oracle built the expectations, so this
    # is two independent derivations agreeing -- the whole reason the table is not oracle-built.
    rows = table.to_pylist()
    assert [row["source_row_number"] for row in rows] == [
        event.source_row_number for event in in_scope
    ]
    by_row_number = {event.source_row_number: event for event in in_scope}
    for row in rows:
        event = by_row_number[row["source_row_number"]]
        assert row[PAYSIM_ENTITY] == event.destination_entity_id
        assert row["event_timestamp"] == paysim_step_to_timestamp(event.step)
        assert row["created_timestamp"] == paysim_step_to_timestamp(event.knowledge_step)
        for name in PAYSIM_MODEL_FEATURE_ORDER:
            assert row[name] == expected[row["source_row_number"]][name], (
                f"{row['source_row_number']}.{name}"
            )
