"""Live strict-PIT regression probe for the running scoring API.

Sends a first/duplicate step-745 request and an older step-744 request, printing the exact
request/response pair and failing if either request receives current-inclusive/future metadata.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_REPORT = Path("artifacts/reports/out-of-order-debug.md")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe duplicate and out-of-order PIT behavior")
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


def _check(
    label: str,
    payload: dict[str, object],
    status: int,
    body: dict[str, object],
    expected_step: int | None,
    expected_staleness: int | None,
) -> None:
    if status != 200:
        raise AssertionError(f"{label}: expected HTTP 200, got {status}: {body}")
    observed_step = body.get("feature_step")
    observed_staleness = body.get("staleness_steps")
    if expected_step is not None:
        if body.get("feature_status") != "fresh":
            raise AssertionError(f"{label}: expected fresh feature status: {body}")
        if observed_step != expected_step:
            raise AssertionError(
                f"{label}: expected feature_step={expected_step}, got {observed_step}"
            )
        if observed_staleness != expected_staleness:
            raise AssertionError(
                f"{label}: expected staleness_steps={expected_staleness}, got {observed_staleness}"
            )
        return
    # No prior event is a valid strict-PIT result for an out-of-order request. If a prior event
    # exists, it must be strictly older than the request and have a positive distance.
    request_step = int(payload["step"])
    if observed_step is not None and int(observed_step) >= request_step:
        raise AssertionError(f"{label}: future/current feature step exposed: {body}")
    if observed_step is None:
        if body.get("feature_status") != "missing" or observed_staleness is not None:
            raise AssertionError(f"{label}: missing prior state metadata is inconsistent: {body}")
    elif not isinstance(observed_staleness, int) or observed_staleness <= 0:
        raise AssertionError(f"{label}: prior state must have positive staleness: {body}")


def _render_case(
    label: str, payload: dict[str, object], status: int, body: dict[str, object]
) -> str:
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
    entity_id = args.entity or f"CDEBUG{uuid.uuid4().hex[:10].upper()}"
    with urllib.request.urlopen(f"{base}/health/ready", timeout=3) as response:
        ready_body = json.loads(response.read())
    if not ready_body.get("ready"):
        raise RuntimeError(f"API is not ready at {base}: {ready_body}")

    cases = [
        (
            "step-743 seed event",
            {
                "transaction_id": "debug-seed-step-743",
                "step": 743,
                "transaction_type": "TRANSFER",
                "amount": "100.00",
                "name_dest": entity_id,
            },
            None,
            None,
        ),
        (
            "step-745 first write",
            {
                "transaction_id": "debug-first-step-745",
                "step": 745,
                "transaction_type": "TRANSFER",
                "amount": "150.75",
                "name_dest": entity_id,
            },
            None,
            None,
        ),
        (
            "step-745 duplicate-safe replay",
            {
                "transaction_id": "debug-duplicate-step-745",
                "step": 745,
                "transaction_type": "TRANSFER",
                "amount": "150.75",
                "name_dest": entity_id,
            },
            743,
            2,
        ),
        (
            "step-744 out-of-order replay",
            {
                "transaction_id": "debug-out-of-order-step-744",
                "step": 744,
                "transaction_type": "TRANSFER",
                "amount": "151.75",
                "name_dest": entity_id,
            },
            743,
            1,
        ),
    ]
    rendered: list[str] = [
        "# Live strict-PIT debug report",
        "",
        f"- Endpoint: `{base}/score`",
        f"- Debug entity: `{entity_id}`",
        "- Purpose: verify duplicate and out-of-order requests do not receive "
        "future-inclusive state.",
        "",
    ]
    for label, payload, expected_step, expected_staleness in cases:
        status, body = _post(args.host, args.port, payload)
        rendered.append(_render_case(label, payload, status, body))
        _check(label, payload, status, body, expected_step, expected_staleness)

    rendered.extend(
        [
            "## Result",
            "",
            "- PASS: duplicate step 745 was scored on pre-decision step 743.",
            "- PASS: older step 744 was scored on pre-decision step 743 with staleness 1.",
            "- The worker did not expose a future feature step in either response.",
            "",
        ]
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n\n".join(rendered) + "\n", encoding="utf-8")
    print("strict-PIT live probe: PASS")
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
