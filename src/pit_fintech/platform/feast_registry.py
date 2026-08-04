"""Canonical checksum over Feast definitions, never over the registry blob (guide §3.3.1).

Guide §3.3 binds `feast plan/apply -> registry checksum -> feature_service_version`, and guide §3.4
makes "`feast apply` idempotent" a G1 acceptance criterion. M030 Finding 2 measured why that
checksum cannot be taken over the registry artifact: a no-op second `apply` moves both the registry
file digest and the serialized-proto digest, because the registry proto carries `last_updated`
timestamps. A gate built on the blob would fail permanently for a reason that has nothing to do
with the definitions, and the natural response -- relaxing the criterion -- would destroy a real
gate.

So the identity is canonicalized from the **definitions**: entity names and join keys, the feature
view name, its ordered fields with their dtypes, the source's `timestamp_field` and
`created_timestamp_column`, the feature service name, and the two frozen version strings carried as
tags. Serialization follows `paysim_feature_contract_checksum` in `features/paysim_specs.py`
(compact JSON, `sort_keys=True`, SHA-256) so a reader meets one hashing convention, not two. Only
mapping *keys* are sorted; every field list stays in declaration order, because field order is part
of the contract (`PAYSIM_MODEL_FEATURE_ORDER`).

This module lives in `platform/` rather than in `features/` for two reasons. `features/` holds the
frozen correctness contract, and `pyproject.toml` deliberately keeps Feast out of the main
dependencies so a Feast resolution failure cannot break `test-temporal`/`test-unit`; a checksum
module that Feast objects flow into belongs on the platform side of that line. And the function it
is closest to in spirit is `platform/lineage.py: component_fingerprint` -- a versioned,
ordered-input identity used as pipeline evidence, not a feature semantic.

Nothing here imports Feast at runtime: the payload readers are duck-typed, so `src/` stays
importable in an environment without Feast and the function can be handed registry-materialized
objects or module-level ones interchangeably.

Two attributes are **deliberately excluded** because they are not stable across the
definitions-module -> `apply` -> registry round trip (measured on Feast 0.65.0), and including
them would make the checksum report a false difference:

- `FeatureView.ttl`: declared `None` in `feature_repo/definitions.py`, read back as
  `timedelta(0)` after `apply`.
- `FeatureView.entity_columns`: empty on the module-level object, populated with the join key
  after `apply`.

`FeatureView.version` (a Feast 0.65 internal, `"latest"` here) is excluded too: it is the library's
own object versioning, not part of the ADR-003/ADR-006 contract this checksum identifies.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - annotations only; this module never imports Feast at runtime
    from feast import Entity, FeatureService, FeatureView
    from feast.data_source import DataSource
    from feast.field import Field

FEAST_DEFINITIONS_CHECKSUM_POLICY_VERSION: Final = "feast-definitions-checksum-v1"


def _canonical_source_path(path: str, project_root: Path | None) -> str:
    """Render a source path as a repo-relative POSIX string so identity is not machine identity."""

    if not path:
        return ""
    if project_root is None:
        return path.replace("\\", "/")
    try:
        return (Path(path).resolve().relative_to(project_root.resolve())).as_posix()
    except ValueError:
        return path.replace("\\", "/")


def _field_payload(field: Field) -> dict[str, str]:
    return {"name": field.name, "dtype": str(field.dtype)}


def _source_payload(source: DataSource, project_root: Path | None) -> dict[str, Any]:
    return {
        "name": source.name,
        "type": type(source).__name__,
        "path": _canonical_source_path(str(getattr(source, "path", "")), project_root),
        "timestamp_field": source.timestamp_field,
        "created_timestamp_column": source.created_timestamp_column,
    }


def _entity_payload(entity: Entity) -> dict[str, Any]:
    return {
        "name": entity.name,
        # `join_keys=[...]` is a constructor argument only; Feast 0.65 stores the single resolved
        # key as `join_key`, and reading the constructor name back raises `AttributeError`.
        "join_key": entity.join_key,
        "value_type": entity.value_type.name,
        "tags": dict(entity.tags),
    }


def _feature_view_payload(view: FeatureView, project_root: Path | None) -> dict[str, Any]:
    # `view.features` is the declaration-ordered list. `view.schema` is NOT usable here: the
    # property returns `list(set(entity_columns + features))` (`feast/feature_view.py:430`), so it
    # loses order entirely -- measured, and the exact reason a checksum built on it would be
    # nondeterministic across processes.
    return {
        "name": view.name,
        "entities": list(view.entities),
        "fields": [_field_payload(field) for field in view.features],
        "source": _source_payload(view.batch_source, project_root),
        "tags": dict(view.tags),
    }


def _feature_service_payload(service: FeatureService) -> dict[str, Any]:
    return {
        "name": service.name,
        "tags": dict(service.tags),
        "projections": [
            {
                "feature_view_name": projection.name,
                "fields": [_field_payload(field) for field in projection.features],
            }
            for projection in service.feature_view_projections
        ],
    }


def feast_definitions_payload(
    *,
    entities: tuple[Entity, ...],
    feature_views: tuple[FeatureView, ...],
    feature_services: tuple[FeatureService, ...],
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Canonicalize Feast definitions into the exact structure the checksum is taken over.

    Returned separately from the digest so a failing comparison can show *what* moved instead of
    only that two hex strings differ. Objects are sorted by name because the order they happen to
    be declared in, or read back from a registry in, is not part of the contract; the field lists
    inside them are left alone because their order is.
    """

    return {
        "policy_version": FEAST_DEFINITIONS_CHECKSUM_POLICY_VERSION,
        "entities": [_entity_payload(entity) for entity in sorted(entities, key=lambda e: e.name)],
        "feature_views": [
            _feature_view_payload(view, project_root)
            for view in sorted(feature_views, key=lambda v: v.name)
        ],
        "feature_services": [
            _feature_service_payload(service)
            for service in sorted(feature_services, key=lambda s: s.name)
        ],
    }


def feast_definitions_checksum(
    *,
    entities: tuple[Entity, ...],
    feature_views: tuple[FeatureView, ...],
    feature_services: tuple[FeatureService, ...],
    project_root: Path | None = None,
) -> str:
    """Hash the canonical definitions; stable across repeated `feast apply` runs by construction."""

    payload = feast_definitions_payload(
        entities=entities,
        feature_views=feature_views,
        feature_services=feature_services,
        project_root=project_root,
    )
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
