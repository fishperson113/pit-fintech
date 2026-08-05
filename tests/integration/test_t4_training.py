from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pit_fintech.features.build_offline import GoldTableSnapshot
from pit_fintech.features.paysim_specs import PAYSIM_MODEL_FEATURE_ORDER
from pit_fintech.training.dataset import (
    EntityDataframeSpec,
    HistoricalRetrievalResult,
    TemporalSplit,
    TrainingDataset,
    split_temporal,
)
from pit_fintech.training.pipeline import TrainingConfig, train_candidate


def _require_training() -> None:
    """Skip loudly when the optional training dependency group is missing.

    Mirrors `_require_feast()` in `tests/integration/test_feast_registry_g1.py`: training is an
    optional dependency group kept out of the CI correctness path on purpose (pyproject.toml), so
    the lane skips with an actionable message instead of failing.

    When `PIT_REQUIRE_TRAINING=1` is set (the CI "Delta sample snapshot and time travel" step),
    the skip is escalated to a hard failure: this guard is the latch against a fake-green CI. If
    someone drops `--group training` from ci.yml or from the Makefile lane, the T4 contract lane
    must fail loudly instead of silently skipping.
    """

    try:
        import lightgbm  # noqa: F401
        import mlflow  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment-dependent skip
        if os.environ.get("PIT_REQUIRE_TRAINING") == "1":
            pytest.fail(
                "PIT_REQUIRE_TRAINING=1 but the training dependency group is missing, so the T4 "
                "MLflow contract lane would have skipped silently instead of running. CI must "
                f"install it with `uv sync --frozen --group dev --group training`. ({exc})"
            )
        pytest.skip(
            "Training dependencies are not installed, so the T4 MLflow contract lane cannot run. "
            "Training is an optional dependency group kept out of the correctness path on purpose "
            f"(pyproject.toml). Install it with `uv sync --frozen --group training`. ({exc})"
        )


def _training_dataset(tmp_path: Path) -> TrainingDataset:
    steps = [1, 2, 3, 521, 522, 523, 632, 633, 634]
    labels = [0, 1, 0, 1, 0, 1, 0, 1, 0]
    columns: dict[str, list[object]] = {
        "source_row_number": list(range(1, 10)),
        "step": steps,
        "isFraud": labels,
        "transaction_type": ["CASH_OUT"] * 9,
        "destination_entity_id": ["C100"] * 9,
    }
    for index, name in enumerate(PAYSIM_MODEL_FEATURE_ORDER):
        columns[name] = [float((row + index) % 5) for row in range(9)]
    path = tmp_path / "entity_dataframe.parquet"
    pq.write_table(pa.table(columns), path)
    snapshot = GoldTableSnapshot(
        layer="gold",
        table="pre_decision_features",
        path=str(path),
        version=1,
        rows=9,
        schema_checksum="schema",
        logical_checksum="logical",
        partition_column="event_day",
        partitions_written=(1, 22, 27),
        delta_app_id=None,
        delta_app_version=None,
    )
    spec = EntityDataframeSpec(
        dataset_snapshot_id="paysim1:test",
        entity_definition_version="paysim-destination-customer-v1",
        feature_definition_version="paysim-destination-features-v2",
        feature_service_version="paysim-fraud-scoring-v2",
        feature_contract_checksum="contract",
        gold_pre_decision=snapshot,
        label_table_path=str(path),
        label_table_version=1,
        start_step=1,
        end_step=743,
        retrieval_backend="duckdb_gold",
    )
    retrieval = HistoricalRetrievalResult(
        spec=spec,
        parquet_path=str(path),
        rows=9,
        fraud_rows=4,
        ordered_feature_names=tuple(PAYSIM_MODEL_FEATURE_ORDER),
        feature_dtypes={name: "double" for name in PAYSIM_MODEL_FEATURE_ORDER},
        label_column="isFraud",
        training_dataset_checksum="dataset-checksum",
        missing_entity_rows=0,
        max_source_event_step=634,
        future_read_violations=0,
        assertions=(),
    )
    return TrainingDataset(
        retrieval=retrieval,
        split_policy="temporal_frozen",
        experiment_namespace="training",
        partitions=(
            TemporalSplit(
                name="train",
                start_step=1,
                end_step=520,
                rows=3,
                fraud_rows=1,
                fraud_rate=1 / 3,
                natural_prevalence=False,
            ),
            TemporalSplit(
                name="validation",
                start_step=521,
                end_step=631,
                rows=3,
                fraud_rows=2,
                fraud_rate=2 / 3,
                natural_prevalence=True,
            ),
            TemporalSplit(
                name="test",
                start_step=632,
                end_step=743,
                rows=3,
                fraud_rows=1,
                fraud_rate=1 / 3,
                natural_prevalence=True,
            ),
        ),
        ordered_feature_names=tuple(PAYSIM_MODEL_FEATURE_ORDER),
        training_dataset_checksum="dataset-checksum",
    )


