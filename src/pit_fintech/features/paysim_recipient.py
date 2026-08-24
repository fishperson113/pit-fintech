"""Reusable PaySim recipient-history and leakage diagnostics.

The functions in this module deliberately keep the deployable strict-PIT values separate from
current-inclusive and future-inclusive positive controls. Labels are carried only as target
metadata for diagnostic grouping; no label or balance field participates in history aggregation.
"""

from __future__ import annotations

from typing import Final

import duckdb
import pyarrow as pa

from pit_fintech.features.paysim_specs import (
    PAYSIM_AMOUNT_DECIMAL_TYPE,
    PAYSIM_ENTITY,
    PAYSIM_FEATURE_CONTRACT,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_HISTORY_FEATURE_NAMES,
    PAYSIM_RECENCY_SENTINEL_STEPS,
    PAYSIM_STATIC_FEATURE_NAMES,
)

PAYSIM_RECIPIENT_FEATURE_VERSION: Final = PAYSIM_FEATURE_DEFINITION_VERSION
LEAKAGE_WINDOWS_STEPS: Final = (1, 24, 168)
MAX_LEAKAGE_WINDOW_STEPS: Final = max(LEAKAGE_WINDOWS_STEPS)
PAYSIM_TRAIN_END_STEP: Final = 520
PAYSIM_VALIDATION_END_STEP: Final = 631
TARGET_TABLE: Final = "paysim_leakage_targets"
VECTOR_TABLE: Final = "paysim_recipient_leakage_vectors"
# The strict, non-leaky history columns the leakage VECTOR_TABLE materializes (count/amount/
# has_history per window). This is the leakage *diagnostic* shape (M015, notebook 03), deliberately
# NOT the frozen contract feature set: the diagnostic keeps its own count/has_history columns for
# the positive-control comparison, so it is pinned here rather than to the contract history names
# (which ADR-011 reshaped for the model). The two evolve independently.
STRICT_PIT_FEATURE_COLUMNS: Final = tuple(
    column
    for window_steps in LEAKAGE_WINDOWS_STEPS
    for column in (
        f"pit_prior_count_{window_steps}h",
        f"pit_prior_amount_{window_steps}h",
        f"recipient_has_history_{window_steps}h",
    )
)
POSITIVE_CONTROL_COLUMNS: Final = (
    *(
        column
        for window_steps in LEAKAGE_WINDOWS_STEPS
        for column in (
            f"current_inclusive_count_{window_steps}h",
            f"current_inclusive_amount_{window_steps}h",
            f"future_count_{window_steps}h",
            f"future_amount_{window_steps}h",
            f"leaky_centered_count_{window_steps}h",
            f"leaky_centered_amount_{window_steps}h",
        )
    ),
    "leaky_lifetime_count",
    "leaky_lifetime_amount",
)


def _validate_sample_size(nonfraud_sample_per_group: int) -> None:
    if (
        isinstance(nonfraud_sample_per_group, bool)
        or not isinstance(nonfraud_sample_per_group, int)
        or nonfraud_sample_per_group < 1
    ):
        raise ValueError("nonfraud_sample_per_group must be a positive integer")


def _validate_split_contract(train_end_step: int, validation_end_step: int) -> None:
    values = (train_end_step, validation_end_step)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("split boundaries must be integers")
    if train_end_step < 1 or validation_end_step <= train_end_step:
        raise ValueError("split boundaries must satisfy 1 <= train < validation")


