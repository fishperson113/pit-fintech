"""Single command boundary used by Make, PowerShell, CI, and notebooks."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pit_fintech.config import get_settings
from pit_fintech.data.build_lakehouse import build_sample_lakehouse, lakehouse_history
from pit_fintech.data.paysim import (
    create_paysim_snapshot,
    find_paysim_csv,
    profile_paysim,
    resolve_project_root,
    setup_instructions,
)
from pit_fintech.data.paysim_fixture import build_paysim_temporal_fixture
from pit_fintech.data.paysim_lakehouse import (
    build_paysim_lakehouse,
    find_latest_paysim_lakehouse_manifest,
    paysim_lakehouse_history,
)
from pit_fintech.data.sample import PARQUET_PATH, build_sample_fixture, profile_sample_fixture
from pit_fintech.features.build_offline import (
    DeltaSourceRef,
    GoldScanEvidence,
    GoldTableSnapshot,
    GoldValidation,
    OfflineFeatureBuildResult,
    SameStepTieProbe,
    build_offline_features,
    promote_staged_gold,
)
from pit_fintech.platform.doctor import collect_checks
from pit_fintech.platform.notebooks import verify_notebooks

app = typer.Typer(no_args_is_help=True, help="PIT Fintech local control plane")
data_app = typer.Typer(no_args_is_help=True, help="Dataset and fixture commands")
notebooks_app = typer.Typer(no_args_is_help=True, help="Notebook quality commands")
model_app = typer.Typer(no_args_is_help=True, help="Exploratory and gated model commands")
features_app = typer.Typer(no_args_is_help=True, help="Versioned feature contract commands")
app.add_typer(data_app, name="data")
app.add_typer(notebooks_app, name="notebooks")
app.add_typer(model_app, name="model")
app.add_typer(features_app, name="features")
console = Console()


@app.command()
def doctor(
    project_root: Annotated[Path, typer.Option(help="Repository root to inspect")] = Path("."),
) -> None:
    """Inspect prerequisites without changing the host or revealing credentials."""

    checks = collect_checks(project_root.resolve())
    table = Table(title="PIT Fintech environment")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for check in checks:
        table.add_row(check.name, f"[{colors[check.status]}]{check.status}[/]", check.detail)
    console.print(table)
    failures = [check for check in checks if check.status == "FAIL"]
    if failures:
        raise typer.Exit(code=1)


@data_app.command("sample")
def data_sample() -> None:
    """Build and validate the credential-free synthetic temporal oracle."""

    manifest = build_sample_fixture()
    console.print(
        f"[green]validated[/] {manifest.canonical_rows} canonical events "
        f"from {manifest.source_rows} rows"
    )
    console.print(f"snapshot: [cyan]{manifest.dataset_snapshot_id}[/]")
    console.print(f"parquet: {PARQUET_PATH}")


@data_app.command("profile")
def data_profile(
    dataset: Annotated[str, typer.Option(help="Dataset implementation to profile")] = "sample",
    path: Annotated[
        Path | None,
        typer.Option(
            help="Explicit PaySim CSV path; otherwise use PAYSIM_CSV, .env, or default location"
        ),
    ] = None,
    checksum: Annotated[
        bool,
        typer.Option(help="Hash the full PaySim file and emit dataset_snapshot_id"),
    ] = False,
) -> None:
    """Generate a decision-oriented profile for an implemented dataset path."""

    if dataset == "sample":
        profile = profile_sample_fixture()
        title = "Synthetic fixture profile"
    elif dataset == "paysim":
        project_root = Path.cwd()
        csv_path = find_paysim_csv(project_root, path)
        if csv_path is None:
            console.print(f"[yellow]{setup_instructions(project_root)}[/]")
            raise typer.Exit(code=2)
        profile = profile_paysim(csv_path, include_checksum=checksum)
        title = "PaySim profile"
    else:
        console.print(f"[red]Unknown dataset: {dataset}. Use sample or paysim.[/]")
        raise typer.Exit(code=2)
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in profile.items():
        table.add_row(key, str(value))
    console.print(table)


@data_app.command("snapshot")
def data_snapshot(
    dataset: Annotated[str, typer.Option(help="Raw dataset to identify")] = "paysim",
    path: Annotated[
        Path | None,
        typer.Option(help="Explicit PaySim CSV path; otherwise use configured/default location"),
    ] = None,
) -> None:
    """Create a raw-data identity manifest before EDA or lakehouse ingestion."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim application snapshot is implemented.[/]")
        raise typer.Exit(code=2)

    project_root = Path.cwd()
    csv_path = find_paysim_csv(project_root, path)
    if csv_path is None:
        console.print(f"[yellow]{setup_instructions(project_root)}[/]")
        raise typer.Exit(code=2)

    settings = get_settings()
    artifact_root = settings.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    manifest, manifest_path = create_paysim_snapshot(
        csv_path,
        project_root=project_root,
        artifact_root=artifact_root,
    )
    table = Table(title="PaySim raw snapshot")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("dataset_snapshot_id", manifest.dataset_snapshot_id)
    table.add_row("sha256", manifest.file.sha256)
    table.add_row("bytes", str(manifest.file.bytes))
    table.add_row("rows", str(manifest.source_rows))
    table.add_row("step range", f"{manifest.step_min}-{manifest.step_max}")
    table.add_row("manifest", str(manifest_path))
    console.print(table)


