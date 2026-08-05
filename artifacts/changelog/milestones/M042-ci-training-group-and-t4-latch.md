# M042 — CI fix: install the training dependency group and latch the T4 lane against a fake-green run

- Date: 2026-08-05
- Status: **implemented** (not verified — awaiting a green CI run).
- Scope: CI reliability fix — the fast-fixture-ci lane failed because the T4 integration test
  required the optional `training` dependency group that the workflow never installed; install it
  and add a latch so the lane cannot skip silently.

## Problem

- GitHub Actions run 30995527627 (workflow fast-fixture-ci, commit d2ce188, 2026-08-05T09:58:57Z)
  failed at step "Delta sample snapshot and time travel" (`make test-lakehouse`), exit code 2.
- Failing test: tests/integration/test_t4_training.py::test_t4_train_candidate_logs_complete_mlflow_contract
- Error: ModuleNotFoundError: No module named 'lightgbm' at src/pit_fintech/models/paysim_lightgbm.py:152,
  surfaced as RuntimeError "Training dependencies are unavailable."
- Lane result on CI: 1 failed, 13 passed, 7 skipped.
- Every other step passed: lint (ruff clean, 88 files formatted), make data-sample,
  make test-temporal (73 passed), make test-unit (87 passed).

## Root cause

- Commit d2ce188 added the T4 lane, which calls train_candidate() and therefore requires the optional
  `training` dependency group (lightgbm, mlflow, scikit-learn).
- .github/workflows/ci.yml synced only `uv sync --frozen --group dev`.
- Makefile target `test-lakehouse` ran `uv run pytest -q tests/integration` with no group flag.

## Changes

3 files, no correctness-path logic touched.

1. .github/workflows/ci.yml
   - "Sync locked environment" now runs `uv sync --frozen --group dev --group training`.
   - The "Delta sample snapshot and time travel" step alone now sets `PIT_REQUIRE_TRAINING: "1"`.
2. Makefile
   - `test-lakehouse` now runs `uv run --group training pytest -q tests/integration`.
   - New self-contained local target `test-integration-full`, which runs
     `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups` for both `pit data sample` and the
     integration lane, matching the existing `test-t3-smoke` / `test-t4-dataset` convention.
   - `test-integration-full` added to .PHONY.
   - A comment above `test-lakehouse` records the local side effect (see EVIDENCE).
3. tests/integration/test_t4_training.py
   - `_require_training()` mirrors `_require_feast()`: skips with an actionable message when the
     training group is absent.
   - When PIT_REQUIRE_TRAINING=1 the skip escalates to pytest.fail. This is the latch against a
     fake-green CI: if anyone drops `--group training` from ci.yml or from the Makefile lane, the T4
     lane fails loudly instead of skipping silently.

## Evidence

All measured 2026-08-05 on Windows/local:

- `uv sync --frozen --group dev --group training --dry-run` into a clean environment outside the repo:
  exit 0, would install 194 packages, including lightgbm==4.7.0, mlflow==3.14.0, scikit-learn==1.9.0.
- `uv sync --frozen --group training --dry-run` against the repo .venv: "Would uninstall 36 packages",
  including feast==0.65.0, ibis-framework==12.0.0, redis==7.4.1. This is why `test-integration-full`
  exists and why the Makefile comment exists; it is standard uv behaviour, not a bug.
- ruff check: All checks passed. ruff format --check: 88 files already formatted.
- Integration lane in the repo .venv with --all-groups: 21 passed, 1 warning (the pre-existing Ibis
  fetch_arrow_table deprecation). T4 ran for real, nothing skipped.
- Latch mutation test, run in a dev-only environment outside the repo:
  - without the variable: 1 passed, 1 skipped, exit 0
  - with PIT_REQUIRE_TRAINING=1: 1 failed, 1 passed, exit 1, message containing "PIT_REQUIRE_TRAINING=1"
  The two runs differ, so the latch is proven to be able to go red.
- The repo .venv was re-checked afterwards: 21 passed and feast 0.65.0 still importable.

## Limits

- All evidence above is local on Windows. No green CI run on ubuntu-latest confirms the fix yet.
  Expected integration lane on CI: 14 passed, 7 skipped, 0 failed (7 skips = 4 Feast + 3 PaySim fixture,
  by design). Status stays `implemented` until a green run exists.
- The latch protects the T4 lane only. Other lanes can still skip silently if their optional group is
  missing; the Feast lane skipping on CI remains intended behaviour.
- Running `make test-lakehouse` locally still removes 36 packages from .venv. That was documented, not
  fixed; `make test-integration-full` is the alternative path.
- No feature, oracle, Gold or training logic changed. No checksum, no metric, no Delta version affected.
