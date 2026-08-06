"""T5 -- populating the online store from Gold post-event state (guide s7).

Gates: **G5 Materialization** and **G8 Recovery** (guide s13).

Guide s7.1 in one sentence: consume ``gold.post_event_state_updates`` rows with
``step <= watermark``, keep the latest per entity, and push it through Feast's ``PushSource`` /
online write path -- never by reading the newest ``pre_decision_features`` row.

Guide s7.2's five safety rules are enforced by :func:`evaluate_write`, which is deliberately
separate from the store adapters so all of them obey the same rules rather than each re-deriving
them. Redis and SQLite are both supported paths and parity must pass on both (guide s7.3).

``redis`` and ``feast`` are optional dependency groups; they are imported inside function bodies,
never at module scope.

Round-1 status (T5): the Redis backend, key layout, JSON payloads and the write-safety rules are
implemented. The SQLite backend, the G8 recovery lane (:func:`rematerialize_after_reset`) and the
Feast ``PushSource`` path (:func:`push_to_feast_online_store`) remain out of scope today.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import duckdb
from deltalake import DeltaTable

from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim_lakehouse import find_latest_paysim_lakehouse_manifest
from pit_fintech.features.build_offline import (
    GOLD_PARTITION_COLUMN,
    GOLD_POST_EVENT_TABLE,
    POST_EVENT_STATE_SCHEMA,
    POST_EVENT_TO_CONTRACT_FIELD,
    gold_table_path,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_ENTITY,
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SPECS,
    PAYSIM_HISTORY_FEATURE_NAMES,
    paysim_feature_contract_checksum,
    paysim_step_to_timestamp,
)
from pit_fintech.materialization.records import (
    FeatureStatus,
    MaterializationRunResult,
    MaterializationWriteDecision,
    MaterializationWriteOutcome,
    OnlineFeatureRecord,
    OnlineReadResult,
    OnlineStoreKind,
    RecoveryReport,
    online_record_key,
    online_run_key,
    online_watermark_key,
)

#: Writes are batched through a Redis pipeline; a batch this size keeps a round trip small while
#: keeping the number of round trips low on the full 2.7M-entity store.
_ONLINE_BATCH_SIZE: Final = 5000
#: Progress is printed at most once per this wall interval, mirroring the ``[gold +Xs]`` /
#: ``[t4 +Xs]`` style used by the other long-running lanes.
_PROGRESS_INTERVAL_SECONDS: Final = 10.0

#: The three amount fields keep their exact decimal value as a JSON *string* in the stored bytes.
#: ``str(float)`` is the shortest round-trip repr, so ``float(str(v)) == v`` exactly -- the stored
#: payload never carries the binary float representation, which is what keeps the stored bytes
#: deterministic (AGENTS.md: "tat dinh lam invariant").
AMOUNT_CONTRACT_FIELDS: Final = frozenset(
    name for name in PAYSIM_HISTORY_FEATURE_NAMES if "_amount_" in name
)

#: The Gold post-event columns an online record actually needs. ``event_timestamp`` and
#: ``created_timestamp`` are deliberately excluded: ADR-006 decision 1.7 fixes exactly one
#: implementation of the affine step -> timestamp map, and it lives in Python
#: (``paysim_step_to_timestamp``), so the record derives its timestamps there instead of trusting
#: bytes a machine-local SQL session produced (build_offline trap 2).
_GOLD_RECORD_PROJECTION: Final = ", ".join(
    column.name
    for column in POST_EVENT_STATE_SCHEMA
    if column.name not in (GOLD_PARTITION_COLUMN, "event_timestamp", "created_timestamp")
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlineStoreConfig:
    """Which store, where, and under which service version's keyspace.

    ``stale_after_steps`` is the freshness boundary: a read whose ``request_step`` exceeds the
    record's ``feature_step`` by more than this is reported ``STALE`` rather than ``FRESH``.
    Default ``1`` follows directly from the shift relation in
    ``features/build_offline.py: GOLD_SHIFT_RELATION`` -- post-event state at step ``s`` is exactly
    the pre-decision history of a cutoff at ``s + 1``, and beyond that the window no longer lines
    up. Widening it is a policy decision that must be recorded, not a tuning knob to quiet a parity
    failure.

    ``host``/``port``/``db`` are the Redis endpoint; the defaults match the repo ``compose.yaml``
    service (``127.0.0.1:6379``, database 0). ``uri`` is kept for the run result's ``store_uri``
    and for the Feast online-store wiring later.
    """

    kind: OnlineStoreKind
    uri: str
    feature_service_version: str
    entity: str
    stale_after_steps: int = 1
    connect_timeout_seconds: float = 2.0
    operation_timeout_seconds: float = 2.0
    max_retries: int = 2
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0


# --------------------------------------------------------------------------------------------
# Redis plumbing
# --------------------------------------------------------------------------------------------


def _redis_client(store: OnlineStoreConfig):
    """Build the redis-py client for ``store``.

    The SQLite backend is deliberately not implemented yet; the T5 round-1 lane is Redis only
    (guide s7.3 parity on SQLite is a later task). ``redis`` is an optional dependency group, so it
    is imported here, inside the function body.
    """

    if store.kind is not OnlineStoreKind.REDIS:
        raise NotImplementedError(
            f"T5 round-1: only the REDIS backend is implemented (got {store.kind.value!r})"
        )
    import redis as redis_py

    return redis_py.Redis(
        host=store.host,
        port=store.port,
        db=store.db,
        decode_responses=True,
        socket_connect_timeout=store.connect_timeout_seconds,
        socket_timeout=store.operation_timeout_seconds,
    )


def _record_payload(record: OnlineFeatureRecord, *, include_run_metadata: bool = True) -> str:
    """Canonical JSON for one online record.

    Field names in the JSON are exactly the dataclass field names. Datetimes become ISO-8601
    strings; the three amount fields become decimal strings (never binary floats). Keys are sorted
    and separators are minimal so the same record always serializes to the same bytes -- the
    determinism the source checksum and G8's byte-equivalence both rely on.

    ``include_run_metadata=False`` drops the two run-local fields (``materialization_run_id``,
    ``written_at``) so the source checksum is a property of the Gold content plus the watermark,
    not of when a particular run happened to execute.
    """

    payload: dict[str, object] = {}
    for field in fields(OnlineFeatureRecord):
        if not include_run_metadata and field.name in (
            "materialization_run_id",
            "written_at",
        ):
            continue
        value = getattr(record, field.name)
        if field.name == "feature_values":
            value = {
                name: str(value) if name in AMOUNT_CONTRACT_FIELDS else value
                for name, value in value.items()
            }
        elif isinstance(value, datetime):
            value = value.isoformat()
        payload[field.name] = value
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _record_from_payload(payload: str) -> OnlineFeatureRecord:
    """Parse :func:`_record_payload` output back into a record (exact round trip)."""

    data = json.loads(payload)
    data["feature_values"] = {
        name: float(value) if name in AMOUNT_CONTRACT_FIELDS else value
        for name, value in data["feature_values"].items()
    }
    for name in ("feature_timestamp", "materialization_watermark", "written_at"):
        data[name] = datetime.fromisoformat(data[name])
    return OnlineFeatureRecord(**data)


def _contract_defaults() -> dict[str, int | float]:
    """The contract defaults for the nine history fields (counts 0, amounts 0.0, flags 0)."""

    return {
        spec.name: spec.default
        for spec in PAYSIM_FEATURE_SPECS
        if spec.name in PAYSIM_HISTORY_FEATURE_NAMES
    }


# --------------------------------------------------------------------------------------------
# Gold read + materialize
# --------------------------------------------------------------------------------------------


def _resolve_gold_post_event(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    gold_post_event_version: int | None,
) -> tuple[Path, int]:
    """Resolve the committed Gold post-event table and pin its version at run start.

    The table lives at ``<data_root>/lakehouse/paysim1/<raw_sha256[:16]>/gold/<table>``; the
    snapshot prefix comes from the same lakehouse manifest the rest of the repo resolves Silver
    through (``features/build_offline.py: gold_table_path`` is reused, never re-typed). The version
    is pinned once here -- guide s7.1: the run stays bound to the version resolved when it began,
    even if Gold ``latest`` moves during it.
    """

    manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
    if manifest_path is None:
        raise FileNotFoundError(
            "no PaySim lakehouse manifest found; build Gold before materializing"
        )
    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    table_path = gold_table_path(
        data_root=data_root,
        snapshot_prefix=manifest.raw_file_sha256[:16],
        table=GOLD_POST_EVENT_TABLE,
    )
    if not (table_path / "_delta_log").exists():
        raise FileNotFoundError(f"Gold post-event table missing at {table_path}; build Gold first")
    version = (
        gold_post_event_version
        if gold_post_event_version is not None
        else DeltaTable(str(table_path)).version()
    )
    return table_path, version


def materialize_to_watermark(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    store: OnlineStoreConfig,
    watermark_step: int,
    run_id: str,
    gold_post_event_version: int | None = None,
) -> MaterializationRunResult:
    """Consume post-event state up to ``watermark_step`` and write the latest state per entity.

    Gate G5 -- "latest feature state dung watermark/version". Pins the Gold table version at run
    start and keeps using it even if Gold ``latest`` advances mid-run (guide s7.1). Every candidate
    write goes through :func:`evaluate_write` first, so no rule in guide s7.2 can be bypassed by a
    fast path.

    ``gold_post_event_version=None`` resolves the current version once, at the start, and records
    it; passing a version explicitly re-materializes a historical state, which is what G10's
    time-travel evidence and G8's recovery path both need.
    """

    if watermark_step < 1:
        raise ValueError(f"watermark_step must be >= 1, got {watermark_step}")
    started_at = datetime.now(UTC)
    progress_started = time.perf_counter()
    last_report = progress_started

    def report(message: str, force: bool = False) -> None:
        nonlocal last_report
        now = time.perf_counter()
        if force or now - last_report >= _PROGRESS_INTERVAL_SECONDS:
            print(
                f"[materialize +{now - progress_started:8.1f}s] {message}",
                flush=True,
            )
            last_report = now

    project_root = project_root.resolve()
    data_root = data_root.resolve()
    artifact_root = artifact_root.resolve()

    report("resolving gold.post_event_state_updates", force=True)
    table_path, version = _resolve_gold_post_event(
        project_root=project_root,
        data_root=data_root,
        artifact_root=artifact_root,
        gold_post_event_version=gold_post_event_version,
    )
    report(f"reading gold v{version} up to watermark step {watermark_step}")
    source_table = DeltaTable(str(table_path), version=version).to_pyarrow_table()

    report("computing latest post-event state per entity")
    connection = duckdb.connect()
    connection.register("gold_post_event", source_table)
    try:
        latest = connection.execute(
            f"""
            SELECT {_GOLD_RECORD_PROJECTION}
            FROM (
                SELECT *,
                       row_number() OVER (
                           PARTITION BY {PAYSIM_ENTITY}
                           ORDER BY step DESC, source_row_number DESC
                       ) AS _rn
                FROM gold_post_event
                WHERE step <= {watermark_step}
            ) AS ranked
            WHERE _rn = 1
            ORDER BY {PAYSIM_ENTITY}
            """
        ).fetch_arrow_table()
    finally:
        connection.close()
    report(f"latest-per-entity rows: {latest.num_rows:,}")

    previous_watermark = read_watermark(store=store)
    if previous_watermark is not None:
        report(f"previous watermark: step {previous_watermark[0]}")

    client = _redis_client(store)
    watermark_key = online_watermark_key(feature_service_version=store.feature_service_version)
    run_key = online_run_key(feature_service_version=store.feature_service_version)

    written_at = datetime.now(UTC)
    checksum_hasher = hashlib.sha256()
    contract_checksum = paysim_feature_contract_checksum()
    written = 0
    noop = 0
    rejected = 0
    future_writes = 0
    rejected_by_outcome: dict[str, int] = {}
    candidates = 0
    max_feature_step = 0

    for batch in latest.to_batches(max_chunksize=_ONLINE_BATCH_SIZE):
        rows = batch.to_pylist()
        records = [
            post_event_row_to_record(
                row=row,
                feature_service_version=store.feature_service_version,
                feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
                feature_contract_checksum=contract_checksum,
                entity=store.entity,
                watermark_step=watermark_step,
                gold_post_event_version=version,
                source_checksum="",
                materialization_run_id=run_id,
                written_at=written_at,
            )
            for row in rows
        ]
        keys = [
            online_record_key(
                feature_service_version=record.feature_service_version,
                entity=record.entity,
                entity_id=record.entity_id,
            )
            for record in records
        ]
        payloads = [_record_payload(record) for record in records]
        for record in records:
            # Source checksum covers the content fields only (no run-local metadata), so the
            # same Gold version + watermark always yields the same checksum.
            checksum_hasher.update(
                _record_payload(record, include_run_metadata=False).encode("utf-8")
            )

        stored_payloads = client.mget(keys)
        to_write: list[tuple[str, str]] = []
        for record, key, payload, stored_payload in zip(
            records, keys, payloads, stored_payloads, strict=True
        ):
            candidates += 1
            max_feature_step = max(max_feature_step, record.feature_step)
            stored = _record_from_payload(stored_payload) if stored_payload is not None else None
            decision = evaluate_write(
                incoming=record,
                stored=stored,
                watermark_step=watermark_step,
            )
            if decision.outcome is MaterializationWriteOutcome.WRITTEN:
                written += 1
                to_write.append((key, payload))
            elif decision.outcome is MaterializationWriteOutcome.NOOP_IDENTICAL:
                noop += 1
            else:
                rejected += 1
                rejected_by_outcome[decision.outcome.value] = (
                    rejected_by_outcome.get(decision.outcome.value, 0) + 1
                )
                if decision.outcome is MaterializationWriteOutcome.REJECTED_FUTURE:
                    future_writes += 1

        if to_write:
            pipeline = client.pipeline(transaction=True)
            for key, payload in to_write:
                pipeline.set(key, payload)
            pipeline.execute()
        report(f"batch done: {written:,} written / {noop:,} noop / {rejected:,} rejected")

    source_checksum = checksum_hasher.hexdigest()
    report(f"records evaluated: {candidates:,}; source checksum {source_checksum[:16]}…")

    # Run metadata first, watermark last: the watermark is the single "materialization finished"
    # signal, so it is written only after every record and the run marker are durable.
    run_payload = json.dumps(
        {
            "run_id": run_id,
            "status": "completed",
            "feature_service_version": store.feature_service_version,
            "gold_post_event_version": version,
            "gold_post_event_path": str(table_path),
            "source_checksum": source_checksum,
            "watermark_step": watermark_step,
            "records_written": written,
            "finished_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    client.set(run_key, run_payload)
    watermark_payload = json.dumps(
        {
            "step": watermark_step,
            "timestamp": paysim_step_to_timestamp(watermark_step).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    client.set(watermark_key, watermark_payload)
    report(f"watermark step {watermark_step} written", force=True)

    finished_at = datetime.now(UTC)
    wall_seconds = time.perf_counter() - progress_started
    manifest_path = _write_materialization_manifest(
        artifact_root=artifact_root,
        run_id=run_id,
        payload={
            "status": "completed",
            "run_id": run_id,
            "store_kind": store.kind.value,
            "store_uri": store.uri or f"redis://{store.host}:{store.port}/{store.db}",
            "feature_service_version": store.feature_service_version,
            "feature_definition_version": PAYSIM_FEATURE_DEFINITION_VERSION,
            "feature_contract_checksum": paysim_feature_contract_checksum(),
            "gold_post_event_version": version,
            "gold_post_event_path": str(table_path),
            "source_checksum": source_checksum,
            "watermark_step": watermark_step,
            "previous_watermark_step": previous_watermark[0]
            if previous_watermark is not None
            else None,
            "entities_considered": candidates,
            "records_written": written,
            "records_noop": noop,
            "records_rejected": rejected,
            "rejected_by_outcome": rejected_by_outcome,
            "max_written_feature_step": max_feature_step,
            "future_writes_attempted": future_writes,
            "rebuilt_from_empty": previous_watermark is None,
            "wall_seconds": round(wall_seconds, 6),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        },
    )

    return MaterializationRunResult(
        status="completed",
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        store=store.kind,
        store_uri=store.uri or f"redis://{store.host}:{store.port}/{store.db}",
        feature_service_version=store.feature_service_version,
        feature_definition_version=PAYSIM_FEATURE_DEFINITION_VERSION,
        feature_contract_checksum=paysim_feature_contract_checksum(),
        gold_post_event_version=version,
        gold_post_event_path=str(table_path),
        source_checksum=source_checksum,
        watermark_step=watermark_step,
        watermark_timestamp=paysim_step_to_timestamp(watermark_step),
        previous_watermark_step=previous_watermark[0] if previous_watermark else None,
        entities_considered=candidates,
        records_written=written,
        records_noop=noop,
        records_rejected=rejected,
        rejected_by_outcome=rejected_by_outcome,
        max_written_feature_step=max_feature_step,
        future_writes_attempted=future_writes,
        rebuilt_from_empty=previous_watermark is None,
        wall_seconds=wall_seconds,
        manifest_path=str(manifest_path),
    )


def _write_materialization_manifest(
    *, artifact_root: Path, run_id: str, payload: dict[str, object]
) -> Path:
    """Persist the run's own manifest under ``<artifact_root>/runs/<run_id>/``."""

    destination = artifact_root.resolve() / "runs" / run_id / "materialization-manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


