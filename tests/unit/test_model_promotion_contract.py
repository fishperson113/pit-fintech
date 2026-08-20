from __future__ import annotations

from pit_fintech.cli import _model_promotion_rejection
from pit_fintech.features.paysim_specs import PAYSIM_MODEL_FEATURE_ORDER


def test_t4_v3_e4_candidate_matches_serving_contract() -> None:
    assert (
        _model_promotion_rejection(
            tags={
                "candidate_or_baseline": "candidate",
                "feature_service_version": "paysim-fraud-scoring-v3",
            },
            params={"experiment_id": "E4"},
            ordered_feature_names=PAYSIM_MODEL_FEATURE_ORDER,
        )
        is None
    )


def test_v2_model_is_rejected_before_champion_alias_move() -> None:
    rejection = _model_promotion_rejection(
        tags={
            "deployable": "true",
            "feature_service_version": "paysim-fraud-scoring-v2",
        },
        params={"experiment_id": "E4"},
        ordered_feature_names=("current_amount", "event_step"),
    )

    assert rejection is not None
    assert "feature service version" in rejection
