from __future__ import annotations

import pytest

from pit_fintech.contracts.events import TemporalEvent
from pit_fintech.data.sample import load_expected, load_source_events


@pytest.fixture
def temporal_events() -> list[TemporalEvent]:
    return load_source_events()


@pytest.fixture
def expected_vectors() -> dict[int, dict[str, int | float]]:
    return load_expected()
