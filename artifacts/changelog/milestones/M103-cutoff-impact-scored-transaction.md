# M103 — Cutoff impact on an already-scored transaction

- Timestamp: 2026-08-25 15:27 +0700
- Status: implemented and verified
- Scope: extend slide 4 so the audience can see why cutoff semantics prevent feature corruption
  after a transaction has already been scored.

## Acceptance and semantics

The output is `docs/reports/pit-fintech-final-report-template-13-slides-cutoff-impact.pptx`.
Slide 4 now distinguishes three transactions/events on the timeline:

1. Event A occurs at the bank at 07:00.
2. Transaction B is scored at cutoff 07:05 while A is still unknown, so A is excluded from B's
   feature vector.
3. A reaches the platform at knowledge time 07:10.
4. Transaction C is scored at 07:12 and may include A because A is both strictly prior and known
   before C's cutoff.

The cutoff impact is explicit: once B has been scored, its feature vector represents the exact
information available at 07:05. A later backfill/recomputation must not insert A into B's history.
That retroactive inclusion would produce an offline vector that never existed online, calculate
B's historical features incorrectly, and violate offline–online parity.

## Technical decisions

- Preserved the M102 deck and exported a new copy.
- Reused the inherited four-point timeline and its four callout boxes; no new shapes, overlays,
  layouts, or assets were added.
- Kept the formal future eligibility condition visible:
  `event_step(A) < event_step(C)` and `knowledge_step(A) <= cutoff(C)`.
- Updated slide 4 speaker notes while retaining a valid `[Sources]` block.
- Restored the source theme XML after artifact-tool export.

## Files added or updated

- `docs/reports/pit-fintech-final-report-template-13-slides-cutoff-impact.pptx`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- `artifacts/changelog/milestones/M103-cutoff-impact-scored-transaction.md`

## Verification

- Template frame-map validation: PASS, zero issues.
- Final slide count: 13.
- All 13 slides rendered; slide 4 inspected at full size and the full deck montage reviewed.
- `slides_test.py`: PASS, no overflow detected.
- Template fidelity: PASS, zero issues.
- Structural placeholder audit: zero empty placeholders.
- Speaker notes: 13/13 slides contain `[Sources]` blocks.
- Theme SHA-256 source/final:
  `617f40cb77f46abc81c064fefab640f84620ebc9e26c4e94ab2c4f8d41952862`.
- Final artifact size: 12,316,640 bytes.

## Known gap

The example uses minute-level production timestamps for clarity, while PaySim's native `step` is
an hourly simulation index. The predicate semantics are the same and no claim is made that PaySim
contains minute-resolution timestamps.
