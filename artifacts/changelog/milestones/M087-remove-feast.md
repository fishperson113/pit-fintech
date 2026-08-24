# M087 — Remove Feast entirely (ADR-012)

- 2026-08-24 — **implemented** (owner-directed; gates owner-pending: `uv lock` + full test run).

## Scope / gate

Owner decision after a full architectural review: Feast never became load-bearing and could not
(off the runtime path; cannot compute window aggregates; cannot own the online windowed-write under
the optimistic lock; the in-tree oracle owns correctness by thesis). Remove it entirely, including
the Feast-only fixture apparatus and related tests. Recorded in **ADR-012** (supersedes the Feast
scope of ADR-006). Every replacement AGENTS.md §11 required already exists in `src/`
(`paysim_specs.py`, `serving/feature_provider.py`, `materialization/records.py`, materialization
manifest, parity gates).

Gate (owner-run): `.\make.ps1 lint` / `test-unit` / `test` green. `ruff check` +
`ruff format --check` + `py_compile` are clean locally; `uv.lock` already regenerated (455 feast +
transitive lines removed, `uv lock --check` → "Resolved 214 packages", consistent);
`test-temporal`/`test-unit` never imported Feast so behaviour is unchanged.

## Deleted

- `feature_store/` (definitions.py, feature_store.yaml, __init__.py + untracked db/pycache)
- `src/pit_fintech/platform/feast_registry.py`
- `src/pit_fintech/data/paysim_fixture.py` (+ its `pit data build-fixture` CLI command)
- `tests/integration/test_feast_registry_g1.py`, `tests/integration/test_paysim_fixture.py`
- `tests/unit/test_feast_definitions_checksum.py`, `tests/unit/test_paysim_fixture.py`
- `data/fixtures/paysim_{expected_features.json,feature_table.parquet,temporal_cases.jsonl,temporal_cases.parquet}`
  (the **synthetic** oracle fixtures `temporal_cases.*` / `expected_features.json` are kept)

## Surgically removed (files kept)

- `serving/feature_provider.py`: `FeastFeatureProvider`, `kind="feast"`, feast-only params; only
  `RedisFeatureProvider` stays wired (`sqlite`/`upstash` skeletons untouched).
- `serving/app.py` + `cli.py`: `feast_repo_path` config/plumbing.
- `materialization/`: `push_to_feast_online_store` (+ `__init__` export).
- `training/dataset.py`: `retrieval_backend="feast"` branch (now `Literal["duckdb_gold"]`).
- `training/lifecycle.py`: unused `DeploymentManifest.feast_definitions_checksum` field.
- `features/build_offline.py`: `GOLD_FEAST_SOURCE_COLUMNS` + its import-time validation +
  `export_feast_source_parquet`.
- `pyproject.toml`: the `feast` optional dependency group + `feature_store` dropped from ruff `src`.
- `Makefile` / `make.ps1`: `feature_store` dropped from ruff dir args.
- Feast docstrings/comments across `paysim_specs`, `paysim_recipient`, `paysim_reference`,
  `materializer`, `backfill/records`, `training/pipeline`, `serving/telemetry`, README/CLAUDE
  reworded; AGENTS.md §11 scope guard updated to record the removal.

## Kept despite the name

`PAYSIM_FEAST_EPOCH_0` + `paysim_step_to_timestamp` (`features/paysim_specs.py`) — the ADR-006
hour-ordinal → UTC mapping used by the medallion tables, materializer and serving. Load-bearing;
optional rename off "FEAST" left as follow-up.

## Known gaps / next steps

- `uv.lock` is already regenerated and consistent (`uv run` reconciled it when the `feast` group
  left `pyproject.toml`; `uv lock --check` passes). No separate `uv lock` needed.
- `uvicorn[standard]==0.34.0` pin was inherited from Feast; kept pending review (removable).
- AGENTS.md still carries historical/descriptive Feast mentions in past-sprint status text; left as
  record, with §11 and ADR-012 as the authoritative current state.
- `models/paysim_lightgbm.py` keeps one historical spike-scope string naming Feast (a record of
  what that spike did not do); intentionally left.
