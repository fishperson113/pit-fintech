"""T7 -- FastAPI scoring service and the versioned FeatureProvider boundary (guide s9; gate G7).

Nothing here imports FastAPI, Uvicorn, Redis or Feast at module scope: they are optional dependency
groups, and the correctness lanes (``test-unit``, ``test-temporal``) must stay importable without
them (ADR-006 consequences).
"""

from pit_fintech.serving.feature_provider import (
    FeastFeatureProvider,
    FeatureProvider,
    FeatureVectorResponse,
    ProviderHealth,
    RedisFeatureProvider,
    SqliteFeatureProvider,
    UpstashFeatureProvider,
    build_feature_provider,
)
from pit_fintech.serving.schemas import (
    ErrorResponse,
    FeatureStatusLiteral,
    HealthResponse,
    LatencyBreakdown,
    ScoreRequest,
    ScoreResponse,
    derive_entity_id,
)
from pit_fintech.serving.scoring import (
    FailurePolicy,
    ScoringContext,
    VersionCheck,
    build_model_vector,
    check_versions,
    commit_post_event_state,
    derive_request_features,
    score_transaction,
)

__all__ = [
    "ErrorResponse",
    "FailurePolicy",
    "FeastFeatureProvider",
    "FeatureProvider",
    "FeatureStatusLiteral",
    "FeatureVectorResponse",
    "HealthResponse",
    "LatencyBreakdown",
    "ProviderHealth",
    "RedisFeatureProvider",
    "ScoreRequest",
    "ScoreResponse",
    "ScoringContext",
    "SqliteFeatureProvider",
    "UpstashFeatureProvider",
    "VersionCheck",
    "build_feature_provider",
    "build_model_vector",
    "check_versions",
    "commit_post_event_state",
    "derive_entity_id",
    "derive_request_features",
    "score_transaction",
]
