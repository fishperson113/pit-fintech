# M027 — Fix non-deterministic vector_checksum: sum money in DECIMAL, not DOUBLE

- Date: 2026-07-29
- Status: verified

## Scope and acceptance

Fix the regression discovered while investigating why `vector_checksum` differed across
back-to-back `train` runs on identical inputs: `pit_prior_amount_*h` and its sibling money
columns were summed as `DOUBLE`, which is not associative under floating-point rounding, and
DuckDB's parallel hash-based `GROUP BY`/`FILTER` aggregation does not guarantee the same partial-
sum merge order between runs. This milestone makes money arithmetic exact so the checksum is
reproducible, without changing the frozen `paysim-fraud-recipient-v2` contract or its dtypes.

## Problem: vector_checksum is not deterministic

Three `train` runs against the same Silver v4 (`source_tables[].logical_checksum` unchanged) and
the same code commit produced three different `vector_checksum` values:

| Run | vector_checksum | training_component_fingerprint | code_commit |
|---|---|---|---|
| 1 | `ff52681f…` | `381de46f…` | (pre-refactor window-function commit) |
| 2 | `4790cffe…` | `15db31e4…` | `1542e8f…` |
| 3 | `28c5d63d…` | `15db31e4…` | `1542e8f…` (same as run 2) |

Runs 2 and 3 share the **same commit and the same training component fingerprint** yet still
disagree — ruling out a code or contract difference as the cause of that pair's drift. Across all
three runs: E1 and E4 metrics (PR-AUC, ROC-AUC, recall@fixed-FPR) matched **bit-exact**,
`future_read_violations = 0` every time, and the Silver logical checksum never moved. The only
thing that moved was the byte content of the money columns inside the vector table.

## Root cause

Two conditions had to hold together, and both trace to the M026 window-function-to-range-join
refactor:

1. `sum(amount)` is computed over `DOUBLE`, which is not exact and not order-independent — adding
   the same set of floating-point numbers in a different order can land on a different last bit.
2. DuckDB's hash-based `GROUP BY` (which the range-join refactor introduced in place of the prior
   `OVER (PARTITION BY ... ORDER BY step)` window frame) runs multi-threaded and merges partial
   sums from each thread in whatever order they finish, which is not fixed across runs.

Before the refactor, the window function carried an explicit `ORDER BY step` inside its frame, so
the second condition did not exist: summation order was pinned by that `ORDER BY` even though the
arithmetic was still `DOUBLE`. The range join has no equivalent ordering guarantee over its
`GROUP BY`, so removing the window frame exposed the first condition (rounding) to the second
(non-deterministic order) for the first time. **This is a regression introduced by the M026
refactor, not a pre-existing defect** — the frozen M019 baseline and the M024/M025 test suites
never exercised a code path where both conditions could combine.

## Why this matters

- **G2 (Backfill idempotency)**: a full or range rerun of the same backfill must produce the same
  checksum. With `DOUBLE` summation under a non-deterministic merge order, it does not — G2 cannot
  pass while this regression stands.
- **G10 (Lakehouse snapshot/version identity)**: anything that compares vector or manifest
  checksums across reruns of the same Silver version inherits the same failure mode.

## Fix

Sum money as `DECIMAL(18,2)` and cast back to `DOUBLE` only at the final projection, instead of
locking summation order:

- `PAYSIM_AMOUNT_DECIMAL_TYPE: Final = "DECIMAL(18,2)"` added to
  `src/pit_fintech/features/paysim_specs.py`.
- Both PIT engines now compute `sum(CAST(s.amount AS DECIMAL(18,2))) FILTER (WHERE ...)` instead
  of `sum(s.amount) FILTER (WHERE ...)`, casting the result to `DOUBLE` only in the outer
  projection (`src/pit_fintech/features/paysim_recipient.py`, `src/pit_fintech/models/
  paysim_training.py`).
