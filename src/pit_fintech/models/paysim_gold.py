"""Gold-backed E1-E4 evaluation matrix.

E2 deliberately uses the Gold post-event table as a current-inclusive control. It is intentionally
not deployable. E1/E3/E4 use the same committed Gold pre-decision table with temporal/random split
variants, so the matrix does not require a Gold schema/backfill change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

import duckdb
import pyarrow as pa

from pit_fintech.features.paysim_specs import (
    PAYSIM_MODEL_FEATURE_ORDER,
    PAYSIM_STATIC_FEATURE_NAMES,
)
from pit_fintech.models.paysim_lightgbm import (
    SKOPS_TRUSTED_LIGHTGBM_TYPES,
    _binary_operating_metrics,
    _load_training_dependencies,
    _model_parameters,
    _threshold_for_fixed_fpr,
)

POST_HISTORY_FEATURE_NAMES: tuple[str, ...] = (
    "post_count_1h",
    "post_amount_1h",
    "post_has_history_1h",
    "post_count_24h",
    "post_amount_24h",
    "post_has_history_24h",
    "post_count_168h",
    "post_amount_168h",
    "post_has_history_168h",
)
GOLD_POST_EVENT_FEATURE_ORDER: tuple[str, ...] = (
    *PAYSIM_STATIC_FEATURE_NAMES,
    *POST_HISTORY_FEATURE_NAMES,
)


@dataclass(frozen=True, slots=True)
class GoldExperimentSpec:
    experiment_id: Literal["E1", "E2", "E3", "E4"]
    feature_set: Literal["static", "post_event", "pit"]
    split_policy: Literal["random", "temporal"]
    feature_names: tuple[str, ...]
    deployable: bool
    purpose: str


GOLD_EXPERIMENT_MATRIX: tuple[GoldExperimentSpec, ...] = (
    GoldExperimentSpec(
        experiment_id="E1",
        feature_set="static",
        split_policy="temporal",
        feature_names=PAYSIM_STATIC_FEATURE_NAMES,
        deployable=True,
        purpose="request-only temporal baseline",
    ),
    GoldExperimentSpec(
        experiment_id="E2",
        feature_set="post_event",
        split_policy="random",
        feature_names=GOLD_POST_EVENT_FEATURE_ORDER,
        deployable=False,
        purpose="current-inclusive Gold post-event positive control",
    ),
    GoldExperimentSpec(
        experiment_id="E3",
        feature_set="pit",
        split_policy="random",
        feature_names=PAYSIM_MODEL_FEATURE_ORDER,
        deployable=False,
        purpose="PIT join effect under random split",
    ),
    GoldExperimentSpec(
        experiment_id="E4",
        feature_set="pit",
        split_policy="temporal",
        feature_names=PAYSIM_MODEL_FEATURE_ORDER,
        deployable=True,
        purpose="strict-PIT temporal candidate",
    ),
)


@dataclass(frozen=True, slots=True)
class GoldExperimentResult:
    experiment_id: str
    feature_set: str
    split_policy: str
    deployable: bool
    rows: int
    fraud_rows: int
    test_pr_auc: float
    test_roc_auc: float
    test_recall: float
    test_precision: float
    observed_fpr: float
    validation_threshold: float
    training_dataset_checksum: str
    mlflow_run_id: str | None = None
    model_uri: str | None = None


def build_gold_experiment_table(
    *,
    pre_decision: pa.Table,
    post_event: pa.Table,
    labels: pa.Table,
) -> pa.Table:
    """Join committed Gold pre/post tables to labels without changing either Delta table."""

    connection = duckdb.connect()
    connection.register("pre_decision", pre_decision)
    connection.register("post_event", post_event)
    connection.register("labels", labels)
    try:
        table = connection.execute(
            """
            SELECT
                p.source_row_number,
                p.step,
                CASE
                    WHEN p.step <= 520 THEN 'train'
                    WHEN p.step <= 631 THEN 'validation'
                    ELSE 'test'
                END AS split,
                l.isFraud::BIGINT AS target_label,
                p.current_amount,
                p.event_step,
                p.transaction_type_transfer,
                p.pit_prior_count_1h,
                p.pit_prior_amount_1h,
                p.recipient_has_history_1h,
                p.pit_prior_count_24h,
                p.pit_prior_amount_24h,
                p.recipient_has_history_24h,
                p.pit_prior_count_168h,
                p.pit_prior_amount_168h,
                p.recipient_has_history_168h,
                q.post_count_1h,
                q.post_amount_1h,
                q.post_has_history_1h,
                q.post_count_24h,
                q.post_amount_24h,
                q.post_has_history_24h,
                q.post_count_168h,
                q.post_amount_168h,
                q.post_has_history_168h
            FROM pre_decision AS p
            INNER JOIN post_event AS q USING (source_row_number, step)
            INNER JOIN labels AS l USING (source_row_number, step)
            ORDER BY p.step, p.source_row_number
            """
        ).to_arrow_table()
    finally:
        connection.close()
    if table.num_rows == 0:
        raise ValueError("Gold E1-E4 join produced zero rows")
    return table


def evaluate_gold_matrix(
    table: pa.Table,
    *,
    seed: int = 20_260_727,
    fixed_fpr: float = 0.01,
    max_boost_rounds: int = 300,
    mlflow_tracking_uri: str | None = None,
    mlflow_experiment_name: str = "pit-fintech-paysim-gold-e1-e4",
) -> tuple[GoldExperimentResult, ...]:
    """Train/evaluate all Gold E1-E4 specs with precision and recall at the locked threshold."""

    dependencies = _load_training_dependencies()
    if mlflow_tracking_uri is not None:
        from pit_fintech.models.paysim_lightgbm import configure_mlflow_experiment

        configure_mlflow_experiment(
            dependencies.mlflow,
            tracking_uri=mlflow_tracking_uri,
            experiment_name=mlflow_experiment_name,
            artifact_uri=None,
        )
    numpy = dependencies.numpy
    labels = numpy.asarray(table["target_label"].to_numpy()).astype("int64", copy=False)
    split = numpy.asarray(table["split"].to_pylist())
    indices = numpy.arange(table.num_rows)
    results: list[GoldExperimentResult] = []

    for spec in GOLD_EXPERIMENT_MATRIX:
        features = numpy.column_stack(
            [numpy.asarray(table[name].to_numpy(), dtype="float64") for name in spec.feature_names]
        )
        if spec.split_policy == "temporal":
            train_indices = indices[split == "train"]
            validation_indices = indices[split == "validation"]
            test_indices = indices[split == "test"]
        else:
            train_indices, remainder = dependencies.train_test_split(
                indices, test_size=0.4, random_state=seed, stratify=labels
            )
            validation_indices, test_indices = dependencies.train_test_split(
                remainder, test_size=0.5, random_state=seed + 1, stratify=labels[remainder]
            )
        for name, partition in (
            ("train", train_indices),
            ("validation", validation_indices),
            ("test", test_indices),
        ):
            if len(partition) == 0 or len(numpy.unique(labels[partition])) != 2:
                raise ValueError(
                    f"Gold {spec.experiment_id} {name} partition must contain both labels"
                )

        pandas = dependencies.pandas
        model = dependencies.lightgbm.LGBMClassifier(
            **{**_model_parameters(seed), "n_estimators": max_boost_rounds}
        )
        model.fit(
            pandas.DataFrame(features[train_indices], columns=spec.feature_names),
            labels[train_indices],
            eval_X=pandas.DataFrame(features[validation_indices], columns=spec.feature_names),
            eval_y=labels[validation_indices],
            eval_metric="binary_logloss",
            callbacks=[dependencies.lightgbm.early_stopping(30, verbose=False)],
            feature_name=list(spec.feature_names),
        )
        validation_scores = model.predict_proba(
            pandas.DataFrame(features[validation_indices], columns=spec.feature_names)
        )[:, 1]
        test_scores = model.predict_proba(
            pandas.DataFrame(features[test_indices], columns=spec.feature_names)
        )[:, 1]
        threshold = _threshold_for_fixed_fpr(
            labels[validation_indices],
            validation_scores,
            fixed_fpr=fixed_fpr,
            dependencies=dependencies,
        ).threshold
        operating = _binary_operating_metrics(labels[test_indices], test_scores, threshold)
        mlflow_run_id = None
        model_uri = None
        if mlflow_tracking_uri is not None:
            with dependencies.mlflow.start_run(
                run_name=f"gold-{spec.experiment_id}-{spec.feature_set}-{spec.split_policy}"
            ) as run:
                dependencies.mlflow.set_tags(
                    {
                        "experiment_id": spec.experiment_id,
                        "feature_set": spec.feature_set,
                        "split_policy": spec.split_policy,
                        "deployable": str(spec.deployable).lower(),
                        "purpose": spec.purpose,
                        "gold_e2_policy": "post_event_current_inclusive_control",
                    }
                )
                dependencies.mlflow.log_params(
                    {
                        "seed": seed,
                        "fixed_fpr": fixed_fpr,
                        "feature_count": len(spec.feature_names),
                        "train_rows": len(train_indices),
                        "validation_rows": len(validation_indices),
                        "test_rows": len(test_indices),
                    }
                )
                dependencies.mlflow.log_metrics(
                    {
                        "test_pr_auc": float(
                            dependencies.average_precision_score(labels[test_indices], test_scores)
                        ),
                        "test_roc_auc": float(
                            dependencies.roc_auc_score(labels[test_indices], test_scores)
                        ),
                        "test_recall": operating["test_recall_at_fixed_fpr"],
                        "test_precision": operating["test_precision_at_fixed_fpr"],
                        "test_observed_fpr": operating["test_observed_fpr"],
                        "validation_threshold": float(threshold),
                    }
                )
                dependencies.mlflow.log_dict(
                    {
                        "feature_names": list(spec.feature_names),
                        "deployable": spec.deployable,
                        "purpose": spec.purpose,
                    },
                    "feature-set.json",
                )
                dependencies.mlflow.log_dict(
                    {"ordered_feature_names": list(spec.feature_names)},
                    "ordered_feature_names.json",
                )
                dependencies.mlflow.log_dict(
                    {"threshold": float(threshold), "fixed_fpr": fixed_fpr},
                    "confusion_and_cost_curves.json",
                )
                dependencies.mlflow_sklearn.log_model(
                    sk_model=model,
                    name="model",
                    serialization_format="skops",
                    skops_trusted_types=list(SKOPS_TRUSTED_LIGHTGBM_TYPES),
                )
                mlflow_run_id = run.info.run_id
                model_uri = f"runs:/{mlflow_run_id}/model"
        results.append(
            GoldExperimentResult(
                experiment_id=spec.experiment_id,
                feature_set=spec.feature_set,
                split_policy=spec.split_policy,
                deployable=spec.deployable,
                rows=len(test_indices),
                fraud_rows=int(labels[test_indices].sum()),
                test_pr_auc=float(
                    dependencies.average_precision_score(labels[test_indices], test_scores)
                ),
                test_roc_auc=float(dependencies.roc_auc_score(labels[test_indices], test_scores)),
                test_recall=operating["test_recall_at_fixed_fpr"],
                test_precision=operating["test_precision_at_fixed_fpr"],
                observed_fpr=operating["test_observed_fpr"],
                validation_threshold=float(threshold),
                training_dataset_checksum=hashlib.sha256(
                    json.dumps(
                        {
                            "experiment_id": spec.experiment_id,
                            "feature_names": spec.feature_names,
                            "split_policy": spec.split_policy,
                            "train_rows": len(train_indices),
                            "validation_rows": len(validation_indices),
                            "test_rows": len(test_indices),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                mlflow_run_id=mlflow_run_id,
                model_uri=model_uri,
            )
        )
    return tuple(results)
