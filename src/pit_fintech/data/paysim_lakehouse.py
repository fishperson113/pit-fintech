"""Versioned PaySim Bronze/Silver Delta application path."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import psutil
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from pit_fintech.contracts.manifests import (
    ApplicationLakehouseManifest,
    DataQualityGateResult,
    DeltaTableSnapshot,
    LakehouseBuildResources,
)
from pit_fintech.data.paysim import (
    connect_paysim,
    create_paysim_snapshot,
    sha256_file,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY_DEFINITION_VERSION,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    paysim_feature_contract_checksum,
)

PAYSIM_LAKEHOUSE_PIPELINE_VERSION: Final = "paysim-bronze-silver-v1"
PAYSIM_ARROW_BATCH_SIZE: Final = 65_536
PAYSIM_TARGET_FILE_SIZE: Final = 128 * 1024 * 1024
PAYSIM_TRANSACTION_TYPES: Final = (
    "CASH_IN",
    "CASH_OUT",
    "DEBIT",
    "PAYMENT",
    "TRANSFER",
)

PAYSIM_BRONZE_COLUMNS: Final = (
    "source_row_number",
    "step",
    "type",
    "amount",
    "nameOrig",
    "oldbalanceOrg",
    "newbalanceOrig",
    "nameDest",
    "oldbalanceDest",
    "newbalanceDest",
    "isFraud",
    "isFlaggedFraud",
    "dataset_snapshot_id",
    "source_file_sha256",
    "source_record_id",
    "event_day",
)
PAYSIM_SILVER_TRANSACTION_COLUMNS: Final = (
    "source_row_number",
    "step",
    "transaction_type",
    "amount",
    "origin_entity_id",
    "origin_entity_kind",
    "destination_entity_id",
    "destination_entity_kind",
    "dataset_snapshot_id",
    "source_file_sha256",
    "source_record_id",
    "event_day",
)
PAYSIM_SILVER_LABEL_COLUMNS: Final = (
    "source_row_number",
    "step",
    "isFraud",
    "dataset_snapshot_id",
    "source_file_sha256",
    "source_record_id",
    "event_day",
)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _portable_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _resolve_manifest_path(path: str, project_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root / candidate


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


def arrow_schema_checksum(schema: pa.Schema) -> str:
    fields = [
        {"name": item.name, "nullable": item.nullable, "type": str(item.type)} for item in schema
    ]
    canonical = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _arrow_schema_signature(schema: pa.Schema) -> tuple[tuple[str, str], ...]:
    return tuple((item.name, str(item.type)) for item in schema)


def _serialized_batch(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


@dataclass
class _ArrowStreamEvidence:
    """Deterministic evidence collected while the writer consumes ordered batches."""

    rows: int = 0
    digest: Any = field(default_factory=hashlib.sha256)

    def track(self, batches: Iterable[pa.RecordBatch]) -> Iterator[pa.RecordBatch]:
        for batch in batches:
            payload = _serialized_batch(batch)
            self.rows += batch.num_rows
            self.digest.update(batch.num_rows.to_bytes(8, byteorder="big", signed=False))
            self.digest.update(len(payload).to_bytes(8, byteorder="big", signed=False))
            self.digest.update(payload)
            yield batch

    @property
    def logical_checksum(self) -> str:
        return self.digest.hexdigest()


def _event_day_sql() -> str:
    return "(floor((step - 1) / 24.0)::INTEGER + 1)"


def _source_record_id_sql(dataset_snapshot_id: str) -> str:
    return f"concat({_sql_string(dataset_snapshot_id)}, ':', source_row_number::VARCHAR)"


def _bronze_query(dataset_snapshot_id: str, raw_file_sha256: str) -> str:
    return f"""
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            type::VARCHAR AS type,
            amount::DOUBLE AS amount,
            nameOrig::VARCHAR AS nameOrig,
            oldbalanceOrg::DOUBLE AS oldbalanceOrg,
            newbalanceOrig::DOUBLE AS newbalanceOrig,
            nameDest::VARCHAR AS nameDest,
            oldbalanceDest::DOUBLE AS oldbalanceDest,
            newbalanceDest::DOUBLE AS newbalanceDest,
            isFraud::TINYINT AS isFraud,
            isFlaggedFraud::TINYINT AS isFlaggedFraud,
            {_sql_string(dataset_snapshot_id)}::VARCHAR AS dataset_snapshot_id,
            {_sql_string(raw_file_sha256)}::VARCHAR AS source_file_sha256,
            {_source_record_id_sql(dataset_snapshot_id)}::VARCHAR AS source_record_id,
            {_event_day_sql()} AS event_day
        FROM paysim
        ORDER BY source_row_number
    """


def _silver_transactions_query(dataset_snapshot_id: str, raw_file_sha256: str) -> str:
    return f"""
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            upper(type)::VARCHAR AS transaction_type,
            amount::DOUBLE AS amount,
            nameOrig::VARCHAR AS origin_entity_id,
            CASE
                WHEN starts_with(nameOrig, 'C') THEN 'CUSTOMER'
                ELSE 'UNKNOWN'
            END::VARCHAR AS origin_entity_kind,
            nameDest::VARCHAR AS destination_entity_id,
            CASE
                WHEN starts_with(nameDest, 'C') THEN 'CUSTOMER'
                WHEN starts_with(nameDest, 'M') THEN 'MERCHANT'
                ELSE 'UNKNOWN'
            END::VARCHAR AS destination_entity_kind,
            {_sql_string(dataset_snapshot_id)}::VARCHAR AS dataset_snapshot_id,
            {_sql_string(raw_file_sha256)}::VARCHAR AS source_file_sha256,
            {_source_record_id_sql(dataset_snapshot_id)}::VARCHAR AS source_record_id,
            {_event_day_sql()} AS event_day
        FROM paysim
        ORDER BY source_row_number
    """


def _silver_labels_query(dataset_snapshot_id: str, raw_file_sha256: str) -> str:
    return f"""
        SELECT
            source_row_number::BIGINT AS source_row_number,
            step::BIGINT AS step,
            isFraud::TINYINT AS isFraud,
            {_sql_string(dataset_snapshot_id)}::VARCHAR AS dataset_snapshot_id,
            {_sql_string(raw_file_sha256)}::VARCHAR AS source_file_sha256,
            {_source_record_id_sql(dataset_snapshot_id)}::VARCHAR AS source_record_id,
            {_event_day_sql()} AS event_day
        FROM paysim
        ORDER BY source_row_number
    """


def _validate_projected_schema(actual: tuple[str, ...], expected: tuple[str, ...]) -> None:
    if actual != expected:
        raise ValueError(f"projected schema mismatch: expected {expected}, received {actual}")


def _quality_gates(
    connection: Any,
    *,
    expected_source_rows: int,
) -> tuple[DataQualityGateResult, ...]:
    allowed_types = ", ".join(_sql_string(value) for value in PAYSIM_TRANSACTION_TYPES)
    result = connection.execute(
        f"""
        SELECT
            count(*)::BIGINT AS source_rows,
            (
                count(*) - count(DISTINCT source_row_number)
            )::BIGINT AS duplicate_source_row_numbers,
            count(*) FILTER (
                WHERE step IS NULL OR step < 1
            )::BIGINT AS invalid_step_rows,
            count(*) FILTER (
                WHERE type IS NULL OR upper(type) NOT IN ({allowed_types})
            )::BIGINT AS invalid_type_rows,
            count(*) FILTER (
                WHERE amount IS NULL OR NOT isfinite(amount) OR amount < 0
            )::BIGINT AS invalid_amount_rows,
            count(*) FILTER (
                WHERE nameOrig IS NULL
                   OR trim(nameOrig) = ''
                   OR NOT starts_with(nameOrig, 'C')
                   OR nameDest IS NULL
                   OR trim(nameDest) = ''
                   OR (
                       NOT starts_with(nameDest, 'C')
                       AND NOT starts_with(nameDest, 'M')
                   )
            )::BIGINT AS invalid_entity_rows,
            count(*) FILTER (
                WHERE isFraud IS NULL OR isFraud NOT IN (0, 1)
            )::BIGINT AS invalid_label_rows,
            count(*) FILTER (
                WHERE isFlaggedFraud IS NULL OR isFlaggedFraud NOT IN (0, 1)
            )::BIGINT AS invalid_policy_rows
        FROM paysim
        """
    ).fetchone()
    if result is None:  # pragma: no cover - aggregate always returns one row
        raise RuntimeError("PaySim quality query returned no result")

    names = (
        "source_rows_match_snapshot",
        "duplicate_source_row_numbers",
        "invalid_step_rows",
        "invalid_type_rows",
        "invalid_amount_rows",
        "invalid_entity_rows",
        "invalid_label_rows",
        "invalid_policy_rows",
    )
    observed = tuple(int(value) for value in result)
    expected = (expected_source_rows, 0, 0, 0, 0, 0, 0, 0)
    failures = {
        name: {"observed": actual, "expected": wanted}
        for name, actual, wanted in zip(names, observed, expected, strict=True)
        if actual != wanted
    }
    if failures:
        raise ValueError(
            "PaySim publish-blocking quality gates failed: " + json.dumps(failures, sort_keys=True)
        )
    return tuple(
        DataQualityGateResult(
            name=name,
            status="pass",
            observed=actual,
            expected=wanted,
        )
        for name, actual, wanted in zip(names, observed, expected, strict=True)
    )


def _write_query_to_delta(
    connection: Any,
    query: str,
    path: Path,
    *,
    layer: str,
    table_name: str,
    expected_columns: tuple[str, ...],
    manifest_path: str,
    batch_size: int,
) -> DeltaTableSnapshot:
    source_reader = connection.execute(query).to_arrow_reader(batch_size)
    _validate_projected_schema(tuple(source_reader.schema.names), expected_columns)
    input_schema_checksum = arrow_schema_checksum(source_reader.schema)
    input_schema_signature = _arrow_schema_signature(source_reader.schema)
    evidence = _ArrowStreamEvidence()
    tracked_reader = pa.RecordBatchReader.from_batches(
        source_reader.schema,
        evidence.track(source_reader),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "overwrite" if (path / "_delta_log").exists() else "error"
    write_deltalake(
        path,
        tracked_reader,
        mode=mode,
        partition_by=["event_day"],
        schema_mode="overwrite" if mode == "overwrite" else None,
        target_file_size=PAYSIM_TARGET_FILE_SIZE,
        name=f"pit_{layer}_{table_name}",
        description=(
            "PaySim application data; event_day is a synthetic simulator layout partition"
        ),
    )
    if evidence.rows == 0:
        raise ValueError(f"refusing to publish empty Delta table: {layer}.{table_name}")

    delta_table = DeltaTable(path)
    output_dataset = delta_table.to_pyarrow_dataset()
    output_rows = int(output_dataset.count_rows())
    _validate_projected_schema(tuple(output_dataset.schema.names), expected_columns)
    output_schema_checksum = arrow_schema_checksum(output_dataset.schema)
    if output_rows != evidence.rows:
        raise RuntimeError(
            f"Delta row-count mismatch for {layer}.{table_name}: {output_rows} != {evidence.rows}"
        )
    if _arrow_schema_signature(output_dataset.schema) != input_schema_signature:
        raise RuntimeError(
            f"Delta schema mismatch for {layer}.{table_name}: "
            f"{output_schema_checksum} != {input_schema_checksum}"
        )

    return DeltaTableSnapshot(
        layer=layer,
        table=table_name,
        path=manifest_path,
        version=delta_table.version(),
        rows=output_rows,
        schema_checksum=output_schema_checksum,
        logical_checksum=evidence.logical_checksum,
    )


def _write_json_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(payload, encoding="utf-8")
    temporary_path.replace(path)


def _publish_manifest(
    manifest: ApplicationLakehouseManifest,
    *,
    artifact_root: Path,
) -> Path:
    snapshot_prefix = manifest.raw_file_sha256[:16]
    lakehouse_artifact_root = (
        artifact_root.resolve() / "datasets" / "paysim1" / snapshot_prefix / "lakehouse"
    )
    version_key = "-".join(
        f"{snapshot.layer}-{snapshot.table}-v{snapshot.version}" for snapshot in manifest.tables
    )
    immutable_path = lakehouse_artifact_root / "manifests" / f"{version_key}.json"
    latest_path = lakehouse_artifact_root / "lakehouse-manifest.json"
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    if immutable_path.exists():
        existing = immutable_path.read_text(encoding="utf-8")
        if existing != payload:
            raise FileExistsError(
                f"immutable lakehouse manifest already exists with different content: "
                f"{immutable_path}"
            )
    else:
        _write_json_atomic(immutable_path, payload)
    _write_json_atomic(latest_path, payload)
    return latest_path


def build_paysim_lakehouse(
    csv_path: Path,
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    batch_size: int = PAYSIM_ARROW_BATCH_SIZE,
) -> tuple[ApplicationLakehouseManifest, Path]:
    """Build and publish exact PaySim Bronze/Silver Delta versions."""

    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    started_at = time.perf_counter()
    process = psutil.Process()
    process_rss_before_bytes = process.memory_info().rss
    project_root = project_root.resolve()
    data_root = data_root.resolve()
    artifact_root = artifact_root.resolve()
    source_manifest, source_manifest_path = create_paysim_snapshot(
        csv_path,
        project_root=project_root,
        artifact_root=artifact_root,
    )
    snapshot_prefix = source_manifest.file.sha256[:16]
    lakehouse_root = data_root / "lakehouse" / "paysim1" / snapshot_prefix

    connection = connect_paysim(csv_path)
    try:
        quality_gates = _quality_gates(
            connection,
            expected_source_rows=source_manifest.source_rows,
        )
        table_definitions = (
            (
                "bronze",
                "paysim_transactions",
                _bronze_query(
                    source_manifest.dataset_snapshot_id,
                    source_manifest.file.sha256,
                ),
                PAYSIM_BRONZE_COLUMNS,
            ),
            (
                "silver",
                "paysim_transactions",
                _silver_transactions_query(
                    source_manifest.dataset_snapshot_id,
                    source_manifest.file.sha256,
                ),
                PAYSIM_SILVER_TRANSACTION_COLUMNS,
            ),
            (
                "silver",
                "paysim_labels",
                _silver_labels_query(
                    source_manifest.dataset_snapshot_id,
                    source_manifest.file.sha256,
                ),
                PAYSIM_SILVER_LABEL_COLUMNS,
            ),
        )
        snapshots = tuple(
            _write_query_to_delta(
                connection,
                query,
                lakehouse_root / layer / table_name,
                layer=layer,
                table_name=table_name,
                expected_columns=expected_columns,
                manifest_path=_portable_path(
                    lakehouse_root / layer / table_name,
                    project_root,
                ),
                batch_size=batch_size,
            )
            for layer, table_name, query, expected_columns in table_definitions
        )
    finally:
        connection.close()

    if any(
        forbidden in PAYSIM_SILVER_TRANSACTION_COLUMNS
        for forbidden in PAYSIM_FORBIDDEN_MODEL_INPUTS
    ):
        raise RuntimeError("forbidden model input leaked into Silver transaction schema")
    expected_rows = source_manifest.source_rows
    if any(snapshot.rows != expected_rows for snapshot in snapshots):
        raise RuntimeError("published PaySim table row counts diverge from the raw snapshot")
    final_size = csv_path.stat().st_size
    final_sha256 = sha256_file(csv_path)
    if final_size != source_manifest.file.bytes or final_sha256 != source_manifest.file.sha256:
        raise RuntimeError(
            "PaySim raw file changed during the lakehouse build; "
            "no application manifest was published"
        )

    wall_seconds = time.perf_counter() - started_at
    delta_parquet_bytes = sum(
        Path(file_uri).stat().st_size
        for snapshot in snapshots
        for file_uri in DeltaTable(_resolve_manifest_path(snapshot.path, project_root)).file_uris()
    )
    event_day_partitions = len(
        {
            path.name
            for path in (lakehouse_root / "bronze" / "paysim_transactions").glob("event_day=*")
            if path.is_dir()
        }
    )
    manifest = ApplicationLakehouseManifest(
        status="completed",
        pipeline_version=PAYSIM_LAKEHOUSE_PIPELINE_VERSION,
        dataset="paysim1",
        dataset_snapshot_id=source_manifest.dataset_snapshot_id,
        source_manifest_path=_portable_path(source_manifest_path, project_root),
        raw_file_sha256=source_manifest.file.sha256,
        source_rows=source_manifest.source_rows,
        entity_definition_version=PAYSIM_ENTITY_DEFINITION_VERSION,
        feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
        feature_contract_checksum=paysim_feature_contract_checksum(),
        code_commit=_current_commit(project_root),
        resources=LakehouseBuildResources(
            wall_seconds=wall_seconds,
            raw_bytes=source_manifest.file.bytes,
            delta_parquet_bytes=delta_parquet_bytes,
            rows_per_second=source_manifest.source_rows / wall_seconds,
            process_rss_before_bytes=process_rss_before_bytes,
            process_rss_after_bytes=process.memory_info().rss,
            event_day_partitions=event_day_partitions,
            arrow_batch_size=batch_size,
            target_file_size_bytes=PAYSIM_TARGET_FILE_SIZE,
        ),
        quality_gates=quality_gates,
        tables=snapshots,
    )
    manifest_path = _publish_manifest(manifest, artifact_root=artifact_root)
    return manifest, manifest_path


def find_latest_paysim_lakehouse_manifest(artifact_root: Path) -> Path | None:
    candidates = list(
        artifact_root.resolve().glob("datasets/paysim1/*/lakehouse/lakehouse-manifest.json")
    )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None


def paysim_lakehouse_history(
    manifest_path: Path,
    *,
    project_root: Path,
) -> list[dict[str, Any]]:
    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    histories: list[dict[str, Any]] = []
    for snapshot in manifest.tables:
        table_path = _resolve_manifest_path(snapshot.path, project_root)
        for commit in DeltaTable(table_path).history():
            histories.append(
                {
                    "layer": snapshot.layer,
                    "table": snapshot.table,
                    **commit,
                }
            )
    return histories
