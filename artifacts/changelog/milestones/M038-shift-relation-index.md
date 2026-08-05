# M038 — Index shift-relation validation by entity

- Date: 2026-08-05
- Status: **implemented, not verified**.
- Scope: remove the O(number_of_entities × number_of_post_rows) scan in Gold shift validation.

## Change

`verify_shift_relation` previously looped over every requested entity and rescanned the complete
post-event row list for each entity. It now builds `post_by_entity` once, then iterates only the
post-event rows belonging to the current entity.

The following behavior is unchanged:

- `(entity, step + 1)` lookup into pre-decision rows;
- `POST_EVENT_TO_CONTRACT_FIELD` comparison;
- compared/mismatch counts;
- validation names and ordering;
- explicit `entity_ids` handling and missing-vector behavior.

Complexity changes from repeated full scans toward one indexing pass plus matching-row scans, at the
cost of a dictionary of row references.

## Verification

- Focused Gold fixture/range tests: 12 passed.
- Ruff check: All checks passed.
- Ruff format check: 86 files already formatted.
- Unit: 87 passed.
- Temporal: 73 passed.
- Integration: 17 passed, one existing Ibis deprecation warning.
- No real Gold build or promotion was run; the already-running user process was not interrupted.
