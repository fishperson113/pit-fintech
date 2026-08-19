# M074 — ADR-011 cold-start FeatureSpec v3 + Track B backfill strategy (plan)

- 2026-08-19 — **planned** (design + ADR + backfill strategy; no `src/`/`tests/` change yet).

## Scope / gate

Turn the M073 findings into an actionable, governance-complete plan for Track B: the FeatureSpec
**v3** change to the Gold schema (cold-start features) and the backfill strategy that migration
requires. This milestone is documents only — the code lands in M075–M079, each owner-gated.

- ADR: `docs/adr/011-cold-start-featurespec-v3.md` (status **proposed**).
- Plan + backfill runbook: `docs/reports/sprint-3-track-b-cold-start-v3-plan.md`.
- Gate for this milestone: review + `changelog-check`. No compute gate (nothing computed).

## Decisions + rationale

Two owner decisions locked the design (asked before writing the ADR, because both reshape it):

1. **Cold-start feature set = fan-in + recency.** Add `pit_distinct_senders_24h`,
   `pit_distinct_senders_168h` (COUNT DISTINCT `origin_entity_id` over prior events — a fan-in signal
   structurally distinct from `pit_prior_count_*`) and `pit_steps_since_last_event` (recency gap,
   sentinel `999` when no event in the 168h lookback). Chosen over an origin-entity block (would
   reopen ADR-002 entity scope, ~2× the online/parity surface → deferred to a possible v4) and over
   recency-only (leaves the most promising structural signal on the table).

2. **Fold Track A into v3 (trim + add).** Drop the five non-earning v2 fields — `event_step` (overfit
   absolute-time coordinate, nb09), `pit_prior_count_168h` (redundant), and the three
   `recipient_has_history_*` flags (`gain ≈ 0`, binarisation of the counts) — from the *stored*
   contract, not just the model feed. One backfill instead of a trim now and an add later.

v3 = 10 fields (2 request + 8 history). Entity, scope, source, temporal semantics and the forbidden
balance/label set are all unchanged from v2. Rationale in full: ADR-011.

## Feasibility verified before writing the ADR

- **Offline:** `silver.paysim_transactions` already carries `origin_entity_id` / `origin_entity_kind`
  (`data/paysim_lakehouse.py:91-92, 209-213`) → `distinct_senders` is computable offline; just add
  `origin_entity_id` to `PAYSIM_PRE_DECISION_SOURCE_COLUMNS`.
- **Online (parity impact):** the winlog `LoggedEvent` (`serving/online_state.py`) stores only
  `(step, knowledge_step, amount)` — **no sender identity**. Fan-in requires `LoggedEvent` to carry
  `origin_entity_id`, a winlog serialization bump, and a per-event `origin_entity_id` on
  `gold.post_event_state_updates` so warm-start can seed it (mirrors the per-event `amount` added in
  M057). `pit_steps_since_last_event` is derivable from winlog steps already.
- **Backfill:** a schema change forces `mode=FULL` (documented in `build_offline._write_gold_table`);
  the v3 `feature_definition_version` yields a fresh idempotency key, so v3 does not touch/reuse the
  v2 Gold — v2 stays intact for rollback.

## Files touched

- `docs/adr/011-cold-start-featurespec-v3.md` (new, proposed).
- `docs/reports/sprint-3-track-b-cold-start-v3-plan.md` (new).
- `artifacts/changelog/{PROJECT_STATUS.md,CHANGELOG.md}` + this log.

No `src/`, `tests/`, notebook, fixture, Gold or Silver change in this milestone.

## Commands + results

None run (design milestone; the user runs all commands). The M075–M079 gates are enumerated in the
plan §4 and the backfill runbook in §5.

## Deviations / known gaps / next steps

- ADR-011 is **proposed**, not accepted — it becomes accepted when M076 lands the Gold schema v3 and
  the fixture goes green (plan §4).
- v2 champion metrics (E1 0.258342 / E4 0.102766; nb tuned 0.376) must **not** be restated for v3; a
  new champion is trained and bound to the v3 checksum in M079.
- Next concrete step: **M075** — contract v3 in `paysim_specs.py` + the pure-Python oracle + both
  DuckDB engines (pre/post), landed as one coordinated change set (import-time guards red-bar the
  suite until every consumer moves together, by design).
