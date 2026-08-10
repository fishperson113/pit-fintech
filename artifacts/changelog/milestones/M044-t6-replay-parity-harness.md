# M044 — T6 replay driver, offline/online parity harness, and the G6 lane

- **Datetime:** 2026-08-10
- **Status:** implemented (pure logic unit-tested; G6 gate NOT claimed — user-run)
- **Sprint / task:** Sprint 2, T6 (guide s8; gate G6)
- **Gate:** G6 Parity — "mismatch = 0 theo tolerance trên required checkpoints" (guide s13). G6 is
  the sprint's Definition of Done (guide s12); if it does not pass, guide s13 restricts Sprint 3 to
  debug/parity work. **Not claimed here.**

## Scope

Move `src/pit_fintech/replay/driver.py` and `src/pit_fintech/replay/parity.py` from round-0
skeleton (every body `raise NotImplementedError`) to working implementations, add a test lane for
the pure logic, and wire `pit replay parity` + Make/PS targets. The full-scale G6 gate remains a
user-run command per hard-rule #1.

## What was implemented

### `replay/driver.py`
- `ReplayDriver.__init__` validates the queue is sorted by `(step, source_row_number)` and raises
  otherwise — accepting an `event_timestamp`-ordered queue would be unordered within a step
  (ADR-006 dec 1.4) and is the mistake that "looks like it worked".
- `emit()` yields one `ReplayStepResult` per event, running `read_online_state -> score ->
  commit_post_event_state -> append_event_history` with no overlap; out-of-scope events are not
  scored but still commit post-event state (history counts every prior event to a destination
  regardless of type). `read_before_update` is recorded as `read_end <= commit_start` (evidence,
  not an assertion).
- `run()` aggregates: `events_emitted/scored/skipped`, `out_of_order_events` (0), `concurrent_
  emissions` (0 by construction — one synchronous generator), `same_step_events_seen`, first/last
  step, final watermark.
- `load_replay_events` reads a Silver step range via `DeltaTable(...).to_pyarrow_dataset()`,
  computes `in_scoring_scope` from `PAYSIM_FEATURE_CONTRACT.scoring_transaction_types/
  scoring_destination_kinds`, and sorts once.

### `replay/parity.py`
- Pure: `canonicalize_vector` (12 fields in `PAYSIM_MODEL_FEATURE_ORDER`, null->contract default,
  int64/float64 cast, a missing contract field is a shape `KeyError` not a null) and
  `classify_mismatch` (structural causes — `WRONG_FEATURE_VERSION`, `MISSING_ENTITY`,
  `STALE_ONLINE_TIMESTAMP` — named before `VALUE_DIFFERENCE`; integers compared exactly, tolerance
  applies to floats only; a non-integral value on an int field is `DTYPE_OR_ROUNDING_MISMATCH`, not
  silently truncated).
- `plan_checkpoints` resolves the six guide s8.3 checkpoints from `gold.pre_decision_features`
  (`BEGINNING_OF_STREAM`, `FINAL_MATERIALIZATION`, `AROUND_HIGH_VOLUME_PERIOD` = densest step with a
  deterministic tie-break, `AROUND_SPLIT_BOUNDARIES` = first cutoff past 631/520, `SAME_SECOND_TIE`
  = second in-scope cutoff sharing a step). `SAME_SECOND_TIE` is gated on the T2 probe flag and
  `SYNTHETIC_LATE_ARRIVAL` is always placed in `unsatisfiable` (no backfill injection is wired), so
  a partial cover cannot look like a pass.
