"""Independent pure-Python oracle for PaySim FeatureSpec v3 (ADR-011).

This module is the **correctness authority** for the ten features of
``paysim-fraud-recipient-v3``. The DuckDB path
(``features/paysim_recipient.py``, ``models/paysim_training.py``) must reproduce these values;
when the two disagree the SQL is wrong until proven otherwise, never this module.

It deliberately uses **no DuckDB, no SQL and no library window function**. The whole point of a
reference implementation is to be an independent second derivation of the same contract: if it ran
on the same engine as the path it checks, a shared engine bug would cancel out on both sides and
the comparison would prove nothing. Explicit Python loops are the intended trade — the oracle runs
on hand-built fixtures, not on the 6.3M-row snapshot, so being slow is acceptable and being
readable is not optional.

What it implements, verbatim from the frozen decisions:

* eligibility (ADR-003 §Temporal semantics, amended by ADR-005 decision 5)::

      prior.step           <  current.step
      AND prior.knowledge_step <= current.knowledge_step

* window (ADR-003)::

      [current_step - window_hours, current_step)

  lower bound inclusive, current event and every other same-``step`` event excluded;
* money summed in :class:`decimal.Decimal` at ``DECIMAL(18,2)``, never in ``float`` — see
  :func:`exact_money`;
* fan-in ``pit_distinct_senders_*`` = ``COUNT(DISTINCT origin_entity_id)`` over the same eligible
  window; recency ``pit_steps_since_last_event`` = ``cutoff.step - max(prior step)`` within the
  widest window, or ``PAYSIM_RECENCY_SENTINEL_STEPS`` when the recipient is cold (ADR-011);
* exactly the ten fields of ``PAYSIM_MODEL_FEATURE_ORDER``, in that order.

``step`` and ``knowledge_step`` are hour ordinals (ADR-002 decision 1). The derived
``event_timestamp``/``created_timestamp`` columns of ADR-006 exist for the Feast layer only and are
deliberately absent here: ADR-006 decision 1.3 keeps the oracle on the integer columns.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import (
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
)
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pit_fintech.features.paysim_specs import (
    HOUR_SECONDS,
    PAYSIM_FEATURE_CONTRACT,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SPECS,
    PAYSIM_HISTORY_FEATURE_NAMES,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_RECENCY_SENTINEL_STEPS,
    PAYSIM_STATIC_FEATURE_NAMES,
)

# --------------------------------------------------------------------------------------------
# Money: exact decimal arithmetic (M027)
# --------------------------------------------------------------------------------------------

MONEY_SCALE_DIGITS: Final = 2
MONEY_QUANTUM: Final = Decimal("0.01")
# DECIMAL(18,2) leaves 16 integer digits; PAYSIM_AMOUNT_DECIMAL_TYPE is the SQL-side name for the
# same type. A per-row amount outside this range is rejected here exactly as the lakehouse
# `amount_decimal_roundtrip_failures` gate rejects it there.
MONEY_MAX_EXCLUSIVE: Final = Decimal(10) ** 16
MONEY_ZERO: Final = Decimal("0.00")
# DuckDB widens SUM(DECIMAL(18,2)) to DECIMAL(38,2); this context reproduces that headroom and
# traps rather than rounds if a total ever exceeds it. Inexact/Rounded are trapped so that any
# silent loss of a cent becomes an exception instead of a wrong number.
MONEY_CONTEXT: Final = Context(
    prec=38,
    traps=[Inexact, Rounded, Overflow, DivisionByZero, InvalidOperation],
)


def exact_money(value: Decimal | int | str | float) -> Decimal:
    """Return one amount as the exact ``DECIMAL(18,2)`` value the SQL path sums.

    Floats are converted through their shortest round-tripping repr, which is the same value
    DuckDB's ``DOUBLE -> DECIMAL(18,2)`` cast produces for every amount that survives the
    lakehouse round-trip gate. An amount needing a third decimal place, or exceeding the type's
    range, is rejected instead of rounded: rounding here would make the oracle agree with a wrong
    SQL result rather than expose it.
    """

    if isinstance(value, bool):
        raise TypeError("amount must be a number, not a bool")
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"amount must be finite, received {value!r}")
        candidate = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            candidate = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"amount is not a decimal literal: {value!r}") from exc
    else:
        raise TypeError(f"unsupported amount type: {type(value).__name__}")

    if not candidate.is_finite():
        raise ValueError(f"amount must be finite, received {value!r}")
    if candidate < 0:
        raise ValueError(f"amount must be non-negative, received {value!r}")
    if candidate.copy_abs() >= MONEY_MAX_EXCLUSIVE:
        raise ValueError(
            f"amount {value!r} exceeds the DECIMAL(18,{MONEY_SCALE_DIGITS}) range that every "
            "downstream money sum is computed in"
        )
    exponent = candidate.as_tuple().exponent
    if not isinstance(exponent, int) or -exponent > MONEY_SCALE_DIGITS:
        raise ValueError(
            f"amount {value!r} needs more than {MONEY_SCALE_DIGITS} decimal places and cannot be "
            "represented exactly; the lakehouse quality gate rejects such rows for the same reason"
        )
    return candidate.quantize(MONEY_QUANTUM)


def sum_money(amounts: Iterable[Decimal]) -> Decimal:
    """Add amounts exactly, so the total is independent of accumulation order.

    Integer-scaled decimal addition is associative and commutative; ``float`` addition is neither,
    which is what made ``vector_checksum`` drift between runs of identical code (M027). Never
    replace this with ``sum()`` over floats.
    """

    total = MONEY_ZERO
    for amount in amounts:
        total = MONEY_CONTEXT.add(total, amount)
    return total


# --------------------------------------------------------------------------------------------
# Contract shape, derived from the frozen FeatureSpec rather than retyped
# --------------------------------------------------------------------------------------------


def _history_window_steps() -> tuple[int, ...]:
    """Read the window sizes out of the frozen specs, in contract order."""

    windows: list[int] = []
    for spec in PAYSIM_FEATURE_SPECS:
        if spec.availability != "historical_only":
            continue
        if spec.window_seconds is None or spec.window_seconds % HOUR_SECONDS:
            raise RuntimeError(
                f"{spec.name} has a window that is not a whole number of hour ordinals: "
                f"{spec.window_seconds}"
            )
        window_steps = spec.window_seconds // HOUR_SECONDS
        if window_steps not in windows:
            windows.append(window_steps)
    return tuple(windows)


PAYSIM_WINDOW_STEPS: Final = _history_window_steps()
WINDOW_KEYS: Final = tuple(f"{window_steps}h" for window_steps in PAYSIM_WINDOW_STEPS)


def _spec_names(availability: str) -> tuple[str, ...]:
    """The feature names of one availability class, in ``PAYSIM_FEATURE_SPECS`` order."""

    return tuple(spec.name for spec in PAYSIM_FEATURE_SPECS if spec.availability == availability)


#: The ADR-011 v3 windows this oracle computes explicitly, asserted below. The history set is
#: non-uniform by window (count at 1h/24h, amount at 1h/24h/168h, distinct-senders at 24h/168h,
#: recency once), so the field list is read straight off the specs rather than reconstructed from a
#: uniform per-window pattern.
_V3_EXPECTED_WINDOW_STEPS: Final = (1, 24, 168)


def _validate_contract_alignment() -> None:
    """Fail at import if this oracle no longer covers exactly the frozen ten fields.

    Field order is part of the contract (ADR-003 §Decision, ADR-011), so a reordered or resized
    spec must stop this module from loading rather than silently emit a differently shaped vector.
    The check compares the name tuples against the ``PAYSIM_FEATURE_SPECS`` derivation, so it is an
    independent cross-check, not a restatement of the same constant.
    """

    if _spec_names("request_available") != PAYSIM_STATIC_FEATURE_NAMES:
        raise RuntimeError(
            "request-time feature names/order no longer match the specs: "
            f"{_spec_names('request_available')} != {PAYSIM_STATIC_FEATURE_NAMES}"
        )
    if _spec_names("historical_only") != PAYSIM_HISTORY_FEATURE_NAMES:
        raise RuntimeError(
            "history feature names/order no longer match the specs: "
            f"{_spec_names('historical_only')} != {PAYSIM_HISTORY_FEATURE_NAMES}"
        )
    expected_order = (*PAYSIM_STATIC_FEATURE_NAMES, *PAYSIM_HISTORY_FEATURE_NAMES)
    if expected_order != PAYSIM_MODEL_FEATURE_ORDER:
        raise RuntimeError("model feature order is no longer request-time followed by history")
    if PAYSIM_WINDOW_STEPS != _V3_EXPECTED_WINDOW_STEPS:
        raise RuntimeError(
            "the explicit v3 compute assumes windows (1, 24, 168); the specs now declare "
            f"{PAYSIM_WINDOW_STEPS} -- update compute_paysim_feature_row alongside the specs"
        )


_validate_contract_alignment()


def paysim_destination_kind(destination_entity_id: str) -> str:
    """Classify a destination the way the Silver projection does."""

    if destination_entity_id.startswith("C"):
        return "CUSTOMER"
    if destination_entity_id.startswith("M"):
        return "MERCHANT"
    return "UNKNOWN"


# --------------------------------------------------------------------------------------------
# Source and output records
# --------------------------------------------------------------------------------------------


class PaySimSourceEvent(BaseModel):
    """One ``silver.paysim_transactions`` row, restricted to fields the contract may read.

    The four PaySim balance columns, ``isFraud`` and ``isFlaggedFraud`` are absent by
    construction: ``extra="forbid"`` makes passing one an error rather than an unused field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_row_number: int = Field(ge=1)
    step: int = Field(ge=1)
    knowledge_step: int = Field(ge=1)
    transaction_type: str = Field(min_length=1)
    amount: Decimal
    origin_entity_id: str = Field(min_length=1)
    destination_entity_id: str = Field(min_length=1)
    destination_entity_kind: str = Field(min_length=1)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Decimal | int | str | float) -> Decimal:
        return exact_money(value)

    @property
    def order_key(self) -> tuple[int, int]:
        """Deterministic replay order (ADR-002 decision 2), not an eligibility rule.

        ``source_row_number`` breaks ties within one ``step``; it never admits a same-step row into
        a feature window (ADR-003 §Temporal semantics).
        """

        return (self.step, self.source_row_number)

    @classmethod
    def from_silver_row(cls, row: Mapping[str, Any]) -> PaySimSourceEvent:
        """Build one event from a Silver row mapping, ignoring columns the contract forbids."""

        destination_entity_id = str(row["destination_entity_id"])
        return cls(
            source_row_number=int(row["source_row_number"]),
            step=int(row["step"]),
            knowledge_step=int(row["knowledge_step"]),
            transaction_type=str(row["transaction_type"]),
            amount=row["amount"],
            origin_entity_id=str(row["origin_entity_id"]),
            destination_entity_id=destination_entity_id,
            destination_entity_kind=str(
                row.get("destination_entity_kind") or paysim_destination_kind(destination_entity_id)
            ),
        )


