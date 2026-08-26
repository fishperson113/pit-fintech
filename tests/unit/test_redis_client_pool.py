from __future__ import annotations

import redis

from pit_fintech.materialization.materializer import OnlineStoreConfig, _redis_client
from pit_fintech.materialization.records import OnlineStoreKind


def test_redis_client_reuses_connection_pool_for_same_endpoint(monkeypatch) -> None:
    created: list[object] = []

    class FakeRedis:
        def __init__(self, **kwargs):
            created.append(self)

    monkeypatch.setattr(redis, "Redis", FakeRedis)
    store = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri="redis://127.0.0.1:6379/0",
        feature_service_version="paysim-fraud-scoring-v3",
        entity="destination_entity_id",
    )

    first = _redis_client(store)
    second = _redis_client(store)

    assert first is second
    assert len(created) == 1
