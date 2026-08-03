"""Small deterministic PaySim fixture extracted from real Silver, scored by the Python oracle.

Distinct from `data/sample.py`, which builds the hand-authored IEEE-CIS-style synthetic fixture
(`data/fixtures/temporal_cases.*`) that FeatureSpec v1 and its oracle (`features/reference.py`)
still depend on. This module extracts a small PaySim fixture from the *real* Silver
`paysim_transactions` Delta table instead, and scores it with the independent PaySim oracle
(`features/paysim_reference.py`) rather than SQL: if expectations were computed in SQL, a later
test comparing the production SQL path against these expectations would only compare the SQL
against itself, which is exactly the failure mode the oracle exists to rule out.

Row selection is entirely order-by-then-take against the real dataset -- no randomness, no
wall-clock sampling, and where a candidate can fail a check the candidates are walked in
lexicographic order and the first confirmed one wins -- so two runs against the same Silver
version produce byte-identical files.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import duckdb
from deltalake import DeltaTable

from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim_lakehouse import find_latest_paysim_lakehouse_manifest
from pit_fintech.features.paysim_reference import (
    PAYSIM_WINDOW_STEPS,
    PaySimSourceEvent,
    compute_paysim_feature_vectors,
)

PROJECT_ROOT: Final = Path(__file__).resolve().parents[3]
FIXTURE_DIR: Final = PROJECT_ROOT / "data" / "fixtures"
SOURCE_PATH: Final = FIXTURE_DIR / "paysim_temporal_cases.jsonl"
EXPECTED_PATH: Final = FIXTURE_DIR / "paysim_expected_features.json"

# The widest history window (168h) bounds every bounded fetch below: nothing outside
# [cutoff - RICH_MIN_STEP_SPAN, cutoff] can ever enter a vector, so nothing outside it is fetched.
RICH_MIN_STEP_SPAN: Final = max(PAYSIM_WINDOW_STEPS)
SCORABLE_TYPES: Final = ("CASH_OUT", "TRANSFER")
_SCORABLE_TYPES_SQL: Final = ", ".join(f"'{value}'" for value in SCORABLE_TYPES)


def _distinguishing_offset_bands() -> tuple[tuple[int, int], ...]:
    """Prior-step offsets, inclusive, that force the three history windows apart.

    Band `i` holds the steps inside window `i` but outside window `i - 1`, so a cutoff with at
    least one prior row in every band gets three different counts and three different sums. That
    is what makes the fixture able to catch a swapped or off-by-one window; it is written once
    here and consumed by both the SQL narrowing and the Python confirmation so the two cannot
    drift apart.
    """

    windows = sorted(PAYSIM_WINDOW_STEPS)
    if len(windows) != 3:
        raise RuntimeError(f"this fixture builder expects exactly three windows, got {windows}")
    lower_bounds = (1, *(window + 1 for window in windows[:-1]))
    return tuple(zip(lower_bounds, windows, strict=True))


_DISTINGUISHING_BANDS: Final = _distinguishing_offset_bands()
_BAND_SUMMARY: Final = ", ".join(f"[{low},{high}]" for low, high in _DISTINGUISHING_BANDS)
# Necessary conditions only, used to shrink the self-join below and nothing else: a distinguishing
# destination needs one prior row per band plus the cutoff row itself, and the band furthest from
# the cutoff fixes the smallest step span such a destination can span.
RICH_MIN_ROW_COUNT: Final = len(_DISTINGUISHING_BANDS) + 1
RICH_MIN_BAND_SPAN: Final = _DISTINGUISHING_BANDS[-1][0]
# Deterministic ceiling on how many candidates the Python confirmation may examine. Every
# candidate's rows are fetched in a single scan, so raising this widens one IN list rather than
# adding another pass over the 6.3M-row table.
RICH_CANDIDATE_LIMIT: Final = 8

_SILVER_COLUMNS: Final = (
    "source_row_number",
    "step",
    "knowledge_step",
    "transaction_type",
    "amount",
    "destination_entity_id",
    "destination_entity_kind",
)


def _resolve_silver_transactions_path(project_root: Path, artifact_root: Path) -> Path:
    """Locate the exact Silver `paysim_transactions` Delta version to extract from."""

    manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
    if manifest_path is None:
        raise FileNotFoundError(
            f"no PaySim application lakehouse manifest found under {artifact_root}; "
            "run `pit data build-lakehouse --dataset paysim` first"
        )
    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    snapshot = next(
        item
        for item in manifest.tables
        if item.layer == "silver" and item.table == "paysim_transactions"
    )
    candidate = Path(snapshot.path)
    return candidate if candidate.is_absolute() else project_root / candidate


def _connect_silver(silver_path: Path) -> duckdb.DuckDBPyConnection:
    """Register the Silver Delta table as an in-memory Arrow view.

    DuckDB here only ever selects rows; every feature value in the fixture comes from the
    pure-Python oracle in `paysim_reference.py`, never from this connection.
    """

    table = DeltaTable(silver_path.as_posix()).to_pyarrow_table()
    connection = duckdb.connect()
    connection.execute("SET preserve_insertion_order = true")
    connection.register("silver_transactions", table)
    return connection


def _pick_zero_history_destination(connection: duckdb.DuckDBPyConnection) -> str:
    """The lexicographically smallest CUSTOMER destination with exactly one scorable row."""

    row = connection.execute(
        f"""
        WITH single AS (
            SELECT destination_entity_id
            FROM silver_transactions
            WHERE destination_entity_kind = 'CUSTOMER'
            GROUP BY destination_entity_id
            HAVING count(*) = 1
        )
        SELECT s.destination_entity_id
        FROM single s
        JOIN silver_transactions t ON t.destination_entity_id = s.destination_entity_id
        WHERE t.transaction_type IN ({_SCORABLE_TYPES_SQL})
        ORDER BY s.destination_entity_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError(
            "no zero-history CUSTOMER destination with a scorable lone transaction was found"
        )
    return str(row[0])


