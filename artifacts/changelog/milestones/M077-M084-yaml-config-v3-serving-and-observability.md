# M077–M084 — YAML runtime config, v3 serving lineage, and observability repair

- **Datetime:** 2026-08-19
- **Status:** implemented; focused/static and read-only live verification passed; owner VPS recreate,
  v3 champion promotion, and fresh-Loki verification pending.
- **Scope:** move non-secret configuration to committed YAML; align the serving/training/promotion
  path with the active v3 FeatureSpec; speed up worker image rebuilds; and repair the Grafana/Loki/
  OTLP observability path down to dashboardable latency percentiles.

This consolidated log replaces the separate M077, M078, M079, M080, M081, M082, M083 and M084 files.

## M077 — Move non-secret runtime configuration to YAML

Replaced the all-in-`.env` shape with a committed root `config.yaml` for non-secret defaults (paths,
dataset defaults, contract versions, local service URLs, ports, logging, optional OTel endpoint).
`Settings` now loads `YamlConfigSettingsSource` after environment and dotenv, giving precedence
init args > process environment > `.env` > `config.yaml` > secrets directory. `PIT_*` variables remain
high-precedence CI/Docker/deployment overrides; credentials stay environment-only. Added direct
`pyyaml>=6,<7`, refreshed `uv.lock`, reduced `.env.example` to overrides/credentials/invocation flags,
and updated README, VPS notes, Makefile, and PowerShell help.

Verification: `test_config` 2 passed; `tests/unit` 112 passed; focused Ruff/format passed; `uv lock`
resolved 240 packages.

## M078 — Align the v3 training/serving lineage

`serve-otel` correctly failed closed: champion alias `paysim-fraud-lightgbm@champion` still resolved
v2 run `84d68cb115e946f886b83c594da7960f` (legacy 12-field order), and read-only MLflow inspection
found no v3 run. `scripts/run_t4_training.py` also hardcoded `feature_service_version=
paysim-fraud-scoring-v2`; an initial fix wrongly read `manifest.feature_service_version` (absent on
`ApplicationLakehouseManifest`) and was corrected to the shared `PAYSIM_FEATURE_SERVICE_VERSION`
constant. Added a regression test proving the training path resolves `paysim-fraud-scoring-v3`; the
serving input-contract guard (v2 model must not score v3 vectors) was left unchanged.

Verification: focused Ruff/`py_compile` passed; v3 lineage regression + full unit suite 113 passed.
No training or promotion was started.

## M079 — Make champion promotion understand the v3 T4 candidate

