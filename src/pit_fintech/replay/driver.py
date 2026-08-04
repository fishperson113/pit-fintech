"""T6 -- the one-producer ordered replay driver (guide s8.1).

Gate: **G6 Parity** -- "mismatch bang 0 theo tolerance tren required checkpoints" (guide s13).
**G6 is the most important gate in Sprint 2**: guide s13 states that if it does not pass, Sprint 3
is limited to debug/parity work and no cloud or dashboard may be built to cover a correctness
failure.

Guide s8.1 fixes the execution model and AGENTS.md s11 repeats it as a scope guard:

* **exactly one** logical Transaction Producer / Replay Driver -- many entities does not mean many
  producers;
* input sorted by event time with a deterministic tie-break, held in a Python iterator/generator or
  an in-memory queue;
* the driver emits one event, waits for scoring **and** the post-score commit to complete, and only
  then emits the next;
* no Kafka, RabbitMQ, Redis Streams or any external service queue in the acceptance path.

The ordering is ``(step, source_row_number)`` (ADR-002 decision 2), and it stays on the integer
ordinals: ADR-006 decision 1.4 notes that hour-resolution derived timestamps *cannot* express the
tie-break at all, because every row in one ``step`` maps to the same instant. Sorting the replay
queue by ``event_timestamp`` would therefore make the order nondeterministic -- and it is the one
mistake that would look like it worked.

.. warning::

   **The same-second tie checkpoint has never been exercised.**

   Guide s8.3 lists "at least one same-second tie case" among G6's required checkpoints. T1's
   committed feature table (``data/fixtures/paysim_feature_table.parquet``) has 11 rows carrying
   11 **distinct** ``event_timestamp`` values, so no tie has ever reached the Feast layer, the
   online store, or this driver.

   Do not assume the full-Silver Gold range contains one either. T2 measures it first --
   ``features/build_offline.py: probe_same_step_ties`` returns
   :class:`~pit_fintech.features.build_offline.SameStepTieProbe` and its result is carried on every
   build -- and T6 must read that result before claiming the checkpoint. A count of ``0`` means the
   checkpoint cannot be satisfied from that range and is a finding to report, not a checkpoint to
   quietly drop.

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayEvent:
    """One source event as the driver emits it.

    Carries the integer ordinals as the ordering authority and the derived timestamp only for
    presentation (ADR-006 decision 1.4). :attr:`order_key` mirrors
    ``paysim_reference.PaySimSourceEvent.order_key`` so the replay order and the oracle's replay
    order are the same tuple, not two definitions that happen to agree.

    ``in_scoring_scope`` records whether this event is one the contract scores at all
    (``CASH_OUT``/``TRANSFER`` to a ``CUSTOMER`` destination, ADR-003). Out-of-scope events are
    still replayed -- they update history for their destination and therefore move online state
    (``paysim_reference.in_scoring_scope`` docstring) -- they are just not scored.
    """

    source_row_number: int
    step: int
    knowledge_step: int
    event_timestamp: datetime
    transaction_type: str
    amount: float
    destination_entity_id: str
    destination_entity_kind: str
    in_scoring_scope: bool

    @property
    def order_key(self) -> tuple[int, int]:
        """``(step, source_row_number)`` -- ADR-002 decision 2."""

        return (self.step, self.source_row_number)


class ReplayHandler(Protocol):
    """What the driver calls for each event, in guide s8.1's mandatory order.

    The driver enforces the sequencing; the handler supplies the behaviour. Splitting them is what
    makes "read -> score -> update" a property of the harness rather than a convention each
    implementation is trusted to follow (ADR-003: "Online execution must be
    ``read history -> score current event -> update state``").
    """

    def read_online_state(self, event: ReplayEvent) -> dict[str, int | float]:
        """Query online features for this event's entity, strictly **before** any update."""
        ...

    def score(self, event: ReplayEvent, features: dict[str, int | float]) -> float:
        """Return a fraud probability for the event from the retrieved vector."""
        ...

    def commit_post_event_state(self, event: ReplayEvent) -> None:
        """Apply this event's post-event state, **after** scoring has completed."""
        ...

    def append_event_history(self, event: ReplayEvent, probability: float) -> None:
        """Append to the event history, after the post-event state commit (AGENTS.md s7)."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayStepResult:
    """One completed event: what was read, what was scored, what was then committed.

    :attr:`read_before_update` exists to be asserted, not merely logged. It is the machine-readable
    form of the invariant AGENTS.md s11 states as "Query/score online phai xay ra truoc khi event
    hien tai update state"; a run where any step has it ``False`` is a correctness failure whatever
    the parity numbers say.
    """

    event: ReplayEvent
    features_read: dict[str, int | float]
    fraud_probability: float | None
    prediction: int | None
    read_before_update: bool
    online_watermark_step_before: int
    online_watermark_step_after: int
    scored: bool
    read_latency_ms: float
    score_latency_ms: float
    commit_latency_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayRunResult:
    """A completed replay pass.

    :attr:`out_of_order_events` and :attr:`concurrent_emissions` must both be ``0``: the first
    proves the queue was ordered, the second proves there was genuinely one producer. Recording
    them is cheap and it is the only way "one logical producer" is evidence rather than an
    assertion in a document.
    """

    status: Literal["completed", "failed"]
    run_id: str
    started_at: datetime
    finished_at: datetime
    events_emitted: int
    events_scored: int
    events_skipped_out_of_scope: int
    out_of_order_events: int
    concurrent_emissions: int
    same_step_events_seen: int
    first_step: int
    last_step: int
    final_watermark_step: int
    wall_seconds: float


class ReplayDriver:
    """The single logical producer. One instance per acceptance run, no exceptions.

    Guide s8.1: "Replay dung dung mot logical Transaction Producer/Replay Driver. [...] Driver phat
    mot event, cho scoring va post-score commit hoan tat, roi moi phat event ke tiep."

    Sequential by construction, not by configuration: there is no concurrency knob, because a
    faster replay that overlaps events would silently break the ``read -> score -> update`` order
    that G6 exists to verify. Guide s7 permits a load/concurrency benchmark elsewhere, but it "khong
    duoc lam thay doi replay correctness mode tuan tu".
    """

    def __init__(
        self,
        *,
        events: tuple[ReplayEvent, ...],
        handler: ReplayHandler,
        run_id: str,
    ) -> None:
        """Take ownership of an already-ordered event sequence.

        Raises if ``events`` is not sorted by :attr:`ReplayEvent.order_key` -- accepting an
        unordered sequence and sorting it silently would hide a caller that built the queue by
        ``event_timestamp``, which is unordered within a ``step``.
        """

        raise NotImplementedError("T6 round-0 skeleton")

    def emit(self) -> Iterator[ReplayStepResult]:
        """Yield one completed step at a time, strictly in order.

        Each iteration performs, in this order and without overlap: read online state, score,
        commit post-event state, append to event history. The next event is not emitted until all
        four have returned.
        """

        raise NotImplementedError("T6 round-0 skeleton")

    def run(self) -> ReplayRunResult:
        """Drain the queue and return the run summary."""

        raise NotImplementedError("T6 round-0 skeleton")


def load_replay_events(
    *,
    data_root: Path,
    silver_transactions_path: Path,
    start_step: int,
    end_step: int,
) -> tuple[ReplayEvent, ...]:
    """Read a step range from Silver, sorted by ``(step, source_row_number)``.

    Sorted here, once, so :class:`ReplayDriver` can reject an unordered sequence rather than
    silently repair it. Every event in the range is returned, including out-of-scope ones: they do
    not get scored but they do move online state for their destination.
    """

    raise NotImplementedError("T6 round-0 skeleton")
