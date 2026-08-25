"""YAML-backed local configuration with optional process-environment overrides."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from pit_fintech.features.paysim_specs import (
    PAYSIM_FEATURE_DEFINITION_VERSION,
    PAYSIM_FEATURE_SERVICE_VERSION,
)

# config.yaml lives at the repo root (this file is src/pit_fintech/config.py).
_REPO_CONFIG_YAML = Path(__file__).resolve().parents[2] / "config.yaml"


def _resolve_yaml_file() -> str:
    """Pick the config.yaml to load, evaluated at Settings() construction (respects CWD).

    A ``config.yaml`` in the current working directory wins (deployment/test override); otherwise
    fall back to the repo-root copy. The repo-root fallback matters when the process CWD is not the
    repo root -- notably a Jupyter kernel started inside ``notebooks/`` -- where a relative
    "config.yaml" would be missed and settings would silently fall back to hardcoded defaults.
    """
    cwd_config = Path("config.yaml")
    if cwd_config.exists():
        return str(cwd_config)
    if _REPO_CONFIG_YAML.exists():
        return str(_REPO_CONFIG_YAML)
    return "config.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIT_",
        yaml_file="config.yaml",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: InitSettingsSource,
        env_settings: EnvSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: SecretsSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load process environment first, then committed YAML defaults.

        A dotenv file is deliberately not loaded. Deployment-specific values may still be supplied
        explicitly as ``PIT_*`` process environment variables, but ``config.yaml`` is the normal
        local runtime source. The YAML path is resolved CWD-first with a repo-root fallback so a
        Jupyter kernel launched inside ``notebooks/`` still finds it.
        """
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=_resolve_yaml_file()),
            file_secret_settings,
        )

    project_root: Path = Path(".")
    data_root: Path = Path("./data")
    artifact_root: Path = Path("./artifacts")
    dataset: str = "sample"
    paysim_csv: Path | None = None
    entity_definition_version: str = "paysim-destination-customer-v1"
    feature_definition_version: str = PAYSIM_FEATURE_DEFINITION_VERSION
    feature_service_version: str = PAYSIM_FEATURE_SERVICE_VERSION
    float_tolerance: float = Field(default=1e-6, gt=0)
    redis_url: str = "redis://localhost:6379/0"
    mlflow_tracking_uri: str = "http://localhost:5000"
    #: Explicit MLflow model id the serving process pulls from ``mlflow_tracking_uri`` (the shared
    #: registry). A registry URI (``models:/paysim-fraud-lightgbm/3``) or a run URI
    #: (``runs:/<run_id>/model``). When None, serving keeps its champion-alias / latest-run
    #: resolution. Change this one value to promote or roll back the served model.
    serving_model_uri: str | None = None
    #: Local MLflow tracking URI to fall back to when the shared registry above is unreachable at
    #: serving startup. When None, `pit serving up` fills it with the local SQLite backend.
    serving_model_local_fallback: str | None = None
    #: Directory where serving caches pulled model artifacts across restarts (HuggingFace-hub
    #: style), keyed by the model's backing MLflow run id, so a restart loads the model from local
    #: disk instead of re-downloading it. None -> ``~/.cache/pit-fintech/mlflow-models``.
    serving_model_cache_dir: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    jupyter_port: int = Field(default=8888, ge=1, le=65535)
    log_level: str = "INFO"
    log_json: bool = False
    #: Self-hosted OTLP/HTTP collector base URL (env `PIT_OTEL_ENDPOINT`), e.g.
    #: ``http://<collector-host>:4318``. Fed into `pit serving up --otel` as the default
    #: `--otel-endpoint`; an explicit CLI flag still overrides it.
    otel_endpoint: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
