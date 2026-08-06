"""demo-metrics: show the in-process scoring counters from /metrics."""

from __future__ import annotations

import argparse
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the /metrics counters")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/metrics"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            text = response.read().decode("utf-8")
    except Exception as exc:
        print(f"API khong chay tai {url}: {exc}")
        print("Chay truoc:  .\\make.ps1 serve   (hoac: make serve)")
        return 1
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
