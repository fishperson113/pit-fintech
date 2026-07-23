# M010 — PaySim raw snapshot Make target

- Date: 2026-07-23
- Status: verified

## Scope and acceptance

Add a user-facing Make target for the raw PaySim snapshot operation. The target must use the same
Python CLI boundary on GNU Make and Windows, must not download or mutate the source CSV, and must
persist enough machine-readable evidence to identify the exact input before EDA.

Acceptance for the command implementation:

- validate the exact PaySim schema before hashing;
- compute full SHA-256 and checksum-addressed `dataset_snapshot_id`;
- record byte size, source row count, step range, schema and code commit;
- atomically write a manifest under the runtime artifact tree;
- rerunning with the same input produces the same snapshot identity, path and content;
- leave execution on the full PaySim file to the user.

## Technical decisions

- Introduce a raw `DatasetSnapshotManifest` rather than reusing the canonical dataset manifest;
  raw snapshotting has no honest `canonical_rows` value yet.
- Store the manifest at
  `artifacts/datasets/paysim1/<sha256-prefix>/snapshot-manifest.json`.
- Use a temporary sibling file followed by `Path.replace` so a partial JSON write is not exposed
  as a valid snapshot manifest.
- Keep the raw file in place. Snapshotting records identity; it is not a copy, transform or Delta
  ingestion operation.
- Expose one learning-oriented command, `data-snapshot`, while dataset download remains a manual
  authorized-source action.

## Files changed

- `Makefile`
- `make.ps1`
- `src/pit_fintech/contracts/manifests.py`
- `src/pit_fintech/data/paysim.py`
- `src/pit_fintech/cli.py`
- `tests/unit/test_paysim.py`
- `README.md`
- `docs/data-access.md`
- project status, cumulative changelog, M009 follow-up and this log

## Verification evidence

```text
uv run --frozen pytest -q tests/unit/test_paysim.py
4 passed.

uv run --frozen ruff check src tests feature_repo notebooks scripts
All checks passed.

uv run --frozen ruff format --check src tests feature_repo notebooks scripts
33 files already formatted.

.\make.ps1 help
Pass; `data-snapshot` is listed as the PaySim identity/manifest operation.

uv run --frozen pytest -q
27 passed.

git diff --check
Pass; existing LF-to-CRLF working-copy warnings only.
```

The idempotency test creates a temporary PaySim-schema CSV, runs snapshot creation twice and
asserts identical manifest models, destination paths and serialized content. It also checks the
relative raw path, two source rows and step range 1–2.

## Deviations, gaps and next step

- The actual `make data-snapshot` / `.\make.ps1 data-snapshot` target was not run on the full
  Kaggle dataset. This is intentional: the user requested that meaningful workflow actions remain
  theirs to execute and inspect.
- The runtime manifest is gitignored evidence; only this implementation log is committed.
- Next step for the user: download PaySim to the configured raw path, run
  `.\make.ps1 data-snapshot`, inspect the printed snapshot ID/manifest, then start EDA.
