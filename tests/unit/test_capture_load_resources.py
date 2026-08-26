"""Contract tests for the local load-resource capture script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "capture_load_resources.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("capture_load_resources", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_size_mib_normalizes_docker_units() -> None:
    module = _load_script()

    assert module.parse_size_mib("7.039GiB") == pytest.approx(7207.936)
    assert module.parse_size_mib("150.7MiB") == pytest.approx(150.7)
    assert module.parse_size_mib("1024kB") == pytest.approx(1.0)
    assert module.parse_size_mib("0B") == 0.0


def test_docker_metrics_extracts_redis_and_worker_values() -> None:
    module = _load_script()
    snapshots = {
        "pit-fintech-redis-1": {
            "CPUPerc": "4.14%",
            "MemUsage": "7.039GiB / 14.61GiB",
            "PIDs": "6",
        },
        "pit-fintech-pit-online-worker-1": {
            "CPUPerc": "0.09%",
            "MemUsage": "150.7MiB / 14.61GiB",
            "PIDs": "20",
        },
    }

    metrics = module.docker_metrics(snapshots)

    assert metrics["redis_cpu_percent"] == pytest.approx(4.14)
    assert metrics["redis_memory_mib"] == pytest.approx(7207.936)
    assert metrics["redis_memory_limit_mib"] == pytest.approx(14960.64)
    assert metrics["redis_pids"] == 6
    assert metrics["worker_cpu_percent"] == pytest.approx(0.09)
    assert metrics["worker_memory_mib"] == pytest.approx(150.7)
    assert metrics["worker_pids"] == 20


def test_decode_docker_stats_line_ignores_streaming_terminal_prefix() -> None:
    module = _load_script()

    payload = module.decode_docker_stats_line(
        '\x1b[2J\x1b[H{"Name":"pit-fintech-redis-1","CPUPerc":"4.14%"}\r\n'
    )

    assert payload == {"Name": "pit-fintech-redis-1", "CPUPerc": "4.14%"}


def test_decode_docker_stats_line_ignores_control_only_refresh_line() -> None:
    module = _load_script()

    assert module.decode_docker_stats_line("\x1b[2J\x1b[H\r\n") is None


def test_csv_columns_cover_host_process_and_container_evidence() -> None:
    module = _load_script()

    required = {
        "timestamp_local",
        "elapsed_seconds",
        "host_cpu_percent",
        "host_memory_percent",
        "host_memory_used_mib",
        "api_pid",
        "api_cpu_percent",
        "api_rss_mib",
        "locust_pid",
        "locust_cpu_percent",
        "locust_rss_mib",
        "redis_cpu_percent",
        "redis_memory_mib",
        "redis_pids",
        "worker_cpu_percent",
        "worker_memory_mib",
        "worker_pids",
    }

    assert required <= set(module.CSV_COLUMNS)
