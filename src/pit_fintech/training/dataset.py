"""T4 -- historical retrieval and the temporal training dataset (guide s6.1, s6.2).

Gate: **G4 Training** -- "temporal run cua model da chon sau EDA co MLflow artifacts day du"
(guide s13). This module owns the half of G4 that is about the *dataset*: retrieving one row per
transaction at its own cutoff, proving no label reached the feature columns, and splitting on the
step boundaries Sprint 1 locked.

Guide s6.1 fixes the entity dataframe. The guide's original column list was IEEE-CIS vocabulary
(``transaction_id`` / ``card_entity_id`` / ``ordered_event_timestamp`` / ``label_is_fraud``) and
its own erratum table (guide "Nhat ky hieu chinh", 2026-08-03) already replaced it with the PaySim
names used here: ``source_row_number`` / ``destination_entity_id`` / ``event_timestamp`` /
``isFraud``, plus the three request-time fields.

Two invariants this module must not soften:

* ``isFraud`` comes from ``silver.paysim_labels`` and never appears in a feature column
  (ADR-002 decision 9, ADR-003 forbidden inputs). The four PaySim balance columns never appear at
  all -- ``PaySimSourceEvent`` forbids them by construction and Gold never carried them.
* the split is the frozen one: train ``step <= 520``, validation ``521-631``, test ``632-743``
  (ADR-002 decision 7). Encoding and imputation are fit on train only (guide s6.2).

Round-0 status: signatures only. Every body raises ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pit_fintech.features.build_offline import GoldTableSnapshot

#: ADR-002 decision 7, restated as the frozen split boundaries. Identical values already live in
#: ``features/paysim_recipient.py`` as ``PAYSIM_TRAIN_END_STEP``/``PAYSIM_VALIDATION_END_STEP``;
#: they are imported from there by any implementation rather than re-typed. Named here only so a
#: reader of this module sees which numbers the split policy means.
TRAIN_END_STEP: int = 520
VALIDATION_END_STEP: int = 631
TEST_END_STEP: int = 743

#: Guide s6.1 entity-dataframe columns, in the order the retrieval emits them.
ENTITY_DATAFRAME_COLUMNS: tuple[str, ...] = (
    "source_row_number",
    "destination_entity_id",
    "event_timestamp",
    "step",
    "isFraud",
    "current_amount",
    "event_step",
    "transaction_type_transfer",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityDataframeSpec:
    """The request handed to historical retrieval: which cutoffs, at which versions.

    ``retrieval_backend`` records which path produced the vectors. Both are legitimate and they
    must agree: Feast is the thin control-plane contract (AGENTS.md s11) and DuckDB reading Gold
    directly is the same data without the registry hop. G1 is the gate that binds Feast's answer to
    the oracle; recording the backend here is what lets a training run say which one it used.
    """

    dataset_snapshot_id: str
    entity_definition_version: str
    feature_definition_version: str
    feature_service_version: str
    feature_contract_checksum: str
    gold_pre_decision: GoldTableSnapshot
    label_table_path: str
    label_table_version: int
    start_step: int
    end_step: int
    retrieval_backend: Literal["feast", "duckdb_gold"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalAssertion:
    """One guide s6.1 post-retrieval assertion, recorded pass or fail."""

    name: str
    status: Literal["pass", "fail"]
    observed: int
    expected: int
    detail: str | None = None


#: The four assertions guide s6.1 requires after retrieval. All must pass before a dataset may be
#: trained on; ``no_label_in_feature_columns`` is also a G4 promotion-gate criterion (guide s6.4).
REQUIRED_RETRIEVAL_ASSERTIONS: tuple[str, ...] = (
    "row_count_unchanged_outside_expected_missing",
    "one_row_per_transaction",
    "no_label_in_feature_columns",
    "ordered_feature_list_frozen",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalRetrievalResult:
    """The training matrix plus the evidence that it is point-in-time correct.

    :attr:`ordered_feature_names` must equal ``PAYSIM_MODEL_FEATURE_ORDER`` -- guide s6.1's "freeze
    ordered feature list", and the same tuple T7 builds its serving vector from. Any divergence
    between them is a G6/G7 failure waiting to happen, so it is asserted here rather than
    discovered at scoring time.
    """

    spec: EntityDataframeSpec
    parquet_path: str
    rows: int
    fraud_rows: int
    ordered_feature_names: tuple[str, ...]
    feature_dtypes: dict[str, str]
    label_column: str
    #: Canonical checksum of the materialized matrix. Also a mandatory MLflow tag (guide s6.3) and
    #: the value AGENTS.md s9 requires to be reproducible from exact Delta source versions.
    training_dataset_checksum: str
    #: Cutoffs with no retrievable vector, kept as a number rather than dropped silently.
    missing_entity_rows: int
    max_source_event_step: int
    future_read_violations: int
    assertions: tuple[RetrievalAssertion, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TemporalSplit:
    """Guide s6.2. One partition of the frozen chronological split.

    ``natural_prevalence`` is carried because the Sprint 1 baseline was measured at natural
    prevalence and the numbers only mean something next to that flag (M019: E1 PR-AUC 0.258342,
    E4 0.102766).
    """

    name: Literal["train", "validation", "test"]
    start_step: int
    end_step: int
    rows: int
    fraud_rows: int
    fraud_rate: float
    natural_prevalence: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TrainingDataset:
    """A split, checksummed training dataset ready for one deterministic run.

    :attr:`split_policy` is a mandatory MLflow tag (guide s6.3) and a G4 promotion criterion
    (guide s6.4: "khong dung leaky/random split artifact"). ``"random_ablation"`` exists so an
    ablation can be *labelled* rather than smuggled in: guide s6.2 requires random-split runs to
    sit in the ``ablation/`` experiment namespace and never reach promotion.
    """

    retrieval: HistoricalRetrievalResult
    split_policy: Literal["temporal_frozen", "random_ablation"]
    experiment_namespace: str
    partitions: tuple[TemporalSplit, ...]
    ordered_feature_names: tuple[str, ...]
    training_dataset_checksum: str


def build_entity_dataframe(*, spec: EntityDataframeSpec, artifact_root: Path) -> Path:
    """Emit the guide s6.1 entity dataframe: one row per in-scope cutoff, labels attached.

    Labels are joined here and only here, so there is exactly one place where ``isFraud`` enters
    the training path and exactly one place to check that it did not leak sideways into a feature
    column. Guide s4.2 forbids joining the label table into feature computation at all, which is
    why this happens after retrieval rather than inside Gold.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def retrieve_historical_features(
    *,
    spec: EntityDataframeSpec,
    entity_dataframe_path: Path,
    artifact_root: Path,
) -> HistoricalRetrievalResult:
    """Attach history features at each cutoff and run every guide s6.1 assertion.

    With ``retrieval_backend="feast"`` this goes through ``get_historical_features`` against the
    frozen ``paysim-fraud-scoring-v2`` service; with ``"duckdb_gold"`` it reads
    ``gold.pre_decision_features`` directly. Feast is a thin contract over the same rows
    (AGENTS.md s11), never the correctness oracle -- a disagreement between the two backends is a
    defect in the Feast layer (ADR-006 decision 1.3), not evidence about the features.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def split_temporal(
    *,
    retrieval: HistoricalRetrievalResult,
    train_end_step: int = TRAIN_END_STEP,
    validation_end_step: int = VALIDATION_END_STEP,
    split_policy: Literal["temporal_frozen", "random_ablation"] = "temporal_frozen",
    seed: int | None = None,
) -> TrainingDataset:
    """Split on the frozen step boundaries (guide s6.2, ADR-002 decision 7).

    ``split_policy="random_ablation"`` is permitted but routes the run into the ``ablation/``
    experiment namespace and makes it ineligible for promotion (guide s6.2, s6.4). It exists so a
    split-policy diagnostic like E3 can be run honestly, not so a nicer number can be reported.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def assert_no_label_leakage(*, dataset: TrainingDataset) -> RetrievalAssertion:
    """Confirm no forbidden column reached the feature matrix.

    Checks ``PAYSIM_FORBIDDEN_MODEL_INPUTS`` -- ``isFraud``, ``isFlaggedFraud`` and the four PaySim
    balance columns (ADR-003) -- against :attr:`TrainingDataset.ordered_feature_names`. A hit is a
    hard failure, never a warning: ADR-002 decision 9 keeps labels strictly evaluation-only and
    CLAUDE.md forbids the balance columns as features outright.
    """

    raise NotImplementedError("T4 round-0 skeleton")


def training_dataset_checksum(*, dataset_path: Path, ordered_feature_names: tuple[str, ...]) -> str:
    """Canonical checksum over the materialized matrix, in frozen feature order.

    AGENTS.md s9: exact Delta source versions must reproduce the same training dataset checksum.
    Money columns are canonicalized as exact decimals before hashing, for the reason M027 recorded
    -- float accumulation is not associative, and that alone made this checksum drift between runs
    of identical code.
    """

    raise NotImplementedError("T4 round-0 skeleton")
