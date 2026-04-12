"""Financial analytics module — public API for the FastAPI backend.

Consolidates DuckDB queries (``analytics.queries``), metric helpers
(``metrics``), and ratio computations (``ratios``) into a single
importable surface.  Also provides company search and SEC filing
access via edgartools.
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from investment_researcher.config import DUCKDB_PATH_RUNTIME
from investment_researcher.analytics.queries import (
    get_all_tickers,
    growth_rates,
    latest_metric_for_all,
    metric_timeseries,
    pivot_metrics,
    quarterly_detail,
    ticker_summary,
    ttm_metrics,
    ratio_timeseries,
    all_ratios_latest as _ratios_latest,
    all_ratios_ttm as _ratios_ttm,
    all_ratios_wide as _ratios_wide,
)
from investment_researcher.ratios import (
    RATIO_CATEGORIES,
    RATIO_REGISTRY,
    get_ratios_by_category,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports (unchanged signatures)
# ---------------------------------------------------------------------------

__all__ = [
    # Ticker helpers
    "get_all_tickers",
    "search_companies",
    "get_company_profile",
    # Time-series
    "ticker_summary",
    "metric_timeseries",
    "pivot_metrics",
    "growth_rates",
    "latest_metric_for_all",
    # TTM & quarterly
    "ttm_metrics",
    "quarterly_detail",
    # Ratios
    "get_ratios_latest",
    "get_ratios_wide",
    "get_ratios_ttm",
    "get_ratios_by_category",
    "ratio_timeseries",
    "RATIO_CATEGORIES",
    "RATIO_REGISTRY",
    # Filing access
    "get_filings_list",
    "get_filing_text",
]


# ---------------------------------------------------------------------------
# Wrapper aliases (match the FastAPI-friendly naming)
# ---------------------------------------------------------------------------


def get_ratios_latest(ticker: str, period_type: str = "annual") -> dict[str, float]:
    """Latest value for every computable ratio."""
    return _ratios_latest(ticker, period_type)


def get_ratios_wide(ticker: str, period_type: str = "annual") -> pd.DataFrame:
    """All computable ratios in wide-form (period_end × ratio_name)."""
    return _ratios_wide(ticker, period_type)


def get_ratios_ttm(ticker: str) -> dict[str, float]:
    """TTM value for every computable ratio."""
    return _ratios_ttm(ticker)


# ---------------------------------------------------------------------------
# NEW — Company search & profile (backed by DuckDB + edgartools)
# ---------------------------------------------------------------------------

def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DUCKDB_PATH_RUNTIME, read_only=True)


def search_companies(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search companies by ticker prefix (case-insensitive).

    Returns a list of ``{"ticker": ..., "latest_period": ...}`` dicts.
    """
    if not query or not query.strip():
        return []
    q = query.strip().upper()
    con = _con()
    try:
        df = con.execute(
            """
            SELECT DISTINCT ticker
            FROM financial_metrics
            WHERE ticker LIKE $1
            ORDER BY ticker
            LIMIT $2
            """,
            [f"{q}%", limit],
        ).df()
    finally:
        con.close()
    return [{"ticker": t} for t in df["ticker"].tolist()]


def get_company_profile(ticker: str) -> dict[str, Any]:
    """Return company metadata combining DuckDB + edgartools.

    Falls back gracefully if edgartools is unavailable or the company
    cannot be resolved.
    """
    profile: dict[str, Any] = {"ticker": ticker.upper()}

    # Gather latest metrics from DuckDB
    summary = ticker_summary(ticker.upper())
    if not summary.empty:
        latest_map = dict(zip(summary["metric_type"], summary["value"]))
        profile["latest_metrics"] = {
            k: (None if (v is None or (isinstance(v, float) and np.isnan(v))) else v)
            for k, v in latest_map.items()
        }
        if "period_end" in summary.columns:
            profile["last_period"] = str(summary["period_end"].max())

    # Try edgartools for richer metadata (name, CIK, SIC, industry)
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        profile["name"] = getattr(co, "name", None)
        profile["cik"] = getattr(co, "cik", None)
        profile["sic"] = getattr(co, "sic", None)
        profile["sic_description"] = getattr(co, "sic_description", None) or getattr(co, "industry", None)
        profile["state"] = getattr(co, "state_of_incorporation", None)
        profile["fiscal_year_end"] = getattr(co, "fiscal_year_end", None)
    except Exception:
        log.debug("edgartools metadata unavailable for %s", ticker, exc_info=True)

    return profile


# ---------------------------------------------------------------------------
# NEW — Filing access via edgartools
# ---------------------------------------------------------------------------


def get_filings_list(
    ticker: str,
    form_type: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return recent filings for *ticker* as a list of dicts.

    Each dict contains ``accession_number``, ``form_type``, ``filing_date``,
    ``primary_document``, and ``description``.
    """
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings()
        if form_type:
            filings = filings.filter(form=form_type)
        result: list[dict[str, Any]] = []
        for f in filings[:limit]:
            result.append(
                {
                    "accession_number": getattr(f, "accession_no", None),
                    "form_type": getattr(f, "form", None),
                    "filing_date": str(getattr(f, "filing_date", "")),
                    "primary_document": getattr(f, "primary_doc_url", None),
                    "description": getattr(f, "description", None) or "",
                }
            )
        return result
    except Exception:
        log.warning("Could not list filings for %s", ticker, exc_info=True)
        return []


def get_filing_text(ticker: str, accession_number: str) -> str:
    """Return a filing's full text as markdown.

    Uses edgartools ``filing.markdown()`` which converts the SEC HTML
    filing into clean markdown — ideal for LLM context.
    """
    try:
        from edgar import Company as EdgarCompany, find

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings()
        for f in filings:
            acc = getattr(f, "accession_no", None)
            if acc and acc.replace("-", "") == accession_number.replace("-", ""):
                return f.markdown()
        return ""
    except Exception:
        log.warning(
            "Could not retrieve filing text for %s / %s",
            ticker,
            accession_number,
            exc_info=True,
        )
        return ""
