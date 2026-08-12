# M066–M070 — Offline observability, event identity and candidate flow

- **Datetime:** 2026-08-12
- **Status:** implemented; focused/static verification passed; owner live verification pending
- **Scope:** lifecycle evidence, durable event identity, asynchronous parity and automatic served-event
  Silver/Gold-candidate processing. Production Gold promotion remains manual/gated.

This consolidated log replaces the separate M066, M067, M068, M069 and M070 files.

## M066 — Offline lifecycle logging

Lifecycle logging observes command/function boundaries. It does not itself trigger the next stage:

```text
pit ingest event-history -> Bronze lifecycle logs
pit features build-gold -> PaySim Gold lifecycle logs
pit features promote-gold -> Gold promotion lifecycle logs
pit parity reconcile -> parity lifecycle logs
```

Implemented:

- Added `src/pit_fintech/platform/lifecycle_logging.py` with deterministic Loki-searchable
  `event key=value` lines.
- Bronze events: `offline.bronze.ingest.started/completed`.
- Gold events: `offline.gold.build.started/staged/completed` and
  `offline.gold.promote.started/refused/completed`.
- Parity events: `offline.parity.reconcile.started/completed`.
- Offline CLI commands configure OTLP export when `PIT_OTEL_ENDPOINT` or
  `OTEL_EXPORTER_OTLP_ENDPOINT` is configured.

## M067 — Durable event identity and Grafana evidence

Stable event identity is derived from:

```text
destination_entity_id + step + knowledge_step + transaction_type + amount
```

`transaction_id` and `request_id` remain observational fields and are not duplicate semantics.

Implemented:

- Added `src/pit_fintech/contracts/served_events.py`.
- Redis score events, worker logs and Event History preserve `event_id`.
- New Event History rows preserve `request_id` and `transaction_id`.
- Bronze completion logs expose bounded first/last event and transaction identities.
- Gold logs expose source version, row counts, checksums, Gold versions and future-read violations.
- Parity logs expose checked entities, event identity range, mismatches, missing online state and pass.
- Grafana dashboard separates online scoring, worker write, Bronze, PaySim Gold, served-event
  candidate and parity evidence.

## M068 — Event-driven async parity consumer

The worker publishes a signal after `apply_score_event` returns. One daemon consumer thread coalesces
event bursts and runs DuckDB parity outside `/score` and outside the ordered Redis consumer wait path:

```text
score -> Redis Stream -> worker apply -> score result
                              └──── signal -> async parity consumer -> DuckDB -> Loki/Grafana
```

The quiet period is burst coalescing, not a periodic schedule. No cron or interval trigger is introduced.

Implemented in `src/pit_fintech/serving/parity_consumer.py`:

- One consumer thread, no thread per request.
- `offline.parity.consumer.started` and `.triggered` lifecycle events.
- Existing `offline.parity.reconcile.started/completed` runs in the background.
- OTel parity metrics are recorded when telemetry is available.
- Manual `pit parity reconcile` remains available as a fallback.

Expected live evidence:

```text
offline.parity.consumer.triggered event_id=...
offline.parity.reconcile.completed checked_entities=... field_mismatches=0 passed=True
```

## M069 — OTel in API/worker images

Root cause found during live inspection: the worker was running the consumer and producing passing parity,
but its container reported:

```text
otel_enabled=True but the OpenTelemetry packages are not installed
```

Therefore worker/consumer/parity logs were visible in Docker logs but not Loki.

Implemented:

- `docker/Dockerfile` accepts `INSTALL_OTEL` (default `0`).
- `compose.yaml` enables `INSTALL_OTEL: "1"` for `api` and `pit-online-worker`.
- No serving/parity semantics or lockfile dependency group was changed.

Owner rebuild:

```powershell
docker compose up -d --build --force-recreate api pit-online-worker
```

## M070 — Automatic served-event Silver and Gold candidate path

When `pit ingest event-history` resolves an existing Bronze table, it idempotently runs:

```text
Bronze served_events
  -> Silver served_events_silver
  -> Gold candidate served_events_gold_candidate
```

This also runs when the checkpoint has no new lines; a missing Bronze table is the only skip condition.
The candidate is not promoted to production Gold, is not used as a champion source, and does not invent
fraud labels. Every candidate row carries `label_status=unlabeled`.

Implemented in `src/pit_fintech/features/served_event_pipeline.py`:

- Normalizes ordinals, destination, transaction type and amount as `DECIMAL(18,2)`.
- Quarantines invalid rows when a quarantine path is configured.
- Computes strict-PIT 1h/24h/168h history features using prior step and knowledge-time predicates.
- Excludes current and future events from pre-decision history.
- Wired into `pit ingest event-history` after Bronze resolution.
- Added Grafana dashboard panel `Offline Silver + Gold candidate` (dashboard version 7).

Paths:

```text
data/lakehouse/served_events                 Bronze
data/lakehouse/served_events_silver          Silver
data/lakehouse/served_events_gold_candidate  Gold candidate/staging
data/lakehouse/quarantine/served_events      invalid rows
```

## M071 — MVP invariant gates and Grafana evidence

Implemented:

- Added `pit backfill run --mode full|range|incremental --start ... --end ...` plus Make/PowerShell
  wrappers. The command emits `offline.backfill.started/completed` with mode, range, idempotency key,
  source Silver version and committed Gold versions.
- Implemented `materialize recover`, which snapshots the scoped Redis namespace, resets it, reruns
  materialization at a pinned Gold version/watermark and compares normalized records plus watermark.
  It emits `offline.recovery.started/completed` and fails when records or watermark differ.
- Materialization emits `offline.materialization.completed` with pinned Gold version, watermark and
  write/no-op/reject counts.
- Grafana dashboard version 9 adds `Offline backfill`, `Offline materialization` and
  `Offline Redis recovery` panels.

Verification:

```text
unit: 110 passed
Gold/Feast integration: 8 passed (one third-party Ibis deprecation warning)
T3 backfill smoke: 1 passed
ruff check/format: pass, 117 files formatted
dashboard JSON v9: valid, 10 panels
git diff --check: pass
```

Not yet verified:

- `materialize recover` has not been run live because it deliberately deletes the scoped Redis
  namespace before rebuilding it; owner must run it against the intended Redis/Gold version.
- Full/range/incremental real backfill evidence and Grafana arrival remain owner-run.
- The original synthetic T9 E2E module remains skipped; MVP closure will use the invariant-focused
  lanes above plus explicit recovery/backfill evidence rather than claiming the skipped broad T9 suite.
No production Gold promotion is wired into the automatic path. No live M070 `make ingest` run was
performed by this session; owner verification should confirm Silver/candidate paths and Loki evidence.

## Known limits and boundaries

- Current `make ingest` remains the Bronze batch boundary; downstream Silver/candidate processing is
  automatic once that command resolves Bronze.
- Async parity compares online Redis/winlog state with DuckDB over served Event History; it does not
  automatically run Bronze -> Silver -> Gold candidate.
- Serving events have no confirmed fraud labels. `prediction=1` must never become `isFraud=1` without
  an independent labeling/enrichment process.
- Gold candidate is not production Gold, champion input or automatic training data.
- Existing historical Event History rows cannot be retroactively attributed to an HTTP request.