@data_app.command("build-lakehouse")
def data_build_lakehouse(
    dataset: Annotated[str, typer.Option(help="Dataset implementation to build")] = "sample",
    path: Annotated[
        Path | None,
        typer.Option(help="Explicit PaySim CSV path; otherwise use configured/default location"),
    ] = None,
) -> None:
    """Build Bronze/Silver Delta tables after the temporal gate has passed."""

    manifest_path: Path | None = None
    if dataset == "sample":
        manifest = build_sample_lakehouse()
    elif dataset == "paysim":
        project_root = resolve_project_root(Path.cwd())
        csv_path = find_paysim_csv(project_root, path)
        if csv_path is None:
            console.print(f"[yellow]{setup_instructions(project_root)}[/]")
            raise typer.Exit(code=2)
        settings = get_settings()
        data_root = settings.data_root
        if not data_root.is_absolute():
            data_root = project_root / data_root
        artifact_root = settings.artifact_root
        if not artifact_root.is_absolute():
            artifact_root = project_root / artifact_root
        manifest, manifest_path = build_paysim_lakehouse(
            csv_path,
            project_root=project_root,
            data_root=data_root,
            artifact_root=artifact_root,
        )
    else:
        console.print(f"[red]Unknown dataset: {dataset}. Use sample or paysim.[/]")
        raise typer.Exit(code=2)

    table = Table(title=f"Lakehouse snapshot {manifest.dataset_snapshot_id}")
    table.add_column("Layer")
    table.add_column("Table")
    table.add_column("Version", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Logical checksum")
    for snapshot in manifest.tables:
        table.add_row(
            snapshot.layer,
            snapshot.table,
            str(snapshot.version),
            str(snapshot.rows),
            snapshot.logical_checksum[:16],
        )
    console.print(table)
    if manifest_path is not None:
        console.print(f"feature contract: [cyan]{manifest.feature_contract_checksum}[/]")
        console.print(f"quality gates: [green]{len(manifest.quality_gates)} passed[/]")
        console.print(
            f"build: {manifest.resources.wall_seconds:.2f}s; "
            f"{manifest.resources.rows_per_second:,.0f} rows/s; "
            f"{manifest.resources.delta_parquet_bytes:,} Delta bytes; "
            f"{manifest.resources.event_day_partitions} event-day partitions"
        )
        console.print(f"manifest: {manifest_path}")


@data_app.command("lakehouse-history")
def data_lakehouse_history(
    dataset: Annotated[str, typer.Option(help="Lakehouse dataset to inspect")] = "sample",
) -> None:
    """Inspect versioned Delta commits for implemented local tables."""

    if dataset == "sample":
        history = lakehouse_history()
    elif dataset == "paysim":
        project_root = resolve_project_root(Path.cwd())
        artifact_root = get_settings().artifact_root
        if not artifact_root.is_absolute():
            artifact_root = project_root / artifact_root
        manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
        if manifest_path is None:
            console.print(
                "[yellow]No PaySim application manifest. "
                "Run data build-lakehouse --dataset paysim first.[/]"
            )
            return
        history = paysim_lakehouse_history(
            manifest_path,
            project_root=project_root,
        )
    else:
        console.print(f"[red]Unknown dataset: {dataset}. Use sample or paysim.[/]")
        raise typer.Exit(code=2)

    if not history:
        console.print("[yellow]No local Delta commits. Run data build-lakehouse first.[/]")
        return
    table = Table(title="Local Delta history")
    table.add_column("Layer")
    table.add_column("Table")
    table.add_column("Version")
    table.add_column("Operation")
    table.add_column("Timestamp")
    for commit in history:
        table.add_row(
            str(commit["layer"]),
            str(commit["table"]),
            str(commit.get("version")),
            str(commit.get("operation")),
            str(commit.get("timestamp")),
        )
    console.print(table)


@data_app.command("build-fixture")
def data_build_fixture(
    dataset: Annotated[
        str, typer.Option(help="Application dataset to derive the temporal fixture from")
    ] = "paysim",
) -> None:
    """Extract a small real-Silver PaySim fixture, score it with the oracle, write it to disk."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim temporal fixture builder is implemented.[/]")
        raise typer.Exit(code=2)

    project_root = resolve_project_root(Path.cwd())
    settings = get_settings()
    artifact_root = settings.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    if find_latest_paysim_lakehouse_manifest(artifact_root) is None:
        console.print(
            "[yellow]No PaySim application lakehouse manifest. "
            "Run data build-lakehouse --dataset paysim first.[/]"
        )
        raise typer.Exit(code=2)

    result = build_paysim_temporal_fixture(project_root=project_root, artifact_root=artifact_root)

    table = Table(title="PaySim temporal fixture")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("source rows", str(result["source_rows"]))
    table.add_row("feature rows", str(result["feature_rows"]))
    table.add_row("silver path", str(result["silver_path"]))
    table.add_row("fixture path", str(result["fixture_path"]))
    table.add_row("expected path", str(result["expected_path"]))
    table.add_row("parquet path", str(result["parquet_path"]))
    table.add_row("feature table path", str(result["feature_table_path"]))
    console.print(table)


@features_app.command("show")
def features_show(
    dataset: Annotated[
        str,
        typer.Option(help="Application feature contract to inspect"),
    ] = "paysim",
) -> None:
    """Print the frozen application FeatureSpec and its canonical checksum."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim application FeatureSpec is implemented.[/]")
        raise typer.Exit(code=2)

    from pit_fintech.features.paysim_specs import (
        PAYSIM_FEATURE_CONTRACT,
        paysim_feature_contract_checksum,
    )

    contract = PAYSIM_FEATURE_CONTRACT
    console.print(f"contract: [cyan]{contract.name}[/]")
    console.print(f"version: [cyan]{contract.version}[/]")
    console.print(f"service: [cyan]{contract.service_version}[/]")
    console.print(f"entity: {contract.entity} ({contract.entity_definition_version})")
    console.print(
        "scope: "
        + ", ".join(contract.scoring_transaction_types)
        + " -> "
        + ", ".join(contract.scoring_destination_kinds)
    )
    console.print(
        f"cutoff: {contract.cutoff_policy}; "
        f"same-time: {contract.same_time_policy}; "
        f"online: {contract.online_update_policy}"
    )
    console.print(f"checksum: [cyan]{paysim_feature_contract_checksum()}[/]")
    console.print(f"feature_count: {len(contract.feature_specs)}")

    table = Table(title="PaySim FeatureSpec v2")
    table.add_column("Feature")
    table.add_column("Availability")
    table.add_column("Window")
    table.add_column("Aggregation")
    table.add_column("Dtype")
    table.add_column("Default")
    for spec in contract.feature_specs:
        window = (
            "request" if spec.window_seconds is None else f"{spec.window_seconds // (60 * 60)}h"
        )
        table.add_row(
            spec.name,
            spec.availability,
            window,
            spec.aggregation,
            spec.dtype,
            str(spec.default),
        )
    console.print(table)
    console.print("forbidden model inputs: " + ", ".join(contract.forbidden_model_inputs))


