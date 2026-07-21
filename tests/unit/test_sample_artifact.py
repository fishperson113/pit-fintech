from __future__ import annotations

from pit_fintech.data.sample import PARQUET_PATH, build_sample_fixture, load_parquet_events


def test_sample_fixture_has_deterministic_logical_counts() -> None:
    manifest = build_sample_fixture()
    assert PARQUET_PATH.exists()
    assert manifest.source_rows == 8
    assert manifest.canonical_rows == 7
    assert len(load_parquet_events()) == 8
