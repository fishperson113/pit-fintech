"""Single command boundary used by Make, PowerShell, CI, and notebooks."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
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
from pit_fintech.materialization.materializer import (
    OnlineStoreConfig,
    materialize_to_watermark,
    read_online_features,
    read_watermark,
)
from pit_fintech.materialization.records import OnlineStoreKind
from pit_fintech.platform.doctor import collect_checks
from pit_fintech.platform.notebooks import verify_notebooks
from pit_fintech.serving import app as serving_runtime
from pit_fintech.serving.scoring import FailurePolicy

app = typer.Typer(no_args_is_help=True, help="PIT Fintech local control plane")
data_app = typer.Typer(no_args_is_help=True, help="Dataset and fixture commands")
ingest_app = typer.Typer(no_args_is_help=True, help="Offline ingestion commands")
notebooks_app = typer.Typer(no_args_is_help=True, help="Notebook quality commands")
model_app = typer.Typer(no_args_is_help=True, help="Exploratory and gated model commands")
features_app = typer.Typer(no_args_is_help=True, help="Versioned feature contract commands")
materialize_app = typer.Typer(no_args_is_help=True, help="Online store materialization commands")
serving_app = typer.Typer(no_args_is_help=True, help="Scoring API commands")
parity_app = typer.Typer(no_args_is_help=True, help="Offline/online parity reconcile commands")
app.add_typer(data_app, name="data")
app.add_typer(ingest_app, name="ingest")
app.add_typer(notebooks_app, name="notebooks")
app.add_typer(model_app, name="model")
app.add_typer(features_app, name="features")
app.add_typer(materialize_app, name="materialize")
app.add_typer(serving_app, name="serving")
app.add_typer(parity_app, name="parity")
console = Console()


def _configure_offline_observability(service_name: str):
    """Export offline lifecycle logs when the shared OTLP endpoint is configured."""

    settings = get_settings()
    endpoint = settings.otel_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    from pit_fintech.platform.logging_config import configure_logging
    from pit_fintech.serving.telemetry import configure_telemetry

    configure_logging(level=settings.log_level, json=True)
    return configure_telemetry(service_name=service_name, endpoint=endpoint, enabled=True)


@ingest_app.command("event-history")
def ingest_event_history_command(
    history_path: Annotated[
        Path | None,
        typer.Option(
            help="Event History JSONL; defaults to artifacts/event_history/served_events.jsonl"
        ),
    ] = None,
    bronze_path: Annotated[
        Path | None,
        typer.Option(help="Bronze landing Delta path; defaults to data/lakehouse/served_events"),
    ] = None,
    checkpoint_path: Annotated[
        Path | None,
        typer.Option(help="Checkpoint JSON path; defaults to artifacts/ingest/event_history.json"),
    ] = None,
) -> None:
    """Ingest unseen serving events into the append-only Bronze landing Delta table."""

    from pit_fintech.ingest.event_history import ingest_event_history

    _configure_offline_observability("pit-fintech-offline-ingest")
    project_root = resolve_project_root(Path.cwd())
    settings = get_settings()

    def resolve_configured(path: Path) -> Path:
        return path if path.is_absolute() else project_root / path

    artifact_root = resolve_configured(settings.artifact_root)
    data_root = resolve_configured(settings.data_root)
    report = ingest_event_history(
        history_path=(
            resolve_configured(history_path)
            if history_path is not None
            else artifact_root / "event_history" / "served_events.jsonl"
        ),
        bronze_path=(
            resolve_configured(bronze_path)
            if bronze_path is not None
            else data_root / "lakehouse" / "served_events"
        ),
        checkpoint_path=(
            resolve_configured(checkpoint_path)
            if checkpoint_path is not None
            else artifact_root / "ingest" / "event_history.json"
        ),
    )
    candidate_report = None
    if Path(report.bronze_path).exists():
        from pit_fintech.features.served_event_pipeline import build_served_event_candidate

        candidate_report = build_served_event_candidate(
            bronze_path=Path(report.bronze_path),
            silver_path=data_root / "lakehouse" / "served_events_silver",
            candidate_path=data_root / "lakehouse" / "served_events_gold_candidate",
            quarantine_path=data_root / "lakehouse" / "quarantine" / "served_events",
        )
    console.print(f"history: {report.history_path}")
    console.print(f"bronze: {report.bronze_path}")
    console.print(f"rows_read: {report.rows_read}")
    console.print(f"rows_appended: {report.rows_appended}")
    console.print(f"duplicate_rows: {report.duplicate_rows}")
    console.print(f"checkpoint_line: {report.end_line}")
    if candidate_report is not None:
        console.print(f"silver_rows: {candidate_report.silver_rows}")
        console.print(f"gold_candidate_rows: {candidate_report.candidate_rows}")
        console.print(f"quarantined_rows: {candidate_report.quarantined_rows}")


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

    _configure_offline_observability("pit-fintech-offline-gold")
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

    _configure_offline_observability("pit-fintech-offline-gold")
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

    promotion = promote_staged_gold(build=build, data_root=data_root, progress=True)
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
    table.add_column("Precision@FPR", justify="right")
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
            f"{row['precision_at_fixed_fpr']:.6f}",
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


@model_app.command("gold-evaluate")
def model_gold_evaluate(
    pre_path: Annotated[Path, typer.Option(help="Gold pre_decision_features Delta path")],
    pre_version: Annotated[int, typer.Option(min=0, help="Exact pre-decision Delta version")],
    post_path: Annotated[Path, typer.Option(help="Gold post_event_state_updates Delta path")],
    post_version: Annotated[int, typer.Option(min=0, help="Exact post-event Delta version")],
    labels_path: Annotated[Path, typer.Option(help="Silver labels Delta path")],
    labels_version: Annotated[int, typer.Option(min=0, help="Exact labels Delta version")],
    seed: Annotated[int, typer.Option(help="Deterministic random-split seed")] = 20_260_727,
    fixed_fpr: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.01,
) -> None:
    """Run the Gold-backed E1-E4 matrix; E2 uses post-event features as the leaky control."""

    from deltalake import DeltaTable

    from pit_fintech.models.paysim_gold import build_gold_experiment_table, evaluate_gold_matrix
    from pit_fintech.models.paysim_lightgbm import default_tracking_uri

    project_root = resolve_project_root(Path.cwd())

    def read_exact(path: Path, version: int):
        resolved = path if path.is_absolute() else project_root / path
        return DeltaTable(str(resolved), version=version).to_pyarrow_table()

    table = build_gold_experiment_table(
        pre_decision=read_exact(pre_path, pre_version),
        post_event=read_exact(post_path, post_version),
        labels=read_exact(labels_path, labels_version),
    )
    _, _, artifact_root = _gold_roots()
    results = evaluate_gold_matrix(
        table,
        seed=seed,
        fixed_fpr=fixed_fpr,
        mlflow_tracking_uri=default_tracking_uri(artifact_root),
    )
    result_table = Table(title="Gold E1-E4 evaluation")
    columns = ("ID", "Features", "Split", "Deployable", "PR-AUC", "ROC-AUC", "Recall", "Precision")
    numeric_columns = {"PR-AUC", "ROC-AUC", "Recall", "Precision"}
    for name in columns:
        result_table.add_column(name, justify="right" if name in numeric_columns else "left")
    for result in results:
        result_table.add_row(
            result.experiment_id,
            result.feature_set,
            result.split_policy,
            str(result.deployable),
            f"{result.test_pr_auc:.6f}",
            f"{result.test_roc_auc:.6f}",
            f"{result.test_recall:.6f}",
            f"{result.test_precision:.6f}",
        )
    console.print(result_table)
    console.print(f"Gold rows: {table.num_rows:,}")
    for result in results:
        console.print(f"{result.experiment_id} MLflow run: {result.mlflow_run_id}")


@model_app.command("promote-champion")
def model_promote_champion(
    run_id: Annotated[str, typer.Option(help="MLflow E4 Gold run id to promote")],
    registered_model_name: Annotated[
        str, typer.Option(help="MLflow registered model name")
    ] = "paysim-fraud-lightgbm",
    tracking_uri: Annotated[str | None, typer.Option(help="Optional MLflow tracking URI")] = None,
) -> None:
    """Register an eligible Gold E4 run and move the MLflow champion alias."""

    import mlflow

    from pit_fintech.models.paysim_lightgbm import default_tracking_uri
    from pit_fintech.serving.model_loader import promote_run_to_champion

    _, _, artifact_root = _gold_roots()
    resolved_tracking_uri = tracking_uri or default_tracking_uri(artifact_root)
    mlflow.set_tracking_uri(resolved_tracking_uri)
    run = mlflow.MlflowClient().get_run(run_id)
    if run.data.tags.get("experiment_id") != "E4" or run.data.tags.get("deployable") != "true":
        console.print("[red]Only a deployable Gold E4 run can become champion.[/]")
        raise typer.Exit(code=2)
    version = promote_run_to_champion(
        tracking_uri=resolved_tracking_uri,
        registered_model_name=registered_model_name,
        mlflow_run_id=run_id,
    )
    console.print(f"registered_model: {registered_model_name}")
    console.print(f"champion_version: {version}")
    console.print(f"champion_uri: models:/{registered_model_name}@champion")


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


@materialize_app.command("run")
def materialize_run(
    watermark: Annotated[
        int,
        typer.Option("--watermark", min=1, help="Gold post-event step to materialize up to"),
    ],
    store: Annotated[str, typer.Option("--store", help="Online store kind")] = "redis",
    uri: Annotated[
        str,
        typer.Option("--uri", help="Online store connection URI"),
    ] = "redis://127.0.0.1:6379/0",
    run_id: Annotated[
        str | None, typer.Option("--run-id", help="Materialization run identifier")
    ] = None,
) -> None:
    """Materialize Gold post-event state into the online store up to a watermark."""

    if store != "redis":
        console.print(f"[red]Unknown store: {store}. Use redis.[/]")
        raise typer.Exit(code=2)

    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY, PAYSIM_FEATURE_SERVICE_VERSION

    project_root, data_root, artifact_root = _gold_roots()
    resolved_run_id = run_id or (
        f"materialize-{watermark}-{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%f%z')}"
    )
    store_config = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=uri,
        feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
        entity=PAYSIM_ENTITY,
    )
    result = materialize_to_watermark(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        store=store_config,
        watermark_step=watermark,
        run_id=resolved_run_id,
    )
    table = Table(title="Materialization run")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", result.run_id)
    table.add_row("status", result.status)
    table.add_row("watermark_step", str(result.watermark_step))
    table.add_row("gold_post_event_version", str(result.gold_post_event_version))
    table.add_row("records_written", str(result.records_written))
    table.add_row("records_noop", str(result.records_noop))
    table.add_row("records_rejected", str(result.records_rejected))
    table.add_row("wall_seconds", f"{result.wall_seconds:.2f}")
    table.add_row("manifest", result.manifest_path)
    console.print(table)
    if result.status != "completed":
        raise typer.Exit(code=1)


@materialize_app.command("show")
def materialize_show(
    entity_id: Annotated[
        str | None, typer.Option("--entity-id", help="Entity to read back from the online store")
    ] = None,
    request_step: Annotated[
        int | None,
        typer.Option("--request-step", help="Step to evaluate freshness against"),
    ] = None,
    uri: Annotated[
        str,
        typer.Option("--uri", help="Online store connection URI"),
    ] = "redis://127.0.0.1:6379/0",
) -> None:
    """Read one entity's online feature state, or the current watermark."""

    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY, PAYSIM_FEATURE_SERVICE_VERSION

    store_config = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=uri,
        feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
        entity=PAYSIM_ENTITY,
    )

    if entity_id is None:
        watermark = read_watermark(store=store_config)
        if watermark is None:
            console.print("[yellow]No watermark set. Run materialize run first.[/]")
            raise typer.Exit(code=1)
        step, timestamp = watermark
        console.print(f"watermark_step: [cyan]{step}[/]")
        console.print(f"watermark_timestamp: {timestamp}")
        return

    if request_step is None:
        console.print("[red]--request-step is required together with --entity-id.[/]")
        raise typer.Exit(code=2)

    result = read_online_features(
        store=store_config, entity_id=entity_id, request_step=request_step
    )
    table = Table(title=f"Online features: {entity_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("status", result.status)
    table.add_row("staleness_steps", str(result.staleness_steps))
    table.add_row("read_latency_ms", f"{result.read_latency_ms:.3f}")
    for key, value in result.feature_values.items():
        table.add_row(key, str(value))
    console.print(table)


@parity_app.command("reconcile")
def parity_reconcile(
    uri: Annotated[
        str,
        typer.Option("--uri", help="Online store connection URI"),
    ] = "redis://127.0.0.1:6379/0",
    event_history: Annotated[
        Path | None,
        typer.Option("--event-history", help="Path to the served Event History JSONL"),
    ] = None,
) -> None:
    """Reconcile online aggregates against the offline DuckDB reference over the Event History.

    Asynchronous offline/online parity (ADR-009 as amended): the serving write path never runs the
    offline engine; run this command after traffic to compare each entity's online aggregate against
    the DuckDB post-event state over the served events. Emits a report and, when
    ``PIT_OTEL_ENDPOINT`` is set and OTel is installed, exports ``pit_parity_checked_total`` /
    ``pit_parity_mismatches_total`` to the collector.
    """

    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY, PAYSIM_FEATURE_SERVICE_VERSION
    from pit_fintech.serving.online_state import reconcile_parity

    telemetry = _configure_offline_observability("pit-fintech-parity")
    _, _, artifact_root = _gold_roots()
    store_config = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=uri,
        feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
        entity=PAYSIM_ENTITY,
    )
    result = reconcile_parity(
        store=store_config,
        artifact_root=artifact_root,
        event_history_path=event_history,
    )

    table = Table(title="Parity reconcile (online vs offline DuckDB)")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("checked_entities", str(result.checked_entities))
    table.add_row("field_mismatches", str(result.field_mismatches))
    table.add_row("missing_online", ", ".join(result.missing_online) or "-")
    table.add_row("passed", "yes" if result.passed else "no")
    console.print(table)
    for detail in result.details:
        # Escape Rich markup so a Windows path with backslashes is not mis-rendered.
        console.print(f"[yellow]{escape(detail)}[/]")

    # Best-effort OTel export; lifecycle logs were emitted by `reconcile_parity` above.
    if telemetry is not None:
        telemetry.record_parity_check(
            checked=result.checked_entities > 0, mismatches=result.field_mismatches
        )

    if not result.passed:
        raise typer.Exit(code=1)


