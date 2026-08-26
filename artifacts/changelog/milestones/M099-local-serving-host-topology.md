# M099 — Local serving-host topology discovery and deck correction

- Timestamp: 2026-08-25 11:34:44 +0700
- Status: implemented and browser-verified
- Safety boundary: read-only discovery only. No file, process, container, volume, port, cache, or data was deleted, stopped, restarted, or modified during host inspection.

## Scope

The owner clarified that serving runs on the local Windows machine; only monitoring and the MLflow registry run on the VPS. Read the live host/process/container state and corrected the 12-slide report so the VPS Node Exporter screenshot is not attributed to the serving host.

## Live local host evidence

Read-only system inspection returned:

- machine: Acer Aspire A715-41G, x64;
- OS: Microsoft Windows 11 Pro, display version 25H2, build 26200;
- CPU: AMD Ryzen 7 3750H with Radeon Vega Mobile Gfx, 4 physical cores / 8 logical processors, reported max 2.30 GHz;
- physical RAM: 29.94 GiB;
- current host snapshot at inspection: 9.81 GiB available, 67.2% used, 17.0 GiB swap configured. This was not sampled during the load window.

Live listener/process inspection returned:

- port 8000: host-native `python.exe`, PID 9440, command `pit.exe serving up --otel`, created 2026-08-25 09:00:57, current RSS 80.9 MiB;
- serving implementation calls `uvicorn.run(app, host=..., port=...)` without `workers`, matching the documented single-process MVP;
- port 6379: Docker Desktop publication on 127.0.0.1;
- port 8089: host-native Locust PID 24816, targeting `http://127.0.0.1:8000`, so the current load generator and API share the same physical host;
- no process or listener was terminated.

Read-only Docker Compose inspection returned both local services running:

- `pit-online-worker`: current snapshot 0.09% CPU, 150.7 MiB / 14.61 GiB, 20 PIDs;
- `redis`: healthy; current snapshot 4.14% CPU, 7.039 GiB / 14.61 GiB, 6 PIDs;
- Docker Desktop's reported memory ceiling is 14.61 GiB, about 48.8% of physical host RAM.

These process/container values are post-load snapshots and are not presented as load-window peaks.

## VPS boundary

`config.yaml` verifies the remote boundary already described by the owner:

- MLflow tracking/registry: `http://100.116.36.6:5000`;
- OTLP Collector: `http://100.116.36.6:4318`;
- Redis remains local at `redis://localhost:6379/0`;
- FastAPI binds local port 8000 and is reachable to remote Prometheus through the configured network path.

No credentials or environment secrets were read or printed.

## Deck correction

Updated `docs/reports/pit-fintech-final-report-10min-slides.html`:

- slide 11 now states that serving is local and the CPU 5.9% / RAM 43.6% screenshot belongs to the VPS monitoring node;
- slide 12 now records the actual Acer/Windows/Ryzen/RAM topology, single FastAPI process, local Docker Redis/PIT worker, Docker memory ceiling, current RSS/container-memory snapshots, and same-host Locust placement;
- the slide keeps a strict evidence boundary: capacity still requires a rerun that samples local CPU/RAM/process RSS, Redis backlog, actual RPS/wall time, and repeated 5–15 minute soak lanes during the exact test window.

## Verification

- Browser visual inspection of revised slide 12 found the hardware/topology table and caveat fully visible and readable.
- Programmatic browser inspection found 12 slides and no layout overflow.
- Browser console reported zero messages and zero JavaScript errors.
- `git diff --check` passed before changelog synchronization and is rerun afterward.
