"""Hand-injected fixtures driven through the production SQL of both PIT engines.

Two invariants that the frozen snapshot cannot exercise on its own live here.

**Knowledge time.** ADR-005 makes historical eligibility two conditions, not one::

    prior.step           <  current.step
    AND prior.knowledge_step <= current.knowledge_step

On the frozen snapshot ``knowledge_step = step``, so the second condition is a no-op and the
committed E1/E4 baseline proves only that it breaks nothing. These tests inject late arrivals and
then mutate the predicate to prove the assertions have teeth.

**Money arithmetic.** Money is summed as DECIMAL, not DOUBLE, so that addition is exact and
independent of the order a parallel hash aggregate merges partial sums. Summing in DOUBLE made
``vector_checksum`` drift between runs of identical code. These tests pin the sums to values
computed exactly with :mod:`decimal`.

Every fixture value is chosen by hand per ADR-005 decision 7; nothing here is random, nothing
touches the frozen dataset, and the feature SQL executed is the production SQL in both engines.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from types import ModuleType

import duckdb
import pytest

from pit_fintech.features import paysim_recipient
from pit_fintech.models import paysim_training

pytestmark = pytest.mark.temporal

FIXTURE_SNAPSHOT_ID = "paysim1:injected-fixture"
FIXTURE_FILE_SHA256 = "0" * 64
# Mirrors data.paysim_lakehouse._event_day_sql(); only internal consistency between the two
# Silver fixture views matters, because they are joined on event_day.
EVENT_DAY_SQL = "(floor((step - 1) / 24.0)::INTEGER + 1)"


@dataclass(frozen=True)
class _FixtureRow:
    source_row_number: int
    step: int
    knowledge_step: int
    transaction_type: str
    amount: float
    origin_entity_id: str
    role: str


def _recipient_connection(
    rows: tuple[_FixtureRow, ...],
    destination_entity_id: str,
) -> duckdb.DuckDBPyConnection:
    """Build a connection whose `paysim` view mirrors data.paysim.connect_paysim.

    Column for column the same view, except that knowledge_step carries injected values instead
    of being derived from step. Nothing else differs, so everything computed on top of it is the
    production feature SQL.
    """

    connection = duckdb.connect()
    values = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}', "
        f"0.0, 0.0, '{destination_entity_id}', 0.0, 0.0, 0, 0)"
        for row in rows
    )
    connection.execute(
        f"""
        CREATE VIEW paysim AS
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            knowledge_step::BIGINT AS knowledge_step,
            type::VARCHAR AS type,
            amount::DOUBLE AS amount,
            nameOrig::VARCHAR AS nameOrig,
            oldbalanceOrg::DOUBLE AS oldbalanceOrg,
            newbalanceOrig::DOUBLE AS newbalanceOrig,
            nameDest::VARCHAR AS nameDest,
            oldbalanceDest::DOUBLE AS oldbalanceDest,
            newbalanceDest::DOUBLE AS newbalanceDest,
            isFraud::INTEGER AS isFraud,
            isFlaggedFraud::INTEGER AS isFlaggedFraud
        FROM (VALUES
            {values}
        ) AS fixture_rows(
            source_row_number, step, knowledge_step, type, amount, nameOrig,
            oldbalanceOrg, newbalanceOrig, nameDest, oldbalanceDest, newbalanceDest,
            isFraud, isFlaggedFraud
        )
        """
    )
    return connection


def _training_connection(
    rows: tuple[_FixtureRow, ...],
    destination_entity_id: str,
) -> duckdb.DuckDBPyConnection:
    """Build a connection whose two Silver views mirror data.paysim_lakehouse output."""

    connection = duckdb.connect()
    transactions = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}')"
        for row in rows
    )
    labels = ",\n".join(f"({row.source_row_number}, {row.step}, 0)" for row in rows)
    connection.execute(
        f"""
        CREATE VIEW {paysim_training.TRANSACTION_SOURCE_VIEW} AS
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            knowledge_step::BIGINT AS knowledge_step,
            transaction_type::VARCHAR AS transaction_type,
            amount::DOUBLE AS amount,
            origin_entity_id::VARCHAR AS origin_entity_id,
            'CUSTOMER'::VARCHAR AS origin_entity_kind,
            '{destination_entity_id}'::VARCHAR AS destination_entity_id,
            'CUSTOMER'::VARCHAR AS destination_entity_kind,
            '{FIXTURE_SNAPSHOT_ID}'::VARCHAR AS dataset_snapshot_id,
            '{FIXTURE_FILE_SHA256}'::VARCHAR AS source_file_sha256,
            concat('{FIXTURE_SNAPSHOT_ID}', ':', source_row_number::VARCHAR)::VARCHAR
                AS source_record_id,
            {EVENT_DAY_SQL} AS event_day
        FROM (VALUES
            {transactions}
        ) AS fixture_rows(
            source_row_number, step, knowledge_step, transaction_type, amount, origin_entity_id
        )
        """
    )
    connection.execute(
        f"""
        CREATE VIEW {paysim_training.LABEL_SOURCE_VIEW} AS
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            isFraud::TINYINT AS isFraud,
            '{FIXTURE_SNAPSHOT_ID}'::VARCHAR AS dataset_snapshot_id,
            '{FIXTURE_FILE_SHA256}'::VARCHAR AS source_file_sha256,
            concat('{FIXTURE_SNAPSHOT_ID}', ':', source_row_number::VARCHAR)::VARCHAR
                AS source_record_id,
            {EVENT_DAY_SQL} AS event_day
        FROM (VALUES
            {labels}
        ) AS fixture_rows(source_row_number, step, isFraud)
        """
    )
    return connection


def _materialize_training(connection: duckdb.DuckDBPyConnection) -> None:
    paysim_training._materialize_vector_table(
        connection,
        dataset_snapshot_id=FIXTURE_SNAPSHOT_ID,
        train_nonfraud_sample_per_type=1_000,
        seed=paysim_training.DEFAULT_SEED,
        train_end_step=paysim_training.PAYSIM_TRAIN_END_STEP,
        validation_end_step=paysim_training.PAYSIM_VALIDATION_END_STEP,
    )


@dataclass(frozen=True)
class _Engine:
    module: ModuleType
    connect: Callable[[tuple[_FixtureRow, ...], str], duckdb.DuckDBPyConnection]
    materialize: Callable[[duckdb.DuckDBPyConnection], None]
    vector_table: str
    money_columns: tuple[str, ...]


MONEY_COLUMNS_ALL: tuple[str, ...] = (
    "pit_prior_amount_1h",
    "pit_prior_amount_24h",
    "pit_prior_amount_168h",
    "future_amount_1h",
    "future_amount_24h",
    "future_amount_168h",
    "current_inclusive_amount_1h",
    "current_inclusive_amount_24h",
    "current_inclusive_amount_168h",
    "leaky_centered_amount_1h",
    "leaky_centered_amount_24h",
    "leaky_centered_amount_168h",
    "leaky_lifetime_amount",
)
MONEY_COLUMNS_PIT_ONLY: tuple[str, ...] = (
    "pit_prior_amount_1h",
    "pit_prior_amount_24h",
    "pit_prior_amount_168h",
)

ENGINES: dict[str, _Engine] = {
    "recipient": _Engine(
        module=paysim_recipient,
        connect=_recipient_connection,
        materialize=paysim_recipient.materialize_recipient_leakage_vectors,
        vector_table=paysim_recipient.VECTOR_TABLE,
        money_columns=MONEY_COLUMNS_ALL,
    ),
    "training": _Engine(
        module=paysim_training,
        connect=_training_connection,
        materialize=_materialize_training,
        vector_table=paysim_training.VECTOR_TABLE,
        money_columns=MONEY_COLUMNS_PIT_ONLY,
    ),
}
ENGINE_NAMES = tuple(ENGINES)


def _cutoff_vector(
    engine: _Engine,
    rows: tuple[_FixtureRow, ...],
    destination_entity_id: str,
    columns: tuple[str, ...],
    source_row_number: int,
) -> dict[str, float | int | None]:
    connection = engine.connect(rows, destination_entity_id)
    engine.materialize(connection)
    selected = ",\n            ".join(columns)
    result = (
        connection.sql(
            f"""
        SELECT
            {selected}
        FROM {engine.vector_table}
        WHERE source_row_number = {source_row_number}
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    assert len(result) == 1, "the cutoff event must produce exactly one vector"
    return result[0]


