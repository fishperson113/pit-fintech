from __future__ import annotations

from pit_fintech.serving.app import _MetricsState


def test_metrics_render_exposes_prometheus_histogram_buckets() -> None:
    metrics = _MetricsState()
    metrics.record_success(12.5)
    metrics.record_success(125.0)
    metrics.record_error()

    rendered = metrics.render()

    assert "pit_scoring_requests_total 3" in rendered
    assert "pit_scoring_errors_total 1" in rendered
    assert 'pit_scoring_latency_ms_bucket{le="25"} 1' in rendered
    assert 'pit_scoring_latency_ms_bucket{le="250"} 2' in rendered
    assert 'pit_scoring_latency_ms_bucket{le="+Inf"} 2' in rendered
    assert "pit_scoring_latency_ms_count 2" in rendered
    assert "pit_scoring_latency_ms_sum 137.500" in rendered
