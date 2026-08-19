from __future__ import annotations

from typer.testing import CliRunner

from pit_fintech.cli import app
from pit_fintech.config import Settings
from pit_fintech.data.paysim import (
    BALANCE_COLUMNS,
    LABEL_COLUMNS,
    POLICY_OUTPUT_COLUMNS,
)
from pit_fintech.features.paysim_recipient import (
    PAYSIM_RECIPIENT_FEATURE_VERSION,
    STRICT_PIT_FEATURE_COLUMNS,
)
from pit_fintech.features.paysim_specs import (
    DAY_SECONDS,
    HOUR_SECONDS,
    PAYSIM_ENTITY,
    PAYSIM_ENTITY_DEFINITION_VERSION,
    PAYSIM_FEATURE_CONTRACT,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SERVICE_VERSION,
    PAYSIM_FEATURE_SPECS,
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    PAYSIM_HISTORY_FEATURE_NAMES,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_RECENCY_SENTINEL_STEPS,
    PAYSIM_STATIC_FEATURE_NAMES,
    WEEK_SECONDS,
    paysim_feature_contract_checksum,
)
from pit_fintech.models.paysim_lightgbm import PIT_FEATURE_COLUMNS, STATIC_FEATURE_COLUMNS


def test_paysim_feature_contract_identity_and_temporal_policy_are_frozen() -> None:
    contract = PAYSIM_FEATURE_CONTRACT

    assert contract.version == "paysim-fraud-recipient-v3"
    assert contract.service_version == "paysim-fraud-scoring-v3"
    assert contract.dataset == "paysim1"
    assert contract.entity == "destination_entity_id"
    assert contract.entity_definition_version == "paysim-destination-customer-v1"
    assert contract.source == "silver.paysim_transactions"
    assert contract.label_source == "silver.paysim_labels"
    assert contract.label_column == "isFraud"
    assert contract.scoring_transaction_types == ("CASH_OUT", "TRANSFER")
    assert contract.scoring_destination_kinds == ("CUSTOMER",)
    assert contract.event_time_column == "step"
    assert contract.event_time_unit == "hour_ordinal"
    assert contract.tie_break_columns == ("source_row_number",)
    assert contract.cutoff_policy == "strict_prior_event_time"
    assert contract.same_time_policy == "exclude_same_event_time"
    assert contract.created_time_policy == "derived_knowledge_step_lte_cutoff"
    assert contract.online_update_policy == "score_then_update"
    assert contract.float_tolerance == 1e-6


