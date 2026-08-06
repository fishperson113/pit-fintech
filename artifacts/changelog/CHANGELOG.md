# Project changelog

## 2026-08-06 — M043: T5 materialization (Redis backend), T7 serving, CLI/Make wiring and e2e demo round

- **Implemented, verified on happy path** (NOT claimed: G5/G7/G9 pass — no test lane pins their
  criteria yet; `tests/e2e/` is still 12 skipped).
- T5 (`materialization/records.py`, `materialization/materializer.py`): `online_record_key` and
  watermark/run key helpers implemented; Redis-only backend (`OnlineStoreConfig` gains
  host/port/db defaults matching `compose.yaml`); `materialize_to_watermark` reads
  `gold.post_event_state_updates` via DeltaTable + DuckDB (version pinned at run start), keeps the
  latest row per entity by `(step DESC, source_row_number DESC)`, renames the nine `post_*` fields
  through `POST_EVENT_TO_CONTRACT_FIELD`, writes JSON payloads through 5000-batch Redis pipelines
  with `evaluate_write` on every candidate, and writes the watermark key last. Amounts are stored
  as decimal strings; `source_checksum` excludes run-local metadata so it is deterministic per
  Gold version + watermark. `evaluate_write`/`write_record` (WATCH/MULTI/EXEC)/`read_online_
  features` (fresh/stale/missing with contract defaults)/`read_watermark`/`reset_online_store`
  (SCAN-scoped, no FLUSHDB) implemented; SQLITE, `rematerialize_after_reset`, and
  `push_to_feast_online_store` stay NotImplementedError with explicit comments.
- T7 (`serving/{schemas,feature_provider,scoring,app}.py`): FastAPI with exactly four routes
  (`POST /score`, `GET /health/live`, `GET /health/ready`, `GET /metrics`); model loaded via
  `mlflow.sklearn.load_model("runs:/<run_id>/model")`, default = newest FINISHED run of
  `pit-fintech-gold-training` (`8f9c709782704f1eba89cc9e3fde83c1` in the demo round);
  `model_version` = MLflow run id, `deployment_id=None` (no model registry, G11 not met).
- CLI/Make/demo: `pit materialize run|show`, `pit serving up`; Make targets `materialize`, `serve`,
  `demo`, `redis-up`, `redis-down`; `scripts/run_demo_e2e.py` (Redis -> Gold -> materialize ->
  serve -> score 3 cases -> tear down).
- Verification (local): ruff clean on `src/` + `scripts/`; unit 87 passed; temporal 73 passed;
  real materialization on Gold v6 — watermark 24: 249,521 records / 32.3 s; watermark 743:
  2,722,362 entities, 2,527,816 written / 194,546 NOOP / 0 rejected / 384.8 s; re-run at 24:
  0 written / 249,521 NOOP; two-run checksum probe identical (`a8bf4b6e...`); reset removed
  exactly 249,523 keys on the probe namespace. Demo `--skip-materialize`: 3/3 PASS in 41.95 s
  (case A entity C1470998563 step 744 fresh/staleness 1, case B step 1243 stale/500, case C
  C0000000000 missing with nine zero history fields).
- Limits: T6 parity not done; SQLITE/G8/Feast PushSource not implemented; no registry (G11 not
  met); no gate claim for G5/G7/G9; work uncommitted in the working tree at time of writing.

## 2026-08-05 — M042: Install the training dependency group in CI and latch the T4 lane against a fake-green run

- **Implemented, not verified.** GitHub Actions run 30995527627 (commit d2ce188) failed at the
  "Delta sample snapshot and time travel" step: `make test-lakehouse` exited 2 with
  `ModuleNotFoundError: No module named 'lightgbm'` in
  `test_t4_train_candidate_logs_complete_mlflow_contract` (1 failed, 13 passed, 7 skipped; every
  other step passed).
- Root cause: the T4 lane calls `train_candidate()` and requires the optional `training` group
  (lightgbm, mlflow, scikit-learn), but the workflow synced only `uv sync --frozen --group dev` and
  the `test-lakehouse` target ran without a group flag.
- `.github/workflows/ci.yml`: sync now installs `--group dev --group training`; the
  "Delta sample snapshot and time travel" step alone sets `PIT_REQUIRE_TRAINING: "1"`.
- `Makefile`: `test-lakehouse` now runs `uv run --group training pytest -q tests/integration`; new
  self-contained local target `test-integration-full` (all-groups, matching the
  `test-t3-smoke`/`test-t4-dataset` convention) added to `.PHONY`; a comment above `test-lakehouse`
  documents the local group-pruning side effect.
- `tests/integration/test_t4_training.py`: `_require_training()` mirrors `_require_feast()` and
  escalates the skip to `pytest.fail` when `PIT_REQUIRE_TRAINING=1` — the latch against a fake-green
  CI.
- Verification (local, Windows): dry-run resolution of `dev + training` (194 packages, exit 0),
  latch mutation test (without the variable 1 skipped/exit 0, with it 1 failed/exit 1), integration
  21 passed, Ruff clean. No green CI run on ubuntu-latest yet; expected lane: 14 passed, 7 skipped,
  0 failed.

## 2026-08-05 — M041: Optimize T4 training path and add Colab-style progress

- Replaced repeated `to_pylist()` over millions of rows in entity dataframe build, retrieval,
  future-read audit and temporal split with Arrow compute (`unique/max/sum/greater_equal`); labels
  are narrowed to the two join columns before the DuckDB join.
- Added `progress` flags (`[t4 +Xs]` phase lines) to dataset/pipeline stages and
  `lightgbm.log_evaluation(period=10)` in `train_candidate`, so `train-gold-candidate` prints
  every-10-rounds training progress like a notebook/Colab run.
- No contract/checksum change; defaults preserve prior behavior.
- Verification: T4/Gold fixtures 6 passed, unit 87, temporal 73, integration 21, Ruff clean.
- Real-run verification: user ran `train-gold-candidate` twice on committed Gold v6 (full
  1..743); both runs produced `test_pr_auc 0.362883` with complete MLflow tags/artifacts,
  confirming deterministic reproducible T4 training on the real lakehouse.
- Warning cleanup: `train_candidate` now passes feature-named DataFrames and uses LightGBM
  `eval_X`/`eval_y`, removing the `eval_set` deprecation and sklearn feature-name warnings from
  the T4 path.

## 2026-08-05 — M040: Optimize Gold promote read-back verification

- Optimized `_write_gold_table` (promote path) to verify written partitions via Arrow dataset
  predicate pushdown and `Table.equals`, replacing full-table `to_pylist()` and two full-table
  `json.dumps` checksum passes.
- Added `[promote +Xs]` phase progress to `promote_staged_gold` (opt-in `progress` flag) and enabled
  it in the `promote-gold` CLI, matching the Gold build progress style.
- Published `logical_checksum` values are byte-identical (same `_canonical_checksum` on the input
  table); no contract, schema, predicate or validation changed.
- Verification: Gold fixture tests 4/4, unit 87, temporal 73, integration 21, Ruff clean. The real
  in-flight promote continues on the old code; this fix applies to the next run.

## 2026-08-05 — M039: Add T3 smoke lane and T4 Gold training path

- **Implemented, partially verified.** Added isolated T3 smoke coverage for backfill execution,
  rerun comparison and expected late-arrival future-read refusal; wired `test-t3-smoke` in both
  runners. The smoke lane also fixed exact Silver-manifest pinning and deterministic late-arrival
  template selection after exposing a real ordering flake.
- Implemented T4 Gold exact-version dataset retrieval, label join, leakage assertions, frozen temporal
  split/checksum, LightGBM candidate training and MLflow required artifact/tag verification.
- Wired `test-t4-dataset` and `train-gold-candidate` in `Makefile` and `make.ps1`; the candidate runner help was verified.
- Verification: T3 smoke pass, T4 dataset fixture pass, T4 MLflow fixture pass, unit 87, temporal 73,
  integration 20; Ruff clean. Full-scale T4 training and T3 G2/G3 correction-success evidence remain
  open. No real T4 training was run.

## 2026-08-05 — M038: Index shift-relation validation by entity

- **Implemented, not verified.** `verify_shift_relation` now groups post-event rows by entity once
  before comparing the one-step-shift relation, removing the previous full-table scan for every
  entity.
- The comparison fields, mismatch semantics, validation ordering and missing-vector behavior are
  unchanged.
- Verification: focused Gold tests 12 passed; Ruff clean; unit 87 passed; temporal 73 passed;
  integration 17 passed with one existing Ibis deprecation warning.
- No real Gold build or promotion was run.

## 2026-08-05 — M037: Add low-overhead Gold build phase progress

- **Implemented, not verified.** `pit features build-gold` now prints phase boundaries and elapsed
  seconds when reading Silver, running audits/queries, writing staging, and validating shift relation.
- Progress is disabled by default for library callers and enabled only by the CLI; no per-row
  instrumentation or Gold business-logic change was introduced.
- Verification: focused CLI/Gold tests 14 passed; Ruff clean; unit 87 passed; temporal 73 passed;
  integration 17 passed with one existing Ibis deprecation warning.
- No real Gold build or promotion was run.

## 2026-08-05 — M036: Narrow and reuse the Gold DuckDB relation

- **Implemented, not verified.** Gold now projects only the seven contract source columns plus
  `event_day` during the Silver Delta read, materializes that narrow relation once in DuckDB for
  repeated audits/queries, and computes expected row count in SQL instead of `source_table.to_pylist()`.
- The optimization preserves the existing SQL producer, PIT predicates, audits, checksums and Gold
  schemas; no batching or semantic change was introduced.
- Verification: focused Gold fixture/range tests 12 passed; Ruff clean; unit 87 passed; temporal 73
  passed; integration 17 passed with one existing Ibis deprecation warning.
- No real Gold build or promotion was run.

## 2026-08-05 — M035: Guard Gold ranges at event-day granularity

- **Implemented, not verified.** Added the shared `validate_gold_cutoff_range` guard for complete
  event-day ranges, including PaySim's final partial day `[721,743]`.
- Reused the shared typed `IN` predicate in `_write_gold_table` and `promote_staged_gold`; T3
  `plan_backfill` now applies the same range guard.
- Added focused tests for invalid/valid ranges, T3 rejection, and predicate identity; existing
  fixture Gold tests now request `[1,24]` rather than a partial day.
- Updated CLI help and README with valid examples `[1,24]`, `[25,48]`, `[721,743]`.
- Verification: Ruff clean; unit 87 passed; temporal 73 passed; integration 17 passed with one
  existing Ibis deprecation warning. No real Gold build/promote was run.

## 2026-08-05 — M034: Wire Gold build and promotion through CLI runners

- **Implemented, not verified.** Added `pit features build-gold` with staging-only default and
  `pit features promote-gold` with manifest reload and explicit promotion output.
- Added matching `gold` and `promote-gold` targets to `Makefile` and switches to `make.ps1`.
- Added CLI wiring integration tests using monkeypatched small objects; no real Gold build or
  promotion was run.
- Updated README command contract and Gold staging/promotion documentation.
- Verification: Ruff clean; unit 77 passed; temporal 73 passed; integration 17 passed with one
  existing Ibis deprecation warning. Full Gold build/promote remains unverified by scope.

## 2026-08-04 — M033: T2 Gold offline features run against real Silver, future-read audit fixed

- **Implemented, not verified.** First real run of `build_offline_features` against real PaySim
  Silver at `cutoff_start_step=cutoff_end_step=1`: `pre_decision_features` 664 rows,
  `post_event_state_updates` 2708 rows. Two independent runs produced identical logical checksums
  (`pre` `c4a8903a4da7adde3bd00a2ec7e00d6e5b672d694f2de71ba98d324abf3e1f8c`, `post`
  `e55eac8791724840b71f5be081d4245e4f6699dbe438dd0e86d9a0e951fbe7cb`).
  `compare_gold_against_reference` matched the SQL-built table against the independent Python oracle
  on all 664 rows × 12 contract fields = 7968 fields, 0 mismatches.
- **Same-step gap closed at Gold scale.** `probe_same_step_ties()` on real Gold step 1: 579 in-scope
  pairs, 1256 any-pairs, 104 entities involved. The earlier concern (T1's 11-row fixture table has
  0 same-step pairs) was scoped to that small fixture only; no artificial tie needs to be built for
  T6.