# --------------------------------------------------------------------------------------------
# Knowledge time
# --------------------------------------------------------------------------------------------

LATE_ENTITY = "C_LATE"
LATE_CUTOFF_ROW_NUMBER = 5
KNOWLEDGE_CLAUSE = "s.knowledge_step <= c.knowledge_step"

# One destination, five rows, no row redundant. The 24h window lower bound is 103 - 24 = 79, so
# all four source rows sit inside the window and knowledge time alone decides the outcome.
LATE_ROWS: tuple[_FixtureRow, ...] = (
    _FixtureRow(1, 99, 200, "TRANSFER", 9000.0, "C_LATE_ARRIVAL", "known far too late"),
    _FixtureRow(2, 100, 100, "CASH_OUT", 10.0, "C_ORDINARY_100", "ordinary prior"),
    _FixtureRow(3, 101, 103, "TRANSFER", 500.0, "C_ON_BOUNDARY", "known exactly at the cutoff"),
    _FixtureRow(4, 102, 102, "CASH_OUT", 20.0, "C_ORDINARY_102", "ordinary prior"),
    _FixtureRow(5, 103, 103, "CASH_OUT", 1.0, "C_CUTOFF", "the cutoff event"),
)

# Correct history for the step-103 cutoff is {100, 101, 102}: row 99 is known too late, row 101
# is known exactly at the cutoff and is therefore eligible under `<=`.
# Columns common to both engines: the leakage diagnostic keeps the v2 count/amount shape while the
# training engine now emits the ADR-011 v3 set, so `pit_prior_count_168h` (leakage-only) is left out
# and the 168h window is checked through `pit_prior_amount_168h`, which both engines carry.
EXPECTED_CUTOFF_VECTOR = {
    "pit_prior_count_1h": 1,
    "pit_prior_amount_1h": 20.0,
    "pit_prior_count_24h": 3,
    "pit_prior_amount_24h": 530.0,
    "pit_prior_amount_168h": 530.0,
    "max_pit_source_step_24h": 102,
}
KNOWLEDGE_COLUMNS = tuple(EXPECTED_CUTOFF_VECTOR)
# Counterfactuals. Each names the bug that would produce it.
AMOUNT_IF_BOUNDARY_ROW_DROPPED = 30.0  # `<=` tightened to `<`: {100, 102}
COUNT_IF_BOUNDARY_ROW_DROPPED = 2
AMOUNT_IF_LATE_ARRIVAL_KEPT = 9530.0  # knowledge-time condition removed: {99, 100, 101, 102}
COUNT_IF_LATE_ARRIVAL_KEPT = 4


