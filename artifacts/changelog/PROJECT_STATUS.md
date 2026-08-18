# Project status

Last updated: 2026-08-18 (M073 — Sprint 3 feature/model validity notebooks, exploratory). Status
words are strict:

- **planned**: present in the six-week guide, with no claim that code exists;
- **implemented**: code/artifact exists but the relevant gate may not have run;
- **verified**: the documented command has passed in this workspace.

## Sprint 2 closure — 2026-08-13 (M072): CLOSED (owner-accepted)

Owner ran the six MVP invariant lanes. Clean: Lane 1 serving/OTel, Lane 2 backfill idempotency
(range [697,720] ×2, short-circuit, 0 duplicate), Lane 3 full backfill ([1,743],
`future_read_violations=0`, Gold `pre_v10`/`post_v9`), Lane 5 async parity
(`field_mismatches=0 passed=True`), Lane 6 served-event candidate (17 silver/17 candidate,
`label_status=unlabeled`). Lane 4 Redis recover: determinism verified
(`records_identical=5,444,725 / 5,444,726`, `watermark_restored=True`) but `differing_entities=1`
(concurrent worker live-write) — accepted limit, not a blocker. Regression:
`lint` clean, `test-unit` 110 passed. Recovery snapshot fixed GET→MGET (~1h → ~180s/pass). Owner
accepted Sprint 2 as **closed** on 2026-08-13; recover quiescent clean pass and optional
`materialize run --refresh` are accepted limits, not carry-over blockers. Detail:
[M072 log](milestones/M072-sprint-2-closure.md),
[completion report](../../docs/reports/sprint-2-completion-report.md).

## Superseded closure plan

Sprint 2 closure target is the MVP invariant scope, not SQLite/Feast PushSource expansion. Before
claiming closure, owner must verify in Grafana and manifests: OTel worker arrival; repeated range
backfill with identical idempotency/checksum/version evidence; full or incremental backfill; Redis
reset/rematerialization with zero differing records and restored watermark; required async parity
checkpoints with zero mismatches; and served-event Bronze -> Silver -> unlabeled Gold candidate output.
If any lane fails, record the exact root cause and leave Sprint 2 `blocked` rather than overclaiming.

## Project governance

