from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pit_fintech.serving import app as serving_app


def test_cached_native_lightgbm_model_uses_lightgbm_flavor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mlflow = pytest.importorskip("mlflow")
    pytest.importorskip("mlflow.lightgbm")
    pytest.importorskip("mlflow.sklearn")
    cache_root = tmp_path / "cache"
    model_dir = cache_root / "run-lgbm"
    model_dir.mkdir(parents=True)
    (model_dir / "MLmodel").write_text("flavors:\n  lightgbm: {}\n", encoding="utf-8")
    expected = object()
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        mlflow.models.Model,
        "load",
        lambda path: SimpleNamespace(flavors={"lightgbm": {}, "python_function": {}}),
    )
    monkeypatch.setattr(
        mlflow.lightgbm,
        "load_model",
        lambda path: calls.append(("lightgbm", path)) or expected,
    )
    monkeypatch.setattr(
        mlflow.sklearn,
        "load_model",
        lambda path: calls.append(("sklearn", path)) or object(),
    )

    loaded = serving_app._load_mlflow_model_cached(
        model_uri="models:/paysim-fraud-lightgbm/1",
        run_id="run-lgbm",
        cache_root=cache_root,
    )

    assert loaded is expected
    assert calls == [("lightgbm", str(model_dir))]


def test_model_deserialization_error_does_not_trigger_tracking_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mlflow = pytest.importorskip("mlflow")
    tracking_uris: list[str] = []
    model_dir = tmp_path / "run-invalid"
    model_dir.mkdir()
    (model_dir / "MLmodel").write_text("flavors:\n  unsupported: {}\n", encoding="utf-8")

    monkeypatch.setattr(mlflow, "set_tracking_uri", tracking_uris.append)
    monkeypatch.setattr(serving_app, "_resolve_run_id", lambda model_uri: "run-invalid")

    with pytest.raises(RuntimeError, match="unsupported MLflow model flavors"):
        serving_app._load_model_by_uri(
            model_uri="models:/paysim-fraud-lightgbm/1",
            tracking_uri="http://shared-mlflow:5000",
            fallback_tracking_uri="sqlite:///local.db",
            cache_root=tmp_path,
        )

    assert tracking_uris == ["http://shared-mlflow:5000"]
