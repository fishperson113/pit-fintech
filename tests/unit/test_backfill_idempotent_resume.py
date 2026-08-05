"""Unit coverage for `resolve_idempotent_run`'s four guide s5.2 branches.

Each test writes zero or one prior :class:`BackfillRunRecord` manifests to a ``tmp_path`` artifact
root via :func:`write_run_manifest`, then asks :func:`resolve_idempotent_run` what an incoming run
under the same idempotency key must do. The four branches, in the order the function itself
checks them:

1. no prior run recorded -> ``RUN_FRESH``.
2. a prior run's ``source_checksum`` differs from the incoming one ->
   ``FAIL_SOURCE_CHECKSUM_CHANGED``, regardless of that prior run's state (covered here for both a
   ``committed`` and a ``failed`` prior run).
3. a prior run is ``committed`` with a matching checksum -> ``NOOP_ALREADY_COMMITTED``.
4. a prior run is ``failed`` or still mid-way (``planned``/``running``/``validated``) with a
   matching checksum -> ``RESUME_AFTER_STAGING_CLEANUP``.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from pit_fintech.backfill.records import (
    BackfillCounts,
    BackfillMode,
    BackfillResumeAction,
    BackfillRunRecord,
    BackfillScanEvidence,
    BackfillState,
    BackfillTimings,
    MaterializationReuse,
)
from pit_fintech.backfill.state_machine import resolve_idempotent_run, write_run_manifest

_KEY = "idempotency-key-under-test"


def _record(
    *,
    run_id: str,
    attempt: int,
    state: BackfillState,
    source_checksum: str,
) -> BackfillRunRecord:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return BackfillRunRecord(
        run_id=run_id,
        idempotency_key=_KEY,
        attempt=attempt,
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
        source_checksum=source_checksum,
        input_partitions=(),
        output_partitions=(),
        output_checksum=None,
        committed_gold_pre_decision_version=(7 if state is BackfillState.COMMITTED else None),
        committed_gold_post_event_version=(7 if state is BackfillState.COMMITTED else None),
        delta_app_id=None,
        delta_app_version=None,
        staging_root=f"artifacts/runs/{run_id}/staging",
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


def test_resolve_idempotent_run_is_fresh_when_no_prior_run_exists(tmp_path: Path) -> None:
    resolution = resolve_idempotent_run(
        artifact_root=tmp_path, idempotency_key=_KEY, incoming_source_checksum="checksum-a"
    )

    assert resolution.action is BackfillResumeAction.RUN_FRESH
    assert resolution.existing_run_id is None
    assert resolution.staging_paths_to_clean == ()


def test_resolve_idempotent_run_is_noop_when_committed_with_matching_checksum(
    tmp_path: Path,
) -> None:
    committed = _record(
        run_id="run-committed",
        attempt=1,
        state=BackfillState.COMMITTED,
        source_checksum="checksum-a",
    )
    write_run_manifest(record=committed, artifact_root=tmp_path)

    resolution = resolve_idempotent_run(
        artifact_root=tmp_path, idempotency_key=_KEY, incoming_source_checksum="checksum-a"
    )

    assert resolution.action is BackfillResumeAction.NOOP_ALREADY_COMMITTED
    assert resolution.existing_run_id == "run-committed"
    assert resolution.staging_paths_to_clean == ()


def test_resolve_idempotent_run_resumes_after_cleanup_when_prior_run_failed(
    tmp_path: Path,
) -> None:
    failed = _record(
        run_id="run-failed",
        attempt=1,
        state=BackfillState.FAILED,
        source_checksum="checksum-a",
    )
    write_run_manifest(record=failed, artifact_root=tmp_path)

    resolution = resolve_idempotent_run(
        artifact_root=tmp_path, idempotency_key=_KEY, incoming_source_checksum="checksum-a"
    )

    assert resolution.action is BackfillResumeAction.RESUME_AFTER_STAGING_CLEANUP
    assert resolution.existing_run_id == "run-failed"
    assert resolution.staging_paths_to_clean == (failed.staging_root,)


def test_resolve_idempotent_run_resumes_after_cleanup_when_prior_run_is_still_mid_way(
    tmp_path: Path,
) -> None:
    running = _record(
        run_id="run-running",
        attempt=1,
        state=BackfillState.RUNNING,
        source_checksum="checksum-a",
    )
    write_run_manifest(record=running, artifact_root=tmp_path)

    resolution = resolve_idempotent_run(
        artifact_root=tmp_path, idempotency_key=_KEY, incoming_source_checksum="checksum-a"
    )

    assert resolution.action is BackfillResumeAction.RESUME_AFTER_STAGING_CLEANUP


def test_resolve_idempotent_run_fails_loud_when_checksum_changed_on_a_committed_run(
    tmp_path: Path,
) -> None:
    committed = _record(
        run_id="run-committed",
        attempt=1,
        state=BackfillState.COMMITTED,
        source_checksum="checksum-a",
    )
    write_run_manifest(record=committed, artifact_root=tmp_path)

    resolution = resolve_idempotent_run(
        artifact_root=tmp_path,
        idempotency_key=_KEY,
        incoming_source_checksum="checksum-b-different",
    )

    assert resolution.action is BackfillResumeAction.FAIL_SOURCE_CHECKSUM_CHANGED
    assert resolution.existing_source_checksum == "checksum-a"
    assert resolution.incoming_source_checksum == "checksum-b-different"


def test_resolve_idempotent_run_fails_loud_when_checksum_changed_on_a_failed_run(
    tmp_path: Path,
) -> None:
    """The checksum-changed branch is not gated on the prior run having committed: resuming a
    *failed* run under a different source checksum would be exactly as silently wrong as
    overwriting a committed one, so it must fail loud here too."""

    failed = _record(
        run_id="run-failed",
        attempt=1,
        state=BackfillState.FAILED,
        source_checksum="checksum-a",
    )
    write_run_manifest(record=failed, artifact_root=tmp_path)

    resolution = resolve_idempotent_run(
        artifact_root=tmp_path,
        idempotency_key=_KEY,
        incoming_source_checksum="checksum-b-different",
    )

    assert resolution.action is BackfillResumeAction.FAIL_SOURCE_CHECKSUM_CHANGED
    assert resolution.existing_run_id == "run-failed"
