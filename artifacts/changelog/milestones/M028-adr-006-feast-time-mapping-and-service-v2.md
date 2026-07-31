# M028 — ADR-006: Feast time mapping and feature service v2 (proposed)

- Date: 2026-07-31
- Status: verified

## Scope and acceptance

Sprint 2 task T1 builds the Feast feature repository (S2-A1) and is gated by G1. Two decisions
block the first file of that repository, and both become expensive to change once a registry
artifact exists, because the registry checksum and the online key namespace are derived from them:

1. PaySim has no column Feast will accept as event time. Silver carries `step BIGINT` and
   `knowledge_step BIGINT` (hour ordinals, range 1–743), while Feast `FileSource` requires
   `timestamp_field`/`created_timestamp_column` to name real timestamp columns.
2. `PAYSIM_FEATURE_SERVICE_VERSION` was still `paysim-fraud-scoring-v1` while the FeatureSpec moved
   to `paysim-fraud-recipient-v2` in ADR-005/M026.

Acceptance for this milestone is documentation plus one dependency declaration:

- `docs/adr/006-feast-time-mapping-and-service-v2.md` records both decisions, the rejected
  alternatives, consequences and revisit conditions, with status `proposed`;
- `pyproject.toml` declares Feast in its own optional dependency group, with no change to the
  frozen `requires-python`, `pyarrow` or `duckdb` constraints and no change to the main
  `dependencies` list;
- no `feature_repo/` change. The service-version bump was applied to `src/`, `tests/` and config
  as a same-day follow-up within this same milestone; the project owner then ran `uv lock`,
  `.\make.ps1 lint`, `.\make.ps1 test-unit` and `.\make.ps1 test-temporal` on 2026-07-31, all
  green — see "Verification state" and "Known gaps and next steps" below for the exact commands,
  numbers and what is still pending.

## Decision

Record ADR-006 as `proposed`:

1. **Derived timestamp columns for the Feast layer.** Freeze
   `EPOCH_0 = 2020-01-01T00:00:00Z` (Unix `1577836800`), with
   `event_timestamp = EPOCH_0 + step hours` and
   `created_timestamp = EPOCH_0 + knowledge_step hours`. The frozen range maps to
   `2020-01-01T01:00:00Z` .. `2020-01-31T23:00:00Z` (Unix `1580511600`).
2. The map is bijective and strictly order-preserving on integers, so every PIT comparison is
   preserved and no invariant is touched. `EPOCH_0` is a presentation convention only: ADR-002
   decision 1 already fixed `step` as an hourly source ordinal, not a business timestamp, so the
   derived dates carry no calendar meaning and must never become a feature, a split boundary or a
   date quoted in a report.
3. Cutoff order and tie-break stay on ADR-001/ADR-003/ADR-005 semantics
   (`prior.step < current.step AND prior.knowledge_step <= current.knowledge_step`, windows
   `[cutoff - window, cutoff)`, tie-break `(step, source_row_number)`). Timestamp comparison must
   not replace them — hour-resolution timestamps cannot express the `source_row_number` tie-break
   at all, since every row in the same step maps to the same instant.
   `src/pit_fintech/features/reference.py` remains the correctness authority.
4. `EPOCH_0` is deliberately distinct from the ADR-001 provisional IEEE-CIS epoch
   (`2017-01-01T00:00:00Z`) and from the synthetic fixture calendar (January 2024), so the two
   time bases can never be silently confused.
5. The derivation lives once in the T2 Gold projection, reused by the fixture builder; Bronze and
   Silver are not touched, so no rebuild of 6,362,620 rows is required for a column that is
   re-derivable by a fixed affine map.
6. **Bump the service version to `paysim-fraud-scoring-v2`.** The twelve fields keep their names,
   order, dtypes, defaults, windows, entity, scoring scope and forbidden inputs. Only the version
   string changes; the canonical contract checksum changes with it, which is the intended effect
   since guide §3.3 binds registry checksum to `feature_service_version` and §6.3/§7.1/§7.2/§9.2
   record that string in MLflow tags, materialization metadata, online key namespaces and every
   scoring response.