def _gold_roots() -> tuple[Path, Path, Path]:
    project_root = resolve_project_root(Path.cwd())
    settings = get_settings()
    data_root = (
        settings.data_root
        if settings.data_root.is_absolute()
        else project_root / settings.data_root
    )
    artifact_root = (
        settings.artifact_root
        if settings.artifact_root.is_absolute()
        else project_root / settings.artifact_root
    )
    return project_root, data_root, artifact_root


def _gold_build_manifest_path(*, artifact_root: Path, run_id: str) -> Path:
    return artifact_root / "runs" / run_id / "gold-build-manifest.json"


def _load_gold_build_result(path: Path) -> OfflineFeatureBuildResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pre_decision = dict(payload["pre_decision"])
    pre_decision["partitions_written"] = tuple(pre_decision["partitions_written"])
    post_event_state = dict(payload["post_event_state"])
    post_event_state["partitions_written"] = tuple(post_event_state["partitions_written"])
    ties = dict(payload["same_step_ties"])
    ties["examples"] = tuple(tuple(example) for example in ties["examples"])
    return OfflineFeatureBuildResult(
        status=payload["status"],
        pipeline_version=payload["pipeline_version"],
        run_id=payload["run_id"],
        built_at=datetime.fromisoformat(payload["built_at"]),
        engine=payload["engine"],
        dataset_snapshot_id=payload["dataset_snapshot_id"],
        raw_file_sha256=payload["raw_file_sha256"],
        entity_definition_version=payload["entity_definition_version"],
        feature_definition_version=payload["feature_definition_version"],
        feature_service_version=payload["feature_service_version"],
        feature_contract_checksum=payload["feature_contract_checksum"],
        cutoff_start_step=payload["cutoff_start_step"],
        cutoff_end_step=payload["cutoff_end_step"],
        lookback_start_step=payload["lookback_start_step"],
        source_tables=tuple(DeltaSourceRef(**source) for source in payload["source_tables"]),
        pre_decision=GoldTableSnapshot(**pre_decision),
        post_event_state=GoldTableSnapshot(**post_event_state),
        staging_root=payload["staging_root"],
        rows_in_scope=payload["rows_in_scope"],
        rows_post_event=payload["rows_post_event"],
        max_source_event_step=payload["max_source_event_step"],
        future_read_violations=payload["future_read_violations"],
        same_step_ties=SameStepTieProbe(**ties),
        scan=GoldScanEvidence(**payload["scan"]),
        validations=tuple(GoldValidation(**validation) for validation in payload["validations"]),
        code_commit=payload["code_commit"],
        lineage_policy_version=payload["lineage_policy_version"],
        gold_component_fingerprint=payload["gold_component_fingerprint"],
        gold_component_paths=tuple(payload["gold_component_paths"]),
        gold_component_dirty=payload["gold_component_dirty"],
        repository_dirty=payload["repository_dirty"],
        manifest_path=payload["manifest_path"],
    )


