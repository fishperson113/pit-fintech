"""T5 -- the online record, its key namespace and the write-safety rules (guide s7.1, s7.2).

Gates: **G5 Materialization** -- "latest feature state dung watermark/version" -- and
**G8 Recovery** -- "Redis reset roi rematerialize thanh cong" (guide s13).

Guide s7.1 fixes what the online store holds: the latest **post-event state** per entity, produced
by consuming source events up to a global watermark ``T`` and pushing the state after the newest
event. It explicitly does **not** take the latest ``pre_decision_features`` row -- that row excludes
the newest transaction and would leave online state one event behind (guide s4.0).

So the source of an online record is ``gold.post_event_state_updates``, and its nine post-event
fields are mapped onto the twelve contract names through
``features/build_offline.py: POST_EVENT_TO_CONTRACT_FIELD``. That map is the only place the two
vocabularies meet, and the rename exists to make "training on post-event state" a ``KeyError``
rather than a leak.

Round-0 status: dataclasses and frozen constants only; the key builder raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

# --------------------------------------------------------------------------------------------
# Key namespace
# --------------------------------------------------------------------------------------------

#: Guide s7.2: "Different feature version khong silently overwrite; namespace key theo service
#: version." The service version is therefore *inside* the key, not a field beside it -- two
#: feature service versions occupy disjoint keyspaces and cannot overwrite one another by
#: construction, which is a stronger guarantee than a compare-on-write check.
#:
#: ``pit`` is the fixed application prefix so a shared Redis instance stays legible.
#: ``entity`` is the join key name (``destination_entity_id``), kept in the key so a future second
#: entity cannot collide with this one.
#:
#: Example:
#: ``pit:paysim-fraud-scoring-v2:destination_entity_id:C1234567890``
ONLINE_KEY_TEMPLATE: Final = "pit:{feature_service_version}:{entity}:{entity_id}"

#: The watermark is a single global value per (service version, store), not per entity.
#: Guide s7.1: "Materialization co global watermark T."
ONLINE_WATERMARK_KEY_TEMPLATE: Final = "pit:{feature_service_version}:_watermark"

#: Where the run's own metadata lives, so a store reset is detectable rather than inferred from a
#: missing entity (G8 needs to tell "never materialized" apart from "wiped").
ONLINE_RUN_KEY_TEMPLATE: Final = "pit:{feature_service_version}:_materialization_run"


class FeatureStatus(StrEnum):
    """Freshness of a retrieved online vector.

    The three values are guide s9.2's ``"fresh|stale|missing"`` verbatim, because the scoring
    response returns this string and a fourth value would break that contract.

    ``MISSING`` means the entity has no record: guide s7.2 requires defaults plus an explicit
    status, never a pretence of freshness, and ADR-003 built ``recipient_has_history_*`` precisely
    so cold start is visible in the vector too.
    """

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


class MaterializationWriteOutcome(StrEnum):
    """What guide s7.2's safety rules decided for one candidate write.

    Every rule in s7.2 maps to exactly one value here, so a materializer cannot express a decision
    the rules do not cover:

    * ``WRITTEN`` -- accepted, newer than what was stored.
    * ``NOOP_IDENTICAL`` -- "Same version/timestamp write idempotent."
    * ``REJECTED_OLDER`` -- "Older write khong overwrite newer record."
    * ``REJECTED_FUTURE`` -- "Khong materialize future row so voi watermark."
    * ``REJECTED_VERSION_MISMATCH`` -- a different feature service version reached this keyspace,
      which the key namespace should already have prevented; reaching it means a caller built a key
      by hand.
    """

    WRITTEN = "written"
    NOOP_IDENTICAL = "noop_identical"
    REJECTED_OLDER = "rejected_older"
    REJECTED_FUTURE = "rejected_future"
    REJECTED_VERSION_MISMATCH = "rejected_version_mismatch"


class OnlineStoreKind(StrEnum):
    """Guide s7.3: both modes are supported paths and parity must pass on both.

    ``SQLITE`` is the deterministic, fast one used by unit-scale integration tests; ``REDIS`` is
    the production-like container that also prepares the Sprint 3 Upstash option.
    """

    SQLITE = "sqlite"
    REDIS = "redis"


def online_record_key(
    *,
    feature_service_version: str,
    entity: str,
    entity_id: str,
) -> str:
    """Build the online key from :data:`ONLINE_KEY_TEMPLATE`.

    Every reader and writer goes through this function. Formatting the template by hand at a call
    site is what eventually produces the ``REJECTED_VERSION_MISMATCH`` case above, so there is one
    builder and it validates that no component carries the ``:`` separator.
    """

    raise NotImplementedError("T5 round-0 skeleton")


# --------------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlineFeatureRecord:
    """One entity's latest post-event state, carrying every guide s7.1 metadata field.

    Guide s7.1 lists them explicitly::

        entity_id
        feature_vector
        feature_timestamp
        materialization_watermark
        feature_service_version
        source_checksum
        written_at

    :attr:`feature_values` holds the **nine history fields under their contract names** -- the
    result of applying ``POST_EVENT_TO_CONTRACT_FIELD`` to a post-event row. The three request-time
    fields are absent on purpose: they describe the request being scored, not the state of an
    entity, and T7 derives them from the request (guide s9.3 step 2).

    :attr:`feature_step` is the integer ordinal ``feature_timestamp`` was derived from, and it is
    the authority: ADR-006 decision 1.4 keeps ordering on the integer columns, so staleness is
    computed by comparing steps, never by subtracting the derived timestamps.
    """

    entity_id: str
    entity: str
    feature_service_version: str
    feature_definition_version: str
    feature_contract_checksum: str
    feature_values: dict[str, int | float]
    feature_step: int
    feature_timestamp: datetime
    feature_knowledge_step: int
    materialization_watermark_step: int
    materialization_watermark: datetime
    source_row_number: int
    source_checksum: str
    gold_post_event_version: int
    materialization_run_id: str
    written_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlineReadResult:
    """What a read returns, including the honest answer when there is nothing to return.

    A ``MISSING`` read returns :attr:`feature_values` filled from the contract defaults
    (``FeatureSpec.default``: ``0`` for counts and history flags, ``0.0`` for amounts) together
    with ``status = MISSING``. Guide s7.2: defaults plus an explicit status, never a pretence of
    freshness.
    """

    entity_id: str
    status: FeatureStatus
    record: OnlineFeatureRecord | None
    feature_values: dict[str, int | float]
    #: ``request_step - record.feature_step``. ``None`` when the record is missing. Freshness is a
    #: step distance, not a wall-clock age -- PaySim time is an hour ordinal (ADR-002 decision 1).
    staleness_steps: int | None
    read_latency_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationWriteDecision:
    """One write evaluated against every guide s7.2 safety rule, with the reason recorded."""

    entity_id: str
    outcome: MaterializationWriteOutcome
    incoming_feature_step: int
    stored_feature_step: int | None
    watermark_step: int
    incoming_feature_service_version: str
    stored_feature_service_version: str | None
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationRunResult:
    """One materialization run to a watermark (guide s7.1); the evidence gate G5 reads.

    G5 is "latest feature state dung watermark/version", so the two things this record must make
    checkable are that no written state came from beyond :attr:`watermark_step`, and that the Gold
    version was pinned at the start: guide s7.1 requires the result to stay bound to the version
    resolved when the run began, even if Gold ``latest`` moves during it.
    """

    status: Literal["completed", "failed"]
    run_id: str
    started_at: datetime
    finished_at: datetime
    store: OnlineStoreKind
    store_uri: str

    feature_service_version: str
    feature_definition_version: str
    feature_contract_checksum: str

    #: Pinned at run start and never re-resolved (guide s7.1).
    gold_post_event_version: int
    gold_post_event_path: str
    source_checksum: str

    watermark_step: int
    watermark_timestamp: datetime
    previous_watermark_step: int | None

    entities_considered: int
    records_written: int
    records_noop: int
    records_rejected: int
    rejected_by_outcome: dict[str, int]
    max_written_feature_step: int
    future_writes_attempted: int

    #: G8. ``True`` when the run rebuilt an emptied store from Gold rather than advancing one.
    rebuilt_from_empty: bool
    wall_seconds: float
    manifest_path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryReport:
    """Gate G8 -- "Redis reset roi rematerialize thanh cong".

    The assertion is not merely that the rerun completed: the rebuilt store must be byte-equivalent
    to the one that was wiped, at the same watermark and version. :attr:`differing_entities` names
    the entities that were not, so a failure is diagnosable.
    """

    store: OnlineStoreKind
    watermark_step: int
    entities_before: int
    entities_after: int
    records_compared: int
    records_identical: int
    differing_entities: tuple[str, ...]
    watermark_restored: bool
    feature_service_version_unchanged: bool
    passed: bool
