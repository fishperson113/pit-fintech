# M021 — Component-scoped lineage guard

- Date: 2026-07-27
- Updated: 2026-07-28
- Status: verified

## Scope and acceptance

Replace repository-wide trainer/lakehouse commit equality with a lineage policy that:

- permits documentation-only commits without rebuilding Silver;
- keeps exact Delta version/schema/logical checksum and FeatureSpec checks as the source gate;
- fingerprints the lakehouse and training implementation boundaries separately;
- rejects uncommitted changes inside the relevant component;
- retains Git commit and repository-wide dirty state as audit metadata;
- reads existing M018/M019 manifests without migration.

## Decisions

- Git commit equality is removed as a compatibility requirement.
- Exact materialized data and contract checks decide whether Silver is valid input.
- Component fingerprint v1 hashes normalized path names and file bytes for an explicit path set.
- New manifests add optional lineage fields so old JSON artifacts still validate.
- A legacy lakehouse manifest is accepted only when its old commit value is clean.
- New dirty-component lakehouse manifests are blocked even if their repository commit exists.
- `--allow-dirty` remains diagnostic-only.

See `docs/adr/004-component-lineage-policy.md`.

## Files added or changed

- `src/pit_fintech/platform/lineage.py`
- `src/pit_fintech/contracts/manifests.py`
- `src/pit_fintech/data/paysim_lakehouse.py`
- `src/pit_fintech/models/paysim_training.py`
- `src/pit_fintech/cli.py`
- `tests/unit/test_paysim_training.py`
- `tests/integration/test_paysim_lakehouse.py`
- `notebooks/05_silver_training_baseline.ipynb`
- `docs/adr/004-component-lineage-policy.md`
- `docs/reports/paysim-silver-training-baseline.md`
- `docs/reports/sprint-1-completion-report.md`
- `docs/research-protocol.md`
- `README.md`
- `AGENTS.md`
- `artifacts/changelog/PROJECT_STATUS.md`
- `artifacts/changelog/CHANGELOG.md`
- this milestone log

## Implemented behavior

- `component_fingerprint()` hashes only declared component files.
- Git commit, component dirty state and repository dirty state are measured independently.
- Training allows different clean lakehouse/trainer commits.
- Training blocks a dirty training component and a dirty lakehouse component.
- Legacy clean lakehouse manifests remain usable.
- New lakehouse/training manifests and MLflow runs carry component-lineage evidence.
- CLI and notebook 05 expose the training fingerprint.

## Verification state

No pytest, notebook, model, formatter or data pipeline command was executed by the agent.
Static inspection confirmed every guard/fingerprint call supplies the new boundary arguments,
`git diff --check` passes, and notebook 05 remains valid JSON with eight code cells and no saved
error output.

User verification:

```text
.\make.ps1 test-unit
  39 passed in 3.33s

.\make.ps1 test-lakehouse
  4 passed in 6.22s

.\make.ps1 test-notebooks
  PASS notebooks 01–05
  verified 5 notebooks
```

All implementation gates passed. Windows ZMQ/TCP kernel messages were non-blocking warnings.

The inspected latest application manifest is a clean legacy Silver v2 manifest from commit
`729d85f`; all three tables contain 6,362,620 rows and retain the verified logical checksums.
Legacy manifests intentionally have no component fields and are accepted through the clean
legacy fallback.

MLflow parent `6f8859ed79544cc19eac3c066d711b22` is a completed pre-M021 training run from the
same legacy v2/commit. It proves the old exact-commit path completed, but it cannot verify the
new fingerprint fields because it predates this implementation.

The later `train` attempt was correctly rejected before MLflow because M021 component files were
still uncommitted. After committing M021, `.\make.ps1 train` must reuse Silver v2 without
running `build-lakehouse`, despite the trainer and lakehouse having different Git commits.

The first M021 commit attempt passed Ruff check and every safety/governance guard. Ruff format
reformatted `paysim_training.py` and `platform/lineage.py`, so the hook correctly stopped for
review and restaging; the changes were formatting-only.

## Known gaps and next step

- Existing verified training manifests do not retroactively gain a component fingerprint; they
  remain valid historical evidence under their original clean-commit policy.
- Fingerprint path sets are explicit and must be updated if component imports move.

## Post-commit reuse verified (2026-07-28)

User-run `.\make.ps1 train`, no command executed by the agent. Manifest inspected:
`artifacts/experiments/paysim-silver-training/5705bd4d1ceb4337b87f77059e99af79/manifest.json`.

All three fields this milestone requires are present:

```text
training_component_fingerprint: f34ba2bd849e70c42a56ab9effd43acb9419cf7a8c6aedd99b81590071619f8b
training_component_dirty: false
repository_dirty: true
```

`repository_dirty: true` is expected, not a defect: at run time the repository had other
uncommitted changes outside the training component's declared path set (this same M024 test
work), and ADR-004 records repository-wide dirty state for transparency only — it is not the
gate. The gate is `training_component_dirty`, which is `false`.

`source_tables` in the same manifest show `silver.paysim_transactions` and `silver.paysim_labels`
still at Delta `version: 2`, while `application_lakehouse_code_commit` remains the older
`729d85fd38852e7c54eb8eb7681a3c8da1adf8ec` — the trainer ran from code commit `ba360fbabfd...`
without rebuilding the lakehouse, which is exactly the post-commit reuse this milestone was
pending on.

The run also reproduced the frozen M019 result from an independent invocation: E1 test PR-AUC
`0.258342`, E4 test PR-AUC `0.102766`, both matching the M019 manifest exactly; vector checksum
`4713896b68a3021e116e8d887f93d39d2ce50446f0c6f160d448c4a3cf3f0cbd`; future-read violations `0`;
MLflow parent run `5705bd4d1ceb4337b87f77059e99af79`.

Status: verified.
