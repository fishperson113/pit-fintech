# M032 — Sprint 2 round 0 scaffold and cross-module contracts

- Date: 2026-08-04
- Status: **implemented, not verified**.
- Commit: pending. This log is prepared for Dương to review and commit; no commit was made by this work.

## Scope and boundary

Round 0 creates the shared shape for the remaining Sprint 2 work (T2–T9), not a working feature
platform. It adds **19 new files (3,842 lines)** and modifies `compose.yaml` for the T8 service
scaffold. The new modules cover Gold-feature construction, backfill, materialization, training,
replay/parity, serving, and an E2E test package.

The status is deliberately **implemented, not verified**. Import succeeds and the reported lint and
existing test lanes are clean, but those results do not execute the planned pipeline. The scaffold
entry points remain `NotImplementedError`; the only explicitly implemented helper is
`backfill_idempotency_key()` in `backfill/records.py`. Therefore this milestone does **not** claim
that Gold build, backfill, materialization, training, replay, serving, promotion/rollback, or E2E
works. No T2–T9 acceptance gate is closed here.

`compose.yaml` is part of the Round 0 work (adds the `api` service and `minio` profile), but it is
not edited by this changelog task. `AGENTS.md` is modified in the worktree because Dương updated it
for Codex; it is **not** a Round 0 product and must not be reverted or attributed to M032.

## Contracts frozen for subsequent rounds

The following seven interfaces were written before implementation so separately built modules have
one agreed seam. Do not alter them implicitly; a change must be recorded and communicated because
other modules bind to them.

1. The two Gold-table names, paths, and complete schemas in `features/build_offline.py`.
2. `OfflineFeatureBuildResult`, the T2 return type, in `features/build_offline.py`.
3. `BackfillRunRecord`, the approximately 30-field run record required by guide §5.1, in
   `backfill/records.py`.
4. `backfill_idempotency_key()` in `backfill/records.py`.
5. `FeatureProvider` ABC and its four adapters in `serving/feature_provider.py`.
6. `ParityFieldResult`, `CheckpointResult`, and `ParityRunReport` in `replay/parity.py`.
7. Pydantic `ScoreRequest` and `ScoreResponse` in `serving/schemas.py`.

## Design constraints that must not be simplified away

- Post-event fields intentionally use names different from the model contract, for example
  `post_count_1h` rather than `pit_prior_count_1h`. This is a leakage guard: a training job pointed
  at the wrong table should fail with `KeyError`, rather than silently consume current-inclusive
  aggregates. `POST_EVENT_TO_CONTRACT_FIELD` is the only permitted bridge between vocabularies.
- Parity reports keep `integer_mismatches` separate from `float_mismatches`. AGENTS.md §9 requires
  integer/categorical mismatches to be exactly zero; only floats may use a tolerance. Merging these
  fields would allow tolerance to conceal an integer mismatch.
- `ParityRunReport.passed` requires both zero mismatches at every checkpoint and
  `missing_checkpoints == ()`. A run that omits the required same-second-tie checkpoint cannot pass
  merely because its remaining checkpoints agree.

## Known traps carried into implementation

1. Feature tables must be produced by the SQL engine, never by `paysim_reference.py`. The oracle is
   an expectation, not a producer; otherwise oracle-versus-oracle comparison is tautological. When
   results differ, treat SQL as wrong until independently demonstrated otherwise, and do not edit
   expected values to match output.
2. Derive Feast timestamps in Python through `paysim_step_to_timestamp`, not SQL. DuckDB
   `TIMESTAMPTZ` rendering is session-time-zone dependent, while the project requires deterministic
   Parquet output. `EPOCH_0` remains `2020-01-01T00:00:00Z`.
3. The current T1 feature table has 11 scoring rows at 11 distinct timestamps, so the same-step pair
   has not reached Feast, an online store, or replay. T2 must run and inspect
   `probe_same_step_ties()`. If in-scope Gold data has no tie, create one before T6. The checkpoint
   planner accepts `same_step_tie_available` as an explicit input to prevent a claimed tie from
   being inferred without evidence.

## Decisions intentionally left open

1. How Feast reads Gold Delta: export Parquet, use a Feast DuckDB offline-store view, or retain
   Feast at fixture scale. `FileSource` cannot read the Delta log; the decision point is
   `export_feast_source_parquet()`.
2. How to handle an entity with no event at step `s`. The relation
   `post_event_state(s) == pre_decision_history(s+1)` only holds one step apart; temporary default
   is `stale_after_steps = 1`, but changing it is a policy decision, not a parity workaround.
3. Whether the idempotency-key payload should keep the `backfill-idempotency-key-v1` prefix. Round
   0 includes it, producing a different digest from the guide §5.2 five-field formula; the stated
   rationale is that this repository versions every hashed identity.
4. Whether and how to unify the existing 10-field `contracts/manifests.py::BackfillManifest` with
   the guide's roughly 30-field `BackfillRunRecord`. This touches both ADR-004 component-fingerprint
   boundaries and is ADR-scale, not a routine refactor.
5. How to resolve the 12-field-versus-9-field seam between T1 and T7: Feast currently declares all
   12 batch fields, while `FeatureProvider` models nine because three request-time values originate
   from the request. T7 must choose projection to nine or an `OnDemandFeatureView`, and record it.

Two deliberate guide deviations remain pending decisions, not silent changes:

- The version prefix in the idempotency-key hash described above changes the guide's literal
  formula.
- No `e2e` marker was added to `pyproject.toml`: ADR-004 includes that file in both component
  fingerprint boundaries, so the marker would invalidate exact-Silver reuse. Existing E2E selection
  uses the `integration` marker and test path instead.

## Recorded checks

The 2026-08-04 HANDOFF records only these checks for Round 0:

```text
import: OK
uv run ruff check src tests feature_repo notebooks scripts: clean (79 files)
uv run pytest -q tests/unit: 50 passed
uv run pytest -q -m temporal tests/temporal: 73 passed
uv run pytest -q tests/e2e: 12 skipped
```

These are scaffold/import/lint and existing-test results only. In particular, `12 skipped` is not
an E2E execution result. No live pipeline behavior is asserted beyond import, lint, and the listed
test collection/execution.

## Files and worktree accounting

Round 0 adds 19 files under:

- `src/pit_fintech/backfill/`, `materialization/`, `replay/`, `serving/`, and `training/`;
- `src/pit_fintech/features/build_offline.py`; and
- `tests/e2e/`.

It modifies `compose.yaml`. The contemporaneous worktree also contains modified `AGENTS.md`, but
that file is Dương's Codex instruction update, outside this milestone. No file was deleted by
Round 0 or by this documentation task.

## Gaps, risks, and next step

The T2 Gold implementation is the dependency root for T5 materialization, T6 replay/parity, and
T7 serving. The pending decisions above must be made explicitly where they become material. The
next implementation work is T2; this log does not assert that it is ready, only that the intended
interfaces and known constraints have been documented.
