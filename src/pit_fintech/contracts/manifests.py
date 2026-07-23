"""Machine-readable lineage contracts shared by future pipeline stages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DatasetFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    bytes: int
    sha256: str


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    dataset_snapshot_id: str
    source: str
    files: tuple[DatasetFile, ...]
    source_rows: int
    canonical_rows: int
    code_commit: str


class DatasetSnapshotManifest(BaseModel):
    """Immutable identity and minimum profile for a raw application dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    dataset_snapshot_id: str
    source: str
    file: DatasetFile
    schema_columns: tuple[str, ...]
    source_rows: int
    step_min: int
    step_max: int
    code_commit: str


class DeltaTableSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: Literal["bronze", "silver"]
    table: str
    path: str
    version: int
    rows: int
    schema_checksum: str
    logical_checksum: str


class LakehouseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_snapshot_id: str
    code_commit: str
    tables: tuple[DeltaTableSnapshot, ...]


class BackfillManifest(BaseModel):
    """Schema reserved for Sprint 2; no backfill state machine is claimed yet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    status: Literal["planned", "running", "validated", "committed", "failed"]
    dataset_snapshot_id: str
    entity_definition_version: str
    feature_definition_version: str
    code_commit: str
    cutoff_start: datetime
    cutoff_end: datetime
    source_checksum: str
    output_checksum: str | None = None
