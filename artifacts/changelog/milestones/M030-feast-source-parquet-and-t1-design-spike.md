# M030 — ADR-006 Feast source Parquet and the T1 design spike

- Date: 2026-08-03
- Status: verified within the scope that was run — lint, `build-fixture` with a two-run
  byte-identical determinism check, the fixture integration lane, and a throwaway Feast spike that
  answered four design questions. **T1 is not done**: see "Known gaps and next steps".
- Commit: pending — nothing in this milestone is committed yet, so no hash exists to record

## Scope and acceptance

Sprint 2 T1 needs a Feast `FileSource`, and ADR-006 decision 1 froze the only way PaySim can
supply one: derived `event_timestamp`/`created_timestamp` columns, because Silver carries hour
ordinals and Feast validates against real timestamp columns. ADR-006 decision 1.7 assigns the
derivation to the Gold projection built by T2. The project owner decided not to wait for T2, and
to take the first step of T1 — the data source only — by extending the existing fixture builder.

This milestone is that first step, plus the design reconnaissance that had to happen before any
registry code is written. Acceptance:

1. `pit data build-fixture` emits a Parquet rendering of the same rows it already emits as JSONL,
   carrying every Silver column plus the two ADR-006 derived timestamp columns, typed so Feast
   `FileSource` validation accepts them;
2. that Parquet is byte-reproducible across independent runs;
3. neither the selected rows, the oracle path, nor the expected-vector file moves;
4. the open questions that could invalidate the T1 design are measured against the installed
   Feast, not assumed.

Item 4 turned out to matter more than items 1-3. Two of its answers change the T1 design.

## What changed and why

### 1. The Feast-facing Parquet (`data/paysim_fixture.py`)

`build_paysim_temporal_fixture` now writes a third file,
`data/fixtures/paysim_temporal_cases.parquet`, from the same selection that produces the JSONL and
the expected vectors. `_fetch_feast_source_table` pulls the selected rows as Arrow with every
column of `PAYSIM_SILVER_TRANSACTION_COLUMNS` — names and types taken straight from Silver rather
than retyped, so the Parquet cannot drift from the table it was extracted from — and appends
exactly two columns, `event_timestamp` and `created_timestamp`, at
`pa.timestamp("us", tz="UTC")`, the same Arrow type the lakehouse writer already uses.

`PaySimFixtureSelection` (a `NamedTuple`) now carries the selection in two shapes: `events`, the
seven columns the frozen contract may read, and `source_table`, the Feast-facing view. The second
is a presentation of the first and never an input to it. No feature value is computed from the
Parquet, and `_write_fixture_files` still derives the expected vectors from `events` alone.

`_verify_round_trip` re-reads the Parquet and fails the build if its `source_row_number` list
differs from the JSONL, or if either derived column is not the UTC timestamp type — so a drift
stops the builder rather than waiting for the integration lane.

### 2. `PAYSIM_FEAST_EPOCH_0` lives in the contract module

ADR-006 decision 1.7 requires "exactly one implementation of the mapping, expressed once, from the
same contract module". `features/paysim_specs.py` is that module — it already holds every frozen
version string, the entity and the scoring scope — so the anchor and the map went there:

```python
PAYSIM_FEAST_EPOCH_0 = datetime(2020, 1, 1, tzinfo=UTC)

def paysim_step_to_timestamp(step_ordinal: int) -> datetime:
    return PAYSIM_FEAST_EPOCH_0 + timedelta(hours=int(step_ordinal))
```

The Unix literal `1577836800` appears nowhere in the codebase; every consumer calls the function.
The constant is named `PAYSIM_FEAST_EPOCH_0` rather than a bare `EPOCH_0` so a reader cannot
mistake it for a PIT time axis: the comment beside it restates that eligibility, window bounds and
the replay tie-break stay on `(step, source_row_number)`.

