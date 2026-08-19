"""The G1 acceptance lane for Sprint 2 T1 (guide `sprint-2-implementation-guide.md` §3.4).

Guide §3.4 states three acceptance criteria for T1, and this module measures all three against the
real `feature_repo/` and the real precomputed feature table, once per module:

1. Feast historical retrieval on the PaySim fixture extracted from real Silver matches the oracle's
   expected vectors (`data/fixtures/paysim_expected_features.json`), field by field;
2. `feast apply` is idempotent, measured with the **definitions** checksum of guide §3.3.1
   (`platform/feast_registry.py`) and never with the registry blob, which M030 Finding 2 measured
   to be unstable across a no-op apply;
3. `paysim-fraud-scoring-v2` resolves all twelve fields in `PAYSIM_MODEL_FEATURE_ORDER` order.

Until now this evidence only existed in throwaway scripts (M030's `scripts/spike_feast_t1.py`,
superseded by this lane, and a scratch probe). A gate that is re-measured by hand is not a gate, so
it lives here.

Two runtime requirements are not always satisfiable, and both skip loudly rather than silently:
Feast is an optional dependency group (`pyproject.toml` keeps it out of the correctness path on
purpose), and the feature table is built from the real PaySim Silver Delta table, which needs a
local `pit data build-lakehouse --dataset paysim` run against a CSV that is not committed. The skip
strategy and its wording follow `tests/integration/test_paysim_fixture.py`.

The lane writes **no** registry into `feature_repo/`. `feast apply` is run against the real
`feature_repo/` directory -- that is the thing under test -- but through a config whose `registry`
and online-store `path` are redirected into a pytest temporary directory, and
`test_the_g1_lane_leaves_feature_repo_registry_untouched` pins that redirection.
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pit_fintech.data.paysim_fixture import (
    EXPECTED_PATH,
    FEATURE_TABLE_PATH,
    PROJECT_ROOT,
    build_paysim_temporal_fixture,
    load_paysim_expected_features,
    load_paysim_fixture_events,
)
from pit_fintech.features.paysim_reference import in_scoring_scope
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SERVICE_VERSION,
    PAYSIM_FEATURE_SPECS,
    PAYSIM_MODEL_FEATURE_ORDER,
    paysim_step_to_timestamp,
)
from pit_fintech.platform.feast_registry import (
    feast_definitions_checksum,
    feast_definitions_payload,
)

pytestmark = pytest.mark.integration

FEATURE_REPO = PROJECT_ROOT / "feature_repo"
FEATURE_STORE_YAML = FEATURE_REPO / "feature_store.yaml"

# The eleven in-scope cutoffs of the frozen `paysim1:16910f90577b0d98` snapshot, written as a
# literal for the same reason `tests/integration/test_paysim_fixture.py` writes it as one: a
# selection change that drops or adds a cutoff must fail here, not reshape the gate silently.
EXPECTED_FEATURE_ROWS = 11

# `feature_repo/definitions.py` reshapes the definition version into an identifier-safe
# `FeatureView` name (Feast breaks on a dashed name at SQLite table creation). Restated here rather
# than imported from `feature_repo`, so a rename on either side fails the gate.
FEATURE_VIEW_NAME = "paysim_fraud_recipient_v3"

_FEAST_DTYPE_BY_FEATURE_NAME = {
    spec.name: ("Int64" if spec.dtype == "int64" else "Float64") for spec in PAYSIM_FEATURE_SPECS
}


@dataclass(frozen=True)
class _G1Run:
    """Everything the three criteria are read from, produced by one apply-twice sequence."""

    repo_yaml: Path
    module_payload: dict[str, Any]
    module_checksum: str
    registry_payloads: tuple[dict[str, Any], ...]
    registry_checksums: tuple[str, ...]
    blob_digests: tuple[str, ...]
    feature_repo_db_digests_before: dict[str, str]


def _require_feast() -> None:
    try:
        import feast  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment-dependent skip
        pytest.skip(
            "Feast is not installed, so the T1 registry lane cannot run. Feast is an optional "
            "dependency group kept out of the correctness path on purpose (pyproject.toml). "
            f"Install it with `uv sync --frozen --group feast`. ({exc})"
        )


def _database_digests(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.db"))
    }


@contextmanager
def _feast_repo_import_context(repo_path: Path):
    """Contain the two process-global side effects `feast apply` has.

    `repo_operations.apply_total` calls `os.chdir(repo_path)` and never restores it, and
    `repo_operations.parse_repo` imports each repo file by its bare module name
    (`py_path_to_module` builds the name relative to the *current* working directory), which needs
    the repo directory on `sys.path`. Left unmanaged, both would leak into every later test in the
    session. Purging the imported modules afterwards also makes a second apply re-read
    `definitions.py` from disk instead of replaying cached objects, which is what makes the
    idempotence measurement mean anything.
    """

    cwd = Path.cwd()
    before = set(sys.modules)
    sys.path.insert(0, str(repo_path))
    try:
        yield
    finally:
        os.chdir(cwd)
        with suppress(ValueError):
            sys.path.remove(str(repo_path))
        for name in set(sys.modules) - before:
            module_file = getattr(sys.modules[name], "__file__", None)
            if module_file and Path(module_file).resolve().parent == repo_path.resolve():
                del sys.modules[name]


def _collect_module_definitions() -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    """Read the declared objects the way `feast apply` does -- by scanning, not by naming them.

    Naming the three objects would make the checksum blind to a fourth one being added to
    `feature_repo/definitions.py`, which is exactly the kind of drift the gate exists to catch.
    """

    from feast import Entity, FeatureService, FeatureView
    from feature_repo import definitions

    values = [getattr(definitions, name) for name in sorted(vars(definitions))]
    return (
        tuple(value for value in values if isinstance(value, Entity)),
        tuple(value for value in values if isinstance(value, FeatureView)),
        tuple(value for value in values if isinstance(value, FeatureService)),
    )


def _registry_definitions(store: Any) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    return (
        tuple(store.list_entities()),
        tuple(store.list_feature_views()),
        tuple(store.list_feature_services()),
    )


def _checksum_of(collections: tuple[tuple[Any, ...], ...]) -> str:
    entities, feature_views, feature_services = collections
    return feast_definitions_checksum(
        entities=entities,
        feature_views=feature_views,
        feature_services=feature_services,
        project_root=PROJECT_ROOT,
    )


def _payload_of(collections: tuple[tuple[Any, ...], ...]) -> dict[str, Any]:
    entities, feature_views, feature_services = collections
    return feast_definitions_payload(
        entities=entities,
        feature_views=feature_views,
        feature_services=feature_services,
        project_root=PROJECT_ROOT,
    )


@pytest.fixture(scope="module")
def g1_run(tmp_path_factory: pytest.TempPathFactory) -> _G1Run:
    """Build the fixture, then apply the real `feature_repo/` twice into a throwaway registry."""

    _require_feast()

    import yaml
    from feast import FeatureStore
    from feast.repo_config import load_repo_config
    from feast.repo_operations import apply_total

    try:
        result = build_paysim_temporal_fixture()
    except FileNotFoundError as exc:
        pytest.skip(f"no local PaySim Silver artifact to build the fixture from: {exc}")

    assert result["feature_table_path"] == str(FEATURE_TABLE_PATH)
    if not FEATURE_TABLE_PATH.exists() or not EXPECTED_PATH.exists():
        pytest.skip(
            "the T1 lane needs both the precomputed feature table and the oracle expectations on "
            f"disk ({FEATURE_TABLE_PATH}, {EXPECTED_PATH}); build them with "
            "`.\\make.ps1 build-fixture` (or `uv run pit data build-fixture --dataset paysim`)"
        )
    assert FEATURE_STORE_YAML.is_file(), f"missing Feast repo config at {FEATURE_STORE_YAML}"

    registry_home = tmp_path_factory.mktemp("feast_g1_registry")
    db_digests_before = _database_digests(FEATURE_REPO)

    # The project's own config, with only the two output paths redirected. Rewriting the whole file
    # here would let the lane pass against a provider or offline store the repo no longer uses.
    config = yaml.safe_load(FEATURE_STORE_YAML.read_text(encoding="utf-8"))
    assert config["registry"] == "registry.db"
    assert config["online_store"]["path"] == "online.db"
    config["registry"] = (registry_home / "registry.db").as_posix()
    config["online_store"]["path"] = (registry_home / "online.db").as_posix()
    repo_yaml = registry_home / "feature_store.yaml"
    repo_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    registry_payloads: list[dict[str, Any]] = []
    registry_checksums: list[str] = []
    blob_digests: list[str] = []

    for _ in range(2):
        repo_config = load_repo_config(FEATURE_REPO, repo_yaml)
        with _feast_repo_import_context(FEATURE_REPO):
            apply_total(repo_config, FEATURE_REPO, skip_source_validation=False)
        blob_digests.append(
            hashlib.sha256((registry_home / "registry.db").read_bytes()).hexdigest()
        )
        store = FeatureStore(repo_path=str(FEATURE_REPO), fs_yaml_file=repo_yaml)
        collections = _registry_definitions(store)
        registry_payloads.append(_payload_of(collections))
        registry_checksums.append(_checksum_of(collections))

    module_collections = _collect_module_definitions()

    return _G1Run(
        repo_yaml=repo_yaml,
        module_payload=_payload_of(module_collections),
        module_checksum=_checksum_of(module_collections),
        registry_payloads=tuple(registry_payloads),
        registry_checksums=tuple(registry_checksums),
        blob_digests=tuple(blob_digests),
        feature_repo_db_digests_before=db_digests_before,
    )


def test_g1_historical_retrieval_matches_the_oracle_expected_vectors(g1_run: _G1Run) -> None:
    """G1 criterion 1: every field of every retrieved row equals the oracle's expectation.

    The entity dataframe is built from the JSONL fixture -- the oracle's own input -- and its
    timestamps come from the frozen ADR-006 map, not from the Parquet. So the join key that reaches
    Feast is derived on the oracle side while the values Feast returns were computed by the SQL
    engine: two independent derivations meeting, which is the whole reason the feature table is not
    oracle-built (guide §3.2.1).
    """

    import pandas as pd
    from feast import FeatureStore

    store = FeatureStore(repo_path=str(FEATURE_REPO), fs_yaml_file=g1_run.repo_yaml)
    service = store.get_feature_service(PAYSIM_FEATURE_SERVICE_VERSION)

    events = load_paysim_fixture_events()
    expected = load_paysim_expected_features()
    in_scope = [event for event in events if in_scoring_scope(event)]
    assert len(in_scope) == EXPECTED_FEATURE_ROWS
    assert set(expected) == {event.source_row_number for event in in_scope}

    entity_df = pd.DataFrame(
        {
            PAYSIM_ENTITY: [event.destination_entity_id for event in in_scope],
            "event_timestamp": [paysim_step_to_timestamp(event.step) for event in in_scope],
            "source_row_number": [event.source_row_number for event in in_scope],
        }
    )

    retrieved = store.get_historical_features(entity_df=entity_df, features=service).to_df()

    assert len(retrieved) == EXPECTED_FEATURE_ROWS
    assert set(PAYSIM_MODEL_FEATURE_ORDER) <= set(retrieved.columns)

    records = retrieved.to_dict("records")
    assert {int(record["source_row_number"]) for record in records} == set(expected)

    # Exact equality, not `float_tolerance`: both sides are correctly-rounded conversions of the
    # same DECIMAL(18,2) value, so anything looser would hide the drift M027 removed.
    differences = [
        f"{int(record['source_row_number'])}.{name}: "
        f"feast={record[name]!r} oracle={expected[int(record['source_row_number'])][name]!r}"
        for record in records
        for name in PAYSIM_MODEL_FEATURE_ORDER
        if record[name] != expected[int(record["source_row_number"])][name]
    ]
    assert not differences, "Feast retrieval disagrees with the oracle:\n" + "\n".join(differences)


def test_g1_feast_apply_is_idempotent_by_definitions_checksum(g1_run: _G1Run) -> None:
    """G1 criterion 2: two applies, one definitions checksum -- measured off the blob.

    The payload comparison runs before the digest comparison on purpose: if the two ever diverge,
    the failure has to say *what* moved, not just that two hex strings differ.
    """

    first_payload, second_payload = g1_run.registry_payloads
    assert first_payload == second_payload
    assert first_payload == g1_run.module_payload

    first_checksum, second_checksum = g1_run.registry_checksums
    assert first_checksum == second_checksum
    assert first_checksum == g1_run.module_checksum

    # The registry blob moves on a no-op apply because the proto carries `last_updated`
    # (M030 Finding 2, guide §3.3.1). Pinned so the finding cannot go stale unnoticed: if a future
    # Feast makes the blob stable this fails, and the fix is to update §3.3.1 and M030 -- the
    # definitions checksum stays the right way to measure idempotence either way.
    first_blob, second_blob = g1_run.blob_digests
    assert first_blob != second_blob, (
        "the registry blob no longer moves on a no-op apply; guide §3.3.1 and M030 Finding 2 "
        "describe Feast 0.65.0 behaviour and need re-measuring"
    )


def test_g1_feature_service_resolves_ten_fields_in_contract_order(g1_run: _G1Run) -> None:
    """G1 criterion 3: `paysim-fraud-scoring-v3` resolves ten fields, in order, with dtypes."""

    from feast import FeatureStore

    store = FeatureStore(repo_path=str(FEATURE_REPO), fs_yaml_file=g1_run.repo_yaml)
    service = store.get_feature_service(PAYSIM_FEATURE_SERVICE_VERSION)

    assert service.name == PAYSIM_FEATURE_SERVICE_VERSION
    assert service.tags["feature_service_version"] == PAYSIM_FEATURE_SERVICE_VERSION

    projections = service.feature_view_projections
    assert len(projections) == 1
    assert projections[0].name == FEATURE_VIEW_NAME

    resolved = projections[0].features
    assert [field.name for field in resolved] == list(PAYSIM_MODEL_FEATURE_ORDER)
    assert [str(field.dtype) for field in resolved] == [
        _FEAST_DTYPE_BY_FEATURE_NAME[name] for name in PAYSIM_MODEL_FEATURE_ORDER
    ]

    view = store.get_feature_view(FEATURE_VIEW_NAME)
    assert view.tags["definition_version"] == PAYSIM_FEATURE_DEFINITION_VERSION
    assert [field.name for field in view.features] == list(PAYSIM_MODEL_FEATURE_ORDER)
    # `FeatureView.schema` is `list(set(entity_columns + features))` (`feast/feature_view.py:430`),
    # so it carries membership but NOT order. Asserted as a set deliberately: reading order from
    # `.schema` is the trap this line exists to keep out of the gate.
    assert set(PAYSIM_MODEL_FEATURE_ORDER) < {field.name for field in view.schema}


def test_the_g1_lane_leaves_feature_repo_registry_untouched(g1_run: _G1Run) -> None:
    """`feast apply` ran against the real repo directory; nothing may have been written into it."""

    assert _database_digests(FEATURE_REPO) == g1_run.feature_repo_db_digests_before
    assert g1_run.repo_yaml.parent != FEATURE_REPO
    assert (g1_run.repo_yaml.parent / "registry.db").is_file()