Serving input assembly was already correct (request features + Redis history combined in
`build_model_vector`, emitted in the artifact's ordered names, with a startup order guard). The
mismatch was lifecycle state: champion still pointed to v2 run `84d68...`, T4 produced v3 run
`70dbc360bbfd43a480198bb712ad03d7` with the correct 10-field artifact, and `model promote-champion`
only recognized the older deployable-Gold tags. Added `_model_promotion_rejection` in `cli.py`:
promotion now accepts a deployable Gold E4 run or a T4 E4 candidate, but requires
`feature_service_version == paysim-fraud-scoring-v3` and an exact 10-field
`ordered_feature_names.json`; a v2 model is rejected before the alias can move. Added accept-v3 /
reject-v2 unit tests.

Verification: `tests/unit` 115 passed; focused Ruff/format/`py_compile` passed. No alias moved.

Owner action: `uv run pit model promote-champion --run-id 70dbc360bbfd43a480198bb712ad03d7` then
`.\make.ps1 serve-otel`.

## M080 — Optimize worker Docker rebuild caching

`pit-online-worker` is a Python Redis Streams consumer with the async DuckDB/pyarrow/deltalake parity
path, not the Redis server, so it shares the offline wheels; the Dockerfile had no persistent uv cache
and re-downloaded large wheels on repeated builds. Added BuildKit syntax and a locked `/root/.cache/uv`
mount to both `uv sync` layers and the optional OTel `uv pip install` layer. Runtime/dependency
semantics unchanged.

Verification: `docker buildx build --check` no warnings; `docker compose config` passed; focused Ruff
+ promotion-contract tests passed (2). The worker image rebuilt and runs on
`pit:paysim-fraud-scoring-v3:events` with Redis `loading:0`/`PONG` and Compose `Up`; a transient
container-name conflict on first recreate self-resolved. No rebuild wall time was captured as a
benchmark.

## M081 — Repair Grafana/Loki visibility and metric dashboard coverage

Read-only live probes found Grafana/Prometheus healthy, target `pit_fintech_scoring` `UP`, and live
values for `pit_scoring_requests_total`, `_errors_total`, and `_latency_ms_avg`
(`pit_parity_checked_total` absent by design — Collector routes OTel metrics to `debug`). The actual
Grafana dashboard (`C:\workspace\prometheus-grafana`) had only Loki panels, and Loki OTLP resource
attributes were not promoted to the `service_name` stream label. Added the Loki `service.name` →
`service_name` index-label mapping (request/entity/trace fields stay structured metadata), added
Prometheus request/error-ratio/latency panels, shifted Loki panels down, bumped dashboard 9 → 10, and
mirrored the Loki mapping into `deploy/vps/loki-config.yaml` as the non-secret sample.

Verification: live Prometheus target/metric queries, VPS Compose config, Loki/Collector/Prometheus/
Grafana YAML, and both dashboard JSONs parsed (13 panels). No VPS service was started.

## M082 — Make config.yaml the runtime configuration source

`config.yaml` held the intended OTLP endpoint, but `Settings` still loaded `.env` via `env_file`,
letting stale feature-version/endpoint values override YAML; the worker image also did not copy
`config.yaml` and relied on Compose `${PIT_OTEL_ENDPOINT}` interpolation. Removed implicit dotenv
loading from `config.py` (explicit `PIT_*` overrides retained), copied `config.yaml` into the image,
removed the Compose interpolation, and documented the new source boundary.

Verification: effective settings resolve from YAML (`otel_endpoint=http://100.116.36.6:4318`,
`feature_service_version=paysim-fraud-scoring-v3`); config tests 2 passed; Ruff/`git diff --check`,
Dockerfile check, and Compose config passed; real OTLP smoke via `configure_telemetry()` created and
`force_flush`ed a `/v1/logs` batch with no exporter exception. Loki persistence remains pending.

## M083 — Diagnose missing OTLP logs at the Collector boundary

VPS evidence: Collector ready on `:4318` but emitting only `Metrics` debug batches (no `Logs`); Loki
returned HTTP 200 with `returned_lines=0`; Loki reported `disk usage exceeded threshold, throttling
writes` at `97.62%`; Collector warned that `otlp`/`otlphttp` aliases are deprecated. This separates the
trace path from the log path and identifies independent Loki disk pressure. In
`prometheus-grafana/otelcol-config.yaml`, renamed `otlp/tempo` → `otlp_grpc/tempo` and `otlphttp/loki`
→ `otlp_http/loki`, and added `debug/logs` beside the Loki exporter so the next request proves
Collector log receipt. YAML parse passed. VPS recreate, fresh-log smoke, and non-destructive disk
remediation (`df -h`/`docker system df`/`du`; never `down -v`) remain owner-pending.

## M084 — Make serving metrics dashboardable with latency percentiles

The configured API scrape target refused the connection (YAML default `api_host: 127.0.0.1` after
`.env` removal), so the dashboard was not the only blocker. Extended `/metrics` in
`serving/app.py` with a classic Prometheus histogram (`pit_scoring_latency_ms_bucket`/`_count`/`_sum`,
buckets 1ms–5000ms + `+Inf`), keeping request/error counters separate and counting only successful
observed-latency requests. Added `tests/unit/test_serving_metrics.py`. Updated the observability
dashboard: request rate over a 5-minute window, error rate as a percentage, and p50/p90/p95/p99 via
`histogram_quantile` (version stays 10, Prometheus UID `prometheus`).

Verification: focused config/metrics tests 3 passed; Ruff/compile/diff passed; dashboard JSON parsed
(13 panels). Live Prometheus/API runtime verification is pending until the API is running and scraped.

## Known limits and boundaries

- `config.yaml` is safe to commit and is the source for stable local defaults; `.env` remains for
  local overrides only. Kaggle credentials and other secrets must never be placed in YAML.
- No MLflow champion alias was moved and no v3 model was promoted by agent verification; operational
  promotion still requires the owner command with the verified v3 run id.
- Observability changes in the separate `C:\workspace\prometheus-grafana` VPS stack are not verified
  live until the owner recreates the Collector/Loki/Grafana/Prometheus services and issues a fresh
  request; Loki disk pressure must be remediated without deleting the named volume.