- **Bug fixed:** the future-read count was a dead-code `future_reads = ... if False else 0`, so
  `GOLD_PROMOTION_PRECONDITIONS`'s `no_future_read_violations`/`max_source_step_below_every_cutoff`
  always passed regardless of data. Replaced with `probe_future_read_violations()`, an
  independently-written self-join that does not call the frozen SQL engine it audits, using `step`
  for range membership and `knowledge_step >= cutoff_step` for the violation condition (using the
  same column for both would make the check tautological). A hand-run mutation
  (`>=` to `>`) turned the new unit test red; reverting restored green.
- **Recorded limitation:** on current data `knowledge_step = step` at ingest (`data/paysim.py`), so
  the audit never fires organically; what changed is that the `0` is now proven by an independent
  computation, not assumed by a literal. `scope="random_sample"` in `compare_gold_against_reference`
  and `export_feast_source_parquet` both remain `NotImplementedError`.
- Two HANDOFF.md §6 decisions were finalized and the guide corrected to match: the idempotency-key
  formula keeps its `policy_version` prefix (guide's literal 5-field formula was out of date; `\0`
  separator, not `:`, because `dataset_snapshot_id` already contains `:`), and no `e2e` pytest
  marker is added (`pyproject.toml` sits in both ADR-004 fingerprint boundaries).
- Recorded checks: `ruff check` clean (81 files); unit 52 passed; temporal 73 passed; integration 13
  passed.
- Detail: [M033 log](milestones/M033-t2-gold-offline-features-real-silver.md).

## 2026-08-04 — M032: Sprint 2 round 0 scaffold and cross-module contracts

- **Implemented, not verified.** Round 0 adds 19 new files (3,842 lines) for the remaining Sprint 2
  seams and modifies `compose.yaml` (T8 `api` service / `minio` profile). It is only a scaffold:
  import succeeds and lint is clean, but implementation entry points raise `NotImplementedError`
  (except the explicitly implemented `backfill_idempotency_key()` helper). No T2–T9 pipeline or
  acceptance gate is claimed to run.
- Seven contracts are fixed across Gold build, backfill records/idempotency, serving providers and
  schemas, and replay parity. Three non-obvious guards are recorded so they are not refactored away:
  post-event names intentionally differ from contract names to prevent leakage, integer mismatches
  remain separate from float-tolerance mismatches, and a parity run cannot pass with required
  checkpoints missing.
- The log carries forward three implementation traps (SQL engine rather than oracle as feature
  producer; Python rather than SQL timestamp derivation; required same-step-tie coverage) and six
  pending decisions, including the Feast-to-Gold path, stale entities, idempotency-key prefix,
  manifest consolidation, and the T1/T7 nine-versus-twelve field seam. It explicitly records the
  two intentional guide deviations: the prefix in the idempotency-key hash and no new `e2e` marker
  because it would invalidate ADR-004 fingerprint reuse.
- Recorded Round 0 checks: import OK; `ruff check` clean for 79 files; unit 50 passed; temporal 73
  passed; E2E 12 skipped. These are not evidence of an E2E run. `AGENTS.md` is modified because
  Dương updated Codex instructions; it is not a M032 output and must not be reverted as one.
- Detail: [M032 log](milestones/M032-sprint2-scaffold-and-contracts.md).

## 2026-08-04 — M031: Feast `feature_repo/`, definitions checksum, and the G1 pytest lane

- Closes the four gaps M030 left open in Sprint 2 T1: no precomputed feature table on disk, no
  `feature_repo/` objects, no definitions-based registry checksum in `src/`, no G1 test lane. All
  three guide §3.4 G1 acceptance criteria now pass (**DAT**) by a real `pytest` test, re-run
  independently and recorded in `verify.md`.
- **Precomputed feature table.** `pit data build-fixture --dataset paysim` now also writes
  `data/fixtures/paysim_feature_table.parquet` — 11 rows, 16 columns, 6,438 bytes — computed by the
  SQL engine (`paysim_pre_decision_feature_sql()`, new in `features/paysim_recipient.py`, reusing
  the existing `_prior_window_predicate`), never the oracle, so comparing the two stays two
  independent derivations. Columns: entity, both ADR-006 timestamps, the 12
  `PAYSIM_MODEL_FEATURE_ORDER` fields in contract order, and a trailing `source_row_number`; `step`/
  `knowledge_step` are dropped from the written file. 132/132 fields match the oracle exactly across
  two independent build runs, SHA-256
  `A6E6B9B00FA62966E19397D9C0A7737FCB48D8C9C81A5C7300CCE047B3B997C5`, confirmed a third time in the
  independent `verify.md` re-run.
- **Real `feature_repo/` and a real `feast apply`.** `feature_repo/feature_store.yaml` (`local`
  profile: DuckDB offline + SQLite online) and `feature_repo/definitions.py` (`Entity`,
  `FileSource`, `FeatureView`, `FeatureService`, every name/dtype/version imported from
  `features/paysim_specs.py`) are new. `feast apply`, run against installed Feast 0.65.0, created
  the entity, feature view, feature service and SQLite table. A second apply reported "No changes to
  infrastructure" but the registry proto's `last_updated` timestamps still moved — restating M030
  Finding 2 on the real repo, not just the spike. `PushSource` and an `OnDemandFeatureView` split
  for the three request-time fields were deliberately not built (T5/T7 scope).
- **Definitions-based registry checksum**, `src/pit_fintech/platform/feast_registry.py` (new; placed
  in `platform/`, not `features/`, because `features/` is the correctness-contract tier and Feast is
  kept out of it per AGENTS.md §11 and the `pyproject.toml` dependency-group comment). Reads Feast
  objects by duck typing (`TYPE_CHECKING`-only import) so `src/` still imports without Feast
  installed; canonical JSON + SHA-256, same convention as `paysim_feature_contract_checksum`.
  `ttl` and `entity_columns` are deliberately excluded from the payload — both read back differently
  from the registry than they are declared in the module (`None`->`timedelta(0)`,
  `[]`->populated), so hashing them would fail the gate for a reason unrelated to a definitions
  change; recorded as a real trade-off, not a free simplification. Current checksum:
  `d330edefbbc0d3a075b4b5f145a6d169e2aa910d39cfae33c70478289432f443`, stable across 2 independent
  processes and across both `apply` runs, while the registry **blob** digest still moved
  (`98fe137e...` -> `fd09313e...`), confirming Finding 2 stays live on this exact lane.
- **G1 pytest lane**, `tests/integration/test_feast_registry_g1.py` (new, 4 tests) — runs
  `apply_total()` (the function `feast apply` itself calls) directly against the real
  `feature_repo/`, redirecting only the registry/online-store output paths to a temp dir (copying
  `definitions.py` was tried and rejected: its `PROJECT_ROOT` resolution would then point
  `FileSource.path` at a nonexistent location). All three G1 criteria pass:
  historical-retrieval-matches-oracle (132/132 fields), apply-idempotent-by-definitions-checksum
  (stable across 2 applies, blob intentionally still differing), and
  feature-service-resolves-12-fields-in-contract-order (exact ordered list + dtype match). A fourth
  guard test confirms the lane leaves `feature_repo/registry.db`/`online.db` byte-identical.
  `tests/unit/test_feast_definitions_checksum.py` (new, 9 tests, no Feast needed) pins the checksum
  function's properties on stub objects.
- **New Feast 0.65.0 findings, not in M030:** `FeatureView.schema` runs through `set()` and loses
  field order (`feast/feature_view.py:430`) — `FeatureView.features` / `feature_view_projections[i]
  .features` must be used instead, confirmed empirically; `feast apply` does not read the source
  file at apply time, so a successful apply is not evidence the source exists; `FeatureView.name`
  must be `.isidentifier()`-safe (a dashed name breaks the SQLite online-store table name with
  `OperationalError near "-"`) while `FeatureService.name` is not so constrained; `entity.join_keys`
  does not exist post-construction — only the singular `entity.join_key` does.
- Status: **verified within the scope re-run recorded in `verify.md`**, independent of the original
  session that wrote the code. `ruff check src tests feature_repo notebooks scripts`: all checks
  passed. `pytest -q tests/unit`: 50 passed (up from 41 — the 9 new checksum tests).
  `pytest -q -m temporal tests/temporal`: 73 passed, unchanged (nothing on the PIT path touched).
  `pytest -q tests/integration`: 11 passed (up from 7 — the 4 new G1 tests plus 1 new feature-table
  schema test). `pytest -q tests/integration/test_feast_registry_g1.py -v`: 4 passed in isolation.
  `Get-FileHash` on the feature table matches the two build-time hashes. The verification script's
  own command-level bookkeeping reported `PASS=8 FAIL=0` across its 8 checks — a separate count from
  the `pytest` totals above, not conflated with them.
- **Known gaps, not glossed over:** the same-step pair still never reaches Feast — the feature
  table holds 11 distinct steps, unchanged from M030 Q1/gap 4. Idempotence is measured across 2
  applies inside 1 process (with the imported module purged between them), not across 2 separate
  `feast apply` CLI invocations — whether a fresh process agrees is CHUA DO DUOC. `ttl`/
  `entity_columns` stay outside the checksum payload by design, so a future change to either will
  not move it. `apply_total()` is called in-process, never through a spawned `feast` binary, so a
  bug confined to the CLI's own argument-parsing layer would not be caught here. No `make`/
  `make.ps1` target exists yet for the G1 lane or for `uv sync --group feast`. Determinism is shown
  on one machine only (Windows 11, Feast 0.65.0, DuckDB pinned in `uv.lock`). Nothing is committed,
  so no commit hash exists (pending); `train` was not re-run and no M019/M026/M027 metric or
  checksum is restated. **Not claimed:** "T1 done", "Sprint 2 ready" — only the four pieces of work
  in this entry, and the three G1 criteria they made measurable, are asserted.
- Detail: [M031 log](milestones/M031-feast-feature-repo-and-g1-lane.md).

## 2026-08-03 — M030: ADR-006 Feast source Parquet and the T1 design spike

- First step of Sprint 2 T1, taken without waiting for T2: the data source only. ADR-006 decision
  1 froze the only way PaySim can supply a Feast `FileSource` — derived timestamp columns, because
  Silver carries hour ordinals and Feast validates against real timestamp columns — and assigned
  the derivation to T2's Gold projection. The project owner decided to take the source step now.
  **T1 is not done**; this milestone is the source plus the design reconnaissance that had to
  happen before any registry code.
- **New Parquet source.** `pit data build-fixture` now writes
  `data/fixtures/paysim_temporal_cases.parquet` from the same selection that produces the JSONL
  and the expected vectors: every Silver column, names and types taken straight from Silver rather
  than retyped, plus exactly 2 derived columns `event_timestamp`/`created_timestamp` at
  `pa.timestamp("us", tz="UTC")`. It is a presentation of the selection, never an input to the
  oracle. `_verify_round_trip` re-reads it and fails the build if the row identities or the
  timestamp types drift.
- **`PAYSIM_FEAST_EPOCH_0` and `paysim_step_to_timestamp` in `features/paysim_specs.py`**, the
  single implementation ADR-006 decision 1.7 requires. The Unix literal `1577836800` appears
  nowhere in the codebase. The mapping is computed in Python, not SQL: a DuckDB `TIMESTAMPTZ`
  expression is rendered against the session time zone, which would make the file depend on the
  machine that produced it.
- **`to_arrow_table`, and `combine_chunks` kept.** The first real run crashed on
  `RecordBatchReader has no attribute combine_chunks`: DuckDB's `.arrow()` returns a reader, not a
  table. `fetch_arrow_table` fixed it but is deprecated; `to_arrow_table` returns a `Table` and
  runs clean under `-W error::DeprecationWarning`, and is what the repo already used at
  `features/paysim_recipient.py:376`. `combine_chunks()` was kept rather than deleted to silence
  the error: it guarantees one chunk, so Parquet row-group boundaries follow the row count and
  never DuckDB's batching.
