"""Cross-engine parity: the pure-Python PaySim oracle against the DuckDB feature path.

``features/reference.py`` has said since Sprint 1 that a DuckDB implementation "must match this
oracle before it is accepted". For the PaySim application contract that comparison had never been
written: the oracle and the SQL were two independent code paths, both green, with nothing binding
them. This module is that binding for ``paysim-fraud-recipient-v2``.

One fixture is defined once, as :data:`PARITY_ROWS`, and driven through three engines:

* ``oracle``   -- :mod:`pit_fintech.features.paysim_reference`, pure Python, no SQL;
* ``recipient``-- the diagnostic SQL in :mod:`pit_fintech.features.paysim_recipient`;
* ``training`` -- the evidence SQL in :mod:`pit_fintech.models.paysim_training`.

All twelve fields of ``PAYSIM_MODEL_FEATURE_ORDER`` are compared, in order, for every scored row.

**Why the fixture reaches far outside the SQL prune.** Both SQL engines prune the self-join with a
literal ``s.step >= c.step - MAX_LEAKAGE_WINDOW_STEPS`` *before* the per-window ``FILTER`` runs.
The oracle has no prune at all. Today the prune is exactly as wide as the widest window, so it is
redundant and any prune bug is masked by the ``FILTER``. That masking is the blind spot: a later
edit that narrows the prune, or that deletes the ``FILTER``'s lower bound as "redundant", changes
the result while every window-boundary test that only uses recent rows stays green. The fixture
therefore carries eligible rows at 168 and 25 steps back (a narrowed prune drops them) and
ineligible rows at 169 and 200 steps back (only the prune, or only the ``FILTER``, keeps them out).
``test_narrowing_the_sql_prune_*`` and ``test_deleting_the_filter_lower_bound_*`` mutate exactly
those two seams and must go red.

**Where the same-step guard actually lives.** Both engines exclude same-``step`` rows twice: once
in the join (``s.step <> c.step`` on the recipient path, ``s.step <= c.step - 1`` on the training
path) and once more in the ``FILTER`` predicate. No single-clause mutation can go red on either
engine, so ``test_admitting_same_step_rows_breaks_parity`` removes both guards at once and the two
``*_is_masked_by_the_*`` tests record which half absorbs which mutation.

Money is compared bit-for-bit. Both sides accumulate in exact decimal, so a disagreement confined
to totals that are not representable as a double points at DuckDB's ``DECIMAL -> DOUBLE`` cast
rather than at either sum.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from types import ModuleType
from typing import cast

import duckdb
import pytest

from pit_fintech.features import paysim_recipient, paysim_reference
from pit_fintech.features.paysim_reference import (
    PaySimSourceEvent,
    compute_paysim_feature_vectors,
    paysim_destination_kind,
    sum_money,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_FEATURE_SPECS,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_RECENCY_SENTINEL_STEPS,
)
from pit_fintech.models import paysim_training

pytestmark = pytest.mark.temporal

FIXTURE_SNAPSHOT_ID = "paysim1:parity-fixture"
FIXTURE_FILE_SHA256 = "0" * 64
# Mirrors data.paysim_lakehouse._event_day_sql(); only internal consistency between the two Silver
# fixture views matters, because they are joined on event_day.
EVENT_DAY_SQL = "(floor((step - 1) / 24.0)::INTEGER + 1)"

PARITY_ENTITY = "C_PARITY"
COLD_ENTITY = "C_COLD"
MERCHANT_ENTITY = "M_PARITY"
CUTOFF_ROW_NUMBER = 100
CUTOFF_STEP = 400


@dataclass(frozen=True)
class _FixtureRow:
    """One PaySim source row. ``why`` documents the case it exists to cover."""

    source_row_number: int
    step: int
    knowledge_step: int
    transaction_type: str
    amount: str
    destination_entity_id: str
    why: str

    @property
    def origin_entity_id(self) -> str:
        return f"C_ORIG_{self.source_row_number}"


# One destination, one cutoff at step 400, and a source row for every case that can separate the
# oracle from the SQL. Amounts are distinct 2-decimal values so that any wrong subset produces a
# visibly wrong total rather than a coincidence.
PARITY_ROWS: tuple[_FixtureRow, ...] = (
    _FixtureRow(
        1,
        200,
        200,
        "TRANSFER",
        "7777.77",
        PARITY_ENTITY,
        "200 steps back: outside every window AND outside the SQL prune. Excluded twice over, so "
        "it only reappears if the prune is widened and the FILTER lower bound is gone.",
    ),
    _FixtureRow(
        2,
        205,
        900,
        "TRANSFER",
        "5555.55",
        PARITY_ENTITY,
        "outside the prune and known at step 900: a late arrival whose exclusion must not depend "
        "on the knowledge-time clause, because the prune already removed it.",
    ),
    _FixtureRow(
        3,
        231,
        231,
        "CASH_OUT",
        "4444.44",
        PARITY_ENTITY,
        "169 steps back: one step outside the inclusive 168h lower bound.",
    ),
    _FixtureRow(
        4,
        232,
        232,
        "CASH_OUT",
        "1111.11",
        PARITY_ENTITY,
        "exactly 168 steps back: on the inclusive lower bound, so 168h must keep it. A prune "
        "narrower than 168 silently drops this row.",
    ),
    _FixtureRow(
        5,
        375,
        375,
        "CASH_OUT",
        "9999.99",
        PARITY_ENTITY,
        "25 steps back: outside 24h, inside 168h. Second row a narrowed prune would drop.",
    ),
    _FixtureRow(
        6,
        376,
        376,
        "TRANSFER",
        "222.22",
        PARITY_ENTITY,
        "exactly 24 steps back: on the inclusive 24h lower bound.",
    ),
    _FixtureRow(
        7,
        380,
        380,
        "CASH_IN",
        "33.33",
        PARITY_ENTITY,
        "CASH_IN: never a scored target, but recipient history is not type-filtered, so both "
        "engines must still count it.",
    ),
    _FixtureRow(
        8,
        398,
        900,
        "CASH_OUT",
        "8888.88",
        PARITY_ENTITY,
        "inside every window, known at step 900: excluded on knowledge time alone (ADR-005).",
    ),
    _FixtureRow(
        9,
        399,
        400,
        "TRANSFER",
        "500.50",
        PARITY_ENTITY,
        "one step back, knowable exactly at the cutoff: the row a `<=`-to-`<` bug drops.",
    ),
    _FixtureRow(
        10,
        400,
        400,
        "CASH_OUT",
        "3333.33",
        PARITY_ENTITY,
        "same step as the cutoff: excluded by the same-step policy, never by ordering.",
    ),
    _FixtureRow(
        11,
        401,
        401,
        "TRANSFER",
        "2222.22",
        PARITY_ENTITY,
        "one step into the future, inside the recipient engine's +168 prune.",
    ),
    _FixtureRow(
        12,
        600,
        600,
        "CASH_OUT",
        "1234.56",
        PARITY_ENTITY,
        "far future, outside the prune in both directions.",
    ),
    _FixtureRow(
        13,
        300,
        300,
        "CASH_OUT",
        "4321.00",
        COLD_ENTITY,
        "different destination: entity isolation, and a cold-start vector of its own.",
    ),
    _FixtureRow(
        14,
        390,
        390,
        "TRANSFER",
        "6543.21",
        MERCHANT_ENTITY,
        "merchant destination: outside the scoring scope of both engines (ADR-003).",
    ),
    _FixtureRow(
        CUTOFF_ROW_NUMBER,
        CUTOFF_STEP,
        CUTOFF_STEP,
        "CASH_OUT",
        "0.01",
        PARITY_ENTITY,
        "the hand-calculated cutoff event.",
    ),
)

_AMOUNTS: dict[int, Decimal] = {row.source_row_number: Decimal(row.amount) for row in PARITY_ROWS}


def _exact(*source_row_numbers: int) -> float:
    """Total the named rows in exact decimal, then land on the double the contract stores."""

    return float(sum_money(_AMOUNTS[number] for number in source_row_numbers))


# Hand-calculated history for the step-400 cutoff, spelled out as row sets rather than recomputed,
# so this expectation is not a second implementation of the window predicate.
PRIOR_1H_ROWS = (9,)
PRIOR_24H_ROWS = (6, 7, 9)
PRIOR_168H_ROWS = (4, 5, 6, 7, 9)
# ADR-011 v3: each fixture row has a unique origin (`C_ORIG_<srn>`), so distinct-senders equals the
# count in the same window. Recency is CUTOFF_STEP minus the latest prior step: row 9 sits at step
# 399, one before the cutoff, so it is 400 - 399 = 1.
EXPECTED_CUTOFF_VECTOR: dict[str, int | float] = {
    "current_amount": 0.01,
    "transaction_type_transfer": 0.0,
    "pit_prior_count_1h": len(PRIOR_1H_ROWS),
    "pit_prior_amount_1h": _exact(*PRIOR_1H_ROWS),
    "pit_prior_count_24h": len(PRIOR_24H_ROWS),
    "pit_prior_amount_24h": _exact(*PRIOR_24H_ROWS),
    "pit_prior_amount_168h": _exact(*PRIOR_168H_ROWS),
    "pit_distinct_senders_24h": len(PRIOR_24H_ROWS),
    "pit_distinct_senders_168h": len(PRIOR_168H_ROWS),
    "pit_steps_since_last_event": CUTOFF_STEP - 399,
}
# Rows the SQL prune removes before the FILTER ever sees them.
OUTSIDE_PRUNE_ROWS = (1, 2)


# --------------------------------------------------------------------------------------------
# The three engines over one fixture
# --------------------------------------------------------------------------------------------


def _oracle_vectors(rows: tuple[_FixtureRow, ...]) -> dict[int, dict[str, int | float]]:
    events = [
        PaySimSourceEvent(
            source_row_number=row.source_row_number,
            step=row.step,
            knowledge_step=row.knowledge_step,
            transaction_type=row.transaction_type,
            amount=row.amount,
            origin_entity_id=row.origin_entity_id,
            destination_entity_id=row.destination_entity_id,
            destination_entity_kind=paysim_destination_kind(row.destination_entity_id),
        )
        for row in rows
    ]
    return {
        row.source_row_number: dict(row.values) for row in compute_paysim_feature_vectors(events)
    }


def _recipient_connection(rows: tuple[_FixtureRow, ...]) -> duckdb.DuckDBPyConnection:
    """Build a `paysim` view column for column identical to data.paysim.connect_paysim.

    Only ``knowledge_step`` differs: it carries injected values instead of being derived from
    ``step``. Everything computed on top of this view is therefore the production feature SQL.
    """

    connection = duckdb.connect()
    values = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}', "
        f"0.0, 0.0, '{row.destination_entity_id}', 0.0, 0.0, 0, 0)"
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


def _training_connection(rows: tuple[_FixtureRow, ...]) -> duckdb.DuckDBPyConnection:
    """Build two Silver views mirroring data.paysim_lakehouse output."""

    connection = duckdb.connect()
    transactions = ",\n".join(
        f"({row.source_row_number}, {row.step}, {row.knowledge_step}, "
        f"'{row.transaction_type}', {row.amount}, '{row.origin_entity_id}', "
        f"'{row.destination_entity_id}')"
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
            destination_entity_id::VARCHAR AS destination_entity_id,
            CASE
                WHEN starts_with(destination_entity_id, 'C') THEN 'CUSTOMER'
                WHEN starts_with(destination_entity_id, 'M') THEN 'MERCHANT'
                ELSE 'UNKNOWN'
            END::VARCHAR AS destination_entity_kind,
            '{FIXTURE_SNAPSHOT_ID}'::VARCHAR AS dataset_snapshot_id,
            '{FIXTURE_FILE_SHA256}'::VARCHAR AS source_file_sha256,
            concat('{FIXTURE_SNAPSHOT_ID}', ':', source_row_number::VARCHAR)::VARCHAR
                AS source_record_id,
            {EVENT_DAY_SQL} AS event_day
        FROM (VALUES
            {transactions}
        ) AS fixture_rows(
            source_row_number, step, knowledge_step, transaction_type, amount,
            origin_entity_id, destination_entity_id
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


#: Vector table the recipient engine materializes for parity. ADR-011: this drives the real v3
#: contract engine ``paysim_pre_decision_feature_sql`` (the one that builds Gold), not the leakage
#: diagnostic table (which keeps the v2 count/amount/has_history shape). The contract engine emits
#: all ten v3 fields directly, so ``projections`` for this engine is empty.
_RECIPIENT_VECTOR_TABLE = "paysim_pre_decision_parity_vectors"


def _materialize_recipient(connection: duckdb.DuckDBPyConnection) -> None:
    # Map the `paysim` raw view onto the PAYSIM_PRE_DECISION_SOURCE_COLUMNS the contract engine
    # reads, then run the frozen v3 SQL. Same view the leakage path reads, so the fixture is shared.
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE paysim_pre_source AS
        SELECT
            source_row_number,
            step,
            knowledge_step,
            type AS transaction_type,
            amount,
            nameOrig AS origin_entity_id,
            nameDest AS destination_entity_id,
            CASE
                WHEN starts_with(nameDest, 'C') THEN 'CUSTOMER'
                WHEN starts_with(nameDest, 'M') THEN 'MERCHANT'
                ELSE 'UNKNOWN'
            END AS destination_entity_kind
        FROM paysim
        """
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {_RECIPIENT_VECTOR_TABLE} AS "
        + paysim_recipient.paysim_pre_decision_feature_sql("paysim_pre_source")
    )


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
class _SqlRewrite:
    """One literal clause rewrite applied to the statements an engine materializes with.

    ``monkeypatch.setattr`` reaches module attributes only. Both engines write their join
    conditions as SQL literals inside the materialize function, so a clause that lives there can
    be mutated only by rewriting the statement text on its way to DuckDB.
    """

    old: str
    new: str


