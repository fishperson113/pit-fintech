# M040 — Optimize Gold promote read-back verification

- Date: 2026-08-05
- Status: **implemented, verified via fixtures**.
- Scope: speed up the T2 promote path (`promote_staged_gold` -> `_write_gold_table`) without
  changing any published business output.

## Problem observed

A real `promote-gold` run for the full `1..743` range showed sustained high CPU with a working set
climbing to ~10 GB. Read-only process inspection confirmed the worker was busy (CPU seconds kept
increasing), not locked; the cost came from the read-back verification inside `_write_gold_table`:

1. `delta.to_pyarrow_table()` loaded the entire committed table after writing, then filtered in
   Python;
2. the partition filter materialised every row through `to_pylist()` and a Python `in` check;
3. the logical-output check compared two `_canonical_checksum()` values, each of which runs
   `to_pylist()` + `json.dumps` over the full multi-million-row table;
4. partition discovery also used `to_pylist()` on the whole partition column.

## Change

`src/pit_fintech/features/build_offline.py` — `_write_gold_table` only:

- Partition discovery uses `pa.compute.unique` instead of full-column `to_pylist()`.
- Read-back uses `delta.to_pyarrow_dataset().to_table(columns=..., filter=isin(partitions))` so only
  the written partitions are scanned, instead of loading the whole table and filtering in Python.
- The logical-output check now compares the sorted Arrow tables with
  `output.equals(expected, check_metadata=False)` instead of hashing both via `to_pylist()` +
  `json.dumps`.
- The published `logical_checksum` still uses the unchanged `_canonical_checksum(table)` on the
  input table, so every persisted checksum value is byte-identical to before.
- `promote_staged_gold` gained an optional `progress: bool = False` flag (default preserves the
  library contract) that prints `[promote +Xs]` phase lines like the Gold build path; the
  `promote-gold` CLI enables it, so `make gold`-style progress is visible during promotion.

No contract, schema, predicate, promotion strategy, checksum value, or validation changed.

## Verification

- Ruff check and format check on the changed file: pass.
- `tests/integration/test_gold_offline_features.py`: 4 passed.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 21 passed, 4 known warnings.
- The running real promote process was not interrupted; the fix applies to the next run.

## Open

- The in-flight real promote (`gold-1-743-20260805T150620864637+0700`) still runs the old code; its
  result remains valid evidence. A re-run after this fix should reproduce identical checksums.
