"""Capture local host, serving-process, Locust, Redis, and worker resources once per second.

The sampler is read-only: it inspects Windows processes/listeners through psutil and consumes the
streaming output of ``docker stats``. It never restarts, stops, or mutates application services.

Example::

    uv run python scripts/capture_load_resources.py \
        --output artifacts/reports/load-resource-20260825.csv

Stop with Ctrl+C. Every CSV row is flushed immediately so an interrupted run remains readable.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

REDIS_CONTAINER = "pit-fintech-redis-1"
WORKER_CONTAINER = "pit-fintech-pit-online-worker-1"

CSV_COLUMNS = (
    "timestamp_local",
    "timestamp_utc",
    "elapsed_seconds",
    "host_cpu_percent",
    "host_memory_percent",
    "host_memory_used_mib",
    "host_memory_available_mib",
    "host_swap_percent",
    "api_pid",
    "api_cpu_percent",
    "api_rss_mib",
    "api_threads",
    "locust_pid",
    "locust_cpu_percent",
    "locust_rss_mib",
    "locust_threads",
    "redis_cpu_percent",
    "redis_memory_mib",
    "redis_memory_limit_mib",
    "redis_pids",
    "worker_cpu_percent",
    "worker_memory_mib",
    "worker_memory_limit_mib",
    "worker_pids",
    "docker_error",
)

_SIZE_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B|kB)\s*$", re.IGNORECASE)
_SIZE_TO_MIB = {
    "b": 1 / (1024 * 1024),
    "kb": 1 / 1024,
    "kib": 1 / 1024,
    "mb": 1.0,
    "mib": 1.0,
    "gb": 1024.0,
    "gib": 1024.0,
    "tb": 1024.0 * 1024.0,
    "tib": 1024.0 * 1024.0,
}


def parse_size_mib(value: str) -> float:
    """Normalize a Docker byte-size string to MiB."""

    match = _SIZE_PATTERN.match(value)
    if match is None:
        raise ValueError(f"unsupported size: {value!r}")
    amount, unit = match.groups()
    return float(amount) * _SIZE_TO_MIB[unit.lower()]


def _parse_percent(value: str) -> float:
    return float(value.strip().removesuffix("%"))


def _container_fields(snapshot: dict[str, str] | None, prefix: str) -> dict[str, object]:
    empty = {
        f"{prefix}_cpu_percent": "",
        f"{prefix}_memory_mib": "",
        f"{prefix}_memory_limit_mib": "",
        f"{prefix}_pids": "",
    }
    if not snapshot:
        return empty
    try:
        used, limit = (part.strip() for part in snapshot["MemUsage"].split("/", maxsplit=1))
        return {
            f"{prefix}_cpu_percent": _parse_percent(snapshot["CPUPerc"]),
            f"{prefix}_memory_mib": round(parse_size_mib(used), 3),
            f"{prefix}_memory_limit_mib": round(parse_size_mib(limit), 3),
            f"{prefix}_pids": int(snapshot["PIDs"]),
        }
    except (KeyError, TypeError, ValueError):
        return empty


def docker_metrics(snapshots: dict[str, dict[str, str]]) -> dict[str, object]:
    """Extract stable numeric Redis and worker fields from Docker JSON snapshots."""

    return {
        **_container_fields(snapshots.get(REDIS_CONTAINER), "redis"),
        **_container_fields(snapshots.get(WORKER_CONTAINER), "worker"),
    }


def decode_docker_stats_line(line: str) -> dict[str, str] | None:
    """Decode one Docker stats JSON object, ignoring streaming terminal control prefixes."""

    start = line.find("{")
    end = line.rfind("}")
    if start < 0 or end < start:
        return None
    return json.loads(line[start : end + 1])


class DockerStatsReader:
    """Keep the latest read-only streaming ``docker stats`` payload per container."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, str]] = {}
        self._error = ""
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        command = [
            "docker",
            "stats",
            "--format",
            "{{json .}}",
            REDIS_CONTAINER,
            WORKER_CONTAINER,
        ]
        kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            self._process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            return
        self._thread = threading.Thread(target=self._read, name="docker-stats-reader", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            try:
                payload = decode_docker_stats_line(line)
                if payload is None:
                    continue
                name = str(payload.get("Name", ""))
                if name:
                    with self._lock:
                        self._snapshots[name] = payload
            except json.JSONDecodeError as exc:
                with self._lock:
                    self._error = f"JSONDecodeError: {exc}"
        if self._process.poll() not in (None, 0) and self._process.stderr is not None:
            error = self._process.stderr.read().strip()
            if error:
                with self._lock:
                    self._error = error[:500]

    def latest(self) -> tuple[dict[str, dict[str, str]], str]:
        with self._lock:
            return dict(self._snapshots), self._error

    def close(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=3)


def _listener_pid(port: int) -> int | None:
    for connection in psutil.net_connections(kind="inet"):
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port == port
            and connection.pid
        ):
            return connection.pid
    return None


