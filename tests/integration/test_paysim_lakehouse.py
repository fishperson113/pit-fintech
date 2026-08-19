from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from deltalake import DeltaTable

from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim import DEFAULT_FILENAME
from pit_fintech.data.paysim_lakehouse import (
    PAYSIM_BRONZE_COLUMNS,
    PAYSIM_LAKEHOUSE_PIPELINE_VERSION,
    PAYSIM_SILVER_LABEL_COLUMNS,
    PAYSIM_SILVER_TRANSACTION_COLUMNS,
    build_paysim_lakehouse,
    find_latest_paysim_lakehouse_manifest,
    paysim_lakehouse_history,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY_DEFINITION_VERSION,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SOURCE,
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    PAYSIM_LABEL_SOURCE,
    PAYSIM_RECENCY_SENTINEL_STEPS,
    paysim_feature_contract_checksum,
)
from pit_fintech.models.paysim_training import (
    TRAINING_VECTOR_COLUMNS,
    build_silver_training_vectors,
)

pytestmark = pytest.mark.integration
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "paysim_schema_sample.csv"


def _copy_fixture(project_root: Path) -> Path:
    csv_path = project_root / "data" / "raw" / "paysim" / DEFAULT_FILENAME
    csv_path.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_PATH, csv_path)
    return csv_path


def _snapshot(manifest: ApplicationLakehouseManifest, layer: str, table: str):
    return next(item for item in manifest.tables if item.layer == layer and item.table == table)


def _table_path(project_root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root / candidate


def test_paysim_delta_build_is_versioned_contract_safe_and_time_travelable(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _copy_fixture(project_root)
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"

    first, first_manifest_path = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )
    second, second_manifest_path = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )

    assert first.status == "completed"
    assert first.pipeline_version == PAYSIM_LAKEHOUSE_PIPELINE_VERSION
    assert first.dataset == "paysim1"
    assert first.source_rows == 12
    assert first.resources.arrow_batch_size == 4
    assert first.resources.raw_bytes == csv_path.stat().st_size
    assert first.resources.delta_parquet_bytes > 0
    assert first.resources.wall_seconds > 0
    assert first.resources.rows_per_second > 0
    assert first.resources.event_day_partitions == 1
    assert first.entity_definition_version == PAYSIM_ENTITY_DEFINITION_VERSION
    assert first.feature_definition_version == PAYSIM_FEATURE_DEFINITION_VERSION
    assert first.feature_contract_checksum == paysim_feature_contract_checksum()
    assert first.lineage_policy_version == "component-fingerprint-v1"
    assert len(first.lakehouse_component_fingerprint or "") == 64
    assert first.lakehouse_component_paths
    assert first.lakehouse_component_dirty is True
    assert first.repository_dirty is True
    assert len(first.quality_gates) == 9
    assert all(gate.status == "pass" for gate in first.quality_gates)
    assert all(snapshot.rows == 12 for snapshot in first.tables)
    assert first_manifest_path == second_manifest_path

    first_bronze = _snapshot(first, "bronze", "paysim_transactions")
    first_transactions = _snapshot(first, "silver", "paysim_transactions")
    first_labels = _snapshot(first, "silver", "paysim_labels")
    second_bronze = _snapshot(second, "bronze", "paysim_transactions")
    second_transactions = _snapshot(second, "silver", "paysim_transactions")
    second_labels = _snapshot(second, "silver", "paysim_labels")

    assert f"{first_transactions.layer}.{first_transactions.table}" == PAYSIM_FEATURE_SOURCE
    assert f"{first_labels.layer}.{first_labels.table}" == PAYSIM_LABEL_SOURCE
    assert second_bronze.version == first_bronze.version + 1
    assert second_transactions.version == first_transactions.version + 1
    assert second_labels.version == first_labels.version + 1
    for initial, rerun in zip(first.tables, second.tables, strict=True):
        assert initial.logical_checksum == rerun.logical_checksum
        assert initial.schema_checksum == rerun.schema_checksum

    bronze_path = _table_path(project_root, first_bronze.path)
    transactions_path = _table_path(project_root, first_transactions.path)
    labels_path = _table_path(project_root, first_labels.path)
    bronze = DeltaTable(bronze_path, version=first_bronze.version).to_pyarrow_table()
    transactions = DeltaTable(
        transactions_path,
        version=first_transactions.version,
    ).to_pyarrow_table()
    labels = DeltaTable(labels_path, version=first_labels.version).to_pyarrow_table()

    assert tuple(bronze.column_names) == PAYSIM_BRONZE_COLUMNS
    assert tuple(transactions.column_names) == PAYSIM_SILVER_TRANSACTION_COLUMNS
    assert tuple(labels.column_names) == PAYSIM_SILVER_LABEL_COLUMNS
    assert set(PAYSIM_FORBIDDEN_MODEL_INPUTS).isdisjoint(transactions.column_names)
    assert "destination_entity_id" in transactions.column_names
    assert "destination_entity_kind" in transactions.column_names
    assert len(set(transactions.column("source_record_id").to_pylist())) == 12
    assert set(transactions.column("destination_entity_kind").to_pylist()) == {
        "CUSTOMER",
        "MERCHANT",
    }
    assert "isFraud" in labels.column_names
    assert sum(labels.column("isFraud").to_pylist()) == 3

    immutable_manifests = list(second_manifest_path.parent.joinpath("manifests").glob("*.json"))
    assert len(immutable_manifests) == 2
    latest = ApplicationLakehouseManifest.model_validate_json(
        second_manifest_path.read_text(encoding="utf-8")
    )
    assert latest == second
    assert find_latest_paysim_lakehouse_manifest(artifact_root) == second_manifest_path
    history = paysim_lakehouse_history(
        second_manifest_path,
        project_root=project_root,
    )
    assert len(history) == 6


