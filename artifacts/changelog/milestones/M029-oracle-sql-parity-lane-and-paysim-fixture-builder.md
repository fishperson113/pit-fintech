# M029 — PaySim oracle/SQL parity lane and real-Silver fixture builder

- Date: 2026-08-03
- Status: verified within the scope that was run — lint, `test-unit`, `test-temporal`, the
  fixture-builder integration lane, and a two-run byte-identical determinism check on a machine
  holding PaySim Silver. Everything outside that scope is still marked below.
- Commit: pending — nothing in this milestone is committed yet, so no hash exists to record

## Scope and acceptance

`src/pit_fintech/features/reference.py:3-5` has said since Sprint 1 that "Full dataset optimization
belongs in a separate DuckDB implementation and must match this oracle before it is accepted." For
the PaySim application contract that comparison had never been written. The oracle and the two
DuckDB paths were three independent code paths, all green, with nothing binding them: a shared
misreading of the contract would have shown up nowhere.

This milestone closes that gap for `paysim-fraud-recipient-v2` and wires the fixture builder that
the same oracle scores. Acceptance:

1. an independent pure-Python PaySim oracle exists and is the declared correctness authority;
2. every one of the twelve `PAYSIM_MODEL_FEATURE_ORDER` fields, in contract order, is compared
   between that oracle and **both** DuckDB engines over one shared fixture, for every scored row;
3. the comparison has teeth: each mutation test provably breaks parity, or says in its own
   docstring that it cannot;
4. `pit data build-fixture` is wired through both runners with CLI guards under test.

## What changed and why

### 1. The PaySim oracle (`features/paysim_reference.py`)

Pure Python: no DuckDB, no SQL, no library window function, explicit loops. If it ran on the same
engine as the path it checks, a shared engine bug would cancel on both sides. It implements the
frozen decisions verbatim — eligibility
`prior.step < current.step AND prior.knowledge_step <= current.knowledge_step` (ADR-003 §Temporal
semantics as amended by ADR-005 decision 5), window `[current_step - window_hours, current_step)`,
money in `Decimal` at `DECIMAL(18,2)` with `Inexact`/`Rounded` trapped, and exactly the twelve
fields in contract order. It fails at import if the frozen spec no longer matches.

### 2. The parity lane (`tests/temporal/test_paysim_oracle_sql_parity.py`)

One fixture, `PARITY_ROWS`, driven through three engines: the oracle, the diagnostic SQL in
`features/paysim_recipient.py`, and the evidence SQL in `models/paysim_training.py`. Agreement
alone is not accepted as correctness — a second test pins the step-400 cutoff to a vector derived
by hand from the row table, so parity means parity with the contract rather than two paths agreeing
on the same wrong answer. The fixture deliberately carries rows far outside the SQL range prune, so
that a later edit narrowing the prune, or deleting the `FILTER`'s "redundant" lower bound, goes red.

### 3. The finding: same-step is enforced in the JOIN, on **both** engines

The same-step policy (ADR-003: "Events at the same `step` are excluded from model features") is
excluded twice on each engine, and the first exclusion is not where the predicate lives:

| Engine | JOIN clause | FILTER clause |
|---|---|---|
| recipient | `s.step <> c.step` — `src/pit_fintech/features/paysim_recipient.py:278` | `s.step <= c.step - 1` — `paysim_recipient.py:83` |
| training | `s.step <= c.step - 1` — `src/pit_fintech/models/paysim_training.py:565` | `s.step <= c.step - 1` — `paysim_training.py:414` |

The oracle excludes them too, at `features/paysim_reference.py:371`. Consequence: **no mutation of
a single clause can go red on either engine** — weaken the `FILTER` and the join still holds;
weaken the join and the `FILTER` still holds. An earlier draft of this lane asserted the opposite
(that the training `FILTER` was unmasked while the recipient one was masked). That asymmetry does
not exist, and the assertion built on it could never have failed.

The lane now records the real shape instead of the imagined one:

