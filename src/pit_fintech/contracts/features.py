"""Feature specifications and computed feature row schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FeatureSpec(BaseModel):
    """A versioned declaration of one feature's source and temporal semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    entity: str = "card_entity_id"
    source: str = "silver.transactions"
    source_column: str | None = None
    expression: str | None = None
    window_seconds: int | None = Field(default=None, gt=0)
    aggregation: Literal[
        "identity",
        "indicator",
        "count",
        "sum",
        "mean",
        "max",
        "distinct_count",
        "time_since_previous",
        "ratio",
    ]
    event_time_column: str = "ordered_event_timestamp"
    availability: Literal["request_available", "historical_only"] = "historical_only"
    dtype: Literal["int64", "float64"]
    default: int | float
    version: str = "v1"
    owner: str = "feature-platform"


class FeatureSetContract(BaseModel):
    """Frozen application feature set plus cross-feature temporal invariants."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str
    service_version: str
    dataset: str
    entity: str
    entity_definition_version: str
    source: str
    label_source: str
    label_column: str
    scoring_transaction_types: tuple[str, ...]
    scoring_destination_kinds: tuple[str, ...]
    event_time_column: str
    event_time_unit: Literal["timestamp", "hour_ordinal"]
    tie_break_columns: tuple[str, ...]
    cutoff_policy: Literal["strict_prior_event_time"]
    same_time_policy: Literal["exclude_same_event_time"]
    created_time_policy: Literal["source_has_no_created_time", "created_time_required"]
    online_update_policy: Literal["score_then_update"]
    feature_specs: tuple[FeatureSpec, ...]
    model_feature_order: tuple[str, ...]
    forbidden_model_inputs: tuple[str, ...]
    float_tolerance: float = Field(default=1e-6, gt=0)
    owner: str = "feature-platform"

    @model_validator(mode="after")
    def validate_frozen_contract(self) -> FeatureSetContract:
        names = tuple(spec.name for spec in self.feature_specs)
        if not 10 <= len(names) <= 15:
            raise ValueError("application feature contract must contain 10 to 15 features")
        if len(set(names)) != len(names):
            raise ValueError("feature names must be unique")
        if names != self.model_feature_order:
            raise ValueError("model_feature_order must exactly match feature_specs order")
        if self.label_column not in self.forbidden_model_inputs:
            raise ValueError("label column must be a forbidden model input")
        if not self.scoring_transaction_types:
            raise ValueError("scoring_transaction_types cannot be empty")
        if not self.scoring_destination_kinds:
            raise ValueError("scoring_destination_kinds cannot be empty")
        if set(names) & set(self.forbidden_model_inputs):
            raise ValueError("model features and forbidden inputs must be disjoint")
        for spec in self.feature_specs:
            if spec.version != self.version:
                raise ValueError(f"{spec.name} does not use contract version {self.version}")
            if spec.entity != self.entity:
                raise ValueError(f"{spec.name} does not use entity {self.entity}")
            if spec.source != self.source:
                raise ValueError(f"{spec.name} does not use source {self.source}")
            if spec.event_time_column != self.event_time_column:
                raise ValueError(f"{spec.name} does not use event time {self.event_time_column}")
        return self


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
