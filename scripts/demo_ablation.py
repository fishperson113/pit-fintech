"""demo-ablation: print the E1-E4 ablation table from the spike experiment.

Reads the local SQLite backend directly. A "round" is a set of FINISHED runs sharing the same
``mlflow.parentRunId`` (the spike runner logs one parent per round); the newest complete round
(E1+E2+E3+E4) wins. Nothing is fabricated: if no complete round exists the script says so and
lists what it found.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Final

import mlflow
from mlflow.tracking import MlflowClient

TRACKING_URI: Final = "sqlite:///artifacts/mlflow/tracking.db"
SPIKE_EXPERIMENT: Final = "pit-fintech-paysim-lightgbm-spike"
GOLD_EXPERIMENT: Final = "pit-fintech-gold-training"

EXPECTED: Final = {
    "E1": ("E1-static-temporal", "static/temporal", "baseline chi dung 3 field request"),
    "E2": ("E2-leaky-random", "leaky/random", "positive control CO Y RO RI - khong duoc tin"),
    "E3": ("E3-pit-random", "pit/random", "feature dung nhung split ngau nhien - khong duoc tin"),
    "E4": ("E4-pit-temporal", "pit/temporal", "ung vien that (PIT + split theo thoi gian)"),
}


def _runs(client: MlflowClient, experiment_name: str) -> list:
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        return []
    return client.search_runs(
        experiment_ids=[experiment.experiment_id], order_by=["start_time DESC"]
    )


def _round_key(tags: dict[str, str], start_ms: int) -> str:
    parent = tags.get("mlflow.parentRunId")
    if parent:
        return f"parent:{parent}"
    return f"minute:{start_ms // 60_000}"


def find_complete_round(
    client: MlflowClient,
) -> tuple[dict[str, object], dict[str, object]] | None:
    """Return (round_meta, {label: run_data}) for the newest complete E1-E4 round, or None."""

    rounds: dict[str, list[object]] = defaultdict(list)
    for run in _runs(client, SPIKE_EXPERIMENT):
        if run.info.status != "FINISHED":
            continue
        key = _round_key(run.data.tags, run.info.start_time or 0)
        rounds[key].append(run)
    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    for key, runs in rounds.items():
        by_name = {run.data.tags.get("mlflow.runName"): run for run in runs}
        if all(by_name.get(name) for name, _, _ in EXPECTED.values()):
            newest = max(runs, key=lambda run: run.info.start_time or 0)
            data = {
                label: {
                    "run_id": by_name[run_name].info.run_id,
                    "run_name": run_name,
                    "test_pr_auc": by_name[run_name].data.metrics.get("test_pr_auc"),
                    "test_roc_auc": by_name[run_name].data.metrics.get("test_roc_auc"),
                    "start_time": by_name[run_name].info.start_time,
                }
                for label, (run_name, _, _) in EXPECTED.items()
            }
            candidates.append(({"key": key, "start_ms": newest.info.start_time}, data))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0]["start_ms"])


def _gold_e4_line(client: MlflowClient) -> str:
    runs = [run for run in _runs(client, GOLD_EXPERIMENT) if run.info.status == "FINISHED"]
    if not runs:
        return "E4 tren Gold v6 (gold-training): khong co run FINISHED"
    newest = max(runs, key=lambda run: run.info.start_time or 0)
    pr_auc = newest.data.metrics.get("test_pr_auc")
    value = f"{pr_auc:.6f}" if pr_auc is not None else "N/A"
    return (
        f"E4 tren Gold v6 (experiment {GOLD_EXPERIMENT!r}, run "
        f"{newest.info.run_id[:8]}) = {value}  (cohort khac, khong so truc tiep voi bang tren)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the E1-E4 ablation table")
    parser.parse_args()
    mlflow.set_tracking_uri(TRACKING_URI)
    client = MlflowClient()

    found = find_complete_round(client)
    if found is None:
        print("KHONG tim thay dot day du E1/E2/E3/E4 (FINISHED) trong experiment spike.")
        runs = _runs(client, SPIKE_EXPERIMENT)
        names = sorted({run.data.tags.get("mlflow.runName", "?") for run in runs}, reverse=True)
        print(f"Nhung gi tim duoc ({len(runs)} run): {names}")
        return 1

    _, data = found
    header = (
        f"{'nhan':<4} {'run_name':<20} {'feature_set/split':<18} "
        f"{'test_pr_auc':>12} {'test_roc_auc':>12}  vai tro"
    )
    print(header)
    print("-" * len(header))
    for label, (run_name, split, role) in EXPECTED.items():
        entry = data[label]
        pr_auc = entry["test_pr_auc"]
        roc_auc = entry["test_roc_auc"]
        print(
            f"{label:<4} {run_name:<20} {split:<18} "
            f"{pr_auc if pr_auc is None else f'{pr_auc:.6f}':>12} "
            f"{roc_auc if roc_auc is None else f'{roc_auc:.6f}':>12}  {role}"
        )

    print(
        "\nCanh bao: cung cohort spike (mau 38.213 dong, oversample fraud) -> "
        "so sanh trong bang nay hop le."
    )
    print(
        "KHONG so sanh cac so nay voi experiment khac (silver-baseline, "
        "gold-training) - khac cohort."
    )
    print()
    print(_gold_e4_line(client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
