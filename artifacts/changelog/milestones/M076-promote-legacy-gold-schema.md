# M076 — Promote staged Gold across the v2→v3 schema boundary

Date: 2026-08-19
Status: implemented; fixture-verified; real-data promotion pending owner run

## Scope and acceptance

Fix promotion of an already committed v2 Gold table when the staged table uses the ADR-011 v3
schema. The exact reported failures were:

- `deltalake.Schema` has no `to_pyarrow()` method;
- after switching schema inspection, Delta-rs 1.6.2 still failed while dropping legacy
  `event_step`/`recipient_has_history_*` fields during an in-place schema overwrite.

Acceptance:

- same-schema partition overwrite retains untouched partitions;
- non-contiguous `IN` overwrite retains the middle partition;
- a full-range v2→v3 replacement removes legacy columns without `event_step` errors;
- a partial-range schema migration is refused rather than deleting untouched Gold partitions.

## Root cause

The previous schema comparison used a tuple on the left and `schema.names` (a list) on the right,
so every existing table was classified as a schema change. In addition, Delta-rs 1.6.2 validates
removed fields from the old table during `schema_mode="overwrite"`, so an in-place overwrite cannot
drop the v2 column set.

## Implementation

- Use the supported Delta-rs Arrow schema accessor: `DeltaTable(path).schema().to_arrow().names`.
- Compare normalized tuples so unchanged schemas use the existing predicate-scoped overwrite.
- For a schema change, compare existing and staged partition sets. Refuse partial migrations with a
  clear error.
- For a full-range migration, write the canonical table to a sibling temporary Delta table and
  swap directories with rollback if the second rename fails. This avoids Delta-rs's legacy-column
  validation while keeping the live table untouched until the replacement is ready.
- Add a regression fixture that writes a legacy v2 table and promotes the v3 schema.

Files changed:

- `src/pit_fintech/features/build_offline.py`
- `tests/integration/test_gold_partition_overwrite.py`

## Verification

Commands run:

- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/integration/test_gold_partition_overwrite.py`
  — 3 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pytest -q tests/integration/test_gold_offline_features.py`
  — 4 passed.
- `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff check src/pit_fintech/features/build_offline.py tests/integration/test_gold_partition_overwrite.py`
  — all checks passed.
- `git diff --check` — passed.

The owner should now rerun the original `promote-gold --run-id ...` command against the retained
staging artifact. No real Gold table was mutated by this agent verification.

## Known gaps / next step

The owner-run real-data promotion and subsequent materialization/parity gates remain open. The
migration guard intentionally rejects a staged partition subset when the committed schema differs;
rebuild a full-range v3 Gold staging artifact if that occurs.
