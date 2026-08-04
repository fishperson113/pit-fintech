"""Real Feast objects for `paysim-fraud-recipient-v2` (ADR-006; guide §3.2-3.2.1).

Entity, `FileSource`, `FeatureView`, `FeatureService` -- the objects `feast apply` discovers when
run from this directory. Every name, dtype and version string below is imported straight from the
frozen application contract (`src/pit_fintech/features/paysim_specs.py`), never re-typed, so this
module cannot drift from the contract it wires up. Imported from `pit_fintech.features.paysim_specs`
directly rather than via `feature_repo/feature_specs.py`'s re-export: `feast apply` imports each
top-level `.py` file in this directory with only this directory on `sys.path` (confirmed
empirically), so `from feature_repo... import ...` is not resolvable from inside `feature_repo/`
the way it is from the installed `pit_fintech` package -- `feature_repo` is never itself an
importable package from its own directory.

Two frozen strings appear here and must stay distinct (ADR-006 decision 2):
`PAYSIM_FEATURE_DEFINITION_VERSION` ("paysim-fraud-recipient-v2", the feature contract) and
`PAYSIM_FEATURE_SERVICE_VERSION` ("paysim-fraud-scoring-v2", the serving contract). The
`FeatureView` name is the definition version with dashes replaced by underscores (Feast requires
an `isidentifier()`-safe name -- confirmed empirically: a dashed `FeatureView` name breaks the
SQLite online-store table name at `apply()` time with `OperationalError near "-"`). The
`FeatureService` name is the service version verbatim: `FeatureService` names are not used as SQL
identifiers, and an apply with a dashed `FeatureService` name and an underscored `FeatureView`
name was confirmed to succeed. Both frozen strings are also carried as `tags` on their respective
object, so the literal contract strings are visible in the registry even though only one of them
had to be reshaped for Feast's naming rule.

`FileSource` points at `data/fixtures/paysim_feature_table.parquet` -- the **precomputed**
pre-decision feature table (M030 Finding 1: Feast does not compute window aggregates,
`feast/aggregation/__init__.py:17`, "not yet supported"; confirmed absent from
`feast/infra/offline_stores/duckdb.py` and `file_source.py`). That table is the SQL engine's
output (`features/paysim_recipient.py`, not the Python oracle), one row per cutoff, columns
`destination_entity_id, event_timestamp, created_timestamp, <12 contract fields>,
source_row_number` (`src/pit_fintech/data/paysim_fixture.py: PAYSIM_FEATURE_TABLE_COLUMNS`). This
module does not build that table and does not assume it exists on disk.

Deliberately narrower than guide §3.2: no `PushSource` is defined here. The guide's `PushSource`
wraps the `FileSource` for the online-write path fed by the replay/materializer (T5, not yet
built); the locked T1 scope for this file is the offline/historical retrieval path (G1's first
criterion), so `FeatureView` reads the `FileSource` directly. Adding the `PushSource` layer is
next-step work, not a correction.

Also deliberately narrower than guide §3.2's last bullet: the three `request_available` fields
(`current_amount`, `event_step`, `transaction_type_transfer`) are served here as ordinary batch
fields from the precomputed table, the same as the nine `historical_only` fields, because that is
what the precomputed table actually contains (`PAYSIM_FEATURE_TABLE_COLUMNS` carries all twelve).
Splitting request-time computation into an `OnDemandFeatureView` is T7 (FastAPI scoring) scope.
"""

from __future__ import annotations

from pathlib import Path

from feast import Entity, FeatureService, FeatureView, Field, FileSource
from feast.types import Float64, Int64
from feast.value_type import ValueType

from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SERVICE_VERSION,
    PAYSIM_FEATURE_SPECS,
    PAYSIM_MODEL_FEATURE_ORDER,
)

REPO_ROOT: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = REPO_ROOT.parent
# HOP DONG voi agent T1a: data/fixtures/paysim_feature_table.parquet. Resolved absolute so
# retrieval works regardless of the working directory `feast apply`/`FeatureStore` is invoked
# from -- `feature_store.yaml`'s own paths are relative to this directory, but `FileSource.path`
# is not re-resolved against it by Feast, so a relative value here would be CWD-dependent.
FEATURE_TABLE_PATH: Path = PROJECT_ROOT / "data" / "fixtures" / "paysim_feature_table.parquet"

_DTYPE_BY_FEATURE_NAME = {
    spec.name: (Int64 if spec.dtype == "int64" else Float64) for spec in PAYSIM_FEATURE_SPECS
}

destination_entity = Entity(
    name=PAYSIM_ENTITY,
    join_keys=[PAYSIM_ENTITY],
    value_type=ValueType.STRING,
)

paysim_pre_decision_features_source = FileSource(
    name="paysim_pre_decision_features",
    path=str(FEATURE_TABLE_PATH),
    timestamp_field="event_timestamp",
    created_timestamp_column="created_timestamp",
)

paysim_fraud_recipient_v2 = FeatureView(
    name=PAYSIM_FEATURE_DEFINITION_VERSION.replace("-", "_"),
    entities=[destination_entity],
    schema=[
        Field(name=name, dtype=_DTYPE_BY_FEATURE_NAME[name]) for name in PAYSIM_MODEL_FEATURE_ORDER
    ],
    source=paysim_pre_decision_features_source,
    ttl=None,
    tags={"definition_version": PAYSIM_FEATURE_DEFINITION_VERSION},
)

paysim_fraud_scoring_v2 = FeatureService(
    name=PAYSIM_FEATURE_SERVICE_VERSION,
    features=[paysim_fraud_recipient_v2],
    tags={"feature_service_version": PAYSIM_FEATURE_SERVICE_VERSION},
)
