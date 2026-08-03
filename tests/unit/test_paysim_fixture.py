"""CLI-level guard: the PaySim fixture-build command fails loudly without a manifest.

Mirrors ``test_paysim_training.py::test_training_cli_requires_a_lakehouse_manifest_before_loading_
model_dependencies``: ``pit_fintech.data.paysim_fixture.build_paysim_temporal_fixture`` needs a real
Silver Delta table that CI cannot produce, so this test does not build one. It instead pins down the
one behavior that must hold everywhere: running the command with no PaySim lakehouse manifest on
disk exits 2 with an actionable message, so the CLI wiring around the fixture builder stays under
test even though its real-Silver success path is only exercised on a machine that has one (see
``tests/integration/test_paysim_fixture.py``).
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pit_fintech.cli import app


def test_build_fixture_cli_requires_a_lakehouse_manifest_before_reading_silver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["data", "build-fixture"])

    assert result.exit_code == 2
    assert "No PaySim application lakehouse manifest" in result.stdout


def test_build_fixture_cli_rejects_non_paysim_dataset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["data", "build-fixture", "--dataset", "sample"])

    assert result.exit_code == 2
    assert "Only the PaySim temporal fixture builder is implemented" in result.stdout
