"""PaySim dataset discovery, validation, and decision-oriented profiling."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from pit_fintech.config import get_settings
from pit_fintech.contracts.manifests import DatasetFile, DatasetSnapshotManifest

DATASET_SLUG = "ealaxi/paysim1"
DATASET_URL = "https://www.kaggle.com/datasets/ealaxi/paysim1"
DEFAULT_FILENAME = "PS_20174392719_1491204439457_log.csv"

EXPECTED_COLUMNS = (
    "step",
    "type",
    "amount",
    "nameOrig",
    "oldbalanceOrg",
    "newbalanceOrig",
    "nameDest",
    "oldbalanceDest",
    "newbalanceDest",
    "isFraud",
    "isFlaggedFraud",
)

REQUEST_TIME_COLUMNS = ("step", "type", "amount", "nameOrig", "nameDest")
BALANCE_COLUMNS = (
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
)
LABEL_COLUMNS = ("isFraud",)
POLICY_OUTPUT_COLUMNS = ("isFlaggedFraud",)


@dataclass(frozen=True)
class PaySimSnapshot:
    path: Path
    size_bytes: int
    sha256: str
    columns: tuple[str, ...]

    @property
    def dataset_snapshot_id(self) -> str:
        return f"paysim1:{self.sha256[:16]}"


def resolve_project_root(start: Path | None = None) -> Path:
    """Find the repository root even when a notebook kernel starts in ``notebooks/``."""

    candidate = (start or Path.cwd()).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return candidate


def find_paysim_csv(
    project_root: Path | None = None,
    explicit_path: Path | None = None,
) -> Path | None:
    """Resolve PaySim without silently substituting a fixture or another dataset."""

    project_root = resolve_project_root(project_root)
    if explicit_path is not None:
        candidate = explicit_path.expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"PaySim CSV does not exist: {candidate}")
        return candidate

    environment_path = os.getenv("PAYSIM_CSV")
    configured_path = get_settings().paysim_csv
    candidates = []
    if environment_path:
        candidates.append(Path(environment_path).expanduser())
    if configured_path:
        candidates.append(configured_path.expanduser())
    candidates.extend(
        [
            project_root / "data" / "raw" / "paysim" / DEFAULT_FILENAME,
            project_root / "data" / "raw" / DEFAULT_FILENAME,
        ]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def setup_instructions(project_root: Path | None = None) -> str:
    project_root = resolve_project_root(project_root)
    destination = project_root / "data" / "raw" / "paysim"
    return "\n".join(
        [
            "PaySim CSV was not found. No synthetic fallback is used.",
            f"Dataset: {DATASET_URL}",
            f"Expected default path: {destination / DEFAULT_FILENAME}",
            "Kaggle CLI option:",
            f"  kaggle datasets download -d {DATASET_SLUG} -p {destination} --unzip",
            "Alternative: set PAYSIM_CSV in the shell or PIT_PAYSIM_CSV in .env.",
        ]
    )


def read_header(csv_path: Path) -> tuple[str, ...]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            return tuple(next(reader))
        except StopIteration as exc:
            raise ValueError(f"PaySim CSV is empty: {csv_path}") from exc


def validate_paysim_csv(csv_path: Path) -> tuple[str, ...]:
    columns = read_header(csv_path)
    if columns != EXPECTED_COLUMNS:
        raise ValueError(
            "Unexpected PaySim schema. "
            f"Expected {EXPECTED_COLUMNS}, received {columns} from {csv_path}"
        )
    return columns


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_snapshot(csv_path: Path) -> PaySimSnapshot:
    columns = validate_paysim_csv(csv_path)
    return PaySimSnapshot(
        path=csv_path.resolve(),
        size_bytes=csv_path.stat().st_size,
        sha256=sha256_file(csv_path),
        columns=columns,
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def connect_paysim(csv_path: Path) -> duckdb.DuckDBPyConnection:
    """Create a lazy PaySim view with a provisional CSV-row tie-break column."""

    validate_paysim_csv(csv_path)
    connection = duckdb.connect()
    connection.execute("SET preserve_insertion_order = true")
    csv_literal = _sql_string(csv_path.resolve().as_posix())
    connection.execute(
        f"""
        CREATE VIEW paysim AS
        SELECT
            row_number() OVER ()::BIGINT AS source_row_number,
            step::BIGINT AS step,
            type::VARCHAR AS type,
            amount::DOUBLE AS amount,
            nameOrig::VARCHAR AS nameOrig,
            oldbalanceOrg::DOUBLE AS oldbalanceOrg,
            newbalanceOrig::DOUBLE AS newbalanceOrig,
            nameDest::VARCHAR AS nameDest,
            oldbalanceDest::DOUBLE AS oldbalanceDest,
            newbalanceDest::DOUBLE AS newbalanceDest,
            isFraud::INTEGER AS isFraud,
            isFlaggedFraud::INTEGER AS isFlaggedFraud
        FROM read_csv_auto({csv_literal}, header = true)
        """
    )
    return connection


def profile_paysim(csv_path: Path, include_checksum: bool = False) -> dict[str, Any]:
    """Return the minimum machine-readable profile needed by the dataset gate."""

    connection = connect_paysim(csv_path)
    try:
        row = connection.execute(
            """
            SELECT
                count(*)::BIGINT AS rows,
                min(step)::BIGINT AS min_step,
                max(step)::BIGINT AS max_step,
                count(DISTINCT nameOrig)::BIGINT AS origin_entities,
                count(DISTINCT nameDest)::BIGINT AS destination_entities,
                sum(isFraud)::BIGINT AS fraud_rows,
                avg(isFraud)::DOUBLE AS fraud_rate,
                sum(isFlaggedFraud)::BIGINT AS flagged_rows
            FROM paysim
            """
        ).fetchone()
        if row is None:  # pragma: no cover - aggregate always returns one row
            raise RuntimeError("PaySim profile query returned no result")
        keys = (
            "rows",
            "min_step",
            "max_step",
            "origin_entities",
            "destination_entities",
            "fraud_rows",
            "fraud_rate",
            "flagged_rows",
        )
        profile = dict(zip(keys, row, strict=True))
        profile.update(
            {
                "path": str(csv_path.resolve()),
                "size_bytes": csv_path.stat().st_size,
                "columns": list(EXPECTED_COLUMNS),
            }
        )
        if include_checksum:
            sha256 = sha256_file(csv_path)
            profile["sha256"] = sha256
            profile["dataset_snapshot_id"] = f"paysim1:{sha256[:16]}"
        return profile
    finally:
        connection.close()


def _current_commit(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNCOMMITTED"


def _manifest_file_path(csv_path: Path, project_root: Path) -> str:
    resolved = csv_path.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def create_paysim_snapshot(
    csv_path: Path,
    *,
    project_root: Path,
    artifact_root: Path,
) -> tuple[DatasetSnapshotManifest, Path]:
    """Hash and profile the raw CSV, then atomically persist its snapshot manifest."""

    snapshot = inspect_snapshot(csv_path)
    profile = profile_paysim(csv_path)
    manifest = DatasetSnapshotManifest(
        dataset="paysim1",
        dataset_snapshot_id=snapshot.dataset_snapshot_id,
        source=DATASET_URL,
        file=DatasetFile(
            path=_manifest_file_path(csv_path, project_root),
            bytes=snapshot.size_bytes,
            sha256=snapshot.sha256,
        ),
        schema_columns=snapshot.columns,
        source_rows=int(profile["rows"]),
        step_min=int(profile["min_step"]),
        step_max=int(profile["max_step"]),
        code_commit=_current_commit(project_root),
    )

    manifest_path = (
        artifact_root.resolve()
        / "datasets"
        / "paysim1"
        / snapshot.sha256[:16]
        / "snapshot-manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)
    return manifest, manifest_path
