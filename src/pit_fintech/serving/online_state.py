"""ADR-008 -- the serving-owned online write path: an independent windowed feature maintainer.

This is the second, independent implementation of the recipient-history features. The offline path
computes them with a DuckDB self-join (`features/paysim_recipient.py`); here the **serving process**
maintains them incrementally from a per-entity event log in the online store. Offline/online parity
is meaningful precisely because these two implementations are independent -- a window-eviction or
ordering bug here diverges from the offline SQL and parity catches it. When online was a
materialized copy of offline Gold, there was nothing to diverge (ADR-007).

The window semantics are copied field-for-field from the offline oracle so the two are *supposed* to
agree (`features/paysim_reference.py`): eligibility is ``prior.step < cutoff.step AND
prior.knowledge_step <= cutoff.knowledge_step``; each window keeps ``[step - w, step)``.
Money is summed as ``Decimal`` and cast to float only at the end, matching the offline
``DECIMAL(18,2)`` accumulation.

Read-before-write (AGENTS.md s11) is the caller's responsibility: score the request from
:func:`read_window_features` *before* calling :func:`apply_event`, so the served vector equals the
offline ``pre_decision_features`` of the request.

``redis`` is an optional dependency group; it is imported inside function bodies, never at module
scope.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from pit_fintech.features.paysim_reference import PAYSIM_WINDOW_STEPS
from pit_fintech.features.paysim_specs import PAYSIM_HISTORY_FEATURE_NAMES
from pit_fintech.materialization.materializer import OnlineStoreConfig

#: Per-entity event-log key. A distinct ``winlog`` prefix so it never collides with the materialized
#: aggregate records (`materialization/records.py: ONLINE_KEY_TEMPLATE`).
WINLOG_KEY_TEMPLATE: Final = "pit:{feature_service_version}:winlog:{entity}:{entity_id}"

#: Money is accumulated at this precision, matching the offline `PAYSIM_AMOUNT_DECIMAL_TYPE`.
_MONEY_QUANTUM: Final = Decimal("0.01")


@dataclass(frozen=True, slots=True, kw_only=True)
class LoggedEvent:
    """One event in an entity's online history log.

    ``knowledge_step`` is carried so the knowledge-time predicate (ADR-005 decision 5) applies at
    read time -- it is what makes a late-arriving correction visible to later cutoffs but not to
    earlier ones. On clean PaySim data ``knowledge_step == step`` and the predicate is a no-op.
    """

    step: int
    knowledge_step: int
    amount: Decimal


def winlog_key(*, store: OnlineStoreConfig, entity_id: str) -> str:
    """Build the per-entity event-log key; rejects a ``:`` in any component (injection guard)."""

    for component in (store.feature_service_version, store.entity, entity_id):
        if ":" in component:
            raise ValueError(f"winlog key component must not contain ':': {component!r}")
    return WINLOG_KEY_TEMPLATE.format(
        feature_service_version=store.feature_service_version,
        entity=store.entity,
        entity_id=entity_id,
    )


def compute_window_features(
    *,
    events: list[LoggedEvent],
    cutoff_step: int,
    cutoff_knowledge_step: int,
) -> dict[str, int | float]:
    """Compute the nine history fields from an event log, at one cutoff.

    Independent re-implementation of ``paysim_reference.compute_paysim_feature_row``'s history half:
    eligibility ``e.step < cutoff_step AND e.knowledge_step <= cutoff_knowledge_step``; each window
    ``w`` keeps ``e.step >= cutoff_step - w``. Counts are exact; amounts are summed as ``Decimal``
    and cast to float once, matching the offline ``DECIMAL(18,2)`` sum bit-for-bit within range.
    """

    eligible = [
        event
        for event in events
        if event.step < cutoff_step and event.knowledge_step <= cutoff_knowledge_step
    ]
    values: dict[str, int | float] = {}
    for window_steps in PAYSIM_WINDOW_STEPS:
        lower_bound = cutoff_step - window_steps
        window = [event for event in eligible if event.step >= lower_bound]
        prior_amount = sum((event.amount for event in window), start=Decimal("0")).quantize(
            _MONEY_QUANTUM
        )
        values[f"pit_prior_count_{window_steps}h"] = len(window)
        values[f"pit_prior_amount_{window_steps}h"] = float(prior_amount)
        values[f"recipient_has_history_{window_steps}h"] = 1 if window else 0
    # Emit in the frozen contract order (assert alignment so a spec reorder is caught here).
    ordered = {name: values[name] for name in PAYSIM_HISTORY_FEATURE_NAMES}
    if set(ordered) != set(values):
        raise RuntimeError("computed history fields do not match PAYSIM_HISTORY_FEATURE_NAMES")
    return ordered


# --------------------------------------------------------------------------------------------
# Redis event-log store
# --------------------------------------------------------------------------------------------


def _redis_client(store: OnlineStoreConfig):
    """Build a redis-py client (optional dependency; imported here)."""

    import redis as redis_py

    return redis_py.Redis(
        host=store.host,
        port=store.port,
        db=store.db,
        decode_responses=True,
        socket_connect_timeout=store.connect_timeout_seconds,
        socket_timeout=store.operation_timeout_seconds,
    )


def _decode_log(payload: str | None) -> list[LoggedEvent]:
    if payload is None:
        return []
    data = json.loads(payload)
    return [
        LoggedEvent(step=int(step), knowledge_step=int(knowledge_step), amount=Decimal(str(amount)))
        for step, knowledge_step, amount in data["events"]
    ]


def _encode_log(events: list[LoggedEvent]) -> str:
    return json.dumps(
        {"events": [[event.step, event.knowledge_step, str(event.amount)] for event in events]},
        separators=(",", ":"),
        sort_keys=True,
    )


def _evict(events: list[LoggedEvent], *, current_step: int) -> list[LoggedEvent]:
    """Drop events that no future cutoff (``>= current_step``) could read.

    The widest window is ``max(PAYSIM_WINDOW_STEPS)``; a future cutoff at step ``c >= current_step``
    reaches back to ``c - w >= current_step - w``. Keeping ``step > current_step - w`` loses nothing
    a later request could need, and bounds the log to the last ``w`` hours.
    """

    horizon = current_step - max(PAYSIM_WINDOW_STEPS)
    return [event for event in events if event.step > horizon]


def read_window_state(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    cutoff_step: int,
    cutoff_knowledge_step: int | None = None,
) -> tuple[dict[str, int | float], bool]:
    """Read one entity's log, compute its history vector, and report whether a log key existed.

    The ``present`` flag distinguishes a cold entity (no key -> ``MISSING`` / cold-start defaults,
    guide s9.4) from one whose events have all aged out of the widest window (key exists, all counts
    zero). The scoring layer needs that difference to apply the cold-start policy honestly.
    """

    client = _redis_client(store)
    payload = client.get(winlog_key(store=store, entity_id=entity_id))
    values = compute_window_features(
        events=_decode_log(payload),
        cutoff_step=cutoff_step,
        cutoff_knowledge_step=cutoff_knowledge_step
        if cutoff_knowledge_step is not None
        else cutoff_step,
    )
    return values, payload is not None


def read_window_features(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    cutoff_step: int,
    cutoff_knowledge_step: int | None = None,
) -> dict[str, int | float]:
    """Read one entity's log and compute its history vector at ``cutoff_step`` (no write)."""

    values, _present = read_window_state(
        store=store,
        entity_id=entity_id,
        cutoff_step=cutoff_step,
        cutoff_knowledge_step=cutoff_knowledge_step,
    )
    return values


