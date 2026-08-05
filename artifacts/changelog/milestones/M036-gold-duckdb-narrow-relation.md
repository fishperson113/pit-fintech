# M036 — Narrow and reuse the Gold DuckDB relation

- Date: 2026-08-05
- Status: **implemented, not verified**.
- Scope: speed-only optimization of the Gold DuckDB path; no PIT/business semantics changed.

## Changes

`build_offline_features` now:

1. Projects only `PAYSIM_PRE_DECISION_SOURCE_COLUMNS` plus `event_day` during the Silver Delta read.
2. Registers that narrow Arrow table once and materializes one temporary DuckDB table
   `gold_source`, reused by same-step, pre-decision, post-event and future-read queries.
3. Computes the expected pre-decision row count with SQL instead of converting the entire source
   table through `source_table.to_pylist()`.

The existing SQL feature producers, predicates, range guard, audits, schema, checksums and output
contract remain unchanged. No streaming/batch semantic change was introduced.

## Verification

- Focused Gold fixture/range tests: 12 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format .`: 1 file reformatted.
- Ruff check: All checks passed.
- Ruff format check: 86 files already formatted.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 17 passed, one existing Ibis deprecation warning.
- No real Gold build or promotion was run.

## Known limitation

Runtime speedup has not been benchmarked against a real full Silver build in this work because the
user explicitly excluded running Gold build/promote. The expected benefit is lower Arrow/DuckDB input
width, fewer Arrow bridge scans, and removal of a full Python-row conversion for the expected count.
