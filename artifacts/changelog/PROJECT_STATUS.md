# Project status

Last updated: 2026-07-27. Status words are strict:

- **planned**: present in the six-week guide, with no claim that code exists;
- **implemented**: code/artifact exists but the relevant gate may not have run;
- **verified**: the documented command has passed in this workspace.

## Project governance

| Artifact / guard | Status | Evidence |
|---|---|---|
| Cumulative changelog | verified | `artifacts/changelog/CHANGELOG.md` |
| Detailed milestone logs | verified | M001–M015 logs under `artifacts/changelog/milestones/` |
| Milestone pre-commit guard | verified | four unit cases pass; installed at `.git/hooks/pre-commit` |
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
| Temporal/unit test suite | verified | user-run `.\make.ps1 test-temporal`: 23 passed in 2.11s, exit code `0`, with the deprecated DuckDB warning removed |
| CI fixture lane | implemented | `.github/workflows/ci.yml` |
| JupyterLab and three Sprint 1 notebooks | verified | user-run `.\make.ps1 test-notebooks`: PASS for notebooks 01–03 and exit code `0`; notebook 03 full-data output has 8 sequential code cells, no errors and zero PIT cutoff violations for 1h/24h/168h |
| Redis + MLflow local service boundary | implemented | Compose config passes; image build hit host timeout and remains unverified |
| PaySim access/checksum and EDA | verified | full snapshot/profile, cross-role analysis and destination gate outputs are verified; `CASH_OUT` is AMBER with 7-day warm fraud counts 2,058/186/101 across train/validation/test, `TRANSFER` is RED with 4/0/0, yielding accepted status `AMBER_CORRECTNESS_ONLY` |
| PaySim raw snapshot command | verified | user-run `.\make.ps1 data-snapshot` froze `paysim1:16910f90577b0d98`, 493,534,783 bytes, 6,362,620 rows and steps 1–743 in `artifacts/datasets/paysim1/16910f90577b0d98/snapshot-manifest.json` |
| Dataset/entity ADR | verified | `docs/adr/002-paysim-dataset-entity-scope.md`; PaySim retained for engineering/PIT evidence, IEEE-CIS optional only if thesis/model-utility scope expands |
| Bronze/Silver Delta sample | verified | 8 Bronze rows, 7 Silver rows, separated label table; 1 integration/time-travel test passes |
| Model-family gate and static/PIT baseline | planned | lock after PaySim EDA; LightGBM is a candidate only |

## Sprint 2

Thin Feast contract, CLI-built Gold features, full/range/incremental backfill, Redis
materialization, local selected-model + MLflow run, gated promotion/rollback, FastAPI/Uvicorn
scoring, one-producer ordered in-memory replay, offline/online parity, and sample E2E are all
**planned**. Ray Train/Tune/Serve and external message brokers are out of the Sprint 2 MVP.

## Sprint 3

E1–E5/P1–P5 experiment execution, fault injection report, clean-room audit, cloud smoke path,
final report, and optional TypeScript scorer are all **planned**. OTel Collector, Prometheus and
Grafana on a separate VPS/ops boundary are **planned/should-have**, not part of core Compose or a
release dependency.

This table must be updated whenever an artifact crosses from planned to implemented or from
implemented to verified.