def apply_event(
    *,
    store: OnlineStoreConfig,
    entity_id: str,
    step: int,
    amount: Decimal,
    knowledge_step: int | None = None,
) -> int:
    """Append one event to the entity's log and evict, atomically (guide s7.2 write safety).

    Read-modify-write on a shared store is a race, so the append is done under ``WATCH``/``MULTI``/
    ``EXEC``; a ``WatchError`` re-reads and retries. Returns the log length after the write.

    This is the online write path AGENTS.md s11 requires to run *after* scoring. It appends the
    current event as observed -- a late-arriving correction carries a ``knowledge_step`` below its
    ``step`` and the read-time predicate keeps it out of earlier cutoffs.
    """

    import redis as redis_py

    resolved_knowledge_step = knowledge_step if knowledge_step is not None else step
    client = _redis_client(store)
    key = winlog_key(store=store, entity_id=entity_id)
    deadline_retries = store.max_retries + 1
    for _attempt in range(deadline_retries):
        client.watch(key)
        events = _decode_log(client.get(key))
        events.append(LoggedEvent(step=step, knowledge_step=resolved_knowledge_step, amount=amount))
        events.sort(key=lambda event: (event.step, event.knowledge_step))
        events = _evict(events, current_step=step)
        payload = _encode_log(events)
        pipeline = client.pipeline(transaction=True)
        pipeline.multi()
        pipeline.set(key, payload)
        try:
            pipeline.execute()
            return len(events)
        except redis_py.WatchError:
            # Another writer touched the key between WATCH and EXEC; re-read and retry.
            time.sleep(0)
            continue
    raise RuntimeError(
        f"apply_event exhausted {deadline_retries} optimistic-lock attempts for {entity_id!r}"
    )


def reset_online_log(*, store: OnlineStoreConfig) -> int:
    """Delete every event-log key in this service version's namespace; return how many were removed.

    Scoped to the ``pit:<fsv>:winlog:`` prefix via ``SCAN`` -- never ``FLUSHDB`` and never another
    service version's keyspace (mirrors ``materializer.reset_online_store``).
    """

    client = _redis_client(store)
    prefix = f"pit:{store.feature_service_version}:winlog:"
    removed = 0
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=prefix + "*", count=1000)
        if keys:
            removed += client.delete(*keys)
        if cursor == 0:
            break
    return removed