@serving_app.command("up")
def serving_up(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Bind host for the scoring API (0.0.0.0 exposes /metrics so a remote "
            "Prometheus can scrape it over Tailscale); default from PIT_API_HOST",
        ),
    ] = get_settings().api_host,
    port: Annotated[
        int,
        typer.Option("--port", help="Bind port for the scoring API; default from PIT_API_PORT"),
    ] = get_settings().api_port,
    mlflow_run_id: Annotated[
        str | None,
        typer.Option("--mlflow-run-id", help="Optional MLflow run identity to pin at startup"),
    ] = None,
    mlflow_tracking_uri: Annotated[
        str | None,
        typer.Option(
            "--mlflow-tracking-uri",
            help="MLflow tracking URI to resolve the model through; defaults to the local "
            "SQLite backend (artifacts/mlflow/tracking.db)",
        ),
    ] = None,
    otel: Annotated[
        bool,
        typer.Option("--otel/--no-otel", help="Export OTLP traces/metrics + trace-correlated logs"),
    ] = False,
    otel_endpoint: Annotated[
        str | None,
        typer.Option(
            "--otel-endpoint",
            help="OTLP/HTTP collector base URL (e.g. http://host:4318); "
            "defaults to PIT_OTEL_ENDPOINT, then OTEL_EXPORTER_OTLP_ENDPOINT",
        ),
    ] = get_settings().otel_endpoint,
) -> None:
    """Start the FastAPI scoring service against the local Redis online store."""

    from pit_fintech.features.paysim_specs import PAYSIM_FEATURE_SERVICE_VERSION
    from pit_fintech.models.paysim_lightgbm import default_tracking_uri
    from pit_fintech.platform.logging_config import configure_logging

    _, _, artifact_root = _gold_roots()
    settings_kwargs: dict[str, object] = {
        "host": host,
        "port": port,
        "provider_kind": "redis",
        "online_store_uri": "redis://127.0.0.1:6379/0",
        "feast_repo_path": None,
        "mlflow_tracking_uri": (
            mlflow_tracking_uri
            if mlflow_tracking_uri is not None
            else default_tracking_uri(artifact_root)
        ),
        "registered_model_name": "paysim-fraud-lightgbm",
        "feature_service_version": PAYSIM_FEATURE_SERVICE_VERSION,
        "policy": FailurePolicy(),
        "log_json": True,
        "otel_enabled": otel,
        "otel_endpoint": otel_endpoint,
    }
    settings_fields = serving_runtime.ServingSettings.__dataclass_fields__
    if mlflow_run_id is not None and "mlflow_run_id" in settings_fields:
        settings_kwargs["mlflow_run_id"] = mlflow_run_id
    settings = serving_runtime.ServingSettings(**settings_kwargs)
    configure_logging(level=get_settings().log_level, json=settings.log_json)
    serving_runtime.run(settings=settings)


