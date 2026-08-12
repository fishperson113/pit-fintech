"""Event-driven asynchronous parity consumer for the ordered online worker."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from pit_fintech.platform.lifecycle_logging import log_lifecycle

logger = logging.getLogger(__name__)


class AsyncParityConsumer:
    """Consume worker signals and run DuckDB parity outside the score/write path."""

    def __init__(
        self,
        *,
        store: Any,
        artifact_root: Path,
        telemetry: Any | None = None,
        debounce_seconds: float = 0.5,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root
        self.telemetry = telemetry
        self.debounce_seconds = debounce_seconds
        self._pending = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="pit-parity-reconcile",
            daemon=True,
        )

    def start(self) -> None:
        """Start the single background parity consumer thread."""

        self._thread.start()
        log_lifecycle(
            logger,
            "offline.parity.consumer.started",
            debounce_seconds=self.debounce_seconds,
        )

    def trigger(self, *, event_id: str | None = None) -> None:
        """Publish a parity signal without waiting for reconciliation."""

        self._pending.set()
        log_lifecycle(logger, "offline.parity.consumer.triggered", event_id=event_id)

    def stop(self, *, timeout: float = 2.0) -> None:
        """Request shutdown and wait briefly for the daemon thread."""

        self._stop.set()
        self._pending.set()
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._pending.wait()
            if self._stop.is_set():
                return
            self._pending.clear()
            self._wait_for_quiet_period()
            if self._stop.is_set():
                return
            self._reconcile_once()

    def _wait_for_quiet_period(self) -> None:
        """Coalesce event bursts so one burst produces one reconcile."""

        deadline = time.monotonic() + self.debounce_seconds
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._pending.wait(timeout=remaining):
                self._pending.clear()
                deadline = time.monotonic() + self.debounce_seconds

    def _reconcile_once(self) -> None:
        try:
            from pit_fintech.serving.online_state import reconcile_parity

            result = reconcile_parity(store=self.store, artifact_root=self.artifact_root)
            if self.telemetry is not None:
                self.telemetry.record_parity_check(
                    checked=result.checked_entities > 0,
                    mismatches=result.field_mismatches,
                )
        except Exception:
            logger.exception("offline parity reconcile failed in background consumer")