The mapping is computed in **Python, not SQL**. A DuckDB `TIMESTAMPTZ` expression is rendered
against the session time zone, which would make the output depend on the machine that produced it
— fatal for a reproducibility project. This was a deliberate choice, recorded in the function's
docstring.

### 3. `to_arrow_table` instead of `.arrow()` / `fetch_arrow_table`

The first real run failed with
`AttributeError: pyarrow.lib.RecordBatchReader object has no attribute combine_chunks`. The
compiled signatures in the installed DuckDB 1.5.4 explain it:

| Method | Returns |
|---|---|
| `arrow(self, rows_per_batch=1000000)` | `pyarrow.lib.RecordBatchReader` |
| `fetch_arrow_table(self, rows_per_batch=1000000)` | `pyarrow.lib.Table` (deprecated) |
| `to_arrow_table(self, batch_size=1000000)` | `pyarrow.lib.Table` |

`fetch_arrow_table` fixed the crash but emitted a `DeprecationWarning`. Checked under
`-W error::DeprecationWarning`: `fetch_arrow_table` raises, `to_arrow_table` runs clean and
returns a `Table`. The final call is `to_arrow_table`, which is also what the repo already used at
`src/pit_fintech/features/paysim_recipient.py:376` — an existing precedent an earlier search had
missed.

`combine_chunks()` was **kept**, not dropped to make the error go away. `to_arrow_table` accepts a
`batch_size` that can split the result, so combining guarantees one chunk, which means the Parquet
row-group boundaries follow the row count alone and never DuckDB's batching. That is a determinism
property, and it is why the crash could not be fixed by deleting the call.

### 4. The T1 design spike (`scripts/spike_feast_t1.py`)

A throwaway probe, not production code: it imports nothing into `src/`, writes nothing into
`feature_repo/` or `data/fixtures/`, builds everything inside a `tempfile.mkdtemp()` directory and
removes it in a `finally` block. Each of its four questions is wrapped separately so a failure
prints its traceback and the run continues — an unanswered question is itself a finding.

The feature table it builds is computed by the **SQL engine**, importing `_prior_window_predicate`
from `features/paysim_recipient.py` rather than restating the window logic. That choice is the
whole point: comparing an oracle-built table against the oracle would be a tautology. An SQL-built
table compared against the oracle is two independent derivations.

## The four spike results

### Q1 — the feature table has no timestamp tie, and that is a coverage hole

The eleven in-scope rows sit at steps 155, 157, 161, 177, 178, 180, 207, 212, 299, 303 and 397 —
eleven distinct steps, no repeats. The 4 history-only rows are all `CASH_IN`.

So the same-step pair at step 303 does **not** reach the feature table: `4149232` (`CASH_OUT`) is
the in-scope cutoff and `4149878` (`CASH_IN`) is history-only. An earlier report called the tie the
largest integration risk for T1; that was wrong, and the project owner's counter-argument was
right. The tie does not block T1.

It is instead a **coverage hole**, and a pointed one: the fixture was deliberately built to carry
a same-step pair, and the feature projection drops it. Whatever Feast does with a tie, the T1 lane
as currently shaped would never find out.

### Q2 — Feast retrieval matches the oracle on every field

`get_historical_features` returned 11 rows and agreed with `paysim_expected_features.json` on
every field of every row, 0 differences. Because the retrieved table was built by the SQL engine
and the expectations by the pure-Python oracle, this is two independent derivations agreeing —
not a file compared against itself.

This is the strongest available evidence that the ADR-006 mapping survives a Feast timestamp join:
Feast joins on `event_timestamp`, not on `step`, and the vectors still came back right.

### Q3 — Feast collapses a tie to one row, but the project does not choose which

Given two rows at the same entity and the same `event_timestamp` with markers 111.0 and 222.0,
Feast returned exactly one row, marker 111.0. No fan-out: one entity request did not become two
training rows, which was the worst case and it did not happen.