- `test_same_step_filter_mutation_alone_is_masked_by_the_join` and
  `test_same_step_join_mutation_alone_is_masked_by_the_filter`, both parametrized over the two
  engines, document which half absorbs which mutation. The first states in its docstring, as a
  limitation and not a property, that **no FILTER-only mutation can go red on either engine**, so
  nothing in this file would catch a same-step regression confined to `_prior_window_predicate`.
- `test_admitting_same_step_rows_breaks_parity` is the mutation with teeth: it removes both guards
  at once and requires parity to break. Reaching the join needed a new seam, because that clause is
  an SQL literal inside the materialize function and `monkeypatch.setattr` only reaches module
  attributes — `_SqlRewrite` plus a `_RewritingConnection` proxy rewrite the statement text on its
  way to DuckDB, and raise if the rewrite never matched, so a no-op mutation cannot pass silently.

Nothing about the same-step policy was weakened: it is still enforced twice on both SQL paths and
once in the oracle. What changed is that the lane no longer claims coverage it does not have.

### 4. Three corrected expected values — arithmetic errors in the test, not defects in the SQL

Each was recomputed by hand from `PARITY_ROWS` and the ADR-003 window definition before anything
was edited, and the arithmetic is written into the docstring or comment beside the assertion so the
next reader can re-derive it. No expected number was adjusted to match observed output, and
`PARITY_ROWS` was not touched — changing the fixture would move the ground under every other test
in the file.

- **Removing the knowledge-time clause.** The leaked late arrival is row 8 at `step = 398`, but the
  1h window at the step-400 cutoff is `[399, 399]`, so 1h cannot move at all; the leak lands in 24h
  (`222.22 + 33.33 + 8888.88 + 500.50 = 9644.93`) and 168h
  (`1111.11 + 9999.99 + 222.22 + 33.33 + 8888.88 + 500.50 = 20756.03`). The assertions moved to
  those two windows, and the unchanged 1h value is now asserted explicitly, because it is the datum
  that distinguishes a bounded leak from a smeared one. The already-passing
  `test_tightening_knowledge_time_breaks_parity` independently implies the same 1h membership.
- **Deleting the FILTER lower bound.** The expected leak set omitted row 3 (`step 231`, `4444.44`)
  — the one fixture row that only that lower bound was guarding, one single step outside the 168h
  bound. Corrected to
  `7777.77 + 4444.44 + 1111.11 + 9999.99 + 222.22 + 33.33 + 500.50 = 24089.36`, with the delta
  against the frozen cutoff vector corrected to `7777.77 + 4444.44 = 12222.21`.
- **Admitting same-step rows.** With the join's step bound gone, neither join carries a self-join
  guard, so the cutoff row joins to itself and contributes its own `current_amount`: 1h becomes
  `500.50 + 3333.33 + 0.01 = 3833.84`, not the two-row figure the previous test asserted. 24h and
  168h were recomputed the same way.

### 5. A comment in production that was false

