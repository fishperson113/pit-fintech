from __future__ import annotations

from pathlib import Path

import pytest

import pit_fintech.backfill.state_machine as state_machine
from pit_fintech.backfill.records import BackfillMode
from pit_fintech.features.build_offline import (
    _partition_predicate,
    validate_gold_cutoff_range,
)


@pytest.mark.parametrize("start, end", [(2, 2), (1, 23), (25, 47), (721, 742)])
def test_validate_gold_cutoff_range_rejects_partial_event_days(start: int, end: int) -> None:
    with pytest.raises(ValueError, match=r"range \[.*\] khong can bien event_day") as error:
        validate_gold_cutoff_range(start, end)

    assert "Dung" in str(error.value)
    assert "event_day" in str(error.value)


@pytest.mark.parametrize("start, end", [(1, 24), (25, 48), (1, 743), (721, 743)])
def test_validate_gold_cutoff_range_accepts_complete_event_days(start: int, end: int) -> None:
    validate_gold_cutoff_range(start, end)


def test_plan_backfill_reuses_gold_range_guard_before_resolving_silver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(**_: object) -> None:
        raise AssertionError("Silver resolution must not run for an invalid Gold range")

    monkeypatch.setattr(state_machine, "_resolve_silver_snapshot", fail_if_called)

    with pytest.raises(ValueError, match=r"range \[2, 2\] khong can bien event_day"):
        state_machine.plan_backfill(
            project_root=Path("."),
            data_root=Path("."),
            artifact_root=Path("."),
            mode=BackfillMode.RANGE,
            cutoff_start_step=2,
            cutoff_end_step=2,
        )


def test_gold_promotion_predicate_uses_the_shared_writer_predicate() -> None:
    assert _partition_predicate((1, 3)) == "event_day IN (CAST(1 AS INT), CAST(3 AS INT))"
