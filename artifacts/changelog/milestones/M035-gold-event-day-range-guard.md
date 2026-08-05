# M035 — Guard Gold ranges at event-day granularity

- Date: 2026-08-05
- Status: **implemented, not verified**.
- Scope: event-day range validation, shared typed partition predicate, T3 reuse, focused tests and
  documentation.

## Decision

Gold backfill ranges must cover whole `event_day` partitions. Valid ranges are aligned starts
`1, 25, ...`, ends divisible by 24, or the frozen PaySim maximum step `743` for the final partial
day. The shared `validate_gold_cutoff_range` is called by `build_offline_features` and by T3
`plan_backfill`, so CLI and state-machine callers receive the same guard.

The partition predicate is centralized in `_partition_predicate`. Both `_write_gold_table` and
`promote_staged_gold` use it, preventing audit output from diverging from the actual Delta writer
predicate.

## Files changed

- `src/pit_fintech/features/build_offline.py`
- `src/pit_fintech/backfill/state_machine.py`
- `src/pit_fintech/cli.py`
- `tests/unit/test_gold_range_guard.py`
- `tests/integration/test_gold_offline_features.py`
- `README.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`

## Verification

- Focused guard/predicate + CLI tests: 12 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format .` — 86 files left unchanged.
- Ruff check — All checks passed.
- Ruff format check — 86 files already formatted.
- Unit — 87 passed.
- Temporal — 73 passed.
- Integration — 17 passed, one existing Ibis deprecation warning.
- No real `build-gold`, `promote-gold`, restore, or lakehouse write was run.

## Known gaps

The full Gold build/promote path remains unverified by scope. The next user-run range should be a
complete event-day range such as `[25,48]`, followed by explicit promotion.
