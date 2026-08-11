from __future__ import annotations

from types import SimpleNamespace

import pytest

from pit_fintech.serving.model_loader import load_champion_model


class _Client:
    def __init__(self, version: object | None) -> None:
        self.version = version

    def get_model_version_by_alias(self, name: str, alias: str) -> object:
        assert name == "paysim-fraud-lightgbm"
        assert alias == "champion"
        if self.version is None:
            raise RuntimeError("alias not found")
        return self.version


def test_load_champion_resolves_alias_and_contract_artifacts() -> None:
    loaded_uris: list[str] = []

    def model_loader(uri: str) -> object:
        loaded_uris.append(uri)
        return "model-object"

    def artifact_loader(uri: str) -> dict[str, object]:
        if uri.endswith("ordered_feature_names.json"):
            return {"ordered_feature_names": ["a", "b"]}
        return {"threshold": 0.73}

    champion = load_champion_model(
        tracking_uri="sqlite:///tracking.db",
        registered_model_name="paysim-fraud-lightgbm",
        alias="champion",
        client=_Client(SimpleNamespace(version="7", run_id="run-7")),
        model_loader=model_loader,
        artifact_loader=artifact_loader,
    )

    assert champion.model == "model-object"
    assert champion.model_version == "7"
    assert champion.mlflow_run_id == "run-7"
    assert champion.model_uri == "models:/paysim-fraud-lightgbm@champion"
    assert champion.ordered_feature_names == ("a", "b")
    assert champion.decision_threshold == pytest.approx(0.73)
    assert loaded_uris == ["runs:/run-7/model"]


def test_load_champion_fails_closed_when_alias_is_missing() -> None:
    with pytest.raises(RuntimeError, match="champion alias"):
        load_champion_model(
            tracking_uri="sqlite:///tracking.db",
            registered_model_name="paysim-fraud-lightgbm",
            client=_Client(None),
        )
