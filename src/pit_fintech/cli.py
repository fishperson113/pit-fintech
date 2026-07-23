"""Single command boundary used by Make, PowerShell, CI, and notebooks."""

from __future__ import annotations

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
    setup_instructions,
)
from pit_fintech.data.sample import PARQUET_PATH, build_sample_fixture, profile_sample_fixture
from pit_fintech.platform.doctor import collect_checks
from pit_fintech.platform.notebooks import verify_notebooks

app = typer.Typer(no_args_is_help=True, help="PIT Fintech local control plane")
data_app = typer.Typer(no_args_is_help=True, help="Dataset and fixture commands")
notebooks_app = typer.Typer(no_args_is_help=True, help="Notebook quality commands")
app.add_typer(data_app, name="data")
app.add_typer(notebooks_app, name="notebooks")
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
) -> None:
    """Build Bronze/Silver Delta tables after the temporal gate has passed."""

    if dataset != "sample":
        console.print("[red]Only the verified sample path is implemented in this milestone.[/]")
        raise typer.Exit(code=2)
    manifest = build_sample_lakehouse()
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


@data_app.command("lakehouse-history")
def data_lakehouse_history() -> None:
    """Inspect versioned Delta commits for implemented local tables."""

    history = lakehouse_history()
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
