# M048 — Locust/OTel make targets and deprecation cleanup

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gates below)
- **Sprint / task:** developer-experience + Sprint 2 T7/T6 observability + parity tooling (ADR-008)

## Scope

Follow-up to M047, requested by the owner:

1. Make targets to **run the Locust web UI + parity harness** and to **run the service with OTel**.
2. Because `setup` (`uv sync --all-groups`) wipes hand-installed tools, a `tools` target to reinstall
   them (locust + the four OTel packages) in one shot.
3. **Deprecation cleanup**: remove/refresh the stale artifacts left behind by the M045 (ADR-008)
   replay removal and the M030 throwaway spike.

## What changed

### New make targets (both `Makefile` and `make.ps1`)
- `tools` — `uv pip install locust` + the four ADR-008 OTel packages
  (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`,
  `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-logging`). OTel and locust
  stay out of `pyproject.toml` (ADR-004 fingerprints), so this target is the supported way to
  install them into the current env after `setup`.
- `locust` — `uv run locust -f scripts/locust_parity.py --host $(LOCUST_HOST)` (default
  `http://127.0.0.1:8000`; web UI at `http://localhost:8089`). New `LOCUST_HOST` make variable and
  `-LocustHost` PS parameter.
- `serve-otel` — `uv run pit serving up --otel`, reading `PIT_OTEL_ENDPOINT` from `.env` (M047).

### Deprecation cleanup
- `scripts/spike_feast_t1.py` — M030's "throwaway" T1 design spike, superseded by the real G1 lane
  (`tests/integration/test_feast_registry_g1.py`, `feature_repo/`, M031). **Marked for removal**;
  the file itself is removed with `git rm` (sandbox could not run git — see Owner gates). Its role
  is fully replaced, and `tests/integration/test_feast_registry_g1.py` docstring updated to say the
  spike is removed. Changelog/milestone docs keep their dated references as history.
- `feature_repo/definitions.py` — comment still said the (never-built) `PushSource` would be "fed
  by the replay/materializer (T5)". ADR-008 removed replay; the serving process owns the online
  write path (`serving/online_state.py` → Redis). Comment rewritten to match.
- `tests/e2e/test_sprint2_e2e.py` — module-docstring chain still listed "one-producer replay";
  `test_replay_reads_before_it_updates` asserted on `ReplayRunResult`/`ReplayStepResult` types that
  no longer exist. Chain rewritten (read -> score -> online write), test renamed to
  `test_score_reads_before_it_updates`, docstring now points at the ADR-008 `serving/app.py`
  ordering + `scripts/locust_parity.py` as the manual gate. The T9 lane stays skipped/planned.
- `scripts/locust_parity.py` — parity-mismatch OTLP export now prefers `PIT_OTEL_ENDPOINT` (M047)
  before `OTEL_EXPORTER_OTLP_ENDPOINT`; docstring points at `tools`/`locust` targets.
- `serving/telemetry.py` — docstring install instructions now point at `tools`.

## Commands + results

- Agent static analysis only. Edits are Ruff-clean by inspection; `make.ps1` cases use the existing
  `Invoke-Checked` helper.
- **Owner lint run (2026-08-10) caught one E501** (line too long, 101 > 100) in the
  `test_score_reads_before_it_updates` docstring (`tests/e2e/test_sprint2_e2e.py`); the paragraph
  was rewrapped so every line is <= 100. No other findings in the run.
- **Owner gates:**

  ```powershell
  .\make.ps1 tools                 # install locust + OTel packages into the current env
  .\make.ps1 lint                  # ruff clean / format check
  git rm scripts/spike_feast_t1.py # finish removing the M030 throwaway spike (sandbox could not)
  # then, with Redis up and a trained model:
  .\make.ps1 redis-up
  .\make.ps1 serve-otel            # start /score with OTel -> PIT_OTEL_ENDPOINT
  .\make.ps1 locust                # open http://localhost:8089 and run the parity load
  ```

## Known gaps / next steps

- Nothing committed yet; the milestone-changelog trio is part of this change set.
- Not touched (planned, not deprecated): `tests/e2e/` T9 lane stays skipped; `training/lifecycle.py`,
  `serving/feature_provider.py` SQLite/Feast/Upstash adapters, `materializer.py` SQLITE/G8/Feast
  PushSource remain `NotImplementedError` round-0 skeletons by design.
