# M007 — PIT Fintech meetup speaker script

- Date: 2026-07-23
- Status: verified

## Scope and acceptance

Create a Markdown talk track for the verified four-slide PIT proposal deck. The script must fit a
ten-minute meetup slot, prioritize temporal correctness over technology breadth, include delivery
cues and transitions, distinguish target architecture from verified implementation, and prepare
concise answers for likely mentor questions.

## Technical and narrative decisions

- Allocate most of the talk to the causal transaction path on slide 3 instead of touring logos.
- Open with a concrete future-read example, then define event time, knowledge time, deterministic
  tie-breaking, offline/online parity, and reproducible backfill.
- Explain pre-decision online state and historical offline reconstruction as the two temporal
  views governed by one contract.
- Preserve the thin Feast role and identify the independent reference oracle as the correctness
  authority.
- State the current evidence boundary explicitly: the synthetic oracle and sample Bronze/Silver
  slice are verified; the Sprint 2/3 platform remains planned.
- Add verbal corrections for the compressed observability diagram and the unresolved application
  dataset/entity decision.
- Refine slide 3 to explain why the local OLAP workload favors embedded DuckDB over a server
  database without claiming PostgreSQL is invalid.
- Explain Feast as an optional buy-versus-build contract/retrieval/materialization boundary, and
  name the equivalent custom FeatureSpec/provider/materializer/version-gate workaround.
- Compress atomic/idempotent/reproducible backfill terminology into one practical acceptance
  statement so the talk stays focused on architecture decisions.

## Files changed

- `docs/reports/pit-fintech-meetup-10min-script.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification evidence

```text
Structural content scan: pass; four slide sections, the 0:00–10:00 timing table, presentation
caveats, observability correction, verified-status boundary and mentor Q&A are present.
Source-deck reference: pass; docs/reports/pit-fintech-proposal-slides.html exists in the repo.
git diff --check: pass; existing LF-to-CRLF working-copy warnings only.

2026-07-23 DuckDB/Feast refinement:
Documentation check: Feast v0.51 historical/online retrieval and materialization boundaries, and
DuckDB in-process analytical/vectorized/Parquet workload properties, reviewed against current
official documentation.
Content scan: pass; DuckDB-versus-PostgreSQL workload trade-off, optional Feast workaround and two
new mentor Q&A prompts are present; detailed atomic/idempotent/reproducible definitions are absent.
Timing-density review: pass after compressing the new technology rationale and retaining backfill
as one practical acceptance statement.
git diff --check: pass; existing LF-to-CRLF working-copy warnings only.
```

## Deviations, gaps and next step

- The source HTML deck was not edited.
- Spoken duration depends on delivery speed; the time boxes are a rehearsal target.
- Next step: rehearse once with a timer and shorten examples before removing technical claims.
