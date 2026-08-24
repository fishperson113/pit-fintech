"""T4 -- model promotion, rollback and the immutable deployment manifest (guide s6.4).

Gate: **G11 Model lifecycle** -- "promote + rollback dung explicit versions/manifests va scoring
tra dung active champion" (guide s13).

Guide s6.4 makes ``make promote RUN_ID=...`` do five things, in this order:

1. re-run the temporal, lineage, parity and model-input-contract gates;
2. resolve a model *version* instead of using ``latest``;
3. write an immutable deployment manifest carrying dataset/Delta/feature/model/code versions;
4. update aliases in a safe order;
5. emit an audit event with a reason and a timestamp.

``make rollback VERSION=...`` accepts only a version that already appeared in a valid deployment
manifest. It never retrains and never silently changes the feature service version.

The alias transition is::

    candidate     -> champion
    old champion  -> previous

The guide's artifact map puts this in ``src/lifecycle/`` (S2-A13). It lives under ``training/``
because the round-0 task assignment gives G11 to T4 alongside G4; the round-0 report records the
divergence so a later reader does not read it as an accident.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

#: Guide s6.4's five promotion criteria. All must pass; the list is a gate, not a checklist to
#: weigh up. "Khong bat buoc candidate phai thang baseline" is deliberately absent -- beating the
#: baseline is not one of the criteria, and adding it would be the exact substitution of a metric
#: for a correctness gate that CLAUDE.md forbids.
PROMOTION_GATE_CRITERIA: tuple[str, ...] = (
    "temporal_data_tests_pass",
    "feature_parity_fixture_pass",
    "no_leaky_or_random_split_artifact",
    "required_metrics_present",
    "model_input_contract_matches_feature_service",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionCriterionResult:
    """One promotion criterion, evaluated at promotion time rather than trusted from a tag."""

    name: str
    status: Literal["pass", "fail"]
    detail: str
    evidence_path: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionGateReport:
    """The re-run gates for one candidate (guide s6.4 step 1).

    Re-run, not re-read: a tag recorded at training time says what was true then, and promotion is
    a later decision against possibly-moved artifacts. ADR-004 is the precedent -- exact
    materialized data and component fingerprints decide compatibility, and a Git commit is audit
    metadata rather than a gate.
    """

    run_id: str
    mlflow_run_id: str
    model_version: int
    criteria: tuple[PromotionCriterionResult, ...]
    passed: bool
    evaluated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DeploymentManifest:
    """The immutable record written on every promotion (guide s6.4 step 3).

    Immutable in the strong sense: a rollback target is only valid if it appears in one of these,
    so editing one retroactively would legitimize a deployment that never happened.
    :attr:`manifest_checksum` covers every other field for exactly that reason.
    """

    manifest_version: Literal["deployment-manifest-v1"]
    deployment_id: str
    promoted_at: datetime
    reason: str
    actor: str

    # what was deployed
    registered_model_name: str
    model_version: int
    model_uri: str
    mlflow_run_id: str
    model_family: str
    ordered_feature_names: tuple[str, ...]
    decision_threshold: float

    # what it was built from
    dataset_snapshot_id: str
    raw_file_sha256: str
    bronze_table_version: int
    silver_transactions_version: int
    silver_labels_version: int
    gold_pre_decision_version: int
    gold_post_event_state_version: int
    entity_definition_version: str
    feature_definition_version: str
    feature_service_version: str
    feature_contract_checksum: str
    training_dataset_checksum: str

    # code and environment
    code_commit: str
    lineage_policy_version: str
    training_component_fingerprint: str
    dependency_lock_sha256: str

    # alias transition actually performed
    previous_champion_version: int | None
    aliases_after: dict[str, int]

    gate_report_path: str
    manifest_checksum: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEvent:
    """Guide s6.4 step 5: an audit event carrying a reason and a timestamp.

    ``"rollback"`` and ``"promote"`` share the shape so the audit trail reads as one sequence.
    """

    event: Literal["promote", "rollback", "promotion_refused"]
    occurred_at: datetime
    actor: str
    reason: str
    deployment_id: str | None
    registered_model_name: str
    from_version: int | None
    to_version: int | None
    feature_service_version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionResult:
    """Outcome of a promotion attempt. Refusal is a normal, recorded outcome."""

    promoted: bool
    gate_report: PromotionGateReport
    manifest: DeploymentManifest | None
    manifest_path: str | None
    audit_event: AuditEvent
    failed_criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RollbackResult:
    """Outcome of a rollback (guide s6.4).

    :attr:`source_manifest_path` is the proof the target version was ever legitimately deployed --
    a rollback to a version with no manifest is refused, not performed with a warning.
    :attr:`feature_service_version_unchanged` records the other half of the guide's sentence:
    rollback does not retrain and does not silently change the feature service version.
    """

    rolled_back: bool
    from_version: int | None
    to_version: int
    source_manifest_path: str | None
    audit_event: AuditEvent
    feature_service_version_unchanged: bool
    refusal_reason: str | None


def evaluate_promotion_gates(
    *,
    project_root: Path,
    artifact_root: Path,
    mlflow_tracking_uri: str,
    mlflow_run_id: str,
) -> PromotionGateReport:
    """Re-run all five guide s6.4 criteria against a candidate run."""

    raise NotImplementedError("T4 round-0 skeleton")


def promote(
    *,
    project_root: Path,
    artifact_root: Path,
    mlflow_tracking_uri: str,
    run_id: str,
    reason: str,
    actor: str,
    registered_model_name: str,
) -> PromotionResult:
    """Promote a candidate to champion, following guide s6.4's five steps in order.

    Gate G11. Resolves an explicit model version -- never ``latest`` -- and moves aliases only
    after the manifest is durably written, so a crash mid-promotion leaves the old champion serving
    rather than an alias pointing at an undocumented version.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def rollback(
    *,
    project_root: Path,
    artifact_root: Path,
    mlflow_tracking_uri: str,
    registered_model_name: str,
    version: int,
    reason: str,
    actor: str,
) -> RollbackResult:
    """Roll back to a version that appears in a valid deployment manifest, or refuse.

    Gate G11. No retraining, no feature-service-version change (guide s6.4). A version with no
    manifest is refused with :attr:`RollbackResult.refusal_reason` set -- the manifest requirement
    is the whole safety property, so it is not overridable by a flag.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def write_deployment_manifest(*, manifest: DeploymentManifest, artifact_root: Path) -> Path:
    """Persist a deployment manifest immutably under ``artifacts/deployments/``.

    Refuses to overwrite an existing ``deployment_id``: these are the records rollback validates
    against, so a silent overwrite would let a rollback target be rewritten after the fact.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def load_deployment_manifests(*, artifact_root: Path) -> tuple[DeploymentManifest, ...]:
    """Every valid deployment manifest, oldest first, checksum-verified on load."""

    raise NotImplementedError("T4 round-0 skeleton")


def active_champion(
    *,
    mlflow_tracking_uri: str,
    registered_model_name: str,
) -> tuple[int, DeploymentManifest] | None:
    """Resolve the champion version and the manifest that put it there.

    Gate G11's second half -- "scoring tra dung active champion" -- is checked by comparing what
    T7 reports serving against what this returns. ``None`` means no champion is deployed, which a
    readiness probe must treat as not-ready rather than fall back to ``latest``.
    """

    raise NotImplementedError("T4 round-0 skeleton")
