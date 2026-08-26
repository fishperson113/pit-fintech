# M093 — Enable OTel by default for serving runners

- **Datetime:** 2026-08-25
- **Status:** implemented; runner wiring verified; fresh Loki/Grafana arrival not rerun.
- **Scope:** make the public serving commands enable the existing OTLP traces, metrics, and logs exporter without requiring an extra CLI flag.

## Acceptance and decision

The repository already has a configured OTLP/HTTP endpoint in `config.yaml`, the required OpenTelemetry packages in the serving environment, and an OTLP log handler in `serving/telemetry.py`. The remaining gap was runner behavior: `pit serving up` defaults to `--no-otel`, while both public `serve` runners invoked it without `--otel`.

Both runners now explicitly pass `--otel`. The CLI default remains unchanged so direct callers can still deliberately use `pit serving up --no-otel`; the repository's normal `serve` command is the opinionated observable path.

## Files changed

- `Makefile`: `serve` now runs `uv run pit serving up --otel`; help text states that OTLP traces, metrics, and logs are enabled.
- `make.ps1`: the `serve` switch passes `--otel`; help text matches the Make target.
- `artifacts/changelog/PROJECT_STATUS.md`: current project status updated.
- `artifacts/changelog/CHANGELOG.md`: M093 summary added.
- `artifacts/changelog/milestones/M093-default-serve-otel.md`: this implementation log.

## Verification

- `make -n serve` — blocked because the Git Bash environment has no `make` command on `PATH`.
- `mingw32-make -n serve` — PASS using the installed make-compatible Windows binary; output was exactly `uv run pit serving up --otel`.
- `mingw32-make help` — PASS; the `serve` row states `Start FastAPI with OTLP traces, metrics, and logs enabled`.
- PowerShell parser over `make.ps1` — PASS.
- `.\make.ps1 help` — PASS; the `serve` row states the same OTel behavior.
- Static Makefile recipe assertion — PASS.
- `git diff --check` — PASS, with only existing line-ending conversion warnings.

No live server was started or restarted during implementation, so fresh Collector receipt, Loki persistence, and Grafana log-panel visibility remain separate runtime gates.

## Deviations and known gaps

- Used installed `mingw32-make` as the mechanical equivalent for the Make dry-run because `make` itself is unavailable on `PATH`; no package installation was performed.
- This change affects the next `make serve` or `.\make.ps1 serve` invocation. It does not retrofit OTel into a process that was started earlier without `--otel`.
- The exporter is best-effort by design: if OTel packages are absent, serving continues with telemetry disabled and emits a warning.
