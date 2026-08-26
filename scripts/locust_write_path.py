"""Locust live write-path sequence: advancement, retries, gaps and late arrivals.

Run one deterministic sequence per user, then stop the user so Locust does not replay the sequence
indefinitely against an already-advanced entity::

    uv run locust -f scripts/locust_write_path.py --host http://127.0.0.1:8000 \
        --headless -u 1 -r 1 -t 30s --csv artifacts/reports/locust-write-path

Each user gets a fresh entity. Every request carries an explicit synthetic knowledge step, modeling
the trusted ingress time that a production wallet would stamp. The final four cases deliberately
have ``knowledge_step > step`` to exercise delayed/out-of-order arrival semantics. Use one user for
deterministic retry assertions; use multiple users only when deliberately testing cross-entity
concurrency.
"""

from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, task
from locust.exception import StopUser


class WritePathUser(HttpUser):
    wait_time = between(0.0, 0.05)

    def on_start(self) -> None:
        self.entity = os.environ.get("LOCUST_WRITE_ENTITY") or (
            f"CLOCUST{uuid.uuid4().hex[:10].upper()}"
        )
        self.step_702_result: dict[str, object] | None = None

    def _score(
        self,
        *,
        label: str,
        transaction_id: str,
        step: int,
        amount: str,
        expected_feature_step: int | None,
        expected_staleness: int | None,
        expected_status: str,
        knowledge_step: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "transaction_id": transaction_id,
            "step": step,
            "transaction_type": "TRANSFER",
            "amount": amount,
            "name_dest": self.entity,
        }
        if knowledge_step is not None:
            payload["knowledge_step"] = knowledge_step
        with self.client.post("/score", json=payload, name=label, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text[:500]}")
                return {}
            body = response.json()
            observed = {
                "feature_step": body.get("feature_step"),
                "staleness_steps": body.get("staleness_steps"),
                "feature_status": body.get("feature_status"),
            }
            expected = {
                "feature_step": expected_feature_step,
                "staleness_steps": expected_staleness,
                "feature_status": expected_status,
            }
            if observed != expected:
                response.failure(f"expected {expected}, got {observed}")
            return body

    @task
    def run_write_path_sequence(self) -> None:
        """Run one at-least-once/reordering sequence and stop this Locust user."""
        self._score(
            label="01 seed step 700",
            transaction_id="locust-700",
            step=700,
            knowledge_step=700,
            amount="10.00",
            expected_feature_step=None,
            expected_staleness=None,
            expected_status="missing",
        )
        self._score(
            label="02 advance step 701",
            transaction_id="locust-701",
            step=701,
            knowledge_step=701,
            amount="20.00",
            expected_feature_step=700,
            expected_staleness=1,
            expected_status="fresh",
        )
        self.step_702_result = self._score(
            label="03 advance step 702",
            transaction_id="locust-702",
            step=702,
            knowledge_step=702,
            amount="30.00",
            expected_feature_step=701,
            expected_staleness=1,
            expected_status="fresh",
        )
        retry = self._score(
            label="04 exact retry step 702",
            transaction_id="locust-702",
            step=702,
            knowledge_step=702,
            amount="30.00",
            expected_feature_step=701,
            expected_staleness=1,
            expected_status="fresh",
        )
        retry_different_id = self._score(
            label="05 retry different transaction id",
            transaction_id="locust-702-retry",
            step=702,
            knowledge_step=702,
            amount="30.00",
            expected_feature_step=701,
            expected_staleness=1,
            expected_status="fresh",
        )
        if self.step_702_result and retry:
            for field in ("fraud_probability", "feature_step", "staleness_steps", "feature_status"):
                if self.step_702_result.get(field) != retry.get(field):
                    self.environment.events.request.fire(
                        request_type="ASSERT",
                        name="retry-equivalence",
                        response_time=0,
                        response_length=0,
                        exception=AssertionError(f"exact retry differs at {field}"),
                    )
        if self.step_702_result and retry_different_id:
            for field in ("fraud_probability", "feature_step", "staleness_steps", "feature_status"):
                if self.step_702_result.get(field) != retry_different_id.get(field):
                    self.environment.events.request.fire(
                        request_type="ASSERT",
                        name="retry-identity-equivalence",
                        response_time=0,
                        response_length=0,
                        exception=AssertionError(f"different-id retry differs at {field}"),
                    )
        self._score(
            label="06 advance gap step 704",
            transaction_id="locust-704",
            step=704,
            knowledge_step=704,
            amount="40.00",
            expected_feature_step=702,
            expected_staleness=2,
            expected_status="fresh",
        )
        self._score(
            label="07 delayed step 703 knowledge 705",
            transaction_id="locust-703-late",
            step=703,
            knowledge_step=705,
            amount="35.00",
            expected_feature_step=702,
            expected_staleness=1,
            expected_status="fresh",
        )
        self._score(
            label="08 late-arrival step 701 knowledge 706",
            transaction_id="locust-701-late",
            step=701,
            amount="99.00",
            knowledge_step=706,
            expected_feature_step=700,
            expected_staleness=1,
            expected_status="fresh",
        )
        self._score(
            label="09 delayed conflicting step 702 knowledge 707",
            transaction_id="locust-702-conflict",
            step=702,
            knowledge_step=707,
            amount="999.00",
            expected_feature_step=701,
            expected_staleness=1,
            expected_status="fresh",
        )
        self._score(
            label="10 resume step 705 knowledge 708",
            transaction_id="locust-705",
            step=705,
            knowledge_step=708,
            amount="50.00",
            expected_feature_step=704,
            expected_staleness=1,
            expected_status="fresh",
        )
        print(f"LOCUST WRITE PATH PASS entity={self.entity}")
        raise StopUser
