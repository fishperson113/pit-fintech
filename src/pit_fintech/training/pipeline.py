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

import hashlib
import pickle
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import psutil
import pyarrow.parquet as pq

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
    progress: bool = False,
) -> TrainingRunResult:
    """Train one deterministic temporal candidate and log its complete MLflow evidence."""

    from pit_fintech.features.paysim_specs import (
        PAYSIM_MODEL_FEATURE_ORDER,
        PAYSIM_STATIC_FEATURE_NAMES,
    )
    from pit_fintech.models.paysim_lightgbm import (
        SKOPS_TRUSTED_LIGHTGBM_TYPES,
        _binary_operating_metrics,
        _load_training_dependencies,
        _model_parameters,
        _threshold_for_fixed_fpr,
        configure_mlflow_experiment,
    )

    if dataset.split_policy != "temporal_frozen":
        raise ValueError("train_candidate requires the frozen temporal training dataset")
    progress_started = time.perf_counter()

    def report(message: str) -> None:
        if progress:
            elapsed = time.perf_counter() - progress_started
            print(f"[t4 +{elapsed:8.1f}s] {message}", flush=True)

    report("reading training dataframe")
    dependencies = _load_training_dependencies()
    table = pq.read_table(dataset.retrieval.parquet_path)
    feature_names = tuple(
        PAYSIM_STATIC_FEATURE_NAMES
        if config.feature_set == "static"
        else PAYSIM_MODEL_FEATURE_ORDER
    )
    missing = [name for name in feature_names if name not in table.column_names]
    if missing or "step" not in table.column_names or "isFraud" not in table.column_names:
        raise ValueError(f"training dataframe is missing required columns: {missing}")

    numpy = dependencies.numpy
    steps = numpy.asarray(table["step"].combine_chunks().to_numpy(zero_copy_only=False))
    labels = numpy.asarray(table["isFraud"].combine_chunks().to_numpy(zero_copy_only=False)).astype(
        "int64", copy=False
    )
    train_indices = numpy.flatnonzero(steps <= 520)
    validation_indices = numpy.flatnonzero((steps >= 521) & (steps <= 631))
    test_indices = numpy.flatnonzero((steps >= 632) & (steps <= 743))
    for name, indices in (
        ("train", train_indices),
        ("validation", validation_indices),
        ("test", test_indices),
    ):
        if len(indices) == 0 or len(numpy.unique(labels[indices])) != 2:
            raise RuntimeError(f"{name} partition must contain both fraud and non-fraud rows")
    report(
        f"split sizes: train={len(train_indices):,} validation={len(validation_indices):,} "
        f"test={len(test_indices):,}"
    )

    def matrix(indices: object) -> object:
        return numpy.column_stack(
            [
                numpy.asarray(
                    table[name].combine_chunks().to_numpy(zero_copy_only=False), dtype="float64"
                )[indices]
                for name in feature_names
            ]
        )

    report("building feature matrices")
    train_features = matrix(train_indices)
    validation_features = matrix(validation_indices)
    test_features = matrix(test_indices)
    train_labels = labels[train_indices]
    validation_labels = labels[validation_indices]
    test_labels = labels[test_indices]
    # Pass DataFrames with column names: keeps feature names on the fitted model and silences the
    # sklearn "X does not have valid feature names" warning that numpy inputs trigger.
    pandas = dependencies.pandas
    train_frame = pandas.DataFrame(train_features, columns=feature_names)
    validation_frame = pandas.DataFrame(validation_features, columns=feature_names)
    rss_before = psutil.Process().memory_info().rss
    started = time.perf_counter()
    parameters = {
        **_model_parameters(config.seed),
        **config.parameters,
        "n_estimators": config.max_boost_rounds,
    }
    model = dependencies.lightgbm.LGBMClassifier(**parameters)
    callbacks = [dependencies.lightgbm.early_stopping(config.early_stopping_rounds, verbose=False)]
    if progress:
        callbacks.append(dependencies.lightgbm.log_evaluation(period=10))
    report(
        f"fitting LightGBM {config.experiment_id}/{config.feature_set} "
        f"({len(feature_names)} features, up to {config.max_boost_rounds} rounds)"
    )
    model.fit(
        train_frame,
        train_labels,
        eval_X=validation_frame,
        eval_y=validation_labels,
        eval_metric="binary_logloss",
        callbacks=callbacks,
    )
    training_seconds = time.perf_counter() - started
    report(f"training complete in {training_seconds:.1f}s")
    rss_after = psutil.Process().memory_info().rss
    report("computing validation threshold and test metrics")
    test_frame = pandas.DataFrame(test_features, columns=feature_names)
    validation_scores = model.predict_proba(validation_frame)[:, 1]
    test_scores = model.predict_proba(test_frame)[:, 1]
    threshold_selection = _threshold_for_fixed_fpr(
        validation_labels, validation_scores, fixed_fpr=config.fixed_fpr, dependencies=dependencies
    )
    threshold = threshold_selection.threshold
    operating = _binary_operating_metrics(test_labels, test_scores, threshold)
    metrics_values = {
        "test_pr_auc": float(dependencies.average_precision_score(test_labels, test_scores)),
        "test_roc_auc": float(dependencies.roc_auc_score(test_labels, test_scores)),
        "validation_pr_auc": float(
            dependencies.average_precision_score(validation_labels, validation_scores)
        ),
        "validation_threshold": threshold,
        **operating,
    }

    lock_path = project_root / "uv.lock"
    lock_digest = (
        hashlib.sha256(lock_path.read_bytes()).hexdigest() if lock_path.exists() else "missing"
    )
    configure_mlflow_experiment(
        dependencies.mlflow,
        tracking_uri=mlflow_tracking_uri,
        experiment_name=experiment_name,
        artifact_uri=None,
    )
    spec = dataset.retrieval.spec
    tags = MlflowRunContract(
        dataset_snapshot_id=spec.dataset_snapshot_id,
        bronze_table_version=0,
        silver_table_version=spec.label_table_version,
        gold_feature_table_version=spec.gold_pre_decision.version,
        entity_version=spec.entity_definition_version,
        feature_service_version=spec.feature_service_version,
        training_dataset_checksum=dataset.training_dataset_checksum,
        split_policy=dataset.split_policy,
        code_commit="UNCOMMITTED",
        candidate_or_baseline="candidate",
    )
    with dependencies.mlflow.start_run(
        run_name=f"{config.experiment_id}-{config.feature_set}"
    ) as run:
        dependencies.mlflow.set_tags(
            {name: str(getattr(tags, name)) for name in REQUIRED_MLFLOW_TAGS}
        )
        dependencies.mlflow.log_params({**parameters, "experiment_id": config.experiment_id})
        dependencies.mlflow.log_metrics(metrics_values)
        dependencies.mlflow.log_dict(
            {"ordered_feature_names": list(feature_names)}, "ordered_feature_names.json"
        )
        dependencies.mlflow.log_dict(
            {name: str(table.schema.field(name).type) for name in feature_names},
            "feature_dtypes.json",
        )
        with tempfile.TemporaryDirectory() as preprocessing_dir:
            preprocessing_path = Path(preprocessing_dir) / "preprocessing.pkl"
            preprocessing_path.write_bytes(pickle.dumps({"kind": "identity", "fit_on": "train"}))
            dependencies.mlflow.log_artifact(str(preprocessing_path), artifact_path=None)
        dependencies.mlflow.log_dict(metrics_values, "metrics.json")
        dependencies.mlflow.log_dict(
            {"threshold": threshold, "fixed_fpr": config.fixed_fpr},
            "confusion_and_cost_curves.json",
        )
        dependencies.mlflow.log_text(lock_path.read_text(encoding="utf-8"), "environment_lock.txt")
        dependencies.mlflow.log_dict(
            {"feature_names": list(feature_names)}, "sample_prediction_contract.json"
        )
        dependencies.mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            serialization_format="skops",
            skops_trusted_types=list(SKOPS_TRUSTED_LIGHTGBM_TYPES),
        )
        mlflow_run_id = run.info.run_id

    missing_tags, missing_artifacts = verify_mlflow_run_contract(
        mlflow_tracking_uri=mlflow_tracking_uri, mlflow_run_id=mlflow_run_id
    )
    training_metrics = TrainingMetrics(
        test_pr_auc=metrics_values["test_pr_auc"],
        test_roc_auc=metrics_values["test_roc_auc"],
        test_recall_at_fixed_fpr=metrics_values["test_recall_at_fixed_fpr"],
        test_precision_at_fixed_fpr=metrics_values["test_precision_at_fixed_fpr"],
        test_observed_fpr=metrics_values["test_observed_fpr"],
        validation_pr_auc=metrics_values["validation_pr_auc"],
        validation_threshold=threshold,
        validation_threshold_policy=threshold_selection.policy,
        best_iteration=int(model.best_iteration_ or config.max_boost_rounds),
    )
    return TrainingRunResult(
        status="completed" if not missing_tags and not missing_artifacts else "failed",
        run_id=config.experiment_id,
        created_at=datetime.now().astimezone(),
        config=config,
        tags=tags,
        metrics=training_metrics,
        sliced_metrics=(),
        ordered_feature_names=feature_names,
        feature_importance_gain={
            name: float(value)
            for name, value in zip(feature_names, model.feature_importances_, strict=True)
        },
        training_seconds=training_seconds,
        process_rss_before_bytes=rss_before,
        process_rss_after_bytes=rss_after,
        mlflow_tracking_uri=mlflow_tracking_uri,
        mlflow_run_id=mlflow_run_id,
        mlflow_experiment_name=experiment_name,
        model_uri=f"runs:/{mlflow_run_id}/model",
        model_alias=None,
        registered_model_name=None,
        registered_model_version=None,
        dependency_lock_sha256=lock_digest,
        dependency_versions={},
        missing_tags=missing_tags,
        missing_artifacts=missing_artifacts,
        claim_boundary=(
            "Validation and test retain natural prevalence; train negatives are sampled.",
            "PaySim is synthetic and history utility remains correctness-only evidence.",
            "This candidate is not promotable until parity, materialization and lifecycle gates "
            "pass.",
        ),
    )


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

    return tuple(
        train_candidate(
            dataset=dataset,
            config=config,
            project_root=project_root,
            artifact_root=artifact_root,
            mlflow_tracking_uri=mlflow_tracking_uri,
            experiment_name=experiment_name,
        )
        for config in configs
    )


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

    import mlflow

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    run = client.get_run(mlflow_run_id)
    missing_tags = tuple(name for name in REQUIRED_MLFLOW_TAGS if not run.data.tags.get(name))

    def artifact_names(path: str = "") -> set[str]:
        names: set[str] = set()
        for item in client.list_artifacts(mlflow_run_id, path):
            relative = f"{path}/{item.path}".strip("/") if path else item.path
            if item.is_dir:
                names.update(artifact_names(relative))
            else:
                names.add(relative)
        return names

    available = artifact_names()
    logged_model = False
    try:
        logged_model = bool(
            client.search_logged_models(
                [run.info.experiment_id],
                filter_string=f"source_run_id = '{mlflow_run_id}'",
                max_results=1,
            )
        )
    except Exception:
        logged_model = False
    missing = tuple(
        name
        for name in REQUIRED_MLFLOW_ARTIFACTS
        if name != "model"
        and name not in available
        and not any(path.startswith(f"{name}/") for path in available)
    )
    model_present = (
        logged_model or "model" in available or any(path.startswith("model/") for path in available)
    )
    missing_artifacts = ("model", *missing) if not model_present else missing
    return missing_tags, missing_artifacts


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

    import mlflow

    payload = {
        "ordered_feature_names": list(ordered_feature_names),
        "feature_dtypes": feature_dtypes,
        "example_vector": list(example_vector),
        "example_probability": example_probability,
    }
    client = mlflow.MlflowClient()
    client.log_dict(mlflow_run_id, payload, "sample_prediction_contract.json")
    return "sample_prediction_contract.json"
