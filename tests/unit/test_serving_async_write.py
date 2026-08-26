from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from pit_fintech.serving import app as serving_app
from pit_fintech.serving.app import ServingSettings, create_app
from pit_fintech.serving.schemas import ScoreResponse
from pit_fintech.serving.scoring import FailurePolicy, ScoringContext


class _NeverUsedProvider:
    def get_online_features(self, *, entity_id: str, request_step: int):  # pragma: no cover
        raise AssertionError("provider should not be used by the patched scorer")

    def get_online_features_batch(
        self, *, entity_ids: tuple[str, ...], request_step: int
    ):  # pragma: no cover
        raise AssertionError("provider should not be used by the patched scorer")

    def health(self):  # pragma: no cover
        raise AssertionError("provider should not be used by the patched scorer")

    def close(self) -> None:  # pragma: no cover
        return None


def test_score_does_not_wait_for_worker_before_returning(monkeypatch) -> None:
    order: list[str] = []
    context = ScoringContext(
        provider=_NeverUsedProvider(),
        policy=FailurePolicy(),
        model=SimpleNamespace(),
        model_version="model-v1",
        deployment_id=None,
        decision_threshold=0.5,
        ordered_feature_names=(),
        feature_service_version="paysim-fraud-scoring-v3",
        feature_definition_version="paysim-destination-customer-v1",
        feature_contract_checksum="checksum",
        entity="destination_entity_id",
    )
    response = ScoreResponse(
        prediction=0,
        fraud_probability=0.1,
        decision_threshold=0.5,
        entity_id="C123",
        model_version="model-v1",
        feature_service_version=context.feature_service_version,
        feature_timestamp=None,
        materialization_watermark=None,
        feature_status="missing",
        request_id="scoring-request",
        latency_ms={
            "total": 1.0,
            "feature_retrieval": 0.1,
            "model_inference": 0.2,
            "validation": 0.0,
        },
        feature_definition_version=context.feature_definition_version,
        feature_contract_checksum=context.feature_contract_checksum,
        feature_provider="redis",
    )

    monkeypatch.setattr(serving_app, "build_scoring_context", lambda *, settings: context)
    monkeypatch.setattr(
        serving_app,
        "score_transaction",
        lambda **kwargs: order.append("score") or response,
    )
    monkeypatch.setattr(
        serving_app,
        "publish_score_event",
        lambda **kwargs: order.append("publish") or "1710000000000-0",
    )
    settings = ServingSettings(
        host="127.0.0.1",
        port=8000,
        provider_kind="redis",
        online_store_uri="redis://redis:6379/0",
        mlflow_tracking_uri="sqlite:///mlflow.db",
        registered_model_name="pit-fintech",
        feature_service_version=context.feature_service_version,
        policy=FailurePolicy(),
    )
    client = TestClient(create_app(settings=settings))

    result = client.post(
        "/score",
        json={
            "transaction_id": "async-write-test",
            "step": 744,
            "transaction_type": "TRANSFER",
            "amount": "10.00",
            "name_dest": "C123",
        },
    )

    assert result.status_code == 200
    assert order == ["score", "publish"]
    assert result.json()["online_write_status"] == "queued"
    assert result.json()["online_write_event_id"] == "1710000000000-0"
