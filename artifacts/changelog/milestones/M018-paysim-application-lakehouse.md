# M018 — PaySim application Bronze/Silver lakehouse

- Date: 2026-07-27
- Updated: 2026-07-27 14:04:34 +07:00
- Status: verified

## Scope and acceptance

Implement the Sprint 1 application-data path from the frozen PaySim CSV snapshot to versioned
Delta tables:

```text
PaySim raw CSV
  -> bronze.paysim_transactions
  -> silver.paysim_transactions
  -> silver.paysim_labels
```

Acceptance for implementation:

- the raw CSV identity is tied to `dataset_snapshot_id` and SHA-256 evidence;
- DuckDB projects ordered record-batch streams into Delta without requiring a full in-memory
  PyArrow table;
- Bronze preserves the source fields and adds deterministic snapshot/row lineage;
- Silver transactions expose the ADR-003 source columns and destination entity while excluding
  labels, policy output and balance fields;
- Silver labels retain `isFraud` in a separate joinable table;
- all tables use the synthetic event day only as a layout partition;
- schema, row count, core value, label separation and source-count gates fail before publish;
- the application manifest records the frozen feature checksum and exact Delta versions;
- each successful rerun publishes an immutable version-manifest plus an atomic latest-manifest;
- CLI, Make and PowerShell support `build-lakehouse --dataset paysim`;
- fixture integration tests cover deterministic rerun, time travel, schema and invalid input.

Full PaySim execution and all pytest/lint commands remain delegated to the user.

## Decisions

- Keep the existing synthetic builder unchanged as the independent correctness oracle.
- Put application tables below
  `data/lakehouse/paysim1/<snapshot-prefix>/{bronze,silver}/`.
- Use `source_row_number` as the deterministic source identity and tie-break lineage.
- Do not deduplicate PaySim rows: the dataset has no transaction ID and identical business
  values can be legitimate separate simulator events.
- Keep all transaction types in Silver; the model scope remains the ADR-003 filter
  `CASH_OUT`/`TRANSFER -> CUSTOMER`.
- Treat Delta writes as individually ACID and publish the multi-table manifest only after every
  table succeeds. Cross-table atomic backfill remains Sprint 2 scope.

## Files added or changed

- `src/pit_fintech/data/paysim_lakehouse.py`
- `src/pit_fintech/data/paysim.py`
- `src/pit_fintech/contracts/manifests.py`
- `src/pit_fintech/cli.py`
- `tests/integration/test_paysim_lakehouse.py`
- `Makefile`
- `make.ps1`
- `README.md`
- `AGENTS.md`
- `docs/reports/paysim-application-lakehouse.md`
- `docs/reports/sprint-1-gate.md`
- `docs/research-protocol.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Implemented behavior

The builder:

1. revalidates the raw SHA/schema, reuses an immutable existing snapshot manifest, or profiles
   and creates it once;
2. marks the Git commit with `-dirty` when the worktree is not clean;
3. runs eight publish-blocking DuckDB quality gates;
4. projects each table in deterministic `source_row_number` order;
5. streams fixed-size Arrow record batches into partitioned Delta writes;
6. validates output schema and row count without materializing the full table in Python;
7. writes label-free Silver transactions and a separate label table;
8. rehashes the raw file and blocks manifest publication if it changed during the build;
9. captures exact versions, schema/ordered-stream checksums, contract version/checksum and
   lightweight resource evidence;
10. writes a version-keyed immutable manifest, then atomically replaces the latest-manifest.

The output paths are snapshot-scoped, so a different raw SHA-256 cannot silently overwrite an
existing application table. Rerunning the same snapshot uses Delta `overwrite`, producing a new
time-travelable version instead of deleting history.

The ordered-stream checksum uses the manifest-recorded Arrow batch size and locked pipeline
version. It is deterministic for an exact pipeline configuration; it is not presented as a
storage-file checksum.

## Verification state

No application build, pytest target, notebook or model command was executed by the agent.

User-run fixture evidence:

```text
.\make.ps1 test-unit
  30 passed in 3.55s
  exit 0

.\make.ps1 test-lakehouse
  3 passed in 4.10s
  exit 0

.\make.ps1 test-lakehouse  # after to_arrow_reader migration
  3 passed in 3.35s
  exit 0
  warnings: 0
```

The integration run emitted six identical DuckDB deprecation warnings—one per streamed table
write across the two-build rerun test—because `fetch_record_batch()` has been superseded by
`to_arrow_reader()`. No assertion, schema, checksum, version, isolation, quality gate or time
travel check failed. The builder now uses `to_arrow_reader(batch_size)`; one clean fixture rerun
then passed 3/3 with no warnings.

User-run full application build:

```text
.\make.ps1 build-lakehouse -Dataset paysim
  temporal gate: 23 passed in 3.69s
  dataset_snapshot_id: paysim1:16910f90577b0d98
  raw rows: 6,362,620
  quality gates: 8 passed
  Delta tables: 3 at version 0, each with 6,362,620 rows
  wall time: 56.2912s
  throughput: 113,030.41 rows/s
  active Delta Parquet bytes: 649,248,646
  event-day partitions: 31
  process RSS before/after: 74,981,376 / 519,098,368 bytes
  code commit: 115e98dcf10b3071f02c228925ab0b366dd2e611-dirty
```

Exact output checksums:

```text
bronze.paysim_transactions
  schema: 6ba9df7b3a4a4d13a3d50c857597ef85068a45d3dc5c56ea7ff2b2d0be8b2a18
  logical: f61c3459f9fde9bce45ce94863c2085c2dd0d55294fe643afa91906e54d13b96
silver.paysim_transactions
  schema: c910a72d081faa2aedaf38a6b7063ac144b384f387d35f02efc22e74206670a1
  logical: bdd83e3c8a1bc55016d0db23cd56bb72419c53d4c873f5a9f24712d0fcd36220
silver.paysim_labels
  schema: 8ffba30059b7e7a4b39ca1af287155827e8160cb7cd8925478b63f28d5db986b
  logical: 545bfc0baeab0cd5b1b2cecea88828dcf45101f73a67bd2ce05acdf3e02e5093
```

The persisted manifest was read back successfully. All eight gate observations match their
expected values, the three table roots contain Delta logs, and the immutable version-0 manifest
exists. M018 is verified.

The first authorized Git commit attempt invoked the required pre-commit suite. Ruff check fixed
four issues and Ruff format reformatted nine Python/notebook files, so the hook correctly stopped
the commit for restaging. Large-file, merge-conflict, TOML, YAML, EOF, whitespace and mandatory
milestone-changelog guards passed. The formatting changes were reviewed as mechanical and staged
for the retry.

Static review:

```text
Python source line-length scan at 100 columns: pass
git diff --check: pass (working-copy CRLF notices only)
PowerShell parser for make.ps1: pass
delta-rs local signature: RecordBatchReader input, partition_by, schema_mode,
  target_file_size, name and description supported
Context7 official delta-rs docs: iterator/RecordBatch streaming and overwrite supported
Make/PowerShell dataset forwarding: implemented
Silver transaction constant vs forbidden FeatureSpec inputs: disjoint by construction
```

## Known gaps and next step

- The full build will create a dirty-code artifact if run before the implementation is committed;
  the verified artifact did record `115e98d...-dirty`. This is valid feasibility evidence but not
  the final clean baseline.
- Process RSS before/after is not sampled peak RSS.
- Individual Delta writes are ACID; multi-table atomic recovery remains Sprint 2 scope.
- Next: commit the verified implementation, then run the locked LightGBM baseline from exact
  Silver Delta version 0 rather than the raw CSV.