def test_paysim_model_feature_order_is_the_frozen_v3_set() -> None:
    # ADR-011 v3: two request-time fields, then the eight non-uniform history fields.
    expected = (
        "current_amount",
        "transaction_type_transfer",
        "pit_prior_count_1h",
        "pit_prior_amount_1h",
        "pit_prior_count_24h",
        "pit_prior_amount_24h",
        "pit_prior_amount_168h",
        "pit_distinct_senders_24h",
        "pit_distinct_senders_168h",
        "pit_steps_since_last_event",
    )

    assert len(PAYSIM_FEATURE_SPECS) == 10
    assert expected == PAYSIM_MODEL_FEATURE_ORDER
    assert tuple(spec.name for spec in PAYSIM_FEATURE_SPECS) == expected
    assert PAYSIM_FEATURE_CONTRACT.model_feature_order == expected
    assert expected[2:] == PAYSIM_HISTORY_FEATURE_NAMES
    assert PAYSIM_STATIC_FEATURE_NAMES == ("current_amount", "transaction_type_transfer")
    # The M016 LightGBM spike columns are deliberately DECOUPLED from the v3 contract (they compute
    # over the leakage VECTOR_TABLE, frozen M016 evidence), so they keep the v2 shape.
    assert STATIC_FEATURE_COLUMNS == ("current_amount", "event_step", "transaction_type_transfer")
    assert PIT_FEATURE_COLUMNS[0:3] == STATIC_FEATURE_COLUMNS
    # STRICT_PIT_FEATURE_COLUMNS is the leakage diagnostic's own count/amount/has_history shape,
    # also decoupled from the contract.
    assert STRICT_PIT_FEATURE_COLUMNS == (
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


def test_paysim_feature_windows_availability_and_defaults_are_explicit() -> None:
    by_name = {spec.name: spec for spec in PAYSIM_FEATURE_SPECS}

    for name in PAYSIM_STATIC_FEATURE_NAMES:
        assert by_name[name].availability == "request_available"
        assert by_name[name].window_seconds is None
        assert by_name[name].dtype == "float64"
        assert by_name[name].default == 0.0

    expected_windows = {
        "pit_prior_count_1h": HOUR_SECONDS,
        "pit_prior_amount_1h": HOUR_SECONDS,
        "pit_prior_count_24h": DAY_SECONDS,
        "pit_prior_amount_24h": DAY_SECONDS,
        "pit_prior_amount_168h": WEEK_SECONDS,
        "pit_distinct_senders_24h": DAY_SECONDS,
        "pit_distinct_senders_168h": WEEK_SECONDS,
        "pit_steps_since_last_event": WEEK_SECONDS,
    }
    for name, window_seconds in expected_windows.items():
        assert by_name[name].availability == "historical_only"
        assert by_name[name].window_seconds == window_seconds

    # Every history field defaults to 0/0.0 except recency, which defaults to the cold sentinel.
    for name in ("pit_prior_count_1h", "pit_prior_amount_1h", "pit_distinct_senders_24h"):
        assert by_name[name].default == 0 or by_name[name].default == 0.0
    assert by_name["pit_steps_since_last_event"].default == PAYSIM_RECENCY_SENTINEL_STEPS


def test_paysim_forbidden_inputs_and_version_boundaries_are_shared() -> None:
    expected_forbidden = (
        *LABEL_COLUMNS,
        *POLICY_OUTPUT_COLUMNS,
        *BALANCE_COLUMNS,
    )

    assert expected_forbidden == PAYSIM_FORBIDDEN_MODEL_INPUTS
    assert set(PAYSIM_MODEL_FEATURE_ORDER).isdisjoint(expected_forbidden)
    assert PAYSIM_FEATURE_DEFINITION_VERSION == PAYSIM_RECIPIENT_FEATURE_VERSION
    assert PAYSIM_ENTITY == "destination_entity_id"
    assert PAYSIM_ENTITY_DEFINITION_VERSION == "paysim-destination-customer-v1"
    assert Settings.model_fields["feature_definition_version"].default == (
        PAYSIM_FEATURE_DEFINITION_VERSION
    )
    assert Settings.model_fields["feature_service_version"].default == (
        PAYSIM_FEATURE_SERVICE_VERSION
    )


def test_paysim_feature_contract_checksum_changes_with_semantics() -> None:
    baseline = paysim_feature_contract_checksum()
    modified_specs = list(PAYSIM_FEATURE_SPECS)
    modified_specs[3] = modified_specs[3].model_copy(update={"window_seconds": 2 * HOUR_SECONDS})
    modified_contract = PAYSIM_FEATURE_CONTRACT.model_copy(
        update={
            "feature_specs": tuple(modified_specs),
            "model_feature_order": tuple(spec.name for spec in modified_specs),
        }
    )

    assert len(baseline) == 64
    assert baseline != paysim_feature_contract_checksum(modified_contract)


def test_features_cli_exposes_frozen_paysim_contract() -> None:
    result = CliRunner().invoke(app, ["features", "show", "--dataset", "paysim"])

    assert result.exit_code == 0
    assert PAYSIM_FEATURE_DEFINITION_VERSION in result.stdout
    assert paysim_feature_contract_checksum() in result.stdout
    assert "PaySim FeatureSpec v3" in result.stdout
    assert "feature_count: 10" in result.stdout
    assert "isFraud" in result.stdout