- **Throwaway design spike `scripts/spike_feast_t1.py`** — writes only into a temp directory it
  deletes, touches neither `feature_repo/` nor `data/fixtures/`. Its feature table is built by the
  SQL engine (importing `_prior_window_predicate` from `features/paysim_recipient.py`) so that
  comparing it against the oracle is two independent derivations, not a file compared with itself.
  Four results: **Q1** the eleven in-scope rows sit at 11 distinct steps, so the fixture's
  same-step pair never reaches the feature table — a coverage hole, not a blocker, and it corrects
  an earlier claim that the tie was T1's largest risk; **Q2** `get_historical_features` returned
  11 rows matching the oracle on every field, 0 differences; **Q3** a deliberate tie collapsed to
  exactly one row with no fan-out, but which row wins is not controlled by the project, exactly as
  ADR-006 decision 1.4 warned; **Q4** a no-op second `apply` changed both the registry file and
  serialized-proto digests (`73b76be0…` to `67ddb993…`) because the proto carries `last_updated`.
- **Finding 1 — Feast does not compute window aggregates, so the feature source must be
  precomputed.** `feast/aggregation/__init__.py:17`: "Feast-handled aggregations are not yet
  supported." `aggregation` appears nowhere in `feast/infra/offline_stores/duckdb.py` or
  `file_source.py`; a plain `FeatureView` does not accept the argument at all, `BatchFeatureView`
  and `StreamFeatureView` only store it, and `OnDemandFeatureView` transforms row-wise over
  already-retrieved inputs. Consequence: the Parquet shipped here is a *source* table, not a
  *feature* table. T1 additionally needs a precomputed table holding the twelve contract fields,
  one row per cutoff. Guide §3.2 line 117 and §4 line 148 always said so; declining to wait for T2
  does not remove that dependency, it moves the obligation into T1.
- **Finding 2 — the guide §3.3 registry checksum must come from definitions, not the registry
  blob.** Q4 shows a blob checksum moves on a no-op apply for a reason unrelated to the
  definitions, so a G1 idempotence criterion measured that way would fail permanently and
  meaninglessly. The checksum has to be canonical over entity/source/view/service and field order,
  the way `paysim_feature_contract_checksum` already works. No such function exists in `src/`.
- **Guides corrected, with the original wording preserved.** Both findings are worthless if the
  guide keeps telling the next reader to build `card_entity` and `fraud_scoring_v1` against a raw
  source. `docs/feature-store/sprint-2-implementation-guide.md` took 14 corrections — entity,
  feature service (three places), feature view schema, `FileSource`, feature spec version,
  registry checksum rule, both acceptance criteria, the `pre_decision_features` description, the
  IEEE-CIS dataset reference, the training entity dataframe columns, and the G1 row — plus 2 new
  sections §3.2.1 and §3.3.1 carrying Findings 1 and 2 into the document people actually follow.
  `docs/feature-store/sprint-3-implementation-guide.md` took 1 correction, its only stale spot.
  Every change is logged inside each guide under a `## Nhật ký hiệu chỉnh` section at the top of
  the file, quoting the original wording next to the replacement and the ADR or milestone that
  justifies it: this project exists to demonstrate lineage, so nothing is deleted silently.
  `docs/adr/` was not touched — a frozen decision changes by new ADR, not in-place edit. Left
  unchanged as historical records: `docs/reports/paysim-feature-contract-v1.md` (ADR-006 line 184
  keeps it at v1), `docs/reports/sprint-1-completion-report.md`,
  `docs/feature-store/point-in-time-feature-store-proposal.md` and
  `docs/feature-store/sprint-1-implementation-guide.md`.
- Status: verified within the scope run. Project owner ran on 2026-08-03: `.\make.ps1 lint`
  (`ruff check` all checks passed; `ruff format --check` 54 files already formatted);
  `.\make.ps1 build-fixture` twice, independently, both reporting 15 source rows and producing
  byte-identical files — `paysim_temporal_cases.jsonl`
  `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` and
  `paysim_expected_features.json`
  `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B` both unchanged from M029,
  and the new `paysim_temporal_cases.parquet`
  `6935B7EE1C0EB4133CA1EF07A11686993329FD119DB3DB4EE6A282FB997153A5` identical across both runs;
  `uv run pytest -q -rs -m integration tests/integration/test_paysim_fixture.py` (2 passed);
  `uv run python scripts/spike_feast_t1.py` (all four questions answered, none unanswered). No
  `DeprecationWarning` remains from project code; one remains from
  `ibis/backends/duckdb/__init__.py:332`, third-party and recorded rather than suppressed.
- **Not done, and not claimed: T1 is not finished.** `feature_repo/` is untouched and still holds
  exactly 2 placeholder files; no `Entity`, `FeatureView`, `FeatureService` or `feature_store.yaml`
  is committed anywhere. There is no precomputed feature table on disk — the eleven-row table Q2
  retrieved was built in memory in a temp directory that was deleted. There is no registry
  checksum in `src/`, and no G1 test lane: the spike is a script, not a test. **G1 does not pass**
  — of the three criteria in guide §3.4 only the first has been measured, and only inside the
  spike; the second cannot be measured as the guide implies until the checksum moves off the
  registry blob (whether apply is semantically idempotent is CHUA XAC DINH); the third was not
  attempted, no `FeatureService` was created. Q3's tie behaviour is observed, not a contract.
  Determinism is shown on one machine and one core count. Nothing is committed, so no commit hash
  is recorded (pending). `train` was not re-run and no M019/M026/M027 metric or checksum is
  restated.
- Detail: [M030 log](milestones/M030-feast-source-parquet-and-t1-design-spike.md).

## 2026-08-03 — M029: PaySim oracle/SQL parity lane and real-Silver fixture builder

- `src/pit_fintech/features/reference.py:3-5` has required since Sprint 1 that a DuckDB
  implementation "must match this oracle before it is accepted". For the PaySim application
  contract that comparison had never been written: the oracle and the two DuckDB paths were
  independent code paths, all green, with nothing binding them. This milestone is the first time
  the PaySim DuckDB path is compared field by field against an independent Python oracle.
- **New oracle.** `src/pit_fintech/features/paysim_reference.py` implements
  `paysim-fraud-recipient-v2` in pure Python — no DuckDB, no SQL, no library window function —
  with eligibility `prior.step < current.step AND prior.knowledge_step <= current.knowledge_step`
  (ADR-003 as amended by ADR-005), window `[current_step - window_hours, current_step)`, money in
  `Decimal` at `DECIMAL(18,2)` with `Inexact`/`Rounded` trapped, and the twelve fields in contract
  order. It fails at import if the frozen spec stops matching.
- **New parity lane.** `tests/temporal/test_paysim_oracle_sql_parity.py` drives one fixture
  (`PARITY_ROWS`) through three engines — the oracle, the diagnostic SQL in
  `features/paysim_recipient.py`, and the evidence SQL in `models/paysim_training.py` — comparing
  all twelve fields in contract order for every scored row. Agreement alone is not accepted: a
  second test pins the step-400 cutoff to a vector derived by hand, so parity means parity with the
  contract rather than two paths agreeing on the same wrong answer.
- **Finding: the same-step policy is enforced in the JOIN on *both* engines, not in the FILTER.**
  `paysim_recipient.py:278` uses `s.step <> c.step` and `paysim_training.py:565` uses
  `s.step <= c.step - 1`, both inside the `LEFT JOIN`, before any `FILTER` runs; the `FILTER`
  repeats the same bound (`paysim_recipient.py:83`, `paysim_training.py:414`) and the oracle
  enforces it again at `paysim_reference.py:371`. Consequence: **no single-clause mutation can go
  red on either engine.** An earlier draft of the lane asserted the opposite asymmetry (training
  FILTER unmasked, recipient FILTER masked); that asymmetry does not exist and the assertion built
  on it could never have failed. The lane now keeps two `*_is_masked_by_the_*` tests that record,
  as a stated limitation, which half absorbs which mutation, plus
  `test_admitting_same_step_rows_breaks_parity`, which removes both guards at once and requires
  parity to break. Reaching the join needed a new seam (`_SqlRewrite` + a `_RewritingConnection`
  proxy that rewrites statement text and raises if the rewrite never matched), because that clause
  is an SQL literal that `monkeypatch.setattr` cannot reach. The policy itself is unchanged and
  still enforced twice on each SQL path.
- **Three expected values corrected — arithmetic errors in the test, not defects in the SQL.** Each
  was recomputed by hand from `PARITY_ROWS` and the ADR-003 window definition, with the arithmetic
  written beside the assertion; no number was adjusted to match observed output and `PARITY_ROWS`
  was not touched. (a) Removing the knowledge-time clause leaks row 8 at `step 398`, which the 1h
  window `[399, 399]` cannot admit, so the assertions moved to 24h (`9644.93`) and 168h
  (`20756.03`) and 1h is now asserted unchanged. (b) Deleting the FILTER lower bound had omitted
  row 3 (`step 231`, `4444.44`) — the one row that bound was solely guarding — corrected to
  `24089.36`. (c) Admitting same-step rows also lets the cutoff row join to itself once the join
  bound is gone, so 1h is `500.50 + 3333.33 + 0.01 = 3833.84`.
- **False comment removed from production.** `src/pit_fintech/models/paysim_training.py:557-562`
  claimed the join was a "widest-window prune only" with eligibility living "entirely in the FILTER
  predicate". The join carries the event-time upper bound `c.step - 1`, i.e. half of the
  eligibility rule. Comment prose only — no SQL clause, literal or predicate changed, so no
  training metric or checksum can move because of it.
- **Fixture builder wired.** `src/pit_fintech/data/paysim_fixture.py` extracts a small
  deterministic fixture from the real Silver `paysim_transactions` Delta table (zero-history
  destination, a destination separately populating 1h/24h/168h, a same-step pair) and scores it
  with the pure-Python oracle, never with SQL — expectations computed in SQL would only compare the
  SQL against itself. Exposed as `pit data build-fixture --dataset paysim` (`cli.py:266-299`),
  `Makefile:47-48` and `make.ps1:74-75`, guarded by `tests/unit/test_paysim_fixture.py` (missing
  manifest and non-paysim dataset both exit 2 with an actionable message) and
  `tests/integration/test_paysim_fixture.py` (real path when a local manifest exists, loud skip
  when not, since the PaySim CSV is not committed and CI cannot produce it).
- **Two bugs the first real run exposed, both fixed.** (a) *The destination picker could not back
  out.* `_pick_rich_destination` committed to one destination on a loose criterion, then
  `_pick_rich_cutoff_step` applied a strictly harder one — a cutoff step with a prior row in each
  of three disjoint offset bands — and raised with no fallback, so an unlucky first pick killed the
  build (`destination C1000004940 never reaches a cutoff step where all three history windows are
  simultaneously distinguishable`). The band criterion was **not** relaxed: without a prior row in
  each of `[1,1]`, `[2,24]` and `[25,168]` step offsets the three windows can return equal counts
  and equal sums, and a swapped window or a bound off by one would pass unnoticed. Instead the
  bands are derived once from `PAYSIM_WINDOW_STEPS` and read by both SQL and Python; the exact band
  predicates are pushed into a bounded SQL self-join that returns candidates ordered by
  `destination_entity_id`; and the first candidate confirmed in Python wins, capped by
  `RICH_CANDIDATE_LIMIT = 8`. Both failure messages now report how many candidates were walked and
  why each was rejected. (b) *The integration test asserted an equality that must never hold.*
  `{event.source_row_number for event in events} == set(expected)` cannot be true: the fixture
  carries every row of the chosen destinations because history is unfiltered by transaction type,
  while `compute_paysim_feature_vectors` scores only rows in scoring scope, so the expectation file
  is a proper subset by construction. The builder's `_verify_round_trip` cannot catch drift here
  because it applies the same scope filter to both sides. Replaced with three stricter assertions —
  `set(expected) == in_scope`, `set(expected) < all_row_numbers`, and `assert history_only` so the
  fixture cannot degenerate into in-scope rows only — with the derivation written beside them.
- Status: verified within the scope run. Project owner ran on 2026-08-03: `.\make.ps1 format`
  (`ruff check --fix`:
  All checks passed; `ruff format`: 1 file reformatted, 52 files left unchanged); `.\make.ps1 lint`
  (`ruff check`: All checks passed; `ruff format --check`: 53 files already formatted);
  `.\make.ps1 test-unit` (41 passed in 1.97s, up from 39 — the new CLI guards);
  `.\make.ps1 test-temporal` (`pit data sample` validated 7 canonical events from 8 rows, snapshot
  `synthetic-temporal-v1:1ef70772400a1d8e`, then 73 passed in 4.52s, up from 47 — the parity module
  is the whole of that increase, and the unchanged snapshot id shows the synthetic ground truth was
  not disturbed).
