# M049 — Wire the scoring API `/metrics` for a remote Prometheus scrape

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner runs the env + VPS steps)
- **Sprint / task:** Sprint 2 T7 observability (Prometheus/Grafana integration)

## Scope

The owner runs a self-hosted Prometheus + Grafana stack (plus node_exporter/cadvisor) on a VPS at
`100.116.36.6` (Tailscale). They want the serving API's metrics visible there. The stack has **no
OTel Collector**, so the OTLP push path (`PIT_OTEL_ENDPOINT`, M046/M047) does not apply to it:
Prometheus pulls HTTP endpoints. The serving API already exposes `/metrics` in Prometheus text
format (hand-rolled `_MetricsState` counters: `pit_scoring_requests_total`,
`pit_scoring_errors_total`, `pit_scoring_latency_ms_avg`), independent of OTel. `prometheus-client`
is already a `serving` group dependency. So the only code change needed is to let `.env` control
the bind host/port.

## What changed

- `src/pit_fintech/cli.py` — `pit serving up` defaults for `--host` and `--port` now come from
  `get_settings().api_host` / `.api_port` (i.e. `PIT_API_HOST` / `PIT_API_PORT` in `.env`), matching
  the env-driven pattern already used for `--otel-endpoint` (M047). Explicit `--host`/`--port`
  flags still override. Defaults are unchanged (`127.0.0.1:8000`) unless `.env` sets them.
- `.env.example` — documents that `PIT_API_HOST=0.0.0.0` exposes `/metrics` for a remote Prometheus
  scrape over Tailscale, with the firewall note.
- `README.md` — new "Connecting the scoring API to Prometheus / Grafana" section: `/metrics` pull
  model, the `.env` + firewall steps, the VPS `prometheus.yml` scrape job, the
  `/etc/prometheus` mount caveat, the Grafana data-source step, and the clarification that
  `PIT_OTEL_ENDPOINT` targets an OTel Collector (OTLP) while Prometheus scrapes `/metrics`.

No dependency change; `prometheus-client` was already in the `serving` group. The `/metrics` route
is unchanged (still the hand-rolled counters) — converting it to `prometheus_client` histograms is
an optional follow-up, not required for the scrape.

## Commands + results

- Agent static analysis only (`get_settings` was already imported in `cli.py`; default args follow
  the M047 pattern). No test asserts the old hardcoded `"127.0.0.1"`/`8000` defaults, so nothing
  should break.
- **Owner gates:**

  ```powershell
  .\make.ps1 lint
  # in .env:  PIT_API_HOST=0.0.0.0   PIT_API_PORT=8000
  .\make.ps1 serve
  # then, on the VPS, add the pit_fintech_scoring scrape job to prometheus.yml and reload.
  ```

## Known gaps / next steps

- The `/metrics` endpoint remains the minimal hand-rolled text format. If the owner wants latency
  histograms / per-status labels in Grafana, convert `_MetricsState` to `prometheus_client`
  (Histogram/Counter) — a small, contained follow-up that would use the already-present dependency.
- Firewall/Tailscale reachability, the VPS `prometheus.yml` edit, and the Grafana data source are
  all owner-side (not code) steps, listed in README.
