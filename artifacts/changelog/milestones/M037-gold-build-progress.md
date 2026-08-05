# M037 — Add low-overhead Gold build phase progress

- Date: 2026-08-05
- Status: **implemented, not verified**.
- Scope: observability-only progress output for the Gold CLI build path.

## Change

`build_offline_features` now accepts `progress=False` by default. The CLI passes `progress=True`.
When enabled, the builder prints phase boundaries with elapsed seconds:

- Silver read start and loaded row count;
- same-step audit start/complete;
- pre-decision query start/complete;
- post-event query start/complete;
- future-read audit start/complete;
- SQL row-count validation;
- Gold staging write start/complete;
- shift-relation validation;
- final staging completion.

There is no per-row progress callback, no DuckDB progress-bar setting, and no business-logic or SQL
semantics change. Library callers retain silent behavior by default.

## Verification

- Focused CLI/Gold tests: 14 passed.
- Ruff check: All checks passed.
- Ruff format check: 86 files already formatted.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 17 passed, one existing Ibis deprecation warning.
- No real Gold build or promotion was run.

## Expected impact

The overhead is limited to a small number of flushed console writes around phase boundaries. It is
not expected to materially affect runtime; actual runtime/phase timing must be measured by a real
user-run build.
