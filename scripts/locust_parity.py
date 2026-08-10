"""ADR-008 -- manual load + offline/online parity harness for the serving write path.

Run by hand, never via pytest (ADR-008): its value is exercising the *live* ``/score`` service
under load and concurrency, which a unit lane cannot represent. Two ways to run it:

    # 1) Load test the running service (bombard /score):
    locust -f scripts/locust_parity.py --host http://127.0.0.1:8000

    # 2) Parity check after the run (Locust event hook prints PASS/FAIL):
    #    the same file registers a test-stop listener that compares the write-path online aggregate
    #    the service maintained (serving/online_state.py, ADR-009) against the independent offline
    #    oracle (features/paysim_reference.py) at each entity's stored step. A mismatch is a real
    #    train/serve skew -- do NOT widen the tolerance to hide it (guide s8.4).

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

# Parity is checked per entity at the write path (ADR-009): after the stream was played through
# /score, each entity's stored aggregate is compared against the offline oracle reference at its
# stored step. The stream above covers window edges, a same-step pair and a late-arriving
# correction, which is what makes the compare non-trivial.


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
    """Fires the synthetic stream at /score.

    Under load Locust spawns many of these concurrently, which is what actually exercises the
    optimistic lock in the `pit-online-worker` (serving/online_state.apply_score_event).
    """

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
    """Compare the write-path online aggregate against the offline oracle at each checkpoint.

    ADR-009: parity is verified at the write path -- after the stream was played through ``/score``
    (each request transitions the entity's aggregate to post-event state), the stored aggregate is
    compared against the independent offline oracle reference for the same stored step. A mismatch
    is a real train/serve skew in the serving write path, not a copy-consistency check.
    """

    from pit_fintech.materialization.materializer import read_online_features
    from pit_fintech.serving.online_state import (
        count_parity_mismatches,
        offline_post_event_reference,
    )

    store = _store()
    failures = 0
    checked = 0
    # Distinct entities seen in the stream, in deterministic order.
    entities = list(dict.fromkeys(name_dest for _, _, _, _, name_dest in _STREAM))
    for name_dest in entities:
        read = read_online_features(store=store, entity_id=name_dest, request_step=1)
        if read.record is None:
            failures += 1
            checked += 1
            print(f"PARITY MISSING {name_dest}: no online aggregate after the stream")
            continue
        stored_step = read.record.feature_step
        stored_knowledge = read.record.feature_knowledge_step
        oracle = offline_post_event_reference(
            store=store,
            entity_id=name_dest,
            step=stored_step,
            knowledge_step=stored_knowledge,
        )
        mismatches = count_parity_mismatches(online=read.feature_values, offline=oracle)
        checked += 1
        if mismatches:
            failures += 1
            for field, online_value, oracle_value in _diff_fields(read.feature_values, oracle):
                print(
                    f"PARITY MISMATCH {name_dest}@step{stored_step} {field}: "
                    f"online={online_value} oracle={oracle_value}"
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
        telemetry.record_parity_check(checked=checked > 0, mismatches=failures)
    except Exception:  # telemetry export must never break the parity check
        pass

    if failures:
        print(
            f"PARITY FAIL: {failures} entity/field mismatch(es) out of {checked} checked "
            "-- online/offline skew (ADR-009)."
        )
    else:
        print(
            f"PARITY PASS: the online write-path aggregate matches the offline oracle at all "
            f"{checked} checkpoints (ADR-009)."
        )


def _diff_fields(online: dict, oracle: dict) -> list[tuple[str, object, object]]:
    """Return the history fields that disagree, for a readable PARITY MISMATCH line."""

    from pit_fintech.features.paysim_specs import PAYSIM_HISTORY_FEATURE_NAMES

    result: list[tuple[str, object, object]] = []
    for field in PAYSIM_HISTORY_FEATURE_NAMES:
        online_value = online[field]
        oracle_value = oracle[field]
        if "_amount_" in field:
            if abs(float(online_value) - float(oracle_value)) > 1e-6:
                result.append((field, online_value, oracle_value))
        elif online_value != oracle_value:
            result.append((field, online_value, oracle_value))
    return result


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