7. Rejected alternatives: building T1 against the existing synthetic fixture oracle (it is the
   `fraud-history-v1` contract — entity `card_entity_id`, 13 features — sharing no entity, feature
   name or source with `paysim-fraud-recipient-v2`, so T1 would produce a repository T2 must
   delete); configuring Feast to accept an integer event-time column (no documented support, and
   Feast is pre-1.0, so relying on offline-store internals would put a hard invariant on a surface
   that can change in a minor release); and keeping the service version at v1 with a documented
   note (a version string exists to be read literally, and the footnote is not what gets read
   during an incident).

## Files added or changed

- `docs/adr/006-feast-time-mapping-and-service-v2.md` (new, status `proposed`; amended same day
  with decision 3 below)
- `pyproject.toml` — new `[dependency-groups] feast` group, and the pre-existing `serving` group's
  `uvicorn` pin lowered to fit it:
  - `feast[duckdb,redis]>=0.65,<0.66`. Superseded same day: the range originally recorded here
    (`>=0.51,<0.53`) was stale before it was ever resolved — 0.65.0 is Feast's current latest.
    Lower bound is the latest reviewed release; upper bound is the next unreviewed minor, because
    Feast is pre-1.0 and a minor bump may break.
  - `serving`'s `uvicorn[standard]` range changed from `>=0.37,<1` to `>=0.34,<=0.34.0` (pinned to
    exactly `0.34.0`). Every Feast release, including 0.65.0, depends on
    `uvicorn[standard]>=0.30.6,<=0.34.0`, and `uv` resolves all `[dependency-groups]` into one
    shared universe, so `serving`'s floor had to drop below Feast's ceiling. See ADR-006 decision 3
    for the rejected alternatives (`[tool.uv] conflicts`, separate environments) and why this is an
    intentional constraint, not an oversight.
  - The `duckdb`/`redis` extras are required by the DuckDB offline store and Redis online store the
    guide specifies. Frozen constraints are untouched: `requires-python >=3.11,<3.13`,
    `pyarrow>=21,<23`, `duckdb>=1.4,<2` — confirmed by the dry-run resolve below, neither pin had to
    move. Feast stays out of the main `dependencies` so a Feast resolution failure cannot break
    `test-temporal` or `test-unit`.
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log
- Same-day follow-up (service-version bump): `src/pit_fintech/features/paysim_specs.py`,
  `src/pit_fintech/config.py`, `.env.example`, `tests/unit/test_paysim_feature_contract.py`,
  `AGENTS.md`. Confirmed green by the project owner's 2026-07-31 acceptance run (see
  "Verification state"). See "Known gaps and next steps" for the exact lines and what remains
  pending.

## Verification state

Documentation plus dependency declarations, now backed by a real acceptance run. Project owner ran
the following on 2026-07-31, from a worktree confirmed clean by `git status --short` both before
and after:

```text
uv lock
```

Result: `Resolved 234 packages in 2ms`. `uv.lock` is now in sync with the current `pyproject.toml`,
including the `feast[duckdb,redis]>=0.65,<0.66` group and the `serving` group's
`uvicorn[standard]==0.34.0` pin.

```text
.\make.ps1 lint
```

Result: `ruff check`: All checks passed! `ruff format --check`: 48 files already formatted.

```text
.\make.ps1 test-unit
```

Result: 39 passed in 2.17s.

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
  47 passed in 3.25s
