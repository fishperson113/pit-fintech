# M095 — Quick Locust `/score` UI runner

- **Datetime:** 2026-08-25
- **Status:** implemented and runner/request contract verified; no load test started.
- **Scope:** expose the existing safe write-path Locust scenario through the public Make and PowerShell task runners.

## Changes

- `Makefile`
  - added `LOCUST_HOST`, defaulting to `http://127.0.0.1:8000`;
  - added `make locust`;
  - added `locust` to `.PHONY` and Make help.
- `make.ps1`
  - added `-LocustHost`, defaulting to `http://127.0.0.1:8000`;
  - added `.\make.ps1 locust` and matching help text.
- Both runners execute the frozen `.venv` environment and launch:

  ```text
  locust -f scripts/locust_write_path.py --host <configured-host>
  ```

- The web UI is available at `http://localhost:8089` while the foreground Locust process is running.
- The target deliberately selects `locust_write_path.py`, not `locust_parity.py`; the latter resets a complete feature-version winlog namespace and is not the safe default for the owner's populated local Redis.

## `/score` request contract

Each Locust user creates a fresh destination entity in `WritePathUser.on_start`. The `_score` helper constructs:

```text
transaction_id
step
transaction_type = TRANSFER
amount
name_dest = fresh per-user entity
knowledge_step = optional for the late-arrival case
```

It sends the body with:

```text
self.client.post("/score", json=payload, ...)
```

The sequence contains ten score calls covering seed, monotonic advancement, exact retry, different-ID retry, a step gap, out-of-order delivery, late arrival, conflicting same-step retry, and resumed advancement. Every non-200 response is marked failed; expected feature step, staleness and status are asserted in Locust.

## Verification

- `mingw32-make -n locust`: passed and generated the expected frozen-env command.
- PowerShell parser: passed.
- Locust 2.46.3 `--list`: discovered `WritePathUser`.
- AST contract check: exactly one request destination `/score`; required JSON keys present.
- No Locust server or load run was started during verification.

## Usage

Windows PowerShell:

```powershell
.\make.ps1 locust
.\make.ps1 locust -LocustHost http://127.0.0.1:8000
```

GNU Make-compatible runner:

```text
make locust
make locust LOCUST_HOST=http://127.0.0.1:8000
```

## Known boundary

This scenario is a correctness-aware burst/concurrency test: each user executes ten calls and then stops. It is not yet a steady-state/soak capacity workload.