class PaySimFeatureRow(BaseModel):
    """The ten-field vector for one cutoff, plus audit lineage for the no-future-read gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_definition_version: str
    source_row_number: int
    step: int
    knowledge_step: int
    transaction_type: str
    destination_entity_id: str
    values: dict[str, int | float]
    eligible_source_row_numbers: dict[str, tuple[int, ...]]
    max_source_step: dict[str, int | None]

    @model_validator(mode="after")
    def _validate_contract_order(self) -> PaySimFeatureRow:
        if tuple(self.values) != PAYSIM_MODEL_FEATURE_ORDER:
            raise ValueError(
                "feature vector does not match the frozen field order: "
                f"{tuple(self.values)} != {PAYSIM_MODEL_FEATURE_ORDER}"
            )
        return self

    @property
    def feature_tuple(self) -> tuple[int | float, ...]:
        """Model input in contract order, which is what a serving vector must equal."""

        return tuple(self.values[name] for name in PAYSIM_MODEL_FEATURE_ORDER)


# --------------------------------------------------------------------------------------------
# Temporal contract
# --------------------------------------------------------------------------------------------


def deduplicate_paysim_events(
    events: Iterable[PaySimSourceEvent],
) -> list[PaySimSourceEvent]:
    """Drop exact duplicate source rows, reject conflicting ones, return replay order.

    ADR-001: "Exact duplicate transaction rows are deduplicated. A duplicate ID with conflicting
    content is rejected."  ``source_row_number`` is the PaySim row identity.
    """

    by_row_number: dict[int, PaySimSourceEvent] = {}
    for event in events:
        existing = by_row_number.get(event.source_row_number)
        if existing is None:
            by_row_number[event.source_row_number] = event
        elif existing != event:
            raise ValueError(f"conflicting duplicate source_row_number={event.source_row_number}")
    return sorted(by_row_number.values(), key=lambda event: event.order_key)


def in_scoring_scope(event: PaySimSourceEvent) -> bool:
    """Report whether an event is one the frozen contract scores at all.

    ADR-003: scoring is limited to ``CASH_OUT``/``TRANSFER`` rows with a customer destination.
    History is *not* filtered this way: every prior event to the same destination counts, whatever
    its type, exactly as the SQL ``scoped_history`` CTE does.
    """

    return (
        event.transaction_type in PAYSIM_FEATURE_CONTRACT.scoring_transaction_types
        and event.destination_entity_kind in PAYSIM_FEATURE_CONTRACT.scoring_destination_kinds
    )


def eligible_history(
    cutoff: PaySimSourceEvent,
    events: Iterable[PaySimSourceEvent],
) -> list[PaySimSourceEvent]:
    """Return the source events this cutoff was allowed to know, before any window is applied.

    Both halves of the invariant, and nothing else::

        prior.step           <  current.step        -- event time (ADR-003)
        AND prior.knowledge_step <= current.knowledge_step  -- knowledge time (ADR-005 decision 5)

    ``step <`` excludes the cutoff itself and every other row in the same hour ordinal. This is the
    only place the future can enter a vector, so it is the only predicate that has to be right;
    everything downstream can only narrow this list.
    """

    return sorted(
        (
            source
            for source in events
            if source.destination_entity_id == cutoff.destination_entity_id
            and source.step < cutoff.step
            and source.knowledge_step <= cutoff.knowledge_step
        ),
        key=lambda source: source.order_key,
    )


def history_within_window(
    history: Sequence[PaySimSourceEvent],
    cutoff: PaySimSourceEvent,
    window_steps: int,
) -> list[PaySimSourceEvent]:
    """Narrow already-eligible history to ``[cutoff.step - window_steps, cutoff.step)``.

    The lower bound is inclusive (ADR-003); the upper bound is already enforced by
    :func:`eligible_history`, so this function can only ever remove rows, never add one.
    """

    lower_bound = cutoff.step - window_steps
    return [source for source in history if source.step >= lower_bound]


# --------------------------------------------------------------------------------------------
# Feature computation
# --------------------------------------------------------------------------------------------


def compute_paysim_feature_row(
    cutoff: PaySimSourceEvent,
    events: Sequence[PaySimSourceEvent],
) -> PaySimFeatureRow:
    """Compute the ten-field pre-decision vector for one cutoff event (ADR-011 v3).

    ``cutoff`` is the event being scored; ``events`` is the pool of source rows the platform may
    read from. Rows in ``events`` that fail the eligibility predicate are never touched by any
    aggregate, so no value can depend on data at or after the cutoff.

    The history set is non-uniform by window: count at 1h/24h, amount at 1h/24h/168h, fan-in
    (distinct senders) at 24h/168h, and recency once over the widest window. Every window is still a
    strict subset of :func:`eligible_history`, so the no-future-read audit lineage is complete.
    """

    history = eligible_history(cutoff, events)
    # `current_amount` is the request-time amount cast to the contract's float64 dtype, the same
    # DOUBLE the SQL projects; it is not a sum, so no accumulation happens here.
    values: dict[str, int | float] = {
        "current_amount": float(cutoff.amount),
        "transaction_type_transfer": 1.0 if cutoff.transaction_type == "TRANSFER" else 0.0,
    }
    eligible_row_numbers: dict[str, tuple[int, ...]] = {}
    max_source_step: dict[str, int | None] = {}

    count_by_window: dict[int, int] = {}
    # Only the final projection leaves the decimal domain, matching the SQL's `::DOUBLE`.
    amount_by_window: dict[int, float] = {}
    senders_by_window: dict[int, int] = {}
    for window_steps, window_key in zip(PAYSIM_WINDOW_STEPS, WINDOW_KEYS, strict=True):
        window = history_within_window(history, cutoff, window_steps)
        count_by_window[window_steps] = len(window)
        amount_by_window[window_steps] = float(sum_money(source.amount for source in window))
        senders_by_window[window_steps] = len({source.origin_entity_id for source in window})
        eligible_row_numbers[window_key] = tuple(source.source_row_number for source in window)
        max_source_step[window_key] = max((source.step for source in window), default=None)

    # Recency is bounded to the widest window so it matches the offline pool, which reads only
    # [cutoff - 168, cutoff). A recipient with no eligible prior event there is cold -> sentinel.
    widest_window = max(PAYSIM_WINDOW_STEPS)
    recency_steps = [
        source.step for source in history_within_window(history, cutoff, widest_window)
    ]
    steps_since_last = (
        cutoff.step - max(recency_steps) if recency_steps else PAYSIM_RECENCY_SENTINEL_STEPS
    )

    values["pit_prior_count_1h"] = count_by_window[1]
    values["pit_prior_amount_1h"] = amount_by_window[1]
    values["pit_prior_count_24h"] = count_by_window[24]
    values["pit_prior_amount_24h"] = amount_by_window[24]
    values["pit_prior_amount_168h"] = amount_by_window[168]
    values["pit_distinct_senders_24h"] = senders_by_window[24]
    values["pit_distinct_senders_168h"] = senders_by_window[168]
    values["pit_steps_since_last_event"] = steps_since_last

    return PaySimFeatureRow(
        feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
        source_row_number=cutoff.source_row_number,
        step=cutoff.step,
        knowledge_step=cutoff.knowledge_step,
        transaction_type=cutoff.transaction_type,
        destination_entity_id=cutoff.destination_entity_id,
        values=values,
        eligible_source_row_numbers=eligible_row_numbers,
        max_source_step=max_source_step,
    )


def compute_paysim_feature_vectors(
    events: Iterable[PaySimSourceEvent],
    *,
    scoring_scope_only: bool = True,
) -> list[PaySimFeatureRow]:
    """Compute one vector per in-scope cutoff, in ``(step, source_row_number)`` replay order.

    ``scoring_scope_only`` keeps the default cohort identical to the SQL target selection
    (``CASH_OUT``/``TRANSFER`` to a customer destination). Set it to ``False`` to compute a vector
    for every event, which is useful when a test needs to inspect a row the model never scores.
    History always spans every event to the destination regardless of this flag.
    """

    canonical_events = deduplicate_paysim_events(events)
    return [
        compute_paysim_feature_row(cutoff, canonical_events)
        for cutoff in canonical_events
        if not scoring_scope_only or in_scoring_scope(cutoff)
    ]


def assert_no_future_reads(rows: Iterable[PaySimFeatureRow]) -> None:
    """Fail if audit lineage shows a source at or after its own decision cutoff."""

    for row in rows:
        for window_key, source_step in row.max_source_step.items():
            if source_step is not None and source_step >= row.step:
                raise AssertionError(
                    f"future read for source_row_number {row.source_row_number} "
                    f"({window_key}): source step {source_step} >= cutoff step {row.step}"
                )


def canonical_feature_checksum(rows: Iterable[PaySimFeatureRow]) -> str:
    """Checksum ordered canonical JSON, so the value survives any storage format."""

    payload = [
        row.model_dump(mode="json")
        for row in sorted(rows, key=lambda item: (item.step, item.source_row_number))
    ]
    serialized = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
