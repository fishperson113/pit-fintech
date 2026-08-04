# M031 — Feast `feature_repo/`, definitions checksum, and the G1 pytest lane

- Date: 2026-08-04
- Status: **verified within the scope re-run recorded in `verify.md`** — lint, `test-unit`,
  `test-temporal`, `test-integration` (including the new G1 lane), and a two-run parquet hash
  check. **Not committed.**
- Commit: pending — nothing in this milestone is committed yet, so no hash exists to record.

## Scope and acceptance

M030 closed the T1 design reconnaissance but left four gaps open: no precomputed feature table on
disk, no `feature_repo/` objects (`Entity`/`FileSource`/`FeatureView`/`FeatureService`/
`feature_store.yaml`), no definitions-based registry checksum in `src/`, and no G1 test lane. This
milestone closes all four, done as three pieces of work in one session:

1. a precomputed pre-decision feature table written to disk by the SQL engine;
2. real `feature_repo/` Feast objects, applied with `feast apply` against the real installed Feast;
3. a definitions-based registry checksum function in `src/`, and a pytest G1 lane that exercises
   the real `feature_repo/` (not a copy, not a spike script).

Acceptance is guide §3.4's three G1 criteria, each measured by a real `pytest` test:

1. Feast historical retrieval on the PaySim fixture matches the oracle's expected vectors.
2. `feast apply` is idempotent, measured by the **definitions** checksum (guide §3.3.1), not the
   registry blob.
3. `paysim-fraud-scoring-v2` resolves all 12 fields in contract order.

All three are met (**DAT**) by test evidence re-run independently and recorded in `verify.md`.
"DAT" is used strictly for criteria backed by a passing `pytest` test in this run; where a number
below could not be traced to a passing test or one of the four drop files this milestone was
written from, it is marked "CHUA DO DUOC" (not yet measured) rather than DAT or FAIL.

## What changed and why

### 1. Precomputed feature table on disk

`pit data build-fixture --dataset paysim` now writes a fourth file,
`data/fixtures/paysim_feature_table.parquet` — 11 rows, 16 columns, 6,438 bytes — closing M030
Finding 1 (Feast does not compute window aggregates, so the `FileSource` a `FeatureView` reads must
already hold the 12 contract fields; the M030 Parquet was a source table, not a feature table).

The table is computed by the **SQL engine**
(`paysim_pre_decision_feature_sql()`, new in `features/paysim_recipient.py`, reusing the existing
`_prior_window_predicate` and `PAYSIM_AMOUNT_DECIMAL_TYPE` rather than restating window logic),
never by the oracle — comparing an oracle-built table against the oracle would be a tautology.
Columns: `destination_entity_id`, `event_timestamp`, `created_timestamp`, the 12
`PAYSIM_MODEL_FEATURE_ORDER` fields in contract order, and a trailing `source_row_number` (needed
because the expected-vector file is keyed by it and no other contract column identifies a row).
`step`/`knowledge_step` are computed in SQL but dropped from the written file — they are ordinals,
not contract fields, and leaving them in would invite a consumer to join on them instead of on the
Feast-validated columns.

Verification inside the builder (`_verify_feature_table`) re-reads the Parquet and raises if it
disagrees with `paysim_expected_features.json`; this ran clean on both runs below. An independent
re-check (`tests/integration/test_paysim_feature_table_pins_the_schema_feature_repo_binds_to`,
appended to `tests/integration/test_paysim_fixture.py`) repeats the comparison from disk.

Two independent `build-fixture` runs (the file was moved out of the repo between runs so the
second run had to regenerate it, not merely leave an old file in place) produced byte-identical
output:

| File | SHA-256 |
|---|---|
| `paysim_feature_table.parquet` | `A6E6B9B00FA62966E19397D9C0A7737FCB48D8C9C81A5C7300CCE047B3B997C5` |

Confirmed again by the independent re-run in `verify.md` (`Get-FileHash`): same hash. The three
pre-existing fixture files (`paysim_temporal_cases.jsonl`, `paysim_expected_features.json`,
`paysim_temporal_cases.parquet`) were confirmed unchanged from M030 — adding the feature table did
not move the selection or the oracle output.

