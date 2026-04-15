"""Shared helpers for golden data integration tests."""

import tempfile
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest

import edgar

from investment_researcher.ingestion.edgar.financials import (
    extract_company_facts,
)
from investment_researcher.signs import normalize_extracted_metric_value
from investment_researcher.ingestion.timeseries import get_connection, initialize_db
from investment_researcher.ingestion.state import initialize_state_db

# ── Shared types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldenMetric:
    """A single known-correct financial data point."""
    metric_type: str
    period_type: str   # "annual" or "quarterly"
    period_end: date
    value: float
    source: str        # "dera", "fmp", or "both"
    tolerance_pct: float = 1.0  # percentage tolerance for comparison


@dataclass(frozen=True)
class GoldenRatio:
    """A single known-correct financial ratio value."""
    ratio_name: str
    period_type: str   # "annual" or "quarterly"
    period_end: date
    value: float
    source: str        # "fmp"
    tolerance_pct: float = 5.0  # percentage tolerance for comparison
    skip_reason: str | None = None  # if set, this golden entry is skipped


@dataclass(frozen=True)
class GoldenTTMRatio:
    """A single known-correct TTM financial ratio value (snapshot, no date)."""
    ratio_name: str
    value: float
    source: str        # "fmp"
    tolerance_pct: float = 15.0  # higher tolerance for TTM comparisons
    skip_reason: str | None = None  # if set, this golden entry is skipped


@dataclass(frozen=True)
class GoldenTTMMetric:
    """A single known-correct TTM metric value (snapshot, no date).

    Used to validate that compute_ttm_metrics() produces correct output
    by comparing against FMP TTM endpoint values.
    """
    metric_type: str
    value: float
    tolerance_pct: float = 5.0  # percentage tolerance for comparison


# ── Constants ────────────────────────────────────────────────────────────────

DATE_TOLERANCE_DAYS = 7  # DERA rounds to month-end; edgartools uses exact dates


# ── Helpers ──────────────────────────────────────────────────────────────────

def find_match(
    rows: list[dict],
    metric_type: str,
    period_type: str,
    golden_pe: date,
) -> dict | None:
    """Find a DuckDB row matching the golden metric (with date tolerance)."""
    best = None
    best_delta = timedelta(days=DATE_TOLERANCE_DAYS + 1)
    for r in rows:
        if r["metric_type"] != metric_type or r["period_type"] != period_type:
            continue
        pe = r["period_end"]
        if hasattr(pe, "date"):
            pe = pe.date()
        elif isinstance(pe, str):
            pe = date.fromisoformat(pe)
        delta = abs(pe - golden_pe)
        if delta <= timedelta(days=DATE_TOLERANCE_DAYS) and delta < best_delta:
            best = r
            best_delta = delta
    return best


def assert_value_close(actual: float, golden, label: str):
    """Assert that actual value is within tolerance of golden value."""
    expected = normalize_extracted_metric_value(golden.metric_type, golden.value)
    if golden.metric_type == "eps_diluted":
        assert abs(actual - expected) <= golden.tolerance_pct, (
            f"{label}: EPS {actual} vs golden {expected}, "
            f"diff=${abs(actual - expected):.4f} > ${golden.tolerance_pct}"
        )
    elif expected != 0:
        pct = abs(actual - expected) / abs(expected) * 100
        assert pct <= golden.tolerance_pct, (
            f"{label}: {actual:,.0f} vs golden {expected:,.0f}, "
            f"diff={pct:.2f}% > {golden.tolerance_pct}%"
        )
    else:
        assert actual == 0, f"{label}: expected 0, got {actual}"


def assert_ratio_close(actual: float, golden: "GoldenRatio", label: str):
    """Assert that an actual ratio is within tolerance of the golden value."""
    expected = golden.value
    if expected == 0:
        assert abs(actual) < 0.001, f"{label}: expected ~0, got {actual}"
        return
    pct = abs(actual - expected) / abs(expected) * 100
    assert pct <= golden.tolerance_pct, (
        f"{label}: {actual:.6f} vs golden {expected:.6f}, "
        f"diff={pct:.2f}% > {golden.tolerance_pct}%"
    )


def assert_ttm_ratio_close(actual: float, golden: "GoldenTTMRatio", label: str):
    """Assert that an actual TTM ratio is within tolerance of the golden value."""
    assert_ratio_close(actual, golden, label)


def assert_ttm_metric_close(actual: float, golden: "GoldenTTMMetric", label: str):
    """Assert that an actual TTM metric is within tolerance of the golden value."""
    assert_value_close(actual, golden, label)


def extract_ticker_rows(ticker: str) -> list[dict]:
    """Extract data for a ticker and return all rows from DuckDB."""
    edgar.set_identity("test@example.com")
    with tempfile.TemporaryDirectory() as tmp:
        db = str(f"{tmp}/test.duckdb")
        state = str(f"{tmp}/test_state.db")
        initialize_db(db_path=db)
        initialize_state_db(db_path=state)

        count = extract_company_facts(ticker, db_path=db, state_db_path=state)
        assert count > 0, f"extract_company_facts returned 0 rows for {ticker}"

        con = get_connection(db)
        try:
            rows = con.execute(
                "SELECT * FROM financial_metrics WHERE ticker = ?", [ticker]
            ).fetchdf().to_dict("records")
        finally:
            con.close()

    return rows
