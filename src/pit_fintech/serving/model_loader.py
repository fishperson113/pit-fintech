"""MLflow champion model resolution for the serving boundary.

The serving process must never silently choose the newest finished training run. A model becomes
servable only after it is registered and the ``champion`` alias points at its explicit version.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChampionModel:
    """One MLflow registry alias resolution plus the model input contract."""

    model: Any
    registered_model_name: str
    alias: str
    model_version: str
    mlflow_run_id: str
    model_uri: str
    ordered_feature_names: tuple[str, ...]
    decision_threshold: float


def load_champion_model(
    *,
    tracking_uri: str,
    registered_model_name: str,
    alias: str = "champion",
    client: Any | None = None,
    model_loader: Callable[[str], Any] | None = None,
    artifact_loader: Callable[[str], dict[str, Any]] | None = None,
) -> ChampionModel:
    """Resolve and load an explicit MLflow registry alias.

    ``client``, ``model_loader`` and ``artifact_loader`` are injectable for the contract tests; the
    production path uses MLflow's tracking client and sklearn loader. Missing aliases and malformed
    contract artifacts fail closed rather than falling back to ``latest``.
    """

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    resolved_client = client or mlflow.MlflowClient()
    try:
        model_version = resolved_client.get_model_version_by_alias(registered_model_name, alias)
    except Exception as exc:
        raise RuntimeError(
            f"MLflow champion alias {registered_model_name!r}@{alias!r} is not available; "
            "promote a validated model before starting serving"
        ) from exc

    version = str(getattr(model_version, "version", ""))
    run_id = str(getattr(model_version, "run_id", ""))
    if not version or not run_id:
        raise RuntimeError("MLflow champion alias returned an incomplete model version")

    model_uri = f"models:/{registered_model_name}@{alias}"
    resolved_model_uri = f"runs:/{run_id}/model"
    load_model = model_loader or mlflow.sklearn.load_model
    load_artifact = artifact_loader or mlflow.artifacts.load_dict
    model = load_model(resolved_model_uri)

    feature_payload = load_artifact(f"runs:/{run_id}/ordered_feature_names.json")
    ordered_feature_names = tuple(feature_payload["ordered_feature_names"])
    threshold_payload = load_artifact(f"runs:/{run_id}/confusion_and_cost_curves.json")
    decision_threshold = float(threshold_payload["threshold"])

    return ChampionModel(
        model=model,
        registered_model_name=registered_model_name,
        alias=alias,
        model_version=version,
        mlflow_run_id=run_id,
        model_uri=model_uri,
        ordered_feature_names=ordered_feature_names,
        decision_threshold=decision_threshold,
    )


def promote_run_to_champion(
    *,
    tracking_uri: str,
    registered_model_name: str,
    mlflow_run_id: str,
    client: Any | None = None,
) -> str:
    """Register one validated run and move the MLflow ``champion`` alias to its version."""

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    resolved_client = client or mlflow.MlflowClient()
    try:
        resolved_client.get_registered_model(registered_model_name)
    except Exception:
        resolved_client.create_registered_model(registered_model_name)

    existing = tuple(
        resolved_client.search_model_versions(
            f"name='{registered_model_name}' and run_id='{mlflow_run_id}'"
        )
    )
    if existing:
        version = str(existing[0].version)
    else:
        created = resolved_client.create_model_version(
            name=registered_model_name,
            source=f"runs:/{mlflow_run_id}/model",
            run_id=mlflow_run_id,
        )
        version = str(created.version)
    resolved_client.set_registered_model_alias(registered_model_name, "champion", version)
    return version