| Artifact / guard | Status | Evidence |
|---|---|---|
| Cumulative changelog | verified | `artifacts/changelog/CHANGELOG.md` |
| Detailed milestone logs | verified | M001–M024 logs under `artifacts/changelog/milestones/` |
| Milestone pre-commit guard | verified | hook blocked the first M019 attempt after Ruff reformatted four files; the reviewed retry passed Ruff, milestone, large-file, conflict, TOML/YAML, EOF and whitespace guards in commit `6e93e7f` |
| Human-readable reports location | verified | reports moved to `docs/reports/` |
| Four-slide PIT proposal deck | verified | slide 2 states the full PIT-Correct Feature Platform for Fraud Detection name, objective, two execution paths (offline training and online serving), the cross-cutting OTel/Prometheus/Grafana observability layer, and four scope anchors; slide 3 embeds the user-authored architecture image; slide 4 now focuses only on the six-week engineering/MLOps outcome and evidence-backed handoff; 4 slides render at 1440x810 without overflow/errors; navigation passes |
| Editable Draw.io target architecture | verified | connected high-level v3 opens in app.diagrams.net; 42 elements, 13 action-labeled edges, explicit Delta offline/Redis online/Feast bridge roles, replaceable logo placeholders, no XML/reference defects |
| Copy-ready Mermaid architecture | verified | current high-level handoff; 7 subgraphs, 12 nodes, 16 action-labeled edges and 10 logo placeholders; transaction `t` is scored from Redis history before `t`, then updates Redis and appends to Event History for the DuckDB/Delta offline path; unique node IDs and valid edge references; OTel/Grafana remains planned |
| M005 sprint scope refinement | verified | Sprint 2/3 planning contract now fixes one-producer in-memory replay, score-before-update, offline-only medallion, thin Feast role, no Ray/Kafka/CDC/BI stack, and optional external VPS observability |
| M006 reusable project self-review checklist | verified | `docs/reports/project-self-review-checklist.md`; 13 non-negotiable hard gates plus a 100-point evidence-based scorecard across data, correctness, SWE, MLOps, serving, operations and scale reasoning |
| M011 knowledge defense checklist | verified | `docs/reports/knowledge-defense-checklist.md`; D0–D4 depth rubric, closed-note review protocol, detailed per-sprint knowledge gates, unseen-case drills, 24 final oral-defense prompts and shallow-understanding red flags |
| M013 proposal deck title consistency | verified | Slide 1 and slide 2 now use the exact same project name: `PIT-Correct Feature Platform for Fraud Detection` |
| M014 PaySim application decision | verified | ADR-002 accepts PaySim as the primary engineering workload with `AMBER_CORRECTNESS_ONLY`; IEEE-CIS remains an optional thesis/model-utility spike |
| M015 destination-centric leakage prototype | verified | user-run `test-temporal` passed 23/23 in 2.11s with exit code `0`; user-run `test-notebooks` passed all three notebooks, and notebook 03 saved 8 sequential code-cell executions with 0 cutoff violations |
| M016 standalone LightGBM candidate spike | verified | user-run `model-spike` completed E1–E4 with exit `0`; parent `0407debd24294c01a1d040f6aa33cc95`, snapshot `paysim1:16910f90577b0d98`, 38,213-row cohort, validated manifest/checksums and four logged `skops` models; candidate metrics retain sampled-cohort and dirty-commit boundaries |
| M017 PaySim FeatureSpec v1 | verified | user-run `features` passed with checksum `5b4e2b6db613f28dd6da209c50a5c3beb82969247e0248d39007bea9c9c26cf4`; temporal 23/23 and notebooks 01–04 passed; after replacing the presentation-width-sensitive CLI assertion, the user confirmed the corrected unit suite passed |
| M018 PaySim application lakehouse | verified | full snapshot `paysim1:16910f90577b0d98` built into three Delta v0 tables of 6,362,620 rows; 8/8 gates pass; 56.29s, 113,030 rows/s, 649,248,646 active Delta bytes, 31 partitions; fixture 3/3 and unit 30/30 pass; artifact correctly records dirty commit boundary |
| M019 Silver-based LightGBM baseline | verified | clean Silver v1/code `6e93e7f…`; 322,461 vectors, 8,213 fraud, checksum `c7f075…`, 0 future reads; MLflow parent `e1ebc…`; E1/E4 complete with exact manifests and skops models |
| M020 Sprint 1 closure | verified | all 9 Sprint 1 gates reconciled in `docs/reports/sprint-1-completion-report.md`; notebook 05 restored output-free; frozen Sprint 2 lineage recorded |
| M021 component-scoped lineage guard | verified | unit 39/39, lakehouse 4/4 and notebooks 5/5 pass; commit equality removed and component fields added; user-run `train` on 2026-07-28 reused Silver v2 without rebuild (`application_lakehouse_code_commit` stayed at `729d85f`), manifest carries `training_component_fingerprint=f34ba2bd…`, `training_component_dirty=false`, `repository_dirty=true` (expected: other files were uncommitted, the training component itself was clean); E1/E4 reproduced the frozen M019 metrics exactly |
| M023 CI dev-lane numpy dependency | verified | CI `make test-unit` failed on `ModuleNotFoundError: numpy` while green locally; `numpy` was only a transitive `training`-group dep and `test_paysim_lightgbm_spike.py` imports it at module top; added `numpy>=2.4,<3` to the `dev` group (matches locked 2.4.6/2.5.1); user confirmed on 2026-07-28 that `fast-fixture-ci` is green including the "Unit tests" step |
| M022 Sprint 1 report and knowledge review | implemented | seven-slide HTML evidence deck and ten-question D0–D4 interview complete, 10/10 assessed, total 18/40; user confirmed on 2026-07-28 by direct visual inspection that the deck renders with no overflow/console errors; Q1/Q2/Q4/Q5/Q6/Q7/Q8/Q9 D2 and Q3/Q10 D1: hard-invariant questions Q1/Q2/Q3/Q5/Q6/Q10 remain below D3 so the Sprint 1 knowledge gate still does not pass; M024 added the Q5/Q6/Q10 remediation test artifacts, but the interview itself has not been re-scored |
| M024 knowledge-review remediation tests | verified | user-run `test-temporal` went from 23 to 33 passed (10 new, none skipped): 8 oracle boundary/mutation tests in `test_reference_oracle.py` (4 boundary fixtures plus 4 mutation/differential tests via `monkeypatch`, no `src/` changes) and 2 tests in `test_paysim_recipient.py` (zero-history pre/post-score regression, E2 feature-set-vs-`PIT_FEATURE_COLUMNS` regression); `lint` clean |
| M025 ADR-005 knowledge_step and FeatureSpec v2 | implemented | `docs/adr/005-knowledge-step-and-featurespec-v2.md` proposes a derived Bronze `knowledge_step` column and a frozen `paysim-fraud-recipient-v2` FeatureSpec; ADR status is `proposed`, not `accepted`; no `src/`, `tests/`, Bronze or Silver change exists yet — accept, spec v2, no-op regression and knowledge-time fixture remain outstanding |
| M026 implement ADR-005 knowledge_step and FeatureSpec v2 | verified | ADR-005 accepted; Bronze emits derived `knowledge_step`, propagated unchanged into `silver.paysim_transactions`; `PAYSIM_FEATURE_DEFINITION_VERSION` bumped to `paysim-fraud-recipient-v2`, `created_time_policy` is `derived_knowledge_step_lte_cutoff`; both PIT engines moved from `RANGE BETWEEN` window functions to range self-joins so the two-column eligibility predicate can be expressed; user-run `build-lakehouse`/`train` on 2026-07-29 against rebuilt Silver v4 reproduced E1 PR-AUC `0.258342`/ROC-AUC `0.601620`/recall `0.275559` and E4 PR-AUC `0.102766`/ROC-AUC `0.784978`/recall `0.036741` bit-exact vs M019, 0 future-read violations, vector checksum `ff52681f…`, training fingerprint `381de46f…`, MLflow parent `d9d142db…` — proving the knowledge-time predicate is a no-op on clean data; missing knowledge-time boundary fixture and shared `pit_sql.py` extraction remain open |
| M027 fix non-deterministic vector_checksum (DECIMAL money sums) | verified | root cause: `sum(amount)` over `DOUBLE` plus the M026 range-join refactor's unordered hash `GROUP BY` combined to make summation order non-deterministic across `train` runs; fix sums money as `PAYSIM_AMOUNT_DECIMAL_TYPE = DECIMAL(18,2)` in both PIT engines, casting to `DOUBLE` only at the final projection; added 9th publish-blocking quality gate `amount_decimal_roundtrip_failures`; contract dtype/version unchanged (no v3 bump); user-run 2026-07-29: two separate consecutive `train` runs against rebuilt Silver v6 produced the SAME `vector_checksum` `ce88d250…`, training fingerprint `a005f4ea…`, E1 PR-AUC `0.258342`/ROC-AUC `0.601620`/recall `0.275559`/precision `0.541601`, E4 PR-AUC `0.102766`/ROC-AUC `0.784978`/recall `0.036741`/precision `0.243386` — unchanged from M019/M026 despite the DOUBLE->DECIMAL arithmetic change, showing the old rounding error was model-invisible but checksum-visible; 0 future-read violations; `test-temporal` 47 passed (33->47, +14 = 7 new tests x 2 engines) and `test-unit` 39 passed; determinism confirmed on one machine/core-count only, a different core count is not yet tested |
| M028 ADR-006 Feast time mapping and service v2 | verified | `docs/adr/006-feast-time-mapping-and-service-v2.md` proposes `EPOCH_0 = 2020-01-01T00:00:00Z` with `event_timestamp = EPOCH_0 + step hours` / `created_timestamp = EPOCH_0 + knowledge_step hours` as Feast-layer-only derived columns (bijective, order-preserving, no invariant touched; cutoff order and tie-break stay on `(step, source_row_number)` per ADR-001/003/005), and a `paysim-fraud-scoring-v1 -> v2` service bump with the twelve fields unchanged; `pyproject.toml` declares `feast[duckdb,redis]>=0.65,<0.66` in its own optional group, with the `serving` group's `uvicorn[standard]` pinned to `==0.34.0` because every Feast release caps uvicorn transitively at `<=0.34.0`; the frozen `requires-python`/`pyarrow`/`duckdb` pins are untouched; ADR status is `proposed`; the v1 service string moved to v2 in 5 of the 6 listed call sites (`paysim_specs.py`, `config.py`, `.env.example`, `test_paysim_feature_contract.py`, `AGENTS.md`), with `docs/reports/paysim-feature-contract-v1.md` intentionally left at v1 as a historical record; project owner ran on 2026-07-31: `uv lock` resolved 234 packages in 2ms (`uv.lock` now in sync with `pyproject.toml`, including the `feast`/`uvicorn==0.34.0` pins); `.\make.ps1 lint` clean (`ruff check`: all checks passed, `ruff format --check`: 48 files already formatted); `.\make.ps1 test-unit` 39 passed in 2.17s; `.\make.ps1 test-temporal` 47 passed in 3.25s (the `pit data sample` fixture regeneration step left `git status --short` clean, confirming it is deterministic); ADR-006 is now **accepted**; project owner ran `.\make.ps1 features` on 2026-07-31 and re-emitted the canonical `paysim-fraud-recipient-v2`/`paysim-fraud-scoring-v2` contract checksum `01bba24cc79be8729ec66557bb68828fbb66a17bfefdb601aaedc1a6cee575de` (12 features); project owner also ran `uv sync --group feast --group serving` on 2026-07-31, materializing `feast==0.65.0`/`redis==7.4.1`/`uvicorn==0.34.0` etc., but that scoped sync uninstalled the `training` group (`lightgbm`, `mlflow`, `scikit-learn`, ...) — a full dev environment requires `uv sync --all-groups` |
| M029 PaySim oracle/SQL parity lane and real-Silver fixture builder | verified (within the scope run) | first repayment of the Sprint 1 debt recorded at `src/pit_fintech/features/reference.py:3-5` ("must match this oracle before it is accepted"): the PaySim DuckDB path had never been compared against an independent oracle. New pure-Python oracle `src/pit_fintech/features/paysim_reference.py` (no DuckDB/SQL/window functions; eligibility `prior.step < current.step AND prior.knowledge_step <= current.knowledge_step`, window `[current_step - window_hours, current_step)`, `Decimal(18,2)` money with `Inexact`/`Rounded` trapped, twelve fields in contract order, import-time contract check) plus `tests/temporal/test_paysim_oracle_sql_parity.py`, which drives one fixture through the oracle, `features/paysim_recipient.py` and `models/paysim_training.py` and compares all twelve fields in contract order for every scored row, with a hand-derived step-400 cutoff vector so agreement alone is not accepted as correctness. **Key finding:** the same-step policy is enforced in the `LEFT JOIN` on *both* engines (`paysim_recipient.py:278` `s.step <> c.step`, `paysim_training.py:565` `s.step <= c.step - 1`) before any `FILTER` runs, with the `FILTER` repeating the bound (`paysim_recipient.py:83`, `paysim_training.py:414`) and the oracle enforcing it again (`paysim_reference.py:371`), so **no single-clause mutation can go red on either engine**; an earlier draft asserted the opposite asymmetry and could never have failed. The lane now states that limitation in the docstring of `test_same_step_filter_mutation_alone_is_masked_by_the_join`, keeps its mirror `test_same_step_join_mutation_alone_is_masked_by_the_filter`, and keeps one mutation with teeth (`test_admitting_same_step_rows_breaks_parity`) that removes both guards at once via a `_SqlRewrite`/`_RewritingConnection` statement-text seam that raises if the rewrite never matched. Three expected values were corrected because the hand calculation was wrong, not the SQL — 24h `9644.93`/168h `20756.03` for the knowledge-time removal (row 8 at `step 398` cannot enter the 1h window `[399, 399]`, which is now asserted unchanged), `24089.36` for the deleted FILTER lower bound (row 3 at `step 231`, `4444.44`, had been omitted), and `3833.84` for same-step admission (the cutoff row also self-joins once the join bound is gone); each arithmetic is written beside its assertion, no number was fitted to observed output and `PARITY_ROWS` was not modified. A false comment in production was corrected at `src/pit_fintech/models/paysim_training.py:557-562` (the join is not a "widest-window prune only" — `c.step - 1` is half of the eligibility rule); comment prose only, no SQL clause touched, so no training metric or checksum can move. `pit data build-fixture --dataset paysim` wired through `cli.py:266-299`, `Makefile:47-48` and `make.ps1:74-75` over `src/pit_fintech/data/paysim_fixture.py`, which extracts a small deterministic fixture from real Silver and scores it with the oracle rather than SQL, guarded by `tests/unit/test_paysim_fixture.py` and `tests/integration/test_paysim_fixture.py`. Project owner ran on 2026-08-03: `.\make.ps1 format` (`ruff check --fix` all checks passed; `ruff format` 1 file reformatted, 52 files left unchanged), `.\make.ps1 lint` (`ruff check` all checks passed; `ruff format --check` 53 files already formatted), `.\make.ps1 test-unit` (41 passed in 1.97s, up from 39), `.\make.ps1 test-temporal` (`pit data sample` validated 7 canonical events from 8 rows, snapshot `synthetic-temporal-v1:1ef70772400a1d8e` unchanged from M028, then 73 passed in 4.52s, up from 47). **The first real run then exposed two bugs, both fixed without weakening anything.** (a) The destination picker committed to one destination on a loose criterion (`_pick_rich_destination`) and then applied a strictly harder three-band criterion (`_pick_rich_cutoff_step`) with no fallback, so an unlucky first pick killed the build (`destination C1000004940 never reaches a cutoff step where all three history windows are simultaneously distinguishable`). The band criterion was **not** relaxed — without a prior row in each of `[1,1]`, `[2,24]` and `[25,168]` step offsets the 1h/24h/168h windows can return equal counts and equal sums, so a swapped window or a bound off by one would pass unnoticed. Instead the bands are derived once from `PAYSIM_WINDOW_STEPS` and read by both SQL and Python, the exact band predicates are pushed into a bounded SQL self-join returning candidates ordered by `destination_entity_id`, and the first candidate confirmed in Python wins (`RICH_CANDIDATE_LIMIT = 8`); both failure messages report how many candidates were walked and why each was rejected. (b) `tests/integration/test_paysim_fixture.py` asserted `{event.source_row_number for event in events} == set(expected)`, an equality that must never hold: the fixture carries every row of the chosen destinations because history is unfiltered by transaction type, while `compute_paysim_feature_vectors` scores only in-scope rows, so the expectation file is a proper subset by construction, and the builder's `_verify_round_trip` cannot catch drift there because it applies the same scope filter to both sides. Replaced by three stricter assertions: `set(expected) == in_scope`, `set(expected) < all_row_numbers`, and `assert history_only`. **Real run after the fixes:** `.\make.ps1 lint` (`ruff check` all checks passed; `ruff format --check` 53 files already formatted), `.\make.ps1 test-unit` (41 passed), `.\make.ps1 test-temporal` (73 passed), `uv run pytest -q -rs -m integration tests/integration/test_paysim_fixture.py` (1 passed — first execution of the builder success path and of the integration lane); `.\make.ps1 build-fixture` run twice independently, both reporting 15 source rows and producing byte-identical files, `paysim_temporal_cases.jsonl` SHA-256 `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` and `paysim_expected_features.json` SHA-256 `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B`. The fixture holds 15 source rows: 11 in scoring scope with a vector, 4 history-only without one; destinations `C1000022185` (rich; steps 42, 138, 155, 157, 159, 177, 178), `C1000004940` (same-step pair, two rows at step 303) and `C100003532` (zero history, one row at step 397); all 4 history-only rows (`861131`, `1357635`, `1701770`, `4149878`) are `CASH_IN` to a `CUSTOMER` destination, leaving scope on transaction type rather than destination kind, which is the intended shape since history counts regardless of type. **Known limitation:** `set(expected) == in_scope` computes `in_scope` with the same `in_scoring_scope` the builder uses, so it is not an independent derivation — it locks the on-disk file against the contract, and `assert history_only` covers the degenerate case separately. **Not run:** nothing is committed, so no commit hash exists (pending); `train` was not re-run and no M019/M026/M027 metric or checksum is restated; no e2e lane exists; the parity lane still runs on hand-built `PARITY_ROWS` only, with no test yet driving the two DuckDB engines against the 15 extracted rows; determinism is shown on one machine and one core count |
| M030 ADR-006 Feast source Parquet and T1 design spike | verified (within the scope run) | First step of Sprint 2 T1 taken without waiting for T2 — the data source only; **T1 is not done**. `pit data build-fixture` now also writes `data/fixtures/paysim_temporal_cases.parquet` from the same selection as the JSONL and expected vectors: every Silver column with names/types taken straight from Silver rather than retyped, plus exactly 2 derived columns `event_timestamp`/`created_timestamp` at `pa.timestamp("us", tz="UTC")`, so Feast `FileSource` validation can accept it. `PAYSIM_FEAST_EPOCH_0` and `paysim_step_to_timestamp` live in `features/paysim_specs.py` as the single implementation ADR-006 decision 1.7 requires; the Unix literal `1577836800` appears nowhere in the codebase, and the mapping is computed in Python rather than SQL because a DuckDB `TIMESTAMPTZ` expression renders against the session time zone and would make the file depend on the machine that produced it. The first real run crashed on `RecordBatchReader has no attribute combine_chunks` (DuckDB `.arrow()` returns a reader, not a table); fixed with `to_arrow_table`, which the repo already used at `features/paysim_recipient.py:376` and which runs clean under `-W error::DeprecationWarning` unlike the deprecated `fetch_arrow_table`. `combine_chunks()` was kept rather than deleted to silence the crash: it guarantees one chunk so Parquet row-group boundaries follow the row count, never DuckDB's batching. A throwaway spike `scripts/spike_feast_t1.py` (temp directory only, deleted on exit, touches neither `feature_repo/` nor `data/fixtures/`) answered four design questions, building its feature table with the SQL engine so that comparing it against the oracle is two independent derivations: **Q1** the eleven in-scope rows sit at 11 distinct steps (155, 157, 161, 177, 178, 180, 207, 212, 299, 303, 397) and the 4 history-only rows are all `CASH_IN`, so the fixture's same-step pair never reaches the feature table — a coverage hole, not a blocker, correcting an earlier claim that the tie was T1's largest risk; **Q2** `get_historical_features` returned 11 rows matching the oracle on every field with 0 differences; **Q3** a deliberate tie collapsed to exactly one row with no fan-out (marker 111.0), but which row wins is not controlled by the project, exactly as ADR-006 decision 1.4 warned; **Q4** a no-op second `apply` moved both the registry file and serialized-proto digests (`73b76be0…` to `67ddb993…`) because the proto carries `last_updated`. **Finding 1:** Feast does not compute window aggregates — `feast/aggregation/__init__.py:17` says "Feast-handled aggregations are not yet supported", `aggregation` appears nowhere in `feast/infra/offline_stores/duckdb.py` or `file_source.py`, a plain `FeatureView` does not accept the argument, `BatchFeatureView`/`StreamFeatureView` only store it, and `OnDemandFeatureView` transforms row-wise over already-retrieved inputs — so the Parquet shipped here is a *source* table and T1 additionally needs a precomputed table of the twelve contract fields, one row per cutoff, exactly as guide §3.2 line 117 and §4 line 148 always implied. **Finding 2:** the guide §3.3 registry checksum must be canonical over the definitions, never over the registry blob, or a G1 idempotence criterion would fail permanently for a meaningless reason. Project owner ran on 2026-08-03: `.\make.ps1 lint` (`ruff check` all checks passed, `ruff format --check` 54 files already formatted); `.\make.ps1 build-fixture` twice independently, both reporting 15 source rows and byte-identical output — jsonl `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` and json `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B` unchanged from M029, new parquet `6935B7EE1C0EB4133CA1EF07A11686993329FD119DB3DB4EE6A282FB997153A5` identical across both runs; integration lane 2 passed; the spike answered all four questions with none unanswered. No `DeprecationWarning` remains from project code; one remains from `ibis/backends/duckdb/__init__.py:332`, third-party. **Not done:** `feature_repo/` untouched, still exactly 2 placeholder files, and no `Entity`/`FeatureView`/`FeatureService`/`feature_store.yaml` committed anywhere; no precomputed feature table exists on disk (Q2's eleven-row table was built in memory in a deleted temp directory); no registry checksum in `src/`; no G1 test lane, the spike is a script not a test; **G1 does not pass** — only the first of the three guide §3.4 criteria has been measured and only inside the spike, the second cannot be measured as the guide implies until the checksum moves off the registry blob (semantic idempotence is CHUA XAC DINH), and the third was never attempted since no `FeatureService` was created; Q3's tie behaviour is observed, not a contract; determinism shown on one machine and one core count; nothing committed, so no commit hash (pending); `train` not re-run and no M019/M026/M027 metric or checksum restated |
| M031 Feast `feature_repo/`, definitions checksum, G1 lane | verified (within the scope re-run recorded in `verify.md`) | Closes M030's four T1 gaps: precomputed feature table on disk (`data/fixtures/paysim_feature_table.parquet`, 11 rows/16 cols, SHA-256 `A6E6B9B00FA62966E19397D9C0A7737FCB48D8C9C81A5C7300CCE047B3B997C5`, 132/132 fields match the oracle), real `feature_repo/feature_store.yaml`+`definitions.py` applied against installed Feast 0.65.0, a definitions-based registry checksum in `src/pit_fintech/platform/feast_registry.py` (`d330edefbbc0d3a075b4b5f145a6d169e2aa910d39cfae33c70478289432f443`, stable across 2 applies; registry **blob** digest still moves `98fe137e...`->`fd09313e...`, confirming M030 Finding 2 stays live), and a real `pytest` G1 lane (`tests/integration/test_feast_registry_g1.py`, 4 tests). All three guide §3.4 G1 criteria pass: historical retrieval matches oracle (132/132 fields), `feast apply` idempotent by definitions checksum, `paysim-fraud-scoring-v2` resolves 12 fields in contract order. New Feast 0.65.0 findings: `FeatureView.schema` loses field order (must read `.features` instead), `feast apply` does not read the source file at apply time, `FeatureView.name` must be `.isidentifier()`-safe while `FeatureService.name` is not, `entity.join_keys` does not exist post-construction (`entity.join_key` does). Independently re-run: `ruff check` all checks passed; `pytest -q tests/unit` 50 passed (41->50); `pytest -q -m temporal` 73 passed (unchanged); `pytest -q tests/integration` 11 passed (7->11); G1 lane alone 4 passed. **Known gaps, not closed here:** the same-step pair still never reaches Feast (feature table holds 11 distinct steps, M030 gap 4 unchanged); idempotence measured across 2 applies in 1 process, not across 2 separate `feast apply` CLI processes; `ttl`/`entity_columns` excluded from the checksum payload by design, so a future change to either will not move it; one machine only; no `make`/`make.ps1` target yet for the G1 lane; nothing committed, no commit hash (pending); `train` not re-run |
| Ten-minute PIT meetup speaker script | verified | `docs/reports/pit-fintech-meetup-10min-script.md`; compressed four-slide talk track targets 9:20 plus buffer, keeps slide 3 as the technical core, and separates six concise mentor Q&A prompts from the spoken script; four slide headings, four closing claims, six Q&A prompts and required status/architecture claims pass the content scan; `git diff --check` passes |
| Vietnamese PIT terminology catalog | verified | `docs/reports/catalog.md`; required-term scan, reader-aid structure and `git diff --check` pass |
| M047 one-shot `setup` + OTel collector endpoint env | implemented (agent static analysis only) | `setup` target (`Makefile` + `make.ps1`) runs `uv sync --frozen --all-groups` then `uv run pre-commit install`, installing every dependency group at once; `Settings.otel_endpoint` reads `PIT_OTEL_ENDPOINT` from `.env` and feeds `pit serving up --otel-endpoint` as its default (`serving/telemetry.py` `OTEL_EXPORTER_OTLP_ENDPOINT` fallback unchanged). Owner gates pending: `.\make.ps1 setup`, `.\make.ps1 lint`, `uv run pit serving up --otel` |
| M048 Locust/OTel make targets + deprecation cleanup | implemented (agent static analysis only) | `tools`/`locust`/`serve-otel` targets in `Makefile`+`make.ps1` (`LOCUST_HOST`/`-LocustHost`); `scripts/spike_feast_t1.py` (M030 throwaway) marked for `git rm`; stale `replay` references in `feature_repo/definitions.py`, `tests/e2e/test_sprint2_e2e.py` (test renamed `test_score_reads_before_it_updates`), `scripts/locust_parity.py` (prefers `PIT_OTEL_ENDPOINT`) and `serving/telemetry.py` updated for ADR-008. Owner gates pending: `.\make.ps1 tools`, `.\make.ps1 lint`, `git rm scripts/spike_feast_t1.py`, then `redis-up`+`serve-otel`+`locust` |
| M049 wire `/metrics` for remote Prometheus scrape | implemented (agent static analysis only) | `pit serving up --host/--port` default from `get_settings()` (`PIT_API_HOST`/`PIT_API_PORT`); `.env.example` + README document `PIT_API_HOST=0.0.0.0` and the VPS `prometheus.yml` scrape job (owner's stack at `100.116.36.6` has no OTel Collector, so Prometheus pulls `/metrics`, not OTLP). Owner gates pending: `.\make.ps1 lint`; set `PIT_API_HOST=0.0.0.0`; `.\make.ps1 serve`; add `pit_fintech_scoring` job to VPS `prometheus.yml` and reload |
| M050 VPS observability sample configs | implemented (agent static analysis only) | new `deploy/vps/`: `otelcol-config.yaml` (traces→Tempo, metrics→debug), `tempo-config.yaml` (refined: underscored YAML ints `1_000_000` crash-looped Tempo — Go YAML rejects them; removed the `ingester`/`compactor` tunables), `docker-compose.otel.yml` (otel-collector + tempo), `prometheus-scrape-job.yml`, `grafana-dashboard.json`, `README.md` (includes troubleshooting for the `/etc/prometheus` host-mount gotcha). Hybrid design (Prometheus pulls `/metrics`; API pushes OTLP traces via `PIT_OTEL_ENDPOINT` → Collector → Tempo → Grafana). README + `.env.example` updated; no `src/`/tests/deps change. VPS setup is owner-side from these files |
| M051 structured logging with OTel correlation | implemented (agent static analysis only) | new `src/pit_fintech/platform/logging_config.py` (structlog JSON + OTel trace_id/span_id processor + request-context bind); `/score` binds/clears request fields and runs the whole body inside the `score` span; `pit serving up` emits JSON; `LoggingInstrumentor` switched to `set_logging_format=False`; new unit test `tests/unit/test_logging_config.py`. Agent: `py_compile` passes; ruff/pytest pending owner. Gates: `.\make.ps1 lint`, `.\make.ps1 test-unit`, then `serve-otel` + hit `/score` |
| M052 ADR-009 parity at the online write path | implemented (ADR accepted; agent static analysis only; no serving code yet) | `docs/adr/009-parity-at-the-online-write-path.md` (accepted): materialize = bulk offline→online copy, **not** a parity gate (read-only copy is always equal); serving reads the materialized aggregate (`RedisFeatureProvider`); serving owns the write path; **parity is verified at the write path** (post-score update vs offline reference for step `t`); serving parity is **observed, not unit-tested** — verified via Prometheus metrics + Tempo traces (`score`→`online_write`) + Grafana (the reason the observability stack exists now). Amends ADR-008 (keeps write-path + Locust; drops winlog recompute read path). Records 3 anti-patterns. No code change. Next: M053+ implementation (read provider, aggregate state transition, post-write parity compare, Grafana parity panel) |
| M053 implement ADR-009 | implemented (agent static analysis only) | `serving/online_state.py` → `apply_event_and_verify` (WATCH/MULTI/EXEC; guards not_warm_started/rejected_older/noop_identical; recompute post-event aggregate at step; oracle parity compare via `count_parity_mismatches`; write log+aggregate in one txn). Read path → `RedisFeatureProvider` (removed `WindowStateFeatureProvider`/`window_state`). `/score` write path records parity telemetry; `pit_parity_checked_total` added. Locust harness compares stored aggregate vs oracle per entity. New `tests/unit/test_online_write_path.py`; Grafana "Write-path parity (ADR-009)" panel. Agent: py_compile clean, no stale refs; ruff/pytest pending. Known gap: materializer writes aggregate not winlog → live writes to unseeded entities refused (`not_warm_started`). Gates: `lint`, `test-unit`, `redis-up`+`materialize`+`serve-otel`+load |
| M054 two-path fan-out, DuckDB parity reference | implemented (agent static analysis only) | ADR-009 updated: after score, event fans out to online (winlog → Redis aggregate) AND offline (Event History → DuckDB → Gold Delta); parity = online Python vs offline DuckDB SQL. `serving/online_state.py`: `_oracle_reference_over` removed; new `_duckdb_reference_over` runs `paysim_post_event_state_sql` (the real offline engine) over the event set; new `append_event_history` (JSONL at `<artifact_root>/event_history/`); `apply_event_and_verify` gains `transaction_type` + appends Event History after Redis commit (best-effort); Locust `offline_post_event_reference` uses DuckDB too. `app.py` passes `transaction_type`. Two new DuckDB-vs-online tests. Agent: py_compile clean, lines<=100, no stale refs; sandbox lacks duckdb so SQL semantics verified by analysis. **Owner: `test-unit` 73 passed (incl. the 2 DuckDB-vs-online tests); `lint` caught B905 `zip()` → fixed `zip(..., strict=True)`. Refinement: a later `test-unit` failed both DuckDB tests with `_duckdb.InvalidInputException` (DuckDB rejects raw `list[dict]` for `register()`); fixed `_duckdb_reference_over` to register a `pyarrow.Table` (`pa.Table.from_pylist`).** Known gap: Event History not yet consumed by offline build (follow-up wires Event History → DuckDB → Gold Delta); `not_warm_started` still stands. Gates: `lint`, `test-unit`, `redis-up`+`materialize`+`serve-otel`+load, check parity panel + event_history jsonl |
| M055 async write path, parity reconcile | implemented (agent static analysis only) | ADR-009 amended: write path is non-blocking (no DuckDB on `/score`); parity verified async by `pit parity reconcile`. `serving/online_state.py`: `WritePathResult` drops parity fields; `apply_event_and_verify` = winlog append + evict + Python recompute + write log/aggregate under WATCH/MULTI/EXEC + Event History append (best-effort). New `ParityReconcileResult` + `reconcile_parity` (reads Event History, runs `_duckdb_reference_over` per entity, counts mismatches). `serving/app.py`: `/score` no longer records parity; `_MetricsState` drops `pit_parity_*`; `/metrics` = scoring only. `cli.py` + Make/PS `parity-reconcile` target; README + deploy/vps README/dashboard updated (parity via OTel, Prometheus-backed panel needs collector remote-write). Agent: py_compile clean, lines<=100, dashboard JSON OK, no stale refs. Known gaps: Event History → Gold Delta not yet wired; `not_warm_started` stands; parity counters via OTel. Gates: `lint`, `test-unit`, `redis-up`+`serve`+`parity-reconcile` |
| M056 event-based write path (ADR-010) | implemented (agent static analysis only) | ADR-010 accepted: write path is pub/sub. `/score` = publisher + scorer (publish to Redis Stream, wait for the worker result, score on the **pre-decision** vector via `score_transaction(prefetched=...)`; timeout => `503`). New `serving/events.py` (XADD + poll), `serving/worker.py` (single ordered consumer), `apply_score_event` in `online_state.py` (WATCH/MULTI/EXEC, captures pre-decision vector, guards, writes log+aggregate+result in one txn, appends Event History). New distinct Docker service **`pit-online-worker`**; `pit serving worker`; Make/PS `worker`/`worker-up`/`worker-down`; AGENTS.md §11 owner-directed exception recorded (Redis Streams as write-path transport). Agent: py_compile clean, lines<=100, no stale `apply_event_and_verify` refs; sandbox no redis/duckdb so verified by analysis. Known gaps: single consumer (scale-out = per-entity sharding later); Event History → Gold Delta not wired; `not_warm_started` stands; parity via OTel. Gates: `lint`, `test-unit`, `redis-up`+`worker-up`+`serve`+`parity-reconcile` |
|| M057 warm-start winlog from Gold | **verified (owner run 2026-08-10)** | closes `not_warm_started`: materialize seeds each entity's winlog so live writes are applied. `POST_EVENT_STATE_SCHEMA` + `paysim_post_event_state_sql` gain `amount` (per-event, not a contract field); materializer warm-start reads **Gold** (joined latest-per-entity, 168h window), not Silver (medallion layering per owner review); batch write seeds winlog for WRITTEN/NOOP; `_build_winlog_by_entity` uses `exact_money`. **Refinements:** promote over old Gold failed `SchemaMismatchError: 18 vs 17` → `_write_gold_table` passes `schema_mode="overwrite"` (full-range promote evolves schema); `parity reconcile` false-failed after warm-start → offline reference now over the entity's **winlog** (same event set), not Event History. **Owner verified:** promoted Gold v7; `materialize` seeded warm-start winlogs for 2,722,362 entities (`0 written / 2,722,362 noop / 0 rejected`); `demo-score` @744 → `feature_provider: pit-online-worker` / `feature_step 743`; `parity-reconcile` **passed yes, 0 mismatch** |
|| M058 out-of-order strict-PIT fix | **verified (2026-08-11 focused lanes)** | `apply_score_event` recomputes the pre-decision vector from winlog at the request cutoff when `step < stored.feature_step`, instead of returning future aggregate state; `staleness_steps` cannot become negative. Regression/write-path unit 8 passed, full unit lane 98 passed, Ruff and format checks clean. Repository-wide `pytest -q` remains blocked at collection by duplicate `test_paysim_fixture.py` module names in unit/integration; live Redis worker/demo/parity was not rerun in this milestone. |
|| M059 duplicate replay strict-PIT fix | **verified (2026-08-11 unit + live API probe)** | duplicate `noop_identical` requests now recompute pre-decision features at the exclusive request cutoff instead of returning post-event aggregate state. Added `scripts/debug_strict_pit.py` and `debug-strict-pit` Make/PowerShell targets; worker rebuilt/recreated. Unit 9 passed, full unit 99 passed, Ruff/format clean. Live evidence: duplicate step 745 → `feature_step=744`, `staleness_steps=1`; out-of-order step 744 → `feature_step=744`, `staleness_steps=0`; report at `artifacts/reports/out-of-order-debug.md`. |
|| M060 normalized feature-step metadata | **verified (2026-08-11 unit + live API probe)** | `feature_step` now means the latest strictly prior event included in the vector. Duplicate and out-of-order branches use `latest_prior_event_step`; cold cutoff returns `feature_step=null`, `feature_status=missing`, `staleness_steps=null`. Unit 10 passed, full unit 100 passed, Ruff/format clean, worker rebuilt/recreated. Final live probe used a fresh debug entity seeded at step 743: first/duplicate step 745 → `feature_step=743`, `staleness_steps=2`; out-of-order step 744 → `feature_step=743`, `staleness_steps=1`; report at `artifacts/reports/out-of-order-debug.md`. |
|| M061 live write-path retry/advancement matrix | **verified (2026-08-11 live FastAPI + worker)** | Added `scripts/live_write_path_matrix.py` and `live-write-matrix` targets. Ten live cases passed: monotonic advancement 700/701/702/704/705, exact retry, different-transaction-ID retry, gap, out-of-order 703, late-arrival 701 with `knowledge_step=704`, and conflicting same-step amount. Retries matched scoring fields; older/late requests did not move state backward; step705 resumed from stored step704. Evidence: `artifacts/reports/live-write-path-matrix.md`. Internal WATCH collision was not forced; API outcome is not exposed directly; online late-arrival correction remains guarded. |
|| M062 Locust write-path sequence | **verified (2026-08-11 live Locust smoke)** | Added `scripts/locust_write_path.py` and `locust-write-path` targets. One fresh entity runs ten advancement/retry/reordering cases once, then stops. Locust 2.46.3 headless: 10 requests, 0 failures, average 51 ms, median 39 ms, max 168 ms; CSV evidence under `artifacts/reports/locust-write-path_*.csv`. No timeout simulation or forced WATCH collision. |
|| M063 OTLP logs and cross-process trace correlation | **implemented (2026-08-11 local verification; duplicate-export fix verified)** | FastAPI/worker export structured logs via OTLP `/v1/logs`; Redis Stream carries W3C `traceparent`; worker binds request context and creates child `online_write` spans. Duplicate root cause was `LoggingInstrumentor` auto-installing a second SDK `LoggingHandler`; disabled with `enable_log_auto_instrumentation=False`. `PIT_OTEL_ENDPOINT` passed to API and worker Compose services. Ruff/format/compile clean; logging/write-path subset 13 passed. VPS live arrival/query verification pending API/worker recreate. |
|| M064 champion loading and Gold E1-E4 evaluation | **verified (2026-08-11 committed Gold + MLflow)** | Serving resolves `paysim-fraud-lightgbm@champion` by default and fails closed without alias; explicit run id remains diagnostic override. Gold matrix uses E1 static/temporal, E2 post-event/current-inclusive/random non-deployable control, E3 PIT/random, E4 PIT/temporal. Real Gold joined 2,770,409 rows; E1-E4 logged to MLflow with PR-AUC/ROC-AUC/recall/precision; E4 promoted as registry version 1 and real `predict_proba` load verified. Unit 104 passed; focused model/Gold/T4 15 passed. |
||| M065 Event History to Bronze ingestion | **implemented (2026-08-11 unit + CLI/PowerShell verification)** | Added checkpointed/idempotent `pit ingest event-history`, `make ingest-event-history`, and `make.ps1 ingest-event-history`. New serving events land in separate `data/lakehouse/served_events` Bronze Delta because they lack raw PaySim Bronze fields/confirmed labels; checkpoint advances only after append. Ingestion tests 2 passed; PowerShell parse/Ruff pass. |
||| M066 offline lifecycle logging | **implemented (agent static analysis; owner verification pending)** | Added Loki-friendly lifecycle events for Event History Bronze ingestion, Gold build/stage/promote, and parity reconcile; commands export them through the configured OTLP endpoint without triggering downstream stages. Focused test and owner verification lanes remain pending. |
||| M067 event identity and Grafana evidence panels | **implemented (lint verified; focused/live verification pending)** | Stable `event_id` now crosses Redis score event, worker log, Event History, Bronze and parity evidence; request/transaction identity is preserved; Gold/parity evidence fields and Grafana v4 panels added. `.\make.ps1 lint` passed after formatting. Focused tests, image recreation and live one-request evidence remain pending. |
||| M068 event-driven async parity consumer | **implemented (agent static analysis; owner live verification pending)** | Worker now coalesces post-apply parity signals in one daemon consumer thread, runs DuckDB reconcile asynchronously, emits latest parity lifecycle logs/metrics, and never blocks `/score` or Redis event handling. Grafana parity panel accepts manual and worker-emitted parity logs. Worker rebuild and one-request live proof pending. |
||| M069 OTLP logs in serving images | **implemented (static config verified; image/live verification pending)** | Worker was proven to run parity but had OTel packages missing, so its logs never reached Loki. Dockerfile now supports `INSTALL_OTEL=1`; API and worker compose builds enable it. Rebuild/recreate and Loki verification pending. |
||| M070 served-event Silver and Gold candidate path | **implemented (focused test passed; live verification pending)** | `pit ingest event-history` now idempotently normalizes the resolved Bronze table into `served_events_silver` and computes strict-PIT `served_events_gold_candidate`, including checkpoint no-op runs; invalid rows can be quarantined; candidate rows remain unlabeled and unpromoted. Grafana dashboard v7 adds the candidate panel. |
||| M071 MVP invariant gates and Grafana evidence | **implemented (focused gates verified; live recovery/backfill evidence pending)** | Added `pit backfill run` and `pit materialize recover`; lifecycle logs/panels cover backfill, materialization and Redis recovery. Unit 110, Gold/Feast integration 8, T3 smoke 1 and lint pass. Recovery intentionally not live-run because it resets the scoped Redis namespace; full real backfill/Loki evidence remains open. |
|| M072 Sprint 2 closure + recovery MGET fix | **CONDITIONAL PASS (owner-run 2026-08-13)** | Six MVP invariant lanes run owner-side; 5 clean (serving/OTel, backfill idempotency range [697,720]×2 short-circuit 0-dup, full backfill [1,743] `future_read_violations=0` Gold `pre_v10`/`post_v9`, async parity `field_mismatches=0 passed=True`, served-event candidate 17/17 unlabeled). Lane 4 recover determinism verified `records_identical=5,444,725/5,444,726` `watermark_restored=True` but `differing_entities=1` (concurrent worker live-write) — not clean `passed=yes`. Recovery snapshot fixed GET→MGET (`_SNAPSHOT_BATCH=5000`, ~1h→~180s/pass); `[recover +Ns]` progress logs; CLI prints differing keys; comparison/exit not weakened (hard rule #5). `lint` clean, `test-unit` 110 passed. Added `notebooks/06_delta_time_travel.ipynb`. Open: recover clean pass on quiescent store; optional `materialize run --refresh` |

## Sprint 1

| Artifact / gate | Status | Evidence |
|---|---|---|
| Project skeleton, lock policy, ignore/env files | verified | `uv sync --frozen --group dev` |
| Make/PowerShell command boundary | verified | CLI commands exercised in this workspace |
| Read-only environment doctor | verified | `pit doctor`; only expected Delta-extension/Kaggle/Git warnings |
| Synthetic temporal source and hand-calculated vectors | verified | current generated snapshot `synthetic-temporal-v1:1ef70772400a1d8e` |
| Independent pre-decision PIT oracle | verified | 0 future reads across 12 temporal tests |
| Temporal oracle test suite | verified | latest user-run `.\make.ps1 test-temporal`: 23 passed in 1.97s, exit code `0`; M017's corrected unit-suite rerun is tracked separately |
| CI fixture lane | verified | `.github/workflows/ci.yml`; user confirmed on 2026-07-28 that `fast-fixture-ci` is green end to end |
| JupyterLab and five Sprint 1 notebooks | verified | user-run verifier passed notebooks 01–05 with exit `0`; notebook 05 remained review-only and ZMQ/TCP kernel messages were non-blocking local warnings |
| LightGBM candidate notebook 04 | verified | review-first surface has been restored to `RUN_TRAINING=False`, explains exploratory E1–E4 and exposes manifest lineage/resource evidence; the prior four-notebook run passed |
| Silver training notebook 05 | verified | user-run notebook verifier passed it in review-only mode; it calls the same `src/` pipeline as `train` and explains lineage, split health, metrics and importance |
| Redis + MLflow local service boundary | verified | docker compose up run on 2026-07-28; redis and mlflow healthchecks both pass (confirmed by repository owner) |
| PaySim access/checksum and EDA | verified | full snapshot/profile, cross-role analysis and destination gate outputs are verified; `CASH_OUT` is AMBER with 7-day warm fraud counts 2,058/186/101 across train/validation/test, `TRANSFER` is RED with 4/0/0, yielding accepted status `AMBER_CORRECTNESS_ONLY` |
| PaySim application data profile | verified | `docs/reports/paysim-data-profile.md` consolidates full snapshot, quality, type/label distribution, entity viability and leakage decisions |
| PaySim raw snapshot command | verified | user-run `.\make.ps1 data-snapshot` froze `paysim1:16910f90577b0d98`, 493,534,783 bytes, 6,362,620 rows and steps 1–743 in `artifacts/datasets/paysim1/16910f90577b0d98/snapshot-manifest.json` |
| Dataset/entity ADR | verified | `docs/adr/002-paysim-dataset-entity-scope.md`; PaySim retained for engineering/PIT evidence, IEEE-CIS optional only if thesis/model-utility scope expands |
| PaySim FeatureSpec v1 | verified | frozen 12-field contract, canonical checksum, temporal suite and notebooks are verified; the brittle Rich-table assertion was replaced by stable `feature_count: 12`, and the user confirmed the corrected unit suite passed |
| PaySim application Bronze/Silver path | verified | full Bronze transactions, label-free Silver transactions and separate Silver labels published at exact Delta v1 with immutable/latest manifests and FeatureSpec checksum linkage |
| Bronze/Silver Delta sample | verified | 8 Bronze rows, 7 Silver rows, separated label table; 1 integration/time-travel test passes |
| Model-family gate and static/PIT baseline | verified | clean exact-Silver E1/E4 temporal baseline completed; E1 PR-AUC 0.258342 and E4 0.102766 on natural-prevalence test; weaker E4 is retained as valid utility evidence |
| Sprint 1 release gate | verified | 9/9 gates pass; frozen handoff and accepted limits are recorded in `docs/reports/sprint-1-completion-report.md` |

## Sprint 2

Thin Feast contract, CLI-built Gold features, full/range/incremental backfill, Redis
materialization, local selected-model + MLflow run, gated promotion/rollback, FastAPI/Uvicorn
scoring, one-producer ordered in-memory replay, offline/online parity, and sample E2E are all
**planned**. The Gold CLI staging/promotion wiring, event-day range guard, shared typed partition
predicate, DuckDB Gold-path narrowing/materialization, CLI phase progress, indexed shift-relation
validation, T3 smoke lane, and T4 Gold-to-MLflow candidate path are now implemented but not fully
verified; full T3 G2/G3 and full-scale T4 training remain open. The full Gold build/promote path was
verified on a real range; no real T4 training was run in this work. Since then T4 training was
verified on Gold v6 (M041: two runs, `test_pr_auc 0.362883`), and T5 Redis materialization + T7
FastAPI scoring + the demo script were implemented and verified on the happy path (M043). Ray Train/Tune/Serve and external
message brokers are out of the Sprint 2 MVP.

**M043 is implemented, verified on happy path** (no gate claim). It closes the online path for
the demo: `materialization/records.py` + `materializer.py` implement the Redis backend —
`online_record_key`/watermark/run key helpers; `materialize_to_watermark` reads
`gold.post_event_state_updates` (DeltaTable + DuckDB, version pinned at run start), keeps the
latest row per entity by `(step DESC, source_row_number DESC)`, renames the nine `post_*` fields
via `POST_EVENT_TO_CONTRACT_FIELD`, writes JSON payloads (amounts as decimal strings) through
5000-batch Redis pipelines with `evaluate_write` on every candidate, and writes the watermark key
last; `evaluate_write`/`write_record` (WATCH/MULTI/EXEC)/`read_online_features`
(fresh/stale/missing with contract defaults)/`read_watermark`/`reset_online_store` (SCAN-scoped)
are implemented; SQLITE, `rematerialize_after_reset` (G8) and `push_to_feast_online_store`
(Feast PushSource) remain NotImplementedError. `serving/{schemas,feature_provider,scoring,app}.py`
serve exactly four routes (`POST /score`, `/health/live`, `/health/ready`, `/metrics`), loading
the model with `mlflow.sklearn.load_model("runs:/<run_id>/model")` (newest FINISHED run of
`pit-fintech-gold-training`, `8f9c709782704f1eba89cc9e3fde83c1` in the demo round;
`model_version` = run id, `deployment_id=None` — no model registry, G11 not met). `cli.py` adds
`pit materialize run|show` and `pit serving up`; Makefile adds `materialize`/`serve`/`demo`/
`redis-up`/`redis-down`; `scripts/run_demo_e2e.py` chains Redis -> Gold -> materialize -> serve ->
score 3 cases -> tear down. Verified locally: ruff clean on `src/` + `scripts/`; unit 87 passed;
temporal 73 passed; real materialization on Gold v6 (w24: 249,521 records / 32.3 s; w743:
2,722,362 entities, 2,527,816 written / 194,546 NOOP / 0 rejected / 384.8 s; re-run at 24:
0 written / 249,521 NOOP; two-run checksum probe identical `a8bf4b6e...`); demo `--skip-
materialize` 3/3 PASS in 41.95 s (case A C1470998563 step 744 fresh/staleness 1; case B step
1243 stale/500; case C C0000000000 missing, nine zero history fields). Not done: T6 parity, SQLITE
backend, G8 recovery lane, Feast PushSource, model registry/G11; `tests/e2e/` still 12 skipped;
G5/G7/G9 are NOT declared passed (no test lane pins their criteria); the work is uncommitted in
the working tree at time of writing.

**M046 completes ADR-008: `/score` now reads the serving-owned event-log store, plus an OpenTelemetry
exporter.** `WindowStateFeatureProvider` reads the per-entity event log and computes the nine window
features live at `request_step`; `build_scoring_context` uses it, so online read + online write +
offline oracle share one independent state. Added `serving/telemetry.py` — OTLP/HTTP traces + metrics
to the user's external collector (`--otel-endpoint`/`OTEL_EXPORTER_OTLP_ENDPOINT`), trace-correlated
logs, FastAPI instrumentation; instruments cover scores, online writes, parity mismatches and
score/read/write latency; `/score` opens a `score` span with a child `online_write` span. OTel is
**not** a project dependency (kept out of pyproject to preserve ADR-004 fingerprints) — installed by
hand into the serving env like `locust`; absent/disabled ⇒ no-op. `pit serving up` gains
`--otel`/`--otel-endpoint`. Agent static analysis only (`ruff` clean); the service, OTLP export and
Grafana dashboards are the owner's to run. Nothing committed.

**M045 (ADR-008) supersedes M044: replay dropped, serving owns the online write path, parity via
Locust.** Owner review concluded the M044 replay/parity was near-vacuous (online = materialized copy
of offline, and the replay harness bypassed `serving/app.py`). ADR-007 is superseded by ADR-008
(accepted). Removed: the whole `src/pit_fintech/replay/` package, its three test files, the
`pit replay parity` command, and the `test-parity`/`parity` Make/PS targets. Added
`serving/online_state.py` — an independent windowed feature maintainer (per-entity Redis event log,
`[step - w, step)` windows re-implemented from the offline oracle, Decimal money, append+evict under
`WATCH`/`MULTI`/`EXEC`); `/score` now runs this write step after scoring (read-before-write kept).
Parity/load is a manual `scripts/locust_parity.py` (not pytest): it bombards `/score` and compares
the online state the service maintained against the independent offline oracle at window-edge,
same-step and late-arrival cutoffs. Agent static analysis only (`ruff` clean on the four files); the
scoring **read** path still uses the materialized provider — switching it to the event-log store is
the immediate follow-up. Nothing committed. The M044 paragraph below is retained as history but its
code no longer exists.

**M044 (T6 replay driver + offline/online parity harness) is implemented; pure logic unit-tested;
G6 not claimed.** `replay/driver.py` and `replay/parity.py` move from round-0 skeleton to working
code. `ReplayDriver` is the single logical producer (rejects a queue not sorted by
`(step, source_row_number)`, runs read->score->commit->append per event with no overlap, records
`read_before_update`, `out_of_order_events=0`, `concurrent_emissions=0`). The parity primitives
`canonicalize_vector` and `classify_mismatch` are pure (integers exact, float tolerance 1e-6 only,
structural causes named before a numeric diff) and unit-tested; `plan_checkpoints`,
`compare_at_checkpoint`, `run_parity_harness` and `write_parity_report` read Gold + the online store
and are the user-run G6 path. `SAME_SECOND_TIE` requires the T2 probe flag and `SYNTHETIC_LATE_
ARRIVAL` is always reported as a gap, so a partial checkpoint cover cannot masquerade as a pass.
**Open, surfaced not hidden:** parity is exact only in the one-step-shift arrangement
(`GOLD_SHIFT_RELATION`); a cutoff whose entity's latest prior event is >1 step back reads STALE and a
same-step tie reads the tied prior event offline excludes — both are emitted as classified
mismatches keeping `passed=False`, since how serving should treat a stale/tied cutoff is the open
T5/T6 design item. New CLI `pit replay parity`; Make/PS `test-parity` (no Redis) and `parity` (G6,
needs Redis + Gold). This session was agent static analysis only (`ruff` clean on the four files);
no repo env run — unit/temporal/parity gates and the real `parity` run on Gold v6 are pending the
project owner. `tests/e2e/` is still 12 skipped. Nothing committed yet.

**ADR-007 (proposed) reframes what G6 proves.** Because the online store is a materialized copy of
offline Gold and serving does no computation, the M044 parity harness compares offline against a
copy of itself: it is an integration test of the materialize + shift-relation plumbing, not the
train/serve-skew correctness proof G6 is presented as. `docs/adr/007-parity-requires-an-independent-
online-computation.md` records the finding and offers two directions — (A) keep MVP materialize-only
scope and reclassify the check honestly, deferring G6-as-correctness; or (B) add an independent
incremental windowed feature maintainer on the write path so parity genuinely catches drift. Status
`proposed`; no code or contract changed; the A/B choice is the next decision and it does not block
committing M044.

**M042 is implemented, not verified.** It fixes the fast-fixture-ci failure (run 30995527627,
commit d2ce188): the T4 MLflow contract lane requires the optional `training` dependency group
(lightgbm, mlflow, scikit-learn), but the workflow synced only `uv sync --frozen --group dev` and
the `test-lakehouse` target ran without a group flag. The workflow now syncs
`--group dev --group training` and sets `PIT_REQUIRE_TRAINING: "1"` on the "Delta sample snapshot
and time travel" step alone; `test-lakehouse` now runs `uv run --group training pytest -q
tests/integration`; a new self-contained local target `test-integration-full` (all-groups, matching
the `test-t3-smoke`/`test-t4-dataset` convention) is the full-lane local path and was added to
`.PHONY`; `_require_training()` mirrors `_require_feast()` and escalates its skip to `pytest.fail`
under `PIT_REQUIRE_TRAINING=1` — the latch against a fake-green CI. All evidence is local on Windows
(dry-run resolution of `dev + training`, latch mutation test with and without the variable, 21
passed integration, Ruff clean); no green CI run on ubuntu-latest yet, so status stays `implemented`
(expected integration lane on CI: 14 passed, 7 skipped, 0 failed).

**M041 is implemented and verified.** It optimizes the T4 Gold-to-training path for full-scale
runs: Silver labels are narrowed to the join columns before the DuckDB join, and repeated
`to_pylist()` over millions of rows in retrieval, future-read audit and temporal split are replaced
with Arrow compute. `train_candidate` and the dataset stages gained `[t4 +Xs]` phase progress and
LightGBM `log_evaluation(period=10)` prints every-10-rounds training progress. No contract or
checksum changed; defaults preserve prior behavior. T4/Gold fixtures 6 passed, unit 87, temporal 73,
integration 21, Ruff clean.

**M041 is implemented and verified.** It optimizes the T4 Gold-to-training path for full-scale
runs: Silver labels are narrowed to the join columns before the DuckDB join, and repeated
`to_pylist()` over millions of rows in retrieval, future-read audit and temporal split are replaced
with Arrow compute. `train_candidate` and the dataset stages gained `[t4 +Xs]` phase progress and
LightGBM `log_evaluation(period=10)` prints every-10-rounds training progress. No contract or
checksum changed; defaults preserve prior behavior. T4/Gold fixtures 6 passed, unit 87, temporal 73,
integration 21, Ruff clean. Real-run verification: user ran `train-gold-candidate` twice on
committed Gold v6 (full 1..743); both runs produced `test_pr_auc 0.362883` with complete MLflow
tags/artifacts, confirming deterministic reproducible T4 training. T4 is ready for T5.

**M040 is implemented and verified.** It optimizes the Gold promote read-back verification in
`_write_gold_table`: partition discovery uses `pa.compute.unique`, the read-back uses Arrow dataset
predicate pushdown (`isin(partitions)`) instead of loading the whole committed table, and the
logical-output check compares sorted Arrow tables with `Table.equals` instead of two full-table
`to_pylist()` + `json.dumps` checksum passes. Published `logical_checksum` values are unchanged
(same `_canonical_checksum` on the input table). Gold fixture tests 4/4, unit 87, temporal 73,
integration 21, Ruff clean. The real in-flight full-range promote still runs the old code; the fix
applies to the next run.

**M032 Round 0 is implemented, not verified.** It adds 19 new files (3,842 lines) and modifies
`compose.yaml`, creating the cross-module scaffolding for T2–T9: Gold-build, backfill,
materialization, training, replay/parity, serving, and E2E package seams. Import is reported OK;
the reported check results are `ruff check` clean for 79 files, unit 50 passed, temporal 73 passed,
and E2E 12 skipped. These results do not demonstrate a running pipeline or E2E: scaffold entry
points raise `NotImplementedError`, except `backfill_idempotency_key()` which is explicitly
implemented. Consequently no T2–T9 gate, serving flow, backfill flow, replay flow, promotion/
rollback, or E2E path is verified by M032.

M032 freezes seven contracts: two Gold tables and `OfflineFeatureBuildResult`; `BackfillRunRecord`
and its idempotency key; `FeatureProvider` plus four adapters; replay parity result types; and
Pydantic score request/response schemas. Its log also records three guards that must survive later
implementation (post-event field names must differ from contract names to prevent leakage,
integer and float parity mismatches must stay separate, and missing checkpoints fail a parity
report), three known traps (SQL engine rather than oracle as feature producer; Python timestamp
mapping; required same-step-tie coverage), and six explicit decisions still pending. The guide
deviations are intentional and unresolved: idempotency hashing currently adds a version prefix,
and no `e2e` marker was added because changing `pyproject.toml` would invalidate both ADR-004
component fingerprints; path plus `integration` marker selects the lane instead. `AGENTS.md` is a
contemporaneous Dương-to-Codex instruction edit, not a Round 0 product and must not be reverted as
one.

Component-scoped lineage is **verified** by M021, including the post-commit `train` reuse of
legacy Silver v2 without rebuild and the new fingerprint fields recorded in the 2026-07-28
manifest.

T1 (Feast repository, S2-A1, gate G1) had two blocking decisions, both resolved in ADR-006 (M028),
**accepted** 2026-07-31: the `EPOCH_0`-based derived timestamp columns Feast requires, and the
`paysim-fraud-scoring-v2` service bump. The `feast` and `serving` dependency groups are declared;
the project owner ran `uv lock` on 2026-07-31 (`Resolved 234 packages in 2ms`), so `uv.lock` is now
in sync with `pyproject.toml`, including the `feast[duckdb,redis]>=0.65,<0.66` and
`uvicorn[standard]==0.34.0` pins. `.\make.ps1 lint`, `.\make.ps1 test-unit` (39 passed) and
`.\make.ps1 test-temporal` (47 passed) all ran clean the same day. The project owner then ran
`uv sync --group feast --group serving` on 2026-07-31, materializing `feast==0.65.0`,
`redis==7.4.1`, `hiredis==3.4.0`, `uvicorn==0.34.0` and related packages — note that this scoped
`uv sync` uninstalled the `training`/tracking group (`lightgbm`, `mlflow`, `scikit-learn`, `scipy`,
`joblib`, `matplotlib`, `skops`, ...), since `uv sync` matches the environment exactly to the named
groups; a full dev environment needs `uv sync --all-groups`. The project owner also ran
`.\make.ps1 features` on 2026-07-31, re-emitting the canonical `paysim-fraud-recipient-v2`/
`paysim-fraud-scoring-v2` contract checksum
`01bba24cc79be8729ec66557bb68828fbb66a17bfefdb601aaedc1a6cee575de` (12 features). No Feast
registry, feature view or `feature_repo/` code exists yet.

`feature_repo/` now holds real Feast objects (M031): `feature_store.yaml` (`local` profile —
DuckDB offline + SQLite online) and `definitions.py` (`Entity`, `FileSource`, `FeatureView`,
`FeatureService`, every name/dtype/version imported from `features/paysim_specs.py`), applied
successfully against installed Feast 0.65.0. A precomputed pre-decision feature table exists on
disk (`data/fixtures/paysim_feature_table.parquet`, 11 rows × 16 columns, computed by the SQL
engine, 132/132 fields matching the oracle). A definitions-based registry checksum exists in
`src/pit_fintech/platform/feast_registry.py`. A real `pytest` G1 lane exists
(`tests/integration/test_feast_registry_g1.py`).

The two M030 findings that shaped this work still hold. Feast does not compute window aggregates
(`feast/aggregation/__init__.py:17`), so the `FeatureView` reads the precomputed table built by the
SQL engine, not a raw source. A registry-blob checksum moves on a no-op `apply` because the proto
carries `last_updated`, so the definitions checksum in `platform/feast_registry.py` is what the
idempotence criterion is measured against; the blob digest was confirmed to still move
(`98fe137e...` -> `fd09313e...`) across the same two applies that left the definitions checksum
unchanged, so Finding 2 is a live, confirmed property of this exact `feature_repo/`, not a residual
worry.

**G1 now passes, all three criteria (M031), each backed by a real `pytest` test re-run
independently and recorded in `verify.md`:** historical retrieval on the real `feature_repo/`
matches the oracle's expected vectors on 132/132 fields; `feast apply` is idempotent measured by
the definitions checksum (`d330edef...443`, stable across two applies in one process); and
`paysim-fraud-scoring-v2` resolves all 12 fields in contract order. This closes the T1 work item
this project has been calling "the G1 lane" — it does **not** mean Sprint 2 T1 is finished. Known
limitations that remain, all recorded in the M031 log: the fixture's same-step pair still has 11
distinct steps and never reaches Feast, so tie-handling at the Feast layer is still unexercised
(M030 gap 4, unchanged); idempotence has only been measured across two `apply` calls inside one
Python process, not across two separate `feast apply` CLI invocations; `ttl`/`entity_columns` are
deliberately excluded from the checksum payload, so a future change to either would not be caught
by this gate; and everything above is confirmed on one machine only (Windows 11, Feast 0.65.0,
DuckDB pinned in `uv.lock`). No `PushSource` or `OnDemandFeatureView` was built (T5/T7 scope). T2
(Gold `pre_decision_features`) has not started; when it does, `FileSource` is expected to point at
a different table and the definitions checksum is expected to change.

The real-Silver PaySim fixture builder added in M029 (`pit data build-fixture --dataset paysim`)
has now been run. Two independent runs on a machine holding PaySim Silver each reported 15 source
rows and produced byte-identical files —
`data/fixtures/paysim_temporal_cases.jsonl` SHA-256
`5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE`,
`data/fixtures/paysim_expected_features.json` SHA-256
`DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B` — and
`tests/integration/test_paysim_fixture.py` passed (1 passed), which is the first execution of the
builder's extraction/scoring/write/round-trip path. Getting there required fixing a
non-backtracking destination picker and an integration assertion that compared two sets which are
a proper subset relation by construction; neither fix relaxed a correctness criterion. The fixture
holds 15 rows, 11 in scoring scope and 4 history-only. Still open: no test drives the two DuckDB
engines against these extracted rows (the parity lane remains on hand-built `PARITY_ROWS`), and
determinism is shown on one machine and one core count only. No e2e lane exists.

**M033 T2 real-Silver Gold build is implemented, not verified.** `build_offline_features` ran
against real PaySim Silver at `cutoff_start_step=cutoff_end_step=1`, producing
`pre_decision_features` (664 rows) and `post_event_state_updates` (2708 rows) with identical
logical checksums across two independent runs (`pre` `c4a8903a4da7adde3bd00a2ec7e00d6e5b672d694f2de71ba98d324abf3e1f8c`,
`post` `e55eac8791724840b71f5be081d4245e4f6699dbe438dd0e86d9a0e951fbe7cb`). `compare_gold_against_reference`
matched the SQL-built table against the independent Python oracle on 664 rows x 12 contract fields
(7968 fields), 0 mismatches. `probe_same_step_ties()` on this Gold table found 579 in-scope
same-step pairs across 104 entities, closing the tie-coverage gap M032/HANDOFF.md flagged for T1's
11-row fixture table specifically — no artificial tie needs to be constructed for T6.

A dead-code bug was fixed: the future-read count previously read `future_reads = ... if False else
0`, so two `GOLD_PROMOTION_PRECONDITIONS` entries always passed regardless of data. Replaced with
`probe_future_read_violations()`, an independently-written self-join (does not call the frozen
`paysim_pre_decision_feature_sql` engine it audits), filtering by `step` and testing
`knowledge_step >= cutoff_step` for the violation itself — using the same column for both would make
the check tautological. A hand-run mutation (`>=` to `>`) turned the new unit test red; reverting
restored green. **Known limitation:** on current data `knowledge_step = step` is fixed at ingest, so
the audit cannot fire organically on this data; the `0` it reports is now proven by an independent
computation rather than assumed by a literal, but it also cannot catch a boundary bug that lives
only inside the frozen SQL engine itself. `compare_gold_against_reference(scope="random_sample")`
and `export_feast_source_parquet()` both remain `NotImplementedError`; the near-quadratic oracle
makes a naive random-sample implementation impractical over a wide step range.

Two HANDOFF.md §6 pending decisions were finalized this session and the guide corrected to match
(not the ADR): the idempotency-key formula keeps a `policy_version` prefix with `\0` separators
(the guide's literal 5-field, unprefixed formula was the stale side — `dataset_snapshot_id` already
contains `:`, so `:` cannot safely separate fields), and no `e2e` pytest marker is added, since
`pyproject.toml` sits in both ADR-004 `component-fingerprint-v1` boundaries and a new marker line
would invalidate exact-Silver reuse; E2E selection stays on path plus the `integration` marker.

Recorded checks: `ruff check` clean (81 files); `pytest -q tests/unit` 52 passed; `pytest -q -m
temporal tests/temporal` 73 passed; `pytest -q tests/integration` 13 passed. T3–T9 have not started
under this milestone; no E2E path is claimed.

## Sprint 3

E1–E5/P1–P5 experiment execution, fault injection report, clean-room audit, cloud smoke path,
final report, and optional TypeScript scorer are all **planned**. OTel Collector, Prometheus and
Grafana on a separate VPS/ops boundary are **planned/should-have**, not part of core Compose or a
release dependency.

**M073 — feature/model validity notebooks (nb09–nb13): implemented (exploratory, non-promotable).**
Owner ran nb09–nb13, logging to MLflow experiment `pit-fintech-notebook-exploration`
(`manifest_backed=false`). Findings (steering evidence on PaySim AMBER, NOT a verified gate):
LightGBM 7-feature tuned = test **PR-AUC ~0.38**, CV **0.38 ± 0.11** (warm 0.41 / cold 0.35);
LightGBM ≈ XGBoost (fair `scale_pos_weight=√(neg/pos)`); Optuna tuning +0.011 on val did not transfer
to test (+0.0006) → ceiling is feature/data; `event_step` confirmed overfit (dropped from feed);
12 stored features → 7 deployable *feed* set (reversible, FeatureSpec `paysim-fraud-recipient-v2`
stays frozen); cold-start (recipients with no history) is the real weakness. Detail:
[M073 log](milestones/M073-feature-model-validity-notebooks.md),
[findings report](../../docs/reports/sprint-3-feature-model-validity-findings.md). **Not verified** —
promotable baseline must run under `src/pit_fintech/training/` with manifest + multi-seed; notebooks
must be output-cleared before commit (hard rule #4).

This table must be updated whenever an artifact crosses from planned to implemented or from
implemented to verified.