- `paysim_recipient.py`'s derived control columns (`current_inclusive_amount_*`,
  `leaky_centered_amount_*`, `leaky_lifetime_amount`) and its two leakage-gate reporting queries
  (`recipient_leakage_window_gate`, `recipient_leakage_breakdown`) were also moved to `DECIMAL`
  addition, so a rounding scalar add could not reintroduce a last-ulp mismatch against the now-
  exact `pit_prior_amount`/`future_amount` columns they are compared against.

**Why DECIMAL instead of locking summation order.** Fixed-point (integer-scaled) addition is
exact, associative and commutative — a hash aggregate produces the same total no matter what
order partial sums are merged in, by construction. Forcing a fixed merge order (e.g. disabling
DuckDB's parallelism, or re-adding an `ORDER BY` window frame) would only constrain *how* the sum
is computed, not remove the rounding that made the result order-sensitive in the first place; a
future planner change, thread-count change, or DuckDB version bump could reopen the same failure
mode. Fixing the arithmetic removes the sensitivity outright.

**Overflow check.** PaySim's largest single `amount` is ~9.24e7. The most implausible 168h/lifetime
sum the fixture design considered is bounded at ~5.9e14 — about 17x below `DECIMAL(18,2)`'s
~1e16 integer-part ceiling. DuckDB additionally promotes `sum(DECIMAL(18,2))` to `DECIMAL(38,2)`
internally, so there is no overflow risk at PaySim's scale.

**Contract impact.** None. Every feature's declared dtype stays `float64` (`DOUBLE`); only the
intermediate arithmetic changed. `paysim-fraud-recipient-v2` is not bumped to v3 — per the ADR-003
change policy, a version bump is for semantics/order/dtype/default changes, and none of those
changed here.

## New guard: 9th quality gate

`_quality_gates()` in `src/pit_fintech/data/paysim_lakehouse.py` gained a publish-blocking gate,
`amount_decimal_roundtrip_failures` (`AMOUNT_DECIMAL_GATE`): every raw `amount` must round-trip
through `TRY_CAST(amount AS DECIMAL(18,2))` back to `DOUBLE` without changing value. If any row
needs more than 2 decimal places or exceeds the DECIMAL range, this gate fails loudly with a
message naming the fix (raise `PAYSIM_AMOUNT_DECIMAL_TYPE`'s scale/precision and rebuild), instead
of silently rounding money that downstream sums assume is exact. Gate count in
`_quality_gates()` moves from 8 to 9 (`tests/integration/test_paysim_lakehouse.py` updated from
`len(first.quality_gates) == 8` to `== 9`).

## New tests

`tests/temporal/test_injected_pit_fixtures.py` replaces `tests/temporal/test_knowledge_time_predicate.py`
(same knowledge-time coverage carried over unchanged: boundary/mutation tests for the `<=`
knowledge-time predicate, parametrized over both PIT engines) and adds the money-arithmetic
coverage for this milestone:

- `test_money_sums_equal_the_exact_decimal_total` (parametrized over `["recipient", "training"]`)
  — a 13-row fixture with deliberately binary-inexact amounts (`0.10`, `0.20`, `0.07`, `0.03`,
  `1234.56`, `9999.99`, ...) whose exact decimal totals are computed independently via
  `decimal.Decimal` in the test itself and asserted against every money column both engines
  produce. This is the load-bearing regression test: reverting the aggregates to plain `DOUBLE`
  summation turns it red deterministically, not by luck of thread scheduling.
- `test_materializing_twice_produces_identical_vectors` (parametrized over `["recipient",
  "training"]`) — materializes the same fixture twice in one process and asserts every column of
  every row is identical. Explicitly documented in the test as a weaker, best-effort check (see
  Known gaps below).

## Files changed

- `src/pit_fintech/features/paysim_specs.py` (`PAYSIM_AMOUNT_DECIMAL_TYPE`)
- `src/pit_fintech/features/paysim_recipient.py` (DECIMAL sums in prior/future windows, derived
  columns, and both leakage-gate reporting queries)
- `src/pit_fintech/models/paysim_training.py` (DECIMAL sum in the prior window)
- `src/pit_fintech/data/paysim_lakehouse.py` (`AMOUNT_DECIMAL_GATE`, 9th quality gate)
- `tests/integration/test_paysim_lakehouse.py` (gate count 8 -> 9)
- `tests/temporal/test_injected_pit_fixtures.py` (new; absorbs the prior knowledge-time test file
  and adds the money-arithmetic tests)
- `tests/temporal/test_knowledge_time_predicate.py` (deleted; merged into the file above)
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

User-run evidence, 2026-07-29 (agent did not execute these commands):

```text
Two separate, consecutive `train` runs against rebuilt Silver
(silver.paysim_transactions=v6, silver.paysim_labels=v6) produced the SAME vector_checksum:

vector checksum: ce88d250000ec529e42c03a201991ae8f69cb3e3607ad7ac4301a1d4f3216247
training fingerprint: a005f4ea7dac09c19b82be2c95ac5f4afbd9d174ac19826d1a1662694dfafeef
MLflow runs: d398b7e5fc474b4cb707cc7d97eda5b2, 6d250b52cc574db9880cfd80e8aa7db2

E1  PR-AUC 0.258342  ROC-AUC 0.601620  recall@FPR 0.275559  precision@FPR 0.541601
E4  PR-AUC 0.102766  ROC-AUC 0.784978  recall@FPR 0.036741  precision@FPR 0.243386

future-read violations: 0

.\make.ps1 test-temporal: 47 passed (up from 33; +14 = 7 tests x 2 engines, matching the new
  tests/temporal/test_injected_pit_fixtures.py money-arithmetic coverage)
.\make.ps1 test-unit: 39 passed
```

This is the pass criterion from the prior "Known gaps" item: two separate `train` processes
against the same Silver version now produce an identical `vector_checksum`, closing the
non-determinism this milestone set out to fix.

**Notable:** E1 and E4 did **not** move from the M019/M026 baseline (`0.258342`/`0.102766`) even
though the underlying arithmetic changed from `DOUBLE` to `DECIMAL(18,2)`. The old floating-point
rounding error was small enough to never cross a LightGBM histogram-bin boundary — small enough to
be metric-invisible — yet large enough to change the summation's last bit and therefore the
`vector_checksum` byte-for-byte. That gap between "invisible to the model" and "visible to a
byte-exact hash" is exactly why `vector_checksum` exists as a separate reproducibility signal
rather than relying on the reported metrics alone.

## Known gaps and next steps

1. **E1/E4 may shift in the last digit versus the M019 baseline.** DECIMAL summation is more
   precise than the DOUBLE running sum M019 used, so a tiny difference from `0.258342`/`0.102766`
   at the far decimal places would be *correct* — a sign the fix worked, not a defect. What must
   **not** differ is the two post-fix `train` runs from each other. (In the run recorded above,
   both metrics happened to match exactly; see the "Notable" paragraph.)
2. **`test_materializing_twice_produces_identical_vectors` is a thin net, not full proof.** Both
   calls run in the same process, sharing a thread pool and query-plan cache, so it cannot catch
   non-determinism that only appears across separate process launches (which is exactly how the
   original bug was discovered — across separate `train` invocations). It is kept because it
   diffs every column of every row and so catches unrelated regressions, but it is not a substitute
   for the two-separate-process check confirmed above.
3. **The user-run evidence above is strong but not absolute proof of determinism.** It confirms two
   runs agree on one machine, at one thread/core count, in one DuckDB build. The number of partial
   sums a hash `GROUP BY` merges depends on thread count, so a machine with a different core count
   could in principle exercise a merge order this run never took. Higher confidence would come from
   repeating the two-run check on a machine with a different core count; this has not been done.
