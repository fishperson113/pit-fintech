"""Standalone LightGBM candidate spike for the PaySim Sprint 1 decision gate.

This module intentionally separates an exploratory model-family spike from the final training
pipeline. It reuses the recipient PIT implementation, logs E1-E4 to MLflow, and emits a
machine-readable manifest. The sampled diagnostic cohort is not a production prevalence sample.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final, Literal

import duckdb
import psutil
import pyarrow as pa

from pit_fintech.contracts.manifests import (
    ModelCandidateManifest,
    ModelCandidateResult,
)
from pit_fintech.data.paysim import connect_paysim, inspect_snapshot
from pit_fintech.features.paysim_recipient import (
    VECTOR_TABLE,
    materialize_recipient_leakage_vectors,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_STATIC_FEATURE_NAMES,
)

LIGHTGBM_SPIKE_VERSION: Final = "paysim-lightgbm-spike-v1"
DEFAULT_SEED: Final = 20_260_727
DEFAULT_FIXED_FPR: Final = 0.01
DEFAULT_NONFRAUD_SAMPLE_PER_GROUP: Final = 5_000
DEFAULT_EXPERIMENT_NAME: Final = "pit-fintech-paysim-lightgbm-spike"
SKOPS_TRUSTED_LIGHTGBM_TYPES: Final = (
    "collections.OrderedDict",
    "lightgbm.basic.Booster",
    "lightgbm.sklearn.LGBMClassifier",
)
COHORT_POLICY: Final = (
    "all customer-destination fraud CASH_OUT/TRANSFER rows plus at most N deterministic "
    "non-fraud rows per temporal split and transaction type"
)

STATIC_FEATURE_COLUMNS: Final = PAYSIM_STATIC_FEATURE_NAMES
PIT_FEATURE_COLUMNS: Final = PAYSIM_MODEL_FEATURE_ORDER
LEAKY_FEATURE_COLUMNS: Final = (
    *STATIC_FEATURE_COLUMNS,
    "current_inclusive_count_1h",
    "current_inclusive_amount_1h",
    "future_count_1h",
    "future_amount_1h",
    "current_inclusive_count_24h",
    "current_inclusive_amount_24h",
    "future_count_24h",
    "future_amount_24h",
    "current_inclusive_count_168h",
    "current_inclusive_amount_168h",
    "future_count_168h",
    "future_amount_168h",
    "leaky_lifetime_count",
    "leaky_lifetime_amount",
)


@dataclass(frozen=True)
class CandidateExperimentSpec:
    experiment_id: Literal["E1", "E2", "E3", "E4"]
    feature_set: Literal["static", "leaky", "pit"]
    split_policy: Literal["random", "temporal"]
    feature_names: tuple[str, ...]
    purpose: str


EXPERIMENT_MATRIX: Final = (
    CandidateExperimentSpec(
        experiment_id="E1",
        feature_set="static",
        split_policy="temporal",
        feature_names=STATIC_FEATURE_COLUMNS,
        purpose="non-history deployable baseline",
    ),
    CandidateExperimentSpec(
        experiment_id="E2",
        feature_set="leaky",
        split_policy="random",
        feature_names=LEAKY_FEATURE_COLUMNS,
        purpose="deliberately leaky positive control; never deployable",
    ),
    CandidateExperimentSpec(
        experiment_id="E3",
        feature_set="pit",
        split_policy="random",
        feature_names=PIT_FEATURE_COLUMNS,
        purpose="separate PIT join effect from temporal split effect",
    ),
    CandidateExperimentSpec(
        experiment_id="E4",
        feature_set="pit",
        split_policy="temporal",
        feature_names=PIT_FEATURE_COLUMNS,
        purpose="candidate deployable semantics; still pre-contract in this spike",
    ),
)

CLAIM_BOUNDARY: Final = (
    "The cohort oversamples fraud, so absolute PR-AUC is not a production prevalence estimate.",
    "E2 is a deliberately leaky positive control and can never be promoted.",
    "LightGBM remains a candidate until the user reviews this evidence and freezes FeatureSpec v1.",
    "This spike does not implement Feast, Gold backfill, Redis parity, promotion, or serving.",
)


@dataclass(frozen=True)
class TrainingDependencies:
    lightgbm: Any
    mlflow: Any
    mlflow_sklearn: Any
    numpy: Any
    average_precision_score: Any
    roc_auc_score: Any
    roc_curve: Any
    train_test_split: Any


@dataclass(frozen=True)
class RunLineage:
    dataset_snapshot_id: str
    candidate_table_checksum: str
    code_commit: str
    dependency_lock_sha256: str


@dataclass(frozen=True)
class ThresholdSelection:
    threshold: float
    policy: Literal["max-tpr-within-fpr", "zero-positive-fallback"]


def _load_training_dependencies() -> TrainingDependencies:
    try:
        import lightgbm
        import mlflow
        import mlflow.sklearn
        import numpy
        from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        raise RuntimeError(
            "Training dependencies are unavailable. Run with `uv run --group training ...` "
            "or launch `lab-training`."
        ) from exc
    return TrainingDependencies(
        lightgbm=lightgbm,
        mlflow=mlflow,
        mlflow_sklearn=mlflow.sklearn,
        numpy=numpy,
        average_precision_score=average_precision_score,
        roc_auc_score=roc_auc_score,
        roc_curve=roc_curve,
        train_test_split=train_test_split,
    )


def build_candidate_table(
    connection: duckdb.DuckDBPyConnection,
    *,
    nonfraud_sample_per_group: int = DEFAULT_NONFRAUD_SAMPLE_PER_GROUP,
    train_end_step: int = 520,
    validation_end_step: int = 631,
) -> pa.Table:
    """Materialize one deterministic cohort containing static, PIT, and leaky columns."""

    materialize_recipient_leakage_vectors(
        connection,
        nonfraud_sample_per_group=nonfraud_sample_per_group,
        train_end_step=train_end_step,
        validation_end_step=validation_end_step,
    )
    return connection.sql(
        f"""
        SELECT
            source_row_number,
            step,
            step::DOUBLE AS event_step,
            split,
            transaction_type,
            CASE WHEN transaction_type = 'TRANSFER' THEN 1.0 ELSE 0.0 END
                AS transaction_type_transfer,
            target_label,
            current_amount,
            pit_prior_count_1h,
            pit_prior_amount_1h,
            recipient_has_history_1h,
            pit_prior_count_24h,
            pit_prior_amount_24h,
            recipient_has_history_24h,
            pit_prior_count_168h,
            pit_prior_amount_168h,
            recipient_has_history_168h,
            current_inclusive_count_1h,
            current_inclusive_amount_1h,
            future_count_1h,
            future_amount_1h,
            current_inclusive_count_24h,
            current_inclusive_amount_24h,
            future_count_24h,
            future_amount_24h,
            current_inclusive_count_168h,
            current_inclusive_amount_168h,
            future_count_168h,
            future_amount_168h,
            leaky_lifetime_count,
            leaky_lifetime_amount
        FROM {VECTOR_TABLE}
        ORDER BY step, source_row_number
        """
    ).to_arrow_table()


def candidate_feature_columns(
    feature_set: Literal["static", "leaky", "pit"],
) -> tuple[str, ...]:
    """Return the predeclared candidate columns without creating a final FeatureSpec."""

    columns = {
        "static": STATIC_FEATURE_COLUMNS,
        "leaky": LEAKY_FEATURE_COLUMNS,
        "pit": PIT_FEATURE_COLUMNS,
    }
    return columns[feature_set]


def default_tracking_uri(artifact_root: Path) -> str:
    """Use a local SQLite MLflow backend so the spike needs no service container."""

    tracking_database = (artifact_root / "mlflow" / "tracking.db").resolve()
    tracking_database.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{tracking_database.as_posix()}"


def default_artifact_uri(artifact_root: Path) -> str:
    """Return the explicit local artifact root paired with the SQLite backend."""

    artifact_path = (artifact_root / "mlflow" / "artifacts").resolve()
    artifact_path.mkdir(parents=True, exist_ok=True)
    return artifact_path.as_uri()


def configure_mlflow_experiment(
    mlflow: Any,
    *,
    tracking_uri: str,
    experiment_name: str,
    artifact_uri: str | None,
) -> None:
    """Configure one experiment without relying on MLflow's legacy file tracking store."""

    mlflow.set_tracking_uri(tracking_uri)
    if artifact_uri is not None and mlflow.get_experiment_by_name(experiment_name) is None:
        mlflow.create_experiment(
            experiment_name,
            artifact_location=artifact_uri,
        )
    mlflow.set_experiment(experiment_name)


