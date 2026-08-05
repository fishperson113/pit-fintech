from __future__ import annotations

import argparse
from pathlib import Path

from deltalake import DeltaTable

from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.build_lakehouse import logical_table_checksum
from pit_fintech.data.paysim_lakehouse import (
    arrow_schema_checksum,
    find_latest_paysim_lakehouse_manifest,
)
from pit_fintech.features.build_offline import (
    GOLD_PARTITION_COLUMN,
    GOLD_PRE_DECISION_TABLE,
    GoldTableSnapshot,
)
from pit_fintech.models.paysim_lightgbm import default_tracking_uri
from pit_fintech.training.dataset import (
    EntityDataframeSpec,
    build_entity_dataframe,
    retrieve_historical_features,
    split_temporal,
)
from pit_fintech.training.pipeline import TrainingConfig, train_candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one reproducible T4 Gold training candidate")
    parser.add_argument("--experiment", choices=("E1", "E4"), default="E4")
    parser.add_argument("--feature-set", choices=("static", "pit"), default="pit")
    parser.add_argument("--seed", type=int, default=20_260_727)
    parser.add_argument("--fixed-fpr", type=float, default=0.01)
    parser.add_argument("--max-boost-rounds", type=int, default=300)
    parser.add_argument("--early-stopping-rounds", type=int, default=30)
    return parser


def _gold_snapshot(*, path: Path, table_name: str) -> GoldTableSnapshot:
    table = DeltaTable(str(path))
    arrow = table.to_pyarrow_table()
    partitions = tuple(sorted({int(value) for value in arrow[GOLD_PARTITION_COLUMN].to_pylist()}))
    return GoldTableSnapshot(
        layer="gold",
        table=table_name,
        path=str(path),
        version=table.version(),
        rows=arrow.num_rows,
        schema_checksum=arrow_schema_checksum(arrow.schema),
        logical_checksum=logical_table_checksum(arrow),
        partition_column=GOLD_PARTITION_COLUMN,
        partitions_written=partitions,
        delta_app_id=None,
        delta_app_version=None,
    )


def main() -> int:
    args = _parser().parse_args()
    project_root = Path.cwd().resolve()
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"
    manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
    if manifest_path is None:
        raise SystemExit(
            "No PaySim lakehouse manifest found; build Silver before train-gold-candidate"
        )
    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    snapshot_prefix = manifest.raw_file_sha256[:16]
    gold_path = data_root / "lakehouse" / "paysim1" / snapshot_prefix / "gold"
    pre_path = gold_path / GOLD_PRE_DECISION_TABLE
    if not (pre_path / "_delta_log").exists():
        raise SystemExit(
            "No committed Gold pre_decision_features found; promote Gold before "
            "train-gold-candidate"
        )
    labels = next(
        item for item in manifest.tables if item.layer == "silver" and item.table == "paysim_labels"
    )
    pre_snapshot = _gold_snapshot(path=pre_path, table_name=GOLD_PRE_DECISION_TABLE)
    spec = EntityDataframeSpec(
        dataset_snapshot_id=manifest.dataset_snapshot_id,
        entity_definition_version=manifest.entity_definition_version,
        feature_definition_version=manifest.feature_definition_version,
        feature_service_version="paysim-fraud-scoring-v2",
        feature_contract_checksum=manifest.feature_contract_checksum,
        gold_pre_decision=pre_snapshot,
        label_table_path=labels.path,
        label_table_version=labels.version,
        start_step=1,
        end_step=743,
        retrieval_backend="duckdb_gold",
    )
    dataframe_path = build_entity_dataframe(spec=spec, artifact_root=artifact_root, progress=True)
    retrieval = retrieve_historical_features(
        spec=spec,
        entity_dataframe_path=dataframe_path,
        artifact_root=artifact_root,
        progress=True,
    )
    dataset = split_temporal(retrieval=retrieval, progress=True)
    config = TrainingConfig(
        experiment_id=args.experiment,
        model_family="lightgbm",
        feature_set=args.feature_set,
        parameters={},
        seed=args.seed,
        fixed_fpr=args.fixed_fpr,
        early_stopping_rounds=args.early_stopping_rounds,
        max_boost_rounds=args.max_boost_rounds,
    )
    result = train_candidate(
        dataset=dataset,
        config=config,
        project_root=project_root,
        artifact_root=artifact_root,
        mlflow_tracking_uri=default_tracking_uri(artifact_root),
        experiment_name="pit-fintech-gold-training",
        progress=True,
    )
    print(f"status: {result.status}")
    print(f"experiment: {config.experiment_id}; feature_set: {config.feature_set}")
    print(f"mlflow_run_id: {result.mlflow_run_id}")
    print(f"test_pr_auc: {result.metrics.test_pr_auc:.6f}")
    print(f"missing_tags: {result.missing_tags}")
    print(f"missing_artifacts: {result.missing_artifacts}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
