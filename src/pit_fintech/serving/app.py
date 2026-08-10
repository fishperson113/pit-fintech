"""T7 -- the FastAPI scoring service (guide s9, s10.2).

Gate: **G7 Serving** -- "API tra prediction + lineage/freshness metadata" (guide s13).

FastAPI + Uvicorn is the reference serving runtime (guide s7/s9, AGENTS.md s7). No Ray Serve in
Sprint 2; it is reconsidered only after correctness passes and a benchmark shows the
single-process path is the bottleneck. The MVP deploys in one process on purpose -- guide s9:
"MVP van duoc deploy trong mot process de tranh microservice overhead."

Guide s10.2 fixes the probes: ``/health/live`` and ``/health/ready``, where ready is true only when
the model, the online store **and** the feature version all load correctly.

``fastapi`` and ``uvicorn`` are the optional ``serving`` dependency group, and ADR-006 decision 3
caps ``uvicorn[standard]`` at ``0.34.0`` because every Feast release pins it transitively and ``uv``
resolves all groups into one universe. Imports therefore stay inside function bodies and under
``TYPE_CHECKING``, so importing ``pit_fintech.serving`` never drags FastAPI into the correctness
lanes.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

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
    from pathlib import Path

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
    provider_kind: Literal["redis", "sqlite", "feast", "upstash"]
    online_store_uri: str
    feast_repo_path: Path | None
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

    Gate G11's second half -- "scoring tra dung active champion" -- would normally be decided by
    reading the deployment manifest (``training/lifecycle.py: active_champion``). That function is
    still a round-0 skeleton (``raise NotImplementedError``) and there is no MLflow model
    registry/alias anywhere in this repo -- ``train_candidate`` never calls
    ``mlflow.register_model``. So G11 cannot actually be satisfied yet: this function resolves an
    explicit MLflow *run*, not a registered/promoted *model version*, and :attr:`ScoringContext.
    model_version` carries the run id with that caveat spelled out at the call site below. This is
    a deliberate scope cut for this pass, not a silent substitution -- promotion/rollback (T4) is
    what would make G11 real.

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
    run_id = settings.mlflow_run_id or _latest_finished_run_id()

    model = mlflow.sklearn.load_model(f"runs:/{run_id}/model")

    ordered_feature_names = _load_ordered_feature_names(run_id=run_id)
    if tuple(ordered_feature_names) != PAYSIM_MODEL_FEATURE_ORDER:
        raise RuntimeError(
            "model input contract mismatch: MLflow run "
            f"{run_id} ordered_feature_names={ordered_feature_names} != "
            f"PAYSIM_MODEL_FEATURE_ORDER={PAYSIM_MODEL_FEATURE_ORDER}"
        )
    decision_threshold = _load_decision_threshold(run_id=run_id)

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
    # ADR-008: scoring reads from the serving-owned event-log store (WindowStateFeatureProvider),
    # the same independent online state the /score write path maintains -- so online read, online
    # write and the offline oracle all refer to one source. The store backend is still Redis
    # (validated above); only the provider that reads it changed.
    provider = build_feature_provider(
        kind="window_state",
        store=store,
        expected_feature_service_version=settings.feature_service_version,
    )

    return ScoringContext(
        provider=provider,
        policy=settings.policy,
        model=model,
        # No MLflow model registry/alias exists in this repo (see docstring above); the run id
        # doubles as the model version identifier for this MVP.
        model_version=run_id,
        # No deployment manifest system yet either (`training/lifecycle.py` round-0 skeleton).
        deployment_id=None,
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
    """

    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0

    def record_success(self, latency_ms: float) -> None:
        self.request_count += 1
        self.total_latency_ms += latency_ms

    def record_error(self) -> None:
        self.request_count += 1
        self.error_count += 1

    def render(self) -> str:
        average_ms = self.total_latency_ms / self.request_count if self.request_count else 0.0
        return (
            f"pit_scoring_requests_total {self.request_count}\n"
            f"pit_scoring_errors_total {self.error_count}\n"
            f"pit_scoring_latency_ms_avg {average_ms:.3f}\n"
        )


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
    from pit_fintech.serving import online_state
    from pit_fintech.serving.schemas import derive_entity_id
    from pit_fintech.serving.telemetry import configure_telemetry

    context = build_scoring_context(settings=settings)
    metrics = _MetricsState()

    # ADR-008: the serving process owns the online write path. build_scoring_context has already
    # rejected any provider_kind other than 'redis', so this store shares that endpoint/namespace.
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

    @app.post(ROUTE_SCORE)
    def score(payload: ScoreRequest):
        request_id = str(uuid.uuid4())
        try:
            with telemetry.span(
                "score",
                transaction_id=payload.transaction_id,
                entity_id=payload.name_dest,
                step=payload.step,
            ):
                response = score_transaction(request=payload, context=context)
        except VersionMismatchError as exc:
            metrics.record_error()
            logger.warning(
                "version_mismatch for transaction_id=%s: %s", payload.transaction_id, exc
            )
            return _error(
                status_code=409, code="version_mismatch", message=str(exc), request_id=request_id
            )
        except StaleFeaturesError as exc:
            metrics.record_error()
            logger.warning(
                "stale_features (fail_closed) for transaction_id=%s: %s",
                payload.transaction_id,
                exc,
            )
            return _error(
                status_code=409, code="stale_features", message=str(exc), request_id=request_id
            )
        except MissingEntityRejectedError as exc:
            metrics.record_error()
            logger.warning(
                "missing_entity_rejected for transaction_id=%s: %s", payload.transaction_id, exc
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
        # ADR-008 write path (step 8): after scoring, update the entity's online history log. This
        # runs strictly after score_transaction has read + scored, preserving read-before-write
        # (AGENTS.md s11). History counts every event to a destination regardless of type, so the
        # append is unconditional. A write failure is logged but does not fail an already-computed
        # score; the next read would then be stale, which the freshness fields already surface.
        try:
            write_started = time.perf_counter()
            with telemetry.span("online_write", entity_id=payload.name_dest, step=payload.step):
                log_length = online_state.apply_event(
                    store=online_store,
                    entity_id=derive_entity_id(name_dest=payload.name_dest),
                    step=payload.step,
                    amount=payload.amount,
                    knowledge_step=payload.knowledge_step,
                )
            telemetry.record_online_write(
                latency_ms=(time.perf_counter() - write_started) * 1000.0, log_length=log_length
            )
        except Exception as exc:
            logger.warning(
                "online write-path apply_event failed for transaction_id=%s: %s",
                payload.transaction_id,
                exc,
            )
        telemetry.record_score(
            prediction=response.prediction,
            feature_status=response.feature_status,
            latency_ms=response.latency_ms.total,
        )
        telemetry.record_online_read(latency_ms=response.latency_ms.feature_retrieval)
        metrics.record_success(response.latency_ms.total)
        return JSONResponse(status_code=200, content=response.model_dump(mode="json"))

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