def _knowledge_cutoff_vector(engine: _Engine) -> dict[str, float | int | None]:
    return _cutoff_vector(
        engine,
        LATE_ROWS,
        LATE_ENTITY,
        KNOWLEDGE_COLUMNS,
        LATE_CUTOFF_ROW_NUMBER,
    )


def _mutated_predicate(original: Callable[[int], str], replacement: str) -> Callable[[int], str]:
    """Return `original` with the knowledge-time clause swapped, failing if it is not there.

    The guard matters: if the predicate is ever reworded, a silent no-op mutation would turn
    these mutation tests green while proving nothing.
    """

    def mutated(window_steps: int) -> str:
        predicate = original(window_steps)
        injected = predicate.replace(KNOWLEDGE_CLAUSE, replacement)
        if injected == predicate:
            raise AssertionError(
                f"knowledge-time clause {KNOWLEDGE_CLAUSE!r} is absent from {predicate!r}; "
                "the mutation would be a no-op and the test would prove nothing"
            )
        return injected

    return mutated


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_knowledge_time_window_values_match_hand_calculation(engine_name: str) -> None:
    """Both engines must reproduce the hand-calculated vector for the step-103 cutoff."""

    vector = _knowledge_cutoff_vector(ENGINES[engine_name])

    # 24h window: {100, 101, 102} -> 10.0 + 500.0 + 20.0.
    assert vector["pit_prior_count_24h"] == 3
    assert vector["pit_prior_amount_24h"] == 530.0
    # 1h window: only step 102 is inside [102, 102], proving 24h is not right by accident.
    assert vector["pit_prior_count_1h"] == 1
    assert vector["pit_prior_amount_1h"] == 20.0
    # 168h window reaches back past step 99, which is still excluded on knowledge time alone.
    assert vector["pit_prior_amount_168h"] == 530.0
    assert vector["max_pit_source_step_24h"] == 102
    assert vector == EXPECTED_CUTOFF_VECTOR


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_row_known_exactly_at_the_cutoff_is_eligible(engine_name: str) -> None:
    """The `<=` half: step 101 has knowledge_step 103, equal to the cutoff, so it counts.

    This is the row that a `<`-instead-of-`<=` bug drops. Dropping it costs exactly 500.0 and one
    event, which is why the amounts are spread far apart.
    """

    vector = _knowledge_cutoff_vector(ENGINES[engine_name])

    assert vector["pit_prior_count_24h"] != COUNT_IF_BOUNDARY_ROW_DROPPED
    assert vector["pit_prior_amount_24h"] != AMOUNT_IF_BOUNDARY_ROW_DROPPED
    assert vector["pit_prior_count_24h"] == 3
    assert vector["pit_prior_amount_24h"] - AMOUNT_IF_BOUNDARY_ROW_DROPPED == 500.0


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_row_known_after_the_cutoff_is_excluded(engine_name: str) -> None:
    """The late-arrival half: step 99 is inside every window but known at step 200.

    Its amount is 9000.0, three orders of magnitude above the legitimate history, so any leak is
    unmistakable rather than a rounding argument.
    """

    vector = _knowledge_cutoff_vector(ENGINES[engine_name])

    assert vector["pit_prior_count_24h"] != COUNT_IF_LATE_ARRIVAL_KEPT
    assert vector["pit_prior_amount_24h"] != AMOUNT_IF_LATE_ARRIVAL_KEPT
    assert vector["pit_prior_amount_24h"] < 9000.0
    assert vector["pit_prior_amount_168h"] < 9000.0
    # The audit column must never point at an event the cutoff could not have known about.
    assert vector["max_pit_source_step_24h"] == 102


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_tightening_knowledge_time_to_strict_changes_the_result(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: `knowledge_step <=` becomes `<`. The boundary row must stop being counted."""

    engine = ENGINES[engine_name]
    baseline = _knowledge_cutoff_vector(engine)
    mutated = _mutated_predicate(
        engine.module._prior_window_predicate,
        "s.knowledge_step < c.knowledge_step",
    )
    monkeypatch.setattr(engine.module, "_prior_window_predicate", mutated)

    assert _knowledge_cutoff_vector(engine) != baseline


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_removing_knowledge_time_changes_the_result(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: drop knowledge time entirely. The late arrival must leak back in."""

    engine = ENGINES[engine_name]
    baseline = _knowledge_cutoff_vector(engine)
    mutated = _mutated_predicate(engine.module._prior_window_predicate, "TRUE")
    monkeypatch.setattr(engine.module, "_prior_window_predicate", mutated)

    assert _knowledge_cutoff_vector(engine) != baseline


# --------------------------------------------------------------------------------------------
# Money arithmetic
# --------------------------------------------------------------------------------------------

MONEY_ENTITY = "C_MONEY"
MONEY_CUTOFF_ROW_NUMBER = 10
MONEY_CUTOFF_STEP = 10

# One destination with thirteen events at consecutive steps. The amounts are deliberately awkward
# in binary: 0.10, 0.20, 0.07, 0.03, 1234.56 and 9999.99 are none of them exactly representable as
# a double, so a DOUBLE running sum accumulates rounding error, while their exact decimal totals
# (11235.50 for the prior windows, 0.50 for the future windows) land on values a double can hold
# exactly. Summing in DECIMAL therefore hits those totals on the nose and summing in DOUBLE does
# not, which is what makes this fixture able to fail if the aggregates ever revert.
MONEY_ROWS: tuple[_FixtureRow, ...] = (
    _FixtureRow(1, 1, 1, "CASH_OUT", 0.10, "C_M01", "prior"),
    _FixtureRow(2, 2, 2, "TRANSFER", 0.20, "C_M02", "prior"),
    _FixtureRow(3, 3, 3, "CASH_OUT", 0.20, "C_M03", "prior, completes 0.50"),
    _FixtureRow(4, 4, 4, "TRANSFER", 1234.56, "C_M04", "prior, large and inexact"),
    _FixtureRow(5, 5, 5, "CASH_OUT", 9999.99, "C_M05", "prior, largest"),
    _FixtureRow(6, 6, 6, "TRANSFER", 0.07, "C_M06", "prior, sub-cent-ish"),
    _FixtureRow(7, 7, 7, "CASH_OUT", 0.03, "C_M07", "prior"),
    _FixtureRow(8, 8, 8, "TRANSFER", 0.10, "C_M08", "prior"),
    _FixtureRow(9, 9, 9, "CASH_OUT", 0.25, "C_M09", "prior, only row in the 1h window"),
    _FixtureRow(10, 10, 10, "CASH_OUT", 0.01, "C_M10", "the cutoff event"),
    _FixtureRow(11, 11, 11, "TRANSFER", 0.10, "C_M11", "future"),
    _FixtureRow(12, 12, 12, "CASH_OUT", 0.20, "C_M12", "future"),
    _FixtureRow(13, 13, 13, "TRANSFER", 0.20, "C_M13", "future, completes 0.50"),
)

# Window membership is spelled out rather than recomputed, so this oracle tests the arithmetic
# only and does not become a second implementation of the window predicate.
PRIOR_1H_STEPS = (9,)
PRIOR_24H_STEPS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
PRIOR_168H_STEPS = PRIOR_24H_STEPS
FUTURE_1H_STEPS = (11,)
FUTURE_24H_STEPS = (11, 12, 13)
FUTURE_168H_STEPS = FUTURE_24H_STEPS
LIFETIME_STEPS = tuple(range(1, 14))
CUTOFF_STEPS = (MONEY_CUTOFF_STEP,)


def _amount_at(step: int) -> Decimal:
    return next(Decimal(str(row.amount)) for row in MONEY_ROWS if row.step == step)


def _exact(*step_groups: Iterable[int]) -> float:
    """Sum the named rows exactly in decimal, then land on the double the contract stores."""

    total = Decimal("0.00")
    for group in step_groups:
        for step in group:
            total += _amount_at(step)
    return float(total)


EXPECTED_MONEY_VALUES: dict[str, float] = {
    "pit_prior_amount_1h": _exact(PRIOR_1H_STEPS),
    "pit_prior_amount_24h": _exact(PRIOR_24H_STEPS),
    "pit_prior_amount_168h": _exact(PRIOR_168H_STEPS),
    "future_amount_1h": _exact(FUTURE_1H_STEPS),
    "future_amount_24h": _exact(FUTURE_24H_STEPS),
    "future_amount_168h": _exact(FUTURE_168H_STEPS),
    "current_inclusive_amount_1h": _exact(PRIOR_1H_STEPS, CUTOFF_STEPS),
    "current_inclusive_amount_24h": _exact(PRIOR_24H_STEPS, CUTOFF_STEPS),
    "current_inclusive_amount_168h": _exact(PRIOR_168H_STEPS, CUTOFF_STEPS),
    "leaky_centered_amount_1h": _exact(PRIOR_1H_STEPS, CUTOFF_STEPS, FUTURE_1H_STEPS),
    "leaky_centered_amount_24h": _exact(PRIOR_24H_STEPS, CUTOFF_STEPS, FUTURE_24H_STEPS),
    "leaky_centered_amount_168h": _exact(PRIOR_168H_STEPS, CUTOFF_STEPS, FUTURE_168H_STEPS),
    "leaky_lifetime_amount": _exact(LIFETIME_STEPS),
}


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_money_sums_equal_the_exact_decimal_total(engine_name: str) -> None:
    """Every money column must equal the exact decimal total, bit for bit.

    This is the load-bearing regression test for `vector_checksum` drift. A DOUBLE running sum
    over these amounts does not land on the exact total, so reverting the aggregates to DOUBLE
    turns this red deterministically rather than by luck of thread scheduling.

    The two totals that are themselves exactly representable as a double -- 11235.50 for the
    prior windows and 0.50 for the future windows -- are the assertions that hold no matter how
    DuckDB converts DECIMAL to DOUBLE. The remaining totals additionally assume that conversion
    is correctly rounded; if only those fail, suspect the cast rather than the sum.
    """

    engine = ENGINES[engine_name]
    vector = _cutoff_vector(
        engine,
        MONEY_ROWS,
        MONEY_ENTITY,
        engine.money_columns,
        MONEY_CUTOFF_ROW_NUMBER,
    )
    expected = {name: EXPECTED_MONEY_VALUES[name] for name in engine.money_columns}

    assert vector["pit_prior_amount_24h"] == 11235.50
    assert vector["pit_prior_amount_168h"] == 11235.50
    assert vector == expected


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_materializing_twice_produces_identical_vectors(engine_name: str) -> None:
    """The whole vector table must be reproducible within one process.

    Weaker than the exactness test above and known to be so: two runs in the same process share a
    thread pool and a plan cache, so this cannot prove the aggregate is order-independent. It is
    kept because it compares every column of every row rather than one cutoff, so it also catches
    non-determinism introduced anywhere else in the materialization.
    """

    engine = ENGINES[engine_name]
    connection = engine.connect(MONEY_ROWS, MONEY_ENTITY)
    query = f"SELECT * FROM {engine.vector_table} ORDER BY step, source_row_number"

    engine.materialize(connection)
    first = connection.sql(query).to_arrow_table().to_pylist()
    engine.materialize(connection)
    second = connection.sql(query).to_arrow_table().to_pylist()

    assert first == second
    assert len(first) == len(MONEY_ROWS)
