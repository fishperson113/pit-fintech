"""T7 -- the FastAPI scoring service (guide s9, s10.2).

Gate: **G7 Serving** -- "API tra prediction + lineage/freshness metadata" (guide s13).

FastAPI + Uvicorn is the reference serving runtime (guide s7/s9, AGENTS.md s7). No Ray Serve in
Sprint 2; it is reconsidered only after correctness passes and a benchmark shows the
single-process path is the bottleneck. The MVP deploys in one process on purpose -- guide s9:
"MVP van duoc deploy trong mot process de tranh microservice overhead."

Guide s10.2 fixes the probes: ``/health/live`` and ``/health/ready``, where ready is true only when
the model, the online store **and** the feature version all load correctly.

``fastapi`` and ``uvicorn`` are the optional ``serving`` dependency group. ``uvicorn[standard]`` is
pinned at ``0.34.0`` -- a cap inherited from the now-removed Feast dependency (ADR-012); kept
pending review. Imports stay inside function bodies and under ``TYPE_CHECKING``, so importing
``pit_fintech.serving`` never drags FastAPI into the correctness lanes.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from pit_fintech.features.paysim_specs import PAYSIM_FEATURE_DEFINITION_VERSION
from pit_fintech.platform.logging_config import bind_request_context, clear_request_context
from pit_fintech.serving.events import publish_score_event, wait_for_score_result
from pit_fintech.serving.feature_provider import FeatureVectorResponse
from pit_fintech.serving.schemas import ErrorResponse, HealthResponse, ScoreRequest
from pit_fintech.serving.scoring import (
    FailurePolicy,
    MissingEntityRejectedError,
    ScoringContext,
    StaleFeaturesError,
    VersionMismatchError,
    score_transaction,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

#: Route paths, frozen so the E2E lane, the smoke target and the Compose healthcheck agree.
ROUTE_SCORE: str = "/score"
ROUTE_HEALTH_LIVE: str = "/health/live"
ROUTE_HEALTH_READY: str = "/health/ready"
ROUTE_METRICS: str = "/metrics"

#: MLflow experiment name `scripts/run_t4_training.py` passes to `train_candidate(...,
#: experiment_name=...)`. Neither `training/pipeline.py` nor `scripts/run_t4_training.py` declares
#: this as an importable constant (it is a literal at the one call site), and this file is out of
#: scope to edit, so it is necessarily duplicated here rather than imported.
TRAINING_EXPERIMENT_NAME: Final = "pit-fintech-gold-training"


@dataclass(frozen=True, slots=True, kw_only=True)
class ServingSettings:
    """Startup configuration for one scoring process.

    ``model_alias="champion"`` is the deployable alias (guide s6.4). ``model_version`` overrides it
    with an explicit version -- guide s6.4 forbids resolving ``latest``, and pinning a version is
    how a rollback is served without retraining.
    """

    host: str
    port: int
    provider_kind: Literal["redis", "sqlite", "upstash"]
    online_store_uri: str
    mlflow_tracking_uri: str
    registered_model_name: str
    model_alias: str = "champion"
    model_version: int | None = None
    feature_service_version: str
    policy: FailurePolicy
    log_json: bool = True
    #: Explicit MLflow run id to serve. There is no model registry/alias in this repo yet
    #: (`training/lifecycle.py: active_champion` is still a round-0 skeleton), so ``model_alias``/
    #: ``model_version`` above cannot be resolved through the registry. When ``None``,
    #: :func:`build_scoring_context` falls back to the latest ``FINISHED`` run in
    #: :data:`TRAINING_EXPERIMENT_NAME`.
    mlflow_run_id: str | None = None

    # --- OpenTelemetry (ADR-008 observability; optional, off by default) ------------------------
    #: When true, traces + metrics are exported over OTLP/HTTP to :attr:`otel_endpoint` and logs are
    #: emitted with trace correlation. The OTel packages are NOT project dependencies (they are not
    #: in pyproject, to keep the ADR-004 component fingerprints stable); install them into the
    #: serving env manually. When they are absent, telemetry silently no-ops.
    otel_enabled: bool = False
    otel_service_name: str = "pit-fintech-serving"
    #: OTLP/HTTP collector endpoint (e.g. ``http://<collector-host>:4318``). When ``None``, the
    #: standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable is used.
    otel_endpoint: str | None = None


def build_scoring_context(*, settings: ServingSettings) -> ScoringContext:
    """Resolve the champion model, threshold and provider once, at startup.

    With no explicit ``mlflow_run_id``, serving resolves the MLflow registry alias configured by
    ``model_alias`` (default ``champion``) and fails closed when that alias is absent. An explicit
    run id remains available for controlled local diagnostics and backward-compatible test fixtures;
    it does not change the production default away from the champion alias.

    Raises at startup when the model's ordered feature names do not equal
    ``PAYSIM_MODEL_FEATURE_ORDER``. Guide s6.4 makes a matching model input contract a promotion
    criterion; refusing to start is the serving-side half of that, and a process that starts and
    then mis-orders a vector at request time fails silently instead.
    """

    import mlflow
    import mlflow.sklearn

    from pit_fintech.features.paysim_specs import (
        PAYSIM_ENTITY,
        PAYSIM_FEATURE_DEFINITION_VERSION,
        PAYSIM_MODEL_FEATURE_ORDER,
        paysim_feature_contract_checksum,
    )
    from pit_fintech.materialization.materializer import OnlineStoreConfig
    from pit_fintech.materialization.records import OnlineStoreKind
    from pit_fintech.serving.feature_provider import build_feature_provider

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    champion = None
    if settings.mlflow_run_id is None:
        from pit_fintech.serving.model_loader import load_champion_model

        champion = load_champion_model(
            tracking_uri=settings.mlflow_tracking_uri,
            registered_model_name=settings.registered_model_name,
            alias=settings.model_alias,
        )
        run_id = champion.mlflow_run_id
        model = champion.model
        ordered_feature_names = champion.ordered_feature_names
        decision_threshold = champion.decision_threshold
    else:
        run_id = settings.mlflow_run_id
        model = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
        ordered_feature_names = _load_ordered_feature_names(run_id=run_id)
        decision_threshold = _load_decision_threshold(run_id=run_id)
    if tuple(ordered_feature_names) != PAYSIM_MODEL_FEATURE_ORDER:
        raise RuntimeError(
            "model input contract mismatch: MLflow run "
            f"{run_id} ordered_feature_names={ordered_feature_names} != "
            f"PAYSIM_MODEL_FEATURE_ORDER={PAYSIM_MODEL_FEATURE_ORDER}"
        )

    if settings.provider_kind != "redis":
        # build_feature_provider() would raise this same NotImplementedError itself, but raising
        # it here names ServingSettings.provider_kind explicitly rather than an assembled store.
        raise NotImplementedError(
            f"ServingSettings.provider_kind={settings.provider_kind!r} is not wired up in this "
            "pass; only 'redis' is (see serving.feature_provider.build_feature_provider)"
        )
    store = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=settings.online_store_uri,
        feature_service_version=settings.feature_service_version,
        entity=PAYSIM_ENTITY,
    )
    # ADR-009: scoring reads the materialized aggregate (RedisFeatureProvider) -- the online store
    # is a precomputed aggregate for fast reads. The serving write path (serving/online_state.py)
    # advances that aggregate and parity-checks it at write time; the read path does not recompute
    # (read-time recomputation is an anti-pattern, ADR-009).
    provider = build_feature_provider(
        kind="redis",
        store=store,
        expected_feature_service_version=settings.feature_service_version,
    )

    return ScoringContext(
        provider=provider,
        policy=settings.policy,
        model=model,
        model_version=(
            f"{settings.registered_model_name}@{champion.model_version}" if champion else run_id
        ),
        deployment_id=(
            f"{settings.registered_model_name}:{champion.model_version}" if champion else None
        ),
        decision_threshold=decision_threshold,
        ordered_feature_names=ordered_feature_names,
        feature_service_version=settings.feature_service_version,
        feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
        feature_contract_checksum=paysim_feature_contract_checksum(),
        entity=PAYSIM_ENTITY,
    )


def _latest_finished_run_id(*, experiment_name: str = TRAINING_EXPERIMENT_NAME) -> str:
    """Fall back for ``ServingSettings.mlflow_run_id=None``: newest ``FINISHED`` run by start time.

    There is no model registry alias to resolve instead (see :func:`build_scoring_context`), so
    "latest" here means exactly that -- the most recently *started* finished run -- not a promoted
    version. Raises with an actionable message rather than returning ``None`` silently.
    """

    import mlflow

    runs = mlflow.search_runs(
        experiment_names=[experiment_name],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["start_time DESC"],
        max_results=1,
        output_format="list",
    )
    if not runs:
        raise RuntimeError(
            f"no FINISHED MLflow run found in experiment {experiment_name!r}; train a candidate "
            "first (.\\make.ps1 train-gold-candidate) or pass ServingSettings.mlflow_run_id "
            "explicitly"
        )
    return runs[0].info.run_id


def _load_decision_threshold(*, run_id: str) -> float:
    """Read the validation-selected threshold ``train_candidate`` logged for this run.

    Falls back to ``0.5`` with a logged warning rather than failing startup -- the threshold
    changes which side of a probability a prediction lands on, not whether scoring is possible at
    all, so an MVP demo can still run without it (loudly, not silently).
    """

    import mlflow.artifacts

    try:
        payload = mlflow.artifacts.load_dict(f"runs:/{run_id}/confusion_and_cost_curves.json")
        return float(payload["threshold"])
    except Exception as exc:
        logger.warning(
            "could not read decision threshold from run %s confusion_and_cost_curves.json (%s); "
            "falling back to 0.5",
            run_id,
            exc,
        )
        return 0.5


def _load_ordered_feature_names(*, run_id: str) -> tuple[str, ...]:
    """Read the feature order ``train_candidate`` logged the model as trained on.

    Falls back to ``PAYSIM_MODEL_FEATURE_ORDER`` with a logged warning;
    :func:`build_scoring_context` still checks the result against that same constant right after
    calling this, so a genuine mismatch is caught either way -- this fallback only covers the
    artifact being unreadable, not a real contract drift.
    """

    import mlflow.artifacts

    from pit_fintech.features.paysim_specs import PAYSIM_MODEL_FEATURE_ORDER

    try:
        payload = mlflow.artifacts.load_dict(f"runs:/{run_id}/ordered_feature_names.json")
        return tuple(payload["ordered_feature_names"])
    except Exception as exc:
        logger.warning(
            "could not read ordered_feature_names.json from run %s (%s); falling back to "
            "PAYSIM_MODEL_FEATURE_ORDER",
            run_id,
            exc,
        )
        return PAYSIM_MODEL_FEATURE_ORDER


@dataclass
class _MetricsState:
    """In-process counters for :data:`ROUTE_METRICS`.

    Not Prometheus (design point 7 allows plain text): one FastAPI process, one counter set, reset
    on restart. Good enough for a demo; a real deployment would export this via
    ``prometheus_client`` instead of hand-rolling text.

    Parity is NOT in these counters: the write path is non-blocking and never runs the offline
    engine (ADR-009 as amended), so serving does not observe parity. Offline/online parity is
    verified asynchronously by `pit parity reconcile`, which exports `pit_parity_*` OTel metrics
    itself.
    """

    request_count: int = 0
    error_count: int = 0
    success_count: int = 0
    total_latency_ms: float = 0.0
    latency_bucket_counts: dict[float, int] = field(default_factory=dict)

    LATENCY_BUCKETS: ClassVar[tuple[float, ...]] = (
        1.0,
        2.0,
        5.0,
        10.0,
        25.0,
        50.0,
        100.0,
        250.0,
        500.0,
        1000.0,
        2500.0,
        5000.0,
        float("inf"),
    )

    def record_success(self, latency_ms: float) -> None:
        self.request_count += 1
        self.success_count += 1
        self.total_latency_ms += latency_ms
        for upper_bound in self.LATENCY_BUCKETS:
            if latency_ms <= upper_bound:
                self.latency_bucket_counts[upper_bound] = (
                    self.latency_bucket_counts.get(upper_bound, 0) + 1
                )

    def record_error(self) -> None:
        self.request_count += 1
        self.error_count += 1

    def render(self) -> str:
        average_ms = self.total_latency_ms / self.success_count if self.success_count else 0.0
        lines = [
            f"pit_scoring_requests_total {self.request_count}\n"
            f"pit_scoring_errors_total {self.error_count}\n"
            f"pit_scoring_latency_ms_avg {average_ms:.3f}\n"
        ]
        for upper_bound in self.LATENCY_BUCKETS:
            le = "+Inf" if upper_bound == float("inf") else f"{upper_bound:g}"
            count = self.latency_bucket_counts.get(upper_bound, 0)
            lines.append(f'pit_scoring_latency_ms_bucket{{le="{le}"}} {count}\n')
        lines.append(f"pit_scoring_latency_ms_count {self.success_count}\n")
        lines.append(f"pit_scoring_latency_ms_sum {self.total_latency_ms:.3f}\n")
        return "".join(lines)


def create_app(*, settings: ServingSettings) -> FastAPI:
    """Build the FastAPI application with the score, health and metrics routes.

    Registers exactly four routes (:data:`ROUTE_SCORE`, :data:`ROUTE_HEALTH_LIVE`,
    :data:`ROUTE_HEALTH_READY`, :data:`ROUTE_METRICS`). The scoring route runs guide s9.3 steps 1-7
    via ``scoring.score_transaction`` and does **not** commit post-event state: guide s9.3 step 8
    puts that update after the prediction and off the batch request path entirely.

    Imports FastAPI inside the body -- it is the optional ``serving`` group.
    """

    import time

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, PlainTextResponse

    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY
    from pit_fintech.materialization.materializer import OnlineStoreConfig
    from pit_fintech.materialization.records import OnlineStoreKind
    from pit_fintech.serving.schemas import derive_entity_id
    from pit_fintech.serving.telemetry import configure_telemetry

    context = build_scoring_context(settings=settings)
    metrics = _MetricsState()

    # ADR-010: the serving process is a publisher, never a store mutator. This store is only used
    # to publish score events and poll worker results; the pit-online-worker owns the online-store
    # mutation. build_scoring_context has already rejected any provider_kind other than 'redis', so
    # this store shares that endpoint/namespace.
    online_store = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=settings.online_store_uri,
        feature_service_version=settings.feature_service_version,
        entity=PAYSIM_ENTITY,
    )

    # ADR-008 observability: OTLP traces/metrics + trace-correlated logs to the user's collector.
    # A no-op when otel_enabled is false or the OpenTelemetry packages are not installed.
    telemetry = configure_telemetry(
        service_name=settings.otel_service_name,
        endpoint=settings.otel_endpoint,
        enabled=settings.otel_enabled,
    )

    app = FastAPI(title="pit-fintech scoring", version=context.model_version)
    app.state.scoring_context = context
    app.state.metrics = metrics
    app.state.telemetry = telemetry
    telemetry.instrument_fastapi(app)

    def _error(*, status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
        error = ErrorResponse(
            code=code,  # type: ignore[arg-type]
            message=message,
            request_id=request_id,
            feature_service_version=context.feature_service_version,
            model_version=context.model_version,
        )
        return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))

    def _result_to_features(result: dict, *, entity_id: str) -> FeatureVectorResponse:
        """Build a FeatureVectorResponse from the worker's pre-decision result (ADR-010)."""

        from pit_fintech.materialization.records import FeatureStatus

        feature_status = (
            FeatureStatus.FRESH
            if result.get("feature_status") == "fresh"
            else FeatureStatus.MISSING
        )
        feature_timestamp = result.get("feature_timestamp")
        return FeatureVectorResponse(
            entity_id=entity_id,
            entity=settings.feature_service_version,
            values=result.get("feature_values", {}),
            status=feature_status,
            is_cold_start=feature_status is FeatureStatus.MISSING,
            feature_service_version=settings.feature_service_version,
            feature_definition_version=result.get(
                "feature_definition_version", PAYSIM_FEATURE_DEFINITION_VERSION
            ),
            feature_contract_checksum=result.get("feature_contract_checksum", ""),
            feature_step=result.get("feature_step"),
            feature_timestamp=datetime.fromisoformat(feature_timestamp)
            if feature_timestamp
            else None,
            materialization_watermark_step=result.get("materialization_watermark_step"),
            materialization_watermark=None,
            staleness_steps=result.get("staleness_steps"),
            provider_name="pit-online-worker",
            retrieval_latency_ms=0.0,
        )

    def _score_request(*, request_id: str, payload: ScoreRequest) -> JSONResponse:
        """Score one request: publish -> wait for worker -> score on the fresh pre-decision vector.

        ADR-010: `/score` is a publisher, never a store mutator. It publishes the event to the
        Redis Stream and waits for the `pit-online-worker` to apply it (under the optimistic lock)
        and return the **pre-decision** feature vector. The request then scores on that vector --
        never a stale version, never a current-inclusive one. The whole body runs inside the
        ``score`` span so every log line carries the active ``trace_id``/``span_id``.
        """
        with telemetry.span(
            "score",
            transaction_id=payload.transaction_id,
            entity_id=payload.name_dest,
            step=payload.step,
        ):
            try:
                entity_id = derive_entity_id(name_dest=payload.name_dest)
                publish_started = time.perf_counter()
                with telemetry.span(
                    "online_publish", entity_id=payload.name_dest, step=payload.step
                ):
                    publish_score_event(
                        store=online_store,
                        feature_service_version=settings.feature_service_version,
                        request_id=request_id,
                        transaction_id=payload.transaction_id,
                        entity_id=entity_id,
                        step=payload.step,
                        knowledge_step=payload.knowledge_step,
                        transaction_type=payload.transaction_type,
                        amount=payload.amount,
                        # ADR-011 fan-in: the sender (PaySim nameOrig). Empty when a client omits it
                        # (e.g. a synthetic demo request) -- the winlog then records no sender for
                        # this event, which under-counts a future cutoff's distinct senders rather
                        # than fabricating one.
                        origin_entity_id=payload.name_orig or "",
                    )
                publish_ms = (time.perf_counter() - publish_started) * 1000.0

                with telemetry.span("online_wait", entity_id=payload.name_dest, step=payload.step):
                    result = wait_for_score_result(
                        store=online_store,
                        feature_service_version=settings.feature_service_version,
                        request_id=request_id,
                    )
                if result is None:
                    metrics.record_error()
                    logger.warning(
                        "online write path timed out waiting for worker for transaction_id=%s "
                        "entity=%s publish_ms=%.2f",
                        payload.transaction_id,
                        payload.name_dest,
                        publish_ms,
                    )
                    return _error(
                        status_code=503,
                        code="online_store_timeout",
                        message="worker did not apply the event within the timeout",
                        request_id=request_id,
                    )
                if result.get("status") == "error":
                    metrics.record_error()
                    logger.warning(
                        "worker reported an error for transaction_id=%s: %s",
                        payload.transaction_id,
                        result.get("error"),
                    )
                    return _error(
                        status_code=503,
                        code="online_store_timeout",
                        message=result.get("error", "worker error"),
                        request_id=request_id,
                    )
                if result.get("status") == "not_warm_started":
                    logger.warning(
                        "online write path refused (not warm-started) for transaction_id=%s "
                        "entity=%s: %s",
                        payload.transaction_id,
                        payload.name_dest,
                        result.get("detail"),
                    )

                prefetched = _result_to_features(result, entity_id=entity_id)
                response = score_transaction(
                    request=payload, context=context, prefetched=prefetched
                )
            except VersionMismatchError as exc:
                metrics.record_error()
                logger.warning(
                    "version_mismatch for transaction_id=%s: %s", payload.transaction_id, exc
                )
                return _error(
                    status_code=409,
                    code="version_mismatch",
                    message=str(exc),
                    request_id=request_id,
                )
            except StaleFeaturesError as exc:
                metrics.record_error()
                logger.warning(
                    "stale_features (fail_closed) for transaction_id=%s: %s",
                    payload.transaction_id,
                    exc,
                )
                return _error(
                    status_code=409,
                    code="stale_features",
                    message=str(exc),
                    request_id=request_id,
                )
            except MissingEntityRejectedError as exc:
                metrics.record_error()
                logger.warning(
                    "missing_entity_rejected for transaction_id=%s: %s",
                    payload.transaction_id,
                    exc,
                )
                return _error(
                    status_code=422,
                    code="missing_entity_rejected",
                    message=str(exc),
                    request_id=request_id,
                )
            except Exception as exc:
                metrics.record_error()
                logger.exception(
                    "online_store_timeout (or model failure) for transaction_id=%s",
                    payload.transaction_id,
                )
                return _error(
                    status_code=503,
                    code="online_store_timeout",
                    message=str(exc),
                    request_id=request_id,
                )
            telemetry.record_score(
                prediction=response.prediction,
                feature_status=response.feature_status,
                latency_ms=response.latency_ms.total,
            )
            telemetry.record_online_read(latency_ms=response.latency_ms.feature_retrieval)
            metrics.record_success(response.latency_ms.total)
            return JSONResponse(status_code=200, content=response.model_dump(mode="json"))

    @app.post(ROUTE_SCORE)
    def score(payload: ScoreRequest):
        request_id = str(uuid.uuid4())
        bind_request_context(
            request_id=request_id,
            transaction_id=payload.transaction_id,
            entity_id=derive_entity_id(name_dest=payload.name_dest),
            step=payload.step,
            knowledge_step=payload.knowledge_step,
            feature_service_version=context.feature_service_version,
            model_version=context.model_version,
        )
        try:
            return _score_request(request_id=request_id, payload=payload)
        finally:
            clear_request_context()

    @app.get(ROUTE_HEALTH_LIVE)
    def health_live() -> HealthResponse:
        return HealthResponse(**liveness(feature_service_version=context.feature_service_version))

    @app.get(ROUTE_HEALTH_READY)
    def health_ready():
        payload = readiness(context=context)
        status_code = 200 if payload["ready"] else 503
        return JSONResponse(
            status_code=status_code, content=HealthResponse(**payload).model_dump(mode="json")
        )

    @app.get(ROUTE_METRICS)
    def metrics_endpoint():
        return PlainTextResponse(metrics.render())

    return app