# --------------------------------------------------------------------------------------------
# Write-safety rules and store adapters
# --------------------------------------------------------------------------------------------


def evaluate_write(
    *,
    incoming: OnlineFeatureRecord,
    stored: OnlineFeatureRecord | None,
    watermark_step: int,
) -> MaterializationWriteDecision:
    """Apply all five guide s7.2 safety rules to one candidate write.

    The rules, and the outcome each produces:

    * ``incoming.feature_step > watermark_step`` -> ``REJECTED_FUTURE``
      ("Khong materialize future row so voi watermark").
    * ``stored is not None and incoming.feature_step < stored.feature_step`` -> ``REJECTED_OLDER``
      ("Older write khong overwrite newer record").
    * identical version and feature step, identical values -> ``NOOP_IDENTICAL``
      ("Same version/timestamp write idempotent").
    * a differing ``feature_service_version`` -> ``REJECTED_VERSION_MISMATCH``
      ("Different feature version khong silently overwrite"); the key namespace should have made
      this unreachable, so reaching it means a key was built outside ``online_record_key``.
    * otherwise -> ``WRITTEN``.

    Pure decision, no I/O, so it is directly unit-testable -- which matters because these five
    lines are what stop an out-of-order replay from corrupting online state.
    """

    common = {
        "entity_id": incoming.entity_id,
        "incoming_feature_step": incoming.feature_step,
        "stored_feature_step": stored.feature_step if stored is not None else None,
        "watermark_step": watermark_step,
        "incoming_feature_service_version": incoming.feature_service_version,
        "stored_feature_service_version": (
            stored.feature_service_version if stored is not None else None
        ),
    }
    if incoming.feature_step > watermark_step:
        return MaterializationWriteDecision(
            outcome=MaterializationWriteOutcome.REJECTED_FUTURE,
            reason=(
                f"incoming feature_step {incoming.feature_step} exceeds watermark {watermark_step}"
            ),
            **common,
        )
    if stored is not None and incoming.feature_step < stored.feature_step:
        return MaterializationWriteDecision(
            outcome=MaterializationWriteOutcome.REJECTED_OLDER,
            reason=(
                f"incoming feature_step {incoming.feature_step} is older than stored "
                f"{stored.feature_step}"
            ),
            **common,
        )
    if (
        stored is not None
        and stored.feature_service_version == incoming.feature_service_version
        and stored.feature_step == incoming.feature_step
        and stored.feature_values == incoming.feature_values
    ):
        return MaterializationWriteDecision(
            outcome=MaterializationWriteOutcome.NOOP_IDENTICAL,
            reason=("same service version, feature_step and values; write is idempotent"),
            **common,
        )
    if stored is not None and (stored.feature_service_version != incoming.feature_service_version):
        return MaterializationWriteDecision(
            outcome=MaterializationWriteOutcome.REJECTED_VERSION_MISMATCH,
            reason=(
                f"stored version {stored.feature_service_version!r} differs from incoming "
                f"{incoming.feature_service_version!r}"
            ),
            **common,
        )
    return MaterializationWriteDecision(
        outcome=MaterializationWriteOutcome.WRITTEN,
        reason="incoming is newer than stored; accepted",
        **common,
    )


