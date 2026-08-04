"""T4 -- the training run and its MLflow contract (guide s6.3).

Gate: **G4 Training** -- "temporal run cua model da chon sau EDA co MLflow artifacts day du"
(guide s13). G4 is about *completeness of evidence*, not about a metric threshold: guide s6.4 says
plainly that a candidate need not beat the baseline to demonstrate the platform, and that an honest
report of a loss is the required outcome when it does not.

Constraints that are already decided and must not be reopened here:

* Local CPU, single node. No Ray Train, no Ray Tune (guide s6, AGENTS.md s11). A small
  deterministic candidate/config matrix is allowed; large-scale HPO is not.
* PR-AUC is the primary metric; ROC-AUC and recall at fixed FPR are secondary. Accuracy is never
  the primary metric for this imbalance (AGENTS.md s9, CLAUDE.md).
* Never tune a model to hide a correctness failure (CLAUDE.md). A metric that drops after leakage
  removal is a valid result -- that is exactly what E4's 0.102766 against E2's 0.915528 records.
* Model family is LightGBM as the selected *candidate*, not a promoted family (ADR-003).

MLflow and LightGBM are optional dependency groups (``training``, ``tracking`` in
``pyproject.toml``). They are imported inside function bodies, never at module scope, so importing
``pit_fintech.training`` cannot break ``test-unit``/``test-temporal`` resolution -- the same line
``platform/feast_registry.py`` holds for Feast.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pit_fintech.training.dataset import TrainingDataset

#: Guide s6.3 makes these ten tags mandatory on every training run. A run missing one is not a G4
#: pass -- the gate is the evidence, not the model.
REQUIRED_MLFLOW_TAGS: tuple[str, ...] = (
    "dataset_snapshot_id",
    "bronze_table_version",
    "silver_table_version",
    "gold_feature_table_version",
    "entity_version",
    "feature_service_version",
    "training_dataset_checksum",
    "split_policy",
    "code_commit",
    "candidate_or_baseline",
)

#: Guide s6.3 required artifacts, by the name they are logged under.
REQUIRED_MLFLOW_ARTIFACTS: tuple[str, ...] = (
    "model",
    "ordered_feature_names.json",
    "feature_dtypes.json",
    "preprocessing.pkl",
    "metrics.json",
    "confusion_and_cost_curves.json",
    "environment_lock.txt",
    "sample_prediction_contract.json",
)

#: MLflow registry aliases (AGENTS.md s7, guide s6.4). Only the promotion command may move
#: ``champion``/``previous``; a training run may only ever set ``candidate``.
MODEL_ALIAS_CANDIDATE: str = "candidate"
MODEL_ALIAS_CHAMPION: str = "champion"
MODEL_ALIAS_PREVIOUS: str = "previous"


@dataclass(frozen=True, slots=True, kw_only=True)
class MlflowRunContract:
    """The ten mandatory tags of guide s6.3, as fields rather than a free-form dict.

    Typed one field per tag on purpose: a ``dict[str, str]`` makes a missing mandatory tag a
    runtime discovery, and G4 is precisely the gate that a tag was not missing.
    """

    dataset_snapshot_id: str
    bronze_table_version: int
    silver_table_version: int
    gold_feature_table_version: int
    entity_version: str
    feature_service_version: str
    training_dataset_checksum: str
    split_policy: str
    code_commit: str
    candidate_or_baseline: Literal["candidate", "baseline"]


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingConfig:
    """One deterministic training configuration.

    ``seed`` plus a pinned dependency lock is what makes a run reproducible; ``fixed_fpr`` is the
    operating point the secondary metrics are read at, matching the Sprint 1 baseline so the
    numbers stay comparable.
    """

    experiment_id: Literal["E1", "E2", "E3", "E4", "E5"]
    model_family: Literal["lightgbm"]
    feature_set: Literal["static", "leaky", "pit"]
    parameters: dict[str, int | float | str | bool]
    seed: int
    fixed_fpr: float
    early_stopping_rounds: int
    max_boost_rounds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingMetrics:
    """Primary and secondary metrics at the locked operating point.

    PR-AUC first because it is the primary metric (AGENTS.md s9). Accuracy is absent by design.
    """

    test_pr_auc: float
    test_roc_auc: float
    test_recall_at_fixed_fpr: float
    test_precision_at_fixed_fpr: float
    test_observed_fpr: float
    validation_pr_auc: float
    validation_threshold: float
    validation_threshold_policy: Literal["max-tpr-within-fpr", "zero-positive-fallback"]
    best_iteration: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SlicedMetrics:
    """ADR-002 consequence 3: report ``CASH_OUT`` warm, ``CASH_OUT`` cold and ``TRANSFER`` cold
    separately, in addition to population metrics.

    Not optional colour. ADR-002 found destination history meaningful for some ``CASH_OUT`` events
    and effectively absent for fraudulent ``TRANSFER`` events, so a single population number hides
    the one thing this dataset is honest about.
    """

    slice_name: Literal["population", "cash_out_warm", "cash_out_cold", "transfer_cold"]
    rows: int
    fraud_rows: int
    pr_auc: float
    roc_auc: float
    recall_at_fixed_fpr: float


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingRunResult:
    """One completed training run and the evidence G4 reads.

    :attr:`missing_tags` and :attr:`missing_artifacts` are populated rather than raised, so a run
    that produced a model but not complete evidence is recorded as exactly that instead of
    disappearing.
    """

    status: Literal["completed", "failed"]
    run_id: str
    created_at: datetime
    config: TrainingConfig
    tags: MlflowRunContract
    metrics: TrainingMetrics
    sliced_metrics: tuple[SlicedMetrics, ...]
    ordered_feature_names: tuple[str, ...]
    feature_importance_gain: dict[str, float]
    training_seconds: float
    process_rss_before_bytes: int
    process_rss_after_bytes: int
    mlflow_tracking_uri: str
    mlflow_run_id: str
    mlflow_experiment_name: str
    model_uri: str
    model_alias: str | None
    registered_model_name: str | None
    registered_model_version: int | None
    dependency_lock_sha256: str
    dependency_versions: dict[str, str]
    missing_tags: tuple[str, ...]
    missing_artifacts: tuple[str, ...]
    claim_boundary: tuple[str, ...]


def train_candidate(
    *,
    dataset: TrainingDataset,
    config: TrainingConfig,
    project_root: Path,
    artifact_root: Path,
    mlflow_tracking_uri: str,
    experiment_name: str,
) -> TrainingRunResult:
    """Train one deterministic configuration and log the full guide s6.3 run contract.

    Gate G4. Fits encoding/imputation on train only, selects the threshold on validation, and
    touches test exactly once for the final selected config (guide s6.2). Registers the model under
    alias ``candidate`` and nothing else -- only :func:`~pit_fintech.training.lifecycle.promote`
    may move a deployable alias (guide s6.4).

    Imports MLflow and LightGBM inside the body; they are optional dependency groups.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def run_candidate_matrix(
    *,
    dataset: TrainingDataset,
    configs: tuple[TrainingConfig, ...],
    project_root: Path,
    artifact_root: Path,
    mlflow_tracking_uri: str,
    experiment_name: str,
) -> tuple[TrainingRunResult, ...]:
    """Run a small, deterministic candidate matrix, one MLflow run each (guide s6).

    "Neu can so sanh nhe, chay mot candidate/config matrix nho, deterministic va log tung run vao
    MLflow; khong mo large-scale hyperparameter search." The bound is deliberate: this is a
    platform project, and a search here would be tuning around correctness rather than measuring
    it.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def verify_mlflow_run_contract(
    *,
    mlflow_tracking_uri: str,
    mlflow_run_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read a logged run back and return ``(missing_tags, missing_artifacts)``.

    Gate G4 is "MLflow artifacts day du", so it is checked by reading the tracking server, not by
    trusting what the training process believed it logged. Empty tuples mean the run contract is
    complete.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def log_sample_prediction_contract(
    *,
    mlflow_run_id: str,
    ordered_feature_names: tuple[str, ...],
    feature_dtypes: dict[str, str],
    example_vector: tuple[float, ...],
    example_probability: float,
) -> str:
    """Log the sample prediction contract artifact (guide s6.3).

    This artifact is what guide s6.4's "model input contract khop paysim-fraud-scoring-v2" is
    checked against at promotion time, and what T7 loads to reject a model whose input ordering
    does not match ``PAYSIM_MODEL_FEATURE_ORDER``.
    """

    raise NotImplementedError("T4 round-0 skeleton")
