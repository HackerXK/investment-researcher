"""Metric display metadata for API consumers.

Raw metric values remain in their canonical backend units. This module exposes
lightweight display hints so mixed-unit tables can render per-share and share
count metrics correctly without guessing from the metric name in the client.
"""

from __future__ import annotations

from typing import Literal


MetricDisplayFormat = Literal["millions", "per_share", "count", "number"]

DEFAULT_METRIC_DISPLAY_FORMAT: MetricDisplayFormat = "millions"

_METRIC_DISPLAY_FORMATS: dict[str, MetricDisplayFormat] = {
    "common_shares_outstanding": "count",
    "eps_basic": "per_share",
    "eps_diluted": "per_share",
}


def get_metric_display_formats(metrics: list[str] | tuple[str, ...] | set[str]) -> dict[str, MetricDisplayFormat]:
    """Return display-format hints keyed by metric_type."""
    return {
        metric: _METRIC_DISPLAY_FORMATS.get(metric, DEFAULT_METRIC_DISPLAY_FORMAT)
        for metric in metrics
    }