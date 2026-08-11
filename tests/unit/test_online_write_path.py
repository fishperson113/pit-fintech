"""Write-path aggregate transition + parity (ADR-009) -- pure logic, no Redis.

Covers `serving/online_state.py`'s pure pieces: `compute_window_features` (post-event window
aggregation), `count_parity_mismatches` (the locked integer-exact / float-1e-6 rules), the mapping
helpers, and the **two-engine parity**: the online Python computation vs the offline DuckDB SQL
engine (`_duckdb_reference_over`). The optimistic lock / WATCH-MULTI-EXEC behaviour is exercised at
runtime through the live service (ADR-009: serving parity is observed, not unit-tested), so those
paths are not faked here.
"""

from __future__ import annotations

from decimal import Decimal

from pit_fintech.serving.online_state import (
    LoggedEvent,
    _evict,
    compute_window_features,
    count_parity_mismatches,
    latest_prior_event_step,
    recompute_pre_decision_features,
)


def _event(step: int, amount: str, knowledge_step: int | None = None) -> LoggedEvent:
    return LoggedEvent(step=step, knowledge_step=knowledge_step or step, amount=Decimal(amount))


def test_post_event_state_at_step_t_is_pre_decision_history_at_t_plus_one() -> None:
    """The shift relation (GOLD_SHIFT_RELATION): post_event_state(step=t) == history(cutoff=t+1)."""
    events = [_event(1, "100.00"), _event(2, "200.00")]
    # post_event_state(step=2) == pre_decision_history(cutoff=3): the 24h window [-21,3) holds both
    # events, and the 1h window [2,3) holds the step-2 event.
    values = compute_window_features(events=events, cutoff_step=3, cutoff_knowledge_step=3)
    assert values["pit_prior_count_24h"] == 2
    assert values["pit_prior_amount_24h"] == 300.0
    assert values["recipient_has_history_24h"] == 1
    assert values["pit_prior_count_1h"] == 1
    assert values["pit_prior_amount_1h"] == 200.0
    assert values["recipient_has_history_1h"] == 1


def test_late_arrival_visible_only_from_its_knowledge_cutoff() -> None:
    """An event with knowledge_step > step is excluded before, included at/after its time."""
    events = [_event(1, "100.00"), _event(5, "999.00", knowledge_step=40)]
    # At cutoff step=6: before its knowledge time (k=5), only the step-1 event is eligible.
    before = compute_window_features(events=events, cutoff_step=6, cutoff_knowledge_step=5)
    # After its knowledge time (k=40), the late step-5 event is included too.
    after = compute_window_features(events=events, cutoff_step=6, cutoff_knowledge_step=40)
    assert before["pit_prior_amount_24h"] == 100.0
    assert after["pit_prior_amount_24h"] == 1099.0
    # The late event lands in the 1h window [5,6) once eligible.
    assert before["pit_prior_amount_1h"] == 0.0
    assert after["pit_prior_amount_1h"] == 999.0


def test_out_of_order_request_recomputes_pre_decision_cutoff() -> None:
    """An older request must not receive the newer stored aggregate (strict PIT)."""
    events = [_event(743, "100.00"), _event(745, "200.00")]

    values = recompute_pre_decision_features(
        events=events,
        request_step=744,
        request_knowledge_step=744,
    )

    assert values["pit_prior_count_1h"] == 1
    assert values["pit_prior_amount_1h"] == 100.0
    assert values["pit_prior_count_24h"] == 1


def test_duplicate_request_cutoff_excludes_duplicate_event_step() -> None:
    """A duplicate at step 745 must see step 744 history, not post-event step 745 history."""
    events = [_event(744, "100.00"), _event(745, "150.75")]

    values = recompute_pre_decision_features(
        events=events,
        request_step=745,
        request_knowledge_step=745,
    )

    assert values["pit_prior_count_1h"] == 1
    assert values["pit_prior_amount_1h"] == 100.0
    assert values["pit_prior_amount_24h"] == 100.0


