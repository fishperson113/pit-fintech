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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pit_fintech.serving.scoring import FailurePolicy, ScoringContext

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from fastapi import FastAPI

#: Route paths, frozen so the E2E lane, the smoke target and the Compose healthcheck agree.
ROUTE_SCORE: str = "/score"
ROUTE_HEALTH_LIVE: str = "/health/live"
ROUTE_HEALTH_READY: str = "/health/ready"
ROUTE_METRICS: str = "/metrics"


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


def build_scoring_context(*, settings: ServingSettings) -> ScoringContext:
    """Resolve the champion model, threshold and provider once, at startup.

    Gate G11's second half -- "scoring tra dung active champion" -- is decided here: the version and
    the deployment id are read from the deployment manifest
    (``training/lifecycle.py: active_champion``) rather than from an alias lookup alone, so the
    response can name the manifest that authorized what it is serving.

    Raises at startup when the model's ordered feature names do not equal
    ``PAYSIM_MODEL_FEATURE_ORDER``. Guide s6.4 makes a matching model input contract a promotion
    criterion; refusing to start is the serving-side half of that, and a process that starts and
    then mis-orders a vector at request time fails silently instead.
    """

    raise NotImplementedError("T7 round-0 skeleton")


def create_app(*, settings: ServingSettings) -> FastAPI:
    """Build the FastAPI application with the score, health and metrics routes.

    Registers exactly four routes (:data:`ROUTE_SCORE`, :data:`ROUTE_HEALTH_LIVE`,
    :data:`ROUTE_HEALTH_READY`, :data:`ROUTE_METRICS`). The scoring route runs guide s9.3 steps 1-7
    via ``scoring.score_transaction`` and does **not** commit post-event state: guide s9.3 step 8
    puts that update after the prediction and off the batch request path entirely.

    Imports FastAPI inside the body -- it is the optional ``serving`` group.
    """

    raise NotImplementedError("T7 round-0 skeleton")


def liveness() -> dict[str, object]:
    """``/health/live`` -- the process is up. Deliberately does not touch the online store.

    A liveness probe that depends on Redis restarts a healthy process when a dependency blips,
    which is the opposite of what it is for. Dependency state belongs to readiness.
    """

    raise NotImplementedError("T7 round-0 skeleton")


def readiness(*, context: ScoringContext) -> dict[str, object]:
    """``/health/ready`` -- guide s10.2's three conditions, reported separately.

    "Ready chi true khi model + online store + feature version load dung." Each condition is its own
    boolean in ``HealthResponse`` so a not-ready answer says which one failed, and ``ready`` is
    their conjunction rather than a field anything can set on its own.
    """

    raise NotImplementedError("T7 round-0 skeleton")


def run(*, settings: ServingSettings) -> None:
    """Serve the app with Uvicorn (single process; see the module docstring on Ray Serve)."""

    raise NotImplementedError("T7 round-0 skeleton")