- **Real run, after the two fixes.** On a machine holding PaySim Silver the project owner re-ran
  `.\make.ps1 lint` (`ruff check` all checks passed; `ruff format --check` 53 files already
  formatted), `.\make.ps1 test-unit` (41 passed), `.\make.ps1 test-temporal` (73 passed) and
  `uv run pytest -q -rs -m integration tests/integration/test_paysim_fixture.py` (1 passed) — the
  first execution of the builder's success path and of the integration lane. `.\make.ps1
  build-fixture` was then run twice independently: both runs reported 15 source rows and produced
  byte-identical files, `data/fixtures/paysim_temporal_cases.jsonl` SHA-256
  `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` and
  `data/fixtures/paysim_expected_features.json` SHA-256
  `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B`. The fixture holds 15 source
  rows: 11 in scoring scope with a vector, 4 history-only without one. Destinations are
  `C1000022185` (rich; steps 42, 138, 155, 157, 159, 177, 178), `C1000004940` (same-step pair, two
  rows at step 303) and `C100003532` (zero history, one row at step 397). All 4 history-only rows
  (`861131`, `1357635`, `1701770`, `4149878`) are `CASH_IN` to a `CUSTOMER` destination — they
  leave scoring scope on transaction type, not destination kind, which is the intended shape since
  history counts regardless of type.
- **Known limitation:** `set(expected) == in_scope` computes `in_scope` with the same
  `in_scoring_scope` the builder uses, so it is not an independent derivation — if the scope
  definition moved, both sides would move together. It locks the file on disk against the contract;
  `assert history_only` covers the degenerate case separately.
- **Not run, and not claimed:** nothing is committed, so no commit hash exists (pending). `train`
  was not re-run and no M019/M026/M027 metric or checksum is restated. No e2e lane exists. The
  parity lane still runs on hand-built `PARITY_ROWS` only — no test yet drives the two DuckDB
  engines against the 15 extracted rows. Determinism is shown on one machine and one core count.
  Sprint 2 T1 has not started: `feature_repo/` still holds exactly two placeholder files.
- Detail: [M029 log](milestones/M029-oracle-sql-parity-lane-and-paysim-fixture-builder.md).

## 2026-07-31 — M028: ADR-006 Feast time mapping and feature service v2 (proposed)

- Sprint 2 T1 (Feast repository, S2-A1, gate G1) is blocked on two decisions that get baked into
  the registry checksum and the online key namespace the moment the first artifact exists, so both
  are frozen in an ADR before any code.
- **Time mapping.** Feast `FileSource` requires `timestamp_field`/`created_timestamp_column` to
  name real timestamp columns; PaySim only has `step`/`knowledge_step` as `BIGINT` hour ordinals.
  Decision: derive `event_timestamp = EPOCH_0 + step hours` and
  `created_timestamp = EPOCH_0 + knowledge_step hours` with `EPOCH_0 = 2020-01-01T00:00:00Z`
  (Unix `1577836800`), mapping the frozen range 1–743 onto `2020-01-01T01:00:00Z` ..
  `2020-01-31T23:00:00Z`. The map is bijective and strictly order-preserving, so every PIT
  comparison is preserved; `EPOCH_0` is a presentation convention, not a claim that `step` is a
  business timestamp (ADR-002 decision 1 stands). Cutoff order and tie-break stay on
  `(step, source_row_number)` per ADR-001/003/005 and must not be re-expressed as timestamp
  comparison — hour-resolution timestamps cannot represent the tie-break at all.
  `features/reference.py` remains the correctness authority.
- **Service version.** `paysim-fraud-scoring-v1` -> `paysim-fraud-scoring-v2`, matching the
  FeatureSpec bump from ADR-005/M026. The twelve fields, their order, dtypes and defaults do not
  change; only the version string, and the canonical contract checksum that includes it.
- Rejected: reusing the `fraud-history-v1` synthetic fixture as the T1 target (different entity
  `card_entity_id`, 13 different features — T1 would be deleted at T2); configuring Feast to take
  an integer event time (no documented support, pre-1.0 internals); keeping v1 with a footnote.
- `pyproject.toml` gains a `feast` dependency group with `feast[duckdb,redis]>=0.65,<0.66`, kept
  out of the main `dependencies` so a Feast resolution failure cannot break the correctness test
  lanes. `requires-python >=3.11,<3.13`, `pyarrow>=21,<23` and `duckdb>=1.4,<2` are untouched.
  Every Feast release caps `uvicorn[standard]` transitively at `<=0.34.0`, so the `serving` group's
  `uvicorn[standard]` is pinned to `==0.34.0` to fit inside that shared resolution universe.
- The v1 service string moved to `paysim-fraud-scoring-v2` in 5 of the 6 listed call sites
  (`paysim_specs.py`, `config.py`, `.env.example`, `test_paysim_feature_contract.py`, `AGENTS.md`);
  `docs/reports/paysim-feature-contract-v1.md` is intentionally left at v1 as a historical record
  of what was frozen under v1.
- Status: verified. **ADR-006 accepted 2026-07-31.** Project owner ran, on 2026-07-31: `uv lock`
  (`Resolved 234 packages in 2ms`, so `uv.lock` is now in sync with `pyproject.toml`, including the
  `feast[duckdb,redis]>=0.65,<0.66` and `uvicorn[standard]==0.34.0` pins); `.\make.ps1 lint`
  (`ruff check`: all checks passed, `ruff format --check`: 48 files already formatted);
  `.\make.ps1 test-unit` (39 passed in 2.17s); `.\make.ps1 test-temporal` (`pit data sample`
  validated 7 canonical events from 8 rows, snapshot `synthetic-temporal-v1:1ef70772400a1d8e`, then
  47 passed in 3.25s). `git status --short` stayed clean after the fixture-regenerating
  `test-temporal` run, confirming that fixture step is deterministic.
- Project owner then ran, also on 2026-07-31: `uv sync --group feast --group serving`
  (`Resolved 234 packages, Prepared 30, Uninstalled 54, Installed 33` — materializing
  `feast==0.65.0`, `redis==7.4.1`, `hiredis==3.4.0`, `ibis-framework==12.0.0`, `uvicorn==0.34.0`
  (replacing `uvicorn==0.51.0`), `gunicorn`, `uvicorn-worker`, `watchfiles`, `websockets`, `dask`,
  `sqlglot`, and uninstalling `lightgbm==4.7.0`, `mlflow==3.14.0` (+skinny/tracing),
  `scikit-learn==1.9.0`, `scipy`, `joblib`, `threadpoolctl`, `matplotlib`, `skops` and their
  dependents); and `.\make.ps1 features` (`uv run pit features show --dataset paysim`), which
  re-emitted the canonical `paysim-fraud-recipient-v2`/`paysim-fraud-scoring-v2` contract checksum
  `01bba24cc79be8729ec66557bb68828fbb66a17bfefdb601aaedc1a6cee575de` (12 features) — replacing the
  `PENDING` placeholder above.
- **Operational note:** `uv sync --group feast --group serving` uninstalled the `training`/tracking
  group even though nothing intended to drop it, because `uv sync` makes the environment match
  exactly the groups named on the command line. The correct command for a full dev environment
  (including `training`) is `uv sync --all-groups`.
- Detail: [M028 log](milestones/M028-adr-006-feast-time-mapping-and-service-v2.md).

## 2026-07-29 — M027 refinement: determinism fix verified

- User-run 2026-07-29: two separate, consecutive `train` runs against rebuilt Silver
  (`silver.paysim_transactions=v6`, `silver.paysim_labels=v6`) produced the **same**
  `vector_checksum` (`ce88d250000ec529e42c03a201991ae8f69cb3e3607ad7ac4301a1d4f3216247`), training
  fingerprint `a005f4ea7dac09c19b82be2c95ac5f4afbd9d174ac19826d1a1662694dfafeef`, MLflow runs
  `d398b7e5fc474b4cb707cc7d97eda5b2` and `6d250b52cc574db9880cfd80e8aa7db2`.
- E1 PR-AUC `0.258342`, ROC-AUC `0.601620`, recall@FPR `0.275559`, precision@FPR `0.541601`; E4
  PR-AUC `0.102766`, ROC-AUC `0.784978`, recall@FPR `0.036741`, precision@FPR `0.243386`; 0
  future-read violations. Neither metric moved from the M019/M026 baseline despite the underlying
  arithmetic changing from `DOUBLE` to `DECIMAL(18,2)`.
- `.\make.ps1 test-temporal`: 47 passed (up from 33; the 14 new cases are the 7 new money-
  arithmetic/knowledge-time tests in `test_injected_pit_fixtures.py` parametrized over both PIT
  engines). `.\make.ps1 test-unit`: 39 passed.
- Notable: the old DOUBLE rounding error was small enough to never cross a LightGBM histogram-bin
  boundary — invisible to every reported metric — yet large enough to change the last bit of the
  summation and therefore `vector_checksum`. That gap is exactly why `vector_checksum` exists as
  an independent reproducibility signal rather than trusting metrics alone.
- This confirms the pass criterion M027 was left on: two separate `train` processes against the
  same Silver version now agree byte-for-byte. Confirmed on one machine/core count only; a
  different core count (which would exercise a different hash-aggregate thread/partial-sum count)
  has not yet been tried.
- Status: verified.
- Detail: [M027 log](milestones/M027-decimal-money-sums-checksum-fix.md).

## 2026-07-29 — M027: fix non-deterministic vector_checksum (sum money in DECIMAL)

- Diagnosed why three `train` runs against the same Silver v4 produced three different
  `vector_checksum` values (`ff52681f…`/`4790cffe…`/`28c5d63d…`) while E1/E4 metrics stayed
  bit-exact and `future_read_violations` stayed 0 every time: runs 2 and 3 shared the same commit
  and training component fingerprint yet still disagreed, ruling out a code/contract cause.
- Root cause: `sum(amount)` over `DOUBLE` is not order-independent, and the M026 refactor from
  `OVER (PARTITION BY ... ORDER BY step)` window frames to range-join `GROUP BY`/`FILTER`
  aggregates removed the implicit `ORDER BY` that had been pinning summation order. DuckDB's
  parallel hash `GROUP BY` merges partial sums in a run-to-run order, so rounding plus
  non-deterministic order combined for the first time. This is a regression from the M026
  refactor, not a pre-existing defect.
- Fix: added `PAYSIM_AMOUNT_DECIMAL_TYPE = "DECIMAL(18,2)"`
  (`src/pit_fintech/features/paysim_specs.py`) and moved every money `sum()` in both PIT engines
  (`features/paysim_recipient.py`, `models/paysim_training.py`) to sum in that DECIMAL type,
  casting to `DOUBLE` only at the final projection. Fixed-point addition is exact, associative and
  commutative, so a hash aggregate cannot disagree with itself regardless of merge order. Chosen
  over locking summation order, which would only constrain *how* the sum runs rather than remove
  the rounding sensitivity. Contract dtype stays `float64`; no version bump (no semantics/order/
  dtype/default changed under ADR-003's change policy).
- Added a 9th publish-blocking quality gate, `amount_decimal_roundtrip_failures`
  (`src/pit_fintech/data/paysim_lakehouse.py`): every raw `amount` must round-trip through
  `DECIMAL(18,2)` back to `DOUBLE` unchanged, or the build fails loudly instead of silently
  rounding money. `tests/integration/test_paysim_lakehouse.py` gate-count assertion moved 8 -> 9.
- Replaced `tests/temporal/test_knowledge_time_predicate.py` with
  `tests/temporal/test_injected_pit_fixtures.py` (same knowledge-time boundary/mutation coverage
  carried over), and added `test_money_sums_equal_the_exact_decimal_total` (asserts every money
  column against an independently computed `decimal.Decimal` exact total — the load-bearing
  regression test) and `test_materializing_twice_produces_identical_vectors` (weaker same-process
  reproducibility check), both parametrized over the `recipient`/`training` engines.
- Status: implemented, not verified — `build-lakehouse`/`train` have not been re-run since this
  fix was written; the pass criterion is two separate `train` runs producing an identical
  `vector_checksum`.
- Detail: [M027 log](milestones/M027-decimal-money-sums-checksum-fix.md).

## 2026-07-29 — M026 refinement: clean-data no-op regression verified

- User-run `build-lakehouse` then `train` on 2026-07-29 against rebuilt Silver
  (`silver.paysim_transactions=v4`, `silver.paysim_labels=v4`) reproduced the M019 baseline
  **bit-exact**: E1 PR-AUC `0.258342`, ROC-AUC `0.601620`, recall@FPR `0.275559`; E4 PR-AUC
  `0.102766`, ROC-AUC `0.784978`, recall@FPR `0.036741`; 0 future-read violations.
- Vector checksum `ff52681f1f6b06627b8f8c027a9277fc0bbcc0ab32fb90047effb5e578cc0ee7`, training
  fingerprint `381de46fb8e3cfea2c2f7ae31f2eb88d50059d74429a9888e47293fa8b498377`, MLflow parent
  run `d9d142db739243299cc1cb59184216a6`.
- This is the regression required by ADR-005 decision 6: it proves, not just claims, that adding
  `prior.knowledge_step <= current.knowledge_step` to both PIT engines' eligibility predicate
  changes nothing on clean PaySim data.
- The floating-point summation-order risk noted when M026 moved from window aggregates to hash
  `GROUP BY`/`FILTER` aggregates did not materialize on this run (bit-exact match), but remains
  unguarded by any test; a future checksum divergence between two runs on the same Silver version
  is the first thing to check against it.
- Status: verified.
- Detail: [M026 log](milestones/M026-paysim-featurespec-v2-implementation.md).

## 2026-07-29 — M026: Implement ADR-005 knowledge_step and PaySim FeatureSpec v2

- Bronze now emits a derived `knowledge_step BIGINT NOT NULL` column
  (`knowledge_step = step`); it propagates unchanged into `silver.paysim_transactions` since
  ADR-003 fixes `feature source: silver.paysim_transactions`.
- Bumped `PAYSIM_FEATURE_DEFINITION_VERSION` from `paysim-fraud-recipient-v1` to
  `paysim-fraud-recipient-v2`, and `created_time_policy` from `"source_has_no_created_time"` to
  the new `"derived_knowledge_step_lte_cutoff"` literal on `FeatureSetContract`.
- Moved both PIT engines (`features/paysim_recipient.py` and `models/paysim_training.py`) from
  `RANGE BETWEEN ... PRECEDING/FOLLOWING` window functions to an explicit range self-join with
  `GROUP BY`/`FILTER (WHERE ...)` aggregates, because a `RANGE` window frame can only order by one
  column and the v2 eligibility predicate needs two independent conditions
  (`prior.step < current.step AND prior.knowledge_step <= current.knowledge_step`) evaluated
  between the same row pair.
- Updated all live references to the frozen version string and "PaySim FeatureSpec v1" display
  text (`config.py`, `.env.example`, `cli.py`, `README.md`, `CLAUDE.md`, `Makefile`, `make.ps1`,
  and the corresponding unit tests); dated changelog/milestone/ADR-003 history was left unchanged
  as the record of what was frozen under v1.
- User-confirmed clean on 2026-07-29: `lint`, `test-temporal`, `test-unit` (agent did not execute
  these commands; exact pass counts were not reported and are not fabricated here).
- **Not run:** `build-lakehouse`, `train`, `test-lakehouse`. The clean-data no-op regression
  required by ADR-005 (E1 reproducing exactly `0.258342`, E4 `0.102766` from M019) has not been
  executed and remains unverified. `train` will also be blocked until `build-lakehouse` rebuilds
  Silver with `knowledge_step`, since the on-disk Silver predates this column.
- Known risk: `sum(amount)` moved from a window aggregate to a hash `GROUP BY`/`FILTER`
  aggregate, which does not guarantee the same floating-point summation order; `pit_prior_amount_*`
  may shift in the last ulp. E1 does not read through this path and must still match bit-exact.
- Status: implemented, not verified.
- Detail: [M026 log](milestones/M026-paysim-featurespec-v2-implementation.md).

## 2026-07-29 — M025: ADR-005 knowledge_step and FeatureSpec v2 (proposed)

- Added `docs/adr/005-knowledge-step-and-featurespec-v2.md`, copied verbatim from the prepared
  draft, proposing a derived Bronze `knowledge_step` column (`knowledge_step = step`, raw CSV and
  snapshot checksum unchanged) so the knowledge-time half of the temporal predicate
  (`prior.created_time <= current.created_time`) can finally be exercised on the PaySim
  application path, alongside a frozen `paysim-fraud-recipient-v2` FeatureSpec.
- ADR-005 status is `proposed`, not `accepted`. This milestone is documentation only: no change to
  `src/`, `tests/`, Bronze, Silver or the feature contract module.
- Remaining steps before any of this is implemented: accept the ADR, freeze FeatureSpec v2, run a
  no-op regression proving clean-data E1/E4 still reproduce exactly `0.258342`/`0.102766` from
  M019, then add the hand-chosen knowledge-time boundary fixture.
- Detail: [M025 log](milestones/M025-knowledge-step-and-featurespec-v2-adr.md).

## 2026-07-28 — M024: Knowledge-review remediation tests

- Added 8 oracle boundary/mutation tests to `tests/temporal/test_reference_oracle.py`: four
  fixtures pin the eligibility boundary (exactly-at-cutoff, strictly-before-cutoff,
  outside-window, same-instant-different-entity), and four mutation/differential tests prove the
  suite goes red if `order_key <` is weakened to `<=` or `created_timestamp <=` is tightened to
  `<`, all via `monkeypatch` with no `src/` changes.
- Added 2 tests to `tests/temporal/test_paysim_recipient.py`: a zero-history regression test that
  separates pre-score (cold-start) from post-score (history now visible) assertions for an unseen
  PaySim destination entity, and a feature-set regression test that fails if `E2`'s
  `EXPERIMENT_MATRIX` entry ever picks up a `pit_prior_*` column instead of the leaky columns.
- This closes the code/test half of the Q5/Q6/Q10 remediation recorded in
  `docs/reports/sprint-1-knowledge-review.md`; it does not re-score the interview, and Q1, Q2,
  Q3, Q5, Q6 and Q10 remain below D3 there.
- An earlier draft of the E2 test compared a materialized column against itself and was rejected
  during review for being tautologically green regardless of correctness; it was rewritten to
  assert directly against `EXPERIMENT_MATRIX` in `src/pit_fintech/models/paysim_lightgbm.py`.
- User-run `.\make.ps1 lint` passed (`ruff check`/`ruff format --check` clean) and
  `.\make.ps1 test-temporal` went from 23 to 33 passed, matching the 10 new tests with none
  skipped.
- Detail: [M024 log](milestones/M024-knowledge-review-remediation-tests.md).

## 2026-07-28 — M021 refinement: post-commit training reuse verified

- User-run `.\make.ps1 train` reused Silver v2 without rebuilding the lakehouse
  (`application_lakehouse_code_commit` stayed at the older `729d85f` while the trainer ran from
  `ba360fb…`), closing the item M021 was left pending on.
- Confirmed the manifest carries all three required fields: `training_component_fingerprint`
  (`f34ba2bd…`), `training_component_dirty` (`false`), `repository_dirty` (`true`, expected since
  other files were uncommitted at run time; the training component itself was clean).
- E1/E4 reproduced the frozen M019 metrics exactly from an independent run (MLflow parent
  `5705bd4d…`, vector checksum `4713896b…`, 0 future-read violations), proving reproducibility.
- Status: verified.
- Detail: [M021 log](milestones/M021-component-lineage-guard.md).

## 2026-07-28 — M022 refinement: deck visual verification passed

- User confirmed by direct visual inspection that
  `docs/reports/pit-fintech-sprint-1-report-slides.html` renders with no overflow or console
  errors, closing the deck half of M022's acceptance.
- The knowledge-review half is unchanged: the interview remains complete at 10/10 assessed
  (18/40) with Q1, Q2, Q3, Q5, Q6 and Q10 below D3, so the Sprint 1 knowledge gate still does not
  pass. M024 added the Q5/Q6/Q10 remediation test artifacts on the same date, but the interview
  itself was not re-scored.
- Status: implemented; deck visual verification passed, knowledge gate does not pass.
- Detail: [M022 log](milestones/M022-sprint-1-report-and-knowledge-review.md).

## 2026-07-28 — M023 refinement: CI green run confirmed

- User confirmed by visual inspection that the GitHub Actions `fast-fixture-ci` workflow is green
  after `uv.lock`/`pyproject.toml` were pushed, including the "Unit tests" step that previously
  failed with `ModuleNotFoundError: No module named 'numpy'`.
- Status: verified.
- Detail: [M023 log](milestones/M023-ci-dev-numpy-dependency.md).

## 2026-07-28 — M001 refinement: Redis + MLflow compose verified

- docker compose up run on 2026-07-28; redis and mlflow healthchecks both pass (confirmed by
  repository owner).
- Detail: [M001 log](milestones/M001-sprint-1-foundation.md).

## 2026-07-27 — M023: CI dev-lane numpy dependency

- Diagnosed a CI-only `make test-unit` failure (`ModuleNotFoundError: No module named 'numpy'`)
  that stayed green locally.
- Root cause: the fast-fixture lane installs only the `dev` group, but `numpy` entered the lock
  only transitively through the optional `training` group, and
  `tests/unit/test_paysim_lightgbm_spike.py` imports numpy at module top level.
- Added `numpy>=2.4,<3` to the `dev` group so the CI unit lane collects it without pulling the
  heavy `training` group; the bound matches the already-locked numpy (2.4.6 / 2.5.1).
- Rejected module-level `importorskip` (would skip the whole spike module and its fixed-FPR
  correctness tests) and rejected adding `training` to CI (violates the fast-lane intent).
- Status: implemented; green CI run pending after `uv.lock` is re-locked and committed.
- Detail: [M023 log](milestones/M023-ci-dev-numpy-dependency.md).

## 2026-07-27 — M022: Sprint 1 report deck and knowledge review

- Added a seven-slide HTML Sprint 1 report using the proposal deck's visual system.
- Structured the narrative around verified outcome, PaySim data decision, frozen FeatureSpec,
  temporal oracle evidence, application path, honest E1/E4 result and Sprint 2 handoff.
- Added a closed-note ten-question knowledge review with D0–D4 scoring, hard-invariant flags and
  explicit pass criteria.
- Interview Q1 scored D2: the three invariant intents and no-release decision were correct, but
  evidence mapping, vector-parity wording and atomic/idempotent backfill lineage were incomplete.
- Interview Q2 scored D2: eligible history, count, sum and late/entity exclusions were correct;
  canonicalization, dedup retention, recency and post-score state were incomplete.
- Interview Q3 scored D1: the late row was correctly excluded as unknowable at decision time,
  but event/knowledge/processing time definitions, watermark and same-cutoff rebuild were missing.
- Interview Q4 scored D2: origin sparsity, destination choice and AMBER engineering scope were
  understood; additional quantitative evidence and a precise no-model-lift claim remain.
- Interview Q5 scored D2: full-history leakage surviving any split boundary and the future-read
  violation were correctly named, and the initial positive-control inversion was self-corrected;
  leakage taxonomy (within-row vs across-split), the training/serving parity consequence and
  control-logic reasoning under a changed assumption remain incomplete.
- Interview Q6 scored D2: the `<`-to-`<=` mutation and its violation were correctly named;
  oracle-as-store framing, missing non-clock divergence causes and no boundary test design
  remain.
- Interview Q7 scored D2: the raw-to-Gold flow and DuckDB/Delta/Parquet capability split were
  correct; the Gold grain shift, the Parquet columnar model and the Delta-as-transaction-log
  relationship remain incomplete.
- Interview Q8 scored D2: Git commit, Delta version, snapshot ID and checksum were correctly
  named; the fingerprint's lineage role, the ADR-004 rationale and the coordinates-versus-
  detectors split remain incomplete.
- Interview Q9 scored D2: E4's higher ROC-AUC and the PIT-feasibility framing were correct; the
  FPR/precision mechanism, the correct E1/E4 subset relation and the PaySim static signal remain
  missing.
- Interview Q10 scored D1: the unknown-evidence caveat was honest, but the zero-history failure
  case, its exact offset and a regression test were not produced.
- Interview complete at 10/10 assessed (total 18/40). Hard-invariant questions Q1, Q2, Q3, Q5,
  Q6 and Q10 remain below D3, so the Sprint 1 knowledge gate does not pass; remediation is
  required.
- Static structure and evidence reconciliation pass; direct `file://` browser rendering was
  policy-blocked, so visual confirmation and the interactive user interview remain.
