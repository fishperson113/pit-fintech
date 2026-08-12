"""Stable identity for events observed by the online serving path."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal


def served_event_id(
    *,
    destination_entity_id: str,
    step: int,
    knowledge_step: int,
    transaction_type: str,
    amount: str | Decimal,
) -> str:
    """Return the idempotent identity shared by serving, Event History and Bronze."""

    identity = {
        "amount": str(amount),
        "destination_entity_id": destination_entity_id,
        "knowledge_step": int(knowledge_step),
        "step": int(step),
        "transaction_type": transaction_type,
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