def test_feature_step_is_latest_strictly_prior_event() -> None:
    events = [_event(743, "100.00"), _event(744, "151.75"), _event(745, "150.75")]

    assert latest_prior_event_step(events=events, request_step=744) == 743
    assert latest_prior_event_step(events=events, request_step=743) is None


def test_window_eviction_drops_oldest_event() -> None:
    events = [_event(1, "100.00"), _event(200, "200.00")]
    evicted = _evict(events, current_step=200)
    # Widest window is 168h: a future cutoff at step>=200 reads back to 200-168=32.
    assert [event.step for event in evicted] == [200]


def test_count_parity_mismatches_integer_exact_and_float_tolerance() -> None:
    online = {
        "pit_prior_count_1h": 1,
        "pit_prior_amount_1h": 100.0,
        "recipient_has_history_1h": 1,
        "pit_prior_count_24h": 1,
        "pit_prior_amount_24h": 100.0,
        "recipient_has_history_24h": 1,
        "pit_prior_count_168h": 1,
        "pit_prior_amount_168h": 100.0,
        "recipient_has_history_168h": 1,
    }
    offline_same = dict(online)
    assert count_parity_mismatches(online=online, offline=offline_same) == 0

    offline_diff_amount = dict(online)
    offline_diff_amount["pit_prior_amount_24h"] = 100.0000005  # within 1e-6 -> OK
    assert count_parity_mismatches(online=online, offline=offline_diff_amount) == 0

    offline_big_diff = dict(online)
    offline_big_diff["pit_prior_amount_24h"] = 100.1  # 0.1 > 1e-6 -> mismatch
    assert count_parity_mismatches(online=online, offline=offline_big_diff) == 1

    offline_count_diff = dict(online)
    offline_count_diff["pit_prior_count_24h"] = 2  # integer mismatch
    assert count_parity_mismatches(online=online, offline=offline_count_diff) == 1


def test_compute_window_features_emits_contract_order() -> None:
    from pit_fintech.features.paysim_specs import PAYSIM_HISTORY_FEATURE_NAMES

    values = compute_window_features(
        events=[_event(1, "10.00")], cutoff_step=2, cutoff_knowledge_step=2
    )
    assert tuple(values) == PAYSIM_HISTORY_FEATURE_NAMES


def test_duckdb_offline_reference_matches_online_compute() -> None:
    """Two-engine parity: the offline DuckDB engine and the online Python computation agree.

    ADR-009 two-path fan-out: parity is the comparison of online (`compute_window_features`, Python)
    vs offline (`paysim_post_event_state_sql`, DuckDB) on the same event set. ``duckdb`` is a core
    dependency, so this runs in the unit lane.
    """

    from pit_fintech.serving.online_state import _duckdb_reference_over

    events = [_event(1, "100.00"), _event(2, "200.00"), _event(5, "50.00")]
    online = compute_window_features(events=events, cutoff_step=6, cutoff_knowledge_step=5)
    offline = _duckdb_reference_over(events=events, entity_id="C1", step=5, knowledge_step=5)
    assert count_parity_mismatches(online=online, offline=offline) == 0


def test_duckdb_offline_reference_respects_knowledge_time() -> None:
    """Both engines apply the knowledge-time predicate identically (late event excluded by it)."""

    from pit_fintech.serving.online_state import _duckdb_reference_over

    # The step-30 event carries knowledge_step=42 > the current event's 41, so it must be excluded
    # from the 24h window by BOTH engines; the step-1 event is outside the 24h range.
    events = [_event(1, "100.00"), _event(30, "999.00", knowledge_step=42), _event(41, "1.00")]
    offline = _duckdb_reference_over(events=events, entity_id="C1", step=41, knowledge_step=41)
    online = compute_window_features(events=events, cutoff_step=42, cutoff_knowledge_step=41)
    assert offline["pit_prior_amount_24h"] == 1.0
    assert offline["pit_prior_count_24h"] == 1
    assert count_parity_mismatches(online=online, offline=offline) == 0