def _rich_candidate_destinations(connection: duckdb.DuckDBPyConnection) -> list[str]:
    """CUSTOMER destinations whose own history can separate all three windows, in id order.

    The band predicates are the ones `_first_distinguishing_cutoff_step` re-derives in Python;
    running them in SQL narrows 6.3M rows to a short candidate list instead of committing the
    build to one destination that may not qualify. `busy` applies only necessary conditions, so
    it can never drop a destination that would have qualified.
    """

    band_predicates = "\n               AND ".join(
        f"max(CASE WHEN c.step - p.step BETWEEN {low} AND {high} THEN 1 ELSE 0 END) = 1"
        for low, high in _DISTINGUISHING_BANDS
    )
    rows = connection.execute(
        f"""
        WITH scoped AS (
            SELECT destination_entity_id, step, transaction_type
            FROM silver_transactions
            WHERE destination_entity_kind = 'CUSTOMER'
        ),
        busy AS (
            SELECT destination_entity_id
            FROM scoped
            GROUP BY destination_entity_id
            HAVING count(*) >= {RICH_MIN_ROW_COUNT}
               AND max(step) - min(step) >= {RICH_MIN_BAND_SPAN}
        ),
        narrowed AS (
            SELECT s.destination_entity_id, s.step, s.transaction_type
            FROM scoped s
            JOIN busy b ON b.destination_entity_id = s.destination_entity_id
        ),
        qualifying AS (
            SELECT c.destination_entity_id AS destination_entity_id
            FROM narrowed c
            JOIN narrowed p
              ON p.destination_entity_id = c.destination_entity_id
             AND c.step - p.step BETWEEN {_DISTINGUISHING_BANDS[0][0]} AND {RICH_MIN_STEP_SPAN}
            WHERE c.transaction_type IN ({_SCORABLE_TYPES_SQL})
            GROUP BY c.destination_entity_id, c.step
            HAVING {band_predicates}
        )
        SELECT destination_entity_id
        FROM qualifying
        GROUP BY destination_entity_id
        ORDER BY destination_entity_id
        LIMIT {RICH_CANDIDATE_LIMIT}
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _fetch_candidate_steps(
    connection: duckdb.DuckDBPyConnection, destinations: Sequence[str]
) -> dict[str, list[tuple[int, str]]]:
    """One scan for every candidate's `(step, transaction_type)` rows, in replay order."""

    placeholders = ", ".join("?" for _ in destinations)
    rows = connection.execute(
        f"""
        SELECT destination_entity_id, step, transaction_type
        FROM silver_transactions
        WHERE destination_entity_id IN ({placeholders})
        ORDER BY destination_entity_id, step, source_row_number
        """,
        list(destinations),
    ).fetchall()
    by_destination: dict[str, list[tuple[int, str]]] = {
        destination: [] for destination in destinations
    }
    for destination_entity_id, step, transaction_type in rows:
        by_destination[str(destination_entity_id)].append((int(step), str(transaction_type)))
    return by_destination


def _first_distinguishing_cutoff_step(rows: Sequence[tuple[int, str]]) -> int | None:
    """Earliest scorable step of one destination whose three windows each differ non-trivially.

    `rows` are that destination's `(step, transaction_type)` pairs in replay order. Walking them
    once and testing offsets against the steps already seen is deterministic, needs no
    window-function SQL, and is a second independent derivation of the SQL band predicates above.
    Returns `None` when the destination never reaches such a step, so the caller can move on to
    the next candidate instead of failing the whole build.
    """

    steps_seen: list[int] = []
    for step, transaction_type in rows:
        distinguishes = all(
            any(low <= step - seen <= high for seen in steps_seen)
            for low, high in _DISTINGUISHING_BANDS
        )
        if transaction_type in SCORABLE_TYPES and distinguishes:
            return int(step)
        steps_seen.append(int(step))
    return None


def _pick_rich_destination_cutoff(connection: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """First candidate destination, in id order, that separates all three history windows."""

    candidates = _rich_candidate_destinations(connection)
    if not candidates:
        raise RuntimeError(
            "no CUSTOMER destination in Silver reaches a scorable step with a prior row in every "
            f"window band (step offsets {_BAND_SUMMARY}, inclusive); the fixture needs one to "
            "prove the 1h/24h/168h windows are read apart, so rebuild Silver from the full "
            "PaySim snapshot -- widening the bands would delete the reason this fixture exists"
        )
    candidate_rows = _fetch_candidate_steps(connection, candidates)
    rejected: list[str] = []
    for destination_entity_id in candidates:
        rows = candidate_rows[destination_entity_id]
        cutoff_step = _first_distinguishing_cutoff_step(rows)
        if cutoff_step is not None:
            return destination_entity_id, cutoff_step
        rejected.append(f"{destination_entity_id} ({len(rows)} rows)")
    raise RuntimeError(
        f"walked {len(candidates)} candidate CUSTOMER destinations ({', '.join(rejected)}) and "
        "none reached a scorable step with a prior row in every window band (step offsets "
        f"{_BAND_SUMMARY}, inclusive). SQL narrowing accepted each of them and the Python "
        "confirmation rejected all of them, so one of the two is wrong; fix the disagreement "
        "rather than widening the bands"
    )


def _pick_same_step_pair(connection: duckdb.DuckDBPyConnection) -> tuple[str, int]:
    """A CUSTOMER destination with two same-step rows, one of them scorable.

    The strict `step <` predicate must exclude the other row of the pair from the scorable
    row's own history, even though both share the same destination and step.
    """

    row = connection.execute(
        f"""
        WITH grouped AS (
            SELECT
                destination_entity_id,
                step,
                count(*) AS row_count,
                sum(CASE WHEN transaction_type IN ({_SCORABLE_TYPES_SQL}) THEN 1 ELSE 0 END)
                    AS scorable_count
            FROM silver_transactions
            WHERE destination_entity_kind = 'CUSTOMER'
            GROUP BY destination_entity_id, step
            HAVING count(*) >= 2 AND scorable_count >= 1
        )
        SELECT destination_entity_id, step
        FROM grouped
        ORDER BY destination_entity_id, step
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("no same-step CUSTOMER-destination pair with a scorable row was found")
    return str(row[0]), int(row[1])


def _rows_to_events(rows: list[tuple[object, ...]]) -> list[PaySimSourceEvent]:
    return [
        PaySimSourceEvent.from_silver_row(dict(zip(_SILVER_COLUMNS, row, strict=True)))
        for row in rows
    ]


def _fetch_all(
    connection: duckdb.DuckDBPyConnection, destination_entity_id: str
) -> list[PaySimSourceEvent]:
    rows = connection.execute(
        f"""
        SELECT {", ".join(_SILVER_COLUMNS)}
        FROM silver_transactions
        WHERE destination_entity_id = ?
        ORDER BY step, source_row_number
        """,
        [destination_entity_id],
    ).fetchall()
    return _rows_to_events(rows)


def _fetch_window(
    connection: duckdb.DuckDBPyConnection,
    destination_entity_id: str,
    step_lower: int,
    step_upper: int,
) -> list[PaySimSourceEvent]:
    rows = connection.execute(
        f"""
        SELECT {", ".join(_SILVER_COLUMNS)}
        FROM silver_transactions
        WHERE destination_entity_id = ? AND step BETWEEN ? AND ?
        ORDER BY step, source_row_number
        """,
        [destination_entity_id, step_lower, step_upper],
    ).fetchall()
    return _rows_to_events(rows)


def select_paysim_fixture_events(silver_path: Path) -> list[PaySimSourceEvent]:
    """Deterministically select a small, real-Silver-derived multi-scenario fixture.

    Three scenarios, one destination each: a zero-history CUSTOMER destination, a destination
    whose history separately populates the 1h/24h/168h windows, and a same-step CUSTOMER-
    destination pair. Selection is order-by-then-take throughout, with the rich destination taken
    as the first id-ordered candidate that passes confirmation; nothing is sampled by run time.
    """

    connection = _connect_silver(silver_path)
    try:
        zero_history_destination = _pick_zero_history_destination(connection)
        rich_destination, rich_cutoff_step = _pick_rich_destination_cutoff(connection)
        same_step_destination, same_step = _pick_same_step_pair(connection)

        events = [
            *_fetch_all(connection, zero_history_destination),
            *_fetch_window(
                connection,
                rich_destination,
                rich_cutoff_step - RICH_MIN_STEP_SPAN,
                rich_cutoff_step,
            ),
            *_fetch_window(
                connection,
                same_step_destination,
                same_step - RICH_MIN_STEP_SPAN,
                same_step,
            ),
        ]
    finally:
        connection.close()

    by_row_number = {event.source_row_number: event for event in events}
    return sorted(by_row_number.values(), key=lambda event: event.order_key)


def _event_to_jsonable(event: PaySimSourceEvent) -> dict[str, object]:
    """Serialize `amount` as a decimal string, never a float, so reruns are byte-identical."""

    return {
        "source_row_number": event.source_row_number,
        "step": event.step,
        "knowledge_step": event.knowledge_step,
        "transaction_type": event.transaction_type,
        "amount": str(event.amount),
        "destination_entity_id": event.destination_entity_id,
        "destination_entity_kind": event.destination_entity_kind,
    }


def load_paysim_fixture_events(path: Path = SOURCE_PATH) -> list[PaySimSourceEvent]:
    events: list[PaySimSourceEvent] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    events.append(PaySimSourceEvent.model_validate_json(line))
                except Exception as exc:
                    raise ValueError(f"invalid paysim fixture row at {path}:{line_number}") from exc
    return events


def load_paysim_expected_features(path: Path = EXPECTED_PATH) -> dict[int, dict[str, int | float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(source_row_number): values for source_row_number, values in payload["vectors"].items()
    }


def _write_fixture_files(events: list[PaySimSourceEvent]) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_event_to_jsonable(event), sort_keys=True) for event in events]
    SOURCE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    vectors = {
        str(row.source_row_number): row.values for row in compute_paysim_feature_vectors(events)
    }
    payload = {"vectors": vectors}
    EXPECTED_PATH.write_text(
        json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_round_trip(events: list[PaySimSourceEvent]) -> None:
    """Re-read the files just written and confirm the oracle reproduces them exactly."""

    loaded = load_paysim_fixture_events()
    expected = load_paysim_expected_features()
    actual = {row.source_row_number: row.values for row in compute_paysim_feature_vectors(loaded)}
    if actual.keys() != expected.keys():
        raise ValueError(
            f"paysim fixture/expected transaction mismatch: {actual.keys()} != {expected.keys()}"
        )
    for source_row_number, expected_values in expected.items():
        if actual[source_row_number] != expected_values:
            raise ValueError(
                f"paysim expected vector mismatch for {source_row_number}: "
                f"{actual[source_row_number]} != {expected_values}"
            )
    if [event.source_row_number for event in loaded] != [
        event.source_row_number for event in events
    ]:
        raise ValueError("paysim fixture row order changed on reload")


def build_paysim_temporal_fixture(
    *,
    project_root: Path | None = None,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    """Extract, score with the pure-Python oracle, and write the PaySim temporal fixture."""

    from pit_fintech.config import get_settings

    project_root = (project_root or PROJECT_ROOT).resolve()
    if artifact_root is None:
        artifact_root = get_settings().artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root

    silver_path = _resolve_silver_transactions_path(project_root, artifact_root)
    events = select_paysim_fixture_events(silver_path)
    _write_fixture_files(events)
    _verify_round_trip(events)

    return {
        "source_rows": len(events),
        "silver_path": str(silver_path),
        "fixture_path": str(SOURCE_PATH),
        "expected_path": str(EXPECTED_PATH),
    }
