from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from pit_fintech.cli import app
from pit_fintech.contracts.manifests import (
    DeltaTableSnapshot,
    ModelTrainingResult,
    SilverTrainingManifest,
    TrainingPartitionProfile,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_FORBIDDEN_MODEL_INPUTS,
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_STATIC_FEATURE_NAMES,
)
from pit_fintech.models.paysim_training import (
    CLAIM_BOUNDARY,
    LOCKED_EXPERIMENTS,
    SILVER_TRAINING_PIPELINE_VERSION,
    TRAINING_SAMPLING_POLICY,
    feature_importance_rows,
    find_latest_training_manifest,
    load_training_manifest,
    manifest_summary_rows,
)
from pit_fintech.platform.notebooks import verify_notebooks


def _source_snapshot(table: str, version: int) -> DeltaTableSnapshot:
    return DeltaTableSnapshot(
        layer="silver",
        table=table,
        path=f"data/lakehouse/{table}",
        version=version,
        rows=100,
        schema_checksum="a" * 64,
        logical_checksum="b" * 64,
    )


def _partition(
    name: str,
    *,
    natural_prevalence: bool,
) -> TrainingPartitionProfile:
    bounds = {
        "train": (1, 520),
        "validation": (521, 631),
        "test": (632, 743),
    }
    step_min, step_max = bounds[name]
    return TrainingPartitionProfile(
        name=name,
        rows=100,
        fraud_rows=2,
        fraud_rate=0.02,
        step_min=step_min,
        step_max=step_max,
        natural_prevalence=natural_prevalence,
    )


def _result(experiment_id: str) -> ModelTrainingResult:
    feature_set = "static" if experiment_id == "E1" else "pit"
    feature_names = (
        PAYSIM_STATIC_FEATURE_NAMES if experiment_id == "E1" else PAYSIM_MODEL_FEATURE_ORDER
    )
    return ModelTrainingResult(
        experiment_id=experiment_id,
        feature_set=feature_set,
        split_policy="temporal",
        feature_names=feature_names,
        validation_threshold=0.7,
        validation_threshold_policy="max-tpr-within-fpr",
        test_pr_auc=0.2 if experiment_id == "E1" else 0.3,
        test_roc_auc=0.7,
        test_recall_at_fixed_fpr=0.4,
        test_precision_at_fixed_fpr=0.1,
        test_observed_fpr=0.01,
        best_iteration=20,
        training_seconds=0.5,
        process_rss_before_bytes=100,
        process_rss_after_bytes=200,
        training_dataset_checksum="c" * 64,
        feature_importance_gain={
            feature_name: float(index + 1) for index, feature_name in enumerate(feature_names)
        },
        mlflow_run_id=f"run-{experiment_id}",
        model_uri=f"runs:/run-{experiment_id}/model",
    )


def _manifest() -> SilverTrainingManifest:
    return SilverTrainingManifest(
        status="completed",
        pipeline_version=SILVER_TRAINING_PIPELINE_VERSION,
        run_id="parent-run",
        created_at=datetime.now(UTC),
        application_lakehouse_manifest_path="artifacts/lakehouse-manifest.json",
        application_lakehouse_code_commit="abc123",
        dataset_snapshot_id="paysim1:fixture",
        raw_file_sha256="d" * 64,
        entity_definition_version="paysim-destination-customer-v1",
        feature_definition_version="paysim-fraud-recipient-v1",
        feature_contract_checksum="e" * 64,
        source_tables=(
            _source_snapshot("paysim_transactions", 1),
            _source_snapshot("paysim_labels", 1),
        ),
        train_end_step=520,
        validation_end_step=631,
        train_nonfraud_sample_per_type=100_000,
        training_sampling_policy=TRAINING_SAMPLING_POLICY,
        vector_rows=300,
        vector_fraud_rows=6,
        vector_checksum="f" * 64,
        future_read_violations=0,
        partitions=(
            _partition("train", natural_prevalence=False),
            _partition("validation", natural_prevalence=True),
            _partition("test", natural_prevalence=True),
        ),
        model_family="lightgbm",
        model_parameters={"n_estimators": 300, "deterministic": True},
        seed=20_260_727,
        fixed_fpr=0.01,
        code_commit="abc123",
        dependency_lock_sha256="0" * 64,
        dependency_versions={"lightgbm": "fixture"},
        mlflow_tracking_uri="sqlite:///tracking.db",
        mlflow_parent_run_id="parent-run",
        claim_boundary=CLAIM_BOUNDARY,
        experiments=(_result("E1"), _result("E4")),
    )


def test_locked_training_matrix_contains_only_temporal_e1_and_e4() -> None:
    assert [
        (item.experiment_id, item.feature_set, item.feature_names) for item in LOCKED_EXPERIMENTS
    ] == [
        ("E1", "static", PAYSIM_STATIC_FEATURE_NAMES),
        ("E4", "pit", PAYSIM_MODEL_FEATURE_ORDER),
    ]
    assert set(PAYSIM_MODEL_FEATURE_ORDER).isdisjoint(PAYSIM_FORBIDDEN_MODEL_INPUTS)
    assert not any(
        "future" in feature or "leaky" in feature for feature in PAYSIM_MODEL_FEATURE_ORDER
    )


def test_training_cli_requires_a_lakehouse_manifest_before_loading_model_dependencies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["model", "train"])

    assert result.exit_code == 2
    assert "No PaySim application lakehouse manifest" in result.stdout


def test_training_manifest_round_trip_summary_and_latest_discovery(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    manifest = _manifest()
    manifest_path = (
        artifact_root / "experiments" / "paysim-silver-training" / manifest.run_id / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )

    assert load_training_manifest(manifest_path) == manifest
    assert find_latest_training_manifest(artifact_root) == manifest_path
    summaries = manifest_summary_rows(manifest)
    assert [item["experiment"] for item in summaries] == ["E1", "E4"]
    assert summaries[1]["test_pr_auc"] == 0.3

    importance = feature_importance_rows(manifest, experiment_id="E4")
    assert importance[0]["feature"] == PAYSIM_MODEL_FEATURE_ORDER[-1]
    assert abs(sum(item["gain_share"] for item in importance) - 1.0) < 1e-5


def test_notebook_verifier_forces_review_only_and_restores_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    notebook_path = tmp_path / "notebooks" / "05_silver_training_baseline.ipynb"
    notebook_path.parent.mkdir()
    notebook_path.write_text("{}", encoding="utf-8")
    observed_flags: list[str | None] = []

    class FakeNotebookClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def execute(self) -> None:
            observed_flags.append(os.environ.get("PIT_NOTEBOOK_RUN_TRAINING"))

    fake_nbformat = SimpleNamespace(read=lambda *_args, **_kwargs: {})
    fake_nbclient = SimpleNamespace(NotebookClient=FakeNotebookClient)
    monkeypatch.setitem(sys.modules, "nbformat", fake_nbformat)
    monkeypatch.setitem(sys.modules, "nbclient", fake_nbclient)
    monkeypatch.setenv("PIT_NOTEBOOK_RUN_TRAINING", "1")

    paths = verify_notebooks(tmp_path)

    assert paths == [notebook_path]
    assert observed_flags == ["0"]
    assert os.environ["PIT_NOTEBOOK_RUN_TRAINING"] == "1"
