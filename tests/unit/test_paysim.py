from __future__ import annotations

from pathlib import Path

import pytest

from pit_fintech.data.paysim import (
    DEFAULT_FILENAME,
    EXPECTED_COLUMNS,
    create_paysim_snapshot,
    find_paysim_csv,
    inspect_snapshot,
    profile_paysim,
    resolve_project_root,
    validate_paysim_csv,
)


def write_paysim_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        ",".join(EXPECTED_COLUMNS)
        + "\n"
        + "1,PAYMENT,10.0,C1,100.0,90.0,M1,0.0,0.0,0,0\n"
        + "2,TRANSFER,200000.0,C1,90.0,90.0,C2,0.0,0.0,1,1\n",
        encoding="utf-8",
    )


def test_find_paysim_csv_uses_default_project_location(tmp_path: Path) -> None:
    csv_path = tmp_path / "data" / "raw" / "paysim" / DEFAULT_FILENAME
    write_paysim_csv(csv_path)

    assert find_paysim_csv(tmp_path) == csv_path.resolve()


def test_find_paysim_csv_resolves_root_from_notebooks_directory(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    notebooks_dir = tmp_path / "notebooks"
    notebooks_dir.mkdir()
    csv_path = tmp_path / "data" / "raw" / DEFAULT_FILENAME
    write_paysim_csv(csv_path)

    assert resolve_project_root(notebooks_dir) == tmp_path.resolve()
    assert find_paysim_csv(notebooks_dir) == csv_path.resolve()


def test_validate_paysim_csv_rejects_wrong_schema(tmp_path: Path) -> None:
    csv_path = tmp_path / "wrong.csv"
    csv_path.write_text("step,type,amount\n1,PAYMENT,10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unexpected PaySim schema"):
        validate_paysim_csv(csv_path)


def test_snapshot_and_profile_are_deterministic(tmp_path: Path) -> None:
    csv_path = tmp_path / "paysim.csv"
    write_paysim_csv(csv_path)

    snapshot = inspect_snapshot(csv_path)
    profile = profile_paysim(csv_path, include_checksum=True)

    assert snapshot.dataset_snapshot_id == profile["dataset_snapshot_id"]
    assert profile["rows"] == 2
    assert profile["min_step"] == 1
    assert profile["max_step"] == 2
    assert profile["origin_entities"] == 1
    assert profile["destination_entities"] == 2
    assert profile["fraud_rows"] == 1
    assert profile["fraud_rate"] == 0.5
    assert profile["flagged_rows"] == 1


def test_create_snapshot_persists_an_idempotent_manifest(tmp_path: Path) -> None:
    csv_path = tmp_path / "data" / "raw" / "paysim" / DEFAULT_FILENAME
    artifact_root = tmp_path / "artifacts"
    write_paysim_csv(csv_path)

    first_manifest, manifest_path = create_paysim_snapshot(
        csv_path,
        project_root=tmp_path,
        artifact_root=artifact_root,
    )
    first_content = manifest_path.read_text(encoding="utf-8")
    second_manifest, second_path = create_paysim_snapshot(
        csv_path,
        project_root=tmp_path,
        artifact_root=artifact_root,
    )

    assert first_manifest == second_manifest
    assert manifest_path == second_path
    assert manifest_path.read_text(encoding="utf-8") == first_content
    assert first_manifest.file.path == f"data/raw/paysim/{DEFAULT_FILENAME}"
    assert first_manifest.source_rows == 2
    assert first_manifest.step_min == 1
    assert first_manifest.step_max == 2
