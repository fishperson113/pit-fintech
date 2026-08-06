"""demo-lineage: print MLflow run lineage (tags/metrics/artifacts) to the terminal.

Reads the local SQLite backend (artifacts/mlflow/tracking.db) directly, so it works whether the
container MLflow or the host mlflow-ui server is running or not. The 10 required lineage tags are
imported from ``pit_fintech.training.pipeline.REQUIRED_MLFLOW_TAGS``, never hand-typed.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Final

import mlflow
from mlflow.tracking import MlflowClient

from pit_fintech.training.pipeline import REQUIRED_MLFLOW_TAGS

TRACKING_URI: Final = "sqlite:///artifacts/mlflow/tracking.db"
EXPERIMENT_NAME: Final = "pit-fintech-gold-training"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print MLflow run lineage for the gold training experiment"
    )
    parser.add_argument("--run-id", help="Print this specific run")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every run of the experiment (default: newest FINISHED run only)",
    )
    return parser


def _iso(millis: int | None) -> str:
    if millis is None:
        return "N/A"
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


def _print_block(title: str) -> None:
    print(f"\n=== {title} ===")


def print_run(run_id: str, client: MlflowClient) -> None:
    run = client.get_run(run_id)
    info = run.info
    tags = run.data.tags
    duration_s = (
        (info.end_time - info.start_time) / 1000.0 if info.start_time and info.end_time else None
    )

    _print_block(f"RUN {run_id}")
    print(f"  run_name     {info.run_name or tags.get('mlflow.runName', 'N/A')}")
    print(f"  status       {info.status}")
    print(f"  start_time   {_iso(info.start_time)}")
    print(f"  end_time     {_iso(info.end_time)}")
    print(f"  duration     {duration_s:.1f}s" if duration_s is not None else "  duration     N/A")

    _print_block("LINEAGE (10 tag bat buoc, thu tu REQUIRED_MLFLOW_TAGS)")
    missing = [name for name in REQUIRED_MLFLOW_TAGS if name not in tags]
    width = max(len(name) for name in REQUIRED_MLFLOW_TAGS)
    for name in REQUIRED_MLFLOW_TAGS:
        value = tags.get(name)
        if value is None:
            print(f"  {name:<{width}}  ** THIEU **")
        else:
            print(f"  {name:<{width}}  {value}")
    if missing:
        print(f"  -> THIEU {len(missing)} tag: {missing}")

    _print_block("METRICS")
    if run.data.metrics:
        width = max(len(name) for name in run.data.metrics)
        for name in sorted(run.data.metrics):
            print(f"  {name:<{width}}  {run.data.metrics[name]}")
    else:
        print("  (khong co metric)")

    _print_block("ARTIFACTS")
    try:
        entries = sorted(
            mlflow.artifacts.list_artifacts(run_id=run_id), key=lambda entry: entry.path
        )
        if not entries:
            print("  (khong co artifact)")
        for entry in entries:
            size = entry.file_size
            size_text = f"{size:,} bytes" if size is not None else "?"
            print(f"  {entry.path:<32} {size_text}")
    except Exception as exc:
        print(f"  khong liet ke duoc artifact (ly do: {exc})")
        print(f"  artifact_uri: {info.artifact_uri}")

    gold = tags.get("gold_feature_table_version", "?")
    silver = tags.get("silver_table_version", "?")
    snapshot = tags.get("dataset_snapshot_id", "?")
    print(f"\n  KET LUAN: Model nay train tren Gold v{gold}, Silver v{silver}, snapshot {snapshot}")


def _resolve_run_ids(client: MlflowClient, args: argparse.Namespace) -> list[str]:
    if args.run_id:
        return [args.run_id]
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        raise SystemExit(f"khong co experiment {EXPERIMENT_NAME!r} trong tracking.db")
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["start_time DESC"],
        max_results=100,
    )
    if not runs:
        raise SystemExit(f"khong co run nao trong experiment {EXPERIMENT_NAME!r}")
    if args.all:
        return [run.info.run_id for run in runs]
    finished = [run.info.run_id for run in runs if run.info.status == "FINISHED"]
    if not finished:
        raise SystemExit("khong co run FINISHED nao de hien thi")
    return [finished[0]]


def main() -> int:
    args = _parser().parse_args()
    mlflow.set_tracking_uri(TRACKING_URI)
    client = MlflowClient()
    for run_id in _resolve_run_ids(client, args):
        print_run(run_id, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