@features_app.command("build-gold")
def features_build_gold(
    start: Annotated[
        int,
        typer.Option(
            "--start",
            min=1,
            help="Inclusive full-event-day range start, e.g. 1, 25, or 721",
        ),
    ],
    end: Annotated[
        int,
        typer.Option(
            "--end",
            min=1,
            help="Inclusive full-event-day range end, e.g. 24, 48, or 743",
        ),
    ],
    run_id: Annotated[str | None, typer.Option("--run-id", help="Staging run identifier")] = None,
    dataset: Annotated[str, typer.Option(help="Application dataset to build")] = "paysim",
) -> None:
    """Build both Gold tables into staging without promoting them.

    Ranges must cover complete event days: [1,24], [25,48], or [721,743].
    """

    if dataset != "paysim":
        console.print("[red]Only the PaySim Gold builder is implemented.[/]")
        raise typer.Exit(code=2)
    if start > end:
        console.print("[red]--start must be less than or equal to --end.[/]")
        raise typer.Exit(code=2)

    project_root, data_root, artifact_root = _gold_roots()
    resolved_run_id = run_id or (
        f"gold-{start}-{end}-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%f%z')}"
    )
    build = build_offline_features(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        run_id=resolved_run_id,
        cutoff_start_step=start,
        cutoff_end_step=end,
        promote=False,
        progress=True,
    )
    console.print(f"run_id: {build.run_id}")
    console.print(
        f"pre_decision_features: rows={build.pre_decision.rows}; "
        f"partitions_written={list(build.pre_decision.partitions_written)}; "
        f"logical_checksum={build.pre_decision.logical_checksum}"
    )
    console.print(
        f"post_event_state_updates: rows={build.post_event_state.rows}; "
        f"partitions_written={list(build.post_event_state.partitions_written)}; "
        f"logical_checksum={build.post_event_state.logical_checksum}"
    )
    console.print(f"status: {build.status}; promote: False")


