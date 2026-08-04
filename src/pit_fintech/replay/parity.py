"""T6 -- offline/online parity harness and its checkpoints (guide s8.2, s8.3, s8.4).

Gate: **G6 Parity** -- "mismatch bang 0 theo tolerance tren required checkpoints" (guide s13), and
the gate the whole sprint is judged on: guide s13 restricts Sprint 3 to debug/parity work if it
does not pass. Guide s12 states the sprint's Definition of Done in the same terms -- the same
entity/cutoff/version must produce the same feature vector offline and in online replay.

Guide s8.1's checkpoint procedure, which :func:`compare_at_checkpoint` implements:

1. pick the transaction ``e`` at cutoff ``T``;
2. replay/materialize only the events strictly before ``e``;
3. query the online feature vector **before** updating with ``e``;
4. query offline ``pre_decision_features(e)`` at the same entity and cutoff;
5. canonicalize dtype, order and null;
6. compare and log every mismatch.

``post_event_state(e)`` is applied only after the comparison and the scoring (guide s8.1 closing
line), which is what keeps step 3 honest.

.. warning::

   **Guide s8.3 requires "at least one same-second tie case" and no such case has ever run.**

   T1's committed feature table has 11 rows with 11 distinct ``event_timestamp`` values, so the tie
   path is untested through Feast, through the online store and through the replay driver. Under
   ADR-006 every row within one ``step`` maps to the same instant, so a same-``step`` pair *is* the
   same-second tie -- but whether the built Gold range contains one is a measured fact, never an
   assumption. Read
   :attr:`~pit_fintech.features.build_offline.OfflineFeatureBuildResult.same_step_ties` before
   claiming :attr:`RequiredCheckpoint.SAME_SECOND_TIE`; a probe result of ``0`` means the
   checkpoint is unsatisfiable from that range and must be reported as a gap, not skipped.

Guide s8.4 closes with the rule that matters most when a mismatch appears: **do not raise the float
tolerance before the cause is identified.** The locked tolerance is
``PAYSIM_FEATURE_CONTRACT.float_tolerance`` (1e-6) and AGENTS.md s9 requires integer/categorical
mismatches to be exactly ``0`` -- a tolerance does not apply to them at all.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pit_fintech.materialization.materializer import OnlineStoreConfig
from pit_fintech.replay.driver import ReplayEvent


class RequiredCheckpoint(StrEnum):
    """The six checkpoints guide s8.3 requires. All must be covered for G6 to pass.

    ``SAME_SECOND_TIE`` is the one T1 never reached -- see the module warning.
    ``SYNTHETIC_LATE_ARRIVAL`` is driven by ``backfill.inject_late_arrival_correction`` and is
    labelled synthetic wherever it is reported (ADR-005 decision 7).
    """

    BEGINNING_OF_STREAM = "beginning_of_stream"
    AROUND_HIGH_VOLUME_PERIOD = "around_high_volume_period"
    AROUND_SPLIT_BOUNDARIES = "around_split_boundaries"
    FINAL_MATERIALIZATION = "final_materialization"
    SAME_SECOND_TIE = "same_second_tie"
    SYNTHETIC_LATE_ARRIVAL = "synthetic_late_arrival"


class MismatchKind(StrEnum):
    """Guide s8.4's taxonomy, verbatim and complete.

    Classifying a mismatch is what tells you whether the bug is in the feature computation, the
    materializer, the key namespace or the clock. Guide s8.4: "Khong sua mismatch bang cach tang
    float tolerance truoc khi xac dinh cause" -- this enum is how a cause gets named first.
    """

    VALUE_DIFFERENCE = "value_difference"
    NULL_OR_DEFAULT_MISMATCH = "null_or_default_mismatch"
    DTYPE_OR_ROUNDING_MISMATCH = "dtype_or_rounding_mismatch"
    STALE_ONLINE_TIMESTAMP = "stale_online_timestamp"
    WRONG_FEATURE_VERSION = "wrong_feature_version"
    MISSING_ENTITY = "missing_entity"
    DUPLICATE_OR_DOUBLE_COUNT = "duplicate_or_double_count"
    BOUNDARY_WINDOW_MISMATCH = "boundary_window_mismatch"


@dataclass(frozen=True, slots=True, kw_only=True)
class ParityFieldResult:
    """Guide s8.2's parity result schema, one row per compared field.

    The guide lists exactly these columns::

        run_id, entity_id, cutoff, feature_name, offline_value, online_value,
        absolute_diff, status, offline_version, online_version, watermark

    :attr:`cutoff_step` is the integer ordinal and is the authority; :attr:`cutoff` is the derived
    ADR-006 timestamp, carried because the guide's schema names it. :attr:`mismatch_kind` is the
    guide s8.4 classification and is ``None`` exactly when :attr:`status` is ``"match"``.
    """

    run_id: str
    entity_id: str
    cutoff_step: int
    cutoff: datetime
    feature_name: str
    offline_value: int | float | None
    online_value: int | float | None
    absolute_diff: float | None
    status: Literal["match", "mismatch"]
    mismatch_kind: MismatchKind | None
    offline_version: str
    online_version: str
    watermark: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointResult:
    """One checkpoint compared, all twelve fields.

    :attr:`integer_mismatches` is separated from :attr:`float_mismatches` because the acceptance
    criteria differ: AGENTS.md s9 requires integer/categorical mismatches to be exactly ``0``,
    while float comparison is against the locked tolerance. Merging them into one count would let a
    tolerance argument be applied to an integer difference, which it never legitimately is.
    """

    checkpoint: RequiredCheckpoint
    label: str
    entity_id: str
    cutoff_step: int
    cutoff: datetime
    source_row_number: int
    watermark_step: int
    fields_compared: int
    matches: int
    integer_mismatches: int
    float_mismatches: int
    field_results: tuple[ParityFieldResult, ...]
    online_feature_status: str
    passed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ParityRunReport:
    """Gate G6's evidence for one replay pass.

    :attr:`passed` requires **both** that every compared checkpoint had zero mismatches and that
    :attr:`missing_checkpoints` is empty. A run that compared four checkpoints perfectly and never
    reached the same-second tie is not a G6 pass -- guide s8.3 lists six, and a checkpoint that was
    not reached is a gap in the evidence, not a neutral absence.
    """

    status: Literal["completed", "failed"]
    run_id: str
    started_at: datetime
    finished_at: datetime

    dataset_snapshot_id: str
    feature_definition_version: str
    feature_service_version: str
    feature_contract_checksum: str
    gold_pre_decision_version: int
    gold_post_event_version: int
    online_store: str

    float_tolerance: float
    checkpoints: tuple[CheckpointResult, ...]
    #: Required checkpoints that were never compared. Non-empty means G6 does not pass.
    missing_checkpoints: tuple[RequiredCheckpoint, ...]
    total_fields_compared: int
    total_integer_mismatches: int
    total_float_mismatches: int
    mismatches_by_kind: dict[str, int]
    read_before_update_violations: int
    passed: bool
    report_path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointPlan:
    """Which cutoffs will be compared, resolved before the replay runs.

    Resolving the plan first means an unsatisfiable checkpoint is discovered up front rather than
    at the end of a full pass. :attr:`same_step_tie_available` is filled from T2's
    ``SameStepTieProbe``; when it is ``False``, :attr:`unsatisfiable` names
    :attr:`RequiredCheckpoint.SAME_SECOND_TIE` and the run reports the gap instead of pretending
    the checkpoint list was covered.
    """

    checkpoints: tuple[tuple[RequiredCheckpoint, str, int, int], ...]
    same_step_tie_available: bool
    unsatisfiable: tuple[RequiredCheckpoint, ...]
    notes: tuple[str, ...]


def plan_checkpoints(
    *,
    data_root: Path,
    gold_pre_decision_path: Path,
    start_step: int,
    end_step: int,
    train_end_step: int,
    validation_end_step: int,
    same_step_tie_available: bool,
) -> CheckpointPlan:
    """Resolve concrete cutoffs for all six guide s8.3 checkpoints.

    ``AROUND_SPLIT_BOUNDARIES`` uses the frozen ADR-002 decision 7 boundaries (520/521 and
    631/632). ``AROUND_HIGH_VOLUME_PERIOD`` is chosen deterministically as the densest step in the
    range, so two planning runs over the same data pick the same cutoff.

    ``same_step_tie_available`` comes from T2's probe; it is a parameter rather than something this
    function discovers, so a caller cannot get a plan that claims a tie checkpoint the built range
    does not contain.
    """

    raise NotImplementedError("T6 round-0 skeleton")


def compare_at_checkpoint(
    *,
    run_id: str,
    checkpoint: RequiredCheckpoint,
    label: str,
    event: ReplayEvent,
    store: OnlineStoreConfig,
    gold_pre_decision_path: Path,
    gold_pre_decision_version: int,
    float_tolerance: float,
) -> CheckpointResult:
    """Run guide s8.1's six-step comparison at one cutoff.

    Reads the online vector **before** any update with ``e``, reads offline
    ``pre_decision_features(e)`` at the same entity and cutoff, canonicalizes both, and compares
    field by field. Applying ``post_event_state(e)`` is the caller's job and happens only after
    this returns.
    """

    raise NotImplementedError("T6 round-0 skeleton")


def canonicalize_vector(
    *,
    values: dict[str, int | float | None],
) -> dict[str, int | float]:
    """Guide s8.1 step 5: normalize dtype, field order and nulls before comparing.

    Emits the twelve fields in ``PAYSIM_MODEL_FEATURE_ORDER``, casts to the contract dtypes
    (``int64`` for counts and history flags, ``float64`` for amounts and the request-time fields),
    and replaces a null with the contract default from ``FeatureSpec.default``. A vector that is
    missing a contract field is an error, not a null: a missing field means the two sides are not
    even the same shape, which is a different defect from a value difference.
    """

    raise NotImplementedError("T6 round-0 skeleton")


def classify_mismatch(
    *,
    feature_name: str,
    offline_value: int | float | None,
    online_value: int | float | None,
    offline_version: str,
    online_version: str,
    online_feature_status: str,
    staleness_steps: int | None,
    float_tolerance: float,
) -> MismatchKind | None:
    """Name the cause of one mismatch from guide s8.4's taxonomy, or ``None`` if the field matches.

    Ordered so the structural causes are named before the numeric one: a version mismatch, a
    missing entity or a stale timestamp explains a value difference, and reporting such a case as
    ``VALUE_DIFFERENCE`` invites the tolerance-raising response guide s8.4 forbids.

    Integers are compared exactly. The tolerance applies to float fields only -- AGENTS.md s9
    requires integer/categorical mismatches to be ``0``.
    """

    raise NotImplementedError("T6 round-0 skeleton")


def run_parity_harness(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    store: OnlineStoreConfig,
    run_id: str,
    start_step: int,
    end_step: int,
    gold_pre_decision_version: int,
    gold_post_event_version: int,
    float_tolerance: float,
    same_step_tie_available: bool,
) -> ParityRunReport:
    """Drive one replay pass and compare at every planned checkpoint.

    Gate G6. Uses exactly one :class:`~pit_fintech.replay.driver.ReplayDriver`; the comparison
    happens between the online read and the post-event commit of the chosen event, which is the
    only point at which the two sides are supposed to be equal.

    Returns a report rather than raising on mismatch: G6 needs the full mismatch table to diagnose
    a cause, and raising on the first difference would hide the rest. Guide s8.4 again: identify
    the cause before touching the tolerance.
    """

    raise NotImplementedError("T6 round-0 skeleton")


def write_parity_report(*, report: ParityRunReport, artifact_root: Path) -> Path:
    """Persist the parity report as machine-readable evidence under ``artifacts/parity/``.

    Row shape is guide s8.2's schema so the report can be read without this module. Do not
    hand-edit numbers a command can emit (CLAUDE.md).
    """

    raise NotImplementedError("T6 round-0 skeleton")