`src/pit_fintech/models/paysim_training.py:557-562` claimed the join was a "widest-window prune
only" and that eligibility "lives entirely in the FILTER predicate". The join immediately below it
carries the event-time upper bound `c.step - 1`, which is half of the eligibility rule and the
thing that actually keeps same-step rows (and `c`'s own row) out. Someone acting on the old comment
could have "cleaned up" the join into a pure prune and silently removed a layer of defense. Comment
prose only: no SQL clause, literal or predicate was changed, so no training metric or checksum can
move as a result of this edit.

### 6. Real-Silver fixture builder wiring

`src/pit_fintech/data/paysim_fixture.py` extracts a small deterministic fixture from the real
Silver `paysim_transactions` Delta table — zero-history destination, a destination whose history
separately populates 1h/24h/168h, and a same-step pair — and scores it with the pure-Python oracle,
never with SQL: expectations computed in SQL would only compare the SQL against itself. Selection
is order-by-then-take throughout, amounts serialize as decimal strings, and the builder re-reads
what it wrote and re-scores it before returning.

Wired as `pit data build-fixture --dataset paysim` (`src/pit_fintech/cli.py:266-299`),
`Makefile:47-48` and `make.ps1:74-75`, with guards in `tests/unit/test_paysim_fixture.py` (missing
manifest and non-paysim dataset both exit 2 with an actionable message) and
`tests/integration/test_paysim_fixture.py` (runs the real path when a local manifest exists, skips
loudly with the builder's own message when it does not, because the PaySim CSV is not committed and
CI cannot produce it).

### 7. Two bugs the first real run exposed

The builder had never been executed. Running it against real PaySim Silver broke it twice, in two
different places, and neither failure was reachable by reading the code alone.

**Bug 1 — the destination picker could not back out of a bad choice.** `_pick_rich_destination`
committed to a single destination on a loose criterion (`count(*) >= 5` plus a 168-step span), and
`_pick_rich_cutoff_step` then applied a strictly harder one — a cutoff step with a prior row in
each of three disjoint offset bands — and raised when the chosen destination failed it. There was
no step back to the next candidate, so one unlucky first pick killed the build:

```text
RuntimeError: destination C1000004940 never reaches a cutoff step where all three history
windows are simultaneously distinguishable
```

The two criteria were not even nested. `span >= 168` is stricter than the bands need — the
furthest band starts at offset 25 — while `count(*) >= 5` plus that span still admits
destinations no band arrangement can satisfy.

What was deliberately **not** done: the three-band criterion was not relaxed. Without a prior row
in each of `[1,1]`, `[2,24]` and `[25,168]` step offsets, the 1h/24h/168h windows can return equal
counts and equal sums, and a swapped window or an off-by-one at a window bound would pass the
fixture unnoticed. Relaxing the bands would delete the reason the rich destination exists.
Instead:

- `_distinguishing_offset_bands()` derives the bands from `PAYSIM_WINDOW_STEPS` once; both the SQL
  and the Python confirmation read that single definition, so the two cannot drift apart;
- `_rich_candidate_destinations()` pushes the exact band predicates into SQL as a self-join bounded
  to `[1, 168]` step offsets, prefiltered by the two conditions that are genuinely *necessary* (one
  prior row per band plus the cutoff row itself, and a span of at least 25) so the prefilter can
  never drop a destination that would have qualified, and returns candidates ordered by
  `destination_entity_id`;
- `_pick_rich_destination_cutoff()` walks those candidates in that fixed order and takes the first
  one `_first_distinguishing_cutoff_step()` confirms in Python; the old raise became a `None`
  return, so a failed candidate now costs the next candidate rather than the build;
- `RICH_CANDIDATE_LIMIT = 8` caps the walk deterministically. The number is a judgment call, not a
  derivation: the SQL already applies the exact criterion, so candidate one should always pass, and
  the remaining slack exists only to survive a SQL/Python disagreement;
- both failure messages now report how many candidates were walked and why each was rejected, and
  one of them states outright that a SQL/Python disagreement is a bug in one of the two rather than
  a reason to widen the bands.

Cost: at most three passes over the 6,362,620-row table (the group-by, the join narrowing, and one
scan that fetches every candidate's rows at once), plus a self-join bounded by per-destination row
counts. No Python loop walks millions of rows.

**Bug 2 — the integration test asserted an equality that must never hold.**
`tests/integration/test_paysim_fixture.py` asserted
`{event.source_row_number for event in events} == set(expected)`. Those two sets are not allowed to
be equal. `select_paysim_fixture_events` fetches *every* row of the chosen destinations, because
history is unfiltered by transaction type (`_fetch_all`/`_fetch_window` filter on destination
only), while `compute_paysim_feature_vectors` emits a vector only for rows in scoring scope
(`scoring_scope_only=True` at `features/paysim_reference.py:461`, `in_scoring_scope` at
`features/paysim_reference.py:336-347`). The expectation file is a proper subset of the source file
by construction: that is the design, not a defect.

The builder's own `_verify_round_trip` cannot catch drift here — it applies the same scoring-scope
filter to both sides (`data/paysim_fixture.py:436`), so it stays green whatever the history rows
do. That is why it passed while the integration lane failed, and it is why the integration test is
the only place the two populations are pinned against each other.

The assertion was replaced by three stricter ones, not by a looser one:

- `set(expected) == in_scope` — the expectation keys are exactly the in-scope source rows;
- `set(expected) < all_row_numbers` — a proper subset, so the source file is genuinely wider;
- `assert history_only` — the fixture must carry at least one out-of-scope history row, since a
  fixture without history rows could not expose a window bug at all.

The derivation is written into a comment beside the assertions so the next reader does not have to
reconstruct it. The first assertion has a stated limitation, recorded under "Known gaps".

## Files added or changed

- `src/pit_fintech/features/paysim_reference.py` (new) — the pure-Python PaySim oracle
- `tests/temporal/test_paysim_oracle_sql_parity.py` (new) — the oracle/SQL parity lane
- `src/pit_fintech/data/paysim_fixture.py` (new) — real-Silver fixture extraction and scoring;
  destination selection rewritten as a deterministic candidate walk (section 7, bug 1)
- `tests/unit/test_paysim_fixture.py` (new) — CLI guards for `build-fixture`
- `tests/integration/test_paysim_fixture.py` (new) — real-Silver path or a loud skip; the
  events-vs-expected assertion corrected to containment plus an exact account of the gap
  (section 7, bug 2)
- `data/fixtures/paysim_temporal_cases.jsonl`, `data/fixtures/paysim_expected_features.json`
  (generated) — first written on disk by this milestone's real run
- `src/pit_fintech/cli.py` — new `data build-fixture` command
- `Makefile`, `make.ps1` — `build-fixture` target on both runners, plus the help entry
- `src/pit_fintech/models/paysim_training.py` — comment prose only (lines 557-562)
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Verification state

### First pass, before the builder had ever run

Project owner ran the following on 2026-08-03, in this order:

```text
.\make.ps1 format
```

Result: `uv run ruff check --fix`: All checks passed! `uv run ruff format`: 1 file reformatted,
52 files left unchanged. (The output does not name the reformatted file.)

```text
.\make.ps1 lint
```

Result: `uv run ruff check`: All checks passed! `uv run ruff format --check`: 53 files already
formatted.

```text
.\make.ps1 test-unit
```

Result: 41 passed in 1.97s, up from 39 at M027/M028 — the CLI guards in
`tests/unit/test_paysim_fixture.py`.

```text
.\make.ps1 test-temporal
```

Result:

```text
uv run pit data sample:
  validated 7 canonical events from 8 rows
  snapshot: synthetic-temporal-v1:1ef70772400a1d8e
  parquet: data/fixtures/temporal_cases.parquet
uv run pytest -q -m temporal tests/temporal:
  73 passed in 4.52s
```

Up from 47 at M027/M028; the parity module is the whole of that increase. The `pit data sample`
prerequisite regenerated the synthetic fixture and reported the same snapshot id
`synthetic-temporal-v1:1ef70772400a1d8e` as M028, so the synthetic ground truth is unchanged by
this milestone.

At that point `pit data build-fixture` had never been executed on any dataset, neither fixture file
existed on disk, and the integration lane had not run. Section 7 records what happened when it did.

### Second pass, after the section 7 fixes

Re-run by the project owner on a machine holding PaySim Silver. Everything below is workspace
output; nothing here is inferred.

```text
.\make.ps1 lint
```

Result: `ruff check`: All checks passed! `ruff format --check`: 53 files already formatted.

```text
.\make.ps1 test-unit
```

Result: 41 passed.

```text
.\make.ps1 test-temporal
```

Result: 73 passed.

```text
uv run pytest -q -rs -m integration tests/integration/test_paysim_fixture.py
```

Result: 1 passed. This is the first execution of the builder's success path — extraction, oracle
scoring, file write and the internal round-trip check — and the first execution of the integration
lane in this milestone. The CLI guards in the unit lane still cover only the two failure paths
(no manifest, wrong dataset); the success path is now covered here instead of nowhere.

```text
.\make.ps1 build-fixture
```

Run twice, independently. Both runs reported 15 source rows, and both produced identical files:

| File | SHA-256 |
|---|---|
| `data/fixtures/paysim_temporal_cases.jsonl` | `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` |
| `data/fixtures/paysim_expected_features.json` | `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B` |

Two independent runs, byte-identical output. That is the determinism evidence, and it is what
order-by-then-take on unique keys, integer-only selection aggregates and decimal-string amount
serialization were built for.

### What the extracted fixture actually contains

15 source rows: 11 in scoring scope, each carrying a vector, and 4 history-only rows with no
vector. Three destinations, one per scenario:

| Destination | Role | Steps present |
|---|---|---|
| `C1000022185` | rich — separately populates 1h/24h/168h | 42, 138, 155, 157, 159, 177, 178 |
| `C1000004940` | same-step pair | two rows at step 303: `4149232`, `4149878` |
| `C100003532` | zero history | one row at step 397 |

The 4 history-only rows are `861131` (step 42), `1357635` (step 138), `1701770` (step 159) and
`4149878` (step 303). All four are `CASH_IN` to a `CUSTOMER` destination: they leave scoring scope
on `transaction_type`, never on destination kind. That is the intended shape — history counts
regardless of type (`features/paysim_reference.py:341-342`), so these rows feed the window
aggregates of other rows while never being scored themselves. It also fixes the same-step pair's
roles: `4149878` is the non-scorable half, so `4149232` is the row whose vector must exclude its
own step-303 neighbour.

## Known gaps and next steps

- **`set(expected) == in_scope` is not an independent derivation.** The integration test computes
  `in_scope` with the same `in_scoring_scope` the builder uses, so if the scope definition moved,
  both sides would move together and the assertion would stay green. What it does lock is that the
  file on disk matches the contract, and `assert history_only` separately stops the fixture from
  degenerating into in-scope rows only. Making it genuinely independent would mean restating the
  scoped transaction types literally in the test, duplicating the contract in a second place; that
  trade has not been taken.
- **Nothing drives the SQL engines against the extracted rows yet.** The parity lane still runs on
  the hand-built `PARITY_ROWS` only. The 15 real-Silver rows are scored by the oracle and checked
  for internal consistency, but no test yet feeds them to `features/paysim_recipient.py` or
  `models/paysim_training.py`. Closing that is the natural next step and the reason the fixture
  exists.
- **Determinism is shown on one machine.** Two independent runs in the project owner's workspace
  agree byte for byte. A different core count or a different DuckDB build has not been tested —
  the same limitation M027 recorded for `vector_checksum`.
- **The FILTER half of the same-step policy is uncovered.** By construction, no mutation of
  `_prior_window_predicate` alone can fail on either engine. The lane says so in the docstring of
  `test_same_step_filter_mutation_alone_is_masked_by_the_join`; it is a coverage limitation, not a
  correctness defect, and it is recorded so nobody reads a green lane as proof of the FILTER.
- **Nothing is committed.** No commit hash exists for this milestone; every command above was run
  against the working tree.
- **`train` was not re-run.** No training metric, `vector_checksum` or fingerprint from
  M019/M026/M027 is restated here, because nothing in this milestone changed a value-bearing SQL
  clause — only test code, new modules, CLI wiring and comment prose.
- **There is no e2e lane.** Nothing in this repository runs offline extraction through to a served
  score; that lane does not exist yet and is not implied by anything above.
- **Sprint 2 T1 has not started.** `feature_repo/` still holds exactly two placeholder files
  (`__init__.py`, `feature_specs.py`). No Feast registry, feature view or materialization exists.
- Next: (1) drive the two DuckDB engines against these 15 extracted rows so the real-Silver fixture
  becomes parity evidence rather than oracle-only evidence; (2) decide whether a mutation aimed at
  the join clauses belongs in the lane permanently or whether the double guard should be collapsed
  to one enforced place so that a single-clause mutation regains teeth.