def liveness(*, feature_service_version: str) -> dict[str, object]:
    """``/health/live`` -- the process is up. Deliberately does not touch the online store.

    A liveness probe that depends on Redis restarts a healthy process when a dependency blips,
    which is the opposite of what it is for. Dependency state belongs to readiness.

    Takes ``feature_service_version`` as a parameter (the round-0 skeleton declared this function
    with no arguments) because :class:`~pit_fintech.serving.schemas.HealthResponse` requires that
    field on every response, live or ready; passing the already-known value in is still "does not
    touch the online store" -- it is a constant from the process's own settings, not a lookup.
    """

    return {
        "status": "live",
        "live": True,
        "ready": False,
        "model_loaded": False,
        "online_store_reachable": False,
        "feature_version_matches": False,
        "model_version": None,
        "feature_service_version": feature_service_version,
        "materialization_watermark_step": None,
        "detail": "process is running",
    }


def readiness(*, context: ScoringContext) -> dict[str, object]:
    """``/health/ready`` -- guide s10.2's three conditions, reported separately.

    "Ready chi true khi model + online store + feature version load dung." Each condition is its own
    boolean in ``HealthResponse`` so a not-ready answer says which one failed, and ``ready`` is
    their conjunction rather than a field anything can set on its own.
    """

    provider_health = context.provider.health()
    model_loaded = context.model is not None
    ready = (
        model_loaded
        and provider_health.reachable
        and provider_health.feature_service_version_matches
    )
    return {
        "status": "ready" if ready else "not_ready",
        "live": True,
        "ready": ready,
        "model_loaded": model_loaded,
        "online_store_reachable": provider_health.reachable,
        "feature_version_matches": provider_health.feature_service_version_matches,
        "model_version": context.model_version,
        "feature_service_version": context.feature_service_version,
        "materialization_watermark_step": provider_health.watermark_step,
        "detail": provider_health.detail,
    }


def run(*, settings: ServingSettings) -> None:
    """Serve the app with Uvicorn (single process; see the module docstring on Ray Serve)."""

    import uvicorn

    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
