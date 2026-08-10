"""ADR-008 -- manual load + offline/online parity harness for the serving write path.

Run by hand, never via pytest (ADR-008): its value is exercising the *live* ``/score`` service
under load and concurrency, which a unit lane cannot represent. Two ways to run it:

    # 1) Load test the running service (bombard /score):
    locust -f scripts/locust_parity.py --host http://127.0.0.1:8000

    # 2) Parity check after the run (Locust event hook prints PASS/FAIL):
    #    the same file registers a test-stop listener that, for each synthetic cutoff, compares the
    #    online windowed state the service maintained (serving/online_state.py) against the
    #    independent offline oracle (features/paysim_reference.py). A mismatch is a real train/serve
    #    skew -- do NOT widen the tolerance to hide it (guide s8.4).

The synthetic stream deliberately crosses the 1h/24h/168h window edges and includes a same-step pair
and a late-arriving correction, so eviction, ordering and the knowledge-time predicate are all
exercised -- the cases a "brand new unrelated transaction" never reaches.

``locust`` is not a project dependency; install it into the serving env before running
(``.\make.ps1 tools`` on Windows / ``make tools`` on POSIX installs locust and the OTel packages in
one shot, and ``.\make.ps1 locust`` / ``make locust`` launches this harness). ``redis`` and the
offline oracle come from the project.
"""

from __future__ import annotations

import os
from decimal import Decimal

from locust import HttpUser, between, events, task

FEATURE_SERVICE_VERSION = os.environ.get("PIT_FEATURE_SERVICE_VERSION", "paysim-fraud-scoring-v2")
REDIS_HOST = os.environ.get("PIT_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("PIT_REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("PIT_REDIS_DB", "0"))

# One deterministic in-order stream. Each tuple is (step, knowledge_step, type, amount, name_dest).
# C1001 spans all three windows and ages events out; C1002 has a same-step pair; C1003 carries a
# late-arriving correction (its knowledge_step is above its step, so only later cutoffs see it).
_STREAM: list[tuple[int, int, str, str, str]] = [
    (1, 1, "TRANSFER", "100.00", "C1001"),
    (2, 2, "CASH_OUT", "200.00", "C1001"),
    (25, 25, "TRANSFER", "300.00", "C1001"),  # older-than-24h relative to step 200
    (200, 200, "CASH_OUT", "50.00", "C1001"),
    (10, 10, "TRANSFER", "10.00", "C1002"),
    (10, 10, "CASH_OUT", "20.00", "C1002"),  # same-step pair
    (11, 11, "TRANSFER", "30.00", "C1002"),
    (5, 40, "CASH_OUT", "999.00", "C1003"),  # late arrival: known at step 40, not before
    (41, 41, "TRANSFER", "1.00", "C1003"),
]

# Cutoffs to check parity at: (name_dest, cutoff_step, cutoff_knowledge_step).
_CHECKPOINTS: list[tuple[str, int, int]] = [
    ("C1001", 201, 201),
    ("C1002", 12, 12),
    ("C1003", 6, 6),  # before the late correction is known -> must NOT count it
    ("C1003", 42, 42),  # after it is known -> must count it
]


def _score_body(step: int, knowledge_step: int, txn_type: str, amount: str, name_dest: str) -> dict:
    return {
        "transaction_id": f"loc-{name_dest}-{step}-{knowledge_step}",
        "step": step,
        "knowledge_step": knowledge_step,
        "transaction_type": txn_type,
        "amount": amount,
        "name_dest": name_dest,
    }


class TransactionUser(HttpUser):
    """Fires the synthetic stream at /score. Under load Locust spawns many of these concurrently,
    which is what actually exercises the optimistic lock in serving/online_state.apply_event."""

    wait_time = between(0.0, 0.05)

    @task
    def score_one(self) -> None:
        step, knowledge_step, txn_type, amount, name_dest = _STREAM[
            self.environment.runner.user_count % len(_STREAM)
        ]
        self.client.post(
            "/score", json=_score_body(step, knowledge_step, txn_type, amount, name_dest)
        )


