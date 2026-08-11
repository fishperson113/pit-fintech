# M065 — Checkpointed Event History to Bronze ingestion

- **Datetime:** 2026-08-11
- **Status:** implemented and locally verified
- **Scope:** asynchronous offline landing of accepted serving events

## Decision

The realtime `pit-online-worker` remains responsible for Redis online state and appending the
offline-visible Event History. A separate batch/cron job consumes new Event History lines; it does not
spawn a process per event and does not run on the synchronous request path.

The live Event History schema does not contain all raw PaySim Bronze columns (`nameOrig`, balances,
confirmed `isFraud`, etc.), so it lands in a separate append-only table:

```text
data/lakehouse/served_events/
```

This is a Bronze landing table, not a replacement for the existing `bronze.paysim_transactions` raw
application table. Silver/Gold enrichment requires the appropriate source/label mapping later.

## Implementation

- Added `src/pit_fintech/ingest/event_history.py`.
- Added `pit ingest event-history`.
- Added `make ingest-event-history` and the short aliases `make ingest` plus Windows
  `make.ps1 ingest-event-history`/`make.ps1 ingest`.
- Checkpoint path defaults to:

```text
artifacts/ingest/event_history.json
```

- Input defaults to:

```text
artifacts/event_history/served_events.jsonl
```

- Idempotency uses a stable event identity hash and existing Delta event IDs; reruns after a write/
  checkpoint boundary do not duplicate rows.
- Checkpoint advances only after the Delta append succeeds and is written atomically.

## Verification

- Event History ingestion unit tests: **2 passed**.
- CLI help exposes `event-history`.
- PowerShell parser: **PASS**.
- Ruff/format/compile: **PASS**.

## Operational flow

```text
pit-online-worker
  -> artifacts/event_history/served_events.jsonl

cron/scheduled command
  -> pit ingest event-history
  -> data/lakehouse/served_events (Bronze landing Delta)

follow-up offline jobs
  -> Silver normalization/enrichment
  -> Gold build/promote
  -> training/MLflow
```
