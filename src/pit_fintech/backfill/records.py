"""T3 -- the backfill run record and its idempotency key (guide s5.1, s5.2).

Gate: **G2 Backfill** -- "full/range rerun co checksum giong nhau va Delta versions duoc ghi"
(guide s13). Every field guide s5.1 makes mandatory is a field of :class:`BackfillRunRecord`; the
list there is a checklist, not a suggestion, so nothing on it is folded into a free-text blob.

:func:`backfill_idempotency_key` is the one function in the round-0 skeleton with a real body. It
is a canonicalization plus a SHA-256 -- no business logic, no I/O -- and leaving it unimplemented
would leave the single value that decides "is this rerun the same backfill?" open to seven separate
guesses.

Deliberately not reusing ``contracts/manifests.py: BackfillManifest``. That model is labelled
"Schema reserved for Sprint 2; no backfill state machine is claimed yet" and carries ten fields
against the ~30 guide s5.1 requires; it also types the range as ``datetime``, which contradicts
ADR-006 decision 1.4 (the ordering authority is the integer ordinals). Round 0 may not edit it, so
this module declares the real record and the round-0 report flags the consolidation as ADR-sized
work rather than a refactor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

# --------------------------------------------------------------------------------------------
# States and modes
# --------------------------------------------------------------------------------------------


class BackfillState(StrEnum):
    """Guide s5.1: ``planned -> running -> validated -> committed``, or ``-> failed``.

    ``failed`` is reachable from ``running`` and from ``validated``; it is never reachable from
    ``committed``. A committed run is immutable -- correcting it means a new run that ``supersedes``
    it (guide s5.2), never a mutation of this record.
    """

    PLANNED = "planned"
    RUNNING = "running"
    VALIDATED = "validated"
    COMMITTED = "committed"
    FAILED = "failed"


class BackfillMode(StrEnum):
    """Guide s5.3.

    ``FULL`` builds the whole range from one pinned Silver version. ``RANGE`` builds an explicit
    sub-range. ``INCREMENTAL`` builds only the delta output range while still reading the lookback
    it needs, then partition-overwrites or ``MERGE``s into Gold.

    Guide s5.3 attaches a rule to the last one: "Khong goi mot query la incremental neu no van scan
    toan bo source." :class:`BackfillScanEvidence` is what makes that claim checkable instead of
    self-reported.
    """

    FULL = "full"
    RANGE = "range"
    INCREMENTAL = "incremental"


class BackfillResumeAction(StrEnum):
    """What :func:`~pit_fintech.backfill.state_machine.resolve_idempotent_run` decided.

    The three branches are guide s5.2 verbatim: committed with a matching checksum is a no-op;
    failed or half-staged is cleaned up and resumed; a changed source checksum fails loud and
    reuses nothing.
    """

    NOOP_ALREADY_COMMITTED = "noop_already_committed"
    RESUME_AFTER_STAGING_CLEANUP = "resume_after_staging_cleanup"
    FAIL_SOURCE_CHECKSUM_CHANGED = "fail_source_checksum_changed"
    RUN_FRESH = "run_fresh"


# --------------------------------------------------------------------------------------------
# Idempotency key (guide s5.2) -- implemented
# --------------------------------------------------------------------------------------------

BACKFILL_IDEMPOTENCY_KEY_POLICY_VERSION: Final = "backfill-idempotency-key-v1"

#: Field separator inside the canonical payload. NUL cannot occur in any of the five inputs, so no
#: pair of distinct inputs can produce the same byte string -- the property a joined-string digest
#: needs and a naive delimiter like ``":"`` does not have (every version string here already
#: contains ``-``, and ``dataset_snapshot_id`` contains ``:``).
_KEY_SEPARATOR: Final = "\0"


def backfill_idempotency_key(
    *,
    dataset_snapshot_id: str,
    entity_definition_version: str,
    feature_definition_version: str,
    cutoff_start_step: int,
    cutoff_end_step: int,
) -> str:
    """Return the guide s5.2 idempotency key for one logical backfill.

    Guide s5.2 gives the formula::

        sha256(dataset_snapshot + entity_version + feature_version + start + end)

    Two runs with the same key are the same logical backfill, and guide s5.2 then decides what
    happens: committed with a matching checksum is a no-op; failed or half-staged is cleaned up and
    resumed; a changed source checksum fails loud rather than reusing the old artifact.

    **The range is expressed in hour ordinals, not timestamps.** ADR-006 decision 1.4 keeps the
    ordering authority on ``step``; deriving the key from ``event_timestamp`` would make it a
    function of ``EPOCH_0``, which is a presentation constant (ADR-006 decision 1.2), so a
    presentation change would silently re-identify every historical backfill. Bounds are inclusive
    on both ends, matching how ``cutoff_start_step``/``cutoff_end_step`` are used throughout T2/T3.

    **One deliberate deviation from the literal formula:**
    :data:`BACKFILL_IDEMPOTENCY_KEY_POLICY_VERSION` is prepended to the hashed payload, so the
    digest differs from a bare five-field hash. The reason is that this repo versions every
    identity it hashes -- ``platform/lineage.py: component_fingerprint`` prefixes
    ``component-fingerprint-v1``, ``platform/feast_registry.py`` prefixes
    ``feast-definitions-checksum-v1`` -- and an unversioned key cannot be migrated later without
    silently colliding old and new schemes. Dropping the prefix is a one-line change if the
    reviewer prefers the formula literally; it is flagged in the round-0 report rather than made
    quietly.
    """

    for name, value in (
        ("dataset_snapshot_id", dataset_snapshot_id),
        ("entity_definition_version", entity_definition_version),
        ("feature_definition_version", feature_definition_version),
    ):
        if not value:
            raise ValueError(f"{name} must be a non-empty string")
        if _KEY_SEPARATOR in value:
            raise ValueError(f"{name} must not contain a NUL byte")
    for name, value in (
        ("cutoff_start_step", cutoff_start_step),
        ("cutoff_end_step", cutoff_end_step),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an int hour ordinal, not {type(value).__name__}")
        if value < 1:
            raise ValueError(f"{name} must be >= 1, received {value}")
    if cutoff_end_step < cutoff_start_step:
        raise ValueError(
            f"cutoff_end_step {cutoff_end_step} precedes cutoff_start_step {cutoff_start_step}"
        )

    payload = _KEY_SEPARATOR.join(
        (
            BACKFILL_IDEMPOTENCY_KEY_POLICY_VERSION,
            dataset_snapshot_id,
            entity_definition_version,
            feature_definition_version,
            str(cutoff_start_step),
            str(cutoff_end_step),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------
# Record components
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PartitionChecksum:
    """One partition's identity, on either side of a run (guide s5.1 input/output partitions).

    ``partition`` is the ``event_day`` ordinal, which is
    ``floor((step - 1) / 24) + 1`` -- an integer, not a date (ADR-006 decision 1.2).
    """

    table: str
    partition: int
    rows: int
    checksum: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillScanEvidence:
    """Guide s5.3: "Ghi bytes/partitions read."

    An incremental run that reports ``source_partitions_read == source_partitions_total`` is a full
    scan wearing an incremental label, and this record is what makes that visible.
    """

    source_partitions_total: int
    source_partitions_read: int
    source_files_read: int
    source_bytes_read: int
    source_rows_scanned: int
    lookback_steps: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillCounts:
    """Guide s5.1 "counts"."""

    source_rows_in_range: int
    cutoff_rows_in_scope: int
    pre_decision_rows_written: int
    post_event_state_rows_written: int
    rows_superseded: int
    duplicate_rows_dropped: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillTimings:
    """Guide s5.1 "timings". Every stage boundary, so a slow phase can be named."""

    planned_at: datetime
    started_at: datetime | None = None
    validated_at: datetime | None = None
    committed_at: datetime | None = None
    failed_at: datetime | None = None
    plan_seconds: float | None = None
    compute_seconds: float | None = None
    validate_seconds: float | None = None
    commit_seconds: float | None = None
    wall_seconds: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillError:
    """Guide s5.1 "errors". One recorded failure, attributed to a stage."""

    stage: BackfillState
    kind: str
    message: str
    occurred_at: datetime
    traceback_digest: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationReuse:
    """Guide s5.1 "previous materialization reused" and s5.3 "Reuse".

    Guide s5.3 permits reusing materialized daily aggregates "chi khi result khop reference", so a
    reuse claim is only admissible next to the verification that backed it.
    """

    reused: bool
    reused_run_id: str | None = None
    reused_partitions: tuple[int, ...] = ()
    verified_against_reference: bool = False
    verification_detail: str | None = None


# --------------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillRunRecord:
    """One backfill run, carrying every field guide s5.1 makes mandatory.

    Gate G2 reads :attr:`output_partitions` and :attr:`committed_gold_pre_decision_version` /
    :attr:`committed_gold_post_event_version`: a full and a range rerun of the same logical
    backfill must produce the same checksums, and the Delta versions they committed must both be
    written down.

    Immutable by construction. A state transition produces a new record (see
    ``state_machine.transition``) rather than mutating this one, so the run history is an append-
    only sequence and ``attempt`` means what it says.
    """

    # --- identity -----------------------------------------------------------------------
    run_id: str
    idempotency_key: str
    attempt: int
    supersedes_run_id: str | None
    state: BackfillState
    mode: BackfillMode

    # --- range (guide s5.1 "range") -----------------------------------------------------
    cutoff_start_step: int
    cutoff_end_step: int
    lookback_start_step: int

    # --- versions (guide s5.1 "source/feature/entity/code versions") --------------------
    dataset_snapshot_id: str
    raw_file_sha256: str
    entity_definition_version: str
    feature_definition_version: str
    feature_service_version: str
    feature_contract_checksum: str
    pipeline_version: str
    code_commit: str
    lineage_policy_version: str
    gold_component_fingerprint: str
    gold_component_dirty: bool
    repository_dirty: bool

    # --- inputs (guide s5.1 "input partitions/checksums", "source Bronze/Silver versions")
    source_bronze_table_version: int | None
    source_silver_transactions_version: int
    source_silver_labels_version: int | None
    source_checksum: str
    input_partitions: tuple[PartitionChecksum, ...]

    # --- outputs (guide s5.1 "output partitions/checksums", "committed Gold version") ----
    output_partitions: tuple[PartitionChecksum, ...]
    output_checksum: str | None
    committed_gold_pre_decision_version: int | None
    committed_gold_post_event_version: int | None
    #: Guide s5.2: "Run manifest ghi Delta application/transaction identity khi writer ho tro."
    #: ``None`` records honestly that the installed writer did not expose one.
    delta_app_id: str | None
    delta_app_version: int | None
    staging_root: str
    staging_cleaned: bool

    # --- evidence -----------------------------------------------------------------------
    counts: BackfillCounts
    timings: BackfillTimings
    scan: BackfillScanEvidence
    reuse: MaterializationReuse
    errors: tuple[BackfillError, ...]
    manifest_path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillRerunComparison:
    """G2's actual assertion: rerunning the same logical backfill reproduces the same bytes.

    Guide s13 G2: "full/range rerun co checksum giong nhau va Delta versions duoc ghi". Delta
    *versions* legitimately differ between the two runs -- a second commit advances the log -- so
    the gate compares checksums and only requires that both versions were recorded.
    """

    idempotency_key: str
    first_run_id: str
    second_run_id: str
    schema_checksums_match: bool
    row_counts_match: bool
    logical_checksums_match: bool
    partition_checksums_match: bool
    both_delta_versions_recorded: bool
    differing_partitions: tuple[int, ...]
    passed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class LateArrivalCorrectionReport:
    """Guide s5.4, labelled synthetic (ADR-005 decision 7).

    The six steps of guide s5.4 in one record: materialize to watermark ``T``, inject an event with
    ``event_time < T`` but ``created_time > T``, resolve the impacted range
    ``[event_time, event_time + max_window]``, backfill it, commit a new Gold version, then compare
    the corrected checksum against the clean reference and confirm the old version still
    time-travels.

    On PaySim that means ``knowledge_step > watermark_step >= step`` (ADR-005 decision 5 is the
    predicate this exercises). ADR-005 decision 7: late arrivals live only in labelled fixtures,
    every value hand-chosen so at least one row sits exactly on the ``<=`` boundary, never random,
    never written into the main dataset, never tied to the train/validation/test split.
    """

    synthetic: bool
    watermark_step: int
    injected_source_row_number: int
    injected_step: int
    injected_knowledge_step: int
    impacted_start_step: int
    impacted_end_step: int
    correction_run_id: str
    corrected_gold_version: int
    clean_reference_checksum: str
    corrected_checksum: str
    checksums_match: bool
    previous_version_time_travel_ok: bool
    previous_version_checksum: str