Field-by-field comparison against the oracle: **11 rows × 12 fields = 132/132 exact matches, 0
differences**, compared with `==` (not `float_tolerance`) because both sides are round-trips of the
same `DECIMAL(18,2)` value through `double`.

Files changed: `src/pit_fintech/features/paysim_recipient.py`,
`src/pit_fintech/data/paysim_fixture.py`, `src/pit_fintech/cli.py` (`build-fixture` table gained
`feature rows` / `feature table path` rows), `tests/integration/test_paysim_fixture.py`.

### 2. Real `feature_repo/` objects and a real `feast apply`

Two new files: `feature_repo/feature_store.yaml` (`local` profile only — DuckDB offline store +
SQLite online store; the guide §3.1 `hosted` profile with Upstash Redis is Sprint 3 scope and is
not defined) and `feature_repo/definitions.py` (`Entity`, `FileSource`, `FeatureView`,
`FeatureService`, every name/dtype/version string imported straight from
`features/paysim_specs.py`, never re-typed).

Deliberately **not** included, and recorded as a scope narrowing rather than a gap: `PushSource`
(the online-write path fed by the replay/materializer, T5 — guide §3.2 mentions it but the T1
contract for this piece did not ask for it) and an `OnDemandFeatureView` split for the three
request-time fields (T7/FastAPI scoring scope; the three fields are served here as ordinary batch
fields, which is what the precomputed table actually contains).

`feast apply`, run from inside `feature_repo/` against the real installed Feast 0.65.0, succeeded:

```
Created entity destination_entity_id
Created feature view paysim_fraud_recipient_v2
Created feature service paysim-fraud-scoring-v2
Created sqlite table pit_fintech_paysim_fraud_recipient_v2
```

A second `apply` reported "No changes to infrastructure" (no sqlite table recreated) but the
registry proto's `meta.created_timestamp`/`last_updated_timestamp` still moved — this restates
M030 Finding 2 on the real `feature_repo/`, not just the throwaway spike.

Files changed: `feature_repo/feature_store.yaml` (new), `feature_repo/definitions.py` (new).

### 3. Definitions-based registry checksum (`src/pit_fintech/platform/feast_registry.py`, new)

