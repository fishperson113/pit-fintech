# Project status

Last updated: 2026-07-23. Status words are strict:

- **planned**: present in the six-week guide, with no claim that code exists;
- **implemented**: code/artifact exists but the relevant gate may not have run;
- **verified**: the documented command has passed in this workspace.

## Project governance

| Artifact / guard | Status | Evidence |
|---|---|---|
| Cumulative changelog | verified | `artifacts/changelog/CHANGELOG.md` |
| Detailed milestone logs | verified | M001–M010 logs under `artifacts/changelog/milestones/` |
| Milestone pre-commit guard | verified | four unit cases pass; installed at `.git/hooks/pre-commit` |
| Human-readable reports location | verified | reports moved to `docs/reports/` |
| Four-slide PIT proposal deck | verified | slide 2 states the full PIT-Correct Feature Platform for Fraud Detection name, objective, two execution paths (offline training and online serving), the cross-cutting OTel/Prometheus/Grafana observability layer, and four scope anchors; slide 3 embeds the user-authored architecture image; slide 4 progresses from Engineering/MLOps to thesis-ready E2E research; 4 slides render at 1440x810 without overflow/errors; navigation passes |
| Editable Draw.io target architecture | verified | connected high-level v3 opens in app.diagrams.net; 42 elements, 13 action-labeled edges, explicit Delta offline/Redis online/Feast bridge roles, replaceable logo placeholders, no XML/reference defects |
| Copy-ready Mermaid architecture | verified | current high-level handoff; 7 subgraphs, 12 nodes, 16 action-labeled edges and 10 logo placeholders; transaction `t` is scored from Redis history before `t`, then updates Redis and appends to Event History for the DuckDB/Delta offline path; unique node IDs and valid edge references; OTel/Grafana remains planned |
| M005 sprint scope refinement | verified | Sprint 2/3 planning contract now fixes one-producer in-memory replay, score-before-update, offline-only medallion, thin Feast role, no Ray/Kafka/CDC/BI stack, and optional external VPS observability |
| M006 reusable project self-review checklist | verified | `docs/reports/project-self-review-checklist.md`; 13 non-negotiable hard gates plus a 100-point evidence-based scorecard across data, correctness, SWE, MLOps, serving, operations and scale reasoning |
| Ten-minute PIT meetup speaker script | verified | `docs/reports/pit-fintech-meetup-10min-script.md`; compressed four-slide talk track targets 9:20 plus buffer, keeps slide 3 as the technical core, and separates six concise mentor Q&A prompts from the spoken script; four slide headings, four closing claims, six Q&A prompts and required status/architecture claims pass the content scan; `git diff --check` passes |
| Vietnamese PIT terminology catalog | verified | `docs/reports/catalog.md`; required-term scan, reader-aid structure and `git diff --check` pass |

## Sprint 1

| Artifact / gate | Status | Evidence |
|---|---|---|
| Project skeleton, lock policy, ignore/env files | verified | `uv sync --frozen --group dev` |
| Make/PowerShell command boundary | verified | CLI commands exercised in this workspace |
| Read-only environment doctor | verified | `pit doctor`; only expected Delta-extension/Kaggle/Git warnings |
| Synthetic temporal source and hand-calculated vectors | verified | snapshot `synthetic-temporal-v1:c0909688e0e26e20` |
| Independent pre-decision PIT oracle | verified | 0 future reads across 12 temporal tests |
| Temporal/unit test suite | verified | 12 temporal + 10 unit + 1 integration test pass |
| CI fixture lane | implemented | `.github/workflows/ci.yml` |
| JupyterLab and three Sprint 1 notebooks | verified | all three target the real PaySim schema, never fall back to the synthetic oracle, resolve the repository root even when kernels start in `notebooks/`, and execute against the schema fixture; DuckDB query cells pass |
| Redis + MLflow local service boundary | implemented | Compose config passes; image build hit host timeout and remains unverified |
| PaySim access/checksum and EDA | implemented | PaySim discovery/schema validation, optional full SHA-256, DuckDB CLI profile, and three real-data EDA notebooks exist; full Kaggle snapshot is not present, so application row counts/checksum/EDA conclusions remain unverified |
| PaySim raw snapshot command | verified | `make data-snapshot` and `.\make.ps1 data-snapshot` call the same CLI boundary; schema, SHA-256, row/step profile and atomic manifest persistence pass fixture unit tests; PowerShell help exposes the target, the current full 28-test suite passes, and execution on the full user-downloaded CSV remains pending |
| Dataset/entity ADR | planned | PaySim first; IEEE-CIS and Home Credit are alternatives |
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
