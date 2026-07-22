# M005 — Sprint scope and runtime-boundary refinement

- Date/time: 2026-07-22 11:26:35 +07:00
- Status: verified planning/documentation milestone

## Scope and acceptance

Fold the architecture review decisions into the authoritative six-week plan without claiming
that the planned Sprint 2/3 runtime components are implemented. Acceptance requires consistent
boundaries across `AGENTS.md`, the implementation guides, proposal/comparison documents and all
three changelog artifacts.

## Decisions

- Replay uses one logical Transaction Producer/Replay Driver. A Python iterator/generator or
  in-memory queue holds deterministically ordered transactions; the driver waits for scoring and
  post-score commits for `t` before emitting `t+1`.
- No external event service is part of the MVP: Kafka/Redpanda, RabbitMQ, Redis Streams and
  Debezium are excluded. Multiple entities do not require multiple producers.
- Prediction cutoff controls routing: FastAPI reads Redis history strictly before `t`, produces
  the score, then updates Redis and appends `t` to Event History.
- Medallion Bronze/Silver/Gold remains valuable for offline data quality, lineage and
  reproducibility. It runs through Python CLI/Makefile, not through JupyterLab or the synchronous
  serving request path.
- Feast remains a thin feature contract/retrieval/materialization layer. DuckDB computes, Delta
  stores offline history/features, Redis stores online state, and the independent PIT oracle
  remains the correctness authority. Removing Feast requires an ADR and equivalent custom
  FeatureSpec/FeatureProvider/version/materialization/parity contracts.
- Training remains local CPU through a Python CLI with the model family selected only after
  PaySim EDA. LightGBM is a candidate, not a pre-commitment; Ray Train and Ray Tune are excluded.
- FastAPI/Uvicorn is the reference serving runtime. Ray Serve is excluded until a benchmark
  proves a need for replicas, autoscaling, batching or distributed serving.
- Superset is excluded because business BI is not an outcome of this project.
- Optional Sprint 3 observability is externalized to the user's VPS/ops boundary. The target
  metrics path is application OTLP over TLS -> OTel Collector -> Prometheus -> Grafana. Grafana
  is the frontend, not the telemetry backend; core Compose remains Redis + MLflow + FastAPI.

## Files changed

- `AGENTS.md`
- `docs/feature-store/sprint-2-implementation-guide.md`
- `docs/feature-store/sprint-3-implementation-guide.md`
- `docs/feature-store/point-in-time-feature-store-proposal.md`
- `docs/feature-store/reference-architecture-comparison.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

The pitch deck, high-level Mermaid handoff and native Draw.io source were intentionally not
modified in this milestone.

## Verification evidence

```text
Scope-term consistency scan: pass; all required decisions present and stale scope phrases absent
Sprint 2 Mermaid sequence structural check: pass; 11 participants, 16 messages, 0 broken refs
Proposal Mermaid flow structural check: pass after separating Replay/Parity IDs
Markdown fence balance: pass across 8 changed planning/audit files
uv run pytest -q tests/unit/test_milestone_changelog_hook.py: 4 passed in 0.96s
git diff --check: pass; existing LF-to-CRLF working-copy warnings only
```

## Deviations, gaps and next step

- The external VPS observability stack is a Sprint 3 should-have plan, not deployed evidence.
- The main high-level Mermaid still compresses observability and omits Prometheus; it was left
  unchanged because this milestone updates sprint planning rather than the presentation diagram.
- PaySim EDA, model selection, Feast integration, replay, serving and observability implementation
  remain pending their sprint gates.
- Next implementation priority remains PaySim EDA and the Sprint 1 dataset/entity/model ADR.
