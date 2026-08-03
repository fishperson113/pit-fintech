"""Exercise the real-Silver PaySim fixture builder when a local artifact exists.

``pit_fintech.data.paysim_fixture.build_paysim_temporal_fixture`` reads the real Silver
``paysim_transactions`` Delta table, so it spans a storage boundary (``pytest.mark.integration``)
and needs a PaySim application lakehouse manifest that only exists after a local
``pit data build-lakehouse --dataset paysim`` run against the full PaySim CSV. That CSV is not
committed to the repo (see ``data/raw/paysim`` handling in ``data/paysim.py``) and CI does not
produce it, so this test cannot require the manifest to always be present the way
``tests/temporal`` requires the credential-free synthetic fixture (``pit data sample``, wired
through the ``data-sample`` Make/make.ps1 prerequisite).

The chosen strategy keeps the difference visible instead of the fixture builder staying an
untested branch: skip loudly, with the builder's own actionable message, when no manifest is
found; run the real path and assert on it when one is.
"""

from __future__ import annotations

import pytest

from pit_fintech.data.paysim_fixture import (
    EXPECTED_PATH,
    SOURCE_PATH,
    build_paysim_temporal_fixture,
    load_paysim_expected_features,
    load_paysim_fixture_events,
)
from pit_fintech.features.paysim_reference import in_scoring_scope

pytestmark = pytest.mark.integration


def test_build_paysim_temporal_fixture_from_real_silver_or_skips_loudly() -> None:
    try:
        result = build_paysim_temporal_fixture()
    except FileNotFoundError as exc:
        pytest.skip(f"no local PaySim Silver artifact to build the fixture from: {exc}")

    assert result["source_rows"] > 0
    assert result["fixture_path"] == str(SOURCE_PATH)
    assert result["expected_path"] == str(EXPECTED_PATH)
    assert SOURCE_PATH.exists()
    assert EXPECTED_PATH.exists()

    events = load_paysim_fixture_events()
    expected = load_paysim_expected_features()

    # The source file is deliberately wider than the expectation file, and asserting equality
    # between the two was wrong. `select_paysim_fixture_events` fetches every row of the chosen
    # destinations (`_fetch_all`/`_fetch_window` filter on destination only) because history is
    # unfiltered by transaction type, while `compute_paysim_feature_vectors` emits a vector only
    # for rows in scoring scope (`scoring_scope_only=True` by default). So the relation to assert
    # is containment plus an exact account of the gap, not equality.
    #
    # The builder's own `_verify_round_trip` cannot catch a drift here: it applies the same
    # scoring-scope filter to both sides, so it stays green whatever the history rows do. This
    # test is the only place the two populations are pinned against each other.
    all_row_numbers = {event.source_row_number for event in events}
    in_scope = {event.source_row_number for event in events if in_scoring_scope(event)}
    history_only = all_row_numbers - in_scope

    assert set(expected) == in_scope
    assert set(expected) < all_row_numbers
    assert history_only, (
        "the fixture carries no out-of-scope history rows, so it could not expose a window bug"
    )
