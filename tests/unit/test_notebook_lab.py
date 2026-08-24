"""Unit tests for the shared notebook-lab split/fold helpers (no data dependency)."""

from __future__ import annotations

import pandas as pd

from pit_fintech.models.notebook_lab import (
    DEFAULT_CUTS,
    DEFAULT_TEST_WIDTH,
    DEPLOYABLE_CORE,
    PIT12,
    VAL_MAX_STEP,
    three_way_temporal_split,
    walk_forward_folds,
)


def _synthetic_frame() -> pd.DataFrame:
    # One row per step 1..800, alternating labels so every window carries both classes.
    steps = list(range(1, 801))
    return pd.DataFrame({"step": steps, "isFraud": [s % 2 for s in steps]})


def test_deployable_core_is_subset_of_model_order() -> None:
    assert all(feature in PIT12 for feature in DEPLOYABLE_CORE)
    assert "event_step" not in DEPLOYABLE_CORE  # dropped as absolute-time overfitting


def test_three_way_split_is_disjoint_and_ordered() -> None:
    frame = _synthetic_frame()
    splits = three_way_temporal_split(frame)
    assert splits["train"]["step"].max() <= 520
    assert splits["val"]["step"].min() == 521
    assert splits["val"]["step"].max() <= 631
    assert splits["test"]["step"].min() == 632
    total = sum(len(part) for part in splits.values())
    assert total == len(frame)  # partition, no overlap or loss


def test_walk_forward_folds_respect_cut_and_embargo() -> None:
    frame = _synthetic_frame()
    folds = walk_forward_folds(frame, cuts=(400,), test_width=55, embargo=168)
    fold = folds[0]
    assert fold.train["step"].max() <= 400 - 168  # embargo removes near-boundary steps
    assert fold.test["step"].min() == 401
    assert fold.test["step"].max() <= 455
    assert fold.usable


def test_walk_forward_zero_embargo_is_production_realistic() -> None:
    frame = _synthetic_frame()
    fold = walk_forward_folds(frame, cuts=(500,), test_width=55, embargo=0)[0]
    assert fold.train["step"].max() == 500  # no gap before the boundary


def test_default_cv_folds_never_enter_the_sealed_test_period() -> None:
    # Data-centric discipline: walk-forward CV/tuning must not read Test (step > VAL_MAX_STEP).
    last_test_end = max(cut + DEFAULT_TEST_WIDTH for cut in DEFAULT_CUTS)
    assert last_test_end <= VAL_MAX_STEP


def test_fold_marked_unusable_without_both_classes() -> None:
    frame = pd.DataFrame({"step": [601, 602, 603], "isFraud": [0, 0, 0]})
    fold = walk_forward_folds(frame, cuts=(600,), test_width=55, embargo=0)[0]
    assert not fold.usable  # single-class test window is skipped by callers


def test_selected_features_round_trip(tmp_path, monkeypatch) -> None:
    # Step 2 -> Step 3/4 handoff: nb09 writes the chosen set, nb10-12 read it.
    import pit_fintech.models.notebook_lab as lab

    target = tmp_path / "selected_features.json"
    monkeypatch.setattr(lab, "selected_features_path", lambda project_root=None: target)

    assert lab.load_selected_features() == list(lab.DEPLOYABLE_CORE)  # fallback before nb09 runs
    lab.save_selected_features(["current_amount", "pit_prior_count_1h"], source="test")
    assert lab.load_selected_features() == ["current_amount", "pit_prior_count_1h"]
