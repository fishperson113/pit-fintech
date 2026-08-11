from __future__ import annotations

import pyarrow as pa

from pit_fintech.models.paysim_gold import (
    GOLD_EXPERIMENT_MATRIX,
    evaluate_gold_matrix,
)


def test_gold_matrix_declares_e1_to_e4_and_e2_is_post_event_control() -> None:
    assert tuple(spec.experiment_id for spec in GOLD_EXPERIMENT_MATRIX) == ("E1", "E2", "E3", "E4")
    assert GOLD_EXPERIMENT_MATRIX[1].feature_set == "post_event"
    assert GOLD_EXPERIMENT_MATRIX[1].deployable is False


def test_gold_matrix_reports_precision_and_recall() -> None:
    rows = 18
    columns: dict[str, list[object]] = {
        "source_row_number": list(range(rows)),
        "step": [*range(1, 7), *range(521, 527), *range(632, 638)],
        "split": ["train"] * 6 + ["validation"] * 6 + ["test"] * 6,
        "target_label": [0, 1, 0, 1, 0, 1] * 3,
    }
    feature_names = {name for spec in GOLD_EXPERIMENT_MATRIX for name in spec.feature_names}
    for index, name in enumerate(sorted(feature_names)):
        columns[name] = [float((row + index) % 7) for row in range(rows)]

    results = evaluate_gold_matrix(pa.table(columns), max_boost_rounds=10)

    assert tuple(result.experiment_id for result in results) == ("E1", "E2", "E3", "E4")
    for result in results:
        assert 0.0 <= result.test_recall <= 1.0
        assert 0.0 <= result.test_precision <= 1.0
