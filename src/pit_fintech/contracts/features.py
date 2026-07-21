"""Feature specifications and computed feature row schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeatureSpec(BaseModel):
    """A versioned declaration of one feature's source and temporal semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    entity: str = "card_entity_id"
    source: str = "silver.transactions"
    window_seconds: int | None = Field(default=None, gt=0)
    aggregation: Literal[
        "count", "sum", "mean", "max", "distinct_count", "time_since_previous", "ratio"
    ]
    event_time_column: str = "ordered_event_timestamp"
    availability: Literal["request_available", "historical_only"] = "historical_only"
    dtype: Literal["int64", "float64"]
    default: int | float
    version: str = "v1"
    owner: str = "feature-platform"


class ComputedFeatureRow(BaseModel):
    """Pre-decision vector and audit lineage for one transaction cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: int
    card_entity_id: str
    cutoff_event_timestamp: datetime
    cutoff_created_timestamp: datetime
    feature_definition_version: str
    values: dict[str, int | float]
    source_transaction_ids: tuple[int, ...] = ()
    max_source_event_timestamp: datetime | None = None
    max_source_transaction_id: int | None = None
