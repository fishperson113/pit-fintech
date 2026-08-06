"""Happy-path end-to-end demo: Redis -> Gold -> materialize -> serve -> score.

Drives the pieces wired up in ``pit_fintech.cli`` (``materialize run`` and ``serving up``) through
one script so a mentor demo is a single command. Does not modify any repository file and performs
no writes outside the online store and the spawned API process.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

import pyarrow.compute as pc
from deltalake import DeltaTable

from pit_fintech.config import get_settings
from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim import resolve_project_root
from pit_fintech.data.paysim_lakehouse import find_latest_paysim_lakehouse_manifest
from pit_fintech.features.build_offline import (
    GOLD_PARTITION_COLUMN,
    GOLD_POST_EVENT_TABLE,
    gold_table_path,
)
from pit_fintech.features.paysim_specs import PAYSIM_ENTITY, PAYSIM_FEATURE_SERVICE_VERSION
from pit_fintech.serving.schemas import ScoreRequest

REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
DEFAULT_WATERMARK = 743
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HEALTH_POLL_SECONDS = 60
MISSING_ENTITY_ID = "C0000000000"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pit-fintech end-to-end demo")
    parser.add_argument("--watermark", type=int, default=DEFAULT_WATERMARK)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--skip-materialize",
        action="store_true",
        help="Skip materialization; assume the online store already has this watermark",
    )
    return parser


def _step_header(title: str) -> None:
    print()
    print(f"=== {title} ===")


def _check_redis() -> tuple[bool, str]:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=2) as sock:
            sock.sendall(b"PING\r\n")
            reply = sock.recv(64)
        if b"PONG" in reply:
            return True, "PONG"
        return False, f"unexpected reply: {reply!r}"
    except OSError as exc:
        return False, str(exc)


def _score_case(*, host: str, port: int, name: str, name_dest: str, step: int) -> bool:
    print(f"--- {name} ---")
    request = ScoreRequest(
        transaction_id=f"demo-{name}",
        step=step,
        transaction_type="TRANSFER",
        amount=Decimal("150.75"),
        name_dest=name_dest,
    )
    print("request:")
    print(request.model_dump_json(indent=2))
    url = f"http://{host}:{port}/score"
    payload = request.model_dump_json().encode("utf-8")
    http_request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(http_request, timeout=10) as response:
            body = response.read().decode("utf-8")
            print(f"response (HTTP {response.status}):")
            print(json.dumps(json.loads(body), indent=2))
            return response.status == 200
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        print(f"response (HTTP {exc.code}):")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except ValueError:
            print(body)
        return False
    except urllib.error.URLError as exc:
        print(f"request failed: {exc}")
        return False


def _print_summary(results: list[tuple[str, bool, str]], total_elapsed: float) -> bool:
    print()
    print("=== Summary ===")
    all_ok = True
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"{status:<4} {name:<20} {detail}")
    print(f"total: {total_elapsed:.2f}s")
    return all_ok


def main() -> int:
    args = _parser().parse_args()
    project_root = resolve_project_root(Path.cwd())
    settings = get_settings()
    data_root = (
        settings.data_root
        if settings.data_root.is_absolute()
        else project_root / settings.data_root
    )
    artifact_root = (
        settings.artifact_root
        if settings.artifact_root.is_absolute()
        else project_root / settings.artifact_root
    )

    results: list[tuple[str, bool, str]] = []
    overall_start = time.monotonic()
    proc: subprocess.Popen[bytes] | None = None

    # Step 1: Redis --------------------------------------------------------------------------
    _step_header("Step 1: Redis check")
    step_start = time.monotonic()
    redis_ok, redis_detail = _check_redis()
    elapsed = time.monotonic() - step_start
    if redis_ok:
        print(f"PASS Redis PING -> {redis_detail} ({elapsed:.2f}s)")
    else:
        print(f"FAIL Redis unreachable: {redis_detail}")
        print("Start it with: docker compose up -d redis")
    results.append(("redis_check", redis_ok, f"{elapsed:.2f}s"))
    if not redis_ok:
        _print_summary(results, time.monotonic() - overall_start)
        return 1

    # Step 2: Gold -----------------------------------------------------------------------------
    _step_header("Step 2: Gold table check")
    step_start = time.monotonic()
    gold_ok = False
    entity_id: str | None = None
    feature_step: int | None = None
    try:
        manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
        if manifest_path is None:
            raise RuntimeError("no PaySim lakehouse manifest found")
        manifest = ApplicationLakehouseManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        snapshot_prefix = manifest.raw_file_sha256[:16]
        gold_post_path = gold_table_path(
            data_root=data_root, snapshot_prefix=snapshot_prefix, table=GOLD_POST_EVENT_TABLE
        )
        gold_table = DeltaTable(str(gold_post_path))
        arrow = gold_table.to_pyarrow_table()
        partitions = len({int(value) for value in arrow[GOLD_PARTITION_COLUMN].to_pylist()})
        print(
            f"post_event_state_updates: version={gold_table.version()} "
            f"rows={arrow.num_rows} partitions={partitions}"
        )
        gold_ok = True

        filtered = arrow.filter(pc.less_equal(arrow["step"], args.watermark))
        if filtered.num_rows > 0:
            sorted_table = filtered.sort_by([("step", "descending")])
            entity_id = sorted_table[PAYSIM_ENTITY][0].as_py()
            feature_step = int(sorted_table["step"][0].as_py())
            print(f"selected demo entity: {entity_id} (feature_step={feature_step})")
        else:
            print(f"WARN no post-event rows at or before step {args.watermark}")
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"FAIL Gold check: {exc}")
    elapsed = time.monotonic() - step_start
    results.append(("gold_check", gold_ok, f"{elapsed:.2f}s"))

    # Step 3: Materialize ------------------------------------------------------------------------
    _step_header("Step 3: Materialize to watermark")
    materialize_ok = False
    if args.skip_materialize:
        print(f"skipped (--skip-materialize); assuming watermark <= {args.watermark} is loaded")
        materialize_ok = True
        results.append(("materialize", materialize_ok, "skipped"))
    else:
        step_start = time.monotonic()
        try:
            from pit_fintech.materialization.materializer import (
                OnlineStoreConfig,
                materialize_to_watermark,
            )
            from pit_fintech.materialization.records import OnlineStoreKind

            store = OnlineStoreConfig(
                kind=OnlineStoreKind.REDIS,
                uri=f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
                feature_service_version=PAYSIM_FEATURE_SERVICE_VERSION,
                entity=PAYSIM_ENTITY,
            )
            run_id = f"demo-{int(time.time())}"
            result = materialize_to_watermark(
                project_root=project_root,
                data_root=data_root,
                artifact_root=artifact_root,
                store=store,
                watermark_step=args.watermark,
                run_id=run_id,
            )
            materialize_ok = result.status == "completed"
            print(
                f"status={result.status} records_written={result.records_written} "
                f"watermark_step={result.watermark_step}"
            )
        except Exception as exc:  # T5 seam still landing; report and continue rather than crash
            print(f"FAIL materialize: {exc}")
        elapsed = time.monotonic() - step_start
        print(f"({elapsed:.2f}s)")
        results.append(("materialize", materialize_ok, f"{elapsed:.2f}s"))

    try:
        # Step 4: Start the scoring API -----------------------------------------------------
        _step_header("Step 4: Start scoring API")
        step_start = time.monotonic()
        api_ok = False
        try:
            serve_command = [
                "uv",
                "run",
                "pit",
                "serving",
                "up",
                "--host",
                args.host,
                "--port",
                str(args.port),
            ]
            proc = subprocess.Popen(serve_command, cwd=project_root)
            health_url = f"http://{args.host}:{args.port}/health/ready"
            deadline = time.monotonic() + HEALTH_POLL_SECONDS
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"serving process exited early with code {proc.returncode}")
                try:
                    with urllib.request.urlopen(health_url, timeout=2) as response:
                        if response.status == 200:
                            body = json.loads(response.read())
                            if body.get("ready"):
                                api_ok = True
                                break
                except (urllib.error.URLError, OSError, ValueError):
                    pass
                time.sleep(2)
        except (RuntimeError, OSError) as exc:
            print(f"FAIL starting API: {exc}")
        elapsed = time.monotonic() - step_start
        if api_ok:
            print(f"PASS API ready ({elapsed:.2f}s)")
        else:
            print(f"FAIL API not ready within {HEALTH_POLL_SECONDS}s ({elapsed:.2f}s)")
        results.append(("serving_up", api_ok, f"{elapsed:.2f}s"))

        # Step 5: Score three cases ----------------------------------------------------------
        _step_header("Step 5: Score requests")
        if api_ok and entity_id is not None and feature_step is not None:
            case_a_ok = _score_case(
                host=args.host,
                port=args.port,
                name="case_a_fresh",
                name_dest=entity_id,
                step=feature_step + 1,
            )
            case_b_ok = _score_case(
                host=args.host,
                port=args.port,
                name="case_b_stale",
                name_dest=entity_id,
                step=feature_step + 500,
            )
            case_c_ok = _score_case(
                host=args.host,
                port=args.port,
                name="case_c_missing",
                name_dest=MISSING_ENTITY_ID,
                step=feature_step + 1,
            )
        else:
            print("skipping: API not ready or no demo entity was found in Gold")
            case_a_ok = case_b_ok = case_c_ok = False
        results.append(("score_case_a_fresh", case_a_ok, ""))
        results.append(("score_case_b_stale", case_b_ok, ""))
        results.append(("score_case_c_missing", case_c_ok, ""))
    finally:
        # Step 6: Tear down the API -----------------------------------------------------------
        _step_header("Step 6: Stop scoring API")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            print("API process stopped")
        else:
            print("no running API process to stop")

    all_ok = _print_summary(results, time.monotonic() - overall_start)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