@features_app.command("promote-gold")
def features_promote_gold(
    run_id: Annotated[str, typer.Option("--run-id", help="Staged Gold run identifier")],
    dataset: Annotated[str, typer.Option(help="Application dataset to promote")] = "paysim",
) -> None:
    """Promote a previously staged Gold build into the committed Gold tables."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim Gold promoter is implemented.[/]")
        raise typer.Exit(code=2)

    _, data_root, artifact_root = _gold_roots()
    manifest_path = _gold_build_manifest_path(artifact_root=artifact_root, run_id=run_id)
    if not manifest_path.is_file():
        console.print(f"[red]No staged Gold build manifest found at {manifest_path}.[/]")
        raise typer.Exit(code=2)
    try:
        build = _load_gold_build_result(manifest_path)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        console.print(f"[red]Could not load staged Gold build {manifest_path}: {exc}[/]")
        raise typer.Exit(code=2) from exc

    promotion = promote_staged_gold(build=build, data_root=data_root)
    console.print(f"run_id: {promotion.run_id}")
    console.print(f"promoted: {promotion.promoted}")
    console.print(f"strategy: {promotion.strategy}")
    console.print(f"predicate: {promotion.predicate}")
    console.print(f"pre_decision_features_version: {promotion.pre_decision_version}")
    console.print(f"post_event_state_updates_version: {promotion.post_event_state_version}")


@model_app.command("spike")
def model_spike(
    dataset: Annotated[str, typer.Option(help="Application dataset to evaluate")] = "paysim",
    path: Annotated[
        Path | None,
        typer.Option(help="Explicit PaySim CSV path; otherwise use configured/default location"),
    ] = None,
    nonfraud_sample_per_group: Annotated[
        int,
        typer.Option(
            min=1,
            help="Maximum deterministic non-fraud rows per temporal split and transaction type",
        ),
    ] = 5_000,
    seed: Annotated[
        int,
        typer.Option(help="Deterministic model and random-split seed"),
    ] = 20_260_727,
    fixed_fpr: Annotated[
        float,
        typer.Option(min=0.000001, max=0.999999, help="Validation FPR used to choose threshold"),
    ] = 0.01,
    tracking_uri: Annotated[
        str | None,
        typer.Option(help="Optional MLflow URI; default is local SQLite under artifacts"),
    ] = None,
) -> None:
    """Run the pre-contract PaySim LightGBM E1-E4 candidate matrix."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim candidate spike is implemented.[/]")
        raise typer.Exit(code=2)

    from pit_fintech.models.paysim_lightgbm import (
        manifest_summary_rows,
        run_paysim_lightgbm_spike,
    )

    project_root = resolve_project_root(Path.cwd())
    csv_path = find_paysim_csv(project_root, path)
    if csv_path is None:
        console.print(f"[yellow]{setup_instructions(project_root)}[/]")
        raise typer.Exit(code=2)

    settings = get_settings()
    artifact_root = settings.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    manifest, manifest_path = run_paysim_lightgbm_spike(
        csv_path,
        project_root=project_root,
        artifact_root=artifact_root,
        nonfraud_sample_per_group=nonfraud_sample_per_group,
        seed=seed,
        fixed_fpr=fixed_fpr,
        tracking_uri=tracking_uri,
    )

    table = Table(title="PaySim LightGBM candidate spike — cohort diagnostics")
    table.add_column("ID")
    table.add_column("Features")
    table.add_column("Split")
    table.add_column("PR-AUC", justify="right")
    table.add_column("ROC-AUC", justify="right")
    table.add_column("Recall@FPR", justify="right")
    table.add_column("Observed FPR", justify="right")
    table.add_column("Threshold policy")
    for row in manifest_summary_rows(manifest):
        table.add_row(
            str(row["experiment"]),
            str(row["features"]),
            str(row["split"]),
            f"{row['test_pr_auc']:.6f}",
            f"{row['test_roc_auc']:.6f}",
            f"{row['recall_at_fixed_fpr']:.6f}",
            f"{row['observed_fpr']:.6f}",
            str(row["threshold_policy"]),
        )
    console.print(table)
    console.print(f"cohort: {manifest.cohort_rows:,} rows / {manifest.cohort_fraud_rows:,} fraud")
    console.print(f"MLflow parent run: [cyan]{manifest.mlflow_parent_run_id}[/]")
    console.print(f"manifest: {manifest_path}")
    console.print(
        "[yellow]Candidate-spike metrics use a sampled cohort and are not production "
        "model-quality claims.[/]"
    )


