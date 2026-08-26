# M094 — Operator-focused VPS Grafana serving dashboard

- **Datetime:** 2026-08-25
- **Status:** implemented; JSON/Compose and live PromQL verification passed; owner VPS deployment and visual verification pending.
- **Scope:** make the provisioned PIT Fintech dashboard immediately readable for serving operations without removing the existing Loki lifecycle evidence.

## Acceptance and design

The old top section exposed only three time-series panels: request rate, error ratio, and latency. Low request volume made rate panels mostly flat, and the dashboard did not answer the first operational questions directly.

Dashboard v11 now starts with four explicit sections:

1. **Serving overview — counters since API restart**
   - API target UP/DOWN.
   - Total scoring requests.
   - Successful responses.
   - Error responses.
   - Success rate.
   - Error rate.
2. **Latency — successful scoring responses**
   - p50, p95, p99 and average as large stat panels calculated from cumulative histogram counters since API restart.
   - Rolling p50/p95/p99 history using Grafana's `$__rate_interval`.
3. **Traffic and errors**
   - Request/s, successful response/s and error/s on one chart.
   - Rolling error-rate percentage on a separate chart.
4. **Logs and lifecycle evidence**
   - Existing Loki panels retained below the operator metrics for detailed drill-down.

The dashboard refreshes every 15 seconds. Descriptions explicitly state that in-process counters reset on API restart and that FastAPI validation 422 responses do not reach the scoring handler counters.

## Files changed

- `deploy/vps/grafana/dashboards/pit-fintech-observability.json`
  - dashboard version 10 -> 11;
  - operator stat/latency/traffic panels added;
  - lifecycle panels shifted below the metrics overview;
  - explicit Prometheus datasource UID retained;
  - 15-second refresh added.
- `deploy/vps/README.md`
  - new dashboard layout documented;
  - Grafana-only recreate commands added;
  - stale `serve-otel` invocation replaced by the current `serve` runner.
- `artifacts/changelog/PROJECT_STATUS.md`, `artifacts/changelog/CHANGELOG.md`, and this milestone log updated together.

## Verification

### Static dashboard and Compose

- Dashboard JSON parsed successfully.
- Dashboard UID remains `pit-fintech-observability`.
- Dashboard version is `11`.
- 27 top-level panels have 27 unique IDs.
- Required panel-title contract passed for API status, request/response/error totals, success/error rates, p50/p95/p99/average latency, latency history, traffic, and rolling error rate.
- `docker compose -f deploy/vps/docker-compose.yml config --quiet` passed.

### Live Prometheus query validation

Every new PromQL expression parsed successfully against `http://100.116.36.6:9090` before handoff. Observed values at verification time:

- API target: `1` (UP).
- Total requests: `4`.
- Successful responses: `4`.
- Error responses: `0`.
- Success rate: `100%`.
- Error rate: `0%`.
- p50 latency: `4 ms`.
- p95 latency: `45 ms`.
- p99 latency: `49 ms`.
- Average latency: `9.54025 ms`.

The rolling request/error-rate expressions also parsed successfully; their current value was zero because there was no traffic in the sampled rate interval.

## Deployment boundary and owner commands

No VPS container was started, recreated, or modified locally. After copying the updated `deploy/vps` folder to the VPS, the owner runs:

```bash
cd ~/prometheus-grafana
sudo docker compose config
sudo docker compose up -d --force-recreate grafana
sudo docker compose logs --tail=50 grafana
```

Do not run `docker compose down -v`; the named volumes preserve dashboard/backend history.

## Known gaps

- Live Grafana rendering is owner-pending. JSON validity and PromQL results do not prove the installed Grafana version's final visual layout.
- Histogram quantiles are bucket estimates, not raw-request exact percentiles.
- The current API metrics are process-local and reset whenever the API restarts.
- Validation errors rejected by FastAPI before `/score` are intentionally absent from these counters.
