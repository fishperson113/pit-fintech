# VPS observability stack — sample config (no secrets)

This directory holds non-secret sample configs for the owner's self-hosted observability stack
(AGENTS.md s7: the app repo only keeps instrumentation, metric contract, dashboard JSON and
non-secret sample config; the VPS itself is the owner's deployment/ops boundary).

## Architecture / role split

The scoring API (`pit serving up`) and `pit-online-worker` are the only processes this stack observes:

```
Windows (scoring API)
  ├── /metrics  ──(Prometheus pull)──────────────▶ Prometheus  ──▶ Grafana
  └── OTLP/HTTP ──(traces + logs, PIT_OTEL_ENDPOINT)▶ Collector ──▶ Tempo/Loki ──▶ Grafana
                                                    ▲
Windows (pit-online-worker) ── OTLP/HTTP ───────────┘
```

* **Metrics**: Prometheus *pulls* `/metrics` on the API (`pit_scoring_requests_total`,
  `pit_scoring_errors_total`, `pit_scoring_latency_ms_avg`). This works with no OTel at all.
* **Traces and logs**: the API pushes OTLP/HTTP traces and structured OTLP logs when started with
  `--otel` and `PIT_OTEL_ENDPOINT`; the worker uses the same endpoint and creates `online_write`
  spans plus request-context JSON logs. The Collector forwards traces to Tempo and logs to Loki;
  Grafana correlates `trace_id`/`span_id` between them. The API `score` span and worker write span
  make the read-before-write path visible, while `pit_parity_mismatches_total` alerts on parity
  drift.

**This stack is the serving-parity verification vehicle (ADR-009).** Online/offline parity is
verified **asynchronously** by `pit parity reconcile` (never on the `/score` request path, which
would block later requests). After traffic, reconcile compares each entity's online aggregate against
the offline DuckDB engine over the served Event History, and exports `pit_parity_mismatches_total` /
`pit_parity_checked_total` as OTel metrics to the collector (best-effort). Tempo shows the
`score` → `online_write` ordering; the Grafana dashboard surfaces the scoring metrics. Because parity
is a live-system property (request ordering, concurrency, state transitions), it is **observed, not
unit-tested**.

> Parity counters reach Grafana through the OTel collector. The collector currently routes OTel
> metrics to `debug` (Prometheus self-host does not accept remote-write by default); to plot them in
> a Prometheus-backed Grafana panel you would wire the collector's Prometheus remote-write exporter
> to a host that accepts it. The reconcile report (`pit parity reconcile`) is the authoritative
> pass/fail.

> Do **not** try to push OTel metrics into a self-hosted Prometheus: Prometheus does not accept
> remote-write by default. The Collector routes the API's OTLP metrics to `debug` (logged), and
> Prometheus keeps scraping `/metrics` directly.

## Files

| File | Purpose |
|---|---|
| `otelcol-config.yaml` | Collector pipeline: traces → Tempo, metrics → debug |
| `tempo-config.yaml` | Minimal Tempo config (query frontend 3200, OTLP/gRPC ingest 4317, local storage) |
| `prometheus-scrape-job.yml` | Prometheus scrape job for the scoring API |
| `grafana-dashboard.json` | Importable Grafana dashboard for the `pit_scoring_*` metrics |

## Setup on the VPS

### 1. Collector + Tempo

Add the `otel-collector` and `tempo` services to the `docker-compose.yml` on the VPS that already
runs your Prometheus/Grafana, then copy the two config files next to it:

```bash
cd ~/prometheus-grafana
cp <repo>/deploy/vps/otelcol-config.yaml ./
cp <repo>/deploy/vps/tempo-config.yaml ./
```

```yaml
# add under services: in your existing docker-compose.yml
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    container_name: otel-collector
    command: ["--config=/etc/otelcol/config.yaml"]
    ports:
      - "4318:4318"   # OTLP/HTTP from the app (PIT_OTEL_ENDPOINT)
      - "4317:4317"   # OTLP/gRPC from the app, optional
    volumes:
      - ./otelcol-config.yaml:/etc/otelcol/config.yaml:ro
    restart: unless-stopped

  tempo:
    image: grafana/tempo:latest
    container_name: tempo
    command: ["-config.file=/etc/tempo.yaml"]
    ports:
      - "3200:3200"   # query frontend (Grafana Tempo data source)
    volumes:
      - ./tempo-config.yaml:/etc/tempo.yaml:ro
    restart: unless-stopped
```

Then `docker compose up -d`.

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
# .env or the deployment environment; config.yaml contains the local defaults
PIT_API_HOST=0.0.0.0          # so Prometheus can scrape /metrics over Tailscale
PIT_API_PORT=8000
PIT_OTEL_ENDPOINT=http://<vps-tailscale-ip>:4318   # OTLP/HTTP to the Collector
```

Start with telemetry on:

```powershell
# first time / after `setup`, install the OTel packages (+ locust for load tests)
uv pip install locust opentelemetry-sdk opentelemetry-exporter-otlp-proto-http `
    opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-logging
uv run pit serving up --otel
```

Allow inbound on port 8000 (and, only if you also let Grafana query Tempo from the browser, the
VPS ports) through the Windows firewall on the Tailscale interface.

## Verification

* `http://<vps-ip>:9090/targets` shows `pit_fintech_scoring` UP.
* `docker compose logs -f otel-collector` shows spans being forwarded.
* Grafana: a fresh `score` trace exists in Tempo Explore; the dashboard shows non-zero request
  counters after traffic (e.g. `uv run locust -f scripts/locust_parity.py --host http://127.0.0.1:8000`).

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
