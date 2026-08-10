# M050 — VPS observability sample configs (OTel Collector + Tempo + dashboard)

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; VPS is the owner's manual setup boundary)
- **Sprint / task:** Sprint 2/3 observability — hybrid Prometheus (pull `/metrics`) + OTel
  Collector→Tempo (push traces). Owner chose: they will configure the VPS by hand; the repo keeps
  non-secret sample configs.

## Scope

The owner runs a self-hosted Prometheus + Grafana stack (plus node_exporter/cadvisor) on a VPS at
`100.116.36.6` (Tailscale). After M049 wired `/metrics` for Prometheus, this milestone adds the
trace side: an OTel Collector receiving OTLP/HTTP from the scoring API and forwarding traces to
Tempo, plus an importable Grafana dashboard. Per AGENTS.md s7, the app repo only holds
instrumentation, metric contract, dashboard JSON and non-secret sample config; the VPS itself is a
separate deployment/ops boundary the owner configures by hand.

## Design decision — hybrid, not all-via-collector

- **Metrics** stay on the Prometheus pull path: Prometheus scrapes `/metrics` on the API directly
  (M049). Self-hosted Prometheus does not accept remote-write by default, so the Collector is
  deliberately **not** wired to push metrics into Prometheus.
- **Traces** go through the Collector: the API pushes OTLP/HTTP (`PIT_OTEL_ENDPOINT`, M046/M047)
  → Collector → Tempo → Grafana. This makes the read-before-write invariant visible (`score` span
  containing its child `online_write` span) and enables `pit_parity_mismatches_total` alerting.
- The Collector's metrics pipeline routes the API's OTLP metrics to `debug` (logged, never fails
  loudly) so enabling `--otel` does not error on the metrics export.

## What changed

- **New `deploy/vps/`** (non-secret sample configs):
  - `otelcol-config.yaml` — Collector pipelines: `traces → otlp/tempo`, `metrics → debug`.
  - `tempo-config.yaml` — minimal Tempo config (query frontend 3200, OTLP/gRPC ingest 4317, local
    storage), mounted explicitly so the image default config is not relied on.
  - `docker-compose.otel.yml` — `otel-collector` (host ports 4317/4318) + `tempo` (host port
    3200 only; the collector reaches Tempo on the compose network at `tempo:4317`). Initial draft
    published host 4317 on both services — a real port conflict — fixed to publish it only on the
    collector. Run standalone or merge into the owner's existing compose.
  - `prometheus-scrape-job.yml` — `pit_fintech_scoring` job for `prometheus.yml`.
  - `grafana-dashboard.json` — importable dashboard: QPS, error ratio, avg latency, total
    requests, templated Prometheus data source.
  - `README.md` — role split, files table, VPS setup steps, Windows `.env`, verification.
- `README.md` — "Connecting the scoring API to Prometheus / Grafana" section now points at
  `deploy/vps/README.md` for the hybrid trace setup and states the Prometheus-vs-OTLP split.
- `.env.example` — `PIT_OTEL_ENDPOINT` comment clarified (traces only; Prometheus scrapes
  `/metrics`, see `deploy/vps/`).

No change to `src/`, `tests/`, dependency groups or ADR-004 fingerprints. The `/metrics` route is
unchanged (still the hand-rolled `_MetricsState` counters); converting to `prometheus_client`
histograms remains an optional follow-up.

## Commands + results

- Agent static analysis only (config files, JSON/YAML validated by inspection; the Grafana
  dashboard JSON is hand-written against the Grafana schema, import is an owner step).
- **Owner gates:** none in this repo — the VPS setup and Grafana import are owner-side, using the
  files above. `.\make.ps1 lint` is unaffected (no Python touched).

## Known gaps / next steps

- The dashboard binds only the three current `/metrics` counters. If the owner wants latency
  histograms / per-status labels, convert `_MetricsState` to `prometheus_client` (already a
  `serving` group dependency) — a contained follow-up.
- `docker-compose.otel.yml` runs standalone; the owner may prefer merging into their existing
  compose — both are documented.
- `pit_fintech_scoring` target and Tempo data source are VPS-side; README lists the verification
  steps (`/targets` UP, collector logs, Tempo Explore).

## Refinement (same date, owner reported Tempo crash-loops)

Tempo exited 1 repeatedly on the VPS. Root cause: my initial `tempo-config.yaml` used YAML numeric
literals with underscores (`max_block_bytes: 1_000_000`, `block_size_bytes: 1_000_000`). Go's YAML
parser does not accept underscores in numbers, so each parsed as a string and failed to unmarshal
into an int at config load. Fixed by removing the `ingester`/`compactor` tunables entirely and
keeping the minimal working config (frontend 3200, OTLP/gRPC ingest 4317, local storage); the
rewritten file documents the restriction so it is not re-introduced. Prometheus crash-looping on
the owner's stack was a separate, VPS-side cause: the compose binds host `/etc/prometheus` (not the
`prometheus.yml` next to the compose file), so Prometheus was reading `/etc/prometheus/prometheus.yml`
on the host — the owner mounts `./prometheus.yml` instead.
