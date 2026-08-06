"""T7 -- the scoring API request/response contracts (guide s9.1, s9.2).

Gate: **G7 Serving** -- "API tra prediction + lineage/freshness metadata" (guide s13). The response
shape *is* the gate: a prediction without the version and freshness fields does not pass it.

**The request contract is adapted from the guide, deliberately.** Guide s9.1 shows::

    {"transaction_id", "event_timestamp", "card_fields", "transaction_amount", "product_code"}

which is IEEE-CIS vocabulary -- ``card_fields`` and ``product_code`` are the provisional ADR-001
entity, and PaySim has neither. The guide's own erratum table already replaced the same vocabulary
in s6.1, and ADR-006's Alternatives section states the principle directly: "The guide wording here
predates ADR-002/ADR-003 and is superseded by them." The frozen application contract is
``paysim-fraud-recipient-v2``: entity ``destination_entity_id``, request-time inputs ``amount``,
``step`` and ``transaction_type`` (ADR-003). :class:`ScoreRequest` carries exactly those.

The **response** contract is guide s9.2 field for field, with no renames, because it is what G7 is
read against and what a downstream consumer binds to.

pydantic is a core dependency (``pyproject.toml``) and every other contract in this repo is a
pydantic model, so these are models rather than dataclasses: FastAPI validates request bodies
through them, and a hand-rolled dataclass would need the validation written twice.

Round-0 status: schemas are complete and importable; the helper raises.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Guide s9.2 ``feature_status``. Mirrors
#: ``materialization/records.py: FeatureStatus`` -- restated as a Literal because this is the wire
#: contract and an enum's repr is not what belongs in a JSON schema.
FeatureStatusLiteral = Literal["fresh", "stale", "missing"]


class ScoreRequest(BaseModel):
    """One transaction submitted for scoring.

    Fields are the frozen request-time inputs of ADR-003 plus the identity needed to trace the
    call. The four PaySim balance columns, ``isFraud`` and ``isFlaggedFraud`` are absent by
    construction and ``extra="forbid"`` makes sending one an error rather than an ignored field --
    the same guarantee ``paysim_reference.PaySimSourceEvent`` gives on the offline path.

    ``step`` is the hour ordinal and is the authority (ADR-002 decision 1); ``event_timestamp`` is
    optional and, if sent, must equal the ADR-006 map of ``step``. It is never used for ordering or
    eligibility (ADR-006 decision 1.4).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str = Field(min_length=1)
    #: PaySim row identity when replaying a known event; absent for a synthetic demo request.
    source_row_number: int | None = Field(default=None, ge=1)
    step: int = Field(ge=1)
    knowledge_step: int | None = Field(default=None, ge=1)
    event_timestamp: datetime | None = None
    transaction_type: Literal["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]
    amount: Decimal = Field(ge=0)
    #: PaySim ``nameDest``. The entity id is derived from it by the shared contract (guide s9.3
    #: step 2), never sent by the client -- a client-supplied entity id would let a caller point a
    #: request at another entity's history.
    name_dest: str = Field(min_length=1)
    name_orig: str | None = None


class LatencyBreakdown(BaseModel):
    """Guide s9.2 ``latency_ms``. Per-stage, so a slow request names its own cause."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total: float
    feature_retrieval: float
    model_inference: float
    validation: float


class ScoreResponse(BaseModel):
    """Guide s9.2's response contract.

    Every lineage and freshness field is mandatory, which is exactly gate G7: "API tra prediction +
    lineage/freshness metadata". :attr:`feature_status` plus :attr:`feature_timestamp` plus
    :attr:`materialization_watermark` is what lets a consumer tell a confident score from one
    computed on cold defaults -- ADR-003 added ``recipient_has_history_*`` for the same reason.

    :attr:`fraud_probability` and :attr:`decision_threshold` are both returned so the caller can
    re-derive :attr:`prediction`; a bare label would make the threshold invisible, and the
    threshold is selected on validation and pinned in the deployment manifest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction: int = Field(ge=0, le=1)
    fraud_probability: float = Field(ge=0.0, le=1.0)
    decision_threshold: float = Field(ge=0.0, le=1.0)
    entity_id: str
    model_version: str
    feature_service_version: str
    feature_timestamp: datetime | None
    materialization_watermark: datetime | None
    feature_status: FeatureStatusLiteral
    request_id: str
    latency_ms: LatencyBreakdown

    # --- additions beyond guide s9.2, all lineage rather than new behaviour ---------------
    #: Deployment identity from the manifest that promoted the active champion (guide s6.4). G11's
    #: "scoring tra dung active champion" is checked against this.
    deployment_id: str | None = None
    feature_definition_version: str
    feature_contract_checksum: str
    #: The integer ordinals behind the two timestamps above. ADR-006 decision 1.4 keeps ordering on
    #: the ordinals, and a consumer computing staleness must use these, not the derived dates.
    feature_step: int | None = None
    materialization_watermark_step: int | None = None
    staleness_steps: int | None = None
    feature_provider: str


class ErrorResponse(BaseModel):
    """A refused request, with the guide s9.4 policy that refused it named.

    ``code`` values map one-to-one onto guide s9.4's failure policy:
    ``version_mismatch`` (fail-closed), ``stale_features`` (only when configured fail-closed),
    ``online_store_timeout`` (``503`` after bounded retry), ``missing_entity_rejected`` (only when
    cold-start policy is reject), ``invalid_request`` and ``model_not_ready``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "invalid_request",
        "version_mismatch",
        "stale_features",
        "online_store_timeout",
        "missing_entity_rejected",
        "model_not_ready",
    ]
    message: str
    request_id: str
    feature_service_version: str | None = None
    model_version: str | None = None


class HealthResponse(BaseModel):
    """``/health/live`` and ``/health/ready`` (guide s10.2).

    Guide s10.2: "ready chi true khi model + online store + feature version load dung." All three
    are separate booleans so a failing probe says which one, and :attr:`ready` is their conjunction
    rather than an independently settable flag.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["live", "ready", "not_ready"]
    live: bool
    ready: bool
    model_loaded: bool
    online_store_reachable: bool
    feature_version_matches: bool
    model_version: str | None = None
    feature_service_version: str
    materialization_watermark_step: int | None = None
    detail: str | None = None


def derive_entity_id(*, name_dest: str) -> str:
    """Derive ``destination_entity_id`` from a request, using the shared contract (guide s9.3.2).

    On PaySim the entity is ``nameDest`` itself with a ``CUSTOMER``/``MERCHANT`` classification
    (ADR-002 decision 4, ``paysim_reference.paysim_destination_kind``) -- not the SHA-256 card hash
    of ADR-001, which was the provisional IEEE-CIS entity and is superseded by ADR-002.

    Implementations must call the existing classifier rather than re-testing the ``C``/``M`` prefix
    here: two copies of an entity rule is how offline and online entity ids start disagreeing, and
    that failure appears as a G6 ``MISSING_ENTITY`` mismatch far from its cause.
    """

    from pit_fintech.features.paysim_reference import paysim_destination_kind

    # The classifier's return value is not needed to compute the id (ADR-002 decision 4: the
    # entity id is `nameDest` itself, unhashed) -- it is called anyway so this is the one and only
    # place PaySim's C/M prefix rule is evaluated for a scoring request.
    paysim_destination_kind(name_dest)
    return name_dest
