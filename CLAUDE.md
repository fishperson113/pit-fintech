# CLAUDE.md

Operational guide for Claude Code working in this repo. `AGENTS.md` is the authoritative
project charter (research question, hard constraints, sprint plan, scope guards) — read it
first when you need *why*. This file is the *how*: commands, layout, conventions, and the
non-negotiable rules that are easy to violate.

This project is bilingual: `AGENTS.md` and some reports are in Vietnamese; code, docstrings,
README, and ADRs are in English. Match the language of the file you are editing.

## What this project is (one paragraph)

A **point-in-time (PIT) correct feature platform for fraud scoring**, built local-first on a
Delta Lakehouse for one CPU machine. It is a paper-inspired adaptation (Liu et al., PVLDB 2023),
**not** a reproduction — never claim the paper's 3x speedup. Three invariants define acceptance:
(1) no feature reads data after the prediction cutoff, (2) offline training vectors and online
serving vectors are identical, (3) backfills are atomic, idempotent, and reproducible from an
exact data/version manifest. Outcomes are judged by machine-readable evidence, not by
architecture size.

## Hard rules — do not violate

1. **The user runs all commands.** Your job is to write code, run static analysis, and reason
   about output the user pastes back. Do not assume a command succeeded — wait for the user's
   verified result before calling anything "verified".
2. **Status words are strict.** In any status update distinguish `planned` / `implemented` /
   `verified` / `blocked`. Never call a milestone "done" or "verified" unless the user has
   confirmed the gate command passed.
3. **Milestone changelog is mandatory (see below).** Any change touching code, tests, notebooks,
   infra, ADRs, or reports must update three files together, or the pre-commit hook blocks the
   commit. Do not bypass the hook.
4. **Correctness logic lives in `src/` and `tests/`, never only in a notebook.** Notebooks are
   EDA/experiment surfaces that call into `src/`. They stay output-free / review-only in git.
5. **Never tune a model to hide a correctness failure.** Metrics dropping after leakage removal
   is a valid result. PR-AUC is the primary metric; never accuracy.
6. **Never use label-derived, post-outcome, or the four PaySim balance columns as features.**
7. **Scope guards (AGENTS.md §11):** no Spark/Kafka/K8s/Airflow/RabbitMQ/Redis-Streams/GPU/Ray
   in the MVP. Feast is a thin registry/retrieval contract, not the correctness oracle. Cloud and
   TypeScript serving start only after Python replay parity + Sprint 2 gates pass.

## Environment & commands

- **Package manager:** `uv` with a frozen `uv.lock` (Python 3.11). Always `uv sync --frozen`.
- **Two runners, same Python control plane:** `Makefile` (GNU Make) and `make.ps1` (Windows
  PowerShell companion). This is a **Windows-primary** workspace — the user typically runs
  `.\make.ps1 <target>`. Keep both files in sync when adding a target.
- **CLI:** everything routes through `pit` (Typer app, `src/pit_fintech/cli.py`), grouped as
  `pit data|features|model|notebooks ...` plus top-level `pit doctor`.

Common targets (see `README.md` "Implemented command contract" for the full table):

| Task | Command |
|---|---|
| Install env + hooks | `.\make.ps1 bootstrap` |
| Environment checks | `.\make.ps1 doctor` |
| Lint + format check | `.\make.ps1 lint` (fix with `format`) |
| Full test suite | `.\make.ps1 test` |
| PIT correctness lane | `.\make.ps1 test-temporal` |
| Unit / lakehouse tests | `.\make.ps1 test-unit` / `test-lakehouse` |
| CI fast lane locally | `.\make.ps1 check` |
| Build Delta tables | `.\make.ps1 build-lakehouse -Dataset sample\|paysim` |
| Locked training baseline | `.\make.ps1 train` |
| Verify changelog governance | `.\make.ps1 changelog-check` |

**Lint/format:** Ruff, line length 100, double quotes, rules `E,F,I,UP,B,SIM,RUF`. Run
`lint` before proposing a commit — the pre-commit hook auto-fixes and can otherwise cause a
"reformatted files" hook failure (this exact thing blocked an earlier commit).

**Test markers:** `temporal` (PIT edge cases) and `integration` (storage/service boundaries),
declared in `pyproject.toml` with `--strict-markers`.

## Repository map