@model_app.command("train")
def model_train(
    dataset: Annotated[str, typer.Option(help="Application dataset to train")] = "paysim",
    lakehouse_manifest: Annotated[
        Path | None,
        typer.Option(
            help="Exact application lakehouse manifest; default is the latest PaySim manifest"
        ),
    ] = None,
    train_nonfraud_sample_per_type: Annotated[
        int,
        typer.Option(
            min=1,
            help="Maximum deterministic train non-fraud rows per transaction type",
        ),
    ] = 100_000,
    seed: Annotated[
        int,
        typer.Option(help="Deterministic training and train-sampling seed"),
    ] = 20_260_727,
    fixed_fpr: Annotated[
        float,
        typer.Option(min=0.000001, max=0.999999, help="Validation FPR used to choose threshold"),
    ] = 0.01,
    tracking_uri: Annotated[
        str | None,
        typer.Option(help="Optional MLflow URI; default is local SQLite under artifacts"),
    ] = None,
    allow_dirty: Annotated[
        bool,
        typer.Option(
            help="Allow diagnostic training from dirty component lineage; never promotable"
        ),
    ] = False,
) -> None:
    """Train the locked E1/E4 baseline from exact PaySim Silver Delta versions."""

    if dataset != "paysim":
        console.print("[red]Only the PaySim Silver training baseline is implemented.[/]")
        raise typer.Exit(code=2)

    from pit_fintech.models.paysim_training import (
        manifest_summary_rows,
        run_paysim_silver_training,
    )

    project_root = resolve_project_root(Path.cwd())
    settings = get_settings()
    artifact_root = settings.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    manifest_path = lakehouse_manifest
    if manifest_path is None:
        manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
    elif not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    if manifest_path is None or not manifest_path.is_file():
        console.print(
            "[yellow]No PaySim application lakehouse manifest. "
            "Run build-lakehouse --dataset paysim first.[/]"
        )
        raise typer.Exit(code=2)

    manifest, output_path = run_paysim_silver_training(
        manifest_path,
        project_root=project_root,
        artifact_root=artifact_root,
        train_nonfraud_sample_per_type=train_nonfraud_sample_per_type,
        seed=seed,
        fixed_fpr=fixed_fpr,
        tracking_uri=tracking_uri,
        allow_dirty=allow_dirty,
    )

    partition_table = Table(title="Chronological training population")
    partition_table.add_column("Split")
    partition_table.add_column("Steps")
    partition_table.add_column("Rows", justify="right")
    partition_table.add_column("Fraud", justify="right")
    partition_table.add_column("Fraud rate", justify="right")
    partition_table.add_column("Prevalence")
    for partition in manifest.partitions:
        partition_table.add_row(
            partition.name,
            f"{partition.step_min}-{partition.step_max}",
            f"{partition.rows:,}",
            f"{partition.fraud_rows:,}",
            f"{partition.fraud_rate:.6f}",
            "natural" if partition.natural_prevalence else "train-sampled",
        )
    console.print(partition_table)

    result_table = Table(title="PaySim Silver LightGBM baseline")
    result_table.add_column("ID")
    result_table.add_column("Features")
    result_table.add_column("PR-AUC", justify="right")
    result_table.add_column("ROC-AUC", justify="right")
    result_table.add_column("Recall@FPR", justify="right")
    result_table.add_column("Precision@FPR", justify="right")
    result_table.add_column("Observed FPR", justify="right")
    for row in manifest_summary_rows(manifest):
        result_table.add_row(
            str(row["experiment"]),
            str(row["features"]),
            f"{row['test_pr_auc']:.6f}",
            f"{row['test_roc_auc']:.6f}",
            f"{row['recall_at_fixed_fpr']:.6f}",
            f"{row['precision_at_fixed_fpr']:.6f}",
            f"{row['observed_fpr']:.6f}",
        )
    console.print(result_table)
    versions = ", ".join(
        f"{snapshot.layer}.{snapshot.table}=v{snapshot.version}"
        for snapshot in manifest.source_tables
    )
    console.print(f"Silver versions: [cyan]{versions}[/]")
    console.print(f"vector checksum: [cyan]{manifest.vector_checksum}[/]")
    console.print(f"future-read violations: [green]{manifest.future_read_violations}[/]")
    if manifest.training_component_fingerprint:
        console.print(
            "training fingerprint: "
            f"[cyan]{manifest.training_component_fingerprint}[/] "
            f"({manifest.lineage_policy_version})"
        )
    console.print(f"MLflow parent run: [cyan]{manifest.mlflow_parent_run_id}[/]")
    console.print(f"manifest: {output_path}")


@notebooks_app.command("verify")
def notebooks_verify(
    project_root: Annotated[Path, typer.Option(help="Repository root containing notebooks")] = Path(
        "."
    ),
) -> None:
    """Execute all tracked notebooks in memory without committing cell outputs."""

    paths = verify_notebooks(project_root.resolve())
    for path in paths:
        console.print(f"[green]PASS[/] {path.name}")
    console.print(f"verified {len(paths)} notebooks")


if __name__ == "__main__":
    app()