- Detail: [M022 log](milestones/M022-sprint-1-report-and-knowledge-review.md).

## 2026-07-27 — M021: Component-scoped lineage guard

- Replaced repository-wide trainer/lakehouse commit equality with exact source-contract checks
  plus separate component fingerprints.
- Added explicit lakehouse and training path boundaries, scoped dirty-state guards and
  repository-wide dirty metadata.
- Kept legacy clean manifests readable while conservatively rejecting legacy dirty manifests.
- Updated CLI, notebook 05, ADR-004 and training documentation to explain that documentation-only
  commits do not require a lakehouse rebuild.
- Added unit contracts for fingerprint scope, different clean commits and dirty-component
  rejection; extended the fixture lakehouse contract for new lineage fields.
- User verification passed unit 39/39, lakehouse 4/4 and notebooks 5/5.
- Inspected legacy Silver v2 and completed pre-M021 run `6f8859…`; both are clean but correctly
  lack the new optional fingerprint fields.
- A later train attempt was correctly blocked because M021 component files were still
  uncommitted. Status: implemented; post-commit CLI reuse and new fingerprint evidence remain.
- The first commit attempt passed all guards except Ruff format, which made formatting-only
  changes to two lineage files and correctly required review/restaging.
- Detail: [M021 log](milestones/M021-component-lineage-guard.md).

