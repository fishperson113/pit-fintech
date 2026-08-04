"""T9 -- shared fixtures for the end-to-end lane (guide s11; gate G9).

Gate: **G9 Reproducibility** -- "synthetic E2E chay bang mot command" (guide s13). Guide s11 adds
the constraint that matters as much as the pipeline itself: "E2E phai chay bang mot command va
khong yeu cau internet/Kaggle." Every fixture here therefore builds from committed synthetic
input, never from the 6.3M-row PaySim snapshot and never from a network fetch.

Marker note: these tests are marked ``integration`` rather than a dedicated ``e2e`` marker.
``pyproject.toml`` declares exactly two markers under ``--strict-markers`` and adding a third would
edit ``pyproject.toml``, which ADR-004 lists inside *both* the lakehouse and training component
fingerprint boundaries -- so a marker declaration would change two lineage fingerprints and
invalidate the exact-Silver reuse the project depends on. Selecting this lane by path
(``pytest tests/e2e``) costs nothing and touches no fingerprint. Flagged in the round-0 report.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True, slots=True, kw_only=True)
class E2EEnvironment:
    """An isolated, disposable workspace for one end-to-end run.

    Every path is under ``tmp_path``: the E2E lane must never write into the repo's ``data/`` or
    ``artifacts/`` trees, or a failed run would leave the working copy dirty and trip the
    ``component_dirty`` guard (ADR-004) for whoever runs next.
    """

    project_root: Path
    data_root: Path
    artifact_root: Path
    online_store_uri: str
    mlflow_tracking_uri: str
    run_id: str


@pytest.fixture
def e2e_environment(tmp_path: Path) -> Iterator[E2EEnvironment]:
    """Provision an isolated workspace with a file-backed MLflow store and a SQLite online store.

    SQLite and a local MLflow file store, not containers: guide s7.3 makes SQLite the deterministic
    supported mode, and G9's "one command, no internet" would not survive a Compose dependency.
    """

    raise NotImplementedError("T9 round-0 skeleton")


@pytest.fixture
def synthetic_raw_csv(tmp_path: Path) -> Path:
    """Write the synthetic PaySim-shaped raw CSV the E2E pipeline starts from.

    Small, hand-authored and committed-deterministic, in the spirit of ``data/sample.py``. It must
    contain, by construction:

    * at least one destination with history spanning all three windows (1h/24h/168h), so the
      windows are read apart rather than coincidentally agreeing;
    * at least one zero-history destination, so cold-start defaults are exercised;
    * **at least one same-step in-scope pair**, because guide s8.3 requires a same-second tie
      checkpoint and T1's fixture has none (11 rows, 11 distinct timestamps). The E2E lane is the
      cheapest place to guarantee one exists rather than hope the sampled range contains it.
    """

    raise NotImplementedError("T9 round-0 skeleton")
