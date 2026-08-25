from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = tuple(
    next((ROOT / "notebooks").glob(f"{number:02d}_*.ipynb")) for number in range(8, 13)
)


def _code_sources(path: Path) -> tuple[str, ...]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        "".join(cell.get("source", ()))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


def _parse_notebook_calls(path: Path) -> tuple[ast.Call, ...]:
    calls: list[ast.Call] = []
    for source in _code_sources(path):
        sanitized = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith(("%", "!"))
        )
        try:
            tree = ast.parse(sanitized)
        except SyntaxError:
            continue
        calls.extend(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    return tuple(calls)


def test_notebook_lightgbm_logger_persists_signature_and_input_example() -> None:
    for path in NOTEBOOKS:
        helper = next(
            source for source in _code_sources(path) if "def log_lightgbm_model" in source
        )
        signature_call = (
            "MLFLOW.models.infer_signature(input_example, model.predict(input_example))"
        )
        assert signature_call in helper
        assert "signature=signature" in helper
        assert "input_example=input_example" in helper
        assert 'Path("mlruns").mkdir' not in helper


def test_every_notebook_model_log_supplies_the_evaluation_input_frame() -> None:
    expected_calls = {9: 2, 10: 1, 11: 1, 12: 1}
    for path in NOTEBOOKS[1:]:
        calls = [
            call
            for call in _parse_notebook_calls(path)
            if isinstance(call.func, ast.Name) and call.func.id == "log_lgbm_evaluation"
        ]
        assert len(calls) == expected_calls[int(path.name[:2])]
        assert all(any(keyword.arg == "input_frame" for keyword in call.keywords) for call in calls)
