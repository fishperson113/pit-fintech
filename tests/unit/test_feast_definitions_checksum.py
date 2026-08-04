"""What the definitions checksum is, and is not, sensitive to (guide §3.3.1).

These run without Feast installed. `platform/feast_registry.py` reads its inputs by attribute, so
the properties that matter -- field order is significant, declaration order is not, a repo-relative
source path is machine-independent -- can be pinned against stubs shaped like the Feast objects,
and stay pinned in the environments where the optional `feast` group is absent. The lane that runs
the same function against real Feast objects is `tests/integration/test_feast_registry_g1.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pit_fintech.platform.feast_registry import (
    FEAST_DEFINITIONS_CHECKSUM_POLICY_VERSION,
    feast_definitions_checksum,
    feast_definitions_payload,
)


@dataclass(frozen=True)
class _ValueType:
    name: str


@dataclass(frozen=True)
class _Field:
    name: str
    dtype: str


@dataclass(frozen=True)
class FileSource:
    name: str
    path: str
    timestamp_field: str
    created_timestamp_column: str


@dataclass(frozen=True)
class _Entity:
    name: str
    join_key: str
    value_type: _ValueType
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _FeatureView:
    name: str
    entities: list[str]
    features: list[_Field]
    batch_source: FileSource
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Projection:
    name: str
    features: list[_Field]


@dataclass(frozen=True)
class _FeatureService:
    name: str
    feature_view_projections: list[_Projection]
    tags: dict[str, str] = field(default_factory=dict)


# The real repo root, so the relative-path canonicalization is exercised the same way the
# integration lane exercises it. The files underneath need not exist: `_canonical_source_path`
# resolves non-strictly and only compares path shapes.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _field(name: str, dtype: str) -> _Field:
    return _Field(name=name, dtype=dtype)


def _fields() -> list[_Field]:
    return [_field("current_amount", "Float64"), _field("pit_prior_count_1h", "Int64")]


def _source() -> FileSource:
    return FileSource(
        name="paysim_pre_decision_features",
        path=str(PROJECT_ROOT / "data" / "fixtures" / "paysim_feature_table.parquet"),
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    )


def _definitions(
    *,
    fields: list[_Field] | None = None,
    service_name: str = "paysim-fraud-scoring-v2",
    source: FileSource | None = None,
) -> dict[str, tuple]:
    resolved = _fields() if fields is None else fields
    view = _FeatureView(
        name="paysim_fraud_recipient_v2",
        entities=["destination_entity_id"],
        features=resolved,
        batch_source=source or _source(),
        tags={"definition_version": "paysim-fraud-recipient-v2"},
    )
    entity = _Entity(
        name="destination_entity_id",
        join_key="destination_entity_id",
        value_type=_ValueType("STRING"),
    )
    service = _FeatureService(
        name=service_name,
        feature_view_projections=[_Projection(name=view.name, features=resolved)],
        tags={"feature_service_version": service_name},
    )
    return {"entities": (entity,), "feature_views": (view,), "feature_services": (service,)}


def _checksum(**overrides) -> str:
    return feast_definitions_checksum(**_definitions(**overrides), project_root=PROJECT_ROOT)


def test_checksum_is_stable_for_the_same_definitions() -> None:
    assert _checksum() == _checksum()


def test_field_order_changes_the_checksum() -> None:
    """Field order is part of the frozen contract, so reordering must be a different identity."""

    reordered = list(reversed(_fields()))
    assert {f.name for f in reordered} == {f.name for f in _fields()}
    assert _checksum(fields=reordered) != _checksum()


def test_dtype_changes_the_checksum() -> None:
    retyped = [_field("current_amount", "Int64"), _field("pit_prior_count_1h", "Int64")]
    assert _checksum(fields=retyped) != _checksum()


def test_service_name_changes_the_checksum() -> None:
    assert _checksum(service_name="paysim-fraud-scoring-v3") != _checksum()


def test_repointing_the_source_changes_the_checksum() -> None:
    """The `FileSource` is part of the definition; swapping the table underneath is not a no-op."""

    elsewhere = FileSource(
        name="paysim_pre_decision_features",
        path=str(PROJECT_ROOT / "data" / "fixtures" / "paysim_temporal_cases.parquet"),
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    )
    assert _checksum(source=elsewhere) != _checksum()


def test_timestamp_columns_change_the_checksum() -> None:
    swapped = FileSource(
        name="paysim_pre_decision_features",
        path=_source().path,
        timestamp_field="created_timestamp",
        created_timestamp_column="event_timestamp",
    )
    assert _checksum(source=swapped) != _checksum()


def test_declaration_order_of_objects_does_not_change_the_checksum() -> None:
    """A registry hands objects back in its own order; that is not a definition change."""

    definitions = _definitions()
    second_view = _FeatureView(
        name="another_view",
        entities=["destination_entity_id"],
        features=_fields(),
        batch_source=_source(),
    )
    views = (*definitions["feature_views"], second_view)
    forward = feast_definitions_checksum(
        entities=definitions["entities"],
        feature_views=views,
        feature_services=definitions["feature_services"],
        project_root=PROJECT_ROOT,
    )
    reversed_order = feast_definitions_checksum(
        entities=definitions["entities"],
        feature_views=tuple(reversed(views)),
        feature_services=definitions["feature_services"],
        project_root=PROJECT_ROOT,
    )
    assert forward == reversed_order
    assert forward != _checksum()


def test_source_path_is_canonicalized_relative_to_the_project_root() -> None:
    """Two checkouts of the same repo must agree, so the absolute path may not reach the digest."""

    payload = feast_definitions_payload(**_definitions(), project_root=PROJECT_ROOT)
    assert payload["policy_version"] == FEAST_DEFINITIONS_CHECKSUM_POLICY_VERSION
    assert (
        payload["feature_views"][0]["source"]["path"]
        == "data/fixtures/paysim_feature_table.parquet"
    )
    assert payload["feature_views"][0]["source"]["type"] == "FileSource"
    assert [entry["name"] for entry in payload["feature_views"][0]["fields"]] == [
        "current_amount",
        "pit_prior_count_1h",
    ]


def test_payload_excludes_the_attributes_that_do_not_survive_an_apply() -> None:
    """`ttl` and `entity_columns` are normalized by `apply`; hashing them reports false drift."""

    payload = feast_definitions_payload(**_definitions(), project_root=PROJECT_ROOT)
    view_payload = payload["feature_views"][0]
    assert "ttl" not in view_payload
    assert "entity_columns" not in view_payload