```
src/pit_fintech/
  cli.py                 Typer control plane (data/features/model/notebooks + doctor)
  config.py              pydantic-settings, env prefix PIT_, .env-backed
  contracts/             events.py, features.py, manifests.py — schemas + evidence manifests
  data/                  canonical.py (dedup/tie-break), sample.py (synthetic oracle),
                         paysim.py, paysim_lakehouse.py, build_lakehouse.py (Bronze/Silver)
  features/              specs.py, reference.py (independent PIT oracle),
                         paysim_specs.py, paysim_recipient.py (frozen v1 contract)
  models/                paysim_lightgbm.py (E1-E4 spike), paysim_training.py (locked E1/E4)
  platform/              doctor.py, lineage.py (component fingerprints), notebooks.py
feature_repo/            frozen v1 specs; real Feast defs begin after Sprint 1 gates
data/fixtures/           committed synthetic source + hand-calculated expected vectors
tests/temporal/          exhaustive PIT correctness (ground truth = synthetic oracle)
tests/unit/  tests/integration/
notebooks/               01_data_profile .. 05_silver_training_baseline (EDA only)
docs/adr/                001 temporal-entity, 002 dataset, 003 feature-contract, 004 lineage
docs/reports/            human-readable reports (Sprint 1 completion, guides)
docs/feature-store/      per-sprint implementation guides
artifacts/changelog/     TRACKED audit trail (rest of artifacts/ is gitignored)
```

## Temporal semantics (the core invariant)

For prediction event `e`, a source event `s` is eligible only when:

```
(s.event_timestamp, s.transaction_id) < (e.event_timestamp, e.transaction_id)
AND s.created_timestamp <= e.created_timestamp
```

Windows are `[cutoff - window, cutoff)` — lower bound inclusive, current event excluded. Exact
duplicate rows are deduplicated; conflicting duplicates fail loudly. Online path must
`read -> score -> update` (query strictly before mutating state). The **synthetic temporal
fixture is the correctness ground truth**; PaySim fraud labels are only model-eval ground truth.

## Frozen contracts (do not change without an ADR + version bump)

- **Dataset snapshot:** `paysim1:16910f90577b0d98`, 6,362,620 rows, steps 1–743.
- **FeatureSpec `paysim-fraud-recipient-v1`** (ADR-003): entity `destination_entity_id`; scope
  `CASH_OUT`/`TRANSFER` with destination kind `CUSTOMER`; 12 fields (3 request-time + count/sum/
  history-flag at 1h/24h/168h); strict `prior_step < current_step`. Any semantics/order/dtype/
  default change bumps the version and requires a backfill.
- Changing a frozen contract = new ADR in `docs/adr/` + `PROJECT_STATUS.md` update.

## Milestone changelog governance (AGENTS.md §13 — enforced by hook)

Whenever you start, meaningfully change, complete, or verify a milestone, update **all three**
in the same commit:

1. `artifacts/changelog/PROJECT_STATUS.md` — current planned/implemented/verified/blocked state.
2. `artifacts/changelog/CHANGELOG.md` — dated entry: milestone ID, change, gate/result, log link.
3. `artifacts/changelog/milestones/M0NN-<slug>.md` — detailed log (datetime+status, scope/gate,
   decisions+rationale, files touched, commands+results, deviations, known gaps, next steps).

The `milestone-changelog` pre-commit hook (`scripts/verify_milestone_changelog.py`) blocks
commits that touch tracked implementation without these updates. Never claim a milestone done to
the user unless all three are in sync. Don't hand-edit evidence numbers that a command can emit.

## Current state (as of 2026-07-27, commit 6e93e7f + uncommitted M021)

- **Sprint 1: complete & verified** (M001–M020). Temporal contract, PaySim feasibility
  (`AMBER_CORRECTNESS_ONLY`), versioned Bronze/Silver, exact-Silver E1/E4 baseline, Sprint 1
  closure report all verified. Baseline: E1 PR-AUC 0.258342, E4 0.102766 (natural prevalence;
  weaker E4 kept as valid evidence).
- **M021 (component-lineage guard): implemented, not verified.** Replaces commit-equality with
  `component-fingerprint-v1` (`platform/lineage.py`, ADR-004): exact Delta/contract is the source
  gate; training and lakehouse have independent fingerprints/dirty state; docs-only commits don't
  force a Silver rebuild. Implementation gates pass (unit 39/39, lakehouse 4/4, notebooks 5/5);
  the open item is post-commit `train` reusing legacy Silver without rebuild + emitting new
  fingerprint fields. **This is the current work in the git status.**
- **Sprint 2: planned.** Thin Feast contract, CLI-built Gold, full/range/incremental backfill,
  Redis materialization, gated promote/rollback, FastAPI scoring, one-producer ordered in-memory
  replay, offline/online parity, sample E2E. Next concrete step per AGENTS.md §2: add a
  probability-scoring wrapper before serving, starting from exact Silver v1.
- **Sprint 3: planned** (experiment matrix E1–E5/P1–P5, fault injection, cloud smoke, optional TS
  scorer, optional external-VPS observability).

## Working conventions

- Prefer editing existing modules over adding new ones; match surrounding style and the terse,
  purpose-first one-line docstrings used across `src/`.
- New CLI behavior goes through a `pit` subcommand and gets a `Makefile` + `make.ps1` target.
- When you propose commands for the user to run, give the PowerShell form first (`.\make.ps1 ...`).
- Reports for humans → `docs/reports/`; raw run outputs/manifests → `artifacts/` (gitignored
  except `artifacts/changelog/`).
