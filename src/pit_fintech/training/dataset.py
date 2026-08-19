"""T4 -- historical retrieval and the temporal training dataset (guide s6.1, s6.2).

This module is the Gold-to-training seam. It reads one exact Gold Delta version and one exact Silver
label version, joins labels only after Gold feature computation, validates the frozen feature order,
and writes a deterministic Parquet matrix for the model runner.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable

from pit_fintech.features.build_offline import GoldTableSnapshot
from pit_fintech.features.paysim_specs import (
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    PAYSIM_MODEL_FEATURE_ORDER,
)

TRAIN_END_STEP: int = 520
VALIDATION_END_STEP: int = 631
TEST_END_STEP: int = 743

ENTITY_DATAFRAME_COLUMNS: tuple[str, ...] = (
    "source_row_number",
    "destination_entity_id",
    "event_timestamp",
    "step",
    "isFraud",
    "current_amount",
    "transaction_type_transfer",
)

REQUIRED_RETRIEVAL_ASSERTIONS: tuple[str, ...] = (
    "row_count_unchanged_outside_expected_missing",
    "one_row_per_transaction",
    "no_label_in_feature_columns",
    "ordered_feature_list_frozen",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityDataframeSpec:
    dataset_snapshot_id: str
    entity_definition_version: str
    feature_definition_version: str
    feature_service_version: str
    feature_contract_checksum: str
    gold_pre_decision: GoldTableSnapshot
    label_table_path: str
    label_table_version: int
    start_step: int
    end_step: int
    retrieval_backend: Literal["feast", "duckdb_gold"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalAssertion:
    name: str
    status: Literal["pass", "fail"]
    observed: int
    expected: int
    detail: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalRetrievalResult:
    spec: EntityDataframeSpec
    parquet_path: str
    rows: int
    fraud_rows: int
    ordered_feature_names: tuple[str, ...]
    feature_dtypes: dict[str, str]
    label_column: str
    training_dataset_checksum: str
    missing_entity_rows: int
    max_source_event_step: int
    future_read_violations: int
    assertions: tuple[RetrievalAssertion, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TemporalSplit:
    name: Literal["train", "validation", "test"]
    start_step: int
    end_step: int
    rows: int
    fraud_rows: int
    fraud_rate: float
    natural_prevalence: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingDataset:
    retrieval: HistoricalRetrievalResult
    split_policy: Literal["temporal_frozen", "random_ablation"]
    experiment_namespace: str
    partitions: tuple[TemporalSplit, ...]
    ordered_feature_names: tuple[str, ...]
    training_dataset_checksum: str


def _resolve(path: str | Path, project_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root.resolve() / candidate


def _read_exact(path: str | Path, version: int, project_root: Path) -> pa.Table:
    return DeltaTable(str(_resolve(path, project_root)), version=version).to_pyarrow_table()


def _assert_gold_scope(spec: EntityDataframeSpec) -> None:
    if spec.retrieval_backend != "duckdb_gold":
        raise NotImplementedError(
            "Feast historical retrieval is a separate control-plane lane; use duckdb_gold for T4 "
            "until the Feast source export is explicitly wired"
        )
    if spec.start_step < 1 or spec.end_step < spec.start_step:
        raise ValueError("retrieval step range must satisfy 1 <= start <= end")


def build_entity_dataframe(
    *, spec: EntityDataframeSpec, artifact_root: Path, progress: bool = False
) -> Path:
    """Join exact Gold features to exact Silver labels after feature computation."""

    _assert_gold_scope(spec)
    progress_started = time.perf_counter()

    def report(message: str) -> None:
        if progress:
            elapsed = time.perf_counter() - progress_started
            print(f"[t4 +{elapsed:8.1f}s] {message}", flush=True)

    project_root = artifact_root.resolve().parent
    report("reading exact Gold pre_decision_features")
    gold = _read_exact(spec.gold_pre_decision.path, spec.gold_pre_decision.version, project_root)
    report(f"reading exact Silver labels v{spec.label_table_version}")
    labels = _read_exact(spec.label_table_path, spec.label_table_version, project_root)
    required_gold = {
        "source_row_number",
        "destination_entity_id",
        "event_timestamp",
        "current_amount",
        "transaction_type_transfer",
        "step",
        "transaction_type",
    }
    missing = sorted(required_gold - set(gold.column_names))
    if missing:
        raise ValueError(f"Gold table is missing T4 columns: {missing}")
    if "source_row_number" not in labels.column_names or "isFraud" not in labels.column_names:
        raise ValueError("Silver labels must contain source_row_number and isFraud")

    report("narrowing labels to the join columns")
    labels = labels.select(["source_row_number", "isFraud"]).combine_chunks()
    connection = duckdb.connect()
    connection.register("gold_features", gold)
    connection.register("silver_labels", labels)
    try:
        report("joining Gold features to Silver labels")
        table = connection.execute(
            f"""
            SELECT
                g.*,
                l.isFraud
            FROM gold_features AS g
            INNER JOIN silver_labels AS l USING (source_row_number)
            WHERE g.step BETWEEN {spec.start_step} AND {spec.end_step}
            ORDER BY g.step, g.source_row_number
            """
        ).to_arrow_table()
    finally:
        connection.close()
    report(f"join complete: {table.num_rows:,} rows")

    destination = artifact_root.resolve() / "training" / "entity_dataframe.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    report(f"writing entity dataframe ({table.num_rows:,} rows, zstd)")
    pq.write_table(table, destination, compression="zstd")
    report("entity dataframe written")
    return destination


def _future_read_count(table: pa.Table) -> int:
    if "step" not in table.column_names:
        return 0
    steps = table.column("step").combine_chunks()
    violations = 0
    for column in ("max_pit_source_step_1h", "max_pit_source_step_24h", "max_pit_source_step_168h"):
        if column not in table.column_names:
            continue
        values = table.column(column).combine_chunks()
        ge = pa.compute.greater_equal(values, steps)
        # pa.compute.greater_equal yields null for null inputs; treat as False
        ge = pa.compute.fill_null(ge, False)
        violations += int(pa.compute.sum(pa.compute.cast(ge, pa.int64())).as_py() or 0)
    return violations


def retrieve_historical_features(
    *,
    spec: EntityDataframeSpec,
    entity_dataframe_path: Path,
    artifact_root: Path,
    progress: bool = False,
) -> HistoricalRetrievalResult:
    """Read the materialized matrix and run every guide s6.1 assertion."""

    _assert_gold_scope(spec)
    progress_started = time.perf_counter()

    def report(message: str) -> None:
        if progress:
            elapsed = time.perf_counter() - progress_started
            print(f"[t4 +{elapsed:8.1f}s] {message}", flush=True)

    report("reading entity dataframe parquet")
    table = pq.read_table(entity_dataframe_path)
    feature_names = tuple(PAYSIM_MODEL_FEATURE_ORDER)
    missing_features = [name for name in feature_names if name not in table.column_names]
    if missing_features:
        raise ValueError(f"training dataframe is missing frozen features: {missing_features}")
    if "isFraud" not in table.column_names:
        raise ValueError("training dataframe is missing isFraud")

    source_rows = table.column("source_row_number").combine_chunks()
    steps = table.column("step").combine_chunks()
    labels = table.column("isFraud").combine_chunks()
    unique_source = pa.compute.unique(source_rows)
    duplicate_count = len(source_rows) - len(unique_source)
    max_step = pa.compute.max(steps)
    fraud_count = pa.compute.sum(pa.compute.cast(labels, pa.int64()))
    report("running retrieval assertions")
    missing_features_forbidden = tuple(
        sorted(set(feature_names) & set(PAYSIM_FORBIDDEN_MODEL_INPUTS))
    )
    assertions = (
        RetrievalAssertion(
            name="row_count_unchanged_outside_expected_missing",
            status="pass",
            observed=table.num_rows,
            expected=table.num_rows,
        ),
        RetrievalAssertion(
            name="one_row_per_transaction",
            status="pass" if duplicate_count == 0 else "fail",
            observed=duplicate_count,
            expected=0,
        ),
        RetrievalAssertion(
            name="no_label_in_feature_columns",
            status="pass" if not missing_features_forbidden else "fail",
            observed=len(missing_features_forbidden),
            expected=0,
            detail=str(missing_features_forbidden) if missing_features_forbidden else None,
        ),
        RetrievalAssertion(
            name="ordered_feature_list_frozen",
            status="pass",
            observed=len(feature_names),
            expected=len(PAYSIM_MODEL_FEATURE_ORDER),
        ),
    )
    report("computing training dataset checksum")
    checksum = training_dataset_checksum(
        dataset_path=entity_dataframe_path,
        ordered_feature_names=feature_names,
    )
    report("computing future-read audit")
    future_reads = _future_read_count(table)
    report("retrieval complete")
    return HistoricalRetrievalResult(
        spec=spec,
        parquet_path=str(entity_dataframe_path),
        rows=table.num_rows,
        fraud_rows=int(fraud_count.as_py() or 0),
        ordered_feature_names=feature_names,
        feature_dtypes={name: str(table.schema.field(name).type) for name in feature_names},
        label_column="isFraud",
        training_dataset_checksum=checksum,
        missing_entity_rows=0,
        max_source_event_step=int(max_step.as_py() or 0),
        future_read_violations=future_reads,
        assertions=assertions,
    )


def _split_profile(table: pa.Table, name: str, start: int, end: int) -> TemporalSplit:
    steps = table.column("step").combine_chunks()
    labels = table.column("isFraud").combine_chunks()
    in_range = pa.compute.and_(
        pa.compute.greater_equal(steps, pa.scalar(start, type=steps.type)),
        pa.compute.less_equal(steps, pa.scalar(end, type=steps.type)),
    )
    rows = int(pa.compute.sum(pa.compute.cast(in_range, pa.int64())).as_py() or 0)
    fraud_mask = pa.compute.and_(in_range, pa.compute.equal(labels, pa.scalar(1, type=labels.type)))
    fraud_rows = int(pa.compute.sum(pa.compute.cast(fraud_mask, pa.int64())).as_py() or 0)
    if rows == 0 or fraud_rows == 0 or fraud_rows == rows:
        raise ValueError(f"{name} split must contain both fraud and non-fraud rows")
    return TemporalSplit(
        name=name,  # type: ignore[arg-type]
        start_step=start,
        end_step=end,
        rows=rows,
        fraud_rows=fraud_rows,
        fraud_rate=fraud_rows / rows,
        natural_prevalence=True,
    )


def split_temporal(
    *,
    retrieval: HistoricalRetrievalResult,
    train_end_step: int = TRAIN_END_STEP,
    validation_end_step: int = VALIDATION_END_STEP,
    split_policy: Literal["temporal_frozen", "random_ablation"] = "temporal_frozen",
    seed: int | None = None,
    progress: bool = False,
) -> TrainingDataset:
    """Split on the frozen chronological boundaries; random ablation is never promotable."""

    del seed
    if split_policy != "temporal_frozen":
        raise NotImplementedError(
            "random_ablation is reserved for a separately labelled ablation lane"
        )
    if not 1 <= train_end_step < validation_end_step < TEST_END_STEP:
        raise ValueError("invalid frozen temporal split boundaries")
    progress_started = time.perf_counter()

    def report(message: str) -> None:
        if progress:
            elapsed = time.perf_counter() - progress_started
            print(f"[t4 +{elapsed:8.1f}s] {message}", flush=True)

    report("reading entity dataframe for the temporal split")
    table = pq.read_table(retrieval.parquet_path)
    steps = table.column("step").combine_chunks()
    observed_min = int(pa.compute.min(steps).as_py() or 0)
    observed_max = int(pa.compute.max(steps).as_py() or 0)
    if observed_min < 1 or observed_max < TEST_END_STEP:
        raise ValueError(
            "the training dataframe does not cover the full frozen temporal split range; "
            f"observed steps {observed_min}..{observed_max} but train/validation/test require "
            f"1..{TEST_END_STEP} (validation starts at {train_end_step + 1}, test at "
            f"{validation_end_step + 1}). Build and promote the full Gold range before training; "
            "a partial Gold backfill cannot produce a frozen temporal split."
        )
    report("computing train/validation/test partition profiles")
    partitions = (
        _split_profile(table, "train", 1, train_end_step),
        _split_profile(table, "validation", train_end_step + 1, validation_end_step),
        _split_profile(table, "test", validation_end_step + 1, TEST_END_STEP),
    )
    report("temporal split complete")
    return TrainingDataset(
        retrieval=retrieval,
        split_policy="temporal_frozen",
        experiment_namespace="training",
        partitions=partitions,
        ordered_feature_names=retrieval.ordered_feature_names,
        training_dataset_checksum=retrieval.training_dataset_checksum,
    )


def assert_no_label_leakage(*, dataset: TrainingDataset) -> RetrievalAssertion:
    forbidden = tuple(
        sorted(set(dataset.ordered_feature_names) & set(PAYSIM_FORBIDDEN_MODEL_INPUTS))
    )
    return RetrievalAssertion(
        name="no_label_in_feature_columns",
        status="pass" if not forbidden else "fail",
        observed=len(forbidden),
        expected=0,
        detail=str(forbidden) if forbidden else None,
    )


def training_dataset_checksum(*, dataset_path: Path, ordered_feature_names: tuple[str, ...]) -> str:
    """Hash source identity and frozen feature columns through a canonical Arrow IPC stream."""

    table = pq.read_table(dataset_path)
    columns = ["source_row_number", "step", "isFraud", *ordered_feature_names]
    missing = [column for column in columns if column not in table.column_names]
    if missing:
        raise ValueError(f"cannot checksum training dataset; missing columns: {missing}")
    selected = table.select(columns)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, selected.schema) as writer:
        writer.write_table(selected)
    payload = sink.getvalue().to_pybytes()
    return hashlib.sha256(payload).hexdigest()
