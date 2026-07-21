"""Canonical temporal event contract used by both offline and replay paths."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TemporalEvent(BaseModel):
    """A decision event with event-time and knowledge-time cutoffs.

    ``event_timestamp`` determines business ordering and feature windows.
    ``created_timestamp`` represents when the source record became knowable. For the
    primary dataset these values are equal; late-arrival fixtures intentionally differ.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: int = Field(ge=0)
    event_timestamp: datetime
    created_timestamp: datetime
    card_entity_id: str = Field(min_length=1)
    transaction_amount: float = Field(ge=0)
    product_code: str
    address_code: str
    label_is_fraud: int | None = Field(default=None, ge=0, le=1)

    @field_validator("event_timestamp", "created_timestamp", mode="before")
    @classmethod
    def normalize_datetime(cls, value: datetime | str) -> datetime:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @property
    def order_key(self) -> tuple[datetime, int]:
        """Strict decision order: event time first, transaction ID as tie-break."""

        return (self.event_timestamp, self.transaction_id)
