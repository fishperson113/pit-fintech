from __future__ import annotations

from pathlib import Path

from pit_fintech.config import Settings


def test_settings_load_non_secret_defaults_from_config_yaml(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            (
                "project_root: ./workspace",
                "data_root: ./lakehouse",
                "artifact_root: ./runs",
                "dataset: paysim",
                "float_tolerance: 0.00001",
                "api_host: 0.0.0.0",
                "api_port: 8100",
                "log_json: true",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for name in (
        "PIT_PROJECT_ROOT",
        "PIT_DATA_ROOT",
        "PIT_ARTIFACT_ROOT",
        "PIT_DATASET",
        "PIT_FLOAT_TOLERANCE",
        "PIT_API_HOST",
        "PIT_API_PORT",
        "PIT_LOG_JSON",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.project_root == Path("workspace")
    assert settings.data_root == Path("lakehouse")
    assert settings.artifact_root == Path("runs")
    assert settings.dataset == "paysim"
    assert settings.float_tolerance == 0.00001
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8100
    assert settings.log_json is True


def test_environment_overrides_yaml_values(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.yaml").write_text("api_port: 8100\nlog_json: false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PIT_API_PORT", "8200")
    monkeypatch.setenv("PIT_LOG_JSON", "true")

    settings = Settings()

    assert settings.api_port == 8200
    assert settings.log_json is True