def write_record(
    *,
    store: OnlineStoreConfig,
    record: OnlineFeatureRecord,
    watermark_step: int,
) -> MaterializationWriteDecision:
    """Write one record through :func:`evaluate_write`, atomically per key.

    Read-modify-write on a shared store is a race, so the comparison and the write are one
    operation (a Redis transaction / SQLite ``BEGIN IMMEDIATE``). Without that, two concurrent
    writers can both read an older stored step and both decide they are newer. Redis implements
    the atomicity with ``WATCH`` + ``MULTI``/``EXEC``; a ``WatchError`` restarts the round.
    """

    client = _redis_client(store)
    key = online_record_key(
        feature_service_version=record.feature_service_version,
        entity=record.entity,
        entity_id=record.entity_id,
    )
    payload = _record_payload(record)
    import redis as redis_py

    while True:
        client.watch(key)
        stored_payload = client.get(key)
        stored = _record_from_payload(stored_payload) if stored_payload is not None else None
        decision = evaluate_write(
            incoming=record,
            stored=stored,
            watermark_step=watermark_step,
        )
        if decision.outcome is not MaterializationWriteOutcome.WRITTEN:
            client.unwatch()
            return decision
        pipeline = client.pipeline(transaction=True)
        pipeline.multi()
        pipeline.set(key, payload)
        try:
            pipeline.execute()
            return decision
        except redis_py.WatchError:
            # Another writer touched the key between WATCH and EXEC; re-read and re-decide.
            continue


