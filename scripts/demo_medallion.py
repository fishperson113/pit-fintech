"""demo-medallion: show the grain of the five medallion tables, read from Delta.

Row counts come from the CURRENT Delta snapshot (DeltaTable.to_pyarrow_dataset().count_rows()),
never from pyarrow.dataset(dir) which would also count obsolete files of older versions.
"""

from __future__ import annotations

import time
from pathlib import Path

from deltalake import DeltaTable

from pit_fintech.config import get_settings
from pit_fintech.contracts.manifests import ApplicationLakehouseManifest
from pit_fintech.data.paysim import resolve_project_root
from pit_fintech.data.paysim_lakehouse import find_latest_paysim_lakehouse_manifest
from pit_fintech.features.build_offline import (
    GOLD_POST_EVENT_TABLE,
    GOLD_PRE_DECISION_TABLE,
    gold_table_path,
)

#: One-line meaning per table (grain). Hard-coded by design: the grain is a contract property.
MEANINGS: dict[str, str] = {
    "bronze.paysim_transactions": "1 giao dich RAW tu CSV PaySim (type/amount/balances/isFraud)",
    "silver.paysim_transactions": "1 event chuan hoa (entity id+kind tach rieng, khong balance)",
    "silver.paysim_labels": "label isFraud cua 1 transaction, tach bang rieng chong leak",
    "gold.pre_decision_features": "1 cutoff trong scope, 12 features PIT-correct TRUOC giao dich",
    "gold.post_event_state_updates": "1 event bat ky, state SAU event (nguon materialize online)",
}


def main() -> int:
    started = time.perf_counter()
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

    manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
    if manifest_path is None:
        print("KHONG tim thay lakehouse manifest; chay build-lakehouse truoc")
        return 1
    manifest = ApplicationLakehouseManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    snapshot_prefix = manifest.raw_file_sha256[:16]

    tables: list[tuple[str, Path]] = []
    for snapshot in manifest.tables:
        path = Path(snapshot.path)
        if not path.is_absolute():
            path = project_root / path
        tables.append((f"{snapshot.layer}.{snapshot.table}", path))
    tables.append(
        (
            "gold.pre_decision_features",
            gold_table_path(
                data_root=data_root,
                snapshot_prefix=snapshot_prefix,
                table=GOLD_PRE_DECISION_TABLE,
            ),
        )
    )
    tables.append(
        (
            "gold.post_event_state_updates",
            gold_table_path(
                data_root=data_root,
                snapshot_prefix=snapshot_prefix,
                table=GOLD_POST_EVENT_TABLE,
            ),
        )
    )

    header = f"{'table':<30} {'ver':>3} {'rows':>12} {'cols':>4}  meaning"
    print(header)
    print("-" * len(header))
    for name, path in tables:
        delta = DeltaTable(str(path))
        version = delta.version()
        dataset = delta.to_pyarrow_dataset()
        rows = dataset.count_rows()
        cols = len(delta.schema().to_arrow().names)
        meaning = MEANINGS.get(name, "")
        print(f"{name:<30} {version:>3} {rows:>12,} {cols:>4}  {meaning}")
    print(f"\n(doc truc tiep tu Delta, {time.perf_counter() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
