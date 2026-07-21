# Makefile adaptation from `aic2026`

## Source critique

The useful source patterns were a small public target surface, `uv` as the dependency runner,
matching Windows/Unix task names, a Jupyter target, Compose lifecycle commands, and a CI lane
that calls the same developer commands.

Patterns deliberately not copied were GPU/cloud/Kaggle notebook targets unrelated to this
CPU-first project, a serving target before a scoring contract exists, `Invoke-Expression` in
the PowerShell runner, disabled Jupyter authentication/XSRF checks, and an unconditional API
service whose dependencies and health are unrelated to the current milestone.

## Local alignment

The Makefile is orchestration only. Business logic lives behind the installed `pit` CLI so
GNU Make, PowerShell, CI, and notebooks cannot drift into four implementations. Targets are
added only when the underlying milestone has real code and a verification path.

| `aic2026` idea | PIT adaptation |
|---|---|
| `setup` | `bootstrap` uses `uv.lock` and pre-commit |
| `lab` | native locked Jupyter plus an authenticated Compose profile |
| `test` / `lint` | fixture-specific temporal lane plus full quality lane |
| `serve` | deferred until the versioned FeatureProvider/model contract exists |
| cloud/GPU tasks | excluded from the Sprint 1 command surface |
| PowerShell mirror | retained, replacing expression evaluation with argument arrays |

## Reusable local helpers

- `pit_fintech.cli`: one command boundary for every task runner;
- `pit_fintech.config`: environment contract with safe local defaults;
- `pit_fintech.platform.doctor`: secret-safe, read-only prerequisite inspection;
- `pit_fintech.data.sample`: deterministic artifact and manifest creation;
- `pit_fintech.features.reference`: correctness oracle future engines must match;
- `feature_repo.feature_specs`: ordered, versioned feature definition shared by consumers.

## Refactor path for later milestones

1. Verify temporal tests before adding optimized compute.
2. Add a DuckDB implementation beside, not inside, the oracle; require vector parity.
3. Add Bronze/Silver Delta commands and exact table versions to manifests.
4. Add Feast only after the v1 spec/entity contract is locked.
5. Add backfill/materialization CLI commands, then expose corresponding Make targets.
6. Add scoring only after FeatureProvider, champion manifest, freshness, and version gates exist.
7. Add cloud/TypeScript targets only after local replay parity passes.
