"""Read-only environment diagnostics for ``make doctor``."""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psutil

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _run_version(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, str(exc))
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return (completed.returncode == 0, output[0] if output else f"exit {completed.returncode}")


def _command_check(name: str, command: list[str], *, required: bool) -> Check:
    if shutil.which(command[0]) is None:
        return Check(name, "FAIL" if required else "WARN", f"{command[0]} not found")
    ok, detail = _run_version(command)
    return Check(name, "PASS" if ok else ("FAIL" if required else "WARN"), detail)


def _import_check(module_name: str) -> Check:
    try:
        module = importlib.import_module(module_name)
        version = getattr(module, "__version__", "version unavailable")
        return Check(f"import:{module_name}", "PASS", str(version))
    except Exception as exc:  # pragma: no cover - diagnostic must report any import failure
        return Check(f"import:{module_name}", "FAIL", f"{type(exc).__name__}: {exc}")


def _port_check(port: int, service: str) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.25)
        in_use = client.connect_ex(("127.0.0.1", port)) == 0
    state = "in use (service may already be running)" if in_use else "available"
    return Check(f"port:{service}", "PASS", f"127.0.0.1:{port} {state}")


def _git_commit(project_root: Path) -> Check:
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return Check("git commit", "PASS", completed.stdout.strip())
    return Check("git commit", "WARN", "repository has no commit yet")


def _delta_extension_check() -> Check:
    try:
        import duckdb

        with duckdb.connect() as connection:
            row = connection.execute(
                """
                SELECT installed, loaded
                FROM duckdb_extensions()
                WHERE extension_name = 'delta'
                """
            ).fetchone()
        installed, loaded = row if row else (False, False)
        detail = f"installed={bool(installed)}, loaded={bool(loaded)}"
        status: Status = "PASS" if installed else "WARN"
        if not installed:
            detail += "; Python delta-rs remains the local fallback"
        return Check("DuckDB delta extension", status, detail)
    except Exception as exc:  # pragma: no cover - environment-dependent diagnostic
        return Check("DuckDB delta extension", "WARN", f"inspection failed: {exc}")


def collect_checks(project_root: Path) -> list[Check]:
    """Collect checks without installing software, downloading extensions, or printing secrets."""

    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(project_root)
    python_ok = (3, 11) <= sys.version_info[:2] < (3, 13)
    virtual_env = os.environ.get("VIRTUAL_ENV") or "not active"
    kaggle_present = bool(
        (Path.home() / ".kaggle" / "kaggle.json").exists()
        or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
        or os.environ.get("KAGGLE_API_TOKEN")
    )

    checks = [
        Check(
            "Python",
            "PASS" if python_ok else "FAIL",
            f"{sys.version.split()[0]} at {sys.executable}",
        ),
        Check(
            "virtual environment", "PASS" if virtual_env != "not active" else "WARN", virtual_env
        ),
        _command_check("uv", ["uv", "--version"], required=True),
        _command_check("git", ["git", "--version"], required=True),
        _command_check("Docker client", ["docker", "--version"], required=False),
        _command_check("Docker Compose", ["docker", "compose", "version"], required=False),
        Check("available RAM", "PASS", f"{memory.available / 2**30:.1f} GiB"),
        Check("free disk", "PASS", f"{disk.free / 2**30:.1f} GiB at {project_root}"),
        _import_check("duckdb"),
        _import_check("deltalake"),
        _import_check("pyarrow"),
        _delta_extension_check(),
        Check(
            "Kaggle credentials",
            "PASS" if kaggle_present else "WARN",
            "configured" if kaggle_present else "not found; sample path is unaffected",
        ),
        _port_check(6379, "redis"),
        _port_check(5000, "mlflow"),
        _port_check(8000, "api"),
        _git_commit(project_root),
    ]
    return checks
