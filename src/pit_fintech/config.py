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
        local runtime source.
        """
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
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