Placed in `platform/`, not `features/`: `pyproject.toml` deliberately keeps Feast out of the main
`dependencies` group so a Feast resolution failure cannot break `test-unit`/`test-temporal`, and
`features/` is the correctness-contract tier (AGENTS.md §11: "Feast is a thin registry/retrieval
contract, not the correctness oracle"). `platform/lineage.py` already holds the project's other
policy-versioned identity digest (`component_fingerprint`), so the registry checksum joins it there
instead.

`feast_definitions_payload()` / `feast_definitions_checksum()` read Feast objects by **duck
typing** (the only `from feast import ...` is inside `if TYPE_CHECKING`), so `src/` still imports
without Feast installed, and the same function accepts both module-declared objects and objects
read back from the registry after `apply` — which is what makes the idempotence measurement in §4
possible. Serialization follows `paysim_feature_contract_checksum`'s convention
(`json.dumps(..., separators=(",",":"), sort_keys=True)` then SHA-256), not `lineage.py`'s raw-byte
hashing, specifically so the payload can be printed and diffed by hand if it ever disagrees.
`FEAST_DEFINITIONS_CHECKSUM_POLICY_VERSION = "feast-definitions-checksum-v1"` is itself part of the
hashed payload.

Two Feast-internal fields are deliberately **excluded** from the payload: `FeatureView.ttl`
(`None` in the module, but reads back as `datetime.timedelta(0)` from the registry after `apply`)
and `FeatureView.entity_columns` (`[]` in the module, populated after `apply`). Including either
would make the module checksum differ from the post-`apply` registry checksum for a reason that has
nothing to do with a definitions change, defeating the whole point of the gate. This is a real
trade-off, not a free simplification: if `ttl` is later given a real materialization-window value,
a change to it will **not** move this checksum and must be gated some other way. Recorded here so
it is not mistaken for an oversight later.

Definitions checksum of the current `feature_repo/`: `d330edefbbc0d3a075b4b5f145a6d169e2aa910d39cfae33c70478289432f443`.
Confirmed stable across two independent processes and across both `feast apply` runs (module
checksum == registry-checksum-after-apply-1 == registry-checksum-after-apply-2). The registry
**blob** digest over the same two applies still moved
(`98fe137edfc372a0fc0edb9990692d0516a3d1358e54680c00f1aa13afef6287` ->
`fd09313e5b0616b75a8dabcafe96cf57efb02a1d67afdeddfcca1a66fc37e7de`), confirming M030 Finding 2 is
still live on this exact lane, not something the definitions checksum silently papered over.

### 4. The G1 pytest lane (`tests/integration/test_feast_registry_g1.py`, new, marker `integration`)

Four tests, driven by a module-scoped fixture that runs `apply_total()` — the same function the
`feast apply` CLI calls (`feast/cli/cli.py` -> `repo_operations.apply_total`) — directly against
the **real** `feature_repo/definitions.py` and `feature_store.yaml`, only redirecting the
`registry`/`online_store.path` outputs to a pytest temp dir (copying `definitions.py` itself to a
temp dir was tried first and rejected: its `PROJECT_ROOT = Path(__file__).resolve().parent.parent`
would then resolve to the temp dir, pointing `FileSource.path` at a location with no parquet file).

Results, all three G1 criteria **DAT**:

1. `test_g1_historical_retrieval_matches_the_oracle_expected_vectors` — 11 rows retrieved via
   `store.get_historical_features(...)`, 132/132 fields exact match against
   `paysim_expected_features.json`, entity-df timestamps derived independently on the test side via
   `paysim_step_to_timestamp`, so this is two independent derivations meeting, not a file compared
   with itself.
2. `test_g1_feast_apply_is_idempotent_by_definitions_checksum` — checksum computed from objects
   read back from the registry after `apply` #1 and after `apply` #2 both equal
   `d330edef...443` and equal the module checksum; the registry blob digest is separately asserted
   to **still differ** across the two applies (`98fe13...` -> `fd0931...`), a deliberate assertion
   of Finding 2 rather than something the test hides.
3. `test_g1_feature_service_resolves_twelve_fields_in_contract_order` — `[f.name for f in
   feature_view_projections[0].features] == list(PAYSIM_MODEL_FEATURE_ORDER)`, an exact list
   comparison (order matters), plus dtypes checked against `PAYSIM_FEATURE_SPECS`.
4. `test_the_g1_lane_leaves_feature_repo_registry_untouched` (a guard, not a G1 criterion) —
   SHA-256 of every `*.db` under `feature_repo/` is byte-identical before and after the lane runs,
   confirming the lane's applies stay inside its own temp registry and do not disturb the
   `registry.db`/`online.db` left in `feature_repo/` by item 2 above.

A companion unit suite, `tests/unit/test_feast_definitions_checksum.py` (9 tests, no Feast
installation required — stub objects shaped like Feast's), pins the checksum function's properties:
stable across repeated calls; changes on field-order permutation, dtype change, service-name
change, source-table change, and timestamp-column-name swap; does **not** change on
object-declaration-order permutation (the registry returns objects in its own order, which is not a
definitions change); `source.path` is normalized to a project-relative POSIX string; `ttl`/
`entity_columns` are absent from the payload.

### New Feast 0.65.0 findings not recorded in M030

- **`FeatureView.schema` (the property) loses field order; `FeatureView.features` (the list
  attribute) keeps it.** Read at `feast/feature_view.py:430`:
  `schema` is `list(set(self.entity_columns + self.features))` — a `set()`, so its iteration order
  is effectively hash-random. Confirmed empirically: printing `[f.name for f in view.schema]`
  produced an order different from `PAYSIM_MODEL_FEATURE_ORDER`. Anything needing field order
  (this lane, T4, T6, T7) must read `FeatureView.features`,
  `FeatureService.feature_view_projections[i].features`, or `PAYSIM_MODEL_FEATURE_ORDER` directly —
  never `.schema`. The checksum function and the G1 order-assertion test both read `.features`;
  `.schema` is used in one test only to assert **set** membership, with a comment explaining why.
- **`feast apply` does not read the source file at apply time.** Apply succeeded even while
  `paysim_feature_table.parquet` did not yet exist on disk (it was still being written by a
  concurrent piece of this same milestone). A gate that wants to confirm the source exists must
  check the file directly; `feast apply` succeeding is not evidence of that.
- **`FeatureView.name` must be `.isidentifier()`-safe; `FeatureService.name` does not have to be.**
  A dashed `FeatureView` name (`paysim-fraud-recipient-v2`) broke `apply()` with
  `OperationalError near "-"` because Feast uses it as a SQLite online-store table name; the
  underscored form (`paysim_fraud_recipient_v2`) works. The same dashed string as a
  `FeatureService.name` (`paysim-fraud-scoring-v2`) applies successfully, because `FeatureService`
  names are not used as SQL identifiers. Both frozen version strings (the definition version and
  the service version, ADR-006 decision 2) are additionally carried in `tags={...}` on their
  respective objects so the literal contract strings are visible in the registry even where the
  object name itself had to be reshaped.
- **`entity.join_keys` does not exist after construction; `entity.join_key` (singular) does.**
  Constructing `Entity(join_keys=[...])` is accepted, but reading `entity.join_keys` back raises
  `AttributeError` — Feast 0.65 stores the result as `entity.join_key`. The checksum payload uses
  the singular form; if an entity ever needs more than one join key, this function would need
  updating (recorded, not yet a real limitation since `PAYSIM_ENTITY` has exactly one).

All four are attributed to source-code reading and empirical runs against the installed
`feast==0.65.0` (pinned `>=0.65,<0.66` in `pyproject.toml`), not to Feast's changelog or issue
tracker — a different Feast version may not reproduce them.

## Files added or changed

| File | Status | Piece |
|---|---|---|
| `src/pit_fintech/features/paysim_recipient.py` | modified | 1 |
| `src/pit_fintech/data/paysim_fixture.py` | modified | 1 |
| `src/pit_fintech/cli.py` | modified | 1 |
| `tests/integration/test_paysim_fixture.py` | modified | 1 |
| `data/fixtures/paysim_feature_table.parquet` | new, generated | 1 |
| `feature_repo/feature_store.yaml` | new | 2 |
| `feature_repo/definitions.py` | new | 2 |
| `src/pit_fintech/platform/feast_registry.py` | new | 3 |
| `tests/integration/test_feast_registry_g1.py` | new | 4 |
| `tests/unit/test_feast_definitions_checksum.py` | new | 4 |

No file was deleted. `feature_repo/registry.db` and `feature_repo/online.db` were created as a
side effect of the real `feast apply` runs and are left in place, untracked (`.gitignore` already
covers `*.db`); the G1 lane's own guard test confirms it does not disturb them.

## Verification state

Independently re-run and recorded in `verify.md`; all numbers below are taken from that re-run, not
recomputed or estimated.

```text
git status --short
```

```
 M src/pit_fintech/cli.py
 M src/pit_fintech/data/paysim_fixture.py
 M src/pit_fintech/features/paysim_recipient.py
 M tests/integration/test_paysim_fixture.py
?? data/fixtures/paysim_feature_table.parquet
?? feature_repo/definitions.py
?? feature_repo/feature_store.yaml
?? src/pit_fintech/platform/feast_registry.py
?? tests/integration/test_feast_registry_g1.py
?? tests/unit/test_feast_definitions_checksum.py
```

```text
uv run ruff check src tests feature_repo notebooks scripts
```

Result: `All checks passed!`

```text
uv run pytest -q tests/unit
```

Result: **50 passed** (up from 41 at M030 — the 9 new checksum-property tests).

```text
uv run pytest -q -m temporal tests/temporal
```

Result: **73 passed** — unchanged from M030, as expected: nothing in this milestone touched the PIT
temporal path.

```text
uv run pytest -q tests/integration
```

Result: **11 passed** (up from 7 at M030's fixture lane — the 4 new G1 tests; includes the new
`test_paysim_feature_table_pins_the_schema_feature_repo_binds_to`).

```text
uv run pytest -q tests/integration/test_feast_registry_g1.py -v
```

Result: **4 passed** — the G1 lane in isolation, confirming the 11-passed integration total above
is not hiding a skip.

```text
Get-FileHash data/fixtures/paysim_feature_table.parquet -Algorithm SHA256
```

Result: `A6E6B9B00FA62966E19397D9C0A7737FCB48D8C9C81A5C7300CCE047B3B997C5` — matches the two build-time
runs recorded in item 1 above.

```text
Get-ChildItem feature_repo -Recurse -File
```

Result: `definitions.py`, `feature_store.yaml`, `feature_specs.py`, `__init__.py`,
`registry.db`, `online.db`, plus `__pycache__/*.pyc` — confirming both new `feature_repo/` files and
both `feast apply` side-effect databases are present on disk.

The independent verification script itself reported `PASS=8 FAIL=0` across the 8 commands above;
that count describes the verification script's own command-level bookkeeping, not a `pytest`
result, and is kept distinct from the `pytest` pass counts above to avoid conflating the two.

## Known gaps and next steps — not glossed over

- **The same-step pair still never reaches Feast.** The feature table holds 11 distinct steps (155,
  157, 161, 177, 178, 180, 207, 212, 299, 303, 397) — this is unchanged from M030 Q1/gap 4. The G1
  lane's tie-handling coverage hole from M030 is still open; nothing in this milestone added a
  second cutoff sharing a step.
- **Idempotence is measured across 2 applies inside 1 process, not across 2 separate CLI
  processes.** The G1 lane purges the imported `definitions` module from `sys.modules` between
  applies so the second read is a genuine re-read from disk, but it never crosses a process
  boundary the way running `feast apply` twice from a shell would. Whether a fresh `feast apply`
  process agrees with this in-process result is CHUA DO DUOC.
- **Determinism is shown on one machine only** — Windows 11, Feast 0.65.0, DuckDB as pinned in
  `uv.lock`. Same limitation M027/M029/M030 recorded; not re-tested here.
- **`ttl` and `entity_columns` are excluded from the checksum payload by design** (§3 above). A
  future change to either will not move this checksum. If `ttl` becomes a real
  materialization-window decision, it needs a separate gate — this one will not catch it.
- **`apply_total()` is called in-process, not through a spawned `feast` CLI subprocess.** There is
  no `feast/__main__.py`, so `python -m feast` does not work, and `shutil.which("feast")` depends on
  the running environment's `PATH`. If a bug exists purely in the CLI's own argument-parsing layer,
  this lane would not catch it.
- **No `make`/`make.ps1` target exists yet for the G1 lane or for `uv sync --group feast`.**
  CLAUDE.md's convention is that new CLI/test behavior gets a target on both runners; this was not
  added, and the decision of whether the lane needs one (versus running under an existing
  `test-integration` target) is left open.
- **`artifacts/changelog/` was not updated until this milestone.** AGENTS.md §13 requires it before
  commit; nothing here was committed prior to this milestone log existing.
- **`train` was not re-run.** No training metric, `vector_checksum` or fingerprint from
  M019/M026/M027 is restated here — nothing in this milestone changed a value-bearing SQL clause on
  the training path.
- **No commit exists for this milestone or for the T1a/T1b/T1c work it documents.** No commit hash
  is recorded above (pending).
- **T1's remaining §3.2 scope (PushSource, T5/T7 split) was deliberately not built here** — recorded
  as a scope narrowing in item 2, not a defect.
- Next: (1) decide whether the same-step coverage hole needs a second fixture scenario or a
  documented permanent limitation of guide §3.4; (2) decide whether idempotence needs to be
  re-measured across real separate `feast apply` CLI invocations before Sprint 2 T1 is called done;
  (3) decide on a `make`/`make.ps1` target for the G1 lane and `uv sync --group feast`; (4) begin T2
  (Gold `pre_decision_features`), at which point `FileSource` will point at a different table and
  this checksum is expected to change — that is the moment guide §3.3's migration note applies.

**Not claimed:** T1 sub-work beyond the four items above; "Sprint 2 done"; "ready for T2". Only the
four pieces of work in this log, and the three G1 criteria they made measurable, are asserted here.
