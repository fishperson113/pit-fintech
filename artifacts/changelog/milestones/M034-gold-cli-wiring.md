# M034 — Wire Gold build and promotion through CLI runners

- Date: 2026-08-05
- Status: **implemented, not verified**.
- Scope: CLI wiring, Makefile/make.ps1 runner parity, CLI integration tests, README command contract.
- Gate: CLI command wiring and existing unit/temporal/integration lanes.

## Decision

Expose two explicit commands:

- `pit features build-gold --start N --end M [--run-id ID] [--dataset paysim]` builds both Gold
  tables into staging and never promotes by default.
- `pit features promote-gold --run-id ID [--dataset paysim]` reloads the staged
  `gold-build-manifest.json` into `OfflineFeatureBuildResult` and promotes explicitly.

The promoter reconstructs the frozen nested dataclasses from the manifest rather than inventing a
second state format. It reports a missing or malformed manifest and does not build implicitly.

## Files changed

- `src/pit_fintech/cli.py` — commands, manifest loader, staging/promotion output.
- `Makefile` — `gold` and `promote-gold` targets.
- `make.ps1` — `gold` and `promote-gold` switches plus `-Start`, `-End`, `-RunId` parameters.
- `tests/integration/test_cli_gold.py` — two CliRunner wiring tests using monkeypatched objects and
  no real lakehouse.
- `README.md` — command contract and staging/promotion usage.
- `artifacts/changelog/PROJECT_STATUS.md`.
- `artifacts/changelog/CHANGELOG.md`.

## Commands and results

- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/integration/test_cli_gold.py -q` — 2 passed.
- Read-only manifest reload check against the existing staging manifest — run_id
  `fixgate-real-silver-audit-step1`, 664 pre rows, 2708 post rows, partitions `(1,)`.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format .` — 1 file reformatted.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff check .` — All checks passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format --check .` — 85 files already formatted.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/unit -q` — 77 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/temporal -q` — 73 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/integration -q` — 17 passed, 1 existing Ibis deprecation warning.
- `git status --short` — implementation changes and pre-existing worktree entries remain; no destructive Git command was run.

## Deviation and known gaps

- No real `build_offline_features` or `promote_staged_gold` command was run in this milestone, so
  full Gold build/promote remains unverified.
- The CLI wiring tests intentionally monkeypatch the builder/promoter and use temporary paths to
  ensure they cannot touch the committed lakehouse.
- The user-run follow-up should execute `make.ps1 gold -Start 2 -End 2`, capture the run ID, then
  execute `make.ps1 promote-gold -RunId <run-id>` in an isolated/approved environment.
