"""Contract tests for the Locust write-path knowledge-time scenario."""

from __future__ import annotations

import ast
from pathlib import Path

LOCUST_SCRIPT = Path(__file__).parents[2] / "scripts" / "locust_write_path.py"


def _score_call_cutoffs() -> list[tuple[int, int]]:
    tree = ast.parse(LOCUST_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "run_write_path_sequence"
        ):
            calls: list[tuple[int, int]] = []
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if not isinstance(child.func, ast.Attribute) or child.func.attr != "_score":
                    continue
                keywords = {keyword.arg: keyword.value for keyword in child.keywords}
                step = ast.literal_eval(keywords["step"])
                knowledge_step = ast.literal_eval(keywords["knowledge_step"])
                calls.append((step, knowledge_step))
            return calls
    raise AssertionError("run_write_path_sequence was not found")


def test_locust_sequence_uses_explicit_monotonic_knowledge_time_with_delayed_events() -> None:
    cutoffs = _score_call_cutoffs()

    assert len(cutoffs) == 10
    assert all(knowledge_step >= step for step, knowledge_step in cutoffs)
    assert [knowledge_step for _, knowledge_step in cutoffs] == sorted(
        knowledge_step for _, knowledge_step in cutoffs
    )
    assert sum(knowledge_step > step for step, knowledge_step in cutoffs) >= 3
