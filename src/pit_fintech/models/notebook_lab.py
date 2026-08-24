"""Shared exploratory-lab helpers for the modeling notebooks (09-12).

Non-promotable surface: build one in-memory modeling frame **from Silver** (never from the
materialized Gold table), the frozen temporal split, and walk-forward CV folds, and centralize
MLflow lab configuration so every modeling notebook logs to one experiment with a consistent
feature set and split protocol.

The frame is built by running the shipped PIT feature SQL
(``features.paysim_recipient.paysim_pre_decision_feature_sql``) over the Silver
``paysim_transactions`` table — the exact derivation the Gold builder uses — so the notebooks
compute the strict pre-cutoff windows themselves instead of reading Gold. This honors "start from
Bronze/Silver/raw, do not shortcut through Gold" while staying leakage-free (a naive in-notebook
rolling window would read future rows). It re-derives features on every load, so it is slower than
reading Gold — an intentional trade for a learning surface. Promotable evidence still runs through
``pit_fintech.training`` with a manifest and multi-seed candidate matrix (hard rule #4). Nothing
here is a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pit_fintech.config import get_settings
from pit_fintech.data.paysim import find_paysim_csv, resolve_project_root
from pit_fintech.features.paysim_recipient import (
    PAYSIM_PRE_DECISION_SOURCE_COLUMNS,
    paysim_pre_decision_feature_sql,
)
from pit_fintech.features.paysim_specs import (
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_STATIC_FEATURE_NAMES,
)

PIT12 = list(PAYSIM_MODEL_FEATURE_ORDER)
STATIC_FEATURES = list(PAYSIM_STATIC_FEATURE_NAMES)

# The 7 PIT-safe features kept after the notebook-09 ablation (``event_step`` dropped as
# absolute-time overfitting). Shared by nb10-12 so the deployable feature set never drifts.
DEPLOYABLE_CORE = [
    "current_amount",
    "transaction_type_transfer",
    "pit_prior_amount_1h",
    "pit_prior_amount_24h",
    "pit_prior_amount_168h",
    "pit_prior_count_1h",
    "pit_prior_count_24h",
]

# Frozen temporal split boundaries (by PaySim ``step``): fit on the past, pick a threshold on
# val, report once on test. Random splits would leak the future (AGENTS PIT invariant).
TRAIN_MAX_STEP = 520
VAL_MAX_STEP = 631

# Default walk-forward protocol shared by the CV notebook (10) and Optuna tuning (11) so the folds
# Optuna optimizes over are exactly the folds nb10 reports the distribution of. Every fold's test
# window stays within Train+Val: the widest is (540, 595], and 595 <= VAL_MAX_STEP (631). This is
# the data-centric discipline -- CV and tuning never read the sealed Test (step > 631); Test is
# touched exactly once, in nb12. Keep new cuts <= VAL_MAX_STEP - DEFAULT_TEST_WIDTH.
DEFAULT_CUTS = (360, 420, 480, 540)
DEFAULT_TEST_WIDTH = 55
LAB_EXPERIMENT = "paysim-notebook-modeling"

MLFLOW_LAB_TAGS = {"surface": "notebook-exploratory", "manifest_backed": "false"}


@dataclass
class LabPaths:
    """Resolved source paths for the modeling lab; ``ready`` gates every heavy cell.

    ``silver_transactions`` is the Silver ``paysim_transactions`` Delta table (the modeling source);
    ``labels`` is Silver ``paysim_labels``; ``paysim_csv`` is the raw CSV, used only where a
    notebook deliberately needs the forbidden balance columns for a leakage control arm (nb09).
    """

    paysim_csv: Path | None
    silver_transactions: Path | None
    labels: Path | None

    @property
    def ready(self) -> bool:
        return (
            self.silver_transactions is not None
            and (self.silver_transactions / "_delta_log").exists()
            and self.labels is not None
            and (self.labels / "_delta_log").exists()
        )

    def as_dict(self) -> dict[str, bool]:
        return {
            "paysim_csv": self.paysim_csv is not None,
            "silver_transactions": self.silver_transactions is not None,
            "labels": self.labels is not None,
            "ready": self.ready,
        }


def resolve_lab_paths(project_root: Path | None = None) -> LabPaths:
    """Locate the Silver ``paysim_transactions`` + ``paysim_labels`` tables and the raw CSV."""
    root = project_root or resolve_project_root(Path.cwd())
    settings = get_settings()
    artifact_root = (
        settings.artifact_root
        if settings.artifact_root.is_absolute()
        else root / settings.artifact_root
    )

    paysim_csv = find_paysim_csv(root)
    silver_transactions: Path | None = None
    labels: Path | None = None
    try:
        from pit_fintech.data.paysim_lakehouse import (
            ApplicationLakehouseManifest,
            _resolve_manifest_path,
            find_latest_paysim_lakehouse_manifest,
        )

        manifest_path = find_latest_paysim_lakehouse_manifest(artifact_root)
        if manifest_path is not None:
            manifest = ApplicationLakehouseManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            for snap in manifest.tables:
                if snap.table == "paysim_transactions" and snap.layer == "silver":
                    silver_transactions = _resolve_manifest_path(snap.path, root)
                elif snap.table == "paysim_labels":
                    labels = _resolve_manifest_path(snap.path, root)
    except Exception:  # optional context, never a gate
        silver_transactions = labels = None
    return LabPaths(paysim_csv=paysim_csv, silver_transactions=silver_transactions, labels=labels)


def load_modeling_frame(paths: LabPaths) -> pd.DataFrame:
    """Compute the v3 PIT feature vectors from Silver + join ``isFraud`` — never reads Gold.

    Runs ``paysim_pre_decision_feature_sql`` over Silver ``paysim_transactions`` (the same strict
    pre-cutoff derivation the Gold builder uses) and joins Silver ``paysim_labels``. The result is
    one row per in-scope cutoff with the frozen contract fields in ``PIT12`` order plus ``step`` and
    ``isFraud``.
    """
    import duckdb
    from deltalake import DeltaTable

    silver = (
        DeltaTable(str(paths.silver_transactions))
        .to_pyarrow_table()
        .select(list(PAYSIM_PRE_DECISION_SOURCE_COLUMNS))
    )
    labels = (
        DeltaTable(str(paths.labels)).to_pyarrow_table().select(["source_row_number", "isFraud"])
    )
    connection = duckdb.connect()
    connection.register("silver_txns", silver)
    connection.register("labels", labels)
    frame = connection.execute(
        f"""
        SELECT vectors.*, labels.isFraud
        FROM ({paysim_pre_decision_feature_sql("silver_txns")}) AS vectors
        JOIN labels USING (source_row_number)
        ORDER BY vectors.step, vectors.source_row_number
        """  # deterministic order -> reproducible LightGBM bins
    ).df()
    connection.close()
    frame[PIT12] = frame[PIT12].astype("float64")
    return frame


def three_way_temporal_split(
    frame: pd.DataFrame,
    train_max: int = TRAIN_MAX_STEP,
    val_max: int = VAL_MAX_STEP,
) -> dict[str, pd.DataFrame]:
    """Split by ``step`` into train ``<= train_max`` / val ``(train_max, val_max]`` / test rest."""
    return {
        "train": frame[frame["step"] <= train_max],
        "val": frame[(frame["step"] > train_max) & (frame["step"] <= val_max)],
        "test": frame[frame["step"] > val_max],
    }


@dataclass
class WalkForwardFold:
    """One walk-forward fold: train the past, test the next time window."""

    cut: int
    embargo: int
    train: pd.DataFrame
    test: pd.DataFrame

    @property
    def usable(self) -> bool:
        """True when the test window is non-empty and carries both classes."""
        return len(self.train) > 0 and len(self.test) > 0 and self.test["isFraud"].nunique() == 2


def walk_forward_folds(
    frame: pd.DataFrame,
    cuts=DEFAULT_CUTS,
    test_width: int = DEFAULT_TEST_WIDTH,
    embargo: int = 0,
) -> list[WalkForwardFold]:
    """Walk-forward folds by ``step``: train ``step <= cut - embargo``, test the next window.

    The embargo drops the ``embargo`` steps just before each boundary to break near-time sample
    dependence (E=0 is production-realistic; E>0 is conservative). Callers filter on
    ``fold.usable`` to skip windows without both classes.
    """
    return [
        WalkForwardFold(
            cut=cut,
            embargo=embargo,
            train=frame[frame["step"] <= cut - embargo],
            test=frame[(frame["step"] > cut) & (frame["step"] <= cut + test_width)],
        )
        for cut in cuts
    ]


def selected_features_path(project_root: Path | None = None) -> Path:
    """Where nb09 writes the ablation-chosen feature set for nb10-12 to read."""
    root = project_root or resolve_project_root(Path.cwd())
    settings = get_settings()
    artifact_root = (
        settings.artifact_root
        if settings.artifact_root.is_absolute()
        else root / settings.artifact_root
    )
    return artifact_root / "notebook_lab" / "selected_features.json"


def save_selected_features(features, *, source: str = "nb09-ablation") -> Path:
    """Persist the feature set chosen by the nb09 ablation (Step 2 output)."""
    import json

    path = selected_features_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"features": list(features), "source": source}, indent=2), encoding="utf-8"
    )
    return path


def load_selected_features(fallback=None) -> list[str]:
    """Read the nb09-chosen feature set; fall back to ``DEPLOYABLE_CORE`` if nb09 hasn't run.

    This is the Step 2 -> Step 3/4 handoff: nb10 (CV), nb11 (Optuna) and nb12 (final Test) train on
    exactly the features the ablation kept, not a hardcoded list.
    """
    import json

    chosen = list(fallback) if fallback is not None else list(DEPLOYABLE_CORE)
    path = selected_features_path()
    if path.exists():
        features = json.loads(path.read_text(encoding="utf-8")).get("features")
        if features:
            chosen = list(features)
    return chosen


def configure_lab_mlflow(experiment: str = LAB_EXPERIMENT):
    """Point MLflow at the configured tracking server + one notebook experiment.

    Returns the ``mlflow`` module with tracking URI and experiment set, or ``None`` when mlflow
    is not installed in the kernel (the notebook still runs, just without logging).
    """
    try:
        import mlflow
    except ImportError:
        return None
    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    mlflow.set_experiment(experiment)
    return mlflow
