from __future__ import annotations

from scripts.run_t4_training import _training_feature_service_version

from pit_fintech.features.paysim_specs import PAYSIM_FEATURE_SERVICE_VERSION


def test_t4_training_uses_active_feature_service_version() -> None:
    assert _training_feature_service_version() == PAYSIM_FEATURE_SERVICE_VERSION
    assert _training_feature_service_version() == "paysim-fraud-scoring-v3"
