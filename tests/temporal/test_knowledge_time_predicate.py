"""Knowledge-time eligibility: late arrivals are dropped, boundary rows are kept.

ADR-005 makes historical eligibility two conditions, not one::

    prior.step           <  current.step
    AND prior.knowledge_step <= current.knowledge_step

On the frozen snapshot ``knowledge_step = step``, so the second condition is a no-op and the
committed E1/E4 baseline proves it breaks nothing. It does not prove the condition does anything.
These tests inject hand-built late arrivals through the production SQL of both PIT engines and
then mutate the predicate to prove the assertions have teeth.

Every fixture value is chosen by hand per ADR-005 decision 7; nothing here is random, and none of
it touches the frozen dataset.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

import duckdb
import pytest

from pit_fintech.features import paysim_recipient
from pit_fintech.models import paysim_training

pytestmark = pytest.mark.temporal

LATE_ENTITY = "C_LATE"
CUTOFF_ROW_NUMBER = 5
KNOWLEDGE_CLAUSE = "s.knowledge_step <= c.knowledge_step"
FIXTURE_SNAPSHOT_ID = "paysim1:knowledge-time-fixture"
FIXTURE_FILE_SHA256 = "0" * 64
# Mirrors data.paysim_lakehouse._event_day_sql(); only internal consistency between the two
# fixture views matters, because they are joined on event_day.
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


# One destination, five rows, no row redundant. The 24h window lower bound is 103 - 24 = 79, so
# all four source rows sit inside the window and knowledge time alone decides the outcome.
FIXTURE_ROWS: tuple[_FixtureRow, ...] = (
    _FixtureRow(1, 99, 200, "TRANSFER", 9000.0, "C_LATE_ARRIVAL", "known far too late"),
    _FixtureRow(2, 100, 100, "CASH_OUT", 10.0, "C_ORDINARY_100", "ordinary prior"),
    _FixtureRow(3, 101, 103, "TRANSFER", 500.0, "C_ON_BOUNDARY", "known exactly at the cutoff"),
    _FixtureRow(4, 102, 102, "CASH_OUT", 20.0, "C_ORDINARY_102", "ordinary prior"),
    _FixtureRow(5, 103, 103, "CASH_OUT", 1.0, "C_CUTOFF", "the cutoff event"),
)

# Correct history for the step-103 cutoff is {100, 101, 102}: row 99 is known too late, row 101
# is known exactly at the cutoff and is therefore eligible under `<=`.
EXPECTED_CUTOFF_VECTOR = {
    "pit_prior_count_1h": 1,
    "pit_prior_amount_1h": 20.0,
    "pit_prior_count_24h": 3,
    "pit_prior_amount_24h": 530.0,
    "pit_prior_count_168h": 3,
    "pit_prior_amount_168h": 530.0,
    "max_pit_source_step_24h": 102,
}
# Counterfactuals. Each names the bug that would produce it.
AMOUNT_IF_BOUNDARY_ROW_DROPPED = 30.0  # `<=` tightened to `<`: {100, 102}
COUNT_IF_BOUNDARY_ROW_DROPPED = 2
AMOUNT_IF_LATE_ARRIVAL_KEPT = 9530.0  # knowledge-time condition removed: {99, 100, 101, 102}
COUNT_IF_LATE_ARRIVAL_KEPT = 4

VECTOR_COLUMNS = ",\n            ".join(EXPECTED_CUTOFF_VECTOR)


def _recipient_cutoff_vector() -> dict[str, float | int | None]:
    """Run the diagnostic engine's production SQL over the injected fixture."""

    connection = duckdb.connect()
    values = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}', "
        f"0.0, 0.0, '{LATE_ENTITY}', 0.0, 0.0, 0, 0)"
        for row in FIXTURE_ROWS
    )
    # Column-for-column the view data.paysim.connect_paysim builds, except that knowledge_step
    # carries injected values instead of being derived from step. Nothing else differs, so the
    # feature SQL below is the production SQL.
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
    paysim_recipient.materialize_recipient_leakage_vectors(connection)
    rows = (
        connection.sql(
            f"""
        SELECT
            {VECTOR_COLUMNS}
        FROM {paysim_recipient.VECTOR_TABLE}
        WHERE source_row_number = {CUTOFF_ROW_NUMBER}
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    assert len(rows) == 1, "the cutoff event must produce exactly one vector"
    return rows[0]


def _training_cutoff_vector() -> dict[str, float | int | None]:
    """Run the locked baseline engine's production SQL over the same injected fixture."""

    connection = duckdb.connect()
    transactions = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}')"
        for row in FIXTURE_ROWS
    )
    labels = ",\n".join(f"({row.source_row_number}, {row.step}, 0)" for row in FIXTURE_ROWS)
    # Mirrors silver.paysim_transactions / silver.paysim_labels as built by
    # data.paysim_lakehouse, again differing only in the injected knowledge_step values.
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
            '{LATE_ENTITY}'::VARCHAR AS destination_entity_id,
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
    paysim_training._materialize_vector_table(
        connection,
        dataset_snapshot_id=FIXTURE_SNAPSHOT_ID,
        train_nonfraud_sample_per_type=1_000,
        seed=paysim_training.DEFAULT_SEED,
        train_end_step=paysim_training.PAYSIM_TRAIN_END_STEP,
        validation_end_step=paysim_training.PAYSIM_VALIDATION_END_STEP,
    )
    rows = (
        connection.sql(
            f"""
        SELECT
            {VECTOR_COLUMNS}
        FROM {paysim_training.VECTOR_TABLE}
        WHERE source_row_number = {CUTOFF_ROW_NUMBER}
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    assert len(rows) == 1, "the cutoff event must produce exactly one vector"
    return rows[0]


@dataclass(frozen=True)
class _Engine:
    module: ModuleType
    cutoff_vector: Callable[[], dict[str, float | int | None]]


ENGINES: dict[str, _Engine] = {
    "recipient": _Engine(paysim_recipient, _recipient_cutoff_vector),
    "training": _Engine(paysim_training, _training_cutoff_vector),
}
ENGINE_NAMES = tuple(ENGINES)


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

    vector = ENGINES[engine_name].cutoff_vector()

    # 24h window: {100, 101, 102} -> 10.0 + 500.0 + 20.0.
    assert vector["pit_prior_count_24h"] == 3
    assert vector["pit_prior_amount_24h"] == 530.0
    # 1h window: only step 102 is inside [102, 102], proving 24h is not right by accident.
    assert vector["pit_prior_count_1h"] == 1
    assert vector["pit_prior_amount_1h"] == 20.0
    # 168h window reaches back past step 99, which is still excluded on knowledge time alone.
    assert vector["pit_prior_count_168h"] == 3
    assert vector["pit_prior_amount_168h"] == 530.0
    assert vector["max_pit_source_step_24h"] == 102
    assert vector == EXPECTED_CUTOFF_VECTOR


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_row_known_exactly_at_the_cutoff_is_eligible(engine_name: str) -> None:
    """The `<=` half: step 101 has knowledge_step 103, equal to the cutoff, so it counts.

    This is the row that a `<`-instead-of-`<=` bug drops. Dropping it costs exactly 500.0 and one
    event, which is why the amounts are spread far apart.
    """

    vector = ENGINES[engine_name].cutoff_vector()

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

    vector = ENGINES[engine_name].cutoff_vector()

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
    baseline = engine.cutoff_vector()
    mutated = _mutated_predicate(
        engine.module._prior_window_predicate,
        "s.knowledge_step < c.knowledge_step",
    )
    monkeypatch.setattr(engine.module, "_prior_window_predicate", mutated)

    assert engine.cutoff_vector() != baseline


@pytest.mark.parametrize("engine_name", ENGINE_NAMES)
def test_removing_knowledge_time_changes_the_result(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: drop knowledge time entirely. The late arrival must leak back in."""

    engine = ENGINES[engine_name]
    baseline = engine.cutoff_vector()
    mutated = _mutated_predicate(engine.module._prior_window_predicate, "TRUE")
    monkeypatch.setattr(engine.module, "_prior_window_predicate", mutated)

    assert engine.cutoff_vector() != baseline