def read_online_features(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    request_step: int,
) -> OnlineReadResult:
    """Read one entity's state and classify its freshness against ``request_step``.

    A missing entity returns the contract defaults with ``status = MISSING`` -- guide s7.2:
    "Missing entity tra defaults + explicit ``feature_status``, khong gia vo fresh." Staleness is a
    step distance (ADR-002 decision 1: ``step`` is an hour ordinal), never a wall-clock age.
    """

    started = time.perf_counter()
    client = _redis_client(store)
    key = online_record_key(
        feature_service_version=store.feature_service_version,
        entity=store.entity,
        entity_id=entity_id,
    )
    payload = client.get(key)
    latency_ms = (time.perf_counter() - started) * 1000.0
    if payload is None:
        return OnlineReadResult(
            entity_id=entity_id,
            status=FeatureStatus.MISSING,
            record=None,
            feature_values=_contract_defaults(),
            staleness_steps=None,
            read_latency_ms=latency_ms,
        )
    record = _record_from_payload(payload)
    staleness_steps = request_step - record.feature_step
    status = (
        FeatureStatus.FRESH if staleness_steps <= store.stale_after_steps else FeatureStatus.STALE
    )
    return OnlineReadResult(
        entity_id=entity_id,
        status=status,
        record=record,
        feature_values=record.feature_values,
        staleness_steps=staleness_steps,
        read_latency_ms=latency_ms,
    )