## 2026-07-27 — M020: Sprint 1 closure

- Reconciled all nine Sprint 1 release gates against the accepted PaySim ADRs, source files,
  user-provided command outputs and immutable runtime manifests.
- Added a completion report that freezes dataset, exact Silver v1, FeatureSpec checksum, clean
  code commit, training-vector checksum and MLflow run lineage for Sprint 2.
- Consolidated the full PaySim snapshot, missingness/quality checks, transaction distribution,
  entity viability and leakage inventory into a standalone application-data report.
- Kept E4's weaker PR-AUC/fixed-FPR outcome as an explicit PaySim utility limitation rather than
  tuning after seeing test results.
- Returned notebook 05 to its exact output-free source object; MLflow and JSON manifests remain
  the authoritative run evidence.
- Clarified that Sprint 1 is complete while online parity, atomic/incremental backfill, Redis,
  serving, replay and model lifecycle remain Sprint 2/3 gates.
- Status: verified. No model, notebook, test or data pipeline was executed by the agent.
- Detail: [M020 log](milestones/M020-sprint-1-closure.md).

## 2026-07-27 — M019: Silver-based LightGBM training baseline

- Started the final Sprint 1 baseline from exact Silver Delta transaction and label versions.
- Fixed the experiment boundary to E1 static/temporal versus E4 PIT/temporal with one shared,
  deterministic CPU-only LightGBM configuration.
- Validation and test keep natural prevalence; only train negatives may be deterministically
  downsampled, with the policy captured in the training manifest.
- The reusable implementation lives in `src/`; notebook 05 only calls and explains that
  implementation.
- Implemented exact manifest-recorded Silver time travel, schema/row/identity/contract gates,
  strict-step 1h/24h/168h vectors and zero-future-read publication blocking.
- Implemented deterministic train-only negative sampling while leaving all validation/test rows
  at natural prevalence.
- Implemented fixed-config E1/E4 LightGBM training with validation-only fixed-FPR thresholding,
  pandas feature-name parity, MLflow `skops` models, feature importance and a validated lineage
  manifest.
- Added `pit model train`, Make/PowerShell `train`, fixture/unit contracts and notebook 05 with a
  cell-by-cell reading guide.
- Notebook 05 is review-only unless `PIT_NOTEBOOK_RUN_TRAINING=1`; notebook 04's training flag
  was restored to false. The notebook verifier forcibly disables that environment flag for its
  child kernels and restores it afterward.
- Clean training rejects dirty or mismatched trainer/lakehouse commits. The verified v0
  lakehouse is therefore feasibility evidence; it must be rebuilt once after the M019 commit.
- User-run unit verification passed 34/34 in 5.72 seconds; exact-Silver fixture integration
  passed 4/4 in 3.59 seconds; both returned exit `0`.
- User-run notebook verification passed notebooks 01–05 with exit `0`. Windows ZMQ/TCP messages
  were non-blocking local-kernel warnings.
- The pasted full v0 lakehouse output is retained as previously verified M018 feasibility
  evidence, not misclassified as the required post-M019 clean rebuild.
- The first commit attempt passed Ruff check and all safety/governance guards; Ruff format
  reformatted notebook 05, the training module and two test files, correctly stopping the commit
  for review and restaging.
- Commit `6e93e7f` then passed every pre-commit guard and left a clean worktree.
- User rebuilt Bronze/Silver as exact Delta v1 from the same clean commit and ran notebook 05 in
  train-and-review mode.
- Completed MLflow parent `e1ebc167813e40b88f16c6e611decea7` with 322,461 vectors, all 8,213
  PaySim fraud rows, checksum `c7f075…` and zero future reads.
- Reconciled train/validation/test to 205,781/78,701/37,979 rows; validation and test retain
  natural prevalence.
- E1 reached test PR-AUC 0.258342, ROC-AUC 0.601620 and recall 0.275559 at observed FPR
  0.007951. E4 reached PR-AUC 0.102766, ROC-AUC 0.784978 and recall 0.036741 at observed FPR
  0.003894.
- Confirmed both child runs, feature artifacts, pinned MLmodel environments and pickle-free
  skops model files.
- Notebook 05 executed all eight code cells without errors. Integer-nullability and missing-pip
  messages are non-blocking MLflow environment/signature warnings; no feature-name warning,
  lineage mismatch or cutoff violation occurred.
- Status: verified. E4's lower PR/operating-point result is retained without tuning.
- Detail: [M019 log](milestones/M019-silver-training-baseline.md).

## 2026-07-27 — M018: PaySim application Bronze/Silver lakehouse

- Started the Sprint 1 application path from the immutable PaySim CSV snapshot to versioned
  Bronze transactions, label-free Silver transactions and separate Silver labels.
- Fixed the implementation boundary to DuckDB/Arrow streaming, deterministic snapshot and row
  lineage, synthetic-day partitioning, exact Delta versions and ADR-003 checksum linkage.
- Kept the synthetic oracle builder independent and deferred multi-table atomic backfill to
  Sprint 2.
- Added eight publish-blocking source/schema/value gates and deterministic source-row lineage.
- Added DuckDB ordered record-batch streaming into snapshot-scoped, synthetic-day-partitioned
  Delta tables without constructing a full PyArrow table in Python.
- Added an application manifest carrying raw/feature/code lineage, exact Delta versions,
  schema/ordered-stream checksums, gate observations and lightweight resource evidence.
- Rehashes the raw file after Delta writes and suppresses manifest publication if the source
  changed during execution.
- Added immutable per-version manifests plus an atomically replaced latest-manifest.
- Wired `build-lakehouse` and `lakehouse-history` for PaySim through CLI, Make and PowerShell.
- Added fixture integration contracts for schema, forbidden-field isolation, deterministic
  rerun, version increment, old-version time travel, manifest history and publish-blocking bad
  amounts.
- Added the human-readable application-lakehouse report and refreshed the Sprint 1 gate/handoff.
- User-run unit verification passed 30/30 in 3.55 seconds; fixture lakehouse verification passed
  3/3 in 4.10 seconds, both with exit code `0`.
- The fixture run exposed six non-blocking warnings from deprecated DuckDB
  `fetch_record_batch()`. Migrated the streaming boundary to
  `to_arrow_reader(batch_size)`.
- Clean user rerun then passed all three integration tests in 3.35 seconds with exit code `0`
  and no warnings. The fixture gate is verified; full-data execution remains pending.
- Full user-run build passed the 23-test temporal prerequisite and published three Delta v0
  tables, each containing all 6,362,620 PaySim rows, with 8/8 quality gates passing.
- Recorded 56.29 seconds, 113,030 rows/s, 649,248,646 active Delta bytes, 31 partitions and
  process RSS growth from 74,981,376 to 519,098,368 bytes.
- Read back and validated the completed manifest, full schema/logical checksums, three Delta
  roots and immutable v0 manifest. The recorded `115e98d...-dirty` boundary is accepted for
  feasibility evidence but not a final clean baseline.
- Status: verified. No runtime command was executed by the agent; all runtime evidence came from
  the user's commands and persisted manifest.
- During the authorized combined M016–M018 commit, pre-commit Ruff fixed four lint findings and
  formatted nine Python/notebook files, correctly stopping the first attempt for review/restage;
  all non-Ruff safety and milestone guards passed.
- Detail: [M018 log](milestones/M018-paysim-application-lakehouse.md).

## 2026-07-27 — M017: Freeze PaySim FeatureSpec v1

- Added a separate PaySim application contract without mutating the synthetic
  `fraud-history-v1` temporal-oracle contract.
- Frozen `paysim-fraud-recipient-v1` and service `paysim-fraud-scoring-v1` for
  `CASH_OUT`/`TRANSFER` rows with customer destinations.
- Locked the ordered 12-field E4-safe vector: three request-time fields plus destination count,
  amount sum and cold-start indicators at 1h, 24h and 168h.
- Locked `prior_step < current_step`, same-step exclusion, `source_row_number` tie-break lineage
  and `read -> score -> update`.
- Excluded label, policy output, all balance fields and every E2 leaky control.
- Added a validated cross-feature contract, canonical checksum, public feature-repository
  exports, aligned application configuration and LightGBM feature-order reuse.
- Added `pit features show`, `make features` and `.\make.ps1 features`, plus unit contracts for
  identity, ordering, windows, forbidden inputs, checksum sensitivity and CLI output.
- Added ADR-003 and a human-readable FeatureSpec report.
- User-run `.\make.ps1 features` passed with 12 feature rows, contract version
  `paysim-fraud-recipient-v1` and checksum
  `5b4e2b6db613f28dd6da209c50a5c3beb82969247e0248d39007bea9c9c26cf4`.
- User-run temporal verification passed 23/23 in 1.97 seconds, and notebook verification passed
  notebooks 01–04 with exit code `0`. Kernel/ZMQ messages were non-blocking local warnings.
- The first unit run had 29 passes and one failure in the CLI smoke test because Rich wrapped a
  long feature name under `CliRunner` capture. Added stable `feature_count: 12` CLI metadata and
  changed the smoke assertion to that scalar.
- The user confirmed the corrected `.\make.ps1 test-unit` suite passed. Together with the
  contract CLI, temporal and four-notebook results, this verifies M017. Exact unit count and
  duration were not supplied and are intentionally not inferred.
- Detail: [M017 log](milestones/M017-paysim-feature-contract-v1.md).

## 2026-07-27 — M016: Standalone PaySim LightGBM candidate spike

- Added a reusable, CPU-only PaySim LightGBM workflow for the predeclared E1–E4 matrix:
  static/temporal, leaky/random, PIT/random and PIT/temporal.
- Reused the verified destination-centric PIT computation and kept label, balances and the
  existing policy output outside E1/E3/E4 model inputs.
- Fixed the diagnostic cohort policy to all eligible fraud plus at most 5,000 deterministic
  non-fraud rows per split/type; documented that oversampling invalidates production-prevalence
  metric claims.
- Added validation-threshold selection at fixed FPR, PR-AUC/ROC-AUC/recall/precision evidence,
  deterministic LightGBM parameters and process time/RSS fields.
- Added local SQLite-backed MLflow tracking with one parent and four child runs, a separate local
  model-artifact directory, feature lists and a validated JSON manifest carrying
  dataset/code/lock/dependency versions.
- Added `pit model spike`, `model-spike`, `lab-training` and their PowerShell equivalents without
  requiring Redis, Docker or a running MLflow server.
- Added notebook 04 as a thin review/manual-execution surface; reusable logic remains in `src/`.
- Added unit contracts for the experiment matrix, forbidden lineage, recipient candidate table
  and manifest discovery/round-trip.
- Recorded the first user runtime attempt, which stopped before training with a missing
  `resolve_project_root` CLI import; added the import and a regression smoke test that exercises
  command wiring through dataset discovery.
- Recorded the second user runtime attempt, which reached MLflow initialization but exposed the
  current MLflow rejection of legacy filesystem tracking stores. Replaced the standalone default
  with `artifacts/mlflow/tracking.db` (SQLite) plus an explicit local artifact directory; no
  environment opt-out or service container is required.
