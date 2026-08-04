"""T5 -- populating the online store from Gold post-event state (guide s7).

Gates: **G5 Materialization** and **G8 Recovery** (guide s13).

Guide s7.1 in one sentence: consume ``gold.post_event_state_updates`` rows with
``step <= watermark``, keep the latest per entity, and push it through Feast's ``PushSource`` /
online write path -- never by reading the newest ``pre_decision_features`` row.

Guide s7.2's five safety rules are enforced by :func:`evaluate_write`, which is deliberately
separate from the store adapters so all of them obey the same rules rather than each re-deriving
them. Redis and SQLite are both supported paths and parity must pass on both (guide s7.3).

``redis`` and ``feast`` are optional dependency groups; they are imported inside function bodies,
never at module scope.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pit_fintech.materialization.records import (
    MaterializationRunResult,
    MaterializationWriteDecision,
    OnlineFeatureRecord,
    OnlineReadResult,
    OnlineStoreKind,
    RecoveryReport,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlineStoreConfig:
    """Which store, where, and under which service version's keyspace.

    ``stale_after_steps`` is the freshness boundary: a read whose ``request_step`` exceeds the
    record's ``feature_step`` by more than this is reported ``STALE`` rather than ``FRESH``.
    Default ``1`` follows directly from the shift relation in
    ``features/build_offline.py: GOLD_SHIFT_RELATION`` -- post-event state at step ``s`` is exactly
    the pre-decision history of a cutoff at ``s + 1``, and beyond that the window no longer lines
    up. Widening it is a policy decision that must be recorded, not a tuning knob to quiet a parity
    failure.
    """

    kind: OnlineStoreKind
    uri: str
    feature_service_version: str
    entity: str
    stale_after_steps: int = 1
    connect_timeout_seconds: float = 2.0
    operation_timeout_seconds: float = 2.0
    max_retries: int = 2


def materialize_to_watermark(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    store: OnlineStoreConfig,
    watermark_step: int,
    run_id: str,
    gold_post_event_version: int | None = None,
) -> MaterializationRunResult:
    """Consume post-event state up to ``watermark_step`` and write the latest state per entity.

    Gate G5 -- "latest feature state dung watermark/version". Pins the Gold table version at run
    start and keeps using it even if Gold ``latest`` advances mid-run (guide s7.1). Every candidate
    write goes through :func:`evaluate_write` first, so no rule in guide s7.2 can be bypassed by a
    fast path.

    ``gold_post_event_version=None`` resolves the current version once, at the start, and records
    it; passing a version explicitly re-materializes a historical state, which is what G10's
    time-travel evidence and G8's recovery path both need.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def evaluate_write(
    *,
    incoming: OnlineFeatureRecord,
    stored: OnlineFeatureRecord | None,
    watermark_step: int,
) -> MaterializationWriteDecision:
    """Apply all five guide s7.2 safety rules to one candidate write.

    The rules, and the outcome each produces:

    * ``incoming.feature_step > watermark_step`` -> ``REJECTED_FUTURE``
      ("Khong materialize future row so voi watermark").
    * ``stored is not None and incoming.feature_step < stored.feature_step`` -> ``REJECTED_OLDER``
      ("Older write khong overwrite newer record").
    * identical version and feature step, identical values -> ``NOOP_IDENTICAL``
      ("Same version/timestamp write idempotent").
    * a differing ``feature_service_version`` -> ``REJECTED_VERSION_MISMATCH``
      ("Different feature version khong silently overwrite"); the key namespace should have made
      this unreachable, so reaching it means a key was built outside ``online_record_key``.
    * otherwise -> ``WRITTEN``.

    Pure decision, no I/O, so it is directly unit-testable -- which matters because these five
    lines are what stop an out-of-order replay from corrupting online state.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def write_record(
    *,
    store: OnlineStoreConfig,
    record: OnlineFeatureRecord,
    watermark_step: int,
) -> MaterializationWriteDecision:
    """Write one record through :func:`evaluate_write`, atomically per key.

    Read-modify-write on a shared store is a race, so the comparison and the write are one
    operation (a Redis transaction / SQLite ``BEGIN IMMEDIATE``). Without that, two concurrent
    writers can both read an older stored step and both decide they are newer.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def read_online_features(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    request_step: int,
) -> OnlineReadResult:
    """Read one entity's state and classify its freshness against ``request_step``.

    A missing entity returns the contract defaults with ``status = MISSING`` -- guide s7.2:
    "Missing entity tra defaults + explicit ``feature_status``, khong gia vo fresh." Staleness is a
    step distance (ADR-002 decision 1: ``step`` is an hour ordinal), never a wall-clock age.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def read_watermark(*, store: OnlineStoreConfig) -> tuple[int, datetime] | None:
    """Current global watermark as ``(step, derived timestamp)``, or ``None`` if never set."""

    raise NotImplementedError("T5 round-0 skeleton")


def reset_online_store(*, store: OnlineStoreConfig) -> int:
    """Delete every key in this service version's namespace and return how many were removed.

    Scoped to the ``pit:<feature_service_version>:`` prefix, never a ``FLUSHDB``: another service
    version's keyspace in the same Redis is not this run's to destroy, and G8's evidence is about
    rebuilding *this* namespace.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def rematerialize_after_reset(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    store: OnlineStoreConfig,
    watermark_step: int,
    run_id: str,
    gold_post_event_version: int,
) -> RecoveryReport:
    """Gate G8 -- "Redis reset roi rematerialize thanh cong".

    Snapshots the store, resets it, re-runs materialization at the same pinned Gold version and
    watermark, then compares record by record. Completing is not the gate: the rebuilt store must
    be equivalent to the one that was wiped, and :attr:`RecoveryReport.differing_entities` names
    every entity where it was not.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def push_to_feast_online_store(
    *,
    store: OnlineStoreConfig,
    records: tuple[OnlineFeatureRecord, ...],
    feature_view_name: str,
) -> int:
    """Write records through Feast's ``PushSource`` / online write path (guide s3.2, s7.1).

    ``feature_repo/definitions.py`` deliberately does not define a ``PushSource`` yet -- its
    docstring records that as locked-out T1 scope, with the online write path left to T5. Adding it
    is this task's work, and it must keep the same schema for batch and online paths (guide s3.2),
    otherwise offline and online vectors stop being comparable and G6 has nothing to measure.

    Feast is an optional dependency group; import it inside the body.
    """

    raise NotImplementedError("T5 round-0 skeleton")


def post_event_row_to_record(
    *,
    row: dict[str, object],
    feature_service_version: str,
    feature_definition_version: str,
    feature_contract_checksum: str,
    entity: str,
    watermark_step: int,
    gold_post_event_version: int,
    source_checksum: str,
    materialization_run_id: str,
    written_at: datetime,
) -> OnlineFeatureRecord:
    """Map one ``gold.post_event_state_updates`` row onto an online record.

    Renames the nine ``post_*`` fields to their contract names through
    ``features/build_offline.py: POST_EVENT_TO_CONTRACT_FIELD``. That map is the single crossing
    point between the two vocabularies, and going around it re-opens exactly the leakage the rename
    was introduced to make impossible.
    """

    raise NotImplementedError("T5 round-0 skeleton")