@events.test_start.add_listener
def seed_ordered_stream(environment, **_kwargs) -> None:
    """Send the stream once, in order, so the parity check has a deterministic online state.

    Ordered seeding is separate from the concurrent load above: parity is asserted against this
    deterministic pass, while the load users prove the lock holds under contention.
    """

    import httpx

    from pit_fintech.materialization.materializer import OnlineStoreConfig
    from pit_fintech.materialization.records import OnlineStoreKind
    from pit_fintech.serving.online_state import reset_online_log

    store = _store()
    reset_online_log(store=store)
    base_url = environment.host or "http://127.0.0.1:8000"
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        for step, knowledge_step, txn_type, amount, name_dest in _STREAM:
            client.post(
                "/score", json=_score_body(step, knowledge_step, txn_type, amount, name_dest)
            )
    _ = (OnlineStoreConfig, OnlineStoreKind)  # imported for clarity of the store shape


@events.test_stop.add_listener
def check_parity(environment, **_kwargs) -> None:
    """Compare online windowed state against the offline oracle at each checkpoint."""

    from decimal import Decimal as _D

    from pit_fintech.features.paysim_reference import (
        PaySimSourceEvent,
        compute_paysim_feature_row,
        paysim_destination_kind,
    )
    from pit_fintech.features.paysim_specs import PAYSIM_HISTORY_FEATURE_NAMES
    from pit_fintech.serving.online_state import read_window_features

    store = _store()
    # Build the oracle's event pool from the same stream (independent implementation).
    pool = [
        PaySimSourceEvent(
            source_row_number=index + 1,
            step=step,
            knowledge_step=knowledge_step,
            transaction_type=txn_type,
            amount=_D(amount),
            destination_entity_id=name_dest,
            destination_entity_kind=paysim_destination_kind(name_dest),
        )
        for index, (step, knowledge_step, txn_type, amount, name_dest) in enumerate(_STREAM)
    ]

    failures = 0
    for name_dest, cutoff_step, cutoff_knowledge_step in _CHECKPOINTS:
        online = read_window_features(
            store=store,
            entity_id=name_dest,
            cutoff_step=cutoff_step,
            cutoff_knowledge_step=cutoff_knowledge_step,
        )
        cutoff = PaySimSourceEvent(
            source_row_number=10_000,
            step=cutoff_step,
            knowledge_step=cutoff_knowledge_step,
            transaction_type="TRANSFER",
            amount=Decimal("0.00"),
            destination_entity_id=name_dest,
            destination_entity_kind=paysim_destination_kind(name_dest),
        )
        oracle = compute_paysim_feature_row(cutoff, pool).values
        for field in PAYSIM_HISTORY_FEATURE_NAMES:
            if online[field] != oracle[field]:
                failures += 1
                print(
                    f"PARITY MISMATCH {name_dest}@{cutoff_step} {field}: "
                    f"online={online[field]} oracle={oracle[field]}"
                )
    # Best-effort: export the mismatch count to the same collector the service uses, so a Grafana
    # panel can alert on parity drift. No-op unless PIT_OTEL_ENDPOINT (or the standard
    # OTEL_EXPORTER_OTLP_ENDPOINT) is set and OTel is installed in this env.
    try:
        from pit_fintech.serving.telemetry import configure_telemetry

        endpoint = os.environ.get("PIT_OTEL_ENDPOINT") or os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT"
        )
        telemetry = configure_telemetry(
            service_name="pit-fintech-parity", endpoint=endpoint, enabled=bool(endpoint)
        )
        if failures:
            telemetry.record_parity_mismatch(count=failures)
    except Exception:  # telemetry export must never break the parity check
        pass

    if failures:
        print(f"PARITY FAIL: {failures} field mismatch(es) -- online/offline skew (ADR-008).")
    else:
        print("PARITY PASS: online windowed state matches the offline oracle at all checkpoints.")


def _store():
    from pit_fintech.features.paysim_specs import PAYSIM_ENTITY
    from pit_fintech.materialization.materializer import OnlineStoreConfig
    from pit_fintech.materialization.records import OnlineStoreKind

    return OnlineStoreConfig(
        kind=OnlineStoreKind.REDIS,
        uri=f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
        feature_service_version=FEATURE_SERVICE_VERSION,
        entity=PAYSIM_ENTITY,
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
    )
