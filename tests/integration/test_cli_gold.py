from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import pit_fintech.cli as cli
from pit_fintech.cli import app

pytestmark = pytest.mark.integration

runner = CliRunner()


def _fake_build(run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        status="staged",
        pre_decision=SimpleNamespace(
            rows=4,
            partitions_written=(2,),
            logical_checksum="pre-checksum",
        ),
        post_event_state=SimpleNamespace(
            rows=6,
            partitions_written=(2,),
            logical_checksum="post-checksum",
        ),
    )


def test_features_build_gold_routes_to_staging_without_promote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []

    def fake_build(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return _fake_build(str(kwargs["run_id"]))

    monkeypatch.setattr(cli, "_gold_roots", lambda: (tmp_path, tmp_path, tmp_path))
    monkeypatch.setattr(cli, "build_offline_features", fake_build)

    result = runner.invoke(
        app,
        [
            "features",
            "build-gold",
            "--start",
            "2",
            "--end",
            "2",
            "--run-id",
            "cli-gold-test",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [
        {
            "project_root": tmp_path,
            "data_root": tmp_path,
            "artifact_root": tmp_path,
            "run_id": "cli-gold-test",
            "cutoff_start_step": 2,
            "cutoff_end_step": 2,
            "promote": False,
            "progress": True,
        }
    ]
    assert "run_id: cli-gold-test" in result.stdout
    assert "status: staged; promote: False" in result.stdout


def test_features_promote_gold_loads_staged_manifest_and_promotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    build = _fake_build("cli-gold-promote-test")
    promotion = SimpleNamespace(
        run_id="cli-gold-promote-test",
        promoted=True,
        strategy="partition_overwrite",
        predicate="event_day IN (CAST(2 AS INT))",
        pre_decision_version=3,
        post_event_state_version=4,
    )
    manifest_path = tmp_path / "runs" / build.run_id / "gold-build-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_promote(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return promotion

    monkeypatch.setattr(cli, "_gold_roots", lambda: (tmp_path, tmp_path, tmp_path))
    monkeypatch.setattr(cli, "_load_gold_build_result", lambda path: build)
    monkeypatch.setattr(cli, "promote_staged_gold", fake_promote)

    result = runner.invoke(
        app,
        ["features", "promote-gold", "--run-id", "cli-gold-promote-test"],
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [{"build": build, "data_root": tmp_path, "progress": True}]
    assert "promoted: True" in result.stdout
    assert "pre_decision_features_version: 3" in result.stdout
    assert "post_event_state_updates_version: 4" in result.stdout
