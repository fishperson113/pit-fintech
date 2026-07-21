"""Frozen Sprint 1 feature definition v1."""

from __future__ import annotations

import hashlib
import json

from pit_fintech.contracts.features import FeatureSpec

FEATURE_DEFINITION_VERSION = "fraud-history-v1"
HOUR = 60 * 60
DAY = 24 * HOUR
WEEK = 7 * DAY

FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="txn_count_1h", window_seconds=HOUR, aggregation="count", dtype="int64", default=0
    ),
    FeatureSpec(
        name="txn_count_24h", window_seconds=DAY, aggregation="count", dtype="int64", default=0
    ),
    FeatureSpec(
        name="txn_count_7d", window_seconds=WEEK, aggregation="count", dtype="int64", default=0
    ),
    FeatureSpec(
        name="amount_sum_24h", window_seconds=DAY, aggregation="sum", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="amount_mean_24h", window_seconds=DAY, aggregation="mean", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="amount_max_24h", window_seconds=DAY, aggregation="max", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="amount_sum_7d", window_seconds=WEEK, aggregation="sum", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="amount_mean_7d", window_seconds=WEEK, aggregation="mean", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="amount_max_7d", window_seconds=WEEK, aggregation="max", dtype="float64", default=0.0
    ),
    FeatureSpec(
        name="seconds_since_previous_txn",
        aggregation="time_since_previous",
        dtype="float64",
        default=-1.0,
    ),
    FeatureSpec(
        name="distinct_products_7d",
        window_seconds=WEEK,
        aggregation="distinct_count",
        dtype="int64",
        default=0,
    ),
    FeatureSpec(
        name="distinct_addresses_7d",
        window_seconds=WEEK,
        aggregation="distinct_count",
        dtype="int64",
        default=0,
    ),
    FeatureSpec(
        name="current_amount_to_mean_24h",
        window_seconds=DAY,
        aggregation="ratio",
        availability="request_available",
        dtype="float64",
        default=0.0,
    ),
)


def feature_definition_checksum(specs: tuple[FeatureSpec, ...] = FEATURE_SPECS) -> str:
    payload = [spec.model_dump(mode="json") for spec in specs]
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
