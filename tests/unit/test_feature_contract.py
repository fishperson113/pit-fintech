from __future__ import annotations

from pit_fintech.features.specs import (
    FEATURE_DEFINITION_VERSION,
    FEATURE_SPECS,
    feature_definition_checksum,
)


def test_mvp_feature_scope_is_frozen() -> None:
    assert FEATURE_DEFINITION_VERSION == "fraud-history-v1"
    assert 10 <= len(FEATURE_SPECS) <= 15
    assert len({spec.name for spec in FEATURE_SPECS}) == len(FEATURE_SPECS)


def test_feature_definition_checksum_changes_with_contract() -> None:
    baseline = feature_definition_checksum()
    modified = list(FEATURE_SPECS)
    modified[0] = modified[0].model_copy(update={"window_seconds": 2 * 60 * 60})
    assert baseline != feature_definition_checksum(tuple(modified))
