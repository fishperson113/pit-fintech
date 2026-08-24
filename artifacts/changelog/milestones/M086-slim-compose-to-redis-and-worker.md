# M086 — Slim dev surface: Compose, Make targets, and Feast repo layout

- 2026-08-24 — **implemented** (owner-directed cleanup; gates owner-pending).

## Scope / gate

Slim the container footprint to what the owner actually runs locally: **Redis (online store) +
`pit-online-worker` (ADR-010 event write path)**. The scoring API and MLflow now run directly on
the Windows host (`.\make.ps1 serve` / `mlflow-ui`), not as Compose services. The MLflow + Grafana
observability cluster is no longer hosted as one on-machine stack, so the standalone otel Compose
file is removed.

Gate: `docker compose config` parses and `docker compose up -d redis pit-online-worker` starts the
two services (owner-run). No `src/` or test behavior changed, so the correctness lanes are
unaffected.

## Changes

- `compose.yaml`: removed the `mlflow`, `api`, `minio` (profile), and `jupyter` (profile lab)
  services and the `mlflow-data` / `minio-data` named volumes. Kept `redis` and
  `pit-online-worker`; only `redis-data` remains. Reworded the worker comment (the API now runs on
  the host and produces the score events this worker consumes).
- Deleted `deploy/vps/docker-compose.otel.yml` (the standalone otel-collector + Tempo Compose).
  The `otelcol-config.yaml`, `tempo-config.yaml`, `loki-config.yaml`, `prometheus-scrape-job.yml`,
  and `grafana-dashboard.json` samples are kept for the separate VPS.
- `deploy/vps/README.md`: replaced the "copy + `docker compose -f docker-compose.otel.yml up`"
  instructions with an inline `otel-collector` + `tempo` service snippet to merge into the VPS's
  existing compose; fixed the verification log command.
- `Makefile` / `make.ps1`: dropped the `lab-container` target (jupyter profile is gone); repointed
  `up-core` and `logs` from `redis mlflow` to `redis pit-online-worker`; removed the stale "stops
  the container first" note on `mlflow-ui`.
- `README.md`: removed the `lab-container` row, repointed the `up-core/status/logs/down` and
  "Local infrastructure" descriptions to Redis + `pit-online-worker` (API/MLflow on host).

## Decisions

- **Remove `api` from Compose** (owner choice): the FastAPI scorer runs on the host via uvicorn;
  the worker still consumes the Redis Stream the host process writes. The `worker-up`/`worker-down`
  targets are unchanged.
- **Keep the deploy/vps config samples** (owner choice): only the compose file was deleted, so the
  VPS otel/Tempo/Prometheus/Grafana configs stay usable when merged into that host's own compose.

## Make target cleanup (owner-directed second pass)

Trimmed `Makefile` + `make.ps1` from ~60 targets to the 29-target core set the owner actually
uses, keeping full capability reachable through the `pit` CLI. **Kept**: `help`, `bootstrap`,
`setup`, `doctor`, `lock`, `lab`, `lab-training`, `data-sample`, `build-lakehouse`, `gold`,
`promote-gold`, `train`, `serve`, `worker`, `materialize`, `backfill`, `mlflow-ui`, `demo-score`,
`up-core`, `status`, `logs`, `down`, `test-temporal`, `test-unit`, `test`, `lint`, `format`,
`check`, `changelog-check`. **Removed** (all remain available via `uv run pit ...`): the whole
`demo-*`/`debug-*`/`locust*` cluster (except `demo-score`), `serve-otel`, `worker-up`/`worker-down`,
`tools`, `redis-up`/`redis-down`, `parity-reconcile`, `materialize-recover`, `test-lakehouse`,
`test-integration-full`, `test-t3-smoke`, `test-t4-dataset`, `model-spike`, `train-gold-candidate`,
`gold-evaluate`, `ingest`/`ingest-event-history`, `test-notebooks`, `build-fixture`, `features`,
`lakehouse-history`, `profile`, `data-snapshot`, `demo`. Dropped the now-unused Make variables and
PowerShell params. Makefile targets and `make.ps1` switch cases verified 1:1; `make.ps1` parses.