def find_latest_candidate_manifest(artifact_root: Path) -> Path | None:
    """Find the newest completed local spike manifest for notebook display."""

    root = artifact_root.resolve() / "experiments" / "paysim-lightgbm-spike"
    candidates = tuple(root.glob("*/manifest.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def load_candidate_manifest(path: Path) -> ModelCandidateManifest:
    """Load and validate one candidate manifest."""

    return ModelCandidateManifest.model_validate_json(path.read_text(encoding="utf-8"))


def manifest_summary_rows(manifest: ModelCandidateManifest) -> list[dict[str, Any]]:
    """Return notebook/CLI-friendly rows without adding a dataframe dependency."""

    return [
        {
            "experiment": result.experiment_id,
            "features": result.feature_set,
            "split": result.split_policy,
            "test_pr_auc": round(result.test_pr_auc, 6),
            "test_roc_auc": round(result.test_roc_auc, 6),
            "recall_at_fixed_fpr": round(result.test_recall_at_fixed_fpr, 6),
            "observed_fpr": round(result.test_observed_fpr, 6),
            "threshold_policy": result.validation_threshold_policy,
            "seconds": round(result.training_seconds, 3),
            "mlflow_run_id": result.mlflow_run_id,
        }
        for result in manifest.experiments
    ]


def _column_to_numpy(table: pa.Table, column: str, dependencies: TrainingDependencies) -> Any:
    values = table[column].combine_chunks().to_numpy(zero_copy_only=False)
    return dependencies.numpy.asarray(values)


def _matrix(
    table: pa.Table,
    feature_names: tuple[str, ...],
    dependencies: TrainingDependencies,
) -> Any:
    columns = [
        _column_to_numpy(table, feature_name, dependencies).astype("float64", copy=False)
        for feature_name in feature_names
    ]
    return dependencies.numpy.column_stack(columns)


def _validate_partition(labels: Any, name: str, dependencies: TrainingDependencies) -> None:
    if len(labels) == 0:
        raise RuntimeError(f"{name} partition is empty")
    if len(dependencies.numpy.unique(labels)) != 2:
        raise RuntimeError(f"{name} partition must contain fraud and non-fraud rows")


def _partition_indices(
    table: pa.Table,
    *,
    split_policy: Literal["random", "temporal"],
    seed: int,
    dependencies: TrainingDependencies,
) -> tuple[Any, Any, Any]:
    labels = _column_to_numpy(table, "target_label", dependencies).astype("int64", copy=False)
    indices = dependencies.numpy.arange(table.num_rows)
    if split_policy == "temporal":
        split_values = dependencies.numpy.asarray(table["split"].to_pylist())
        train_indices = indices[split_values == "train"]
        validation_indices = indices[split_values == "validation"]
        test_indices = indices[split_values == "test"]
    else:
        train_indices, remainder_indices = dependencies.train_test_split(
            indices,
            test_size=0.4,
            random_state=seed,
            stratify=labels,
        )
        validation_indices, test_indices = dependencies.train_test_split(
            remainder_indices,
            test_size=0.5,
            random_state=seed + 1,
            stratify=labels[remainder_indices],
        )

    _validate_partition(labels[train_indices], "train", dependencies)
    _validate_partition(labels[validation_indices], "validation", dependencies)
    _validate_partition(labels[test_indices], "test", dependencies)
    return train_indices, validation_indices, test_indices


def _threshold_for_fixed_fpr(
    labels: Any,
    scores: Any,
    *,
    fixed_fpr: float,
    dependencies: TrainingDependencies,
) -> ThresholdSelection:
    false_positive_rates, true_positive_rates, thresholds = dependencies.roc_curve(labels, scores)
    eligible = dependencies.numpy.flatnonzero(false_positive_rates <= fixed_fpr)
    if eligible.size == 0:
        raise RuntimeError(f"No validation threshold satisfies fixed FPR {fixed_fpr}")
    best_position = int(eligible[dependencies.numpy.argmax(true_positive_rates[eligible])])
    threshold = float(thresholds[best_position])
    if dependencies.numpy.isfinite(threshold):
        return ThresholdSelection(
            threshold=threshold,
            policy="max-tpr-within-fpr",
        )

    finite = eligible[dependencies.numpy.isfinite(thresholds[eligible])]
    if finite.size:
        best_position = int(finite[dependencies.numpy.argmax(true_positive_rates[finite])])
        return ThresholdSelection(
            threshold=float(thresholds[best_position]),
            policy="max-tpr-within-fpr",
        )

    finite_scores = scores[dependencies.numpy.isfinite(scores)]
    if finite_scores.size == 0:
        raise RuntimeError("Validation scores contain no finite values")
    zero_positive_threshold = float(
        dependencies.numpy.nextafter(
            dependencies.numpy.max(finite_scores),
            dependencies.numpy.inf,
        )
    )
    if not dependencies.numpy.isfinite(zero_positive_threshold):
        raise RuntimeError("Could not construct a finite zero-positive threshold")
    return ThresholdSelection(
        threshold=zero_positive_threshold,
        policy="zero-positive-fallback",
    )


def _binary_operating_metrics(labels: Any, scores: Any, threshold: float) -> dict[str, float]:
    predictions = scores >= threshold
    positives = labels == 1
    negatives = labels == 0
    true_positives = int((predictions & positives).sum())
    false_positives = int((predictions & negatives).sum())
    false_negatives = int((~predictions & positives).sum())
    true_negatives = int((~predictions & negatives).sum())
    recall = true_positives / max(true_positives + false_negatives, 1)
    precision = true_positives / max(true_positives + false_positives, 1)
    observed_fpr = false_positives / max(false_positives + true_negatives, 1)
    return {
        "test_recall_at_fixed_fpr": float(recall),
        "test_precision_at_fixed_fpr": float(precision),
        "test_observed_fpr": float(observed_fpr),
    }


def _fraud_rate(labels: Any) -> float:
    return float(labels.mean())


def _candidate_table_checksum(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _training_dataset_checksum(
    table: pa.Table,
    spec: CandidateExperimentSpec,
    train_indices: Any,
    validation_indices: Any,
    test_indices: Any,
    dependencies: TrainingDependencies,
) -> str:
    source_rows = _column_to_numpy(table, "source_row_number", dependencies)
    payload = {
        "feature_names": list(spec.feature_names),
        "split_policy": spec.split_policy,
        "train_source_rows": [int(value) for value in source_rows[train_indices]],
        "validation_source_rows": [int(value) for value in source_rows[validation_indices]],
        "test_source_rows": [int(value) for value in source_rows[test_indices]],
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _model_parameters(seed: int) -> dict[str, Any]:
    return {
        "objective": "binary",
        "n_estimators": 300,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_child_samples": 50,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_alpha": 0.0,
        "reg_lambda": 0.0,
        "random_state": seed,
        "n_jobs": 1,
        "deterministic": True,
        "force_col_wise": True,
        "verbosity": -1,
    }


def _train_experiment(
    table: pa.Table,
    spec: CandidateExperimentSpec,
    *,
    seed: int,
    fixed_fpr: float,
    lineage: RunLineage,
    dependencies: TrainingDependencies,
) -> tuple[Any, ModelCandidateResult]:
    features = _matrix(table, spec.feature_names, dependencies)
    labels = _column_to_numpy(table, "target_label", dependencies).astype("int64", copy=False)
    train_indices, validation_indices, test_indices = _partition_indices(
        table,
        split_policy=spec.split_policy,
        seed=seed,
        dependencies=dependencies,
    )
    train_features = features[train_indices]
    validation_features = features[validation_indices]
    test_features = features[test_indices]
    train_labels = labels[train_indices]
    validation_labels = labels[validation_indices]
    test_labels = labels[test_indices]
    training_dataset_checksum = _training_dataset_checksum(
        table,
        spec,
        train_indices,
        validation_indices,
        test_indices,
        dependencies,
    )

    process = psutil.Process()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    model = dependencies.lightgbm.LGBMClassifier(**_model_parameters(seed))
    model.fit(
        train_features,
        train_labels,
        eval_X=validation_features,
        eval_y=validation_labels,
        eval_metric="binary_logloss",
        callbacks=[dependencies.lightgbm.early_stopping(30, verbose=False)],
        feature_name=list(spec.feature_names),
    )
    training_seconds = time.perf_counter() - started
    rss_after = process.memory_info().rss

    validation_scores = model.predict_proba(validation_features)[:, 1]
    test_scores = model.predict_proba(test_features)[:, 1]
    threshold_selection = _threshold_for_fixed_fpr(
        validation_labels,
        validation_scores,
        fixed_fpr=fixed_fpr,
        dependencies=dependencies,
    )
    threshold = threshold_selection.threshold
    operating_metrics = _binary_operating_metrics(test_labels, test_scores, threshold)
    metrics = {
        "test_pr_auc": float(dependencies.average_precision_score(test_labels, test_scores)),
        "test_roc_auc": float(dependencies.roc_auc_score(test_labels, test_scores)),
        **operating_metrics,
    }

    with dependencies.mlflow.start_run(
        run_name=f"{spec.experiment_id}-{spec.feature_set}-{spec.split_policy}",
        nested=True,
    ) as child_run:
        dependencies.mlflow.set_tags(
            {
                "experiment_id": spec.experiment_id,
                "feature_set": spec.feature_set,
                "split_policy": spec.split_policy,
                "candidate_feature_version": PAYSIM_FEATURE_DEFINITION_VERSION,
                "dataset_snapshot_id": lineage.dataset_snapshot_id,
                "candidate_table_checksum": lineage.candidate_table_checksum,
                "training_dataset_checksum": training_dataset_checksum,
                "code_commit": lineage.code_commit,
                "dependency_lock_sha256": lineage.dependency_lock_sha256,
                "deployable": str(spec.experiment_id == "E4").lower(),
                "purpose": spec.purpose,
                "validation_threshold_policy": threshold_selection.policy,
            }
        )
        dependencies.mlflow.log_params(
            {
                **_model_parameters(seed),
                "feature_count": len(spec.feature_names),
                "fixed_fpr": fixed_fpr,
                "train_rows": len(train_indices),
                "validation_rows": len(validation_indices),
                "test_rows": len(test_indices),
            }
        )
        dependencies.mlflow.log_metrics(
            {
                **metrics,
                "validation_threshold": threshold,
                "training_seconds": training_seconds,
                "train_fraud_rate": _fraud_rate(train_labels),
                "validation_fraud_rate": _fraud_rate(validation_labels),
                "test_fraud_rate": _fraud_rate(test_labels),
            }
        )
        dependencies.mlflow.log_dict(
            {
                "feature_names": list(spec.feature_names),
                "feature_dtypes": {feature_name: "float64" for feature_name in spec.feature_names},
                "purpose": spec.purpose,
                "claim_boundary": list(CLAIM_BOUNDARY),
            },
            "feature-set.json",
        )
        dependencies.mlflow_sklearn.log_model(
            sk_model=model,
            name="model",
            input_example=train_features[:5],
            serialization_format="skops",
            skops_trusted_types=list(SKOPS_TRUSTED_LIGHTGBM_TYPES),
        )
        child_run_id = child_run.info.run_id

    result = ModelCandidateResult(
        experiment_id=spec.experiment_id,
        feature_set=spec.feature_set,
        split_policy=spec.split_policy,
        feature_names=spec.feature_names,
        train_rows=len(train_indices),
        validation_rows=len(validation_indices),
        test_rows=len(test_indices),
        train_fraud_rate=_fraud_rate(train_labels),
        validation_fraud_rate=_fraud_rate(validation_labels),
        test_fraud_rate=_fraud_rate(test_labels),
        validation_threshold=threshold,
        validation_threshold_policy=threshold_selection.policy,
        test_pr_auc=metrics["test_pr_auc"],
        test_roc_auc=metrics["test_roc_auc"],
        test_recall_at_fixed_fpr=metrics["test_recall_at_fixed_fpr"],
        test_precision_at_fixed_fpr=metrics["test_precision_at_fixed_fpr"],
        test_observed_fpr=metrics["test_observed_fpr"],
        best_iteration=int(model.best_iteration_ or _model_parameters(seed)["n_estimators"]),
        training_seconds=training_seconds,
        process_rss_before_bytes=rss_before,
        process_rss_after_bytes=rss_after,
        training_dataset_checksum=training_dataset_checksum,
        mlflow_run_id=child_run_id,
        model_uri=f"runs:/{child_run_id}/model",
    )
    return model, result


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_commit(project_root: Path) -> str:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        return "UNCOMMITTED"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    suffix = "-dirty" if status.returncode != 0 or status.stdout.strip() else ""
    return f"{commit.stdout.strip()}{suffix}"


def _atomic_write_manifest(manifest: ModelCandidateManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def run_paysim_lightgbm_spike(
    csv_path: Path,
    *,
    project_root: Path,
    artifact_root: Path,
    nonfraud_sample_per_group: int = DEFAULT_NONFRAUD_SAMPLE_PER_GROUP,
    seed: int = DEFAULT_SEED,
    fixed_fpr: float = DEFAULT_FIXED_FPR,
    tracking_uri: str | None = None,
    experiment_name: str = DEFAULT_EXPERIMENT_NAME,
) -> tuple[ModelCandidateManifest, Path]:
    """Run the pre-contract E1-E4 matrix and persist MLflow plus JSON evidence."""

    if not 0 < fixed_fpr < 1:
        raise ValueError("fixed_fpr must be between 0 and 1")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")

    dependencies = _load_training_dependencies()
    snapshot = inspect_snapshot(csv_path)
    resolved_artifact_root = artifact_root.resolve()
    resolved_tracking_uri = tracking_uri or default_tracking_uri(resolved_artifact_root)
    resolved_artifact_uri = (
        default_artifact_uri(resolved_artifact_root) if tracking_uri is None else None
    )
    configure_mlflow_experiment(
        dependencies.mlflow,
        tracking_uri=resolved_tracking_uri,
        experiment_name=experiment_name,
        artifact_uri=resolved_artifact_uri,
    )

    connection = connect_paysim(csv_path)
    try:
        candidate_table = build_candidate_table(
            connection,
            nonfraud_sample_per_group=nonfraud_sample_per_group,
        )
    finally:
        connection.close()

    labels = candidate_table["target_label"].combine_chunks().to_numpy(zero_copy_only=False)
    cohort_fraud_rows = int(labels.sum())
    candidate_table_checksum = _candidate_table_checksum(candidate_table)
    code_commit = _current_commit(project_root)
    dependency_lock_sha256 = _sha256_file(project_root / "uv.lock")
    lineage = RunLineage(
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        candidate_table_checksum=candidate_table_checksum,
        code_commit=code_commit,
        dependency_lock_sha256=dependency_lock_sha256,
    )
    results: list[ModelCandidateResult] = []
    with dependencies.mlflow.start_run(run_name=LIGHTGBM_SPIKE_VERSION) as parent_run:
        dependencies.mlflow.set_tags(
            {
                "run_type": "candidate-spike",
                "dataset_snapshot_id": snapshot.dataset_snapshot_id,
                "candidate_feature_version": PAYSIM_FEATURE_DEFINITION_VERSION,
                "model_family": "lightgbm",
                "promotion_allowed": "false",
            }
        )
        dependencies.mlflow.log_params(
            {
                "spike_version": LIGHTGBM_SPIKE_VERSION,
                "seed": seed,
                "fixed_fpr": fixed_fpr,
                "nonfraud_sample_per_group": nonfraud_sample_per_group,
                "cohort_rows": candidate_table.num_rows,
                "cohort_fraud_rows": cohort_fraud_rows,
            }
        )
        for spec in EXPERIMENT_MATRIX:
            _, result = _train_experiment(
                candidate_table,
                spec,
                seed=seed,
                fixed_fpr=fixed_fpr,
                lineage=lineage,
                dependencies=dependencies,
            )
            results.append(result)

        parent_run_id = parent_run.info.run_id
        manifest = ModelCandidateManifest(
            status="completed",
            spike_version=LIGHTGBM_SPIKE_VERSION,
            run_id=parent_run_id,
            created_at=datetime.now(UTC),
            dataset_snapshot_id=snapshot.dataset_snapshot_id,
            dataset_file_sha256=snapshot.sha256,
            entity_definition_version="paysim-destination-customer-v1",
            candidate_feature_version=PAYSIM_FEATURE_DEFINITION_VERSION,
            model_family="lightgbm",
            seed=seed,
            fixed_fpr=fixed_fpr,
            nonfraud_sample_per_group=nonfraud_sample_per_group,
            cohort_rows=candidate_table.num_rows,
            cohort_fraud_rows=cohort_fraud_rows,
            candidate_table_checksum=candidate_table_checksum,
            cohort_sampling_policy=COHORT_POLICY,
            code_commit=code_commit,
            dependency_lock_sha256=dependency_lock_sha256,
            dependency_versions={
                "lightgbm": _package_version("lightgbm"),
                "mlflow": _package_version("mlflow"),
                "numpy": _package_version("numpy"),
                "scikit-learn": _package_version("scikit-learn"),
            },
            mlflow_tracking_uri=dependencies.mlflow.get_tracking_uri(),
            mlflow_parent_run_id=parent_run_id,
            claim_boundary=CLAIM_BOUNDARY,
            experiments=tuple(results),
        )
        dependencies.mlflow.log_dict(
            manifest.model_dump(mode="json"),
            "candidate-spike-manifest.json",
        )

    manifest_path = (
        resolved_artifact_root
        / "experiments"
        / "paysim-lightgbm-spike"
        / parent_run_id
        / "manifest.json"
    )
    _atomic_write_manifest(manifest, manifest_path)
    return manifest, manifest_path
