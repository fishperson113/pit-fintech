# Project status

Last updated: 2026-07-27. Status words are strict:

- **planned**: present in the six-week guide, with no claim that code exists;
- **implemented**: code/artifact exists but the relevant gate may not have run;
- **verified**: the documented command has passed in this workspace.

## Project governance

| Artifact / guard | Status | Evidence |
|---|---|---|
| Cumulative changelog | verified | `artifacts/changelog/CHANGELOG.md` |
| Detailed milestone logs | verified | M001–M022 logs under `artifacts/changelog/milestones/` |
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
| M021 component-scoped lineage guard | implemented | unit 39/39, lakehouse 4/4 and notebooks 5/5 pass; commit equality removed and component fields added; post-commit `train` reuse against legacy Silver v2 remains |
| M023 CI dev-lane numpy dependency | implemented | CI `make test-unit` failed on `ModuleNotFoundError: numpy` while green locally; `numpy` was only a transitive `training`-group dep and `test_paysim_lightgbm_spike.py` imports it at module top; added `numpy>=2.4,<3` to the `dev` group (matches locked 2.4.6/2.5.1); green CI run pending after re-lock/commit |
| M022 Sprint 1 report and knowledge review | implemented | seven-slide HTML evidence deck and ten-question D0–D4 closed-note interview added; visual verification and user assessment pending |
| Ten-minute PIT meetup speaker script | verified | `docs/reports/pit-fintech-meetup-10min-script.md`; compressed four-slide talk track targets 9:20 plus buffer, keeps slide 3 as the technical core, and separates six concise mentor Q&A prompts from the spoken script; four slide headings, four closing claims, six Q&A prompts and required status/architecture claims pass the content scan; `git diff --check` passes |
| Vietnamese PIT terminology catalog | verified | `docs/reports/catalog.md`; required-term scan, reader-aid structure and `git diff --check` pass |

## Sprint 1

| Artifact / gate | Status | Evidence |
|---|---|---|
| Project skeleton, lock policy, ignore/env files | verified | `uv sync --frozen --group dev` |
| Make/PowerShell command boundary | verified | CLI commands exercised in this workspace |
| Read-only environment doctor | verified | `pit doctor`; only expected Delta-extension/Kaggle/Git warnings |
| Synthetic temporal source and hand-calculated vectors | verified | current generated snapshot `synthetic-temporal-v1:1ef70772400a1d8e` |
| Independent pre-decision PIT oracle | verified | 0 future reads across 12 temporal tests |
| Temporal oracle test suite | verified | latest user-run `.\make.ps1 test-temporal`: 23 passed in 1.97s, exit code `0`; M017's corrected unit-suite rerun is tracked separately |
| CI fixture lane | implemented | `.github/workflows/ci.yml` |
| JupyterLab and five Sprint 1 notebooks | verified | user-run verifier passed notebooks 01–05 with exit `0`; notebook 05 remained review-only and ZMQ/TCP kernel messages were non-blocking local warnings |
| LightGBM candidate notebook 04 | verified | review-first surface has been restored to `RUN_TRAINING=False`, explains exploratory E1–E4 and exposes manifest lineage/resource evidence; the prior four-notebook run passed |
| Silver training notebook 05 | verified | user-run notebook verifier passed it in review-only mode; it calls the same `src/` pipeline as `train` and explains lineage, split health, metrics and importance |
| Redis + MLflow local service boundary | implemented | Compose config passes; image build hit host timeout and remains unverified |
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
**planned**. Ray Train/Tune/Serve and external message brokers are out of the Sprint 2 MVP.

Component-scoped lineage implementation gates are **verified** by M021. The milestone remains
implemented until post-commit `train` reuses legacy Silver v2 without rebuild and emits the new
fingerprint fields.

## Sprint 3

E1–E5/P1–P5 experiment execution, fault injection report, clean-room audit, cloud smoke path,
final report, and optional TypeScript scorer are all **planned**. OTel Collector, Prometheus and
Grafana on a separate VPS/ops boundary are **planned/should-have**, not part of core Compose or a
release dependency.

This table must be updated whenever an artifact crosses from planned to implemented or from
implemented to verified.
