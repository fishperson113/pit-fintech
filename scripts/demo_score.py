"""demo-score: send one normal and one suspicious transaction to a running API.

Prints each request and a readable result table. Exits 1 with a hint if the API is not running.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score two demo transactions against /score")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
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


def _print_result(
    label: str, payload: dict[str, object], status: int, body: dict[str, object]
) -> None:
    print(f"\n--- {label} ---")
    print("request:")
    print(json.dumps(payload, indent=2))
    print(f"response (HTTP {status}):")
    if status != 200:
        print(json.dumps(body, indent=2))
        return
    latency = body.get("latency_ms", {})
    rows = [
        ("prediction", body.get("prediction")),
        ("fraud_probability", f"{body.get('fraud_probability'):.6e}"),
        ("decision_threshold", f"{body.get('decision_threshold'):.6f}"),
        ("feature_status", body.get("feature_status")),
        ("feature_step", body.get("feature_step")),
        ("materialization_watermark_step", body.get("materialization_watermark_step")),
        ("staleness_steps", body.get("staleness_steps")),
        ("model_version", body.get("model_version")),
        ("feature_provider", body.get("feature_provider")),
        (
            "latency total/retrieval/inference",
            f"{latency.get('total', 0):.1f}/{latency.get('feature_retrieval', 0):.1f}/"
            f"{latency.get('model_inference', 0):.1f} ms",
        ),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"  {name:<{width}}  {value}")


def main() -> int:
    args = _parser().parse_args()
    base = f"http://{args.host}:{args.port}"
    try:
        with urllib.request.urlopen(f"{base}/health/ready", timeout=3) as response:
            ready = json.loads(response.read()).get("ready")
    except Exception:
        ready = False
    if not ready:
        print(f"API khong san sang tai {base}.")
        print("Chay truoc:  .\\make.ps1 serve   (hoac: make serve)")
        return 1

    cases = [
        (
            "giao dich BINH THUONG",
            {
                "transaction_id": "demo-score-normal",
                "step": 744,
                "transaction_type": "TRANSFER",
                "amount": "150.75",
                "name_dest": "C1470998563",
            },
        ),
        (
            "giao dich NGHI NGO",
            {
                "transaction_id": "demo-score-suspicious",
                "step": 744,
                "transaction_type": "CASH_OUT",
                "amount": "1000000",
                "name_dest": "C0000000000",
            },
        ),
    ]
    for label, payload in cases:
        status, body = _post(args.host, args.port, payload)
        _print_result(label, payload, status, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