- `compare_at_checkpoint` reads the online vector (before e's update) and offline
  `pre_decision_features(e)`, canonicalizes both, and compares all 12 fields. `run_parity_harness`
  resets the namespace, replays with one `ReplayDriver` whose handler commits each event's
  post-event Gold row to the online store, captures the comparison at each checkpoint, and returns a
  `ParityRunReport` whose `passed` requires zero integer + zero float mismatches AND empty
  `missing_checkpoints`. `write_parity_report` persists guide s8.2 rows under `artifacts/parity/`.

## Decisions + rationale

1. **The driver is pure and single-threaded; the handler supplies all I/O.** This makes "read
   before update" a property of the harness (unit-testable against an in-memory handler) rather than
   a convention each backend is trusted to follow.
2. **Parity is measured through the real online store, not by comparing two Gold tables.** The
   handler writes each event's post-event state to Redis via the M043 `write_record`, so the lane
   catches materializer/key/serialization bugs, not just SQL-vs-SQL agreement.
3. **Staleness / same-step ties are surfaced as classified mismatches, never smoothed over.**
   `GOLD_SHIFT_RELATION` holds exactly only at a one-step shift. A cutoff whose entity's latest
   prior event is >1 step back reads STALE; a same-step tie reads the tied prior event that offline's
   strict-prior-step rule excludes. Resolving how serving should treat these is the open T5/T6 design
   item the shift-relation docstring flags — this harness reports it and keeps `passed=False`, it
   does not decide it silently.

## Files touched

- `src/pit_fintech/replay/driver.py` — implemented (was skeleton).
- `src/pit_fintech/replay/parity.py` — implemented (was skeleton); added `_values_match`,
  `_load_cutoff_candidates`, `_read_offline_vector`, `_load_post_event_rows`, `_ReplayParityHandler`,
  `_with_report_path`.
- `src/pit_fintech/cli.py` — new `replay` Typer group + `pit replay parity`.
- `tests/unit/test_replay_driver.py`, `tests/unit/test_parity_classification.py` — new (pure).
- `tests/integration/test_replay_parity.py` — new (planning over a small Delta table; no Redis).
- `Makefile`, `make.ps1` — `test-parity` and `parity` targets (+ `PARITY_START/PARITY_END`).

## Commands + results

- Agent, in the Linux sandbox (static analysis only — the repo env cannot be synced here, GitHub
  download of the pinned CPython is blocked): `ruff check` and `ruff format --check` **clean** on
  `replay/driver.py`, `replay/parity.py`, `cli.py`, and the three test files; `python -m ast`
  parses all changed modules.
- **Not run by the agent (require the repo env / Redis / Gold):** `test-unit`, `test-temporal`,
  `test-parity`, and the real `parity` run.

### Gate commands for the project owner (PowerShell)

```powershell
.\make.ps1 lint
.\make.ps1 test-unit            # expect the driver + classification tests to be picked up
.\make.ps1 test-temporal        # regression: unchanged
.\make.ps1 test-parity          # driver + classification unit tests + planning integration test
# Real G6 on committed Gold v6 (needs Redis up):
.\make.ps1 redis-up
.\make.ps1 parity -Start 1 -End 743
```

## Deviations

- The e2e marker convention is unchanged (path selection, no `pyproject.toml` edit — ADR-004
  fingerprint boundaries). The new integration test uses the existing `integration` marker.
- No new field was added to `ReplayRunResult`; `read_before_update_violations` in the report folds
  into `out_of_order_events` (both 0 by construction).

## Design finding — ADR-007 (proposed)

Owner review raised the sharper problem behind the staleness finding: in the MVP the online store is
a **materialized copy** of offline Gold, and serving does **no computation** — so the parity harness
compares offline against a copy of itself. The only non-vacuous content is the shift relation between
two offline tables plus the materialize/rename/serialize plumbing; that is an integration test, not
the train/serve-skew correctness proof G6 is presented as. Materialization *can* still have plumbing
bugs, so the check has value, but it must not be sold as the correctness gate.

Recorded as `docs/adr/007-parity-requires-an-independent-online-computation.md` (status `proposed`)
with two directions for the owner:

- **Option A** — keep materialize-only scope; reclassify the harness as a materialize + shift-relation
  integration guard and defer G6-as-correctness.
- **Option B** — give the write path an independent incremental windowed feature maintainer
  (read -> score -> compute new 1h/24h/168h state by increment + eviction -> write); parity then
  compares that independently-maintained state against offline `pre_decision_features` and genuinely
  catches drift. Only the handler's `commit_post_event_state` changes; the driver and pure primitives
  are reused unchanged.

No code or contract changed for this ADR; the A/B choice is the next decision.

## Known gaps / next steps

- **G6 is not claimed.** The staleness / same-step design item must be resolved before a clean
  `mismatch=0` run is meaningful: either checkpoints are chosen in the one-step-shift arrangement, or
  serving's stale-cutoff policy is decided and encoded. Do not raise the float tolerance to make it
  pass (guide s8.4).
- `_load_post_event_rows` loads the range's post-event rows into a dict; on the full 1..743 range
  that is millions of rows in memory. Fine for a smaller range or a machine with headroom; a
  streaming variant is a follow-up.
- `SYNTHETIC_LATE_ARRIVAL` will always be a reported gap until `backfill.inject_late_arrival_
  correction` (ADR-005 dec 7) is wired into the parity range.
- Determinism/behaviour shown by static analysis only; nothing committed, so no commit hash yet.