But **which** row wins is not determined by anything the project controls. This is exactly what
ADR-006 decision 1.4 warned about — hour-resolution timestamps cannot express the
`(step, source_row_number)` tie-break, because every row in the same `step` maps to the same
instant. Recorded here as observed behaviour of Feast 0.65.0, not as a contract.

### Q4 — the registry blob is not a stable identity

A no-op second `apply` changed the digest:

```text
before: 73b76be0a95b5ef8fe393ac29c43de78a1632db5e41fb95d7ec8a0e56b7eb349
after:  67ddb99358774a7a487f4e79eb0c03501c3fa6527baa1f89e098c53b156bdf16
```

Both the registry file SHA-256 and the serialized-proto SHA-256 moved, because the registry proto
carries `last_updated` timestamps.

## Two findings with design consequences

These are the reason the spike was worth running, and both change T1.

### Finding 1 — Feast does not compute window aggregates, so the source must be precomputed

`.venv/Lib/site-packages/feast/aggregation/__init__.py:17` states it outright:

> NOTE: Feast-handled aggregations are not yet supported. This class provides a way to register
> user-defined aggregations.

Confirmed at the store layer: `aggregation` does not appear anywhere in
`feast/infra/offline_stores/duckdb.py` or `file_source.py` — only in the `mongodb` and `ray`
contrib stores. A plain `FeatureView` does not even accept an `aggregations` argument;
`BatchFeatureView` and `StreamFeatureView` accept one but only store it. `OnDemandFeatureView`
transforms row-wise over already-retrieved inputs and cannot look back over history.

**Consequence.** The Parquet this milestone ships — every Silver column plus 2 derived timestamps,
15 rows — is a *source* table, not a *feature* table. It cannot be what a `FeatureView` reads,
because none of the contract's history fields exist in it and Feast will not compute them. T1
needs a second, precomputed table holding the twelve contract fields, one row per cutoff. The
guide already said so and it was misread: guide §3.2 line 117 points the `FileSource` at the
"pre-decision Gold Delta table", and §4 line 148 defines `pre_decision_features` as
"aggregate ngay trước từng transaction" — a T2 artifact. Deciding not to wait for T2 does not
remove that dependency; it moves the obligation to produce the table into T1.

### Finding 2 — the guide §3.3 checksum must come from definitions, not from the registry

Guide §3.3 binds `feast plan/apply -> registry checksum -> feature_service_version`, and guide
§3.4 makes "`feast apply` idempotent" a G1 acceptance criterion. Q4 shows that a checksum taken
over the registry artifact moves on a no-op apply, for a reason that has nothing to do with the
definitions. If G1 measured idempotence that way, it would fail permanently for a meaningless
reason, and the natural response — relaxing the criterion — would destroy a real gate.

**Consequence.** The registry checksum has to be computed over the canonical definitions
(entity, source, feature view, feature service, field names and order), the way
`paysim_feature_contract_checksum` already computes the contract checksum, and never over the
registry blob. No such function exists in `src/` today.

## Files added or changed

- `src/pit_fintech/features/paysim_specs.py` — `PAYSIM_FEAST_EPOCH_0` and
  `paysim_step_to_timestamp`, the single implementation of the ADR-006 mapping
- `src/pit_fintech/data/paysim_fixture.py` — `PARQUET_PATH`, `_fetch_feast_source_table`,
  `PaySimFixtureSelection`, Parquet write and Parquet round-trip check
- `src/pit_fintech/cli.py` — `build-fixture` table gained a `parquet path` row
- `tests/integration/test_paysim_fixture.py` — new test pinning the Parquet against the JSONL
  rows, the Silver column set, the UTC timestamp types and the ADR-006 map; every previous
  assertion left untouched
- `scripts/spike_feast_t1.py` (new) — throwaway T1 design probe
- `data/fixtures/paysim_temporal_cases.parquet` (generated) — first written by this milestone
- `docs/feature-store/sprint-2-implementation-guide.md` — 14 stale spots corrected, 2 new
  sections added (see "Guides corrected" below)
