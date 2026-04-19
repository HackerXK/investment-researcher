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
    cashflow_pivot,
    cashflow_timeseries,
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
    "cashflow_timeseries",
    "cashflow_pivot",
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
    "get_insider_trades",
]


_FORM4_CODE_DESCRIPTIONS = {
    "P": "Open Market Purchase",
    "S": "Open Market Sale",
    "A": "Grant/Award",
    "M": "Option Exercise",
    "F": "Tax Withholding",
    "G": "Gift",
    "X": "Option Exercise",
    "D": "Disposition to Issuer",
    "C": "Conversion",
    "E": "Expiration of Short Position",
    "H": "Expiration of Long Position",
    "I": "Discretionary Transaction",
    "O": "Exercise of Out-of-Money Derivative",
    "U": "Disposition (Tender of Shares)",
    "Z": "Deposit/Withdrawal (Voting Trust)",
}

_NOTABLE_TRADE_VALUE = 100_000.0
_VERY_NOTABLE_TRADE_VALUE = 1_000_000.0


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
    start_date: str | None = None,
    end_date: str | None = None,
    include_amendments: bool = True,
) -> list[dict[str, Any]]:
    """Return recent filings for *ticker* as a list of dicts.

    Each dict contains ``accession_number``, ``form_type``, ``filing_date``,
    ``primary_document``, and ``description``.
    """
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings(
            form=form_type,
            filing_date=_build_filing_date_filter(start_date, end_date),
            amendments=include_amendments,
        )
        if filings is None:
            return []
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


def _build_filing_date_filter(
    start_date: str | None,
    end_date: str | None,
) -> str | None:
    """Build an edgartools-compatible filing date filter."""
    if start_date and end_date:
        return f"{start_date}:{end_date}"
    if start_date:
        return f"{start_date}:"
    if end_date:
        return f":{end_date}"
    return None


def _normalize_number(value: Any) -> int | float | None:
    """Convert pandas / Python numeric-like values to JSON-safe numbers."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _classify_trade_significance(value: Any) -> str:
    """Bucket a trade's value for quick screening."""
    numeric = _normalize_number(value)
    magnitude = abs(float(numeric)) if numeric is not None else 0.0
    if magnitude < _NOTABLE_TRADE_VALUE:
        return "Normal"
    if magnitude < _VERY_NOTABLE_TRADE_VALUE:
        return "Notable"
    return "Very notable"


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


def get_insider_trades(
    ticker: str,
    start_date: str,
    end_date: str,
    transaction_codes: list[str] | None = None,
    acquired_disposed: str | None = "D",
    min_value: float = 0.0,
    limit: int = 200,
    include_amendments: bool = False,
) -> list[dict[str, Any]]:
    """Return structured Form 4 transactions for a date range.

    This is the preferred interface for insider-trading questions because it
    returns transaction-level fields directly instead of forcing the agent to
    iterate through raw filing markdown.

    Typical sell screens use ``transaction_codes=["S", "F"]`` and
    ``acquired_disposed="D"`` to capture discretionary sales plus tax
    withholding dispositions.
    """
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings(
            form="4",
            filing_date=_build_filing_date_filter(start_date, end_date),
            amendments=include_amendments,
        )
        if filings is None:
            return []

        normalized_codes = (
            {code.strip().upper() for code in transaction_codes if code and code.strip()}
            if transaction_codes
            else None
        )
        normalized_acquired_disposed = acquired_disposed.upper() if acquired_disposed else None

        trades: list[dict[str, Any]] = []
        for filing in filings:
            try:
                form4 = filing.obj()
                if form4 is None:
                    continue
                summary = form4.get_ownership_summary()
                tx_df = form4.non_derivative_table.transactions.data
                if tx_df is None or tx_df.empty:
                    continue

                if normalized_acquired_disposed:
                    tx_df = tx_df[tx_df["AcquiredDisposed"] == normalized_acquired_disposed]
                if normalized_codes:
                    tx_df = tx_df[tx_df["Code"].isin(normalized_codes)]
                if tx_df.empty:
                    continue

                for row in tx_df.itertuples(index=False):
                    shares = _normalize_number(getattr(row, "Shares", None))
                    price = _normalize_number(getattr(row, "Price", None))
                    value = (
                        _normalize_number(float(shares) * float(price))
                        if shares is not None and price is not None
                        else None
                    )
                    if value is not None and abs(float(value)) < min_value:
                        continue

                    code = str(getattr(row, "Code", "") or "")
                    acquired_disposed_code = str(getattr(row, "AcquiredDisposed", "") or "")
                    trades.append(
                        {
                            "accession_number": getattr(filing, "accession_no", None),
                            "filing_date": str(getattr(filing, "filing_date", "") or ""),
                            "tx_date": str(getattr(row, "Date", "") or ""),
                            "insider_name": getattr(summary, "insider_name", None),
                            "position": getattr(summary, "position", None),
                            "transaction_code": code,
                            "transaction_type": str(getattr(row, "TransactionType", "") or ""),
                            "code_description": _FORM4_CODE_DESCRIPTIONS.get(
                                code,
                                f"Other ({code})" if code else "Other",
                            ),
                            "acquired_disposed": acquired_disposed_code,
                            "shares": shares,
                            "price": price,
                            "proceeds": value if acquired_disposed_code == "D" else None,
                            "value": value,
                            "remaining_shares": _normalize_number(getattr(row, "Remaining", None)),
                            "security": getattr(row, "Security", None),
                            "is_direct": getattr(row, "DirectIndirect", None) == "D",
                            "ownership_nature": getattr(row, "NatureOfOwnership", None),
                            "primary_activity": getattr(summary, "primary_activity", None),
                            "classification": _classify_trade_significance(value),
                            "is_tax_withholding": code == "F",
                        }
                    )
            except Exception:
                log.warning(
                    "Could not parse Form 4 for %s / %s",
                    ticker,
                    getattr(filing, "accession_no", None),
                    exc_info=True,
                )

        trades.sort(
            key=lambda trade: (
                float(trade["proceeds"] or trade["value"] or 0.0),
                str(trade["tx_date"] or trade["filing_date"] or ""),
                str(trade["accession_number"] or ""),
            ),
            reverse=True,
        )
        return trades[:limit]
    except Exception:
        log.warning(
            "Could not retrieve insider trades for %s from %s to %s",
            ticker,
            start_date,
            end_date,
            exc_info=True,
        )
        return []
