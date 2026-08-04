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

from dataclasses import dataclass
from typing import Literal

from pit_fintech.serving.feature_provider import FeatureProvider, FeatureVectorResponse
from pit_fintech.serving.schemas import ScoreRequest, ScoreResponse


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


def derive_request_features(*, request: ScoreRequest) -> dict[str, float]:
    """Step 2: the three request-time fields, from the shared contract.

    ``current_amount = float(amount)``, ``event_step = float(step)``,
    ``transaction_type_transfer = 1.0 if transaction_type == "TRANSFER" else 0.0`` -- the same
    expressions ``features/paysim_specs.py`` declares and
    ``features/paysim_recipient.py: paysim_pre_decision_feature_sql`` emits offline. They are
    written in one place per side and must be derived from the specs rather than re-typed, because
    a divergence here is a G6 mismatch on a *request-time* field, which is the confusing kind.
    """

    raise NotImplementedError("T7 round-0 skeleton")


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

    raise NotImplementedError("T7 round-0 skeleton")


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

    raise NotImplementedError("T7 round-0 skeleton")


def score_transaction(*, request: ScoreRequest, context: ScoringContext) -> ScoreResponse:
    """Run guide s9.3 steps 1-7 and return the full G7 response.

    Does **not** perform step 8. The post-event update is the caller's, because a batch-serving MVP
    takes it off the request path entirely while replay mode must run it after the prediction
    exists (guide s9.3 step 8). Keeping it out of this function is what stops "update then score"
    from ever being one refactor away.
    """

    raise NotImplementedError("T7 round-0 skeleton")


def commit_post_event_state(
    *,
    request: ScoreRequest,
    context: ScoringContext,
    fraud_probability: float,
) -> None:
    """Step 8: apply post-event state, only after :func:`score_transaction` has returned.

    Called by the replay driver, never from inside the scoring path. ADR-003 and AGENTS.md s11 both
    state the ordering as a hard invariant, and T6 asserts it per event via
    :attr:`~pit_fintech.replay.driver.ReplayStepResult.read_before_update`.
    """

    raise NotImplementedError("T7 round-0 skeleton")
