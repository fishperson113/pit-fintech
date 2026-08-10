# VPS observability stack — sample config (no secrets)

This directory holds non-secret sample configs for the owner's self-hosted observability stack
(AGENTS.md s7: the app repo only keeps instrumentation, metric contract, dashboard JSON and
non-secret sample config; the VPS itself is the owner's deployment/ops boundary).

## Architecture / role split

The scoring API (`pit serving up`) is the only thing this stack observes:

```
Windows (scoring API)
  ├── /metrics  ──(Prometheus pull)──────────────▶ Prometheus  ──▶ Grafana
  └── OTLP/HTTP ──(traces, PIT_OTEL_ENDPOINT)────▶ Collector    ──▶ Tempo  ──▶ Grafana
```

* **Metrics**: Prometheus *pulls* `/metrics` on the API (`pit_scoring_requests_total`,
  `pit_scoring_errors_total`, `pit_scoring_latency_ms_avg`). This works with no OTel at all.
* **Traces**: the API *pushes* OTLP/HTTP traces to the OTel Collector when started with
  `--otel` and `PIT_OTEL_ENDPOINT`. The Collector forwards them to Tempo; Grafana reads them via
  the Tempo data source. This makes the read-before-write invariant visible as a `score` span
  containing its child `online_write` span, and `pit_parity_mismatches_total` alerts on parity
  drift.

> Do **not** try to push OTel metrics into a self-hosted Prometheus: Prometheus does not accept
> remote-write by default. The Collector routes the API's OTLP metrics to `debug` (logged), and
> Prometheus keeps scraping `/metrics` directly.

## Files

| File | Purpose |
|---|---|
| `docker-compose.otel.yml` | OTel Collector (`otel-collector`) + Tempo services; run standalone or merge into your existing compose |
| `otelcol-config.yaml` | Collector pipeline: traces → Tempo, metrics → debug |
| `tempo-config.yaml` | Minimal Tempo config (query frontend 3200, OTLP/gRPC ingest 4317, local storage) |
| `prometheus-scrape-job.yml` | Prometheus scrape job for the scoring API |
| `grafana-dashboard.json` | Importable Grafana dashboard for the `pit_scoring_*` metrics |

## Setup on the VPS

### 1. Collector + Tempo

Run standalone (recommended — keeps your existing Prometheus/Grafana compose untouched):

```bash
cd ~/prometheus-grafana
cp <repo>/deploy/vps/docker-compose.otel.yml ./
cp <repo>/deploy/vps/otelcol-config.yaml ./
cp <repo>/deploy/vps/tempo-config.yaml ./
docker compose -f docker-compose.otel.yml up -d
```

Or merge the `otel-collector` and `tempo` services into your existing `docker-compose.yml` and
`docker compose up -d`.

### 2. Prometheus scrape job

Copy the `pit_fintech_scoring` job from `prometheus-scrape-job.yml` into the `scrape_configs:` list
of the Prometheus config the running container actually mounts (if your compose mounts
`- /etc/prometheus:/etc/prometheus`, that is `/etc/prometheus/prometheus.yml` on the host, not the
file next to your compose). Replace `<windows-tailscale-ip>` with the Windows machine's Tailscale
IPv4 (`tailscale ip -4`). Reload:

```bash
docker compose exec prometheus kill -HUP 1
```

### 3. Grafana data sources + dashboard

1. Prometheus: `http://prometheus:9090` (same compose network) or `http://<vps-ip>:9090`.
2. Tempo: `http://tempo:3200`.
3. Import `grafana-dashboard.json` (Dashboards → New → Import) and pick the Prometheus data source
   when prompted.
4. To inspect traces: Tempo data source → Explore → select a `score` trace; the child
   `online_write` span shows the write happening after the read.

## On the Windows machine (scoring API)

```env
# .env
PIT_API_HOST=0.0.0.0          # so Prometheus can scrape /metrics over Tailscale
PIT_API_PORT=8000
PIT_OTEL_ENDPOINT=http://<vps-tailscale-ip>:4318   # OTLP/HTTP to the Collector
```

Start with telemetry on:

```powershell
.\make.ps1 tools       # install the OTel packages + locust (first time / after `setup`)
.\make.ps1 serve-otel  # uv run pit serving up --otel
```

Allow inbound on port 8000 (and, only if you also let Grafana query Tempo from the browser, the
VPS ports) through the Windows firewall on the Tailscale interface.

## Verification

* `http://<vps-ip>:9090/targets` shows `pit_fintech_scoring` UP.
* `docker compose -f docker-compose.otel.yml logs -f otel-collector` shows spans being forwarded.
* Grafana: a fresh `score` trace exists in Tempo Explore; the dashboard shows non-zero request
  counters after traffic (e.g. `.\make.ps1 locust`).

## Troubleshooting — crash-looping containers

If a service keeps restarting, read its log first:

```bash
sudo docker logs <service> --tail 40
```

Two known gotchas:

* **Prometheus (`Restarting (2)`):** your compose mounts a host directory
  (`- /etc/prometheus:/etc/prometheus`), so Prometheus reads `/etc/prometheus/prometheus.yml` on
  the host — **not** the `prometheus.yml` next to the compose file. If that host file is missing
  or broken, Prometheus exits. Fix: mount the repo file instead —
  `- ./prometheus.yml:/etc/prometheus/prometheus.yml:ro` — then `sudo docker compose up -d`.
* **Tempo (`Restarting (1)`):** Go's YAML parser rejects underscores in numbers. If you edit
  `tempo-config.yaml`, use plain integers (`1000000`, not `1_000_000`) or rely on the image
  defaults. The checked-in file already does this.

Unrelated and harmless: `cadvisor` may exit 255 on newer kernels (`/dev/kmsg` permissions); it is
not part of the PIT observability path — comment it out of the compose if it disturbs you.