- Recorded the third user runtime attempt, which initialized SQLite and began LightGBM but found
  no finite positive-prediction threshold within the 1% validation FPR budget. Added a finite
  zero-positive fallback with an explicit manifest/MLflow policy and a regression test; also
  migrated validation data to LightGBM's installed `eval_X`/`eval_y` API.
- Recorded the fourth user runtime attempt, which trained the first candidate but was rejected
  at MLflow model serialization because `skops` requires explicit trust for third-party
  LightGBM types. Kept pickle-free serialization and added a minimal three-type allowlist plus
  a unit contract; no global or wildcard trust bypass was introduced.
- User-run `.\make.ps1 model-spike` then completed E1–E4 with exit code `0`, parent run
  `0407debd24294c01a1d040f6aa33cc95` and a validated manifest for 38,213 cohort rows / 8,213
  fraud rows on snapshot `paysim1:16910f90577b0d98`.
- Verified all four child run IDs and logged `skops` model directories. E4 PIT/temporal reached
  PR-AUC `0.324524`, ROC-AUC `0.714972`, recall `0.202875` and observed test FPR `0.001500`;
  these remain sampled-cohort candidate metrics rather than production-prevalence claims.
- M016 standalone model-spike runtime and evidence contract are verified. FeatureSpec v1,
  PaySim Bronze/Silver and the clean locked baseline remain Sprint 1 work.
- Rewrote notebook 04 after a successful manual run had been saved with training enabled and
  verbose non-blocking warnings. The checked-in notebook is now review-first, defaults to
  `RUN_TRAINING=False`, contains no saved runtime output, explains the E1–E4 comparisons and
  exposes manifest lineage/resource evidence. A subsequent user-run notebook verifier passed
  notebooks 01–04 with exit code `0`.
- Updated the research protocol, README and handoff rules. No model, notebook, test, formatter,
  linter or pipeline command was executed by the agent during that rewrite; user-run model and
  notebook evidence now keep M016 verified.
- Detail: [M016 log](milestones/M016-lightgbm-candidate-spike.md).

## 2026-07-27 — M015: Destination-centric PaySim leakage prototype

- Replaced notebook 03's sparse `nameOrig` comparison with ADR-002-aligned customer-destination
  history over conservative 1h/24h/168h windows.
- Separated strict PIT, current-inclusive update-before-score, future contribution, centered
  leaky control and lifetime full-history control so current and future leakage are measurable
  independently.
- Added reusable DuckDB computation in `src/`, a safe strict-PIT projection, explicit cold-start
  indicators, fixed PaySim split defaults and multi-field target/vector identity guards.
- Added a hand-calculated recipient temporal fixture and nine test functions covering same-step
  exclusion, inclusive lower boundary, cold defaults, repeated-origin isolation, deterministic
  reruns, split assignment, positive controls, safe lineage and invalid input.
- Rewrote notebook 03 as 16 cells with compact JSON evidence, a guaranteed non-empty example and
  an explanatory ±168-hour timeline.
- Initial static JSON/style/semantic reviews found no blocker; runtime verification was delegated
  to the user as required by the project workflow.
- User-run `.\make.ps1 test-temporal` cleanly completed 23/23 temporal tests in 2.11 seconds with
  exit code `0` after replacing the deprecated DuckDB call.
- User-run `.\make.ps1 test-notebooks` passed notebooks 01–03 with exit code `0`. The Windows
  ZMQ/TCP kernel messages are runtime warnings rather than notebook failures.
- Saved notebook 03 evidence covers 38,213 deterministic cohort rows, records zero strict-PIT
  cutoff violations for 1h/24h/168h, and detects future contributions in
  4.3755%/23.5731%/40.2376% of rows respectively.
- The notebook also preserves a non-empty cutoff example and all four timeline relations:
  `PIT_PRIOR`, `TARGET_CURRENT`, `SAME_STEP_EXCLUDED` and `FUTURE_UNAVAILABLE`.
- M015 is verified. Static/PIT model training and MLflow evidence remain a separate Sprint 1
  deliverable.
- Detail: [M015 log](milestones/M015-destination-leakage-prototype.md).

## 2026-07-27 — M014: Keep PaySim as the primary pipeline workload

- Accepted `docs/adr/002-paysim-dataset-entity-scope.md` after the user confirmed the project is
  engineering/pipeline-first rather than an attempt to maximize fraud-model accuracy.
- Locked PaySim status as `AMBER_CORRECTNESS_ONLY`: suitable for PIT correctness, reproducible
  backfill, replay, parity and serving evidence, without claiming stable historical-feature model
  lift across the complete population.
- Locked hourly `step`, deterministic `(step, source_row_number)` ordering, conservative
  strict-step model-utility evidence, customer destination history, 1h/24h/168h windows and
  chronological splits 1-520 / 521-631 / 632-743.
- Kept static request features and explicit cold-start behavior for all transactions; recipient
  history is primarily a `CASH_OUT` experiment while fraud `TRANSFER` remains a cold path.
- IEEE-CIS is now an optional thesis/model-utility viability spike, not an MVP replacement.
- Marked M009 PaySim EDA and the dataset/entity ADR verified; persisted the decision in
  `AGENTS.md`.
- Detail: [M014 log](milestones/M014-paysim-application-decision.md).

## 2026-07-27 — M009 refinement: cross-role PaySim account-history EDA

- Confirmed from user-run commands that the full PaySim snapshot is available and reproducible:
  `paysim1:16910f90577b0d98`, 493,534,783 bytes, 6,362,620 rows and steps 1–743.
- Confirmed that the pre-refinement versions of all three PaySim notebooks executed successfully
  on the full snapshot with exit code `0`.
- Extended notebook 02 beyond separate `nameOrig`/`nameDest` cardinality. It now unifies `C...`
  customer identities across sender and receiver roles while keeping `M...` merchants separate.
- Added account-role overlap, row-level prior-history coverage by transaction type/fraud label,
  and a diagnostic test for a linkable `TRANSFER -> CASH_OUT` mule sequence.
- Kept `isFraud` restricted to retrospective coverage analysis; it is explicitly prohibited from
  deployable feature computation.
- User-run `Restart Kernel and Run All` completed all 10 code cells without errors. Only 1,769
  customer accounts (0.0256%) appear in both roles; prior history for the current origin remains
  approximately 0.15–0.27% across transaction/label groups.
- The diagnostic found 0 of 4,116 fraudulent cash-outs with a linkable earlier incoming transfer.
  This falsifies a linkable mule-chain assumption for this CSV but does not disprove the simulator
  scenario itself.
- Added the final PaySim dataset gate: current-destination history at conservative 1-hour,
  24-hour and 7-day windows, separated by destination kind, transaction type, label and temporal
  split. The table also quantifies how much same-hour CSV ordering would inflate coverage.
- Predeclared a GREEN/AMBER/RED decision over customer `CASH_OUT`/`TRANSFER` slices before seeing
  the outputs: keep PaySim as primary, retain it only for correctness/engineering evidence, or
  trigger an IEEE-CIS viability spike.
- User-run `Restart Kernel and Run All` completed all 13 code cells in order with no saved error
  or traceback. Fraud `CASH_OUT` has 7-day warm counts 2,058/186/101 and coverage
  70.9655%/31.5254%/16.1342% across train/validation/test, so it is AMBER under the frozen rule.
- Fraud `TRANSFER` has only 4/0/0 warm rows and 0.1388%/0%/0% coverage, so it is RED. With no
  GREEN slice and one AMBER slice, the deterministic dataset result is
  `AMBER_CORRECTNESS_ONLY`: retain PaySim for PIT/MLOps correctness, but do not claim stable
  historical-feature model value across the full fraud problem.
- The saved Arrow representation truncates the literal final gate columns, but the visible
  numeric inputs uniquely determine the classifications above; a compact machine-readable
  decision artifact remains a later evidence improvement.
- Detail: [M009 log](milestones/M009-paysim-eda-notebooks.md).

## 2026-07-24 — M013: Proposal deck title consistency

- Synchronized the slide 1 title with slide 2 as `PIT-Correct Feature Platform for Fraud
  Detection`.
- Preserved the four-slide engineering-only pitch structure and all existing architecture content.
- Detail: [M013 log](milestones/M013-proposal-deck-title-consistency.md).

## 2026-07-24 — M012: Engineering-only proposal deck

- Removed thesis-ready language and the separate thesis extension card from the four-slide pitch
  deck at `docs/reports/pit-fintech-proposal-slides.html`.
- Reframed slide 4 around the actual six-week engineering/MLOps outcome: a runnable local feature
  platform with PIT correctness, parity, reproducible backfill, replay/recovery and evidence-backed
  handoff.
- Updated the slide 2 scope chip and slide 4 footer to remove thesis positioning while preserving
  the existing PIT architecture, observability and project scope.
- Removed the unused research-card CSS and kept the deck as a four-slide engineering pitch.
- Detail: [M012 log](milestones/M012-engineering-only-proposal-deck.md).

## 2026-07-24 — M011: Deep knowledge and oral-defense checklist

- Added `docs/reports/knowledge-defense-checklist.md` to define what the project author must
  understand after each sprint, separately from what the implementation has verified.
- Introduced a D0–D4 depth rubric and four observable checks: explain, draw/calculate, break with
  a counterexample, and prove with repository evidence.
- Made Sprint 1 deliberately detailed around grain/entity/order, event and knowledge time,
  cutoff/window semantics, leakage, independent oracle design, storage boundaries and debugging.
- Added Sprint 2 gates for feature contracts, atomic/idempotent/reproducible backfills, replay,
  Redis state, parity and model lifecycle; added Sprint 3 gates for experiments, incidents,
  observability, scale transfer and research honesty.
- Added 24 randomized oral-defense prompts, non-compensable core topics, shallow-understanding red
  flags and a repeatable closed-note review form.
- Cross-linked the knowledge checklist from the existing implementation/evidence scorecard.
- Detail: [M011 log](milestones/M011-knowledge-defense-checklist.md).

## 2026-07-23 — M009 refinement: notebook-safe PaySim path resolution

- Fixed the loader bug where `Path.cwd()` caused kernels launched from `notebooks/` to search
  under `notebooks/data/raw/`.
- Added repository-root discovery by walking parents to `pyproject.toml`; the loader and setup
  instructions now normalize any supplied working directory.
- Updated all three PaySim notebooks to use the resolved repository root.
- Verified five PaySim unit tests, including a notebook-directory regression case; all three
  notebooks execute against the schema fixture and Ruff passes. The user's full PaySim EDA was
  intentionally not run.
- Detail: [M009 log](milestones/M009-paysim-eda-notebooks.md).

## 2026-07-23 — M010: PaySim raw snapshot Make target

- Added `data-snapshot` to GNU Make and the Windows PowerShell companion so the user can freeze
  the PaySim input through the project command contract.
- Added a dedicated CLI snapshot operation that validates schema, computes the full SHA-256,
  profiles row count and step range, and atomically writes a machine-readable manifest under a
  checksum-addressed artifact directory.
- Kept data acquisition manual and kept snapshotting read-only with respect to the raw CSV.
- Verified idempotency on a temporary PaySim-schema CSV: the same input produces the same
  snapshot ID, manifest path and manifest content.
- Evidence: four PaySim unit tests and the full 27-test suite pass; Ruff check/format and
  `git diff --check` pass; PowerShell help exposes the new target. The full PaySim snapshot
  command was intentionally not run because that is the next user learning action.
- Detail: [M010 log](milestones/M010-paysim-raw-snapshot-target.md).

## 2026-07-23 — M009: PaySim EDA notebooks and profile boundary

- Replaced the three synthetic/mock Sprint 1 notebooks with real PaySim workflows for snapshot
  profiling, temporal/entity viability, and leakage auditing.
- Added a reusable PaySim module that discovers the raw CSV, validates the exact 11-column
  schema, computes SHA-256 snapshot identity, opens a lazy DuckDB view, and emits a
  machine-readable profile.
- Extended `pit data profile --dataset paysim` and the Windows `profile -Dataset paysim`
  boundary; documented default path, shell environment and `.env` configuration.
- Encoded the Kaggle source warning as a baseline leakage policy: balance columns are excluded,
  `isFraud` is label-only, and `isFlaggedFraud` is an existing policy output rather than neutral
  request context.
