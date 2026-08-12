"""Small, dependency-free lifecycle log helper for offline/online boundaries."""

from __future__ import annotations

import logging
from typing import Any


def log_lifecycle(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit one Loki-friendly lifecycle line with deterministic key/value fields.

    The application currently exports plain-text OTLP log bodies and puts OTel context in
    structured metadata. Keeping the lifecycle event and correlation fields in the body makes them
    searchable even when a batch command has no parent trace.
    """

    values = " ".join(
        f"{key}={_render(value)}" for key, value in sorted(fields.items()) if value is not None
    )
    logger.info("%s%s", event, f" {values}" if values else "")


def _render(value: Any) -> str:
    """Render a field without whitespace so Loki line filters remain predictable."""

    return str(value).replace(" ", "_")