def _require_vectors(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.sql(f"SELECT 1 FROM {VECTOR_TABLE} LIMIT 0")
    except duckdb.Error as exc:
        raise RuntimeError(
            "Recipient leakage vectors are unavailable; materialize them first"
        ) from exc


def _prior_window_predicate(window_steps: int) -> str:
    """Range-join form of ``RANGE BETWEEN {w} PRECEDING AND 1 PRECEDING`` plus knowledge time.

    Both step bounds are inclusive and ``c.step - 1`` excludes every same-step row, matching
    ADR-003. The trailing knowledge-time condition is the ADR-005 addition; on clean data
    ``knowledge_step = step``, so it is implied by ``s.step <= c.step - 1`` and changes nothing.
    """

    return (
        f"s.step >= c.step - {window_steps}"
        " AND s.step <= c.step - 1"
        " AND s.knowledge_step <= c.knowledge_step"
    )


def _future_window_predicate(window_steps: int) -> str:
    """Range-join form of ``RANGE BETWEEN 1 FOLLOWING AND {w} FOLLOWING``.

    The knowledge-time condition is deliberately omitted: ``future_*`` are the E2 positive
    controls whose only purpose is to read across the cutoff, so restricting what they may know
    would destroy the control.
    """

    return f"s.step >= c.step + 1 AND s.step <= c.step + {window_steps}"


def _window_columns(window_steps: int) -> str:
    prior = _prior_window_predicate(window_steps)
    future = _future_window_predicate(window_steps)
    return f"""
        (count(s.source_row_number) FILTER (WHERE {prior}))::BIGINT
            AS pit_prior_count_{window_steps}h,
        coalesce(
            sum(CAST(s.amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})) FILTER (WHERE {prior}),
            0.0
        )::DOUBLE AS pit_prior_amount_{window_steps}h,
        (max(s.step) FILTER (WHERE {prior}))::BIGINT
            AS max_pit_source_step_{window_steps}h,
        (count(s.source_row_number) FILTER (WHERE {future}))::BIGINT
            AS future_count_{window_steps}h,
        coalesce(
            sum(CAST(s.amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})) FILTER (WHERE {future}),
            0.0
        )::DOUBLE AS future_amount_{window_steps}h
    """


def _derived_window_columns(window_steps: int) -> str:
    """Derive the control columns, adding money in DECIMAL so the sums stay exact.

    Scalar addition of a fixed operand list is already order-stable, so these columns were never
    the source of checksum drift. They are added in DECIMAL anyway: mixing an exact aggregate with
    a rounding scalar addition would reintroduce a last-ulp difference between
    ``current_inclusive_amount`` and the ``pit_prior_amount`` it is compared against in the
    leakage gate.
    """

    prior_amount = f"CAST(pit_prior_amount_{window_steps}h AS {PAYSIM_AMOUNT_DECIMAL_TYPE})"
    future_amount = f"CAST(future_amount_{window_steps}h AS {PAYSIM_AMOUNT_DECIMAL_TYPE})"
    current = f"CAST(current_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})"
    return f"""
        CASE WHEN pit_prior_count_{window_steps}h > 0 THEN 1 ELSE 0 END
            AS recipient_has_history_{window_steps}h,
        pit_prior_count_{window_steps}h + 1
            AS current_inclusive_count_{window_steps}h,
        ({prior_amount} + {current})::DOUBLE
            AS current_inclusive_amount_{window_steps}h,
        pit_prior_count_{window_steps}h + 1 + future_count_{window_steps}h
            AS leaky_centered_count_{window_steps}h,
        ({prior_amount} + {current} + {future_amount})::DOUBLE
            AS leaky_centered_amount_{window_steps}h
    """


def _pre_decision_history_columns() -> tuple[str, tuple[str, ...]]:
    """The eight ADR-011 v3 history columns of the pre-decision projection, and the names they emit.

    Non-uniform by window on purpose: count at 1h/24h, amount at 1h/24h/168h, fan-in
    (``count(DISTINCT origin_entity_id)``) at 24h/168h, and recency once over the widest window.
    Money sums stay in ``DECIMAL(18,2)`` (M027); each ``FILTER`` re-applies the window bound on top
    of the join's ``s.step <= c.step - 1``. Recency is ``c.step - max(prior step)`` bounded to the
    widest window (the same pool the offline build reads), or ``PAYSIM_RECENCY_SENTINEL_STEPS`` when
    the recipient is cold. Every count/distinct/recency is cast to ``BIGINT`` because DuckDB types a
    bare aggregate as ``INTEGER`` while the contract declares ``int64``; a Parquet schema cares.
    """

    prior_1 = _prior_window_predicate(1)
    prior_24 = _prior_window_predicate(24)
    prior_168 = _prior_window_predicate(MAX_LEAKAGE_WINDOW_STEPS)

    def _count(predicate: str, name: str) -> str:
        return f"(count(s.source_row_number) FILTER (WHERE {predicate}))::BIGINT AS {name}"

    def _amount(predicate: str, name: str) -> str:
        return (
            f"coalesce(sum(CAST(s.amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})) "
            f"FILTER (WHERE {predicate}), 0.0)::DOUBLE AS {name}"
        )

    def _distinct(predicate: str, name: str) -> str:
        return f"(count(DISTINCT s.origin_entity_id) FILTER (WHERE {predicate}))::BIGINT AS {name}"

    fragments = (
        _count(prior_1, "pit_prior_count_1h"),
        _amount(prior_1, "pit_prior_amount_1h"),
        _count(prior_24, "pit_prior_count_24h"),
        _amount(prior_24, "pit_prior_amount_24h"),
        _amount(prior_168, "pit_prior_amount_168h"),
        _distinct(prior_24, "pit_distinct_senders_24h"),
        _distinct(prior_168, "pit_distinct_senders_168h"),
        (
            f"coalesce(c.step - (max(s.step) FILTER (WHERE {prior_168})), "
            f"{PAYSIM_RECENCY_SENTINEL_STEPS})::BIGINT AS pit_steps_since_last_event"
        ),
    )
    names = (
        "pit_prior_count_1h",
        "pit_prior_amount_1h",
        "pit_prior_count_24h",
        "pit_prior_amount_24h",
        "pit_prior_amount_168h",
        "pit_distinct_senders_24h",
        "pit_distinct_senders_168h",
        "pit_steps_since_last_event",
    )
    return ",\n            ".join(fragments), names


# The columns `paysim_pre_decision_feature_sql` reads off its relation. They are exactly the seven
# Silver columns the frozen contract may read: no balance column, no label, nothing post-outcome.
PAYSIM_PRE_DECISION_SOURCE_COLUMNS: Final = (
    "source_row_number",
    "step",
    "knowledge_step",
    "transaction_type",
    "amount",
    "origin_entity_id",
    "destination_entity_id",
    "destination_entity_kind",
)
# Identity columns the projection carries alongside the ten contract fields. `step` and
# `knowledge_step` are the integer ordinals ADR-006 derives the timestamps from in Python;
# they are emitted so the caller can derive them, never so SQL can.
PAYSIM_PRE_DECISION_IDENTITY_COLUMNS: Final = (
    PAYSIM_ENTITY,
    "source_row_number",
    "step",
    "knowledge_step",
)


def paysim_pre_decision_feature_sql(relation: str) -> str:
    """One pre-decision vector per in-scope cutoff: the ten frozen contract fields, in order.

    ``relation`` is any DuckDB relation carrying ``PAYSIM_PRE_DECISION_SOURCE_COLUMNS``; the
    self-join means every history row must be present in it, so the caller is responsible for
    handing over a pool that already spans ``[cutoff_step - 168, cutoff_step]`` for every cutoff.

    This materializes the eight history fields into the offline Gold table so training and the
    online-store materialization read precomputed windows rather than recomputing them at read time
    (an anti-pattern, ADR-009). Building it here,
    from :func:`_prior_window_predicate` and :data:`PAYSIM_AMOUNT_DECIMAL_TYPE`, keeps that table
    on the shipped SQL engine: comparing it against ``features/paysim_reference.py`` is then two
    independent derivations, whereas a table built by the oracle and checked against the oracle
    would be a tautology.

    The join is bounded by the widest window and stops one step before the cutoff, so no same-step
    row can enter any aggregate; each window then narrows further inside its own ``FILTER``.
    """

    history_columns, history_names = _pre_decision_history_columns()
    if history_names != PAYSIM_HISTORY_FEATURE_NAMES:
        raise RuntimeError(
            "pre-decision projection no longer emits the frozen history fields in contract order: "
            f"{history_names} != {PAYSIM_HISTORY_FEATURE_NAMES}"
        )
    if PAYSIM_STATIC_FEATURE_NAMES != ("current_amount", "transaction_type_transfer"):
        raise RuntimeError(
            "request-time feature names changed; this projection emits current_amount/"
            f"transaction_type_transfer, not {PAYSIM_STATIC_FEATURE_NAMES}"
        )
    contract = PAYSIM_FEATURE_CONTRACT
    scorable_types = ", ".join(f"'{value}'" for value in contract.scoring_transaction_types)
    scorable_kinds = ", ".join(f"'{value}'" for value in contract.scoring_destination_kinds)
    return f"""
        SELECT
            c.{PAYSIM_ENTITY},
            c.source_row_number,
            c.step,
            c.knowledge_step,
            CAST(c.amount AS DOUBLE) AS current_amount,
            (CASE WHEN c.transaction_type = 'TRANSFER' THEN 1.0 ELSE 0.0 END)::DOUBLE
                AS transaction_type_transfer,
            {history_columns}
        FROM {relation} AS c
        LEFT JOIN {relation} AS s
            ON s.{PAYSIM_ENTITY} = c.{PAYSIM_ENTITY}
            AND s.step >= c.step - {MAX_LEAKAGE_WINDOW_STEPS}
            AND s.step <= c.step - 1
        WHERE c.transaction_type IN ({scorable_types})
          AND c.destination_entity_kind IN ({scorable_kinds})
        GROUP BY
            c.{PAYSIM_ENTITY},
            c.source_row_number,
            c.step,
            c.knowledge_step,
            c.transaction_type,
            c.amount
        ORDER BY c.step, c.source_row_number
    """


def materialize_recipient_leakage_vectors(
    connection: duckdb.DuckDBPyConnection,
    *,
    nonfraud_sample_per_group: int = 5_000,
    train_end_step: int = PAYSIM_TRAIN_END_STEP,
    validation_end_step: int = PAYSIM_VALIDATION_END_STEP,
) -> int:
    """Build a deterministic diagnostic cohort and strict/leaky recipient vectors.

    The target cohort includes every customer-destination fraud row for ``CASH_OUT`` and
    ``TRANSFER`` plus a bounded deterministic non-fraud sample per temporal split and type.
    History is computed before the target join, over every event for each selected destination.

    History uses a single range self-join rather than window frames, because the FeatureSpec v2
    eligibility predicate compares two columns (``step`` and ``knowledge_step``) between source
    and cutoff and ``RANGE BETWEEN`` can only order by one.
    """

    _validate_sample_size(nonfraud_sample_per_group)
    _validate_split_contract(train_end_step, validation_end_step)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {TARGET_TABLE} AS
        WITH assigned AS (
            SELECT
                event.source_row_number,
                event.step,
                event.type AS transaction_type,
                event.amount AS current_amount,
                event.nameDest AS destination_entity_id,
                event.isFraud AS target_label,
                CASE
                    WHEN event.step <= {train_end_step} THEN 'train'
                    WHEN event.step <= {validation_end_step} THEN 'validation'
                    ELSE 'test'
                END AS split
            FROM paysim AS event
            WHERE starts_with(event.nameDest, 'C')
              AND event.type IN ('CASH_OUT', 'TRANSFER')
        ), ranked AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY split, transaction_type, target_label
                    ORDER BY
                        (
                            source_row_number * 1103515245 + 12345
                        ) % 2147483647,
                        source_row_number
                ) AS sample_rank
            FROM assigned
        )
        SELECT
            source_row_number,
            step,
            transaction_type,
            current_amount,
            destination_entity_id,
            target_label,
            split
        FROM ranked
        WHERE target_label = 1 OR sample_rank <= {nonfraud_sample_per_group}
        """
    )

    window_columns = ",\n".join(
        _window_columns(window_steps).strip() for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    derived_columns = ",\n".join(
        _derived_window_columns(window_steps).strip() for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    history_columns = ",\n".join(
        (
            f"history.pit_prior_count_{window_steps}h, "
            f"history.pit_prior_amount_{window_steps}h, "
            f"history.max_pit_source_step_{window_steps}h, "
            f"history.future_count_{window_steps}h, "
            f"history.future_amount_{window_steps}h"
        )
        for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {VECTOR_TABLE} AS
        WITH target_destinations AS (
            SELECT DISTINCT destination_entity_id
            FROM {TARGET_TABLE}
        ), scoped_history AS (
            SELECT
                event.source_row_number,
                event.step,
                event.knowledge_step,
                event.type AS source_transaction_type,
                event.nameOrig AS origin_entity_id,
                event.nameDest AS destination_entity_id,
                event.amount
            FROM paysim AS event
            SEMI JOIN target_destinations
                ON target_destinations.destination_entity_id = event.nameDest
        ), cutoffs AS (
            SELECT
                source_row_number,
                step,
                knowledge_step,
                source_transaction_type,
                origin_entity_id,
                destination_entity_id,
                amount,
                count(*) OVER (
                    PARTITION BY destination_entity_id
                )::BIGINT AS leaky_lifetime_count,
                sum(CAST(amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})) OVER (
                    PARTITION BY destination_entity_id
                )::DOUBLE AS leaky_lifetime_amount
            FROM scoped_history
        ), windowed AS (
            SELECT
                c.source_row_number,
                c.step,
                c.source_transaction_type,
                c.origin_entity_id,
                c.destination_entity_id,
                c.amount,
                {window_columns},
                c.leaky_lifetime_count,
                c.leaky_lifetime_amount
            FROM cutoffs AS c
            LEFT JOIN scoped_history AS s
                ON s.destination_entity_id = c.destination_entity_id
                AND s.step >= c.step - {MAX_LEAKAGE_WINDOW_STEPS}
                AND s.step <= c.step + {MAX_LEAKAGE_WINDOW_STEPS}
                AND s.step <> c.step
            GROUP BY
                c.source_row_number,
                c.step,
                c.knowledge_step,
                c.source_transaction_type,
                c.origin_entity_id,
                c.destination_entity_id,
                c.amount,
                c.leaky_lifetime_count,
                c.leaky_lifetime_amount
        ), target_vectors AS (
            SELECT
                '{PAYSIM_RECIPIENT_FEATURE_VERSION}' AS feature_definition_version,
                target.source_row_number,
                target.step,
                target.split,
                target.transaction_type,
                target.target_label,
                history.origin_entity_id,
                target.destination_entity_id,
                target.current_amount,
                {history_columns},
                history.leaky_lifetime_count,
                history.leaky_lifetime_amount
            FROM windowed AS history
            JOIN {TARGET_TABLE} AS target
                ON target.source_row_number = history.source_row_number
                AND target.step = history.step
                AND target.transaction_type = history.source_transaction_type
                AND target.destination_entity_id = history.destination_entity_id
                AND target.current_amount = history.amount
        )
        SELECT
            *,
            {derived_columns}
        FROM target_vectors
        ORDER BY step, source_row_number
        """
    )
    target_result = connection.sql(f"SELECT count(*) FROM {TARGET_TABLE}").fetchone()
    vector_result = connection.sql(f"SELECT count(*) FROM {VECTOR_TABLE}").fetchone()
    target_count = int(target_result[0]) if target_result is not None else 0
    vector_count = int(vector_result[0]) if vector_result is not None else 0
    if vector_count != target_count:
        raise RuntimeError(
            f"Target/vector identity mismatch: {target_count} targets, {vector_count} vectors"
        )
    return vector_count