def read_watermark(*, store: OnlineStoreConfig) -> tuple[int, datetime] | None:
    """Current global watermark as ``(step, derived timestamp)``, or ``None`` if never set."""

    client = _redis_client(store)
    payload = client.get(
        online_watermark_key(feature_service_version=store.feature_service_version)
    )
    if payload is None:
        return None
    data = json.loads(payload)
    return int(data["step"]), datetime.fromisoformat(data["timestamp"])


def reset_online_store(*, store: OnlineStoreConfig) -> int:
    """Delete every key in this service version's namespace and return how many were removed.

    Scoped to the ``pit:<feature_service_version>:`` prefix, never a ``FLUSHDB``: another service
    version's keyspace in the same Redis is not this run's to destroy, and G8's evidence is about
    rebuilding *this* namespace. ``SCAN`` iterates without blocking the server the way ``KEYS``
    would on a large store.
    """

    client = _redis_client(store)
    prefix = f"pit:{store.feature_service_version}:"
    removed = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=prefix + "*", count=1000)
        if keys:
            removed += client.delete(*keys)
        if cursor == 0:
            break
    return removed


def rematerialize_after_reset(
    *,
    project_root: Path,
    data_root: Path,
    artifact_root: Path,
    store: OnlineStoreConfig,
    watermark_step: int,
    run_id: str,
    gold_post_event_version: int,
) -> RecoveryReport:
    """Gate G8 -- "Redis reset roi rematerialize thanh cong".

    Snapshots the store, resets it, re-runs materialization at the same pinned Gold version and
    watermark, then compares record by record. Completing is not the gate: the rebuilt store must
    be equivalent to the one that was wiped, and :attr:`RecoveryReport.differing_entities` names
    every entity where it was not.
    """

    # T5 round-1: out of scope today -- the G8 recovery lane needs the snapshot/compare harness on
    # top of reset + materialize, which are both implemented. Left as an explicit gap, not a stub.
    raise NotImplementedError("T5 round-1: G8 recovery lane is out of scope today")


