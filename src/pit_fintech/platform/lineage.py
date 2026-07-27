"""Component-scoped Git and source fingerprints for reproducible pipeline evidence."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Final

COMPONENT_FINGERPRINT_POLICY_VERSION: Final = "component-fingerprint-v1"


def component_fingerprint(project_root: Path, paths: tuple[str, ...]) -> str:
    """Hash an ordered source/dependency boundary without including unrelated files."""

    digest = hashlib.sha256()
    digest.update(f"{COMPONENT_FINGERPRINT_POLICY_VERSION}\0".encode())
    for relative_path in sorted(paths):
        path = project_root / relative_path
        digest.update(relative_path.replace("\\", "/").encode())
        digest.update(b"\0")
        if not path.is_file():
            digest.update(b"<MISSING>\0")
            continue
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, byteorder="big", signed=False))
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def current_git_commit(project_root: Path) -> str:
    """Return the current Git commit without conflating it with worktree dirtiness."""

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return commit.stdout.strip() if commit.returncode == 0 else "UNCOMMITTED"


def repository_dirty(project_root: Path) -> bool:
    """Report any tracked or untracked repository change for transparent audit metadata."""

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return status.returncode != 0 or bool(status.stdout.strip())


def component_dirty(project_root: Path, paths: tuple[str, ...]) -> bool:
    """Report changes only inside a declared component boundary."""

    tracked_changes = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *paths],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if tracked_changes.returncode not in (0, 1):
        return True
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", *paths],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return (
        tracked_changes.returncode == 1
        or untracked.returncode != 0
        or bool(untracked.stdout.strip())
    )