```

`test-temporal` regenerates `data/fixtures/temporal_cases.parquet` (and the other fixtures) via
`pit data sample`; `git status --short` stayed clean after the run, confirming that regeneration
step is deterministic and byte-identical to what is already committed. The service-version bump
(5 of 6 call sites, see "Files added or changed") is therefore gated by real green
`lint`/`test-unit`/`test-temporal` runs, not file edits alone. The project owner separately ran
`.\make.ps1 features` and `uv sync --group feast --group serving` on 2026-07-31, re-emitting the
contract checksum and materializing the `feast`/`serving` groups — see "Known gaps and next steps"
for the checksum value and an operational-risk note about that `uv sync` invocation.

## Known gaps and next steps

- **ADR-006 accepted 2026-07-31.** The project owner accepted the ADR; `docs/adr/006-feast-time-mapping-and-service-v2.md` status is now `accepted`. `EPOCH_0` and the v2 service string are
  now binding.
- **`uv.lock` is in sync with `pyproject.toml`, and the `feast`/`serving` groups are materialized.**
  The project owner's `uv lock` run on 2026-07-31 resolved `234 packages in 2ms`, covering both the
  `feast[duckdb,redis]>=0.65,<0.66` group and the `uvicorn[standard]==0.34.0` pin. The project owner
  then ran `uv sync --group feast --group serving` on 2026-07-31: `Resolved 234 packages, Prepared
  30, Uninstalled 54, Installed 33` — installing `feast==0.65.0`, `redis==7.4.1`, `hiredis==3.4.0`,
  `ibis-framework==12.0.0`, `uvicorn==0.34.0` (replacing `uvicorn==0.51.0`), `gunicorn`,
  `uvicorn-worker`, `watchfiles`, `websockets`, `dask`, `sqlglot`, and others, while uninstalling
  `lightgbm==4.7.0`, `mlflow==3.14.0` (+skinny/tracing), `scikit-learn==1.9.0`, `scipy`, `joblib`,
  `threadpoolctl`, `matplotlib`, `skops` and their dependents. See the operational-risk bullet below
  for why that uninstall happened and how to avoid it.
- **5 of the 6 listed call sites are bumped to `paysim-fraud-scoring-v2`**, confirmed green by the
  project owner's 2026-07-31 `lint`/`test-unit`/`test-temporal` runs (see "Verification state"):
  `src/pit_fintech/features/paysim_specs.py:16`, `src/pit_fintech/config.py:29`,
  `.env.example:12`, `tests/unit/test_paysim_feature_contract.py:39`, `AGENTS.md:164` (the
  `service` clause only — the co-located `paysim-fraud-recipient-v1` text on that same AGENTS.md
  line is a separate, unrelated reference and was left untouched). The `Settings` default
  assertion at `tests/unit/test_paysim_feature_contract.py:125` compares against the constant and
  moved automatically. `docs/reports/paysim-feature-contract-v1.md:15` is the sixth listed site;
  it is a historical record and remains `v1` intentionally, by choice, not an omission.
- **The contract checksum has been re-emitted.** The project owner ran `.\make.ps1 features`
  (`uv run pit features show --dataset paysim`) on 2026-07-31 against the v2 service string and got:

  ```text
  contract: paysim-fraud-recipient-features
  version: paysim-fraud-recipient-v2
  service: paysim-fraud-scoring-v2
  entity: destination_entity_id (paysim-destination-customer-v1)
  scope: CASH_OUT, TRANSFER -> CUSTOMER
  cutoff: strict_prior_event_time; same-time: exclude_same_event_time; online: score_then_update
  checksum: 01bba24cc79be8729ec66557bb68828fbb66a17bfefdb601aaedc1a6cee575de
  feature_count: 12
  ```

  This is the canonical `paysim-fraud-recipient-v2` / `paysim-fraud-scoring-v2` contract checksum
  and differs from the v1 checksum (`5b4e2b6d…`, M017) because `service_version` is part of the
  canonical JSON `paysim_feature_contract_checksum()` hashes. It is unrelated to the training
  `vector_checksum` values (M019/M026/M027 above), which are a separate artifact from `train`.
- **Operational risk: `uv sync --group <X> --group <Y>` uninstalls groups not named.** `uv sync`
  makes the environment match exactly the set of groups given on the command line, so running
  `uv sync --group feast --group serving` removed the `training`/tracking group
  (`lightgbm`, `mlflow`, `scikit-learn`, `scipy`, `joblib`, `threadpoolctl`, `matplotlib`, `skops`
  and their dependents) even though nothing in this milestone intended to drop them. The correct
  command for a full dev environment (all groups, including `training`) is `uv sync --all-groups`.
  This is a trap for the next person who runs a scoped `uv sync` expecting it to only add packages.
- Next: (1) start T1 against the PaySim contract now that ADR-006 is accepted and the contract
  checksum is re-emitted; (2) if a full dev/training environment is needed again, run
  `uv sync --all-groups` rather than a scoped `--group` invocation.
