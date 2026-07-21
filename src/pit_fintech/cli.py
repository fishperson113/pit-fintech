"""Single command boundary used by Make, PowerShell, CI, and notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pit_fintech.data.build_lakehouse import build_sample_lakehouse, lakehouse_history
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
) -> None:
    """Generate a decision-oriented profile for an implemented dataset path."""

    if dataset != "sample":
        console.print("[red]Full-data profiling is planned after data access is verified.[/]")
        raise typer.Exit(code=2)
    profile = profile_sample_fixture()
    table = Table(title="Synthetic fixture profile")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in profile.items():
        table.add_row(key, str(value))
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