@dataclass(frozen=True)
class _SqlEngine:
    module: ModuleType
    connect: Callable[[tuple[_FixtureRow, ...]], duckdb.DuckDBPyConnection]
    materialize: Callable[[duckdb.DuckDBPyConnection], None]
    vector_table: str
    projections: dict[str, str]
    # How this engine keeps same-step rows out of the join, and the weakening that admits them.
    # The two engines spell the same rule differently, so the mutation has to be per engine.
    join_same_step_rewrite: _SqlRewrite


class _RewritingConnection:
    """Delegate to a real connection, rewriting one clause in every statement it executes.

    ``applied`` is the no-op guard, in the same spirit as :func:`_mutated_predicate`: a rewrite
    that never matched would leave a mutation test green while proving nothing.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, rewrite: _SqlRewrite) -> None:
        self._connection = connection
        self._rewrite = rewrite
        self.applied = 0

    def execute(self, query: str, *args: object, **kwargs: object) -> object:
        mutated = query.replace(self._rewrite.old, self._rewrite.new)
        if mutated != query:
            self.applied += 1
        return self._connection.execute(mutated, *args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


SQL_ENGINES: dict[str, _SqlEngine] = {
    "recipient": _SqlEngine(
        module=paysim_recipient,
        connect=_recipient_connection,
        materialize=_materialize_recipient,
        vector_table=_RECIPIENT_VECTOR_TABLE,
        # The v3 contract engine emits all ten fields directly, so nothing is reconstructed here.
        projections={},
        # The join writes its same-step exclusion as `s.step <= c.step - 1`, followed by a newline
        # before `WHERE`; the FILTER spells the same clause inline (` AND s.knowledge_step ...`), so
        # the trailing newline makes this target the join and only the join.
        join_same_step_rewrite=_SqlRewrite(
            "s.step <= c.step - 1\n",
            "s.step <= c.step\n",
        ),
    ),
    "training": _SqlEngine(
        module=paysim_training,
        connect=_training_connection,
        materialize=_materialize_training,
        vector_table=paysim_training.VECTOR_TABLE,
        projections={},
        # Here the join writes its bound exactly like the FILTER does, so the trailing newline is
        # what makes this target the join and only the join: inside the FILTER the clause is
        # always followed by ` AND s.knowledge_step <= c.knowledge_step` on the same line.
        join_same_step_rewrite=_SqlRewrite(
            "s.step <= c.step - 1\n",
            "s.step <= c.step\n",
        ),
    ),
}
SQL_ENGINE_NAMES = tuple(SQL_ENGINES)


def _sql_vectors(
    engine: _SqlEngine,
    rows: tuple[_FixtureRow, ...] = PARITY_ROWS,
    *,
    rewrite: _SqlRewrite | None = None,
) -> dict[int, dict[str, int | float]]:
    """Run one fixture through an SQL engine and project the twelve fields in contract order.

    ``rewrite`` mutates the materialize statements on their way to DuckDB. It is the only handle
    on clauses that live in an SQL literal instead of in a patchable module attribute.
    """

    connection = engine.connect(rows)
    if rewrite is None:
        engine.materialize(connection)
    else:
        proxy = _RewritingConnection(connection, rewrite)
        engine.materialize(cast(duckdb.DuckDBPyConnection, proxy))
        if proxy.applied == 0:
            raise AssertionError(
                f"clause {rewrite.old!r} is absent from the statements that build "
                f"{engine.vector_table}; the mutation would be a no-op and the test would "
                "prove nothing"
            )
    selected = ",\n            ".join(
        f"{engine.projections.get(name, name)} AS {name}" for name in PAYSIM_MODEL_FEATURE_ORDER
    )
    records = (
        connection.sql(
            f"""
        SELECT
            source_row_number,
            {selected}
        FROM {engine.vector_table}
        ORDER BY step, source_row_number
        """
        )
        .to_arrow_table()
        .to_pylist()
    )
    return {
        record["source_row_number"]: {name: record[name] for name in PAYSIM_MODEL_FEATURE_ORDER}
        for record in records
    }


# --------------------------------------------------------------------------------------------
# Parity
# --------------------------------------------------------------------------------------------


def test_window_sizes_agree_between_oracle_and_sql() -> None:
    """The oracle derives its windows from the frozen specs; the SQL hard-codes them."""

    assert paysim_reference.PAYSIM_WINDOW_STEPS == paysim_recipient.LEAKAGE_WINDOWS_STEPS


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_oracle_and_sql_agree_field_by_field(engine_name: str) -> None:
    """Every scored row, every one of the twelve fields, in contract order.

    This is the comparison ``features/reference.py`` has always required and that the PaySim path
    never had. Field order is asserted on both sides because order is part of the contract
    (ADR-003 §Decision).
    """

    oracle = _oracle_vectors(PARITY_ROWS)
    sql = _sql_vectors(SQL_ENGINES[engine_name])

    assert sql.keys() == oracle.keys(), "the two paths disagree about the scoring scope"
    assert oracle, "the fixture produced no scored rows, so this comparison would be vacuous"
    for source_row_number in sorted(oracle):
        assert tuple(oracle[source_row_number]) == PAYSIM_MODEL_FEATURE_ORDER
        assert tuple(sql[source_row_number]) == PAYSIM_MODEL_FEATURE_ORDER
        for name in PAYSIM_MODEL_FEATURE_ORDER:
            assert sql[source_row_number][name] == oracle[source_row_number][name], (
                f"{engine_name} disagrees with the oracle on {name} "
                f"for source_row_number={source_row_number}"
            )


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_cutoff_vector_matches_the_hand_calculation(engine_name: str) -> None:
    """Agreement is not enough: both paths must also hit the hand-calculated vector.

    Two implementations can agree on a wrong answer. This pins the step-400 cutoff to values
    derived by hand from the row table above, so parity means parity with the contract.
    """

    oracle = _oracle_vectors(PARITY_ROWS)[CUTOFF_ROW_NUMBER]
    sql = _sql_vectors(SQL_ENGINES[engine_name])[CUTOFF_ROW_NUMBER]

    assert oracle == EXPECTED_CUTOFF_VECTOR
    assert sql == EXPECTED_CUTOFF_VECTOR
    # 24h keeps rows 6/7/9 and 168h additionally keeps 4/5, so the two windows cannot be equal by
    # accident; a single wrong window is visible as a wrong total, not only as a wrong count.
    assert oracle["pit_prior_amount_24h"] != oracle["pit_prior_amount_168h"]


def test_history_is_not_filtered_by_transaction_type() -> None:
    """A CASH_IN row is never scored, yet both paths must count it as recipient history."""

    oracle = _oracle_vectors(PARITY_ROWS)

    assert 7 not in oracle, "CASH_IN must not be a scored target (ADR-003 scoring scope)"
    assert 7 in PRIOR_24H_ROWS
    assert oracle[CUTOFF_ROW_NUMBER]["pit_prior_count_24h"] == 3


def test_scoring_scope_excludes_merchant_destinations() -> None:
    """ADR-003 limits scoring to CASH_OUT/TRANSFER with a customer destination."""

    oracle = _oracle_vectors(PARITY_ROWS)

    assert 14 not in oracle
    assert 13 in oracle
    # Row 13 is a zero-history scored cutoff: no prior events -> counts/fan-in 0 and cold recency.
    assert oracle[13]["pit_prior_count_24h"] == 0
    assert oracle[13]["pit_distinct_senders_168h"] == 0
    assert oracle[13]["pit_steps_since_last_event"] == PAYSIM_RECENCY_SENTINEL_STEPS


# --------------------------------------------------------------------------------------------
# Mutations: proof that the comparison has teeth
# --------------------------------------------------------------------------------------------

KNOWLEDGE_CLAUSE = "s.knowledge_step <= c.knowledge_step"


def _mutated_predicate(
    original: Callable[[int], str],
    old: str,
    new: str,
    *,
    formatted: bool = False,
) -> Callable[[int], str]:
    """Return ``original`` with one clause rewritten, failing if that clause is not there.

    The guard matters: if the predicate is ever reworded, a silent no-op mutation would leave these
    tests green while proving nothing.
    """

    def mutated(window_steps: int) -> str:
        predicate = original(window_steps)
        target = old.format(window_steps=window_steps) if formatted else old
        replacement = new.format(window_steps=window_steps) if formatted else new
        injected = predicate.replace(target, replacement)
        if injected == predicate:
            raise AssertionError(
                f"clause {target!r} is absent from {predicate!r}; the mutation would be a no-op "
                "and the test would prove nothing"
            )
        return injected

    return mutated


def _assert_parity_breaks(
    engine: _SqlEngine,
    *,
    rewrite: _SqlRewrite | None = None,
) -> dict[int, dict[str, int | float]]:
    """Recompute the SQL side under an active mutation and require it to disagree."""

    oracle = _oracle_vectors(PARITY_ROWS)
    mutated = _sql_vectors(engine, rewrite=rewrite)
    assert mutated != oracle, "the mutation changed nothing; this test cannot detect the bug"
    return mutated


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_tightening_knowledge_time_breaks_parity(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`knowledge_step <=` narrowed to `<` drops row 9, which is knowable exactly at the cutoff."""

    engine = SQL_ENGINES[engine_name]
    monkeypatch.setattr(
        engine.module,
        "_prior_window_predicate",
        _mutated_predicate(
            engine.module._prior_window_predicate,
            KNOWLEDGE_CLAUSE,
            "s.knowledge_step < c.knowledge_step",
        ),
    )
    mutated = _assert_parity_breaks(engine)[CUTOFF_ROW_NUMBER]

    assert mutated["pit_prior_count_1h"] == 0
    assert mutated["pit_prior_amount_1h"] == 0.0
    assert mutated["pit_prior_amount_24h"] == _exact(6, 7)


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_removing_knowledge_time_breaks_parity(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping the knowledge-time clause leaks the step-398 late arrival into 24h and 168h.

    Row 8 is knowable only at step 900 (ADR-005), so the clause is the only thing holding it out.
    *Which* windows it then reaches is decided by step arithmetic, not by the clause: a window is
    ``[c.step - w, c.step - 1]`` inclusive on both ends, so at the step-400 cutoff

        1h   -> [399, 399]   row 8 sits at step 398 and stays out; only row 9 qualifies
        24h  -> [376, 399]   row 8 is inside
        168h -> [232, 399]   row 8 is inside

    The unchanged 1h value is the discriminating datum here, not a missed leak: it shows the leak
    is bounded by the window rather than smeared across every field.
    """

    engine = SQL_ENGINES[engine_name]
    monkeypatch.setattr(
        engine.module,
        "_prior_window_predicate",
        _mutated_predicate(engine.module._prior_window_predicate, KNOWLEDGE_CLAUSE, "TRUE"),
    )
    mutated = _assert_parity_breaks(engine)[CUTOFF_ROW_NUMBER]

    # 1h is [399, 399] and row 8 sits at step 398, so this window must not move at all.
    assert mutated["pit_prior_count_1h"] == len(PRIOR_1H_ROWS)
    assert mutated["pit_prior_amount_1h"] == _exact(*PRIOR_1H_ROWS)
    # 24h: 222.22 (6) + 33.33 (7) + 8888.88 (8) + 500.50 (9) = 9644.93
    assert mutated["pit_prior_count_24h"] == len(PRIOR_24H_ROWS) + 1
    assert mutated["pit_prior_amount_24h"] == _exact(6, 7, 8, 9)
    assert mutated["pit_prior_amount_24h"] != EXPECTED_CUTOFF_VECTOR["pit_prior_amount_24h"]
    # 168h: 1111.11 (4) + 9999.99 (5) + 222.22 (6) + 33.33 (7) + 8888.88 (8) + 500.50 (9)
    #     = 20756.03. Every fixture row has a unique origin, so distinct-senders equals the count.
    assert mutated["pit_distinct_senders_168h"] == len(PRIOR_168H_ROWS) + 1
    assert mutated["pit_prior_amount_168h"] == _exact(4, 5, 6, 7, 8, 9)


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_narrowing_the_sql_prune_breaks_parity(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prune seam, first direction: a prune narrower than the widest window silently loses rows.

    ``MAX_LEAKAGE_WINDOW_STEPS`` is the literal both engines interpolate into the join's range
    prune, before any ``FILTER`` runs. Narrowing it to 24 leaves every window predicate untouched
    and still cuts rows 4 (168 steps back) and 5 (25 steps back) out of the 168h window, collapsing
    it onto the 24h value. Nothing in a fixture built only from recent rows would notice.
    """

    engine = SQL_ENGINES[engine_name]
    monkeypatch.setattr(engine.module, "MAX_LEAKAGE_WINDOW_STEPS", 24)
    mutated = _assert_parity_breaks(engine)[CUTOFF_ROW_NUMBER]

    assert mutated["pit_prior_amount_168h"] == _exact(*PRIOR_24H_ROWS)
    assert mutated["pit_prior_amount_168h"] != EXPECTED_CUTOFF_VECTOR["pit_prior_amount_168h"]
    assert mutated["pit_distinct_senders_168h"] == len(PRIOR_24H_ROWS)


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_deleting_the_filter_lower_bound_breaks_parity(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prune seam, second direction: the rows that only exist to sit outside the prune.

    Deleting the ``FILTER``'s lower bound is the plausible "it is redundant, the join already
    prunes to 168" refactor. On its own it is invisible for the 168h window, because the prune
    happens to enforce the same bound. Widen the prune afterwards -- a separate, innocuous-looking
    edit -- and history reaches back forever.

    Two fixture rows then leak in, one on each side of that pair: row 3 sits 169 steps back, one
    single step outside the 168h lower bound, and row 1 sits 200 steps back, far outside the
    original prune as well. Row 2 (205 steps back, ``knowledge_step`` 900) stays out on knowledge
    time whatever the step bounds say, which is what makes it the belt-and-braces case.
    """

    engine = SQL_ENGINES[engine_name]
    monkeypatch.setattr(
        engine.module,
        "_prior_window_predicate",
        _mutated_predicate(
            engine.module._prior_window_predicate,
            "s.step >= c.step - {window_steps} AND ",
            "",
            formatted=True,
        ),
    )
    monkeypatch.setattr(engine.module, "MAX_LEAKAGE_WINDOW_STEPS", 400)
    mutated = _assert_parity_breaks(engine)[CUTOFF_ROW_NUMBER]

    # With no lower bound left, every window collapses onto the same set: everything with
    # step <= 399 and knowledge_step <= 400. Rows 1 and 3 are knowable and now unbounded on the
    # left; rows 2 and 8 stay out on knowledge time alone (knowledge_step 900 > 400).
    #   7777.77 (1) + 4444.44 (3) + 1111.11 (4) + 9999.99 (5) + 222.22 (6) + 33.33 (7)
    #   + 500.50 (9) = 24089.36
    leaked_rows = (1, 3, *PRIOR_168H_ROWS)
    leaked = _exact(*leaked_rows)
    assert mutated["pit_prior_amount_1h"] == leaked
    assert mutated["pit_prior_amount_24h"] == leaked
    assert mutated["pit_prior_amount_168h"] == leaked
    assert mutated["pit_prior_count_1h"] == len(leaked_rows)
    # The rows the deleted bound was the only guard against: 7777.77 (1) + 4444.44 (3) = 12222.21
    assert mutated["pit_prior_amount_168h"] - EXPECTED_CUTOFF_VECTOR[
        "pit_prior_amount_168h"
    ] == pytest.approx(_exact(1, 3), abs=1e-9)
    # Row 2 needs the prune *and* knowledge time; row 3 needed only the FILTER's lower bound, which
    # is why deleting that bound is enough to pull it in.
    assert 2 in OUTSIDE_PRUNE_ROWS
    assert 3 not in OUTSIDE_PRUNE_ROWS


SAME_STEP_FILTER_CLAUSE = "s.step <= c.step - 1"
SAME_STEP_FILTER_WEAKENED = "s.step <= c.step"


def _weaken_the_filter_same_step_bound(
    engine: _SqlEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admit same-step rows in the shared FILTER predicate, leaving each join untouched."""

    monkeypatch.setattr(
        engine.module,
        "_prior_window_predicate",
        _mutated_predicate(
            engine.module._prior_window_predicate,
            SAME_STEP_FILTER_CLAUSE,
            SAME_STEP_FILTER_WEAKENED,
        ),
    )


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_same_step_filter_mutation_alone_is_masked_by_the_join(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On *both* engines the join, not the FILTER, is what keeps same-step rows out.

    ``paysim_recipient`` joins with ``s.step <> c.step`` and ``paysim_training`` with
    ``s.step <= c.step - 1``; each drops row 10 before any ``FILTER`` runs, so weakening the shared
    predicate to ``s.step <= c.step`` changes nothing on either engine.

    Recorded as a limitation, not as a property: **no mutation of the FILTER alone can go red on
    either engine**, so nothing in this file would catch a same-step regression confined to
    ``_prior_window_predicate``. An earlier version of this module claimed the two engines differed
    here and asserted that the training FILTER was unmasked; it is not, and the assertion could
    never have failed. ``test_admitting_same_step_rows_breaks_parity`` is the mutation with teeth:
    it has to remove both guards at once.
    """

    engine = SQL_ENGINES[engine_name]
    baseline = _sql_vectors(engine)
    _weaken_the_filter_same_step_bound(engine, monkeypatch)

    assert _sql_vectors(engine) == baseline
    assert _oracle_vectors(PARITY_ROWS) == baseline


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_same_step_join_mutation_alone_is_masked_by_the_filter(engine_name: str) -> None:
    """The mirror image: weakening only the join is absorbed by the untouched FILTER.

    Admitting same-step rows into the join still leaves ``s.step <= c.step - 1`` in every
    ``FILTER``, so no compared field moves. Together with the test above this pins the actual
    shape of the guard -- same-step exclusion is enforced twice on each engine, which is why
    breaking it needs a two-clause mutation and why neither clause alone is covered.
    """

    engine = SQL_ENGINES[engine_name]
    mutated = _sql_vectors(engine, rewrite=engine.join_same_step_rewrite)

    assert mutated == _oracle_vectors(PARITY_ROWS)


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_admitting_same_step_rows_breaks_parity(
    engine_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove both same-step guards at once and the fixture catches the leak on both engines.

    Row 10 sits at the cutoff's own step with a lower ``source_row_number`` -- ADR-003: the
    tie-break is "not permission to read an earlier CSV row from the same hour". Neither join
    carries a self-join guard beyond its step bound either, so with that bound gone the cutoff
    row 100 also joins to itself and contributes its own ``current_amount``.

    Hand-calculated at the step-400 cutoff, where the mutated window is ``[c.step - w, c.step]``
    and rows 2 and 8 remain excluded on knowledge time (``knowledge_step`` 900 > 400):

        1h   [399, 400] -> rows 9, 10, 100
             500.50 + 3333.33 + 0.01 = 3833.84
        24h  [376, 400] -> rows 6, 7, 9, 10, 100
             222.22 + 33.33 + 500.50 + 3333.33 + 0.01 = 4089.39
        168h [232, 400] -> rows 4, 5, 6, 7, 9, 10, 100 (each a distinct origin)
             1111.11 + 9999.99 + 222.22 + 33.33 + 500.50 + 3333.33 + 0.01 = 15200.49

    Row 11 (step 401) stays out of all three: it is inside the recipient join's +168 prune but
    fails the mutated upper bound ``s.step <= c.step`` all the same.
    """

    engine = SQL_ENGINES[engine_name]
    _weaken_the_filter_same_step_bound(engine, monkeypatch)
    mutated = _assert_parity_breaks(
        engine,
        rewrite=engine.join_same_step_rewrite,
    )[CUTOFF_ROW_NUMBER]

    assert mutated["pit_prior_count_1h"] == 3
    assert mutated["pit_prior_amount_1h"] == _exact(9, 10, CUTOFF_ROW_NUMBER)
    assert mutated["pit_prior_count_24h"] == 5
    assert mutated["pit_prior_amount_24h"] == _exact(6, 7, 9, 10, CUTOFF_ROW_NUMBER)
    assert mutated["pit_distinct_senders_168h"] == 7
    assert mutated["pit_prior_amount_168h"] == _exact(4, 5, 6, 7, 9, 10, CUTOFF_ROW_NUMBER)
    # The leak is exactly row 10 plus the cutoff's own row: 3333.33 + 0.01 = 3333.34
    assert mutated["pit_prior_amount_168h"] - EXPECTED_CUTOFF_VECTOR[
        "pit_prior_amount_168h"
    ] == pytest.approx(_exact(10, CUTOFF_ROW_NUMBER), abs=1e-9)


# --------------------------------------------------------------------------------------------
# Deliberate differences that must not be asserted equal
# --------------------------------------------------------------------------------------------


def test_paysim_tie_break_is_not_the_synthetic_oracle_tie_break() -> None:
    """The two oracles order events differently on purpose; neither is the other's reference.

    ``features/reference.py`` implements the synthetic ``fraud-history-v1`` contract and orders by
    ``(event_timestamp, transaction_id)`` per ADR-001: "The reference cutoff order is
    ``(event_timestamp, transaction_id)`` with strict ``<`` semantics."  PaySim has no timestamp,
    so ADR-002 decision 2 replaces it: "Persist ``source_row_number`` once in Bronze and use
    ``(step, source_row_number)`` as the deterministic replay/cutoff order with strict ``<``
    semantics."

    Those are different contracts over different entities, so no test may assert their vectors
    equal. What is asserted here is that the PaySim oracle uses the PaySim order key.
    """

    events = _oracle_vectors(PARITY_ROWS)
    cutoff = next(row for row in PARITY_ROWS if row.source_row_number == CUTOFF_ROW_NUMBER)
    source = PaySimSourceEvent(
        source_row_number=cutoff.source_row_number,
        step=cutoff.step,
        knowledge_step=cutoff.knowledge_step,
        transaction_type=cutoff.transaction_type,
        amount=cutoff.amount,
        origin_entity_id=cutoff.origin_entity_id,
        destination_entity_id=cutoff.destination_entity_id,
        destination_entity_kind="CUSTOMER",
    )

    assert source.order_key == (CUTOFF_STEP, CUTOFF_ROW_NUMBER)
    assert events, "fixture must produce vectors for this assertion to mean anything"


@pytest.mark.parametrize("engine_name", SQL_ENGINE_NAMES)
def test_same_step_tie_break_never_admits_an_earlier_row(engine_name: str) -> None:
    """The tie-break orders replay; it is not permission to read an earlier row in the same hour.

    ADR-003: "``source_row_number`` is the deterministic replay/tie-break column, not permission to
    read an earlier CSV row from the same hour for model-utility claims."  Row 10 has a lower
    ``source_row_number`` than the cutoff and the same ``step``, so an ordering-based
    implementation would count it. Both paths must exclude it.

    This is where the PaySim contract deliberately parts company with the synthetic oracle, which
    *does* admit an earlier same-instant transaction under ``(event_timestamp, transaction_id) <``
    (see ``test_same_timestamp_uses_transaction_id_tie_break``).
    """

    same_step_row = next(row for row in PARITY_ROWS if row.source_row_number == 10)
    oracle = _oracle_vectors(PARITY_ROWS)[CUTOFF_ROW_NUMBER]
    sql = _sql_vectors(SQL_ENGINES[engine_name])[CUTOFF_ROW_NUMBER]

    assert same_step_row.step == CUTOFF_STEP
    assert same_step_row.source_row_number < CUTOFF_ROW_NUMBER
    assert oracle["pit_prior_count_1h"] == 1
    assert sql["pit_prior_count_1h"] == 1
    assert oracle["pit_prior_amount_1h"] == _exact(9)
    assert sql["pit_prior_amount_1h"] == _exact(9)


def test_positive_control_columns_are_not_part_of_the_compared_contract() -> None:
    """The recipient table's leaky columns exist by design and must never be compared as features.

    ADR-003 forbids them as model inputs; they are the E2 positive controls. The oracle does not
    implement them, and that absence is intentional, not a gap in parity.
    """

    assert set(paysim_recipient.POSITIVE_CONTROL_COLUMNS).isdisjoint(PAYSIM_MODEL_FEATURE_ORDER)
    # STRICT_PIT_FEATURE_COLUMNS is the leakage diagnostic's own count/amount/has_history shape
    # (ADR-011 decoupled it from the model contract), but it must still never carry a leaky control.
    assert set(paysim_recipient.STRICT_PIT_FEATURE_COLUMNS).isdisjoint(
        paysim_recipient.POSITIVE_CONTROL_COLUMNS
    )


def test_oracle_value_types_match_the_declared_dtypes() -> None:
    """int64 fields come back as Python ints and float64 fields as floats, not the reverse."""

    dtypes = {spec.name: spec.dtype for spec in PAYSIM_FEATURE_SPECS}
    values = _oracle_vectors(PARITY_ROWS)[CUTOFF_ROW_NUMBER]

    for name, dtype in dtypes.items():
        value = values[name]
        assert not isinstance(value, bool)
        if dtype == "int64":
            assert isinstance(value, int), name
        else:
            assert isinstance(value, float), name