def test_paysim_quality_failure_blocks_delta_publish(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _copy_fixture(project_root)
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace(
            "1,PAYMENT,10.0,",
            "1,PAYMENT,-10.0,",
            1,
        ),
        encoding="utf-8",
    )
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"

    with pytest.raises(ValueError, match="invalid_amount_rows"):
        build_paysim_lakehouse(
            csv_path,
            project_root=project_root,
            data_root=data_root,
            artifact_root=artifact_root,
            batch_size=4,
        )

    assert not (data_root / "lakehouse").exists()


def test_exact_silver_versions_build_strict_pit_training_vectors(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _copy_fixture(project_root)
    manifest, manifest_path = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=project_root / "data",
        artifact_root=project_root / "artifacts",
        batch_size=4,
    )

    vectors, sources = build_silver_training_vectors(
        manifest_path,
        project_root=project_root,
        train_nonfraud_sample_per_type=100,
        seed=20_260_727,
        train_end_step=2,
        validation_end_step=4,
    )

    assert sources.manifest == manifest
    assert sources.transactions_snapshot.version == 0
    assert sources.labels_snapshot.version == 0
    assert tuple(vectors.table.column_names) == TRAINING_VECTOR_COLUMNS
    assert vectors.table.num_rows == 7
    assert vectors.future_read_violations == 0
    assert len(vectors.checksum) == 64
    assert [(item.name, item.rows, item.natural_prevalence) for item in vectors.partitions] == [
        ("train", 2, False),
        ("validation", 3, True),
        ("test", 2, True),
    ]

    rows = vectors.table.to_pylist()
    step_five = next(row for row in rows if row["step"] == 5)
    # ADR-011 v3: count_168h/has_history_168h were dropped; the 168h history is checked through
    # pit_prior_amount_168h, and recency (5 - latest prior step 4 = 1) covers has-history.
    assert step_five["pit_prior_amount_168h"] == 5.0
    assert step_five["pit_steps_since_last_event"] == 1
    assert step_five["max_pit_source_step_168h"] == 4

    step_six = next(row for row in rows if row["step"] == 6)
    # No prior event -> cold: zero history amount and the recency sentinel.
    assert step_six["pit_prior_amount_168h"] == 0.0
    assert step_six["pit_steps_since_last_event"] == PAYSIM_RECENCY_SENTINEL_STEPS
    assert step_six["max_pit_source_step_168h"] is None
