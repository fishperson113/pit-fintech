# ADR-012: Remove Feast; the in-tree PIT platform is the sole feature contract

- Status: accepted
- Date: 2026-08-24
- Supersedes the Feast scope of [ADR-006](006-feast-time-mapping-and-service-v2.md)
- Depends on: [ADR-003](003-paysim-feature-contract-v1.md), [ADR-008](008-serving-owns-the-online-write-path.md), [ADR-009](009-parity-at-the-online-write-path.md), [ADR-011](011-cold-start-featurespec-v3.md)
- Applies to: the whole repository (removes `feature_store/`, the Feast dependency group, and the Feast lane)

## Context

AGENTS.md §11 originally mandated Feast as a "thin registry/retrieval/materialization contract."
In practice Feast never became load-bearing, and review concluded it could not:

1. **It is off the runtime path.** The only wired `FeatureProvider` is `RedisFeatureProvider`;
   `FeastFeatureProvider` was a `NotImplementedError` skeleton. Scoring reads the materialized
   aggregate from Redis directly (ADR-009). No `src/` module imported the Feast definitions.
2. **It cannot compute the features.** The contract is rolling-window aggregates (count/sum/history
   at 1h/24h/168h); Feast computes no window aggregates (M030 Finding 1), so a `FeatureView` could
   only ever read a precomputed table.
3. **It cannot own the online path.** The windows must be maintained per-transaction under an
   optimistic lock — each scored transaction becomes history for the next (ADR-008, ADR-010).
   Feast's online store is read-only and populated by batch `materialize`/PushSource; it cannot do
   the atomic read-modify-write-of-aggregates the PIT read-before-write invariant requires.
4. **The research thesis owns correctness.** The correctness source of truth is deliberately the
   in-tree PIT oracle (`features/paysim_reference.py`) + SQL engine, not Feast (AGENTS.md §11). So
   Feast was always a thin bolt-on, and keeping it exercised only a skipped acceptance lane (G1).

Every replacement AGENTS.md §11 required before dropping Feast already exists independently in
`src/`: a versioned `FeatureSpec` (`features/paysim_specs.py`), a `FeatureProvider`
(`serving/feature_provider.py`), a Redis key/schema contract (`materialization/records.py`), a
materialization manifest, and parity gates (write-path parity + `pit parity reconcile`).

## Decision

Remove Feast from the repository entirely:

- Delete `feature_store/` (the Feast repo: `definitions.py`, `feature_store.yaml`), the
  `platform/feast_registry.py` checksum module, and the Feast lanes
  (`tests/integration/test_feast_registry_g1.py`, `tests/unit/test_feast_definitions_checksum.py`).
- Delete the Feast-only apparatus that fed the `FileSource`: `data/paysim_fixture.py` and its
  `pit data build-fixture` CLI command, the `paysim_*` fixture artifacts under `data/fixtures/`,
  `build_offline.py: GOLD_FEAST_SOURCE_COLUMNS` / `export_feast_source_parquet`, and
  `materializer.py: push_to_feast_online_store`. The SQL-vs-oracle cross-check that lived on that
  fixture is retired with it (owner decision); the temporal PIT ground truth remains the
  **synthetic** oracle (`data/sample.py`, `tests/temporal`), which never depended on Feast.
- Remove the Feast provider seam (`FeastFeatureProvider`, `kind="feast"`), the `feast_repo_path`
  serving config, the `feast` retrieval backend option, and the unused
  `DeploymentManifest.feast_definitions_checksum` lineage field.
- Remove the `feast` optional dependency group from `pyproject.toml`.

**Kept, despite the name:** `PAYSIM_FEAST_EPOCH_0` and `paysim_step_to_timestamp`
(`features/paysim_specs.py`). These are the ADR-006 hour-ordinal → UTC mapping used across the
medallion tables, materializer, and serving — load-bearing well beyond Feast. Renaming them off
"FEAST" is optional follow-up.

## Consequences

- `uvicorn[standard]==0.34.0` was capped only because Feast pinned it transitively. The pin is kept
  for now (no behaviour change) and flagged as removable follow-up.
- `test-temporal` / `test-unit` are unaffected (they never imported Feast). The offline/online
  parity and correctness gates are unchanged. `uv.lock` was regenerated automatically (455 feast +
  transitive lines removed; `uv lock --check` passes).
- ADR-006's Feast time-mapping decisions remain the authority for the *timestamp mapping* (kept);
  its Feast *registry/service* decisions are superseded here.
