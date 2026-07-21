from __future__ import annotations

from scripts.verify_milestone_changelog import (
    CHANGELOG_PATH,
    STATUS_PATH,
    validation_errors,
)


def test_docs_only_change_does_not_require_milestone_log() -> None:
    assert validation_errors(["docs/data-access.md"]) == []


def test_implementation_change_requires_all_audit_files() -> None:
    errors = validation_errors(["src/pit_fintech/cli.py"])
    assert len(errors) == 3


def test_complete_milestone_audit_set_passes() -> None:
    paths = [
        "src/pit_fintech/cli.py",
        STATUS_PATH,
        CHANGELOG_PATH,
        "artifacts/changelog/milestones/M001-foundation.md",
    ]
    assert validation_errors(paths) == []


def test_windows_paths_are_normalized() -> None:
    paths = [
        "tests\\unit\\test_example.py",
        "artifacts\\changelog\\PROJECT_STATUS.md",
        "artifacts\\changelog\\CHANGELOG.md",
        "artifacts\\changelog\\milestones\\M001-foundation.md",
    ]
    assert validation_errors(paths) == []
