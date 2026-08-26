# M096 — Knowledge-time-aware Locust workload

- **Datetime:** 2026-08-25
- **Status:** implemented; RED/GREEN contract test and live one-user `/score` smoke passed.
- **Scope:** make the default Locust workload explicitly exercise trusted-ingress knowledge time instead of relying only on the API fallback `knowledge_step = step`.

## Scenario

All ten requests now carry explicit knowledge time. Knowledge time is monotonic in request arrival order:

| Call | Event step | Knowledge step | Meaning |
|---|---:|---:|---|
| seed | 700 | 700 | on-time |
| advance | 701 | 701 | on-time |
| advance | 702 | 702 | on-time |
| exact retry | 702 | 702 | preserves first-seen knowledge time |
| different-ID retry | 702 | 702 | same event identity semantics |
| gap advance | 704 | 704 | on-time with event-step gap |
| delayed/out-of-order | 703 | 705 | known after newer step 704 |
| late arrival | 701 | 706 | substantially delayed event |
| delayed conflicting step | 702 | 707 | conflicting historical request |
| resumed advance | 705 | 708 | later event accepted at a later knowledge cutoff |

The final four requests deliberately use `knowledge_step > step`. This remains a synthetic PaySim ordinal mapping: it models the knowledge time a production wallet gateway would stamp, not a claim that a public caller should control production knowledge time.

## TDD evidence

A unit contract test was added first at `tests/unit/test_locust_write_path_contract.py`.

RED result before implementation:

```text
FAILED test_locust_sequence_uses_explicit_monotonic_knowledge_time_with_delayed_events
KeyError: 'knowledge_step'
1 failed
```

The test enforces:

- exactly ten `_score` calls;
- every call has an explicit knowledge step;
- every `knowledge_step >= step`;
- knowledge time is monotonic in request-arrival order;
- at least three calls have delayed knowledge.

GREEN result:

```text
1 passed
```

## Live verification

Command:

```text
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups locust -f scripts/locust_write_path.py --host http://127.0.0.1:8000 --headless -u 1 -r 1 -t 15s --csv artifacts/reports/locust-knowledge-time-smoke --only-summary
```

Result:

- API readiness gate passed before Locust started.
- 10 POST `/score` requests.
- 0 failures (`0.00%`).
- Delayed cases 703/705, 701/706, 702/707 and resumed 705/708 all returned HTTP 200 and matched expected feature metadata.
- Aggregated average 78 ms, median 50 ms, max 273 ms.
- Output: `LOCUST WRITE PATH PASS`.
- Exit code `0`.
- A fresh random `CLOCUST...` entity was used; Redis was not reset.

## Files

- `scripts/locust_write_path.py`
- `tests/unit/test_locust_write_path_contract.py`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Boundary

The current serving path rejects older event steps after state has advanced, while still recomputing a strict pre-decision response at the historical cutoff. Therefore the delayed 703/705 and 701/706 requests prove request handling and PIT-safe response semantics; they do not claim that online state applies historical corrections after a newer event has already been committed.