- `docs/feature-store/sprint-3-implementation-guide.md` — 1 stale spot corrected
- `artifacts/changelog/PROJECT_STATUS.md`, `artifacts/changelog/CHANGELOG.md`, this log

## Guides corrected

Both findings above are worthless if the guide keeps telling the next reader to build
`card_entity` and `fraud_scoring_v1` against a raw source. The two Sprint guides were corrected in
place, and every correction is recorded inside each guide under a `## Nhật ký hiệu chỉnh` section
placed at the top of the file, quoting the original wording alongside the replacement and the ADR
or milestone that justifies it. Nothing was deleted silently: this project exists to demonstrate
lineage, so erasing the original plan would destroy the thing being demonstrated.

`docs/feature-store/sprint-2-implementation-guide.md` — 14 corrections: `feature spec v1` to
`paysim-fraud-recipient-v2` (§1); `card_entity` to `destination_entity_id` (§3.2); the `FileSource`
line to a precomputed table (§3.2); "history feature v1" to the twelve `paysim-fraud-recipient-v2`
fields in `PAYSIM_MODEL_FEATURE_ORDER` (§3.2); `fraud_scoring_v1` to `paysim-fraud-scoring-v2` in
three places (§3.2, §3.4, §6.4); the registry checksum rule (§3.3); the acceptance criteria
(§3.4, two lines); `pre_decision_features` now stating it is also T1's feature source (§4.0);
"full IEEE-CIS" to the frozen `paysim1:16910f90577b0d98` snapshot (§4.1); the training entity
dataframe columns from `transaction_id`/`card_entity_id`/`ordered_event_timestamp`/`label_is_fraud`
to `source_row_number`/`destination_entity_id`/`event_timestamp`/`isFraud` (§6.1); and the G1 row
of the Go/No-Go table (§13). Four of those were found by scanning the whole file, not from the
known list: §1, §4.1, §6.1 and §6.4.

Two sections are **new**, not corrections, and carry Finding 1 and Finding 2 into the document
that the next person actually follows: §3.2.1 (Feast does not compute window aggregates, so the
feature source must be precomputed, and it must be built by the SQL engine or G1 becomes a
tautology) and §3.3.1 (the registry blob is not a stable identity, with both digests recorded).

`docs/feature-store/sprint-3-implementation-guide.md` — 1 correction: "chỉ có giá trị trên
IEEE-CIS" to the frozen PaySim snapshot (§4.1). That is the only stale spot in the file; Sprint 3
discusses ablation, monitoring and cloud at a level that does not name an entity or a feature
service, so it never carried the `card_entity`/`fraud_scoring_v1` errors.

`docs/adr/` was **not** touched: an ADR is a frozen decision and changing one requires a new ADR,
not an in-place edit.

Deliberately left unchanged as historical records, each stating its own reason in the report to
the project owner: `docs/reports/paysim-feature-contract-v1.md` (ADR-006 line 184 explicitly keeps
it at v1), `docs/reports/sprint-1-completion-report.md` (state at Sprint 1 close),
`docs/feature-store/point-in-time-feature-store-proposal.md` (the original research proposal that
ADR-002 exists to supersede) and `docs/feature-store/sprint-1-implementation-guide.md` (plan of a
completed sprint; its `card_entity_id` at line 206 is not even stale, because the synthetic
fixture genuinely uses that column). `docs/data-access.md` and
`docs/reports/project-self-review-checklist.md` mention IEEE-CIS correctly, as the ADR-002 optional
alternative, and needed no change.

## Verification state

Run by the project owner on 2026-08-03. Everything below is workspace output.

```text
.\make.ps1 lint
```

Result: `ruff check`: All checks passed! `ruff format --check`: 54 files already formatted (up
one, the spike script).

```text
.\make.ps1 build-fixture
```

Prints five rows now, including `parquet path`. Run twice, independently. Both runs reported 15
source rows and produced identical files:

| File | SHA-256 |
|---|---|
| `paysim_temporal_cases.jsonl` | `5DD9228FE5B6A2430EC7ABC23E978219F171D1F1316D364633A77B72839DF5AE` |
| `paysim_expected_features.json` | `DF9846F7EB299799425E7FF204202884498B7F7A2BA31AE1BBE3A4922ED9C15B` |
| `paysim_temporal_cases.parquet` | `6935B7EE1C0EB4133CA1EF07A11686993329FD119DB3DB4EE6A282FB997153A5` |

The first two are unchanged from M029, which is the point: the Parquet is a second presentation of
the same selection, and adding it moved neither the chosen rows nor the oracle output. The Parquet
hash is identical across the two independent runs — that is the determinism claim for the new file.

```text
uv run pytest -q -rs -m integration tests/integration/test_paysim_fixture.py
```

Result: 2 passed.

```text
uv run python scripts/spike_feast_t1.py
```

Result: all four questions answered, none unanswered. Q1 GOOD, Q2 GOOD, Q3 one row with no
fan-out, Q4 PROBLEM. Details above.

No `DeprecationWarning` remains from project code. One warning still comes from
`ibis/backends/duckdb/__init__.py:332`, a third-party library reached through the Feast DuckDB
offline store; it is not ours to fix and is recorded rather than suppressed.

## Known gaps and next steps

- **T1 is not done.** This milestone delivered the data-source step and the design
  reconnaissance, nothing else.
- **`feature_repo/` is untouched** and still holds exactly 2 placeholder files (`__init__.py`,
  `feature_specs.py`). No `Entity`, `FeatureView`, `FeatureService` or `feature_store.yaml` is
  committed anywhere in the repository.
- **There is no precomputed feature table on disk.** The eleven-row table that Q2 retrieved was
  built inside the spike, in memory, into a temporary directory that was deleted on exit. Nothing
  reproduces it today, and per Finding 1 it is required before a `FeatureView` can exist.
- **There is no registry checksum in `src/`.** Per Finding 2 it must be derived from the
  definitions; no such function has been written.
- **There is no G1 test lane.** The spike is a throwaway script, not a test; nothing in
  `tests/` exercises Feast.
- **G1 does not pass.** Of the three acceptance criteria in guide §3.4, only the first
  (historical retrieval matching the fixture oracle) has been measured, and only inside the spike.
  The second (`feast apply` idempotent) cannot be measured the way the guide implies until the
  checksum moves off the registry blob; whether apply is *semantically* idempotent is CHUA XAC
  DINH. The third (the feature service resolving the ordered feature names) has not been attempted
  — no `FeatureService` was created.
- **The same-step pair is not exercised by Feast.** Q1's coverage hole. If T1 wants the fixture's
  same-step case to mean anything at the Feast layer, the feature projection has to keep a tie, or
  the fixture needs a second scenario where two *cutoffs* share a step.
- **Tie resolution is observed, not controlled.** Q3's marker 111.0 is Feast 0.65.0 behaviour on
  one run. It must not become a contract, and no code may depend on it.
- **Determinism is shown on one machine.** Two independent runs in the project owner's workspace
  agree byte for byte for all three fixture files. A different core count or a different pyarrow
  or DuckDB build has not been tested — the same limitation M027 and M029 recorded.
- **Nothing is committed.** No commit hash exists for this milestone; every command above ran
  against the working tree.
- **`train` was not re-run.** No training metric, `vector_checksum` or fingerprint from
  M019/M026/M027 is restated here: nothing in this milestone changed a value-bearing SQL clause.
- Next: (1) build the precomputed pre-decision feature table as a real, reproducible artifact via
  the SQL engine, deciding explicitly whether it belongs to T1 or waits for T2's Gold; (2) write
  the definitions-based registry checksum; (3) turn the spike's Q2 into a real G1 test lane; (4)
  decide how the same-step case reaches the Feast layer.
