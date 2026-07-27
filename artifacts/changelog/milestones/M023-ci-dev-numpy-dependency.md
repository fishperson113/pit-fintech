# M023 — CI dev-lane numpy dependency

- Date: 2026-07-27
- Status: implemented; green CI run pending user execution

## Scope and acceptance

The GitHub Actions fast-fixture lane (`.github/workflows/ci.yml`) failed `make test-unit` on the
remote runner while the same command was green locally. Collection of
`tests/unit/test_paysim_lightgbm_spike.py` aborted with `ModuleNotFoundError: No module named
'numpy'`, interrupting the whole unit suite (exit code 2).

Acceptance: the CI unit lane collects and runs every `tests/unit` module without installing the
heavy `training` group, and the numeric correctness tests for the LightGBM spike keep running on
CI rather than being skipped.

## Root cause

- CI provisions only the locked core plus the `dev` group (`uv sync --frozen --group dev`).
- `numpy` is not a direct project or `dev` dependency; it entered the lock only transitively
  through the optional `training` group (lightgbm/scikit-learn/mlflow).
- Local runs are green because the developer machine has the `training` group synced, so `numpy`
  is present.
- `tests/unit/test_paysim_lightgbm_spike.py` imports `numpy` at module top level, so pytest fails
  at collection time when the `training` group is absent.
- The production code is not at fault: `src/pit_fintech/models/paysim_lightgbm.py` imports numpy,
  lightgbm and mlflow lazily inside functions. Only the test module needs numpy at import time,
  and it uses numpy solely to build small arrays for `_threshold_for_fixed_fpr` /
  `_binary_operating_metrics`; its lightgbm/mlflow references are string constants and mocks.

## Decisions

- Add `numpy>=2.4,<3` as a direct member of the `dev` dependency group.
- Do not add the `training` group to the CI fast lane: it would pull lightgbm/mlflow/scikit-learn
  and violate the fast-fixture-lane intent in AGENTS.md §7/§8.
- Do not module-level `importorskip("numpy")`: that would skip the entire spike test module on
  CI, dropping the non-numpy tests (CLI discovery, MLflow-mock, skops allowlist) and losing the
  fixed-FPR threshold correctness coverage.
- The chosen bound matches the already-locked numpy (2.4.6 on 3.11, 2.5.1 on 3.12), so the
  re-lock only promotes numpy to a direct `dev` member without changing resolved versions.

## Files added or changed

- `pyproject.toml`
- `uv.lock` (re-locked by the user via `make lock` / `.\make.ps1 lock`)
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

No command was executed by the agent. The change was applied by static inspection:

- `tests/unit/test_paysim_lightgbm_spike.py:8` is the only top-level `numpy` import across
  `tests/unit`; `tests/unit/test_paysim_training.py` imports only `duckdb`-backed src modules and
  does not import numpy at collection time.
- numpy is already resolved in `uv.lock` (2.4.6 / 2.5.1), so `>=2.4,<3` is satisfiable without a
  version change.

Pending user execution:

```text
.\make.ps1 lock          # record numpy in the dev group
# stage pyproject.toml + uv.lock, commit, push
# confirm the fast-fixture-ci "Unit tests" step is green
```

## Known gaps and next step

- Verification depends on the remote CI run turning green after `uv.lock` is committed; until
  then this milestone stays implemented, not verified.
- If a future unit test needs another `training`-only transitive dependency at import time, it
  must either mock it or be added to the `dev` group under the same reasoning.
