"""Environment-backed local configuration with safe defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PIT_",
        extra="ignore",
        case_sensitive=False,
    )

    project_root: Path = Path(".")
    data_root: Path = Path("./data")
    artifact_root: Path = Path("./artifacts")
    dataset: str = "sample"
    paysim_csv: Path | None = None
    entity_definition_version: str = "entity-application-candidate-v0"
    feature_definition_version: str = "fraud-history-v1"
    feature_service_version: str = "fraud-scoring-v1"
    float_tolerance: float = Field(default=1e-6, gt=0)
    redis_url: str = "redis://localhost:6379/0"
    mlflow_tracking_uri: str = "http://localhost:5000"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    jupyter_port: int = Field(default=8888, ge=1, le=65535)
    log_level: str = "INFO"
    log_json: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