Repointed live docs off the removed targets to the `pit` CLI: `README.md` (command-contract table
+ quickstart/spike/feature-inspect walkthroughs), `deploy/vps/README.md` (telemetry start), and the
`docs/data-access.md` / `docs/demo/e2e-demo.md` how-to guides. Historical audit logs
(`artifacts/changelog/**`) and point-in-time `docs/reports/**` were intentionally left unchanged —
they record commands as run at the time.

## Feast repo layout cleanup (owner-directed third pass)

Owner decided to **keep Feast as a separate top-level directory** (separation of concerns, not
folded into `src/`) but tidy the layout. Two changes:

- **Deleted `feature_repo/feature_specs.py`** — a re-export shim that nothing imported (grep for
  `feature_specs` across `src/tests/scripts` = 0 hits; the only mention was a docstring in
  `definitions.py` explaining why it did *not* use it). Dead code.
- **Renamed `feature_repo/` → `feature_store/`** (via `git mv`, history preserved) to match the
  idiomatic MLOps name. The contract still lives in `src/pit_fintech/features/paysim_specs.py`;
  `definitions.py` still imports it (single source of truth, ADR-006), and no `src/` module imports
  the Feast definition files directly — access is via `FeatureStore(repo_path=...)` only.

No ADR was cut: the rename changes neither the feature contract's fields/semantics/versions nor
Feast's role, so it is outside the ADR-gated surface (AGENTS.md §11). It is recorded here and the
live repo maps (`README.md`, `CLAUDE.md`) were updated; historical ADR/changelog/guide text that
names `feature_repo/` was left as-written.

Load-bearing references repointed to `feature_store`: `pyproject.toml` (`src = [...]`, ruff/isort
first-party resolution), `Makefile` + `make.ps1` (ruff `check`/`format` dir args),
`scripts/verify_milestone_changelog.py` (`IMPLEMENTATION_PREFIXES`, so the governance hook still
guards the dir), and `tests/integration/test_feast_registry_g1.py` (`FEATURE_REPO` path constant +
`from feature_store import definitions`). Docstrings/comments in `data/paysim_fixture.py`,
`features/build_offline.py`, `materialization/materializer.py`, `platform/feast_registry.py`,
`serving/feature_provider.py`, and `tests/integration/test_paysim_fixture.py` updated for accuracy.
Verified: `ruff check` + `ruff format --check` clean on the touched set; `py_compile` clean; no
`feature_repo` remains in any `.py`/config/Makefile (only in intentionally-retained historical docs).
The G1 lane itself is owner-run (needs the `feast` group + local PaySim CSV) to confirm the moved
`from feature_store import definitions` resolves under `feast apply`.

## Files touched

- `compose.yaml`, `Makefile`, `make.ps1`, `README.md`, `CLAUDE.md`, `deploy/vps/README.md`,
  `docs/data-access.md`, `docs/demo/e2e-demo.md`, `pyproject.toml`,
  `scripts/verify_milestone_changelog.py`
- renamed: `feature_repo/{__init__.py,definitions.py,feature_store.yaml}` →
  `feature_store/…`; docstring/comment touch-ups in `src/pit_fintech/data/paysim_fixture.py`,
  `src/pit_fintech/features/build_offline.py`, `src/pit_fintech/materialization/materializer.py`,
  `src/pit_fintech/platform/feast_registry.py`, `src/pit_fintech/serving/feature_provider.py`,
  `tests/integration/test_feast_registry_g1.py`, `tests/integration/test_paysim_fixture.py`
- deleted: `deploy/vps/docker-compose.otel.yml`, `feature_repo/feature_specs.py`

## Known gaps / next steps

- Owner to run `docker compose config` + `up -d redis pit-online-worker` to move this from
  implemented → verified.
