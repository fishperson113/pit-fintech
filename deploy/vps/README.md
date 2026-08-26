# Prometheus + Grafana + OTel Collector + Tempo + Loki

This folder is the VPS-side observability stack for the PIT-Fintech scoring API.
It contains no credentials. Copy `.env.example` to `.env` only when SMTP or a public Grafana URL is
needed; never commit the real `.env`.

## Architecture

```text
Windows scoring API / worker
  ├── /metrics --------------------> Prometheus ------> Grafana
  ├── OTLP traces ------------------> OTel Collector -> Tempo ----> Grafana
  └── OTLP logs / Alloy-forwarded --> OTel Collector -> Loki ----> Grafana
```

The app emits OTLP logs directly with request context (`request_id`, `transaction_id`, `entity_id`,
`step`, `knowledge_step`, feature/model versions) and OTel `trace_id`/`span_id` when telemetry is
enabled. The Collector forwards these logs to Loki. Loki promotes the low-cardinality
`service.name` resource attribute to the `service_name` stream label; the remaining correlation
fields stay structured metadata.

## Services

| Service | Purpose | Persistent volume |
|---|---|---|
| Prometheus | Pulls API `/metrics`, node-exporter and cAdvisor metrics | `prometheus-data` |
| Grafana | Dashboards and Explore UI; datasources auto-provisioned | `grafana-data` |
| OTel Collector | Receives OTLP traces/logs/metrics | none; stateless |
| Tempo | Trace storage/query backend | `tempo-data` |
| Loki | Structured log storage/query backend | `loki-data` |
| node_exporter | VPS host metrics | none |
| cAdvisor | Docker/container metrics | none |

## Deploy/update on the VPS

```bash
cd ~/prometheus-grafana
cp .env.example .env                 # optional; defaults are safe for smoke use
sudo docker compose config           # validate interpolation and YAML before starting
sudo docker compose up -d
sudo docker compose ps
```

After changing `prometheus.yml`, reload Prometheus:

```bash
sudo docker compose exec prometheus kill -HUP 1
```

After changing Collector, Tempo, Loki or Compose config:

```bash
sudo docker compose up -d --force-recreate otel-collector tempo loki grafana prometheus
sudo docker compose logs --tail=100 otel-collector tempo loki
```

Do not use `docker compose down -v` unless intentionally deleting monitoring history.

## Endpoints

- Grafana: `http://<vps>:3000`
- Prometheus: `http://<vps>:9090`
- Tempo query API: internal Compose endpoint `http://tempo:3200`
- Loki query API: internal Compose endpoint `http://loki:3100`
- OTel OTLP/gRPC ingest: `<vps>:4317`
- OTel OTLP/HTTP ingest: `<vps>:4318`

Only expose ports 4317/4318 to the Windows machine over the intended private network (for this
project, Tailscale/firewall rules). Loki stays internal to the Compose network; do not publish 3100
publicly unless a separate authenticated gateway is in front of it.

## Grafana datasources

`grafana/provisioning/datasources/datasources.yml` automatically provisions:

- Prometheus as the default metrics datasource.
- Tempo as the trace datasource.
- Loki as the log datasource.
- Tempo → Loki trace-to-logs and Loki `trace_id` → Tempo derived-field correlation.

The provisioned `PIT Fintech Observability` dashboard is organized for an operator-first read:

- API target status plus total requests, successful responses, error responses, success rate and
  error rate (counters are since the current API process started).
- p50, p95, p99 and average scoring latency as large stat panels, followed by rolling percentile
  trends.
- request/s, successful response/s and error/s traffic, plus rolling error rate.
- detailed Loki lifecycle panels below the metrics overview for drill-down.

After copying an updated dashboard file to the VPS, recreate only Grafana so file provisioning
reloads the dashboard with the same UID:

```bash
sudo docker compose up -d --force-recreate grafana
sudo docker compose logs --tail=50 grafana
```

This does not delete the `grafana-data`, Prometheus, Tempo or Loki named volumes.

Useful Loki queries after log ingestion:

```logql
{service_name=~".+"}
{service_name=~".+"} | entity_id="C1470998563"
{service_name=~".+"} | outcome="rejected_older"
{service_name=~".+"} | trace_id != ""
```

The application currently emits plain-text log bodies through OTLP while correlation fields such as
`trace_id`, `span_id`, `entity_id`, and `service_name` arrive as structured metadata. Do not append
`| json` unless the selected source is actually JSON text; otherwise Loki will show `JSONParserErr`.

## Prometheus scrape target

`prometheus.yml` scrapes:

- Prometheus itself.
- `node_exporter:9100`.
- `cadvisor:8080`.
- The Windows scoring API at `100.100.18.71:8000`.

Replace the Windows Tailscale address if it changes. Confirm it at:

```text
http://<vps>:9090/targets
```

The Compose file mounts the repository's `prometheus.yml` directly, so no `/etc/prometheus` host copy
is required. The OTel Collector's API metrics are intentionally routed to its debug exporter. Prometheus pulls
`/metrics` directly; do not configure a Prometheus remote-write exporter unless the metrics topology
is deliberately changed.

## Windows scoring API settings

```env
PIT_API_HOST=0.0.0.0
PIT_API_PORT=8000
PIT_OTEL_ENDPOINT=http://<vps-tailscale-ip>:4318
```

Start the API (the public `serve` runner enables OTel by default):

```powershell
.\make.ps1 serve
```

This exports traces, metrics and structured OTLP logs when the PIT serving process is started with
OTel enabled. The API and `pit-online-worker` both send OTLP/HTTP to the Collector; the worker keeps
the request `traceparent`, so Loki log rows can be correlated with the `score` -> `online_write`
Tempo trace. No Windows-side Alloy or local log shipper is required for the current application path.

## Verification checklist

```bash
sudo docker compose config
sudo docker compose ps
curl -fsS http://localhost:9090/-/ready
curl -fsS http://localhost:3100/ready       # run on VPS; Loki is not published by Compose
curl -fsS http://localhost:3200/ready       # run on VPS; Tempo image/config dependent
curl -fsS http://localhost:13133/           # only if a Collector health extension is added
```

Then verify:

1. Prometheus target `pit_fintech_scoring` is `UP`.
2. Grafana has Prometheus, Tempo and Loki datasources without manual URL entry.
3. A fresh `score` trace appears in Tempo Explore.
4. Once an OTLP log/Alloy path is active, the matching `trace_id` opens the Tempo trace from Loki.
5. `pit parity reconcile` remains the authoritative parity pass/fail; parity counters are not yet
   Prometheus-backed by this stack.

## Known operational boundaries

- Loki is a single-node filesystem-backed deployment with seven-day retention; size/retention should
  be revisited for long-running production traffic.
- Tempo and Loki use named Docker volumes, so their local history survives container recreation; `docker compose down -v` still deletes it.
- cAdvisor can exit on hosts where `/dev/kmsg` is unavailable; it is not required for API traces/logs.
- The Collector logs pipeline is configured, but it is inactive until an OTLP log source or Alloy
  forwarding path is connected.
