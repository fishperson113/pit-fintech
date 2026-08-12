from __future__ import annotations

import logging

from pit_fintech.platform.lifecycle_logging import log_lifecycle


def test_log_lifecycle_emits_searchable_sorted_key_value_fields(caplog) -> None:
    logger = logging.getLogger("test.lifecycle")

    with caplog.at_level(logging.INFO, logger="test.lifecycle"):
        log_lifecycle(
            logger,
            "offline.parity.reconcile.completed",
            entity_id="C100",
            field_mismatches=0,
            passed=True,
            trace_id="abc123",
        )

    assert caplog.records[0].getMessage() == (
        "offline.parity.reconcile.completed entity_id=C100 field_mismatches=0 "
        "passed=True trace_id=abc123"
    )
