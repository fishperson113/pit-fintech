# Project changelog

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
