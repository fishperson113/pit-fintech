from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from typer.testing import CliRunner

from pit_fintech.cli import app
from pit_fintech.contracts.manifests import (
    ModelCandidateManifest,
    ModelCandidateResult,
)
from pit_fintech.data.paysim import (
    BALANCE_COLUMNS,
    LABEL_COLUMNS,
    POLICY_OUTPUT_COLUMNS,
    connect_paysim,
)
from pit_fintech.features.paysim_specs import PAYSIM_FEATURE_DEFINITION_VERSION
from pit_fintech.models.paysim_lightgbm import (
    CLAIM_BOUNDARY,
    EXPERIMENT_MATRIX,
    LEAKY_FEATURE_COLUMNS,
    LIGHTGBM_SPIKE_VERSION,
    PIT_FEATURE_COLUMNS,
    SKOPS_TRUSTED_LIGHTGBM_TYPES,
    STATIC_FEATURE_COLUMNS,
    _binary_operating_metrics,
    _threshold_for_fixed_fpr,
    build_candidate_table,
    candidate_feature_columns,
    configure_mlflow_experiment,
    default_artifact_uri,
    default_tracking_uri,
    find_latest_candidate_manifest,
    load_candidate_manifest,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "paysim_recipient_temporal.csv"


def test_model_spike_cli_reaches_dataset_discovery_before_training(monkeypatch) -> None:
    discovered_from: list[Path] = []

    def missing_dataset(project_root: Path, explicit_path: Path | None) -> None:
        discovered_from.append(project_root)
        assert explicit_path is None
        return None

    monkeypatch.setattr("pit_fintech.cli.find_paysim_csv", missing_dataset)

    result = CliRunner().invoke(app, ["model", "spike"])

    assert result.exit_code == 2
    assert discovered_from == [Path.cwd().resolve()]
    assert "PaySim CSV was not found" in result.stdout
    assert not isinstance(result.exception, NameError)


def test_local_mlflow_uses_sqlite_and_explicit_artifact_root(tmp_path: Path) -> None:
    tracking_uri = default_tracking_uri(tmp_path)
    artifact_uri = default_artifact_uri(tmp_path)

    assert tracking_uri.startswith("sqlite:///")
    assert tracking_uri.endswith("/mlflow/tracking.db")
    assert artifact_uri.startswith("file:")
    assert artifact_uri.endswith("/mlflow/artifacts")
    assert (tmp_path / "mlflow").is_dir()
    assert (tmp_path / "mlflow" / "artifacts").is_dir()


def test_mlflow_experiment_is_created_with_explicit_artifact_location() -> None:
    calls: list[tuple[str, object]] = []

    class FakeMlflow:
        def set_tracking_uri(self, tracking_uri: str) -> None:
            calls.append(("set_tracking_uri", tracking_uri))

        def get_experiment_by_name(self, experiment_name: str) -> None:
            calls.append(("get_experiment_by_name", experiment_name))
            return None

        def create_experiment(self, experiment_name: str, *, artifact_location: str) -> None:
            calls.append(("create_experiment", (experiment_name, artifact_location)))

        def set_experiment(self, experiment_name: str) -> None:
            calls.append(("set_experiment", experiment_name))

    configure_mlflow_experiment(
        FakeMlflow(),
        tracking_uri="sqlite:///tracking.db",
        experiment_name="candidate-spike",
        artifact_uri="file:///artifacts",
    )

    assert calls == [
        ("set_tracking_uri", "sqlite:///tracking.db"),
        ("get_experiment_by_name", "candidate-spike"),
        ("create_experiment", ("candidate-spike", "file:///artifacts")),
        ("set_experiment", "candidate-spike"),
    ]


def test_fixed_fpr_threshold_can_choose_a_finite_zero_positive_fallback() -> None:
    labels = np.asarray([0, 0, 1])
    scores = np.asarray([0.9, 0.8, 0.7])

    def roc_curve(_labels, _scores):
        return (
            np.asarray([0.0, 0.5, 1.0]),
            np.asarray([0.0, 0.0, 1.0]),
            np.asarray([np.inf, 0.9, 0.7]),
        )

    dependencies = SimpleNamespace(numpy=np, roc_curve=roc_curve)
    selection = _threshold_for_fixed_fpr(
        labels,
        scores,
        fixed_fpr=0.01,
        dependencies=dependencies,
    )
    metrics = _binary_operating_metrics(labels, scores, selection.threshold)

    assert selection.policy == "zero-positive-fallback"
    assert np.isfinite(selection.threshold)
    assert selection.threshold > scores.max()
    assert metrics == {
        "test_recall_at_fixed_fpr": 0.0,
        "test_precision_at_fixed_fpr": 0.0,
        "test_observed_fpr": 0.0,
    }


def test_candidate_matrix_matches_predeclared_e1_to_e4_contract() -> None:
    assert [
        (spec.experiment_id, spec.feature_set, spec.split_policy) for spec in EXPERIMENT_MATRIX
    ] == [
        ("E1", "static", "temporal"),
        ("E2", "leaky", "random"),
        ("E3", "pit", "random"),
        ("E4", "pit", "temporal"),
    ]
    assert candidate_feature_columns("static") == STATIC_FEATURE_COLUMNS
    assert candidate_feature_columns("pit") == PIT_FEATURE_COLUMNS
    assert candidate_feature_columns("leaky") == LEAKY_FEATURE_COLUMNS


def test_deployable_candidate_columns_exclude_raw_forbidden_fields() -> None:
    forbidden = {*BALANCE_COLUMNS, *LABEL_COLUMNS, *POLICY_OUTPUT_COLUMNS}

    assert set(STATIC_FEATURE_COLUMNS).isdisjoint(forbidden)
    assert set(PIT_FEATURE_COLUMNS).isdisjoint(forbidden)
    assert not any("future" in column or "leaky" in column for column in PIT_FEATURE_COLUMNS)
    assert any("future" in column for column in LEAKY_FEATURE_COLUMNS)


def test_skops_allowlist_is_minimal_and_lightgbm_specific() -> None:
    assert SKOPS_TRUSTED_LIGHTGBM_TYPES == (
        "collections.OrderedDict",
        "lightgbm.basic.Booster",
        "lightgbm.sklearn.LGBMClassifier",
    )
    assert "*" not in SKOPS_TRUSTED_LIGHTGBM_TYPES


def test_candidate_table_preserves_recipient_pit_and_explicit_splits() -> None:
    connection = connect_paysim(FIXTURE_PATH)
    try:
        table = build_candidate_table(
            connection,
            nonfraud_sample_per_group=100,
            train_end_step=140,
            validation_end_step=170,
        )
    finally:
        connection.close()

    rows = table.to_pylist()
    assert len(rows) == 9
    assert {row["split"] for row in rows} == {"train", "validation", "test"}
    step_two = next(row for row in rows if row["step"] == 2)
    assert step_two["pit_prior_count_168h"] == 2
    assert step_two["pit_prior_amount_168h"] == 30.0
    assert step_two["current_inclusive_amount_168h"] == 60.0
    assert step_two["future_amount_168h"] > 0


def _fake_result(experiment_id: str, feature_set: str, split_policy: str) -> dict[str, object]:
    return {
        "experiment_id": experiment_id,
        "feature_set": feature_set,
        "split_policy": split_policy,
        "feature_names": list(STATIC_FEATURE_COLUMNS),
        "train_rows": 10,
        "validation_rows": 4,
        "test_rows": 4,
        "train_fraud_rate": 0.1,
        "validation_fraud_rate": 0.1,
        "test_fraud_rate": 0.1,
        "validation_threshold": 0.5,
        "validation_threshold_policy": "max-tpr-within-fpr",
        "test_pr_auc": 0.2,
        "test_roc_auc": 0.7,
        "test_recall_at_fixed_fpr": 0.3,
        "test_precision_at_fixed_fpr": 0.4,
        "test_observed_fpr": 0.01,
        "best_iteration": 20,
        "training_seconds": 0.5,
        "process_rss_before_bytes": 100,
        "process_rss_after_bytes": 200,
        "training_dataset_checksum": "c" * 64,
        "mlflow_run_id": f"run-{experiment_id}",
        "model_uri": f"runs:/run-{experiment_id}/model",
    }


def test_manifest_round_trip_and_latest_discovery(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    tracking_uri = default_tracking_uri(artifact_root)
    result_payloads = (
        _fake_result("E1", "static", "temporal"),
        _fake_result("E2", "leaky", "random"),
        _fake_result("E3", "pit", "random"),
        _fake_result("E4", "pit", "temporal"),
    )
    manifest = ModelCandidateManifest(
        status="completed",
        spike_version=LIGHTGBM_SPIKE_VERSION,
        run_id="parent-run",
        created_at=datetime.now(UTC),
        dataset_snapshot_id="paysim1:fixture",
        dataset_file_sha256="a" * 64,
        entity_definition_version="paysim-destination-customer-v1",
        candidate_feature_version=PAYSIM_FEATURE_DEFINITION_VERSION,
        model_family="lightgbm",
        seed=20_260_727,
        fixed_fpr=0.01,
        nonfraud_sample_per_group=100,
        cohort_rows=18,
        cohort_fraud_rows=4,
        candidate_table_checksum="d" * 64,
        cohort_sampling_policy="fixture",
        code_commit="abc123",
        dependency_lock_sha256="b" * 64,
        dependency_versions={"lightgbm": "fixture"},
        mlflow_tracking_uri=tracking_uri,
        mlflow_parent_run_id="parent-run",
        claim_boundary=CLAIM_BOUNDARY,
        experiments=tuple(
            ModelCandidateResult.model_validate(payload) for payload in result_payloads
        ),
    )
    manifest_path = (
        artifact_root / "experiments" / "paysim-lightgbm-spike" / "parent-run" / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )

    assert tracking_uri.startswith("sqlite:///")
    assert find_latest_candidate_manifest(artifact_root) == manifest_path
    assert load_candidate_manifest(manifest_path) == manifest
