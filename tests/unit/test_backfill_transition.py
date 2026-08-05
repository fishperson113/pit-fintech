"""Unit coverage for the T3 backfill state machine's legal/illegal transitions (guide s5.1).

``transition()`` is the enforcement point for ``planned -> running -> validated -> committed``,
plus the two failure edges ``running -> failed`` and ``validated -> failed``. These tests exercise
every legal edge, a representative sample of illegal edges (skips, reversals, and both terminal
states refusing to move at all), and confirm the function returns a new record rather than
mutating its argument.
"""

from __future__ import annotations

import datetime

import pytest

from pit_fintech.backfill.records import (
    BackfillCounts,
    BackfillMode,
    BackfillRunRecord,
    BackfillScanEvidence,
    BackfillState,
    BackfillTimings,
    MaterializationReuse,
)
from pit_fintech.backfill.state_machine import transition


def _record(state: BackfillState) -> BackfillRunRecord:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return BackfillRunRecord(
        run_id="run-1",
        idempotency_key="key-1",
        attempt=1,
        supersedes_run_id=None,
        state=state,
        mode=BackfillMode.RANGE,
        cutoff_start_step=1,
        cutoff_end_step=10,
        lookback_start_step=1,
        dataset_snapshot_id="paysim1:deadbeef",
        raw_file_sha256="sha",
        entity_definition_version="entity-v1",
        feature_definition_version="feature-v1",
        feature_service_version="service-v1",
        feature_contract_checksum="contract-checksum",
        pipeline_version="pipeline-v1",
        code_commit="abc123",
        lineage_policy_version="component-fingerprint-v1",
        gold_component_fingerprint="fingerprint",
        gold_component_dirty=False,
        repository_dirty=False,
        source_bronze_table_version=None,
        source_silver_transactions_version=1,
        source_silver_labels_version=None,
        source_checksum="source-checksum",
        input_partitions=(),
        output_partitions=(),
        output_checksum=None,
        committed_gold_pre_decision_version=None,
        committed_gold_post_event_version=None,
        delta_app_id=None,
        delta_app_version=None,
        staging_root="artifacts/runs/run-1/staging",
        staging_cleaned=False,
        counts=BackfillCounts(
            source_rows_in_range=0,
            cutoff_rows_in_scope=0,
            pre_decision_rows_written=0,
            post_event_state_rows_written=0,
            rows_superseded=0,
            duplicate_rows_dropped=0,
        ),
        timings=BackfillTimings(planned_at=now),
        scan=BackfillScanEvidence(
            source_partitions_total=0,
            source_partitions_read=0,
            source_files_read=0,
            source_bytes_read=0,
            source_rows_scanned=0,
            lookback_steps=0,
        ),
        reuse=MaterializationReuse(reused=False),
        errors=(),
        manifest_path="",
    )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (BackfillState.PLANNED, BackfillState.RUNNING),
        (BackfillState.RUNNING, BackfillState.VALIDATED),
        (BackfillState.RUNNING, BackfillState.FAILED),
        (BackfillState.VALIDATED, BackfillState.COMMITTED),
        (BackfillState.VALIDATED, BackfillState.FAILED),
    ],
)
def test_transition_allows_every_legal_edge(
    from_state: BackfillState, to_state: BackfillState
) -> None:
    record = _record(from_state)

    result = transition(record=record, to_state=to_state)

    assert result.state is to_state
    assert result is not record
    assert record.state is from_state  # the input record is untouched


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (BackfillState.PLANNED, BackfillState.VALIDATED),
        (BackfillState.PLANNED, BackfillState.COMMITTED),
        (BackfillState.PLANNED, BackfillState.FAILED),
        (BackfillState.RUNNING, BackfillState.COMMITTED),
        (BackfillState.RUNNING, BackfillState.PLANNED),
        (BackfillState.VALIDATED, BackfillState.RUNNING),
        (BackfillState.VALIDATED, BackfillState.PLANNED),
        (BackfillState.COMMITTED, BackfillState.FAILED),
        (BackfillState.COMMITTED, BackfillState.RUNNING),
        (BackfillState.COMMITTED, BackfillState.PLANNED),
        (BackfillState.FAILED, BackfillState.RUNNING),
        (BackfillState.FAILED, BackfillState.COMMITTED),
        (BackfillState.FAILED, BackfillState.PLANNED),
    ],
)
def test_transition_rejects_every_illegal_edge(
    from_state: BackfillState, to_state: BackfillState
) -> None:
    record = _record(from_state)

    with pytest.raises(ValueError, match="illegal backfill state transition"):
        transition(record=record, to_state=to_state)


def test_transition_applies_field_updates_alongside_the_state_change() -> None:
    """`transition` doubles as the write path for evidence collected at that stage boundary."""

    record = _record(BackfillState.RUNNING)

    result = transition(
        record=record,
        to_state=BackfillState.VALIDATED,
        output_checksum="new-checksum",
    )

    assert result.state is BackfillState.VALIDATED
    assert result.output_checksum == "new-checksum"
    assert record.output_checksum is None