def _long_form_sql() -> str:
    selects: list[str] = []
    for window_steps in LEAKAGE_WINDOWS_STEPS:
        selects.append(
            f"""
            SELECT
                split,
                transaction_type,
                target_label,
                source_row_number,
                step,
                {window_steps}::BIGINT AS window_hours,
                current_amount,
                pit_prior_count_{window_steps}h AS pit_prior_count,
                pit_prior_amount_{window_steps}h AS pit_prior_amount,
                max_pit_source_step_{window_steps}h AS max_pit_source_step,
                current_inclusive_amount_{window_steps}h AS current_inclusive_amount,
                future_count_{window_steps}h AS future_count,
                future_amount_{window_steps}h AS future_amount,
                leaky_centered_amount_{window_steps}h AS leaky_centered_amount,
                leaky_lifetime_amount
            FROM {VECTOR_TABLE}
            """
        )
    return "\nUNION ALL\n".join(selects)


def recipient_strict_pit_features(
    connection: duckdb.DuckDBPyConnection,
) -> pa.Table:
    """Return the safe identity/request/PIT projection without labels or controls."""

    _require_vectors(connection)
    feature_columns = ",\n".join(STRICT_PIT_FEATURE_COLUMNS)
    return connection.sql(
        f"""
        SELECT
            feature_definition_version,
            source_row_number,
            step,
            transaction_type,
            destination_entity_id,
            current_amount,
            {feature_columns}
        FROM {VECTOR_TABLE}
        ORDER BY step, source_row_number
        """
    ).to_arrow_table()


