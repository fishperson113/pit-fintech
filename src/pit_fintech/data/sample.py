"""Build the versioned synthetic temporal oracle without external credentials."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.contracts.manifests import DatasetFile, DatasetManifest
from pit_fintech.data.canonical import deduplicate_events, ordered_event_timestamps
from pit_fintech.features.reference import compute_feature_vectors

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = PROJECT_ROOT / "data" / "fixtures"
SOURCE_PATH = FIXTURE_DIR / "temporal_cases.jsonl"
PARQUET_PATH = FIXTURE_DIR / "temporal_cases.parquet"
EXPECTED_PATH = FIXTURE_DIR / "expected_features.json"
MANIFEST_PATH = PROJECT_ROOT / "artifacts" / "sample" / "dataset-manifest.json"
PROFILE_PATH = PROJECT_ROOT / "artifacts" / "sample" / "data-profile.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_events(path: Path = SOURCE_PATH) -> list[TemporalEvent]:
    events: list[TemporalEvent] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    events.append(TemporalEvent.model_validate_json(line))
                except Exception as exc:
                    raise ValueError(f"invalid fixture row at {path}:{line_number}") from exc
    return events


def load_parquet_events(path: Path = PARQUET_PATH) -> list[TemporalEvent]:
    table = pq.read_table(path)
    event_fields = set(TemporalEvent.model_fields)
    return [
        TemporalEvent.model_validate(
            {key: value for key, value in row.items() if key in event_fields}
        )
        for row in table.to_pylist()
    ]


def load_expected(path: Path = EXPECTED_PATH) -> dict[int, dict[str, int | float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(transaction_id): values for transaction_id, values in payload["vectors"].items()}


def _validate_expected(events: list[TemporalEvent]) -> None:
    actual = {row.transaction_id: row.values for row in compute_feature_vectors(events)}
    expected = load_expected()
    if actual.keys() != expected.keys():
        raise ValueError(
            f"fixture/expected transaction mismatch: {actual.keys()} != {expected.keys()}"
        )
    for transaction_id, expected_values in expected.items():
        actual_values = actual[transaction_id]
        for feature_name, expected_value in expected_values.items():
            actual_value = actual_values[feature_name]
            if isinstance(expected_value, float):
                if abs(float(actual_value) - expected_value) > 1e-9:
                    raise ValueError(
                        f"expected vector mismatch for {transaction_id}/{feature_name}: "
                        f"{actual_value} != {expected_value}"
                    )
            elif actual_value != expected_value:
                raise ValueError(
                    f"expected vector mismatch for {transaction_id}/{feature_name}: "
                    f"{actual_value} != {expected_value}"
                )


def _parquet_rows(events: list[TemporalEvent]) -> list[dict[str, Any]]:
    ordered = ordered_event_timestamps(events)
    rows: list[dict[str, Any]] = []
    for event in events:
        row = event.model_dump(mode="python")
        row["ordered_event_timestamp"] = ordered[event.transaction_id]
        row["source_row_hash"] = hashlib.sha256(event.model_dump_json().encode("utf-8")).hexdigest()
        rows.append(row)
    return rows


def _current_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNCOMMITTED"


def build_sample_fixture() -> DatasetManifest:
    """Validate hand-calculated vectors, write Parquet, and emit a runtime manifest."""

    events = load_source_events()
    _validate_expected(events)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(_parquet_rows(events)), PARQUET_PATH, compression="zstd")

    source_checksum = sha256_file(SOURCE_PATH)
    snapshot_id = f"synthetic-temporal-v1:{source_checksum[:16]}"
    files = tuple(
        DatasetFile(
            path=str(path.relative_to(PROJECT_ROOT)),
            bytes=path.stat().st_size,
            sha256=sha256_file(path),
        )
        for path in (SOURCE_PATH, PARQUET_PATH, EXPECTED_PATH)
    )
    manifest = DatasetManifest(
        dataset="synthetic-temporal-oracle",
        dataset_snapshot_id=snapshot_id,
        source="committed hand-calculated fixture",
        files=files,
        source_rows=len(events),
        canonical_rows=len(deduplicate_events(events)),
        code_commit=_current_commit(),
    )
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def profile_sample_fixture() -> dict[str, Any]:
    """Produce a decision-oriented profile from the canonical synthetic events."""

    build_sample_fixture()
    source_events = load_parquet_events()
    events = deduplicate_events(source_events)
    entity_counts: dict[str, int] = {}
    timestamp_counts: dict[str, int] = {}
    for event in events:
        entity_counts[event.card_entity_id] = entity_counts.get(event.card_entity_id, 0) + 1
        timestamp = event.event_timestamp.isoformat()
        timestamp_counts[timestamp] = timestamp_counts.get(timestamp, 0) + 1

    labels = [event.label_is_fraud for event in events if event.label_is_fraud is not None]
    profile: dict[str, Any] = {
        "source_rows": len(source_events),
        "canonical_rows": len(events),
        "exact_duplicate_rows": len(source_events) - len(events),
        "entities": len(entity_counts),
        "events_per_entity": dict(sorted(entity_counts.items())),
        "same_timestamp_groups": sum(count > 1 for count in timestamp_counts.values()),
        "late_arrival_rows": sum(
            event.created_timestamp > event.event_timestamp for event in events
        ),
        "fraud_rate": sum(labels) / len(labels) if labels else None,
        "event_time_min": min(event.event_timestamp for event in events).isoformat(),
        "event_time_max": max(event.event_timestamp for event in events).isoformat(),
    }
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return profile
