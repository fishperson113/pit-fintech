# Project changelog

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