def recipient_leakage_window_gate(
    connection: duckdb.DuckDBPyConnection,
) -> pa.Table:
    """Return a compact three-window cutoff/leakage gate."""

    _require_vectors(connection)
    return connection.sql(
        f"""
        WITH comparison AS (
            {_long_form_sql()}
        )
        SELECT
            window_hours,
            count(*) AS compared_rows,
            sum(CASE
                WHEN max_pit_source_step >= step THEN 1 ELSE 0
            END) AS pit_cutoff_violations,
            sum(CASE
                WHEN abs(current_inclusive_amount - pit_prior_amount) > 1e-9
                THEN 1 ELSE 0
            END) AS current_inclusive_changed_rows,
            sum(CASE WHEN future_count > 0 THEN 1 ELSE 0 END) AS future_read_rows,
            round(
                100.0 * sum(CASE WHEN future_count > 0 THEN 1 ELSE 0 END) / count(*),
                4
            ) AS future_read_percent,
            sum(CASE
                WHEN abs(future_amount) > 1e-9 THEN 1 ELSE 0
            END) AS future_value_changed_rows,
            sum(CASE
                WHEN abs(leaky_centered_amount - pit_prior_amount) > 1e-9
                THEN 1 ELSE 0
            END) AS positive_control_changed_rows,
            round(
                avg(
                    CAST(current_inclusive_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})
                    - CAST(pit_prior_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})
                ),
                2
            )::DOUBLE AS mean_current_contribution,
            round(avg(CAST(future_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})), 2)::DOUBLE
                AS mean_future_contribution
        FROM comparison
        GROUP BY window_hours
        ORDER BY window_hours
        """
    ).to_arrow_table()