- Verified all notebook SQL against a committed schema-only test fixture and verified the
  missing-data path does not substitute synthetic data. Full PaySim EDA remains unverified until
  the authorized Kaggle CSV is present and its checksum/results are recorded.
- Evidence: 26 pytest cases pass; Ruff check and format pass; three notebooks pass in both
  execution modes; CLI fixture profile emits `paysim1:b40a4eb1c8971b54`.
- Detail: [M009 log](milestones/M009-paysim-eda-notebooks.md).

## 2026-07-23 — M007 refinement: shorter meetup delivery

- Reduced each slide to one memorable claim and removed repeated explanations from the spoken
  path.
- Rebalanced the timing to a 9:20 target plus 40 seconds of buffer while retaining slide 3 as
  the deepest technical section.
- Preserved the DuckDB/Delta role boundary, optional Feast/custom workaround, chronological
  replay parity and honest verified-versus-planned status.
- Moved six concise mentor prompts into an explicitly optional Q&A section.
- Verified four slide headings, four explicit closing claims, six optional Q&A prompts, and the
  required evidence-boundary, DuckDB/Delta, Feast and narrow-scope statements; `git diff --check`
  passes with working-copy line-ending warnings only.
- Detail: [M007 log](milestones/M007-meetup-speaker-script.md).

## 2026-07-23 — M007 refinement: DuckDB and Feast trade-offs

- Rebalanced slide 3's talk track away from definitions of atomicity, idempotency and
  reproducibility and toward the architecture decisions the presenter expects to defend.
- Explained DuckDB as an embedded analytical fit for the local file-first scan/window/join/
  aggregate workload while keeping PostgreSQL as a valid server-oriented alternative.
- Explained Feast as an optional thin contract/retrieval/materialization boundary rather than a
  correctness dependency, and listed the custom FeatureSpec/provider/materializer/version-gate
  responsibilities required without it.
- Added mentor Q&A for DuckDB versus PostgreSQL and Feast versus a custom implementation.
- Verified the current DuckDB and Feast documentation boundaries, the revised talk-track content
  and timing density; `git diff --check` passes with working-copy line-ending warnings only.
- Detail: [M007 log](milestones/M007-meetup-speaker-script.md).

## 2026-07-23 — M008: Vietnamese PIT terminology catalog

- Added `docs/reports/catalog.md`, a project-specific glossary for the English terminology in the
  proposal deck and ten-minute speaker script.
- Anchored the explanations in one transaction-at-10:00 example and explained `temporal view` as
  offline historical reconstruction versus online pre-decision state.
- Distinguished event time from knowledge time, pre-decision features from post-event state, PIT
  join from temporal split, parity from freshness, and atomicity from idempotency and
  reproducibility.
- Added role boundaries for DuckDB, Delta, Feast, Redis, FastAPI, MLflow and the observability
  stack, plus a Vietnamese replacement cheat sheet and five meetup-ready sentences.
- Verified the required core terms, timeline example, technology-role table, Vietnamese cheat
  sheet and five meetup-ready sentences; `git diff --check` passes with working-copy line-ending
  warnings only.
- Detail: [M008 log](milestones/M008-pit-term-catalog.md).

## 2026-07-23 — M007: Ten-minute PIT meetup speaker script

- Added a speaker-ready Markdown talk track for the four-slide proposal deck under
  `docs/reports/`.
- Allocated the ten-minute narrative around the three invariants, the score-before-update causal
  path, the two temporal views, and oracle/parity/backfill evidence instead of listing tools.
- Added delivery cues, transitions, status-safe language, six presentation caveats and concise
  answers to likely mentor questions.
- Corrected the target observability flow verbally to
  `Application -> OTel Collector -> Prometheus -> Grafana` without modifying the source deck.
- Verified four timed slide sections, delivery cues, caveats, status boundaries and mentor Q&A;
  `git diff --check` passes with working-copy line-ending warnings only.
- Detail: [M007 log](milestones/M007-meetup-speaker-script.md).

## 2026-07-22 — M006: Evidence-based project self-review checklist

- Added a reusable checklist for end-of-sprint, pre-demo and final self-review under
  `docs/reports/`.
- Separated 13 non-negotiable release gates from a weighted 100-point maturity score so temporal
  leakage, parity, reproducibility or version failures cannot be hidden by aggregate scoring.
- Covered data understanding, temporal/incremental correctness, storage/reconciliation/schema
  change, Python/SQL/SWE, model lifecycle, online serving, observability/incident response and
  research/scale reasoning.
- Added explicit checks for source-to-target reconciliation, compatible and breaking schema
  evolution, incident/postmortem practice and scale-up design without expanding the mandatory
  runtime stack.
- Defined honest outcome labels from concept/demo through verified local MVP, engineering
  portfolio-ready and thesis-ready candidate; none imply production readiness.
- Detail: [M006 log](milestones/M006-project-self-review-checklist.md).

## 2026-07-22 — M003 refinements: Problem framing, architecture visual and output direction

- Replaced the text-heavy six-stage cards on slide 3 with the user-authored high-level
  architecture image at `docs/architecture/pipeline.png`.
- Reframed slide 2 around two execution problems and one cross-cutting reliability concern:
  offline fraud-model training, online fraud-score serving, and observability across both paths.
  The observability card makes the `OTel -> Prometheus -> Grafana` path explicit, while a single
  shared PIT Feature Platform bar retains parity/contract ownership without duplicating slide
  3's architecture detail.
- Expanded slide 2 for speaker depth: the full project name is now the headline, the objective
  explicitly connects leakage-free training to cutoff-correct serving, and four scope anchors
  cover PaySim EDA-first, local CPU/zero mandatory cost, six weeks/three sprints, and the
  Engineering-to-thesis direction.
- Kept the four-slide structure, title, navigation and existing visual system; the image is
  referenced by a portable repo-relative path and includes intrinsic dimensions and accessible
  alternative text.
- Verified slide 3 at 1440x810: image loads at its native 1457x626 dimensions, renders at
  approximately 1282x551, remains within the slide, and produces no console/page errors.
- Reframed slide 4 from three parallel directions into two sequential outcomes: first a
  job-ready Engineering/MLOps system, then an E2E thesis-ready research extension of the same
  codebase. The E2E e-commerce prediction thesis baseline is named as the completeness reference,
  not as the target domain.
- Removed “Experience” as a standalone outcome and replaced the closing statement with the path
  `build system -> prove correctness -> package as an E2E thesis`.
- Verified slide 4 at 1440x810: two equal 639x248 cards, no card/slide overflow, and zero
  console/page errors.
- Verified slide 2 at 1440x810: two equal 639x218 cards, shared-platform bridge visible, no
  card/slide overflow, and zero console/page errors.
- Re-verified the expanded slide 2: three execution/observability cards and four scope chips
  render at 1440x810 without overflow or browser errors.
- Detail: [M003 log](milestones/M003-proposal-html-deck.md).

## 2026-07-22 — M005: Sprint scope and runtime-boundary refinement

- Updated the authoritative sprint plan and Sprint 2/3 guides from the architecture decisions
  made during review.
- Fixed replay to one logical Transaction Producer/Replay Driver backed by a deterministic
  in-memory iterator/queue; event `t` must finish score and post-score commits before `t+1`.
- Kept Bronze/Silver/Gold medallion processing in the offline CLI/Makefile path and out of the
  synchronous FastAPI request path; JupyterLab remains an EDA/experiment environment only.
- Retained Feast as a thin versioned contract/retrieval/materialization layer, with DuckDB as
  compute, Delta as offline source of truth, Redis as online store, and the custom PIT oracle as
  correctness authority.
- Confirmed local CPU training and FastAPI/Uvicorn reference serving; Ray Train, Ray Tune and
  Ray Serve are excluded unless future benchmarks justify distributed execution.
- Excluded Kafka/Redpanda/RabbitMQ/Redis Streams, Debezium and Superset from the six-week MVP.
- Moved optional Sprint 3 observability runtime to a separate VPS/ops boundary:
  application OTLP -> OTel Collector -> Prometheus -> Grafana. The application repo retains only
  instrumentation, metric semantics, dashboard JSON and non-secret config examples.
- Updated the Sprint 2 Mermaid sequence so current transactions are scored from history before
  their Redis/Event History updates.
- Detail: [M005 log](milestones/M005-sprint-scope-refinement.md).

## 2026-07-21 — M004: Editable target architecture and EDA-gated model policy

- Installed the Draw.io Codex plugin from the `jgraph/drawio-mcp` marketplace.
- Added a native editable target architecture under `docs/architecture/` and opened it in
  app.diagrams.net for visual verification.
- Replaced the pre-EDA LightGBM commitment with an explicit model-selection gate; LightGBM is
  now a candidate baseline only.
- Made PaySim the EDA-first application path; IEEE-CIS and Home Credit remain ADR-gated
  alternatives, while the synthetic oracle remains the correctness ground truth.
- Refined the Draw.io source into a connected high-level topology after architecture review:
  Delta is the offline store, Redis is the online store, Feast is their contract/materialization
  bridge, and EDA, training, serving and replay connect through explicitly labeled actions.
- Reduced the final graph from 87 elements/25 edges to 42 elements/13 action-labeled edges while
  retaining replaceable logo placeholders and a four-color relation legend.
- Verified well-formed XML with 42 diagram elements, 13 rendered edges, zero duplicate IDs,
  zero broken references and zero edges missing geometry. The pitch-deck HTML was intentionally
  not modified.
- Added a copy-ready Mermaid high-level source with 12 nodes and 16 action-labeled edges, grouped
  into seven subgraphs: Dev Env, Data Pipeline, Feature Platform, Training Pipeline, Model
  Registry, Serving Pipeline and Observability. JupyterLab pulls offline features and logs
  experiments to MLflow; OpenTelemetry and Grafana are shown as target observability components.
  Replay/Quality Gates remains absent and ten replaceable `LOGO` placeholders are preserved.
- Mapped the Event History node to Mermaid's `das` shape, the horizontal-cylinder/direct-access
  storage equivalent of Draw.io's `mxgraph.flowchart.direct_data` shape.
- Replaced the generic New Event node with a Transaction Producer role. The local implementation
  is explicitly a replay driver, not a claim of live/Kafka traffic.
- Corrected the fraud-scoring cutoff flow: the producer sends transaction `t` directly to
  FastAPI, FastAPI reads Redis history strictly before `t`, and only after scoring updates Redis
  and appends the event to the DuckDB/Delta offline history path.
- Detail: [M004 log](milestones/M004-drawio-target-architecture.md).

## 2026-07-21 — M003: PIT Fintech proposal HTML deck

- Added a four-slide, self-contained HTML presentation under `docs/reports/`.
- Covers project goal, failure modes, end-to-end architecture/technology, and output direction.
- Positions the project primarily as Fintech/MLOps engineering with research-backed evidence;
  Jupyter/cloud experimentation remains an enabler rather than the outcome.
- Added keyboard navigation, fullscreen mode, responsive 16:9 layout, and print styling.
- Verified all four slides at 1440x810 with no content overflow or console warnings/errors;
  button and keyboard navigation pass.
- Regression evidence: 23 pytest cases and Ruff checks pass.
- Detail: [M003 log](milestones/M003-proposal-html-deck.md).

## 2026-07-21 — M002: Milestone audit governance and documentation layout

- Added mandatory milestone logging rules to `AGENTS.md`.
- Added a pre-commit guard requiring project status, cumulative changelog, and a detailed
  milestone log for staged implementation changes.
- Made `artifacts/changelog/` a tracked exception while preserving gitignore for runtime runs.
- Moved human-readable reports to `docs/reports/` and feature-store guides to
  `docs/feature-store/`.
- Evidence: four hook unit cases, 23 passing tests, Ruff, and installed `.git/hooks/pre-commit`.
- Detail: [M002 log](milestones/M002-milestone-audit-governance.md).

## 2026-07-21 — M001: Sprint 1 foundation and temporal correctness slice

- Established Make/PowerShell/CLI/CI control plane and locked Python environment.
- Added synthetic temporal oracle, 13 feature specs, temporal/unit tests, and three notebooks.
- Added versioned Bronze/Silver Delta sample with label separation and time-travel evidence.
- Verified 0 future reads and deterministic logical checksums on the sample path.
- Sprint 1 remains in progress because application-data EDA, entity decision, and model
  baselines are pending.
- Detail: [M001 log](milestones/M001-sprint-1-foundation.md).
