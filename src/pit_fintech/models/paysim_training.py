"""Locked PaySim E1/E4 training pipeline over exact Silver Delta versions.

The exploratory M016 spike reads the raw CSV and includes deliberately invalid controls. This
module is the clean Sprint 1 baseline: it reads the application-lakehouse manifest, opens the
recorded Delta versions, computes only frozen strict-PIT features, preserves natural prevalence
in validation/test, and emits MLflow plus a validated lineage manifest.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final, Literal

import duckdb
import psutil
import pyarrow as pa
import pyarrow.compute as pc
from deltalake import DeltaTable

from pit_fintech.contracts.manifests import (
    ApplicationLakehouseManifest,
    DeltaTableSnapshot,
    ModelTrainingResult,
    SilverTrainingManifest,
    TrainingPartitionProfile,
)
from pit_fintech.data.paysim_lakehouse import (
    PAYSIM_SILVER_LABEL_COLUMNS,
    PAYSIM_SILVER_TRANSACTION_COLUMNS,
    arrow_schema_checksum,
)
from pit_fintech.features.paysim_recipient import (
    LEAKAGE_WINDOWS_STEPS,
    MAX_LEAKAGE_WINDOW_STEPS,
    PAYSIM_TRAIN_END_STEP,
    PAYSIM_VALIDATION_END_STEP,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY_DEFINITION_VERSION,
    PAYSIM_FEATURE_CONTRACT,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_STATIC_FEATURE_NAMES,
    paysim_feature_contract_checksum,
)
from pit_fintech.models.paysim_lightgbm import (
    SKOPS_TRUSTED_LIGHTGBM_TYPES,
    TrainingDependencies,
    _binary_operating_metrics,
    _load_training_dependencies,
    _model_parameters,
    _threshold_for_fixed_fpr,
    configure_mlflow_experiment,
    default_artifact_uri,
    default_tracking_uri,
)
from pit_fintech.platform.lineage import (
    COMPONENT_FINGERPRINT_POLICY_VERSION,
    component_dirty,
    component_fingerprint,
    current_git_commit,
    repository_dirty,
)

SILVER_TRAINING_PIPELINE_VERSION: Final = "paysim-silver-lightgbm-v1"
DEFAULT_SEED: Final = 20_260_727
DEFAULT_FIXED_FPR: Final = 0.01
DEFAULT_TRAIN_NONFRAUD_PER_TYPE: Final = 100_000
DEFAULT_EXPERIMENT_NAME: Final = "pit-fintech-paysim-silver-baseline"
LINEAGE_POLICY_VERSION: Final = COMPONENT_FINGERPRINT_POLICY_VERSION
TRANSACTION_SOURCE_VIEW: Final = "paysim_silver_transactions"
LABEL_SOURCE_VIEW: Final = "paysim_silver_labels"
TARGET_TABLE: Final = "paysim_training_targets"
VECTOR_TABLE: Final = "paysim_training_vectors"
TRAINING_COMPONENT_PATHS: Final = (
    "src/pit_fintech/models/paysim_training.py",
    "src/pit_fintech/models/paysim_lightgbm.py",
    "src/pit_fintech/contracts/manifests.py",
    "src/pit_fintech/data/paysim_lakehouse.py",
    "src/pit_fintech/features/paysim_recipient.py",
    "src/pit_fintech/features/paysim_specs.py",
    "src/pit_fintech/platform/lineage.py",
    "pyproject.toml",
    "uv.lock",
)

TRAINING_SAMPLING_POLICY: Final = (
    "all eligible train fraud plus at most N deterministic train non-fraud rows per transaction "
    "type; validation and test retain every eligible row at natural PaySim prevalence"
)
CLAIM_BOUNDARY: Final = (
    "Validation and test metrics use natural PaySim prevalence; train negatives are sampled.",
    "PaySim is synthetic and ADR-002 rates history utility AMBER_CORRECTNESS_ONLY.",
    "E4 uses strict prior-step features; same-step, future, label, policy, and balances "
    "are absent.",
    "This baseline is not promotable until Sprint 2 parity, materialization, and version "
    "gates pass.",
)

STATIC_FEATURE_COLUMNS: Final = PAYSIM_STATIC_FEATURE_NAMES
PIT_FEATURE_COLUMNS: Final = PAYSIM_MODEL_FEATURE_ORDER
IDENTITY_COLUMNS: Final = (
    "feature_definition_version",
    "dataset_snapshot_id",
    "source_row_number",
    "source_record_id",
    "step",
    "split",
    "transaction_type",
    "destination_entity_id",
    "target_label",
)
AUDIT_COLUMNS: Final = tuple(
    f"max_pit_source_step_{window_steps}h" for window_steps in LEAKAGE_WINDOWS_STEPS
)
TRAINING_VECTOR_COLUMNS: Final = (
    *IDENTITY_COLUMNS,
    *PIT_FEATURE_COLUMNS,
    *AUDIT_COLUMNS,
)


@dataclass(frozen=True)
class LockedExperimentSpec:
    experiment_id: Literal["E1", "E4"]
    feature_set: Literal["static", "pit"]
    feature_names: tuple[str, ...]
    purpose: str


LOCKED_EXPERIMENTS: Final = (
    LockedExperimentSpec(
        experiment_id="E1",
        feature_set="static",
        feature_names=STATIC_FEATURE_COLUMNS,
        purpose="request-only temporal baseline",
    ),
    LockedExperimentSpec(
        experiment_id="E4",
        feature_set="pit",
        feature_names=PIT_FEATURE_COLUMNS,
        purpose="strict-PIT temporal baseline and Sprint 2 model candidate",
    ),
)


@dataclass(frozen=True)
class LoadedSilverSources:
    manifest: ApplicationLakehouseManifest
    transactions_snapshot: DeltaTableSnapshot
    labels_snapshot: DeltaTableSnapshot
    transactions_dataset: Any
    labels_dataset: Any


@dataclass(frozen=True)
class SilverTrainingVectors:
    table: pa.Table
    checksum: str
    future_read_violations: int
    partitions: tuple[TrainingPartitionProfile, ...]


def _validate_split_contract(train_end_step: int, validation_end_step: int) -> None:
    values = (train_end_step, validation_end_step)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("split boundaries must be integers")
    if train_end_step < 1 or validation_end_step <= train_end_step:
        raise ValueError("split boundaries must satisfy 1 <= train < validation")


def _validate_training_options(
    *,
    train_nonfraud_sample_per_type: int,
    seed: int,
    fixed_fpr: float,
    train_end_step: int,
    validation_end_step: int,
) -> None:
    if (
        isinstance(train_nonfraud_sample_per_type, bool)
        or not isinstance(train_nonfraud_sample_per_type, int)
        or train_nonfraud_sample_per_type < 1
    ):
        raise ValueError("train_nonfraud_sample_per_type must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not 0 < fixed_fpr < 1:
        raise ValueError("fixed_fpr must be between 0 and 1")
    _validate_split_contract(train_end_step, validation_end_step)


def _resolve_path(path: str, project_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root.resolve() / candidate


def _portable_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _snapshot(
    manifest: ApplicationLakehouseManifest,
    *,
    layer: str,
    table: str,
) -> DeltaTableSnapshot:
    matches = tuple(item for item in manifest.tables if item.layer == layer and item.table == table)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {layer}.{table} snapshot, found {len(matches)}")
    return matches[0]


def _validate_lakehouse_contract(manifest: ApplicationLakehouseManifest) -> None:
    expected_checksum = paysim_feature_contract_checksum()
    failures: dict[str, dict[str, str]] = {}
    checks = (
        (
            "entity_definition_version",
            manifest.entity_definition_version,
            PAYSIM_ENTITY_DEFINITION_VERSION,
        ),
        (
            "feature_definition_version",
            manifest.feature_definition_version,
            PAYSIM_FEATURE_DEFINITION_VERSION,
        ),
        (
            "feature_contract_checksum",
            manifest.feature_contract_checksum,
            expected_checksum,
        ),
    )
    for name, observed, expected in checks:
        if observed != expected:
            failures[name] = {"observed": observed, "expected": expected}
    if failures:
        raise ValueError(
            "application lakehouse does not match frozen FeatureSpec: "
            + json.dumps(failures, sort_keys=True)
        )


def _open_exact_delta_source(
    snapshot: DeltaTableSnapshot,
    *,
    project_root: Path,
    expected_columns: tuple[str, ...],
) -> Any:
    table_path = _resolve_path(snapshot.path, project_root)
    if not (table_path / "_delta_log").is_dir():
        raise FileNotFoundError(f"Delta log does not exist: {table_path}")
    delta_table = DeltaTable(table_path, version=snapshot.version)
    if delta_table.version() != snapshot.version:
        raise RuntimeError(
            f"Delta version mismatch for {snapshot.layer}.{snapshot.table}: "
            f"{delta_table.version()} != {snapshot.version}"
        )
    dataset = delta_table.to_pyarrow_dataset()
    if tuple(dataset.schema.names) != expected_columns:
        raise ValueError(
            f"schema columns changed for {snapshot.layer}.{snapshot.table}: "
            f"{tuple(dataset.schema.names)}"
        )
    actual_schema_checksum = arrow_schema_checksum(dataset.schema)
    if actual_schema_checksum != snapshot.schema_checksum:
        raise ValueError(
            f"schema checksum changed for {snapshot.layer}.{snapshot.table}: "
            f"{actual_schema_checksum} != {snapshot.schema_checksum}"
        )
    actual_rows = int(dataset.count_rows())
    if actual_rows != snapshot.rows:
        raise ValueError(
            f"row count changed for {snapshot.layer}.{snapshot.table}: "
            f"{actual_rows} != {snapshot.rows}"
        )
    return dataset


def load_exact_silver_sources(
    manifest_path: Path,
    *,
    project_root: Path,
) -> LoadedSilverSources:
    """Validate one application manifest and open its exact transaction/label versions."""

    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    _validate_lakehouse_contract(manifest)
    transactions_snapshot = _snapshot(
        manifest,
        layer="silver",
        table="paysim_transactions",
    )
    labels_snapshot = _snapshot(
        manifest,
        layer="silver",
        table="paysim_labels",
    )
    if transactions_snapshot.rows != labels_snapshot.rows:
        raise ValueError("Silver transaction and label row counts disagree in the manifest")

    transactions_dataset = _open_exact_delta_source(
        transactions_snapshot,
        project_root=project_root,
        expected_columns=PAYSIM_SILVER_TRANSACTION_COLUMNS,
    )
    labels_dataset = _open_exact_delta_source(
        labels_snapshot,
        project_root=project_root,
        expected_columns=PAYSIM_SILVER_LABEL_COLUMNS,
    )
    return LoadedSilverSources(
        manifest=manifest,
        transactions_snapshot=transactions_snapshot,
        labels_snapshot=labels_snapshot,
        transactions_dataset=transactions_dataset,
        labels_dataset=labels_dataset,
    )


def _source_quality_gate(
    connection: duckdb.DuckDBPyConnection,
    *,
    sources: LoadedSilverSources,
) -> None:
    row = connection.execute(
        f"""
        SELECT
            (
                SELECT count(*) - count(DISTINCT source_row_number)
                FROM {TRANSACTION_SOURCE_VIEW}
            )::BIGINT AS duplicate_transaction_rows,
            (
                SELECT count(*) - count(DISTINCT source_row_number)
                FROM {LABEL_SOURCE_VIEW}
            )::BIGINT AS duplicate_label_rows,
            (
                SELECT count(*)
                FROM {TRANSACTION_SOURCE_VIEW}
                WHERE dataset_snapshot_id != ?
                   OR source_file_sha256 != ?
            )::BIGINT AS transaction_lineage_mismatches,
            (
                SELECT count(*)
                FROM {LABEL_SOURCE_VIEW}
                WHERE dataset_snapshot_id != ?
                   OR source_file_sha256 != ?
            )::BIGINT AS label_lineage_mismatches,
            (
                SELECT count(*)
                FROM {TRANSACTION_SOURCE_VIEW} AS event
                FULL OUTER JOIN {LABEL_SOURCE_VIEW} AS label
                    USING (
                        source_row_number,
                        step,
                        dataset_snapshot_id,
                        source_file_sha256,
                        source_record_id,
                        event_day
                    )
                WHERE event.source_row_number IS NULL
                   OR label.source_row_number IS NULL
            )::BIGINT AS transaction_label_identity_mismatches
        """,
        [
            sources.manifest.dataset_snapshot_id,
            sources.manifest.raw_file_sha256,
            sources.manifest.dataset_snapshot_id,
            sources.manifest.raw_file_sha256,
        ],
    ).fetchone()
    if row is None:  # pragma: no cover - aggregate always returns one row
        raise RuntimeError("Silver source quality query returned no result")
    names = (
        "duplicate_transaction_rows",
        "duplicate_label_rows",
        "transaction_lineage_mismatches",
        "label_lineage_mismatches",
        "transaction_label_identity_mismatches",
    )
    failures = {name: int(value) for name, value in zip(names, row, strict=True) if value != 0}
    if failures:
        raise ValueError(
            "Silver source quality gate failed: " + json.dumps(failures, sort_keys=True)
        )


def _prior_window_predicate(window_steps: int) -> str:
    """Range-join form of ``RANGE BETWEEN {w} PRECEDING AND 1 PRECEDING`` plus knowledge time.

    Kept word-for-word identical to ``paysim_recipient._prior_window_predicate`` so the evidence
    path and the diagnostic path cannot drift apart. Both step bounds are inclusive and
    ``c.step - 1`` excludes every same-step row, matching ADR-003. The knowledge-time condition is
    the ADR-005 addition; on clean data ``knowledge_step = step``, so it is implied by
    ``s.step <= c.step - 1`` and changes nothing.
    """

    return (
        f"s.step >= c.step - {window_steps}"
        " AND s.step <= c.step - 1"
        " AND s.knowledge_step <= c.knowledge_step"
    )


def _window_columns(window_steps: int) -> str:
    prior = _prior_window_predicate(window_steps)
    return f"""
        (count(s.source_row_number) FILTER (WHERE {prior}))::BIGINT
            AS pit_prior_count_{window_steps}h,
        coalesce(
            sum(s.amount) FILTER (WHERE {prior}),
            0.0
        )::DOUBLE AS pit_prior_amount_{window_steps}h,
        (max(s.step) FILTER (WHERE {prior}))::BIGINT
            AS max_pit_source_step_{window_steps}h
    """


def _derived_history_columns(window_steps: int) -> str:
    return f"""
        pit_prior_count_{window_steps}h,
        pit_prior_amount_{window_steps}h,
        CASE WHEN pit_prior_count_{window_steps}h > 0 THEN 1 ELSE 0 END::BIGINT
            AS recipient_has_history_{window_steps}h
    """


def _materialize_vector_table(
    connection: duckdb.DuckDBPyConnection,
    *,
    dataset_snapshot_id: str,
    train_nonfraud_sample_per_type: int,
    seed: int,
    train_end_step: int,
    validation_end_step: int,
) -> None:
    scoring_types = ", ".join(
        "'" + value.replace("'", "''") + "'"
        for value in PAYSIM_FEATURE_CONTRACT.scoring_transaction_types
    )
    scoring_destination_kinds = ", ".join(
        "'" + value.replace("'", "''") + "'"
        for value in PAYSIM_FEATURE_CONTRACT.scoring_destination_kinds
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {TARGET_TABLE} AS
        WITH joined AS (
            SELECT
                event.dataset_snapshot_id,
                event.source_row_number,
                event.source_record_id,
                event.step,
                event.transaction_type,
                event.amount AS current_amount,
                event.destination_entity_id,
                label.isFraud::TINYINT AS target_label,
                CASE
                    WHEN event.step <= {train_end_step} THEN 'train'
                    WHEN event.step <= {validation_end_step} THEN 'validation'
                    ELSE 'test'
                END AS split
            FROM {TRANSACTION_SOURCE_VIEW} AS event
            JOIN {LABEL_SOURCE_VIEW} AS label
                USING (
                    source_row_number,
                    step,
                    dataset_snapshot_id,
                    source_file_sha256,
                    source_record_id,
                    event_day
                )
            WHERE event.transaction_type IN ({scoring_types})
              AND event.destination_entity_kind IN ({scoring_destination_kinds})
        ), ranked AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY split, transaction_type, target_label
                    ORDER BY
                        (
                            source_row_number * 1103515245 + {seed}
                        ) % 2147483647,
                        source_row_number
                ) AS sample_rank
            FROM joined
        )
        SELECT
            dataset_snapshot_id,
            source_row_number,
            source_record_id,
            step,
            transaction_type,
            current_amount,
            destination_entity_id,
            target_label,
            split
        FROM ranked
        WHERE split != 'train'
           OR target_label = 1
           OR sample_rank <= {train_nonfraud_sample_per_type}
        """
    )

    window_columns = ",\n".join(
        _window_columns(window_steps).strip() for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    derived_columns = ",\n".join(
        _derived_history_columns(window_steps).strip() for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    max_source_columns = ",\n".join(
        f"history.max_pit_source_step_{window_steps}h" for window_steps in LEAKAGE_WINDOWS_STEPS
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {VECTOR_TABLE} AS
        WITH target_destinations AS (
            SELECT DISTINCT destination_entity_id
            FROM {TARGET_TABLE}
        ), scoped_history AS (
            SELECT
                event.source_row_number,
                event.source_record_id,
                event.step,
                event.knowledge_step,
                event.transaction_type,
                event.destination_entity_id,
                event.amount
            FROM {TRANSACTION_SOURCE_VIEW} AS event
            SEMI JOIN target_destinations
                USING (destination_entity_id)
        ), windowed AS (
            SELECT
                c.source_row_number,
                c.source_record_id,
                c.step,
                c.transaction_type,
                c.destination_entity_id,
                c.amount,
                {window_columns}
            FROM scoped_history AS c
            LEFT JOIN scoped_history AS s
                -- Widest-window prune only. Eligibility, including the knowledge-time
                -- half of the invariant, lives entirely in the FILTER predicate so that
                -- _prior_window_predicate stays the single source of truth.
                ON s.destination_entity_id = c.destination_entity_id
                AND s.step >= c.step - {MAX_LEAKAGE_WINDOW_STEPS}
                AND s.step <= c.step - 1
            GROUP BY
                c.source_row_number,
                c.source_record_id,
                c.step,
                c.knowledge_step,
                c.transaction_type,
                c.destination_entity_id,
                c.amount
        ), target_vectors AS (
            SELECT
                '{PAYSIM_FEATURE_DEFINITION_VERSION}'::VARCHAR
                    AS feature_definition_version,
                target.dataset_snapshot_id,
                target.source_row_number,
                target.source_record_id,
                target.step,
                target.split,
                target.transaction_type,
                target.destination_entity_id,
                target.target_label,
                target.current_amount::DOUBLE AS current_amount,
                target.step::DOUBLE AS event_step,
                CASE WHEN target.transaction_type = 'TRANSFER' THEN 1.0 ELSE 0.0 END::DOUBLE
                    AS transaction_type_transfer,
                {
            ", ".join(
                f"history.pit_prior_count_{window_steps}h, history.pit_prior_amount_{window_steps}h"
                for window_steps in LEAKAGE_WINDOWS_STEPS
            )
        },
                {max_source_columns}
            FROM windowed AS history
            JOIN {TARGET_TABLE} AS target
                USING (
                    source_row_number,
                    source_record_id,
                    step,
                    transaction_type,
                    destination_entity_id
                )
        )
        SELECT
            feature_definition_version,
            dataset_snapshot_id,
            source_row_number,
            source_record_id,
            step,
            split,
            transaction_type,
            destination_entity_id,
            target_label,
            current_amount,
            event_step,
            transaction_type_transfer,
            {derived_columns},
            {max_source_columns}
        FROM target_vectors AS history
        ORDER BY step, source_row_number
        """
    )

    target_count = connection.execute(f"SELECT count(*) FROM {TARGET_TABLE}").fetchone()
    vector_count = connection.execute(f"SELECT count(*) FROM {VECTOR_TABLE}").fetchone()
    target_rows = int(target_count[0]) if target_count is not None else 0
    vector_rows = int(vector_count[0]) if vector_count is not None else 0
    if target_rows == 0:
        raise ValueError("scoring scope produced no Silver training targets")
    if vector_rows != target_rows:
        raise RuntimeError(
            f"target/vector identity mismatch: {target_rows} targets, {vector_rows} vectors"
        )
    snapshot_mismatches = connection.execute(
        f"""
        SELECT count(*)
        FROM {VECTOR_TABLE}
        WHERE dataset_snapshot_id != ?
        """,
        [dataset_snapshot_id],
    ).fetchone()
    if snapshot_mismatches is None or int(snapshot_mismatches[0]) != 0:
        raise RuntimeError("training vectors crossed dataset snapshot boundaries")


def _arrow_table_checksum(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _partition_table(table: pa.Table, name: str) -> pa.Table:
    return table.filter(pc.equal(table["split"], name))


def _partition_profile(
    table: pa.Table,
    *,
    name: Literal["train", "validation", "test"],
) -> TrainingPartitionProfile:
    partition = _partition_table(table, name)
    if partition.num_rows == 0:
        raise ValueError(f"{name} partition is empty")
    fraud_rows = int(pc.sum(partition["target_label"]).as_py())
    step_min = int(pc.min(partition["step"]).as_py())
    step_max = int(pc.max(partition["step"]).as_py())
    return TrainingPartitionProfile(
        name=name,
        rows=partition.num_rows,
        fraud_rows=fraud_rows,
        fraud_rate=fraud_rows / partition.num_rows,
        step_min=step_min,
        step_max=step_max,
        natural_prevalence=name != "train",
    )


def _future_read_violations(table: pa.Table) -> int:
    violations = 0
    for column in AUDIT_COLUMNS:
        comparison = pc.greater_equal(table[column], table["step"])
        violations += int(pc.sum(pc.fill_null(comparison, False)).as_py())
    return violations


def build_silver_training_vectors(
    manifest_path: Path,
    *,
    project_root: Path,
    train_nonfraud_sample_per_type: int = DEFAULT_TRAIN_NONFRAUD_PER_TYPE,
    seed: int = DEFAULT_SEED,
    train_end_step: int = PAYSIM_TRAIN_END_STEP,
    validation_end_step: int = PAYSIM_VALIDATION_END_STEP,
) -> tuple[SilverTrainingVectors, LoadedSilverSources]:
    """Build the locked model population from exact Silver versions without fitting a model."""

    _validate_training_options(
        train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
        seed=seed,
        fixed_fpr=DEFAULT_FIXED_FPR,
        train_end_step=train_end_step,
        validation_end_step=validation_end_step,
    )
    sources = load_exact_silver_sources(
        manifest_path,
        project_root=project_root,
    )
    connection = duckdb.connect()
    try:
        connection.execute("SET preserve_insertion_order = true")
        connection.register(TRANSACTION_SOURCE_VIEW, sources.transactions_dataset)
        connection.register(LABEL_SOURCE_VIEW, sources.labels_dataset)
        _source_quality_gate(connection, sources=sources)
        _materialize_vector_table(
            connection,
            dataset_snapshot_id=sources.manifest.dataset_snapshot_id,
            train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
            seed=seed,
            train_end_step=train_end_step,
            validation_end_step=validation_end_step,
        )
        table = connection.sql(
            f"""
            SELECT {", ".join(TRAINING_VECTOR_COLUMNS)}
            FROM {VECTOR_TABLE}
            ORDER BY step, source_row_number
            """
        ).to_arrow_table()
    finally:
        connection.close()

    if tuple(table.column_names) != TRAINING_VECTOR_COLUMNS:
        raise RuntimeError("training vector projection disagrees with the frozen column order")
    if set(PAYSIM_FORBIDDEN_MODEL_INPUTS).intersection(PIT_FEATURE_COLUMNS):
        raise RuntimeError("forbidden model fields entered the frozen feature vector")
    future_read_violations = _future_read_violations(table)
    if future_read_violations != 0:
        raise RuntimeError(
            f"strict-PIT training vectors contain {future_read_violations} future reads"
        )
    vectors = SilverTrainingVectors(
        table=table,
        checksum=_arrow_table_checksum(table),
        future_read_violations=future_read_violations,
        partitions=(
            _partition_profile(table, name="train"),
            _partition_profile(table, name="validation"),
            _partition_profile(table, name="test"),
        ),
    )
    return vectors, sources


def _validate_binary_partition(labels: Any, name: str, dependencies: TrainingDependencies) -> None:
    if len(labels) == 0:
        raise RuntimeError(f"{name} partition is empty")
    if len(dependencies.numpy.unique(labels)) != 2:
        raise RuntimeError(f"{name} partition must contain fraud and non-fraud rows")


def _experiment_dataset_checksum(
    vector_checksum: str,
    spec: LockedExperimentSpec,
) -> str:
    canonical = json.dumps(
        {
            "vector_checksum": vector_checksum,
            "experiment_id": spec.experiment_id,
            "feature_names": list(spec.feature_names),
            "split_policy": "temporal",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _model_environment_requirements() -> list[str]:
    packages = ("mlflow", "lightgbm", "scikit-learn", "pandas", "numpy", "skops")
    return [f"{package}=={_package_version(package)}" for package in packages]


def _train_experiment(
    vectors: SilverTrainingVectors,
    spec: LockedExperimentSpec,
    *,
    lineage: dict[str, str],
    seed: int,
    fixed_fpr: float,
    dependencies: TrainingDependencies,
) -> ModelTrainingResult:
    partitions = {
        name: _partition_table(vectors.table, name) for name in ("train", "validation", "test")
    }
    frames = {
        name: table.select(spec.feature_names).to_pandas() for name, table in partitions.items()
    }
    labels = {
        name: dependencies.numpy.asarray(
            table["target_label"].combine_chunks().to_numpy(zero_copy_only=False),
            dtype="int64",
        )
        for name, table in partitions.items()
    }
    for name in ("train", "validation", "test"):
        _validate_binary_partition(labels[name], name, dependencies)

    process = psutil.Process()
    rss_before = process.memory_info().rss
    started = time.perf_counter()
    model_parameters = _model_parameters(seed)
    model = dependencies.lightgbm.LGBMClassifier(**model_parameters)
    model.fit(
        frames["train"],
        labels["train"],
        eval_X=frames["validation"],
        eval_y=labels["validation"],
        eval_metric="binary_logloss",
        callbacks=[dependencies.lightgbm.early_stopping(30, verbose=False)],
        feature_name=list(spec.feature_names),
    )
    training_seconds = time.perf_counter() - started
    rss_after = process.memory_info().rss

    validation_scores = model.predict_proba(
        frames["validation"],
        validate_features=True,
    )[:, 1]
    test_scores = model.predict_proba(
        frames["test"],
        validate_features=True,
    )[:, 1]
    threshold_selection = _threshold_for_fixed_fpr(
        labels["validation"],
        validation_scores,
        fixed_fpr=fixed_fpr,
        dependencies=dependencies,
    )
    operating_metrics = _binary_operating_metrics(
        labels["test"],
        test_scores,
        threshold_selection.threshold,
    )
    metrics = {
        "test_pr_auc": float(dependencies.average_precision_score(labels["test"], test_scores)),
        "test_roc_auc": float(dependencies.roc_auc_score(labels["test"], test_scores)),
        **operating_metrics,
    }
    importance_values = model.booster_.feature_importance(importance_type="gain")
    feature_importance = {
        feature_name: float(value)
        for feature_name, value in zip(spec.feature_names, importance_values, strict=True)
    }
    training_dataset_checksum = _experiment_dataset_checksum(vectors.checksum, spec)

    with dependencies.mlflow.start_run(
        run_name=f"{spec.experiment_id}-{spec.feature_set}-temporal",
        nested=True,
    ) as child_run:
        dependencies.mlflow.set_tags(
            {
                "experiment_id": spec.experiment_id,
                "feature_set": spec.feature_set,
                "split_policy": "temporal",
                "feature_definition_version": PAYSIM_FEATURE_DEFINITION_VERSION,
                "feature_contract_checksum": paysim_feature_contract_checksum(),
                "dataset_snapshot_id": lineage["dataset_snapshot_id"],
                "silver_transactions_version": lineage["silver_transactions_version"],
                "silver_labels_version": lineage["silver_labels_version"],
                "vector_checksum": vectors.checksum,
                "training_dataset_checksum": training_dataset_checksum,
                "code_commit": lineage["code_commit"],
                "lineage_policy_version": lineage["lineage_policy_version"],
                "training_component_fingerprint": lineage["training_component_fingerprint"],
                "repository_dirty": lineage["repository_dirty"],
                "dependency_lock_sha256": lineage["dependency_lock_sha256"],
                "promotion_allowed": "false",
                "purpose": spec.purpose,
                "validation_threshold_policy": threshold_selection.policy,
            }
        )
        dependencies.mlflow.log_params(
            {
                **model_parameters,
                "feature_count": len(spec.feature_names),
                "fixed_fpr": fixed_fpr,
                "train_rows": partitions["train"].num_rows,
                "validation_rows": partitions["validation"].num_rows,
                "test_rows": partitions["test"].num_rows,
            }
        )
        dependencies.mlflow.log_metrics(
            {
                **metrics,
                "validation_threshold": threshold_selection.threshold,
                "training_seconds": training_seconds,
            }
        )
        dependencies.mlflow.log_dict(
            {
                "feature_names": list(spec.feature_names),
                "feature_importance_gain": feature_importance,
                "purpose": spec.purpose,
                "claim_boundary": list(CLAIM_BOUNDARY),
            },
            "feature-set.json",
        )
        dependencies.mlflow_sklearn.log_model(
            sk_model=model,
            name="model",
            input_example=frames["train"].head(5),
            serialization_format="skops",
            skops_trusted_types=list(SKOPS_TRUSTED_LIGHTGBM_TYPES),
            pip_requirements=_model_environment_requirements(),
        )
        child_run_id = child_run.info.run_id

    return ModelTrainingResult(
        experiment_id=spec.experiment_id,
        feature_set=spec.feature_set,
        split_policy="temporal",
        feature_names=spec.feature_names,
        validation_threshold=threshold_selection.threshold,
        validation_threshold_policy=threshold_selection.policy,
        test_pr_auc=metrics["test_pr_auc"],
        test_roc_auc=metrics["test_roc_auc"],
        test_recall_at_fixed_fpr=metrics["test_recall_at_fixed_fpr"],
        test_precision_at_fixed_fpr=metrics["test_precision_at_fixed_fpr"],
        test_observed_fpr=metrics["test_observed_fpr"],
        best_iteration=int(model.best_iteration_ or model_parameters["n_estimators"]),
        training_seconds=training_seconds,
        process_rss_before_bytes=rss_before,
        process_rss_after_bytes=rss_after,
        training_dataset_checksum=training_dataset_checksum,
        feature_importance_gain=feature_importance,
        mlflow_run_id=child_run_id,
        model_uri=f"runs:/{child_run_id}/model",
    )


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


def _require_clean_lineage(
    *,
    code_commit: str,
    lakehouse_commit: str,
    lakehouse_component_dirty: bool | None,
    training_component_dirty: bool,
    allow_dirty: bool,
) -> None:
    if allow_dirty:
        return
    if code_commit == "UNCOMMITTED":
        raise RuntimeError(
            "component-guarded training requires a Git commit for the training implementation"
        )
    legacy_lakehouse_dirty = lakehouse_component_dirty is None and (
        lakehouse_commit == "UNCOMMITTED" or lakehouse_commit.endswith("-dirty")
    )
    if lakehouse_component_dirty is True or legacy_lakehouse_dirty:
        raise RuntimeError(
            "training requires a lakehouse manifest produced from a clean lakehouse component"
        )
    if training_component_dirty:
        raise RuntimeError(
            "training component has uncommitted changes; commit the training/contract/lock "
            "files, then retry. Documentation-only changes do not trigger this guard"
        )


def _atomic_write_manifest(manifest: SilverTrainingManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(
                f"training manifest already exists with different content: {path}"
            )
        return
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(payload, encoding="utf-8")
    temporary_path.replace(path)


def run_paysim_silver_training(
    manifest_path: Path,
    *,
    project_root: Path,
    artifact_root: Path,
    train_nonfraud_sample_per_type: int = DEFAULT_TRAIN_NONFRAUD_PER_TYPE,
    seed: int = DEFAULT_SEED,
    fixed_fpr: float = DEFAULT_FIXED_FPR,
    train_end_step: int = PAYSIM_TRAIN_END_STEP,
    validation_end_step: int = PAYSIM_VALIDATION_END_STEP,
    tracking_uri: str | None = None,
    experiment_name: str = DEFAULT_EXPERIMENT_NAME,
    allow_dirty: bool = False,
) -> tuple[SilverTrainingManifest, Path]:
    """Train locked E1/E4 baselines and publish exact Silver/model lineage."""

    _validate_training_options(
        train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
        seed=seed,
        fixed_fpr=fixed_fpr,
        train_end_step=train_end_step,
        validation_end_step=validation_end_step,
    )
    project_root = project_root.resolve()
    artifact_root = artifact_root.resolve()
    application_manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    code_commit = current_git_commit(project_root)
    training_fingerprint = component_fingerprint(project_root, TRAINING_COMPONENT_PATHS)
    training_component_dirty = component_dirty(project_root, TRAINING_COMPONENT_PATHS)
    worktree_dirty = repository_dirty(project_root)
    _require_clean_lineage(
        code_commit=code_commit,
        lakehouse_commit=application_manifest.code_commit,
        lakehouse_component_dirty=application_manifest.lakehouse_component_dirty,
        training_component_dirty=training_component_dirty,
        allow_dirty=allow_dirty,
    )

    dependencies = _load_training_dependencies()
    vectors, sources = build_silver_training_vectors(
        manifest_path,
        project_root=project_root,
        train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
        seed=seed,
        train_end_step=train_end_step,
        validation_end_step=validation_end_step,
    )
    for partition in vectors.partitions:
        if partition.fraud_rows == 0 or partition.fraud_rows == partition.rows:
            raise RuntimeError(f"{partition.name} partition must contain fraud and non-fraud rows")

    resolved_tracking_uri = tracking_uri or default_tracking_uri(artifact_root)
    resolved_artifact_uri = default_artifact_uri(artifact_root) if tracking_uri is None else None
    configure_mlflow_experiment(
        dependencies.mlflow,
        tracking_uri=resolved_tracking_uri,
        experiment_name=experiment_name,
        artifact_uri=resolved_artifact_uri,
    )

    dependency_lock_sha256 = _sha256_file(project_root / "uv.lock")
    lineage = {
        "dataset_snapshot_id": sources.manifest.dataset_snapshot_id,
        "silver_transactions_version": str(sources.transactions_snapshot.version),
        "silver_labels_version": str(sources.labels_snapshot.version),
        "code_commit": code_commit,
        "lineage_policy_version": LINEAGE_POLICY_VERSION,
        "training_component_fingerprint": training_fingerprint,
        "repository_dirty": str(worktree_dirty).lower(),
        "dependency_lock_sha256": dependency_lock_sha256,
    }
    model_parameters = _model_parameters(seed)
    results: list[ModelTrainingResult] = []
    with dependencies.mlflow.start_run(run_name=SILVER_TRAINING_PIPELINE_VERSION) as parent_run:
        dependencies.mlflow.set_tags(
            {
                "run_type": "silver-training-baseline",
                "dataset_snapshot_id": sources.manifest.dataset_snapshot_id,
                "feature_definition_version": PAYSIM_FEATURE_DEFINITION_VERSION,
                "feature_contract_checksum": paysim_feature_contract_checksum(),
                "model_family": "lightgbm",
                "promotion_allowed": "false",
                "code_commit": code_commit,
                "lineage_policy_version": LINEAGE_POLICY_VERSION,
                "training_component_fingerprint": training_fingerprint,
                "repository_dirty": str(worktree_dirty).lower(),
            }
        )
        dependencies.mlflow.log_params(
            {
                "pipeline_version": SILVER_TRAINING_PIPELINE_VERSION,
                "seed": seed,
                "fixed_fpr": fixed_fpr,
                "train_end_step": train_end_step,
                "validation_end_step": validation_end_step,
                "train_nonfraud_sample_per_type": train_nonfraud_sample_per_type,
                "vector_rows": vectors.table.num_rows,
            }
        )
        dependencies.mlflow.log_dict(
            {
                "application_lakehouse_manifest_path": _portable_path(
                    manifest_path,
                    project_root,
                ),
                "application_lakehouse_code_commit": sources.manifest.code_commit,
                "application_lakehouse_component_fingerprint": (
                    sources.manifest.lakehouse_component_fingerprint
                ),
                "application_lakehouse_component_dirty": (
                    sources.manifest.lakehouse_component_dirty
                ),
                "source_tables": [
                    item.model_dump(mode="json")
                    for item in (
                        sources.transactions_snapshot,
                        sources.labels_snapshot,
                    )
                ],
                "partitions": [item.model_dump(mode="json") for item in vectors.partitions],
                "vector_checksum": vectors.checksum,
                "future_read_violations": vectors.future_read_violations,
                "lineage_policy_version": LINEAGE_POLICY_VERSION,
                "training_component_fingerprint": training_fingerprint,
                "training_component_paths": list(TRAINING_COMPONENT_PATHS),
                "repository_dirty": worktree_dirty,
            },
            "silver-lineage.json",
        )
        for spec in LOCKED_EXPERIMENTS:
            results.append(
                _train_experiment(
                    vectors,
                    spec,
                    lineage=lineage,
                    seed=seed,
                    fixed_fpr=fixed_fpr,
                    dependencies=dependencies,
                )
            )

        parent_run_id = parent_run.info.run_id
        manifest = SilverTrainingManifest(
            status="completed",
            pipeline_version=SILVER_TRAINING_PIPELINE_VERSION,
            run_id=parent_run_id,
            created_at=datetime.now(UTC),
            application_lakehouse_manifest_path=_portable_path(
                manifest_path,
                project_root,
            ),
            application_lakehouse_code_commit=sources.manifest.code_commit,
            application_lakehouse_component_fingerprint=(
                sources.manifest.lakehouse_component_fingerprint
            ),
            application_lakehouse_component_dirty=(sources.manifest.lakehouse_component_dirty),
            dataset_snapshot_id=sources.manifest.dataset_snapshot_id,
            raw_file_sha256=sources.manifest.raw_file_sha256,
            entity_definition_version=sources.manifest.entity_definition_version,
            feature_definition_version=sources.manifest.feature_definition_version,
            feature_contract_checksum=sources.manifest.feature_contract_checksum,
            source_tables=(
                sources.transactions_snapshot,
                sources.labels_snapshot,
            ),
            train_end_step=train_end_step,
            validation_end_step=validation_end_step,
            train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
            training_sampling_policy=TRAINING_SAMPLING_POLICY,
            vector_rows=vectors.table.num_rows,
            vector_fraud_rows=int(pc.sum(vectors.table["target_label"]).as_py()),
            vector_checksum=vectors.checksum,
            future_read_violations=vectors.future_read_violations,
            partitions=vectors.partitions,
            model_family="lightgbm",
            model_parameters=model_parameters,
            seed=seed,
            fixed_fpr=fixed_fpr,
            code_commit=code_commit,
            lineage_policy_version=LINEAGE_POLICY_VERSION,
            training_component_fingerprint=training_fingerprint,
            training_component_paths=TRAINING_COMPONENT_PATHS,
            training_component_dirty=training_component_dirty,
            repository_dirty=worktree_dirty,
            dependency_lock_sha256=dependency_lock_sha256,
            dependency_versions={
                package: _package_version(package)
                for package in (
                    "deltalake",
                    "duckdb",
                    "lightgbm",
                    "mlflow",
                    "numpy",
                    "pandas",
                    "pyarrow",
                    "scikit-learn",
                    "skops",
                )
            },
            mlflow_tracking_uri=dependencies.mlflow.get_tracking_uri(),
            mlflow_parent_run_id=parent_run_id,
            claim_boundary=CLAIM_BOUNDARY,
            experiments=tuple(results),
        )
        dependencies.mlflow.log_dict(
            manifest.model_dump(mode="json"),
            "silver-training-manifest.json",
        )

    output_path = (
        artifact_root / "experiments" / "paysim-silver-training" / parent_run_id / "manifest.json"
    )
    _atomic_write_manifest(manifest, output_path)
    return manifest, output_path


def find_latest_training_manifest(artifact_root: Path) -> Path | None:
    root = artifact_root.resolve() / "experiments" / "paysim-silver-training"
    candidates = tuple(root.glob("*/manifest.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def load_training_manifest(path: Path) -> SilverTrainingManifest:
    return SilverTrainingManifest.model_validate_json(path.read_text(encoding="utf-8"))


def manifest_summary_rows(manifest: SilverTrainingManifest) -> list[dict[str, Any]]:
    return [
        {
            "experiment": result.experiment_id,
            "features": result.feature_set,
            "test_pr_auc": round(result.test_pr_auc, 6),
            "test_roc_auc": round(result.test_roc_auc, 6),
            "recall_at_fixed_fpr": round(result.test_recall_at_fixed_fpr, 6),
            "precision_at_fixed_fpr": round(result.test_precision_at_fixed_fpr, 6),
            "observed_fpr": round(result.test_observed_fpr, 6),
            "threshold": round(result.validation_threshold, 8),
            "threshold_policy": result.validation_threshold_policy,
            "best_iteration": result.best_iteration,
            "seconds": round(result.training_seconds, 3),
            "mlflow_run_id": result.mlflow_run_id,
        }
        for result in manifest.experiments
    ]


def feature_importance_rows(
    manifest: SilverTrainingManifest,
    *,
    experiment_id: Literal["E1", "E4"] = "E4",
) -> list[dict[str, Any]]:
    result = next(item for item in manifest.experiments if item.experiment_id == experiment_id)
    total_gain = sum(result.feature_importance_gain.values())
    rows = [
        {
            "feature": feature,
            "gain": round(gain, 6),
            "gain_share": round(gain / total_gain, 6) if total_gain > 0 else 0.0,
        }
        for feature, gain in result.feature_importance_gain.items()
    ]
    return sorted(rows, key=lambda item: (-item["gain"], item["feature"]))