def recipient_leakage_breakdown(
    connection: duckdb.DuckDBPyConnection,
) -> pa.Table:
    """Return window/type/label diagnostics without treating labels as history inputs."""

    _require_vectors(connection)
    return connection.sql(
        f"""
        WITH comparison AS (
            {_long_form_sql()}
        )
        SELECT
            window_hours,
            split,
            transaction_type,
            target_label,
            count(*) AS rows,
            sum(CASE WHEN pit_prior_count > 0 THEN 1 ELSE 0 END) AS pit_warm_rows,
            sum(CASE WHEN future_count > 0 THEN 1 ELSE 0 END) AS future_read_rows,
            sum(CASE
                WHEN abs(future_amount) > 1e-9 THEN 1 ELSE 0
            END) AS future_value_changed_rows,
            sum(CASE
                WHEN abs(leaky_centered_amount - pit_prior_amount) > 1e-9
                THEN 1 ELSE 0
            END) AS positive_control_changed_rows,
            round(
                avg(
                    CAST(current_inclusive_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})
                    - CAST(pit_prior_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})
                ),
                2
            )::DOUBLE AS mean_current_contribution,
            round(avg(CAST(future_amount AS {PAYSIM_AMOUNT_DECIMAL_TYPE})), 2)::DOUBLE
                AS mean_future_contribution
        FROM comparison
        GROUP BY window_hours, split, transaction_type, target_label
        ORDER BY
            window_hours,
            CASE split WHEN 'train' THEN 1 WHEN 'validation' THEN 2 ELSE 3 END,
            target_label DESC,
            transaction_type
        """
    ).to_arrow_table()


