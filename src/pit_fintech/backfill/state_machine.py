"""T3 -- the backfill state machine driving T2's builder (guide s5).

Gate: **G2 Backfill** -- "full/range rerun co checksum giong nhau va Delta versions duoc ghi"
(guide s13). G3 rides along: this module never writes to a main Gold table itself, it calls
``features/build_offline.py`` and lets promotion own atomicity.

The state machine is guide s5.1::

    planned -> running -> validated -> committed
                       -> failed

and the idempotency contract is guide s5.2, resolved by :func:`resolve_idempotent_run` before any
compute starts.

Round-0 status: signatures only. Every body raises ``NotImplementedError``. The one piece of real
behaviour T3 needs early -- the idempotency key -- lives in :mod:`pit_fintech.backfill.records`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pit_fintech.backfill.records import (
    BackfillMode,
    BackfillRerunComparison,
    BackfillResumeAction,
    BackfillRunRecord,
    BackfillState,
    LateArrivalCorrectionReport,
)
from pit_fintech.features.build_offline import OfflineFeatureBuildResult


@dataclass(frozen=True, slots=True, kw_only=True)
class BackfillPlan:
    """What a ``planned`` run has decided before it touches data.

    Producing this is cheap and reading it is how a reviewer checks that an "incremental" run is
    actually incremental *before* it runs: :attr:`output_start_step` versus
    :attr:`read_start_step` shows the lookback, and :attr:`target_partitions` shows what will be
    overwritten.
    """

    run_id: str
    idempotency_key: str
    mode: BackfillMode
    output_start_step: int
    output_end_step: int
    #: ``output_start_step - GOLD_LOOKBACK_STEPS``, clamped at the dataset's first step. Guide
    #: s5.3: an incremental run reads the lookback it needs and nothing more.
    read_start_step: int
    read_end_step: int
    target_partitions: tuple[int, ...]
    source_silver_transactions_version: int
    source_checksum: str
    dataset_snapshot_id: str
    entity_definition_version: str
    feature_definition_version: str
    staging_root: str
    resume_action: BackfillResumeAction
    previous_run_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class IdempotencyResolution:
    """Guide s5.2 applied to an existing run with the same key.

    The three branches, verbatim: committed with a matching checksum is a no-op; failed or staged
    is cleaned up safely and resumed; a changed source checksum fails loud and reuses nothing.
    :attr:`reason` carries the sentence a human needs when the third branch fires, because "fail
    loud" that does not say what changed is just a failure.
    """

    action: BackfillResumeAction
    idempotency_key: str
    existing_run_id: str | None
    existing_state: BackfillState | None
    existing_source_checksum: str | None
    incoming_source_checksum: str
    staging_paths_to_clean: tuple[str, ...]
    reason: str


def plan_backfill(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    mode: BackfillMode,
    cutoff_start_step: int,
    cutoff_end_step: int,
    run_id: str | None = None,
    silver_manifest_path: Path | None = None,
) -> BackfillPlan:
    """Resolve versions, range, lookback and idempotency without computing anything.

    ``mode=FULL`` plans the whole frozen step range 1-743 from one pinned Silver version;
    ``RANGE`` and ``INCREMENTAL`` plan the requested output range and derive
    :attr:`BackfillPlan.read_start_step` from ``GOLD_LOOKBACK_STEPS`` (guide s5.3).
    """

    raise NotImplementedError("T3 round-0 skeleton")


def resolve_idempotent_run(
    *,
    artifact_root: Path,
    idempotency_key: str,
    incoming_source_checksum: str,
) -> IdempotencyResolution:
    """Decide what an incoming run with an existing key must do (guide s5.2).

    Refuses to reuse an artifact whose source checksum moved -- that is the branch whose failure
    mode is silent corruption, so it fails loud and names the two checksums.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def transition(
    *,
    record: BackfillRunRecord,
    to_state: BackfillState,
    **updates: object,
) -> BackfillRunRecord:
    """Return a new record in ``to_state``, rejecting a transition the machine does not allow.

    Legal edges (guide s5.1): ``planned -> running -> validated -> committed``, plus
    ``running -> failed`` and ``validated -> failed``. Nothing leaves ``committed`` or ``failed``:
    a committed run is corrected by a new run that ``supersedes`` it (guide s5.2), never by
    editing this one.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def execute_backfill(
    *,
    plan: BackfillPlan,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
) -> BackfillRunRecord:
    """Run one planned backfill through the state machine and return the terminal record.

    Gate G2. Calls ``features/build_offline.build_offline_features`` for the compute and
    ``promote_staged_gold`` for the commit, so G3's atomicity lives in exactly one place. A run
    that fails validation returns a ``failed`` record with the failing validations in
    :attr:`BackfillRunRecord.errors` and the main Gold tables untouched -- it does not raise.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def record_from_build(
    *,
    plan: BackfillPlan,
    build: OfflineFeatureBuildResult,
    attempt: int,
) -> BackfillRunRecord:
    """Fold a T2 build result into the guide s5.1 run record.

    The single adapter between T2's return type and T3's audit record; keeping it explicit is what
    stops the two field vocabularies from being merged by hand at each call site.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def write_run_manifest(*, record: BackfillRunRecord, artifact_root: Path) -> Path:
    """Persist a run record as an immutable JSON manifest under ``artifacts/runs/<run_id>/``.

    Guide s5.2: a retry must not create a duplicate commit, nor two snapshots carrying the same
    logical backfill identity without a ``supersedes`` relation. This manifest is where that
    relation is written down.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def load_run_manifest(path: Path) -> BackfillRunRecord:
    """Read back a run manifest written by :func:`write_run_manifest`."""

    raise NotImplementedError("T3 round-0 skeleton")


def find_runs_by_idempotency_key(
    *,
    artifact_root: Path,
    idempotency_key: str,
) -> tuple[BackfillRunRecord, ...]:
    """Every recorded run sharing one logical backfill identity, oldest first."""

    raise NotImplementedError("T3 round-0 skeleton")


def compare_reruns(
    *,
    first: BackfillRunRecord,
    second: BackfillRunRecord,
) -> BackfillRerunComparison:
    """Gate G2's assertion: two runs of the same logical backfill produced the same bytes.

    Compares schema/row-count/logical/partition checksums and confirms both runs recorded their
    committed Delta versions. Delta versions themselves are expected to differ -- a second commit
    advances the log -- so version *equality* is deliberately not asserted.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def inject_late_arrival_correction(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    watermark_step: int,
    injected_step: int,
    injected_knowledge_step: int,
) -> LateArrivalCorrectionReport:
    """Guide s5.4's six-step fault-injection path, explicitly labelled synthetic.

    ADR-005 decision 7 constrains this hard: late arrivals exist only in labelled test fixtures,
    every value is hand-chosen so at least one row sits exactly on the ``<=`` boundary, they are
    never generated randomly, never written into the main dataset, and never tied to the
    train/validation/test split. ADR-005's whole reason for adding ``knowledge_step`` was that this
    path must run through the *same* SQL as production, so it must not grow a test-only query.
    """

    raise NotImplementedError("T3 round-0 skeleton")


def cleanup_staging(*, artifact_root: Path, run_id: str) -> tuple[str, ...]:
    """Remove one run's staging tree and return what was removed.

    Only ever deletes below ``artifacts/runs/<run_id>/staging/``. Guide s10.1 draws the same line
    for ``make clean-runtime``: recoverable state at a clearly resolved path, never raw data.
    """

    raise NotImplementedError("T3 round-0 skeleton")
