from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from deltalake import DeltaTable

from pit_fintech.backfill.records import BackfillMode, BackfillState
from pit_fintech.backfill.state_machine import (
    compare_reruns,
    execute_backfill,
    inject_late_arrival_correction,
    plan_backfill,
)
from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim import DEFAULT_FILENAME
from pit_fintech.data.paysim_lakehouse import build_paysim_lakehouse
from pit_fintech.features.build_offline import (
    GOLD_POST_EVENT_TABLE,
    GOLD_PRE_DECISION_TABLE,
    POST_EVENT_STATE_SCHEMA,
    PRE_DECISION_FEATURE_SCHEMA,
    build_offline_features,
    compare_gold_against_reference,
    gold_table_path,
    promote_staged_gold,
    verify_shift_relation,
)
from pit_fintech.training.dataset import (
    EntityDataframeSpec,
    build_entity_dataframe,
    retrieve_historical_features,
)

pytestmark = pytest.mark.integration


def _write_fixture_csv(project_root: Path) -> Path:
    path = project_root / "data" / "raw" / "paysim" / DEFAULT_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            (
                "step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,"
                "newbalanceDest,isFraud,isFlaggedFraud",
                "1,CASH_IN,10.0,C0,10.0,0.0,C100,0.0,10.0,0,0",
                "2,TRANSFER,20.0,C1,30.0,10.0,C100,10.0,30.0,0,0",
                "3,CASH_OUT,30.0,C2,40.0,10.0,C100,30.0,60.0,0,0",
                "3,TRANSFER,40.0,C3,50.0,10.0,C100,60.0,100.0,0,0",
                "4,CASH_OUT,50.0,C4,60.0,10.0,C100,100.0,150.0,0,0",
                "5,PAYMENT,5.0,C5,10.0,5.0,M9,0.0,5.0,0,0",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_gold_fixture_build_is_atomic_contract_safe_and_deterministic(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _write_fixture_csv(project_root)
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"
    _, silver_manifest = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )

    first = build_offline_features(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        run_id="gold-fixture-one",
        cutoff_start_step=1,
        cutoff_end_step=24,
        silver_manifest_path=silver_manifest,
    )
    assert first.status == "staged"
    assert all(validation.status == "pass" for validation in first.validations)
    assert first.rows_in_scope == 4
    assert first.rows_post_event == 6
    assert first.same_step_ties.in_scope_same_step_pairs == 2
    assert first.same_step_ties.any_same_step_pairs == 2
    assert first.same_step_ties.entities_with_same_step_pairs == 1
    assert first.same_step_ties.examples
    assert not gold_table_path(
        data_root=data_root,
        snapshot_prefix=first.raw_file_sha256[:16],
        table=GOLD_PRE_DECISION_TABLE,
    ).exists()

    parity = compare_gold_against_reference(build=first)
    assert parity.sql_rows == parity.oracle_rows == 4
    assert parity.compared_fields == 48
    assert parity.mismatched_fields == 0, parity.differences
    shift = verify_shift_relation(build=first, entity_ids=("C100",))
    assert len(shift) == 1
    assert shift[0].status == "pass"
    assert shift[0].detail == "compared_fields=36"

    second = build_offline_features(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        run_id="gold-fixture-two",
        cutoff_start_step=1,
        cutoff_end_step=24,
        silver_manifest_path=silver_manifest,
        promote=True,
    )
    assert second.status == "committed"
    assert first.pre_decision.logical_checksum == second.pre_decision.logical_checksum
    assert first.post_event_state.logical_checksum == second.post_event_state.logical_checksum

    for table_name, schema, rows in (
        (GOLD_PRE_DECISION_TABLE, PRE_DECISION_FEATURE_SCHEMA, 4),
        (GOLD_POST_EVENT_TABLE, POST_EVENT_STATE_SCHEMA, 6),
    ):
        path = gold_table_path(
            data_root=data_root,
            snapshot_prefix=second.raw_file_sha256[:16],
            table=table_name,
        )
        table = DeltaTable(path).to_pyarrow_table()
        assert tuple(table.column_names) == tuple(column.name for column in schema)
        assert table.num_rows == rows


def test_promote_staged_gold_refuses_when_future_read_violations_reported(tmp_path: Path) -> None:
    """Gate G3: a failing ``no_future_read_violations`` / ``max_source_step_below_every_cutoff``
    entry must block promotion, leaving the main Gold tables untouched.

    ``probe_future_read_violations`` itself is exercised directly against hand-built data in
    ``tests/unit/test_gold_future_read_audit.py``; this test proves the wiring from a failing
    validation through to ``promote_staged_gold`` refusing to promote, which is the behavior the
    dead-code ``future_reads = ... if False else 0`` line silently defeated.
    """

    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _write_fixture_csv(project_root)
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"
    _, silver_manifest = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )

    staged = build_offline_features(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        run_id="gold-fixture-future-read-violation",
        cutoff_start_step=1,
        cutoff_end_step=24,
        silver_manifest_path=silver_manifest,
    )
    assert all(validation.status == "pass" for validation in staged.validations)

    broken_validations = tuple(
        replace(validation, status="fail", observed=1)
        if validation.name in ("no_future_read_violations", "max_source_step_below_every_cutoff")
        else validation
        for validation in staged.validations
    )
    broken = replace(staged, validations=broken_validations)

    promotion = promote_staged_gold(build=broken, data_root=data_root)

    assert promotion.promoted is False
    assert {v.name for v in promotion.failed_validations} == {
        "no_future_read_violations",
        "max_source_step_below_every_cutoff",
    }
    assert not gold_table_path(
        data_root=data_root,
        snapshot_prefix=broken.raw_file_sha256[:16],
        table=GOLD_PRE_DECISION_TABLE,
    ).exists()