def recipient_leakage_example(
    connection: duckdb.DuckDBPyConnection,
) -> pa.Table:
    """Return one deterministic warm cutoff with future context or fail visibly."""

    _require_vectors(connection)
    table = connection.sql(
        f"""
        SELECT
            feature_definition_version,
            source_row_number,
            step,
            split,
            transaction_type,
            target_label,
            origin_entity_id,
            destination_entity_id,
            current_amount,
            pit_prior_count_1h,
            pit_prior_amount_1h,
            current_inclusive_amount_1h,
            future_count_1h,
            future_amount_1h,
            leaky_centered_amount_1h,
            pit_prior_count_24h,
            pit_prior_amount_24h,
            current_inclusive_amount_24h,
            future_count_24h,
            future_amount_24h,
            leaky_centered_amount_24h,
            pit_prior_count_168h,
            pit_prior_amount_168h,
            current_inclusive_amount_168h,
            future_count_168h,
            future_amount_168h,
            leaky_centered_amount_168h,
            leaky_lifetime_amount
        FROM {VECTOR_TABLE}
        WHERE pit_prior_count_168h > 0
          AND future_count_168h > 0
        ORDER BY
            target_label DESC,
            CASE transaction_type WHEN 'CASH_OUT' THEN 1 ELSE 2 END,
            step,
            source_row_number
        LIMIT 1
        """
    ).to_arrow_table()
    if table.num_rows != 1:
        raise RuntimeError("No recipient cutoff has both strict prior and future 168h context")
    return table


