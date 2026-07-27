"""Machine-readable lineage contracts shared by future pipeline stages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DatasetFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    bytes: int
    sha256: str


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    dataset_snapshot_id: str
    source: str
    files: tuple[DatasetFile, ...]
    source_rows: int
    canonical_rows: int
    code_commit: str


class DatasetSnapshotManifest(BaseModel):
    """Immutable identity and minimum profile for a raw application dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    dataset_snapshot_id: str
    source: str
    file: DatasetFile
    schema_columns: tuple[str, ...]
    source_rows: int
    step_min: int
    step_max: int
    code_commit: str


class DeltaTableSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: Literal["bronze", "silver"]
    table: str
    path: str
    version: int
    rows: int
    schema_checksum: str
    logical_checksum: str


class LakehouseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_snapshot_id: str
    code_commit: str
    tables: tuple[DeltaTableSnapshot, ...]


class DataQualityGateResult(BaseModel):
    """One publish-blocking application-data assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["pass"]
    observed: int
    expected: int


class LakehouseBuildResources(BaseModel):
    """Lightweight local feasibility evidence; RSS values are not sampled peaks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wall_seconds: float
    raw_bytes: int
    delta_parquet_bytes: int
    rows_per_second: float
    process_rss_before_bytes: int
    process_rss_after_bytes: int
    event_day_partitions: int
    arrow_batch_size: int
    target_file_size_bytes: int


class ApplicationLakehouseManifest(BaseModel):
    """Exact PaySim Bronze/Silver versions published for one raw snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed"]
    pipeline_version: str
    dataset: Literal["paysim1"]
    dataset_snapshot_id: str
    source_manifest_path: str
    raw_file_sha256: str
    source_rows: int
    entity_definition_version: str
    feature_definition_version: str
    feature_contract_checksum: str
    code_commit: str
    lineage_policy_version: Literal["component-fingerprint-v1"] | None = None
    lakehouse_component_fingerprint: str | None = None
    lakehouse_component_paths: tuple[str, ...] = ()
    lakehouse_component_dirty: bool | None = None
    repository_dirty: bool | None = None
    resources: LakehouseBuildResources
    quality_gates: tuple[DataQualityGateResult, ...]
    tables: tuple[DeltaTableSnapshot, ...]


class BackfillManifest(BaseModel):
    """Schema reserved for Sprint 2; no backfill state machine is claimed yet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    status: Literal["planned", "running", "validated", "committed", "failed"]
    dataset_snapshot_id: str
    entity_definition_version: str
    feature_definition_version: str
    code_commit: str
    cutoff_start: datetime
    cutoff_end: datetime
    source_checksum: str
    output_checksum: str | None = None


class ModelCandidateResult(BaseModel):
    """One exploratory model result inside a pre-contract experiment matrix."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: Literal["E1", "E2", "E3", "E4"]
    feature_set: Literal["static", "leaky", "pit"]
    split_policy: Literal["random", "temporal"]
    feature_names: tuple[str, ...]
    train_rows: int
    validation_rows: int
    test_rows: int
    train_fraud_rate: float
    validation_fraud_rate: float
    test_fraud_rate: float
    validation_threshold: float
    validation_threshold_policy: Literal[
        "max-tpr-within-fpr",
        "zero-positive-fallback",
    ]
    test_pr_auc: float
    test_roc_auc: float
    test_recall_at_fixed_fpr: float
    test_precision_at_fixed_fpr: float
    test_observed_fpr: float
    best_iteration: int
    training_seconds: float
    process_rss_before_bytes: int
    process_rss_after_bytes: int
    training_dataset_checksum: str
    mlflow_run_id: str
    model_uri: str


class ModelCandidateManifest(BaseModel):
    """Machine-readable evidence for the standalone LightGBM candidate spike."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed"]
    spike_version: str
    run_id: str
    created_at: datetime
    dataset_snapshot_id: str
    dataset_file_sha256: str
    entity_definition_version: str
    candidate_feature_version: str
    model_family: Literal["lightgbm"]
    seed: int
    fixed_fpr: float
    nonfraud_sample_per_group: int
    cohort_rows: int
    cohort_fraud_rows: int
    candidate_table_checksum: str
    cohort_sampling_policy: str
    code_commit: str
    dependency_lock_sha256: str
    dependency_versions: dict[str, str]
    mlflow_tracking_uri: str
    mlflow_parent_run_id: str
    claim_boundary: tuple[str, ...]
    experiments: tuple[ModelCandidateResult, ...]


class TrainingPartitionProfile(BaseModel):
    """Observed label and time coverage for one chronological model partition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["train", "validation", "test"]
    rows: int
    fraud_rows: int
    fraud_rate: float
    step_min: int
    step_max: int
    natural_prevalence: bool


class ModelTrainingResult(BaseModel):
    """One locked temporal baseline trained from the same Silver vector population."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: Literal["E1", "E4"]
    feature_set: Literal["static", "pit"]
    split_policy: Literal["temporal"]
    feature_names: tuple[str, ...]
    validation_threshold: float
    validation_threshold_policy: Literal[
        "max-tpr-within-fpr",
        "zero-positive-fallback",
    ]
    test_pr_auc: float
    test_roc_auc: float
    test_recall_at_fixed_fpr: float
    test_precision_at_fixed_fpr: float
    test_observed_fpr: float
    best_iteration: int
    training_seconds: float
    process_rss_before_bytes: int
    process_rss_after_bytes: int
    training_dataset_checksum: str
    feature_importance_gain: dict[str, float]
    mlflow_run_id: str
    model_uri: str


class SilverTrainingManifest(BaseModel):
    """Reproducible E1/E4 evidence tied to exact PaySim Silver Delta versions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed"]
    pipeline_version: str
    run_id: str
    created_at: datetime
    application_lakehouse_manifest_path: str
    application_lakehouse_code_commit: str
    application_lakehouse_component_fingerprint: str | None = None
    application_lakehouse_component_dirty: bool | None = None
    dataset_snapshot_id: str
    raw_file_sha256: str
    entity_definition_version: str
    feature_definition_version: str
    feature_contract_checksum: str
    source_tables: tuple[DeltaTableSnapshot, ...]
    train_end_step: int
    validation_end_step: int
    train_nonfraud_sample_per_type: int
    training_sampling_policy: str
    vector_rows: int
    vector_fraud_rows: int
    vector_checksum: str
    future_read_violations: int
    partitions: tuple[TrainingPartitionProfile, ...]
    model_family: Literal["lightgbm"]
    model_parameters: dict[str, int | float | str | bool]
    seed: int
    fixed_fpr: float
    code_commit: str
    lineage_policy_version: Literal["component-fingerprint-v1"] | None = None
    training_component_fingerprint: str | None = None
    training_component_paths: tuple[str, ...] = ()
    training_component_dirty: bool | None = None
    repository_dirty: bool | None = None
    dependency_lock_sha256: str
    dependency_versions: dict[str, str]
    mlflow_tracking_uri: str
    mlflow_parent_run_id: str
    claim_boundary: tuple[str, ...]
    experiments: tuple[ModelTrainingResult, ...]
