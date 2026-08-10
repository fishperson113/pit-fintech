# M047 — One-shot `setup` target and OTel collector endpoint env

- **Datetime:** 2026-08-10
- **Status:** implemented (agent static analysis only; owner gate: `.\make.ps1 setup` then `.\make.ps1 lint`)
- **Sprint / task:** developer-experience + Sprint 2 T7 observability wiring (ADR-008)

## Scope

Two small developer-experience changes requested by the owner:

1. A single `setup` target that installs **every** dependency group in one shot. The previous
   guidance was several `uv sync --group ...` calls, which under uv's match-environment-exactly
   semantics silently **uninstalled** the groups not named on the command line (recorded in M028
   and in the `test-lakehouse` Makefile comment).
2. A `.env`-backed collector endpoint so the owner's self-hosted OTel Collector is wired into
   `pit serving up --otel` without passing `--otel-endpoint` on every start.

## What changed

### One-shot `setup`
- `Makefile`: new `setup` target — `uv sync --frozen --all-groups` then
  `uv run pre-commit install`; added `setup` to `.PHONY`. `bootstrap` is unchanged (dev + hooks).
- `make.ps1`: matching `setup` case (same two commands) and a help-table row.
- `README.md` / `CLAUDE.md`: `setup` documented next to `bootstrap` in the command contract.
- Rationale: the dependency groups are `dev`, `training`, `tracking`, `feast`, `serving`
  (`pyproject.toml` `[dependency-groups]`); `--all-groups` installs all five at once. `--frozen`
  preserves the lock-first policy (CLAUDE.md "Always `uv sync --frozen`").

### OTel collector endpoint env
- `src/pit_fintech/config.py`: `Settings` gains `otel_endpoint: str | None = None`. The model is
  pydantic-settings with `env_prefix="PIT_"`, so this reads `PIT_OTEL_ENDPOINT` from `.env`.
- `src/pit_fintech/cli.py`: `pit serving up --otel-endpoint` default is now
  `get_settings().otel_endpoint`, so `.env`'s `PIT_OTEL_ENDPOINT` is honored; an explicit
  `--otel-endpoint` flag still overrides. Help text updated to mention `PIT_OTEL_ENDPOINT` then
  `OTEL_EXPORTER_OTLP_ENDPOINT`.
- `.env.example`: documents `PIT_OTEL_ENDPOINT` with the `http://<collector-host>:4318` example.
- `serving/telemetry.py` is untouched: the existing fallback to
  `os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")` still applies when neither the flag nor
  `PIT_OTEL_ENDPOINT` is set. No dependency change; OTel stays a hand-installed optional (ADR-008,
  ADR-004 fingerprint preserved).

## Commands + results

- Agent static analysis only: the Linux sandbox could not run the Windows `.venv` toolchain. Edits
  are Ruff-clean by inspection (no new imports beyond the already-imported `get_settings`; no
  formatting-sensitive lines added outside Makefile/make.ps1/`.env.example`).
- **Owner gates:**

  ```powershell
  .\make.ps1 setup                     # one-shot full environment + hooks
  .\make.ps1 lint                      # ruff clean / format check
  uv run pit serving up --otel         # reads PIT_OTEL_ENDPOINT from .env
  ```

## Known gaps / next steps

- Nothing committed yet; the milestone-changelog trio is part of this change set.
- Pre-existing, untouched here: `serve`/`materialize`/`demo` rows are not in the README command
  contract table; the `serve` make target does not pass `--otel` (run
  `uv run pit serving up --otel` directly when telemetry is wanted).
