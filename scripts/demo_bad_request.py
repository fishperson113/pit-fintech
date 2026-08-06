"""demo-bad: prove invalid requests never reach the scoring path.

Reads the in-process /metrics counters, sends one valid request, then three invalid ones,
and shows that requests_total only moves for the valid request while errors_total stays 0.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

HOST = "127.0.0.1"
PORT = 8000


def _metrics() -> dict[str, int]:
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/metrics", timeout=5) as response:
        text = response.read().decode("utf-8")
    values: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in (
            "pit_scoring_requests_total",
            "pit_scoring_errors_total",
            "pit_scoring_latency_ms_avg",
        ):
            values[parts[0]] = int(float(parts[1]))
    return values


def _post(payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}/score",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _detail(body: dict[str, object]) -> str:
    details = body.get("detail")
    if isinstance(details, list) and details:
        first = details[0]
        if isinstance(first, dict):
            return f"{first.get('msg', '')}  (loc={first.get('loc')})"
    return json.dumps(body)


def main() -> int:
    try:
        before = _metrics()
    except Exception as exc:
        print(f"API khong chay tai http://{HOST}:{PORT}: {exc}")
        print("Chay truoc:  .\\make.ps1 serve   (hoac: make serve)")
        return 1

    print("=== buoc 1: /metrics truoc ===")
    print(f"  requests_total = {before.get('pit_scoring_requests_total', 0)}")

    print("\n=== buoc 2: gui 1 request HOP LE ===")
    status, body = _post(
        {
            "transaction_id": "demo-bad-valid",
            "step": 744,
            "transaction_type": "TRANSFER",
            "amount": "150.75",
            "name_dest": "C1470998563",
        }
    )
    print(f"  HTTP {status}  prediction={body.get('prediction')}")

    print("\n=== buoc 3: /metrics sau request hop le ===")
    after_valid = _metrics()
    print(f"  requests_total = {after_valid.get('pit_scoring_requests_total', 0)}  (phai tang 1)")

    print("\n=== buoc 4: transaction_type = 'ABC' ===")
    status, body = _post(
        {
            "transaction_id": "demo-bad-abc",
            "step": 744,
            "transaction_type": "ABC",
            "amount": "150.75",
            "name_dest": "C1470998563",
        }
    )
    print(f"  HTTP {status}  {_detail(body)}")

    print("\n=== buoc 5: thieu name_dest ===")
    status, body = _post(
        {
            "transaction_id": "demo-bad-missing",
            "step": 744,
            "transaction_type": "TRANSFER",
            "amount": "150.75",
        }
    )
    print(f"  HTTP {status}  {_detail(body)}")

    print("\n=== buoc 6: amount = -100 ===")
    status, body = _post(
        {
            "transaction_id": "demo-bad-negative",
            "step": 744,
            "transaction_type": "TRANSFER",
            "amount": "-100",
            "name_dest": "C1470998563",
        }
    )
    print(f"  HTTP {status}  {_detail(body)}")

    print("\n=== buoc 7: /metrics lan cuoi ===")
    after = _metrics()
    print(f"  requests_total = {after.get('pit_scoring_requests_total', 0)}")
    print(f"  errors_total    = {after.get('pit_scoring_errors_total', 0)}")
    moved = after.get("pit_scoring_requests_total", 0) == after_valid.get(
        "pit_scoring_requests_total", 0
    )
    conclusion = (
        "requests_total KHONG tang sau 3 request hong -> validation chan truoc scoring path"
        if moved
        else "CANH BAO: requests_total co thay doi sau request hong - kiem tra lai"
    )
    print(f"\nKET LUAN: {conclusion}")
    return 0 if moved else 2


if __name__ == "__main__":
    raise SystemExit(main())
