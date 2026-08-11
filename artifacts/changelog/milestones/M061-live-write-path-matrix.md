# M061 — live online write-path retry and advancement matrix

- **Datetime:** 2026-08-11
- **Status:** verified (live FastAPI + worker)
- **Sprint / task:** Sprint 2 T5/T7 — monotonic online writes, at-least-once retries, gaps, out-of-order and late-arrival probes

## Scope

Added `scripts/live_write_path_matrix.py` and the `live-write-matrix` Make/PowerShell targets. The
probe creates a fresh entity, sends requests to the running FastAPI `/score`, asserts feature-step
and staleness metadata, compares retry scoring fields, and writes every request/response to
`artifacts/reports/live-write-path-matrix.md`.

## Cases executed

1. Seed step 700: cold pre-decision state.
2. Advance step 701 and step 702: monotonic writes use the latest strictly prior event.
3. Exact retry step 702: same response scoring fields.
4. Retry step 702 with a different transaction ID: still idempotent because duplicate identity is
   based on step, knowledge step and amount rather than transaction ID.
5. Advance with a gap to step 704: state advances and reports staleness 2.
6. Out-of-order step 703 after step 704: old request scores against prior step 702; stored state is
   not moved backward.
7. Late-arrival step 701 with `knowledge_step=704`: old request scores against step 700; online
   older-write guard leaves state unchanged.
8. Conflicting same-step amount at step 702: does not overwrite the newer state.
9. Step 705 after all rejected/older requests: resumes from stored step 704, proving monotonic state.

## Results

- HTTP 200 for all ten requests.
- Exact and different-transaction-ID retries matched the original step-702 scoring fields.
- All assertions passed: `live write-path matrix: PASS`.
- Fresh entity: `CMATRIXCFDD129553`.
- Evidence report: `artifacts/reports/live-write-path-matrix.md`.

## Retry-policy interpretation

The live matrix verifies at-least-once request replay behavior, not a network timeout injection. A
repeated `/score` request is safe when it has the same step, knowledge step and amount: the worker
returns the same pre-decision vector without double-counting. The internal optimistic-lock retry
under Redis `WATCH/MULTI/EXEC` was not forced into a collision by this probe.

## Known observations

- The API response does not expose the internal `outcome` (`written`, `noop_identical`,
  `rejected_older`); state preservation is inferred from later monotonic responses.
- `feature_status` remains `fresh` when a prior record exists even when `staleness_steps=2`; the
  numeric staleness field is the reliable evidence of logical step distance in this worker path.
- Online late-arrival correction remains guarded as an older write; it is not merged into the
  existing aggregate by this matrix.
