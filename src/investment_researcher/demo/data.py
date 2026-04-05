"""Data access layer for the demo dashboard.

Thin wrapper around DuckDB queries returning pandas DataFrames.
"""

import duckdb
import numpy as np
import pandas as pd

from investment_researcher.config import DUCKDB_PATH
from investment_researcher.metrics import compute_ttm_metrics
from investment_researcher.ratios import (
    compute_ratios,
    compute_ratios_wide,
    compute_ttm_ratios,
    latest_ratios,
)

_DB_PATH = DUCKDB_PATH


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(_DB_PATH, read_only=True)


# ── Ticker helpers ───────────────────────────────────────────────────────────

def get_all_tickers() -> list[str]:
    """Return a sorted list of every ticker in the database."""
    con = _con()
    try:
        return con.execute(
            "SELECT DISTINCT ticker FROM financial_metrics ORDER BY ticker"
        ).df()["ticker"].tolist()
    finally:
        con.close()


def ticker_summary(
    ticker: str,
    period_type: str = "annual",
) -> pd.DataFrame:
    """Latest value for every metric_type for *ticker* and *period_type*."""
    con = _con()
    try:
        return con.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY metric_type
                    ORDER BY period_end DESC
                ) AS rn
                FROM financial_metrics
                WHERE ticker = $1 AND period_type = $2
            )
            SELECT metric_type, value, period_end
            FROM ranked WHERE rn = 1
            ORDER BY metric_type
            """,
            [ticker, period_type],
        ).df()
    finally:
        con.close()


# ── Time-series queries ─────────────────────────────────────────────────────

def metric_timeseries(
    ticker: str,
    metrics: list[str],
    period_type: str = "annual",
) -> pd.DataFrame:
    """Return a time series of *metrics* for *ticker*.

    Columns: metric_type, value, period_end
    """
    con = _con()
    try:
        placeholders = ", ".join(f"'{m}'" for m in metrics)
        return con.execute(
            f"""
            SELECT metric_type, value, period_end
            FROM financial_metrics
            WHERE ticker = $1
              AND period_type = $2
              AND metric_type IN ({placeholders})
            ORDER BY period_end
            """,
            [ticker, period_type],
        ).df()
    finally:
        con.close()


def pivot_metrics(
    ticker: str,
    metrics: list[str],
    period_type: str = "annual",
) -> pd.DataFrame:
    """Pivoted: rows = period_end, columns = metric_type."""
    df = metric_timeseries(ticker, metrics, period_type)
    if df.empty:
        return df
    return df.pivot(index="period_end", columns="metric_type", values="value").sort_index()


def growth_rates(
    ticker: str,
    metrics: list[str],
    period_type: str = "annual",
) -> pd.DataFrame:
    """Year-over-year percentage growth for each metric.

    For annual data, compares adjacent periods (shift 1).
    For quarterly data, compares same quarter prior year (shift 4).
    """
    piv = pivot_metrics(ticker, metrics, period_type)
    if piv.empty:
        return piv
    shift = 4 if period_type == "quarterly" else 1
    return (piv / piv.shift(shift) - 1).dropna(how="all") * 100


# ── Cross-company queries ────────────────────────────────────────────────────

def latest_metric_for_all(metric_type: str, period_type: str = "annual", limit: int = 20) -> pd.DataFrame:
    """Top *limit* companies by the latest value of *metric_type*."""
    con = _con()
    try:
        return con.execute(
            """
            WITH ranked AS (
                SELECT ticker, value, period_end,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY period_end DESC) AS rn
                FROM financial_metrics
                WHERE metric_type = $1 AND period_type = $2
            )
            SELECT ticker, value, period_end
            FROM ranked WHERE rn = 1
            ORDER BY value DESC
            LIMIT $3
            """,
            [metric_type, period_type, limit],
        ).df()
    finally:
        con.close()


# ── TTM and quarterly detail ─────────────────────────────────────────────────

def ttm_metrics(
    ticker: str,
    metrics: list[str],
) -> dict[str, float]:
    """Compute Trailing Twelve Months for the requested *metrics*.

    Delegates to the backend :func:`compute_ttm_metrics` which handles
    flow-metric summation, stock-metric snapshots, annual fallbacks, and
    derived-metric enrichment.  The result is filtered to only the requested
    metric names.
    """
    all_ttm = compute_ttm_metrics(ticker, db_path=_DB_PATH)
    return {m: all_ttm[m] for m in metrics if m in all_ttm}


def quarterly_detail(
    ticker: str,
    metrics: list[str],
    n_quarters: int = 8,
) -> pd.DataFrame:
    """Return a table of discrete quarterly values + TTM column.

    Returns a DataFrame with:
      - index = metric_type
      - columns = ['TTM', 'Quarter Ended 09/28/2024', ...] (reverse chronological)
    """
    con = _con()
    try:
        placeholders = ", ".join(f"'{m}'" for m in metrics)
        df = con.execute(
            f"""
            WITH recent_periods AS (
                SELECT period_end, MIN(period) AS period
                FROM financial_metrics
                WHERE ticker = $1
                  AND period_type = 'quarterly'
                  AND metric_type IN ({placeholders})
                GROUP BY period_end
                ORDER BY period_end DESC
                LIMIT {int(n_quarters)}
            )
            SELECT fm.metric_type, fm.value, rp.period, fm.period_end
            FROM financial_metrics fm
            INNER JOIN recent_periods rp
                ON fm.period_end = rp.period_end
            WHERE fm.ticker = $1
              AND fm.period_type = 'quarterly'
              AND fm.metric_type IN ({placeholders})
            ORDER BY fm.period_end DESC, fm.metric_type
            """,
            [ticker],
        ).df()
    finally:
        con.close()

    if df.empty:
        return pd.DataFrame()

    latest_window_period_end = df["period_end"].max()

    # Pivot: rows=metric_type, columns=period (e.g. Q1-2026)
    pivot = df.pivot_table(
        index="metric_type", columns="period", values="value", aggfunc="first"
    )

    # Sort columns by period_end (most recent first)
    period_order = (
        df[["period", "period_end"]]
        .drop_duplicates("period")
        .sort_values("period_end", ascending=False)["period"]
        .tolist()
    )
    pivot = pivot[[p for p in period_order if p in pivot.columns]]

    # Preserve the requested metric order even if some metrics are missing for
    # the currently selected quarter window.
    pivot = pivot.reindex(metrics)

    # Track recency per metric across all available quarterly rows.  This lets
    # the UI suppress stale TTM values for metrics that are no longer reported
    # in recent filings.
    con = _con()
    try:
        placeholders = ", ".join(f"'{m}'" for m in metrics)
        latest_metric_df = con.execute(
            f"""
            SELECT metric_type, MAX(period_end) AS latest_period_end
            FROM financial_metrics
            WHERE ticker = $1
              AND period_type = 'quarterly'
              AND metric_type IN ({placeholders})
            GROUP BY metric_type
            """,
            [ticker],
        ).df()
    finally:
        con.close()

    latest_metric_period = dict(
        zip(latest_metric_df["metric_type"], latest_metric_df["latest_period_end"])
    )

    # Add TTM column, but only when the metric is current through the latest
    # visible quarter. Otherwise TTM can look deceptively "fresh" even when the
    # underlying metric has not been reported for several quarters.
    ttm = ttm_metrics(ticker, metrics)
    pivot.insert(
        0,
        "TTM",
        pivot.index.map(
            lambda m: ttm.get(m, np.nan)
            if latest_metric_period.get(m) == latest_window_period_end
            else np.nan
        ),
    )

    return pivot


# ── Ratio convenience functions ──────────────────────────────────────────────

def ratio_timeseries(
    ticker: str,
    ratio_names: list[str] | None = None,
    period_type: str = "annual",
) -> pd.DataFrame:
    """Return ratio values over time (long-form).

    Delegates to ratios.compute_ratios().
    """
    return compute_ratios(ticker, period_type, ratio_names)


def all_ratios_wide(
    ticker: str,
    period_type: str = "annual",
) -> pd.DataFrame:
    """Return all computable ratios in wide-form (period_end × ratio_name)."""
    return compute_ratios_wide(ticker, period_type)


def all_ratios_latest(
    ticker: str,
    period_type: str = "annual",
) -> dict[str, float]:
    """Return the latest value for every computable ratio."""
    return latest_ratios(ticker, period_type)


def all_ratios_ttm(ticker: str) -> dict[str, float]:
    """Return TTM (Trailing Twelve Months) value for every computable ratio."""
    return compute_ttm_ratios(ticker)
