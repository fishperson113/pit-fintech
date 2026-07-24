# M012 — Engineering-only proposal deck

- Date: 2026-07-24
- Status: verified

## Scope and acceptance

Remove thesis-ready positioning from the four-slide proposal deck while preserving the pitch's
engineering/MLOps goal, PIT architecture, observability boundary and six-week scope.

Acceptance requires:

- no thesis/thesis-ready language or separate thesis extension card in the deck;
- slide 4 describes only the runnable, evidence-backed engineering outcome;
- slide count and navigation remain unchanged;
- the unused research-card styling is removed;
- current project status and cumulative changelog are updated.

## Files changed

- `docs/reports/pit-fintech-proposal-slides.html`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification evidence

```text
Deck thesis-term scan: pass (no thesis/thesis-ready occurrences)
Deck slide count: 4 sections remain
Deck research-card scan: pass (no .direction.research style or card)
git diff --check: pass
```

## Deviations, gaps and next step

- The speaker script and knowledge checklist were intentionally not changed; this request was
  limited to pitch-deck content.
- Browser rendering was not rerun in this edit; existing deck structure and navigation were kept
  unchanged, and a visual render can be run separately if needed.
