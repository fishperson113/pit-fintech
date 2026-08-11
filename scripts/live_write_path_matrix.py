"""Live write-path matrix for monotonic advancement, retries and late arrivals.

The matrix uses a fresh entity, sends requests to a running FastAPI server, asserts PIT metadata,
and writes every request/response plus failures to a Markdown evidence report.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_REPORT = Path("artifacts/reports/live-write-path-matrix.md")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the live online write-path matrix")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--entity", help="fresh debug entity; defaults to a generated value")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def _post(host: str, port: int, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://{host}:{port}/score",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _assert_response(
    label: str,
    payload: dict[str, object],
    status: int,
    body: dict[str, object],
    *,
    feature_step: int | None,
    staleness_steps: int | None,
    feature_status: str,
) -> None:
    if status != 200:
        raise AssertionError(f"{label}: expected HTTP 200, got {status}: {body}")
    observed = {
        "feature_step": body.get("feature_step"),
        "staleness_steps": body.get("staleness_steps"),
        "feature_status": body.get("feature_status"),
    }
    expected = {
        "feature_step": feature_step,
        "staleness_steps": staleness_steps,
        "feature_status": feature_status,
    }
    if observed != expected:
        raise AssertionError(f"{label}: expected {expected}, got {observed}; body={body}")


def _render(label: str, payload: dict[str, object], status: int, body: dict[str, object]) -> str:
    return "\n".join(
        [
            f"### {label}",
            "Request:",
            "```json",
            json.dumps(payload, indent=2),
            "```",
            f"HTTP status: `{status}`",
            "Response:",
            "```json",
            json.dumps(body, indent=2),
            "```",
        ]
    )


def main() -> int:
    args = _parser().parse_args()
    base = f"http://{args.host}:{args.port}"
    entity = args.entity or f"CMATRIX{uuid.uuid4().hex[:10].upper()}"
    with urllib.request.urlopen(f"{base}/health/ready", timeout=3) as response:
        ready = json.loads(response.read())
    if not ready.get("ready"):
        raise RuntimeError(f"API is not ready at {base}: {ready}")

    def payload(transaction_id: str, step: int, amount: str, **extra: object) -> dict[str, object]:
        value: dict[str, object] = {
            "transaction_id": transaction_id,
            "step": step,
            "transaction_type": "TRANSFER",
            "amount": amount,
            "name_dest": entity,
        }
        value.update(extra)
        return value

    cases: list[tuple[str, dict[str, object], int | None, int | None, str]] = [
        ("01 seed step 700", payload("matrix-700", 700, "10.00"), None, None, "missing"),
        ("02 advance step 701", payload("matrix-701", 701, "20.00"), 700, 1, "fresh"),
        ("03 advance step 702", payload("matrix-702", 702, "30.00"), 701, 1, "fresh"),
        (
            "04 exact retry step 702",
            payload("matrix-702", 702, "30.00"),
            701,
            1,
            "fresh",
        ),
        (
            "05 retry with different transaction id",
            payload("matrix-702-retry", 702, "30.00"),
            701,
            1,
            "fresh",
        ),
        ("06 advance with gap step 704", payload("matrix-704", 704, "40.00"), 702, 2, "fresh"),
        (
            "07 out-of-order step 703",
            payload("matrix-703-late", 703, "35.00"),
            702,
            1,
            "fresh",
        ),
        (
            "08 late-arrival step 701 known at 704",
            payload("matrix-701-late", 701, "99.00", knowledge_step=704),
            700,
            1,
            "fresh",
        ),
        (
            "09 conflicting same-step retry",
            payload("matrix-702-conflict", 702, "999.00"),
            701,
            1,
            "fresh",
        ),
        (
            "10 resume monotonic advancement step 705",
            payload("matrix-705", 705, "50.00"),
            704,
            1,
            "fresh",
        ),
    ]

    rendered: list[str] = [
        "# Live online write-path matrix",
        "",
        f"- Endpoint: `{base}/score`",
        f"- Entity: `{entity}`",
        "- Purpose: monotonic advancement, at-least-once retry, duplicate identity, gaps, "
        "out-of-order and late-arrival behavior.",
        "",
    ]
    responses: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for label, request, expected_step, expected_staleness, expected_status in cases:
        status, body = _post(args.host, args.port, request)
        rendered.append(_render(label, request, status, body))
        responses[label] = body
        try:
            _assert_response(
                label,
                request,
                status,
                body,
                feature_step=expected_step,
                staleness_steps=expected_staleness,
                feature_status=expected_status,
            )
        except AssertionError as exc:
            failures.append(str(exc))

    retry_pairs = [
        ("03 advance step 702", "04 exact retry step 702"),
        ("03 advance step 702", "05 retry with different transaction id"),
    ]
    for original, retry in retry_pairs:
        original_body = responses[original]
        retry_body = responses[retry]
        for field in ("fraud_probability", "feature_step", "staleness_steps", "feature_status"):
            if original_body.get(field) != retry_body.get(field):
                failures.append(
                    f"{retry}: retry field {field!r} differs from {original}: "
                    f"{original_body.get(field)!r} != {retry_body.get(field)!r}"
                )

    rendered.extend(
        [
            "## Matrix assertions",
            "",
            "- Seed request starts cold; every accepted advancing request uses the latest strictly "
            "prior event.",
            "- Exact retry and different-transaction-id retry produce identical scoring fields.",
            "- Gap step 704 reports positive staleness without reading future state.",
            "- Out-of-order and late-arrival requests do not move the stored state backward; "
            "step 705 resumes from step 704.",
            "",
            "## Result",
            "",
        ]
    )
    if failures:
        rendered.extend(["- **FAIL**", "", *[f"- {failure}" for failure in failures]])
    else:
        rendered.append("- **PASS: all live write-path matrix assertions passed.**")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n\n".join(rendered) + "\n", encoding="utf-8")
    print(f"live write-path matrix: {'FAIL' if failures else 'PASS'}")
    print(f"entity: {entity}")
    print(f"report: {args.report.resolve()}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
