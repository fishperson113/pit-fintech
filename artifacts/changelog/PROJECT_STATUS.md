# Project status

Last updated: 2026-07-21. Status words are strict:

- **planned**: present in the six-week guide, with no claim that code exists;
- **implemented**: code/artifact exists but the relevant gate may not have run;
- **verified**: the documented command has passed in this workspace.

## Project governance

| Artifact / guard | Status | Evidence |
|---|---|---|
| Cumulative changelog | verified | `artifacts/changelog/CHANGELOG.md` |
| Detailed milestone logs | verified | M001 and M002 logs under `artifacts/changelog/milestones/` |
| Milestone pre-commit guard | verified | four unit cases pass; installed at `.git/hooks/pre-commit` |
| Human-readable reports location | verified | reports moved to `docs/reports/` |
| Four-slide PIT proposal deck | verified | 4 slides render at 1440x810 without overflow/errors; button and keyboard navigation pass |

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
| JupyterLab and three Sprint 1 notebooks | verified | all three execute in memory through the project kernel |
| Redis + MLflow local service boundary | implemented | Compose config passes; image build hit host timeout and remains unverified |
| IEEE-CIS access/checksum | planned | requires competition-rule acceptance |
| Entity sensitivity and full data profile | planned | Day-2 decision input |
| IEEE-CIS vs PaySim ADR decision | planned | do not lock before EDA |
| Bronze/Silver Delta sample | verified | 8 Bronze rows, 7 Silver rows, separated label table; 1 integration/time-travel test passes |
| Static/PIT LightGBM baseline | planned | later Sprint 1 |

## Sprint 2

Feast repository, Gold features, full/range/incremental backfill, Redis materialization,
LightGBM + MLflow model run, gated promotion/rollback, FastAPI scoring, chronological replay,
offline/online parity, and sample E2E are all **planned**.

## Sprint 3

E1–E5/P1–P5 experiment execution, monitoring, fault injection report, clean-room audit, cloud
smoke path, final report, and optional TypeScript scorer are all **planned**.

This table must be updated whenever an artifact crosses from planned to implemented or from
implemented to verified.
