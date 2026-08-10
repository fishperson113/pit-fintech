# M045 — Drop replay; serving owns the online write path; parity via Locust (ADR-008)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; no repo-env run; G6 redefined, not claimed)
- **Sprint / task:** Sprint 2, T6/T7 (guide §8/§9); supersedes M044
- **ADR:** [ADR-008](../../docs/adr/008-serving-owns-the-online-write-path.md) (accepted, supersedes
  ADR-007)

## Why

Owner review of M044 concluded the parity approach was near-vacuous: the online store was a
materialized **copy** of offline Gold and serving performed no computation, so parity compared
offline against a copy of itself. Worse, the replay harness drove a handler directly and **bypassed
`serving/app.py`**, so it tested a parallel re-implementation, not the serving pipeline. The
meaningful behaviour (a new transaction incrementing an entity, window eviction, a late-arrival
under the optimistic lock) is a runtime property of the write path under real, concurrent requests.

## Decision (ADR-008)

1. The serving `/score` pipeline owns the online write path: `read -> score -> compute new windowed
   state independently -> write` under the optimistic lock.
2. Drop the replay harness entirely.
3. Parity/load testing is a manual Locust script, not pytest.

## What changed

### Removed
- `src/pit_fintech/replay/` (`driver.py`, `parity.py`, `__init__.py`).
- `tests/unit/test_replay_driver.py`, `tests/unit/test_parity_classification.py`,
  `tests/integration/test_replay_parity.py`.
- CLI `replay` group + `pit replay parity`; `test-parity` and `parity` targets in `Makefile` and
  `make.ps1` (and the `PARITY_START/PARITY_END` vars).

### Added — `serving/online_state.py`
An independent windowed feature maintainer, the second implementation that makes parity meaningful:
- `LoggedEvent` + a per-entity Redis event log keyed `pit:<fsv>:winlog:<entity>:<id>`.
- `compute_window_features`: re-implements the offline history semantics independently — eligibility
  `e.step < cutoff_step AND e.knowledge_step <= cutoff_knowledge_step`, each window keeps
  `e.step >= cutoff_step - w`, money summed as `Decimal` (matching `DECIMAL(18,2)`), cast to float
  once. Emits the nine fields in `PAYSIM_HISTORY_FEATURE_NAMES` order.
- `apply_event`: append current event, sort, evict beyond `max(window)` hours, write under
  `WATCH`/`MULTI`/`EXEC` with bounded retry.
- `read_window_features`, `reset_online_log` (SCAN-scoped, never FLUSHDB).

### Changed — `serving/app.py`
`/score` runs the write step after `score_transaction` returns (read-before-write preserved,
AGENTS.md §11). The append is unconditional (history counts every event to a destination regardless
of type). A write failure is logged, not fatal to an already-computed score — the freshness fields
surface the resulting staleness.

### Added — `scripts/locust_parity.py`
Manual load + parity harness (not pytest). Bombards `/score` (concurrency exercises the lock), and
on test stop compares the online state the service maintained against the **independent** offline
oracle (`features/paysim_reference.compute_paysim_feature_row`) at cutoffs that cross the 1h/24h/168h
edges, a same-step pair, and a late-arriving correction. Prints `PARITY PASS`/`PARITY FAIL`. `locust`
is not a project dependency; install it into the serving env before running.

## Commands + results

- Agent, sandbox: `ruff check` + `ruff format --check` **clean** on `serving/online_state.py`,
  `serving/app.py`, `cli.py`, `scripts/locust_parity.py`; `ast` parses the changed modules.
- **Not run** (require the serving env / Redis / a running service): the FastAPI app, and the Locust
  parity/load run. These are the owner's gates.

### Owner gate commands

```powershell
.\make.ps1 lint
.\make.ps1 test-unit        # replay tests are gone; expect the suite to drop those and stay green
.\make.ps1 redis-up
.\make.ps1 serve            # start the FastAPI service (writes now update the online log)
# in another shell, with locust installed in the serving env:
uv pip install locust
locust -f scripts/locust_parity.py --host http://127.0.0.1:8000
#   -> watch for "PARITY PASS" / "PARITY MISMATCH ..." in the Locust log
```

## Deviations / known gaps

- **Scoring read path unchanged.** `/score` still reads features via the materialized
  `RedisFeatureProvider`, while the write path now builds the independent event-log store. Switching
  the read path to `online_state.read_window_features` (so the served vector comes from the same
  independent store) is the immediate follow-up; until then the winlog store is exercised by the
  write path + Locust parity, not by scoring itself.
- Guide §8 ("replay và parity harness") and the AGENTS.md one-producer-replay scope note are now
  stale; ADR-008 flags them for revision. Not rewritten here.
- `materialize_to_watermark` (M043) is superseded for the acceptance flow; whether it stays as a bulk
  warm-start is deferred (ADR-008).
- Agent static analysis only; nothing committed, so no commit hash yet.