def push_to_feast_online_store(
    *,
    store: OnlineStoreConfig,
    records: tuple[OnlineFeatureRecord, ...],
    feature_view_name: str,
) -> int:
    """Write records through Feast's ``PushSource`` / online write path (guide s3.2, s7.1).

    ``feature_repo/definitions.py`` deliberately does not define a ``PushSource`` yet -- its
    docstring records that as locked-out T1 scope, with the online write path left to T5. Adding it
    is this task's work, and it must keep the same schema for batch and online paths (guide s3.2),
    otherwise offline and online vectors stop being comparable and G6 has nothing to measure.

    Feast is an optional dependency group; import it inside the body.
    """

    # T5 round-1: out of scope today -- the Redis backend is the materialization path; the Feast
    # PushSource definition (feature_repo) and this adapter are the follow-up.
    raise NotImplementedError("T5 round-1: Feast PushSource path is out of scope today")


def post_event_row_to_record(
    *,
    row: dict[str, object],
    feature_service_version: str,
    feature_definition_version: str,
    feature_contract_checksum: str,
    entity: str,
    watermark_step: int,
    gold_post_event_version: int,
    source_checksum: str,
    materialization_run_id: str,
    written_at: datetime,
) -> OnlineFeatureRecord:
    """Map one ``gold.post_event_state_updates`` row onto an online record.

    Renames the nine ``post_*`` fields to their contract names through
    ``features/build_offline.py: POST_EVENT_TO_CONTRACT_FIELD``. That map is the single crossing
    point between the two vocabularies, and going around it re-opens exactly the leakage the rename
    was introduced to make impossible.
    """

    feature_values: dict[str, int | float] = {}
    for post_name, contract_name in POST_EVENT_TO_CONTRACT_FIELD.items():
        value = row[post_name]
        assert isinstance(value, (int, float))
        feature_values[contract_name] = value
    step = int(row["step"])
    return OnlineFeatureRecord(
        entity_id=str(row[PAYSIM_ENTITY]),
        entity=entity,
        feature_service_version=feature_service_version,
        feature_definition_version=feature_definition_version,
        feature_contract_checksum=feature_contract_checksum,
        feature_values=feature_values,
        feature_step=step,
        feature_timestamp=paysim_step_to_timestamp(step),
        feature_knowledge_step=int(row["knowledge_step"]),
        materialization_watermark_step=watermark_step,
        materialization_watermark=paysim_step_to_timestamp(watermark_step),
        source_row_number=int(row["source_row_number"]),
        source_checksum=source_checksum,
        gold_post_event_version=gold_post_event_version,
        materialization_run_id=materialization_run_id,
        written_at=written_at,
    )
