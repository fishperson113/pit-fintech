# Local serving burst resource report — 2026-08-25

## Result

The local Acer serving stack completed a burst window with zero server-side scoring errors. Prometheus observed an exact counter delta of **1,080 completed scoring requests**, while the one-second local sampler showed the shared host at **100% CPU median and peak** during the detected scoring window.

This is valid evidence for a functional burst and saturation finding. It is not yet a maximum-capacity or sustained-throughput claim because Locust shared the serving host, the run was one-shot, and no repeated or soak lane was executed.

## Topology under test

```text
Acer Aspire A715-41G — Windows 11 Pro 25H2
Ryzen 7 3750H — 4 physical / 8 logical CPUs — 29.94 GiB RAM

Local host
├─ FastAPI/Uvicorn — one native process — port 8000
├─ Locust — native process — localhost target
└─ Docker Desktop — 14.61 GiB memory ceiling
   ├─ Redis
   └─ PIT online worker

VPS
├─ Prometheus/Grafana
├─ Loki/Tempo/OTel Collector
└─ MLflow registry
```

## Evidence sources

- Raw one-second CSV: `artifacts/reports/load-resource-20260825-120757.csv`.
- Raw CSV SHA-256: `2f4afd745d20dc9ad9e203dd65660934e7038e8c4cf4f51a01b2e1402b213af2`.
- Machine-readable summary: `artifacts/reports/load-resource-20260825-120757-summary.json`.
- Prometheus exact counter/histogram deltas: `2026-08-25T12:12:30+07:00` through `12:14:05+07:00`.

The sampler contains 412 data rows at one-second resolution from `12:08:08.282` through `12:14:59.716` local time.

## Detected windows

The scoring window is defined reproducibly as the first through last sample where FastAPI process CPU was at least 5%:

- Baseline: `12:11:44.288`–`12:12:43.292` (60 seconds).
- Scoring: `12:12:44.279`–`12:13:55.717` (**71.437 seconds**).
- Asynchronous worker drain completed at `12:14:07.720` (**83.437 seconds** from scoring onset).

## Request and latency evidence

Prometheus cumulative counter and histogram differences over the run window:

| Metric | Observed |
|---|---:|
| Completed scoring requests | 1,080 |
| Scoring errors | 0 |
| Success rate | 100% |
| Average latency | 11.50 ms |
| p50 latency | 9.25 ms |
| p95 latency | 32.42 ms |
| p99 latency | 49.30 ms |
| Approximate requests/s over detected scoring window | 15.12 |

The planned workload was 100 users × 10 requests/user = 1,000 requests, but Locust was closed before its CSV/API result could be retrieved. The authoritative server-side counter increased by 1,080, so this report does not silently rewrite the observed value to 1,000 or infer an exact user count.

## Local resource evidence

| Resource | 60-second baseline median | Scoring median | Scoring peak |
|---|---:|---:|---:|
| Host CPU | 20.65% | 100.00% | 100.00% |
| Host RAM used | 19.54 GiB | 21.01 GiB | 22.26 GiB / 74.3% |
| FastAPI CPU | 0.00% | 193.35% | 262.50% |
| FastAPI RSS | 84.70 MiB | 303.98 MiB | 312.70 MiB |
| Locust CPU | 0.00% | 6.20% | 18.20% |
| Locust RSS | 28.88 MiB | 67.14 MiB | 67.31 MiB |
| Redis CPU | 0.60% | 125.98% | 148.45% |
| Redis memory | 7,207.94 MiB | 7,229.95 MiB | 7,235.58 MiB |
| PIT worker CPU | 0.05% | 44.95% | 137.71% |
| PIT worker memory | 150.70 MiB | 151.80 MiB | 154.80 MiB |

After FastAPI activity ended, the PIT worker continued draining queued writes. Its total active-window peak was **148.06% CPU** and **156.30 MiB** memory.

On Windows/psutil and Docker, process/container CPU percentages can exceed 100%; approximately 100% represents one fully used logical CPU. Therefore FastAPI's 262.5% peak means roughly 2.63 logical CPUs at that sample, not 262.5% of the entire eight-logical-CPU host.

## Deltas from baseline

- Host memory increased by up to **2.715 GiB** during scoring.
- FastAPI RSS increased by **228.0 MiB**.
- Redis memory increased by **27.648 MiB**.
- PIT worker memory increased by **5.6 MiB** through drain.

## Interpretation

1. The request path remained correct at the scoring-counter level: 1,080 completed and zero scoring errors.
2. Latency remained low at p95 32.42 ms and p99 49.30 ms for this run.
3. The shared host reached CPU saturation for much of the scoring window; throughput was CPU-bound under this topology.
4. FastAPI and Redis were the largest CPU consumers during scoring, while the asynchronous worker continued meaningful work for about 12 seconds after FastAPI activity ended.
5. Redis's approximately 7.06 GiB resident dataset dominates container memory, but the burst itself added only about 27.65 MiB.
6. Locust shared the host, so this is a conservative co-located generator result rather than an isolated server benchmark.

## Remaining capacity gate

Before claiming a maximum supported user/RPS level:

- preserve Locust CSV and exact user/spawn settings on the next run;
- run the generator on another host or quantify its interference;
- repeat the same lane at least three times;
- execute a 5–15 minute sustained/soak lane;
- record queue pending/backlog and recovery time;
- define the acceptable p95/p99 and error-rate thresholds before testing.
