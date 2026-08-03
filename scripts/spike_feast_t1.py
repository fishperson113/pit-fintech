"""Throwaway T1 spike: does Feast actually behave the way ADR-006 assumes?

NOT production code. Nothing here is imported by `src/`, nothing is committed to `feature_repo/`,
and every artifact it creates lives in a temporary directory that is removed on exit. It exists to
answer four questions before any registry code is written, because each answer can change the T1
design and two of them cannot be recovered from once a registry artifact exists.

Run it, paste the stdout, throw it away (or keep it as the record of what was measured):

    uv run python scripts/spike_feast_t1.py

Every question prints its own verdict. A question that cannot be answered prints the reason and
the traceback rather than skipping quietly -- an unanswered question here is itself a finding.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import traceback
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pit_fintech.data.paysim_fixture import (  # noqa: E402
    EXPECTED_PATH,
    load_paysim_expected_features,
    load_paysim_fixture_events,
)
from pit_fintech.features.paysim_recipient import _prior_window_predicate  # noqa: E402
from pit_fintech.features.paysim_reference import (  # noqa: E402
    PAYSIM_WINDOW_STEPS,
    in_scoring_scope,
)
from pit_fintech.features.paysim_specs import (  # noqa: E402
    PAYSIM_ENTITY,
    PAYSIM_MODEL_FEATURE_ORDER,
    paysim_step_to_timestamp,
)

ENTITY_KEY = PAYSIM_ENTITY
UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")


def banner(question: str, title: str) -> None:
    print("\n" + "=" * 96)
    print(f"Q{question}. {title}")
    print("=" * 96)


def verdict(good: bool, message: str) -> None:
    print(f"\n  >>> {'GOOD' if good else 'PROBLEM'}: {message}")


# ------------------------------------------------------------------------------------------
# Q1 -- does the 11-row feature table still carry a same-step pair?
# ------------------------------------------------------------------------------------------


def question_1() -> list:
    banner("1", "Do any two in-scope rows share a step (would become a Feast timestamp tie)?")

    events = load_paysim_fixture_events()
    in_scope = [event for event in events if in_scoring_scope(event)]
    steps = [event.step for event in in_scope]

    print(f"  fixture rows      : {len(events)}")
    print(f"  in-scope rows     : {len(in_scope)}")
    print(f"  in-scope steps    : {steps}")
    print(f"  distinct steps    : {len(set(steps))}")
    for event in in_scope:
        print(
            f"    row {event.source_row_number:>8}  step {event.step:>4}  "
            f"{event.transaction_type:<9} {event.destination_entity_id}"
        )

    history_only = [event for event in events if not in_scoring_scope(event)]
    print("\n  history-only rows (in the source parquet, never a cutoff):")
    for event in history_only:
        print(
            f"    row {event.source_row_number:>8}  step {event.step:>4}  "
            f"{event.transaction_type:<9} {event.destination_entity_id}"
        )

    duplicated = sorted({step for step in steps if steps.count(step) > 1})
    if duplicated:
        verdict(False, f"steps {duplicated} repeat among cutoffs; Feast will face a real tie")
    else:
        verdict(
            True,
            "no two cutoffs share a step, so the feature table has no tie -- which also means "
            "the same-step pair the fixture was built to carry is NOT exercised by Feast "
            "(a coverage hole, not a blocker)",
        )
    return in_scope


# ------------------------------------------------------------------------------------------
# Q2 -- build the 11-row feature table with the SQL engine, retrieve it through Feast
# ------------------------------------------------------------------------------------------


def _feature_sql() -> str:
    """The twelve contract fields, using the production window predicate, not a retyped one.

    `_prior_window_predicate` is imported from `features/paysim_recipient.py` on purpose: the
    point of this spike is to compare an SQL-derived table against the Python oracle. If the SQL
    here were written from scratch it would be a third derivation and prove nothing about the
    engine the project actually ships.
    """

    windows = sorted(PAYSIM_WINDOW_STEPS)
    columns = []
    for window_steps in windows:
        prior = _prior_window_predicate(window_steps)
        columns.append(
            f"""
            (count(s.source_row_number) FILTER (WHERE {prior}))::BIGINT
                AS pit_prior_count_{window_steps}h,
            coalesce(
                sum(CAST(s.amount AS DECIMAL(18,2))) FILTER (WHERE {prior}), 0.0
            )::DOUBLE AS pit_prior_amount_{window_steps}h,
            CASE WHEN (count(s.source_row_number) FILTER (WHERE {prior})) > 0 THEN 1 ELSE 0 END
                AS recipient_has_history_{window_steps}h
            """
        )
    widest = max(windows)
    return f"""
        SELECT
            c.source_row_number,
            c.step,
            c.knowledge_step,
            c.{ENTITY_KEY},
            CAST(c.amount AS DOUBLE) AS current_amount,
            CAST(c.step AS DOUBLE) AS event_step,
            CASE WHEN c.transaction_type = 'TRANSFER' THEN 1.0 ELSE 0.0 END
                AS transaction_type_transfer,
            {",".join(columns)}
        FROM fixture_rows AS c
        LEFT JOIN fixture_rows AS s
            ON s.{ENTITY_KEY} = c.{ENTITY_KEY}
            AND s.step >= c.step - {widest}
            AND s.step <= c.step - 1
        WHERE c.transaction_type IN ('CASH_OUT', 'TRANSFER')
            AND c.destination_entity_kind = 'CUSTOMER'
        GROUP BY
            c.source_row_number, c.step, c.knowledge_step, c.{ENTITY_KEY},
            c.amount, c.transaction_type
        ORDER BY c.step, c.source_row_number
    """


def build_feature_table() -> pa.Table:
    """Compute the twelve fields from the 15 fixture rows with DuckDB, then add ADR-006 times."""

    events = load_paysim_fixture_events()
    frame = pd.DataFrame(
        [
            {
                "source_row_number": event.source_row_number,
                "step": event.step,
                "knowledge_step": event.knowledge_step,
                "transaction_type": event.transaction_type,
                "amount": float(event.amount),
                ENTITY_KEY: event.destination_entity_id,
                "destination_entity_kind": event.destination_entity_kind,
            }
            for event in events
        ]
    )
    connection = duckdb.connect()
    connection.register("fixture_rows", frame)
    table = connection.execute(_feature_sql()).to_arrow_table().combine_chunks()
    connection.close()

    for name, column in (("event_timestamp", "step"), ("created_timestamp", "knowledge_step")):
        derived = [paysim_step_to_timestamp(value) for value in table.column(column).to_pylist()]
        table = table.append_column(
            pa.field(name, UTC_TIMESTAMP, nullable=False),
            pa.array(derived, type=UTC_TIMESTAMP),
        )
    return table


def _make_store(repo_path: Path, source_path: Path, view_name: str, fields: list):
    from feast import Entity, FeatureStore, FeatureView, FileSource, RepoConfig
    from feast.value_type import ValueType

    entity = Entity(name="destination", join_keys=[ENTITY_KEY], value_type=ValueType.STRING)
    source = FileSource(
        name="paysim_pre_decision_features",
        path=str(source_path),
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    )
    view = FeatureView(name=view_name, entities=[entity], schema=fields, source=source, ttl=None)
    config = RepoConfig(
        project="pit_spike",
        provider="local",
        registry=str(repo_path / "registry.db"),
        offline_store={"type": "duckdb"},
        online_store={"type": "sqlite", "path": str(repo_path / "online.db")},
        entity_key_serialization_version=3,
        repo_path=str(repo_path),
    )
    store = FeatureStore(config=config)
    store.apply([entity, source, view])
    return store, view


def question_2(repo_path: Path) -> None:
    banner("2", "Does Feast get_historical_features reproduce the oracle's expected vectors?")

    from feast import Field
    from feast.types import Float64, Int64

    table = build_feature_table()
    print(f"  feature table rows: {table.num_rows}")
    print(f"  feature columns   : {[c for c in table.column_names]}")

    source_path = repo_path / "pre_decision_features.parquet"
    pq.write_table(table, source_path, compression="zstd")

    expected = load_paysim_expected_features()
    print(f"  expected vectors  : {len(expected)}  (from {EXPECTED_PATH.name})")

    integer_prefixes = ("pit_prior_count", "recipient_has_history")
    fields = [
        Field(name=name, dtype=Int64 if name.startswith(integer_prefixes) else Float64)
        for name in PAYSIM_MODEL_FEATURE_ORDER
    ]
    store, _ = _make_store(repo_path, source_path, "paysim_pre_decision", fields)

    frame = table.to_pandas()
    entity_df = frame[[ENTITY_KEY, "event_timestamp", "source_row_number"]].copy()
    retrieved = store.get_historical_features(
        entity_df=entity_df,
        features=[f"paysim_pre_decision:{name}" for name in PAYSIM_MODEL_FEATURE_ORDER],
    ).to_df()

    print(f"\n  retrieved rows    : {len(retrieved)}")
    print(retrieved.to_string(max_colwidth=18))

    mismatches: list[str] = []
    for _, row in retrieved.iterrows():
        row_number = int(row["source_row_number"])
        if row_number not in expected:
            mismatches.append(f"row {row_number} has no expected vector")
            continue
        for name, expected_value in expected[row_number].items():
            actual = row[name]
            if abs(float(actual) - float(expected_value)) > 1e-6:
                mismatches.append(
                    f"row {row_number} {name}: feast {actual} != oracle {expected_value}"
                )

    missing = set(expected) - {int(v) for v in retrieved["source_row_number"]}
    for row_number in sorted(missing):
        mismatches.append(f"row {row_number} expected by the oracle but not returned by Feast")

    if mismatches:
        print("\n  field-level differences:")
        for item in mismatches:
            print(f"    {item}")
        verdict(False, f"{len(mismatches)} difference(s) between Feast retrieval and the oracle")
    else:
        verdict(
            True,
            "Feast retrieval matches the oracle on every field of every row -- and because the "
            "table was built by the SQL engine, this is two independent derivations agreeing, "
            "not a file compared against itself",
        )


# ------------------------------------------------------------------------------------------
# Q3 -- what does Feast do with a real timestamp tie?
# ------------------------------------------------------------------------------------------


def question_3(repo_path: Path) -> None:
    banner("3", "With two rows at the SAME entity and SAME event_timestamp, which one wins?")

    from feast import Field
    from feast.types import Float64

    moment = paysim_step_to_timestamp(303)
    print(f"  both rows carry event_timestamp = {moment.isoformat()}")
    print("  row A: created_timestamp = same instant, marker = 111.0")
    print("  row B: created_timestamp = same instant, marker = 222.0")
    print("  ADR-006 decision 1.4 says hour-resolution timestamps cannot express the tie-break,")
    print("  so whatever Feast returns here is a platform behaviour the project cannot control.")

    table = pa.table(
        {
            ENTITY_KEY: pa.array(["C_TIE", "C_TIE"], type=pa.string()),
            "marker": pa.array([111.0, 222.0], type=pa.float64()),
            "event_timestamp": pa.array([moment, moment], type=UTC_TIMESTAMP),
            "created_timestamp": pa.array([moment, moment], type=UTC_TIMESTAMP),
        }
    )
    source_path = repo_path / "tie.parquet"
    pq.write_table(table, source_path, compression="zstd")

    store, _ = _make_store(
        repo_path, source_path, "paysim_tie_probe", [Field(name="marker", dtype=Float64)]
    )
    entity_df = pd.DataFrame(
        {ENTITY_KEY: ["C_TIE"], "event_timestamp": [moment + timedelta(hours=1)]}
    )
    retrieved = store.get_historical_features(
        entity_df=entity_df, features=["paysim_tie_probe:marker"]
    ).to_df()

    print(f"\n  rows returned     : {len(retrieved)}")
    print(retrieved.to_string())

    if len(retrieved) != 1:
        verdict(False, f"Feast returned {len(retrieved)} rows for one entity key -- a tie fans out")
        return
    marker = float(retrieved["marker"].iloc[0])
    verdict(
        marker in (111.0, 222.0),
        f"Feast collapsed the tie to marker={marker}. Which row that is, is NOT determined by "
        "anything the project controls -- if T1 ever puts two same-step cutoffs in one feature "
        "table, this is the behaviour it inherits",
    )


# ------------------------------------------------------------------------------------------
# Q4 -- is `apply` idempotent, and what identifies the registry?
# ------------------------------------------------------------------------------------------


def question_4(repo_path: Path) -> None:
    banner("4", "What identifies the registry, and does a second apply change it?")

    from feast import Field
    from feast.types import Float64

    source_path = repo_path / "tie.parquet"
    if not source_path.exists():
        print("  Q3 did not produce a source file, so Q4 has nothing to apply. Reason above.")
        verdict(False, "skipped because Q3 failed")
        return

    store, view = _make_store(
        repo_path, source_path, "paysim_registry_probe", [Field(name="marker", dtype=Float64)]
    )
    registry_file = repo_path / "registry.db"

    def fingerprints() -> tuple[str, str]:
        file_digest = hashlib.sha256(registry_file.read_bytes()).hexdigest()
        proto_digest = hashlib.sha256(
            store.registry.proto().SerializeToString(deterministic=True)
        ).hexdigest()
        return file_digest, proto_digest

    first_file, first_proto = fingerprints()
    print(f"  registry file     : {registry_file}")
    print(f"  after apply #1    : file sha256   {first_file}")
    print(f"                      proto sha256  {first_proto}")

    store.apply([view])
    second_file, second_proto = fingerprints()
    print(f"  after apply #2    : file sha256   {second_file}")
    print(f"                      proto sha256  {second_proto}")

    print(
        "\n  NOTE: the registry proto carries `last_updated` timestamps, so a differing digest "
        "here is not by itself proof that a definition changed. Guide 3.3 wants a checksum "
        "bound to `feature_service_version`; if these digests move on a no-op apply, that "
        "checksum has to be computed over the definitions, not over the registry blob."
    )
    if first_file == second_file and first_proto == second_proto:
        verdict(True, "a no-op apply left both digests unchanged; the blob is usable as a checksum")
    else:
        verdict(
            False,
            "a no-op apply moved a digest, so the registry blob is NOT a stable identity -- the "
            "guide 3.3 checksum must be derived from the definitions instead",
        )


def main() -> int:
    print("Feast T1 spike -- throwaway probe, writes only into a temporary directory")
    print(f"project root: {PROJECT_ROOT}")
    try:
        import feast

        print(f"feast version: {feast.__version__}")
    except Exception:
        print("feast is not importable; run `uv sync --all-groups` first")
        traceback.print_exc()
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="pit-feast-spike-"))
    print(f"temp repo   : {workdir}")
    failures = 0
    try:
        for number, run in (
            ("1", question_1),
            ("2", lambda: question_2(workdir)),
            ("3", lambda: question_3(workdir)),
            ("4", lambda: question_4(workdir)),
        ):
            try:
                run()
            except Exception:
                failures += 1
                print(f"\n  >>> UNANSWERED: Q{number} raised, full traceback below.")
                print("  An unanswered question is a finding: paste this back rather than ignore.")
                traceback.print_exc()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        print(f"\ncleaned up {workdir} (exists: {workdir.exists()})")

    print(f"\nquestions that could not be answered: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
