"""T7 -- the scoring order and the failure policy (guide s9.3, s9.4).

Gate: **G7 Serving** (guide s13).

Guide s9.3 fixes the order of a scored request, and it is not negotiable because step 8 is where
the project's central invariant lives:

1. validate request;
2. derive entity id and request features via the shared contract;
3. retrieve history features;
4. check version and freshness;
5. build the ordered model vector;
6. score;
7. emit structured log and metrics;
8. in replay/streaming mode, update post-event state **after** the prediction exists. A
   batch-serving MVP may take the update off the request path entirely.

Step 8 restates ADR-003 ("Online execution must be ``read history -> score current event -> update
state``") and AGENTS.md s11 ("Query/score online phai xay ra truoc khi event hien tai update
state"). Reversing it makes an event part of its own history -- the current-inclusive leak that
experiment E2 exists to measure, not to ship.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pit_fintech.materialization.records import FeatureStatus
from pit_fintech.serving.feature_provider import FeatureProvider, FeatureVectorResponse
from pit_fintech.serving.schemas import (
    LatencyBreakdown,
    ScoreRequest,
    ScoreResponse,
    derive_entity_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class FailurePolicy:
    """Guide s9.4, as configuration rather than scattered branches.

    * :attr:`on_missing_entity` -- "defined cold-start defaults hoac reject, khong random fill".
      Default is ``"cold_start_defaults"``: ADR-003 built ``recipient_has_history_*`` precisely so a
      cold start is visible in the vector instead of hidden.
    * :attr:`on_stale_features` -- guide s9.4 makes the demo default fail-open **with a logged
      warning**, and the response always flags the staleness either way.
    * version mismatch is **not** configurable. Guide s9.4 says fail-closed, full stop: serving a
      vector built under one feature version through a model trained on another produces a number
      with no defined meaning.
    * :attr:`online_store_timeout_retries` / :attr:`online_store_timeout_seconds` -- bounded retry
      then ``503``. Never fall back to an unversioned local cache (guide s9.4).
    """

    on_missing_entity: Literal["cold_start_defaults", "reject"] = "cold_start_defaults"
    on_stale_features: Literal["fail_open", "fail_closed"] = "fail_open"
    online_store_timeout_retries: int = 2
    online_store_timeout_seconds: float = 2.0
    log_stale_warning: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoringContext:
    """Everything a scoring call needs, resolved once at startup rather than per request.

    Resolving the model version and threshold at startup is what makes
    :attr:`deployment_id` meaningful: G11 asks that scoring return the *active champion*, and a
    per-request ``latest`` lookup would make the answer depend on when the request arrived.
    """

    provider: FeatureProvider
    policy: FailurePolicy
    #: The loaded scikit-learn/LightGBM estimator (``.predict_proba``). Typed ``Any`` rather than
    #: imported from ``lightgbm``/``sklearn`` at module scope, so importing this module never pulls
    #: in the ``training``/``tracking`` optional dependency groups (module docstring).
    model: Any
    model_version: str
    deployment_id: str | None
    decision_threshold: float
    ordered_feature_names: tuple[str, ...]
    feature_service_version: str
    feature_definition_version: str
    feature_contract_checksum: str
    entity: str


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionCheck:
    """Step 4 of guide s9.3, kept separate so fail-closed cannot be skipped by a fast path."""

    matches: bool
    expected_feature_service_version: str
    observed_feature_service_version: str
    expected_contract_checksum: str
    observed_contract_checksum: str
    detail: str


class VersionMismatchError(RuntimeError):
    """Guide s9.4: version mismatch is fail-closed and not configurable by :class:`FailurePolicy`.

    Raised by :func:`score_transaction`; the FastAPI route layer (``app.py``) is the only place
    that turns this into an HTTP response, so :func:`score_transaction` itself never has to decide
    a status code.
    """

    def __init__(self, check: VersionCheck) -> None:
        super().__init__(check.detail)
        self.check = check


class StaleFeaturesError(RuntimeError):
    """Raised only when :attr:`FailurePolicy.on_stale_features` is ``"fail_closed"``."""

    def __init__(self, *, entity_id: str, staleness_steps: int | None) -> None:
        super().__init__(
            f"stale features for entity_id={entity_id!r} (staleness_steps={staleness_steps})"
        )
        self.entity_id = entity_id
        self.staleness_steps = staleness_steps


class MissingEntityRejectedError(RuntimeError):
    """Raised only when :attr:`FailurePolicy.on_missing_entity` is ``"reject"``."""

    def __init__(self, *, entity_id: str, feature_service_version: str) -> None:
        super().__init__(
            f"entity_id={entity_id!r} missing under "
            f"feature_service_version={feature_service_version!r} and policy=reject"
        )
        self.entity_id = entity_id
        self.feature_service_version = feature_service_version


def derive_request_features(*, request: ScoreRequest) -> dict[str, float]:
    """Step 2: the three request-time fields, from the shared contract.

    ``current_amount = float(amount)``, ``event_step = float(step)``,
    ``transaction_type_transfer = 1.0 if transaction_type == "TRANSFER" else 0.0`` -- the same
    expressions ``features/paysim_specs.py`` declares and
    ``features/paysim_recipient.py: paysim_pre_decision_feature_sql`` emits offline. They are
    written in one place per side and must be derived from the specs rather than re-typed, because
    a divergence here is a G6 mismatch on a *request-time* field, which is the confusing kind.

    These three expressions are copied verbatim from the independent Python oracle
    (``features/paysim_reference.py: compute_paysim_feature_row``), not re-derived, so this is the
    same formula proven correct offline rather than a second implementation of it.
    """

    return {
        "current_amount": float(request.amount),
        "event_step": float(request.step),
        "transaction_type_transfer": 1.0 if request.transaction_type == "TRANSFER" else 0.0,
    }


def check_versions(
    *,
    context: ScoringContext,
    features: FeatureVectorResponse,
) -> VersionCheck:
    """Step 4: confirm the retrieved vector was built under the expected contract.

    Fail-closed on mismatch (guide s9.4). Compares both the service version string and the contract
    checksum: ADR-006 decision 2.3 makes ``service_version`` part of the canonical JSON, so the
    checksum is the stronger of the two and the string alone can agree while semantics have moved.
    """

    matches = (
        features.feature_service_version == context.feature_service_version
        and features.feature_contract_checksum == context.feature_contract_checksum
    )
    detail = (
        "feature vector matches the expected service version and contract checksum"
        if matches
        else (
            "feature version mismatch: service_version observed="
            f"{features.feature_service_version!r} expected={context.feature_service_version!r}; "
            f"contract_checksum observed={features.feature_contract_checksum!r} "
            f"expected={context.feature_contract_checksum!r}"
        )
    )
    return VersionCheck(
        matches=matches,
        expected_feature_service_version=context.feature_service_version,
        observed_feature_service_version=features.feature_service_version,
        expected_contract_checksum=context.feature_contract_checksum,
        observed_contract_checksum=features.feature_contract_checksum,
        detail=detail,
    )


def build_model_vector(
    *,
    request_features: dict[str, float],
    history_features: dict[str, int | float],
    ordered_feature_names: tuple[str, ...],
) -> tuple[float, ...]:
    """Step 5: assemble the twelve-field model input in frozen contract order.

    ``ordered_feature_names`` must be ``PAYSIM_MODEL_FEATURE_ORDER`` (ADR-003: the vector order is
    part of the contract). Raises if a field is missing from either side rather than substituting a
    default -- a default silently filling a *retrieval* failure is indistinguishable from a genuine
    cold start once it reaches the model, and only one of the two is legitimate.
    """

    combined: dict[str, int | float] = {**request_features, **history_features}
    missing = [name for name in ordered_feature_names if name not in combined]
    if missing:
        raise KeyError(f"cannot build model vector, missing features: {missing}")
    return tuple(float(combined[name]) for name in ordered_feature_names)


def score_transaction(*, request: ScoreRequest, context: ScoringContext) -> ScoreResponse:
    """Run guide s9.3 steps 1-7 and return the full G7 response.

    Does **not** perform step 8. The post-event update is the caller's, because a batch-serving MVP
    takes it off the request path entirely while replay mode must run it after the prediction
    exists (guide s9.3 step 8). Keeping it out of this function is what stops "update then score"
    from ever being one refactor away.
    """

    request_started = time.perf_counter()

    # Step 1: validate request. FastAPI has already parsed the body into `ScoreRequest`
    # (`extra="forbid"` plus field constraints), so by the time this function runs the request is
    # already validated; there is nothing further to check here.
    validation_ms = 0.0

    # Step 2: derive entity id / request-time features via the one shared contract.
    entity_id = derive_entity_id(name_dest=request.name_dest)
    request_features = derive_request_features(request=request)

    # Step 3: retrieve history features from the versioned online store.
    retrieval_started = time.perf_counter()
    features = context.provider.get_online_features(entity_id=entity_id, request_step=request.step)
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1000.0

    if features.status == FeatureStatus.MISSING and context.policy.on_missing_entity == "reject":
        raise MissingEntityRejectedError(
            entity_id=entity_id, feature_service_version=context.feature_service_version
        )

    # Step 4: check version/freshness. Version mismatch is fail-closed, full stop (guide s9.4).
    version_check = check_versions(context=context, features=features)
    if not version_check.matches:
        raise VersionMismatchError(version_check)
    if features.status == FeatureStatus.STALE:
        if context.policy.on_stale_features == "fail_closed":
            raise StaleFeaturesError(entity_id=entity_id, staleness_steps=features.staleness_steps)
        if context.policy.log_stale_warning:
            logger.warning(
                "serving stale features for entity_id=%s staleness_steps=%s "
                "(policy=fail_open, feature_service_version=%s)",
                entity_id,
                features.staleness_steps,
                features.feature_service_version,
            )

    # Step 5: build the ordered model vector.
    vector = build_model_vector(
        request_features=request_features,
        history_features=features.values,
        ordered_feature_names=context.ordered_feature_names,
    )

    # Step 6: score.
    inference_started = time.perf_counter()
    import pandas as pd  # optional `training`/`tracking` dependency; imported lazily on purpose

    frame = pd.DataFrame([vector], columns=list(context.ordered_feature_names))
    fraud_probability = float(context.model.predict_proba(frame)[0, 1])
    inference_ms = (time.perf_counter() - inference_started) * 1000.0
    prediction = 1 if fraud_probability >= context.decision_threshold else 0

    total_ms = (time.perf_counter() - request_started) * 1000.0

    # Step 7: emit structured log/metrics. Kept to a single log line here; request-rate/latency
    # counters are the FastAPI process's job (app.py's `/metrics`), not this pure function's.
    logger.info(
        "scored transaction_id=%s entity_id=%s prediction=%d fraud_probability=%.6f "
        "feature_status=%s total_ms=%.2f",
        request.transaction_id,
        entity_id,
        prediction,
        fraud_probability,
        features.status.value,
        total_ms,
    )

    return ScoreResponse(
        prediction=prediction,
        fraud_probability=fraud_probability,
        decision_threshold=context.decision_threshold,
        entity_id=entity_id,
        model_version=context.model_version,
        feature_service_version=features.feature_service_version,
        feature_timestamp=features.feature_timestamp,
        materialization_watermark=features.materialization_watermark,
        feature_status=features.status.value,
        request_id=str(uuid.uuid4()),
        latency_ms=LatencyBreakdown(
            total=total_ms,
            feature_retrieval=retrieval_ms,
            model_inference=inference_ms,
            validation=validation_ms,
        ),
        deployment_id=context.deployment_id,
        feature_definition_version=features.feature_definition_version,
        feature_contract_checksum=features.feature_contract_checksum,
        feature_step=features.feature_step,
        materialization_watermark_step=features.materialization_watermark_step,
        staleness_steps=features.staleness_steps,
        feature_provider=features.provider_name,
    )


def commit_post_event_state(
    *,
    request: ScoreRequest,
    context: ScoringContext,
    fraud_probability: float,
) -> None:
    """Step 8: apply post-event state, only after :func:`score_transaction` has returned.

    Implemented by the online write path (ADR-008): the serving pipeline maintains the entity's
    windowed feature state itself. ADR-003 and AGENTS.md s11 state the read-before-update ordering
    as a hard invariant, so this runs only after scoring.
    """

    # Implemented in the online write path module (serving/online_state.py, ADR-008). This thin
    # wrapper is kept for the pipeline's step numbering; app.py calls the maintainer directly.
    raise NotImplementedError(
        "ADR-008: use serving.online_state.OnlineWindowState via the /score write path"
    )
