"""Frozen PaySim application FeatureSpec v2."""

from __future__ import annotations

import hashlib
import json
from typing import Final

from pit_fintech.contracts.features import FeatureSetContract, FeatureSpec

HOUR_SECONDS: Final = 60 * 60
DAY_SECONDS: Final = 24 * HOUR_SECONDS
WEEK_SECONDS: Final = 7 * DAY_SECONDS

PAYSIM_FEATURE_DEFINITION_VERSION: Final = "paysim-fraud-recipient-v2"
PAYSIM_FEATURE_SERVICE_VERSION: Final = "paysim-fraud-scoring-v1"
PAYSIM_FEATURE_CONTRACT_NAME: Final = "paysim-fraud-recipient-features"
PAYSIM_FEATURE_SOURCE: Final = "silver.paysim_transactions"
PAYSIM_LABEL_SOURCE: Final = "silver.paysim_labels"
PAYSIM_ENTITY: Final = "destination_entity_id"
PAYSIM_ENTITY_DEFINITION_VERSION: Final = "paysim-destination-customer-v1"

PAYSIM_STATIC_FEATURE_NAMES: Final = (
    "current_amount",
    "event_step",
    "transaction_type_transfer",
)
PAYSIM_HISTORY_FEATURE_NAMES: Final = (
    "pit_prior_count_1h",
    "pit_prior_amount_1h",
    "recipient_has_history_1h",
    "pit_prior_count_24h",
    "pit_prior_amount_24h",
    "recipient_has_history_24h",
    "pit_prior_count_168h",
    "pit_prior_amount_168h",
    "recipient_has_history_168h",
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
        name="event_step",
        source_column="step",
        expression="CAST(step AS DOUBLE)",
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
        name="recipient_has_history_1h",
        expression="CASE WHEN pit_prior_count_1h > 0 THEN 1 ELSE 0 END",
        aggregation="indicator",
        availability="historical_only",
        window_seconds=HOUR_SECONDS,
        dtype="int64",
        default=0,
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
        name="recipient_has_history_24h",
        expression="CASE WHEN pit_prior_count_24h > 0 THEN 1 ELSE 0 END",
        aggregation="indicator",
        availability="historical_only",
        window_seconds=DAY_SECONDS,
        dtype="int64",
        default=0,
    ),
    _spec(
        name="pit_prior_count_168h",
        expression="COUNT(prior destination events)",
        aggregation="count",
        availability="historical_only",
        window_seconds=WEEK_SECONDS,
        dtype="int64",
        default=0,
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
    _spec(
        name="recipient_has_history_168h",
        expression="CASE WHEN pit_prior_count_168h > 0 THEN 1 ELSE 0 END",
        aggregation="indicator",
        availability="historical_only",
        window_seconds=WEEK_SECONDS,
        dtype="int64",
        default=0,
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
