"""Frozen PaySim application FeatureSpec v3 (ADR-011: cold-start fan-in + recency)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Final

from pit_fintech.contracts.features import FeatureSetContract, FeatureSpec

HOUR_SECONDS: Final = 60 * 60
DAY_SECONDS: Final = 24 * HOUR_SECONDS
WEEK_SECONDS: Final = 7 * DAY_SECONDS

PAYSIM_FEATURE_DEFINITION_VERSION: Final = "paysim-fraud-recipient-v3"
PAYSIM_FEATURE_SERVICE_VERSION: Final = "paysim-fraud-scoring-v3"
PAYSIM_FEATURE_CONTRACT_NAME: Final = "paysim-fraud-recipient-features"
PAYSIM_FEATURE_SOURCE: Final = "silver.paysim_transactions"
PAYSIM_LABEL_SOURCE: Final = "silver.paysim_labels"
PAYSIM_ENTITY: Final = "destination_entity_id"
PAYSIM_ENTITY_DEFINITION_VERSION: Final = "paysim-destination-customer-v1"

# ADR-006 decision 1. Feast's `FileSource` requires real timestamp columns, but PaySim carries only
# the `step`/`knowledge_step` hour ordinals (ADR-002 decision 1). This anchor presents them as UTC
# timestamps for the Feast layer only. It is frozen: changing it changes every derived timestamp,
# and therefore every registry artifact, Gold partition and online key derived from them, so it
# requires a new ADR. It lives here because ADR-006 decision 1.7 requires exactly one
# implementation of the mapping, expressed from the contract module and reused by every consumer.
#
# What this constant is NOT: the PIT computation never reads the derived columns. Eligibility,
# window bounds and the replay tie-break stay on `(step, source_row_number)` (ADR-006 decision 1.4)
# because hour-resolution timestamps cannot express the tie-break at all -- every row in the same
# `step` maps to the same instant. A derived date is never a feature, a split boundary, or a date
# quoted in a report as if it were real (ADR-006 decision 1.2).
PAYSIM_FEAST_EPOCH_0: Final = datetime(2020, 1, 1, tzinfo=UTC)


def paysim_step_to_timestamp(step_ordinal: int) -> datetime:
    """Map an hour ordinal to its ADR-006 derived UTC timestamp, for the Feast layer only.

    `f(n) = PAYSIM_FEAST_EPOCH_0 + n hours` is strictly monotone on integers, so it is bijective
    and order-preserving over the frozen 1-743 range: it adds no information, removes none, and
    merges no two distinct steps. Used for both `event_timestamp` (from `step`) and
    `created_timestamp` (from `knowledge_step`).
    """

    return PAYSIM_FEAST_EPOCH_0 + timedelta(hours=int(step_ordinal))


# Money is summed as this DECIMAL type, never as DOUBLE. Integer-scaled addition is exact,
# associative and commutative, so a parallel hash aggregate produces the same value no matter how
# partial sums are merged; DOUBLE addition does not, which made vector_checksum drift between runs
# of identical code. Only the final projection casts back to the DOUBLE dtype the contract
# declares, so this is a numeric-stability decision, not a contract change. PaySim tops out near
# 9.2e7 per row and ~1.1e12 for a full-history sum, four orders below the ~1e16 ceiling. Enforced
# at lakehouse build time by the `amount_decimal_roundtrip_failures` quality gate.
PAYSIM_AMOUNT_DECIMAL_TYPE: Final = "DECIMAL(18,2)"

# ADR-011: `pit_steps_since_last_event` takes this sentinel when a recipient has no eligible prior
# event within the widest (168h) history window. It is strictly larger than any in-window gap (max
# window 168), so the feature is monotone in staleness: a larger value always means a colder
# recipient. It is also the contract default for the field (a cold read returns the sentinel, never
# 0 -- 0 would mean "an event just happened", the opposite signal).
PAYSIM_RECENCY_SENTINEL_STEPS: Final = 999

PAYSIM_STATIC_FEATURE_NAMES: Final = (
    "current_amount",
    "transaction_type_transfer",
)
# ADR-011 v3 history set. Non-uniform by window on purpose (nb09/nb12): count only earns a place at
# 1h/24h, amount at 1h/24h/168h; the redundant `recipient_has_history_*` flags and `event_step` were
# dropped; fan-in (`pit_distinct_senders_*`) and recency (`pit_steps_since_last_event`) were added.
PAYSIM_HISTORY_FEATURE_NAMES: Final = (
    "pit_prior_count_1h",
    "pit_prior_amount_1h",
    "pit_prior_count_24h",
    "pit_prior_amount_24h",
    "pit_prior_amount_168h",
    "pit_distinct_senders_24h",
    "pit_distinct_senders_168h",
    "pit_steps_since_last_event",
)
PAYSIM_MODEL_FEATURE_ORDER: Final = (
    *PAYSIM_STATIC_FEATURE_NAMES,
    *PAYSIM_HISTORY_FEATURE_NAMES,
)
PAYSIM_FORBIDDEN_MODEL_INPUTS: Final = (
    "isFraud",
    "isFlaggedFraud",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
)


def _spec(
    *,
    name: str,
    aggregation: str,
    dtype: str,
    default: int | float,
    availability: str,
    source_column: str | None = None,
    expression: str | None = None,
    window_seconds: int | None = None,
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        entity=PAYSIM_ENTITY,
        source=PAYSIM_FEATURE_SOURCE,
        source_column=source_column,
        expression=expression,
        window_seconds=window_seconds,
        aggregation=aggregation,
        event_time_column="step",
        availability=availability,
        dtype=dtype,
        default=default,
        version=PAYSIM_FEATURE_DEFINITION_VERSION,
    )


PAYSIM_FEATURE_SPECS: Final = (
    _spec(
        name="current_amount",
        source_column="amount",
        expression="CAST(amount AS DOUBLE)",
        aggregation="identity",
        availability="request_available",
        dtype="float64",
        default=0.0,
    ),
    _spec(
        name="transaction_type_transfer",
        source_column="transaction_type",
        expression="CASE WHEN transaction_type = 'TRANSFER' THEN 1.0 ELSE 0.0 END",
        aggregation="indicator",
        availability="request_available",
        dtype="float64",
        default=0.0,
    ),
    _spec(
        name="pit_prior_count_1h",
        expression="COUNT(prior destination events)",
        aggregation="count",
        availability="historical_only",
        window_seconds=HOUR_SECONDS,
        dtype="int64",
        default=0,
    ),
    _spec(
        name="pit_prior_amount_1h",
        source_column="amount",
        expression="COALESCE(SUM(prior destination amount), 0.0)",
        aggregation="sum",
        availability="historical_only",
        window_seconds=HOUR_SECONDS,
        dtype="float64",
        default=0.0,
    ),
    _spec(
        name="pit_prior_count_24h",
        expression="COUNT(prior destination events)",
        aggregation="count",
        availability="historical_only",
        window_seconds=DAY_SECONDS,
        dtype="int64",
        default=0,
    ),
    _spec(
        name="pit_prior_amount_24h",
        source_column="amount",
        expression="COALESCE(SUM(prior destination amount), 0.0)",
        aggregation="sum",
        availability="historical_only",
        window_seconds=DAY_SECONDS,
        dtype="float64",
        default=0.0,
    ),
    _spec(
        name="pit_prior_amount_168h",
        source_column="amount",
        expression="COALESCE(SUM(prior destination amount), 0.0)",
        aggregation="sum",
        availability="historical_only",
        window_seconds=WEEK_SECONDS,
        dtype="float64",
        default=0.0,
    ),
    # ADR-011 cold-start fan-in: distinct source accounts that paid this recipient in the window.
    # Structurally distinct from `pit_prior_count_*` (a burst from one sender and the same volume
    # from many senders read identically there, differently here). Source column `origin_entity_id`
    # is the ingested `nameOrig`; it is neither a balance column, a label nor post-outcome.
    _spec(
        name="pit_distinct_senders_24h",
        source_column="origin_entity_id",
        expression="COUNT(DISTINCT prior origin_entity_id)",
        aggregation="distinct_count",
        availability="historical_only",
        window_seconds=DAY_SECONDS,
        dtype="int64",
        default=0,
    ),
    _spec(
        name="pit_distinct_senders_168h",
        source_column="origin_entity_id",
        expression="COUNT(DISTINCT prior origin_entity_id)",
        aggregation="distinct_count",
        availability="historical_only",
        window_seconds=WEEK_SECONDS,
        dtype="int64",
        default=0,
    ),
    # ADR-011 cold-start recency: hour ordinals since the recipient's most recent prior event within
    # the 168h lookback; `PAYSIM_RECENCY_SENTINEL_STEPS` when there is none (cold). Bounded to the
    # widest window so it matches the offline pool, which reads only [cutoff - 168, cutoff).
    _spec(
        name="pit_steps_since_last_event",
        source_column="step",
        expression=(
            "COALESCE(current.step - MAX(prior destination step), PAYSIM_RECENCY_SENTINEL_STEPS)"
        ),
        aggregation="time_since_previous",
        availability="historical_only",
        window_seconds=WEEK_SECONDS,
        dtype="int64",
        default=PAYSIM_RECENCY_SENTINEL_STEPS,
    ),
)

PAYSIM_FEATURE_CONTRACT: Final = FeatureSetContract(
    name=PAYSIM_FEATURE_CONTRACT_NAME,
    version=PAYSIM_FEATURE_DEFINITION_VERSION,
    service_version=PAYSIM_FEATURE_SERVICE_VERSION,
    dataset="paysim1",
    entity=PAYSIM_ENTITY,
    entity_definition_version=PAYSIM_ENTITY_DEFINITION_VERSION,
    source=PAYSIM_FEATURE_SOURCE,
    label_source=PAYSIM_LABEL_SOURCE,
    label_column="isFraud",
    scoring_transaction_types=("CASH_OUT", "TRANSFER"),
    scoring_destination_kinds=("CUSTOMER",),
    event_time_column="step",
    event_time_unit="hour_ordinal",
    tie_break_columns=("source_row_number",),
    cutoff_policy="strict_prior_event_time",
    same_time_policy="exclude_same_event_time",
    created_time_policy="derived_knowledge_step_lte_cutoff",
    online_update_policy="score_then_update",
    feature_specs=PAYSIM_FEATURE_SPECS,
    model_feature_order=PAYSIM_MODEL_FEATURE_ORDER,
    forbidden_model_inputs=PAYSIM_FORBIDDEN_MODEL_INPUTS,
    float_tolerance=1e-6,
)


def paysim_feature_contract_checksum(
    contract: FeatureSetContract = PAYSIM_FEATURE_CONTRACT,
) -> str:
    canonical = json.dumps(
        contract.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def paysim_feature_contract_payload() -> dict[str, object]:
    payload = PAYSIM_FEATURE_CONTRACT.model_dump(mode="json")
    payload["contract_checksum"] = paysim_feature_contract_checksum()
    return payload
