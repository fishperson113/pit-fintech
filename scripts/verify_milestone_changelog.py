"""Pre-commit guard for durable milestone implementation logs."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable

STATUS_PATH = "artifacts/changelog/PROJECT_STATUS.md"
CHANGELOG_PATH = "artifacts/changelog/CHANGELOG.md"
MILESTONE_PREFIX = "artifacts/changelog/milestones/"

IMPLEMENTATION_FILES = {
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "Makefile",
    "compose.yaml",
    "make.ps1",
    "pyproject.toml",
    "uv.lock",
}
IMPLEMENTATION_PREFIXES = (
    ".github/workflows/",
    "docker/",
    "docs/adr/",
    "docs/reports/",
    "feature_repo/",
    "notebooks/",
    "scripts/",
    "src/",
    "tests/",
)


def normalize(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_implementation_path(path: str) -> bool:
    normalized = normalize(path)
    return normalized in IMPLEMENTATION_FILES or normalized.startswith(IMPLEMENTATION_PREFIXES)


def validation_errors(paths: Iterable[str]) -> list[str]:
    changed = {normalize(path) for path in paths if normalize(path)}
    if not any(is_implementation_path(path) for path in changed):
        return []

    errors: list[str] = []
    if STATUS_PATH not in changed:
        errors.append(f"missing staged project status: {STATUS_PATH}")
    if CHANGELOG_PATH not in changed:
        errors.append(f"missing staged cumulative changelog: {CHANGELOG_PATH}")
    if not any(path.startswith(MILESTONE_PREFIX) and path.endswith(".md") for path in changed):
        errors.append(f"missing staged milestone log under: {MILESTONE_PREFIX}")
    return errors


def staged_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        print(completed.stderr.strip() or "unable to inspect staged paths", file=sys.stderr)
        raise SystemExit(2)
    return completed.stdout.splitlines()


def main() -> int:
    errors = validation_errors(staged_paths())
    if not errors:
        return 0

    print("Milestone changelog guard failed:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    print(
        "Update project status, cumulative changelog, and the active milestone log before commit.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