def test_t4_train_candidate_logs_complete_mlflow_contract(tmp_path: Path) -> None:
    _require_training()
    dataset = _training_dataset(tmp_path)
    result = train_candidate(
        dataset=dataset,
        config=TrainingConfig(
            experiment_id="E4",
            model_family="lightgbm",
            feature_set="pit",
            parameters={"n_estimators": 10, "min_child_samples": 1},
            seed=20260727,
            fixed_fpr=0.01,
            early_stopping_rounds=3,
            max_boost_rounds=10,
        ),
        project_root=Path.cwd(),
        artifact_root=tmp_path / "artifacts",
        mlflow_tracking_uri=f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}",
        experiment_name="t4-test",
    )
    assert result.status == "completed", (result.missing_tags, result.missing_artifacts)
    assert result.missing_tags == ()
    assert result.missing_artifacts == ()
    assert result.mlflow_run_id
    assert result.metrics.test_pr_auc >= 0.0


def test_split_temporal_rejects_partial_gold_range(tmp_path: Path) -> None:
    """A partial Gold backfill must fail fast instead of producing an empty split.

    This mirrors the real-lakehouse state (Gold promoted only to step 48): every entity row
    lands in the train range and validation/test would be empty. The frozen split contract is
    not weakened; the error must explain the observed versus required step coverage.
    """

    path = tmp_path / "partial_entity_dataframe.parquet"
    steps = [1, 2, 3, 47, 48]
    labels = [0, 1, 0, 1, 0]
    columns: dict[str, list[object]] = {
        "source_row_number": list(range(1, 6)),
        "step": steps,
        "isFraud": labels,
        "transaction_type": ["CASH_OUT"] * 5,
        "destination_entity_id": ["C100"] * 5,
    }
    for index, name in enumerate(PAYSIM_MODEL_FEATURE_ORDER):
        columns[name] = [float((row + index) % 5) for row in range(5)]
    pq.write_table(pa.table(columns), path)
    spec = EntityDataframeSpec(
        dataset_snapshot_id="paysim1:partial",
        entity_definition_version="paysim-destination-customer-v1",
        feature_definition_version="paysim-destination-features-v2",
        feature_service_version="paysim-fraud-scoring-v2",
        feature_contract_checksum="contract",
        gold_pre_decision=GoldTableSnapshot(
            layer="gold",
            table="pre_decision_features",
            path=str(path),
            version=1,
            rows=5,
            schema_checksum="schema",
            logical_checksum="logical",
            partition_column="event_day",
            partitions_written=(1, 2),
            delta_app_id=None,
            delta_app_version=None,
        ),
        label_table_path=str(path),
        label_table_version=1,
        start_step=1,
        end_step=48,
        retrieval_backend="duckdb_gold",
    )
    retrieval = HistoricalRetrievalResult(
        spec=spec,
        parquet_path=str(path),
        rows=5,
        fraud_rows=2,
        ordered_feature_names=tuple(PAYSIM_MODEL_FEATURE_ORDER),
        feature_dtypes={name: "double" for name in PAYSIM_MODEL_FEATURE_ORDER},
        label_column="isFraud",
        training_dataset_checksum="partial-checksum",
        missing_entity_rows=0,
        max_source_event_step=48,
        future_read_violations=0,
        assertions=(),
    )
    with pytest.raises(ValueError, match="does not cover the full frozen temporal split range"):
        split_temporal(retrieval=retrieval)