def recipient_leakage_timeline(
    connection: duckdb.DuckDBPyConnection,
) -> pa.Table:
    """Return the ±168-hour event timeline around the deterministic example."""

    example = recipient_leakage_example(connection).to_pylist()[0]
    return connection.execute(
        """
        SELECT
            history.source_row_number,
            history.step,
            history.type AS transaction_type,
            history.amount,
            history.nameOrig AS origin_entity_id,
            history.nameDest AS destination_entity_id,
            history.isFraud AS source_label,
            ?::BIGINT AS cutoff_source_row_number,
            ?::BIGINT AS cutoff_step,
            CASE
                WHEN history.source_row_number = ? THEN 'TARGET_CURRENT'
                WHEN history.step < ? THEN 'PIT_PRIOR'
                WHEN history.step > ? THEN 'FUTURE_UNAVAILABLE'
                ELSE 'SAME_STEP_EXCLUDED'
            END AS relation_to_cutoff,
            abs(history.step - ?) <= 1 AS within_1h,
            abs(history.step - ?) <= 24 AS within_24h,
            abs(history.step - ?) <= 168 AS within_168h
        FROM paysim AS history
        WHERE history.nameDest = ?
          AND history.step BETWEEN ? - 168 AND ? + 168
        ORDER BY history.step, history.source_row_number
        """,
        [
            example["source_row_number"],
            example["step"],
            example["source_row_number"],
            example["step"],
            example["step"],
            example["step"],
            example["step"],
            example["step"],
            example["destination_entity_id"],
            example["step"],
            example["step"],
        ],
    ).to_arrow_table()