@serving_app.command("worker")
def serving_worker(
    host: Annotated[str, typer.Option("--host", help="Redis host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Redis port")] = 6379,
    db: Annotated[int, typer.Option("--db", help="Redis database")] = 0,
) -> None:
    """Run the pit-online-worker: consume score events and maintain the online store (ADR-010).

    This is the write-path consumer. It reads the Redis Stream in order, applies each event under
    the optimistic lock, and publishes the pre-decision result the waiting request polls. Run it as
    its own container (`pit-online-worker` in compose.yaml) or here in a terminal; `/score` needs it
    to be running.
    """

    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY, PAYSIM_FEATURE_SERVICE_VERSION
    from pit_fintech.materialization.materializer import OnlineStoreConfig
    from pit_fintech.materialization.records import OnlineStoreKind
    from pit_fintech.platform.logging_config import configure_logging
    from pit_fintech.serving.telemetry import configure_telemetry
    from pit_fintech.serving.worker import run_worker

    settings = get_settings()
    artifact_root = settings.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = Path.cwd() / artifact_root
    configure_logging(level=settings.log_level, json=True)
    telemetry = configure_telemetry(
        service_name="pit-fintech-online-worker",
        endpoint=settings.otel_endpoint,
        enabled=bool(settings.otel_endpoint),
    )
    store = OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=f"redis://{host}:{port}/{db}",
        feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
        entity=PAYSIM_ENTITY,
        host=host,
        port=port,
        db=db,
    )
    run_worker(
        store=store,
        feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
        telemetry=telemetry,
        artifact_root=artifact_root,
    )


if __name__ == "__main__":
    app()