def test_t3_smoke_backfill_rerun_and_late_arrival_guard(tmp_path: Path) -> None:
    """Smoke the T3 seams without touching the real PaySim lakehouse."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _write_fixture_csv(project_root)
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"
    _, silver_manifest = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )

    plan = plan_backfill(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        mode=BackfillMode.RANGE,
        cutoff_start_step=1,
        cutoff_end_step=24,
        run_id="t3-smoke-initial",
        silver_manifest_path=silver_manifest,
    )
    first = execute_backfill(
        plan=plan,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
    )
    assert first.state is BackfillState.COMMITTED
    assert first.committed_gold_pre_decision_version is not None
    assert first.committed_gold_post_event_version is not None

    rerun = replace(first, run_id="t3-smoke-rerun")
    comparison = compare_reruns(first=first, second=rerun)
    assert comparison.passed
    assert comparison.logical_checksums_match
    assert comparison.partition_checksums_match

    with pytest.raises(RuntimeError, match="no_future_read_violations"):
        inject_late_arrival_correction(
            project_root=project_root,
            data_root=data_root,
            artifact_root=artifact_root,
            watermark_step=24,
            injected_step=1,
            injected_knowledge_step=25,
        )


def test_t4_gold_to_training_dataset_fixture(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    csv_path = _write_fixture_csv(project_root)
    data_root = project_root / "data"
    artifact_root = project_root / "artifacts"
    _, silver_manifest_path = build_paysim_lakehouse(
        csv_path,
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        batch_size=4,
    )
    build = build_offline_features(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        run_id="t4-dataset-fixture",
        cutoff_start_step=1,
        cutoff_end_step=24,
        silver_manifest_path=silver_manifest_path,
    )
    manifest = ApplicationLakehouseManifest.model_validate_json(
        silver_manifest_path.read_text(encoding="utf-8")
    )
    labels = next(item for item in manifest.tables if item.table == "paysim_labels")
    spec = EntityDataframeSpec(
        dataset_snapshot_id=manifest.dataset_snapshot_id,
        entity_definition_version=build.entity_definition_version,
        feature_definition_version=build.feature_definition_version,
        feature_service_version=build.feature_service_version,
        feature_contract_checksum=build.feature_contract_checksum,
        gold_pre_decision=build.pre_decision,
        label_table_path=labels.path,
        label_table_version=labels.version,
        start_step=1,
        end_step=24,
        retrieval_backend="duckdb_gold",
    )
    dataframe_path = build_entity_dataframe(spec=spec, artifact_root=artifact_root)
    retrieval = retrieve_historical_features(
        spec=spec,
        entity_dataframe_path=dataframe_path,
        artifact_root=artifact_root,
    )
    assert retrieval.rows == build.rows_in_scope
    assert retrieval.ordered_feature_names
    assert retrieval.training_dataset_checksum
    assert all(assertion.status == "pass" for assertion in retrieval.assertions)