def _process_metrics(
    *, prefix: str, port: int, cache: dict[int, psutil.Process]
) -> dict[str, object]:
    empty = {
        f"{prefix}_pid": "",
        f"{prefix}_cpu_percent": "",
        f"{prefix}_rss_mib": "",
        f"{prefix}_threads": "",
    }
    pid = _listener_pid(port)
    if pid is None:
        return empty
    try:
        process = cache.get(pid)
        if process is None:
            process = psutil.Process(pid)
            process.cpu_percent(None)
            cache.clear()
            cache[pid] = process
        with process.oneshot():
            return {
                f"{prefix}_pid": pid,
                f"{prefix}_cpu_percent": process.cpu_percent(None),
                f"{prefix}_rss_mib": round(process.memory_info().rss / 1024**2, 3),
                f"{prefix}_threads": process.num_threads(),
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cache.pop(pid, None)
        return empty


def _sample(
    *,
    started: float,
    api_port: int,
    locust_port: int,
    process_caches: dict[str, dict[int, psutil.Process]],
    docker_reader: DockerStatsReader,
) -> dict[str, object]:
    now_local = datetime.now().astimezone()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    snapshots, docker_error = docker_reader.latest()
    row: dict[str, object] = {
        "timestamp_local": now_local.isoformat(timespec="milliseconds"),
        "timestamp_utc": now_local.astimezone(UTC).isoformat(timespec="milliseconds"),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "host_cpu_percent": psutil.cpu_percent(None),
        "host_memory_percent": memory.percent,
        "host_memory_used_mib": round((memory.total - memory.available) / 1024**2, 3),
        "host_memory_available_mib": round(memory.available / 1024**2, 3),
        "host_swap_percent": swap.percent,
        "docker_error": docker_error,
    }
    row.update(_process_metrics(prefix="api", port=api_port, cache=process_caches["api"]))
    row.update(_process_metrics(prefix="locust", port=locust_port, cache=process_caches["locust"]))
    row.update(docker_metrics(snapshots))
    return row


def _default_output() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return Path("artifacts/reports") / f"load-resource-{stamp}.csv"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="New CSV path; never overwritten")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds")
    parser.add_argument("--duration", type=float, default=None, help="Optional bounded duration")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--locust-port", type=int, default=8089)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not math.isfinite(args.interval) or args.interval < 0.2:
        raise SystemExit("--interval must be a finite value >= 0.2 seconds")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        raise SystemExit("--duration must be a finite value > 0 seconds")

    output = args.output or _default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    docker_reader = DockerStatsReader()
    docker_reader.start()
    process_caches: dict[str, dict[int, psutil.Process]] = {"api": {}, "locust": {}}
    psutil.cpu_percent(None)
    started = time.monotonic()
    deadline = started + args.duration if args.duration is not None else None
    samples = 0

    print(
        f"RESOURCE_CAPTURE_STARTED output={output.resolve()} interval={args.interval}s",
        flush=True,
    )
    try:
        with output.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            handle.flush()
            next_sample = started
            while not stop.is_set():
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    break
                if now < next_sample:
                    stop.wait(next_sample - now)
                    continue
                writer.writerow(
                    _sample(
                        started=started,
                        api_port=args.api_port,
                        locust_port=args.locust_port,
                        process_caches=process_caches,
                        docker_reader=docker_reader,
                    )
                )
                handle.flush()
                samples += 1
                next_sample += args.interval
                if next_sample < time.monotonic():
                    next_sample = time.monotonic()
    finally:
        docker_reader.close()

    print(
        f"RESOURCE_CAPTURE_STOPPED output={output.resolve()} samples={samples}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
