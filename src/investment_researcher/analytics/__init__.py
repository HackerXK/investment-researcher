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
from investment_researcher.analytics.sec_filings import (
    build_filing_date_filter as _build_filing_date_filter_impl,
    classify_trade_significance as _classify_trade_significance_impl,
    extract_form4_trades,
    extract_institutional_holdings,
    extract_material_events,
    extract_proxy_statement_record,
    normalize_number as _normalize_number_impl,
    summarize_insider_sales_rows,
    summarize_institutional_holdings_rows,
    summarize_material_event_rows,
    summarize_proxy_statement_rows,
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
    "summarize_insider_sells",
    "get_material_events",
    "summarize_material_events",
    "get_proxy_statement_data",
    "summarize_proxy_statement",
    "get_institutional_holdings",
    "summarize_institutional_holdings",
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
    return _build_filing_date_filter_impl(start_date, end_date)


def _normalize_number(value: Any) -> int | float | None:
    """Convert pandas / Python numeric-like values to JSON-safe numbers."""
    return _normalize_number_impl(value)


def _classify_trade_significance(value: Any) -> str:
    """Bucket a trade's value for quick screening."""
    return _classify_trade_significance_impl(value)


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
        trades: list[dict[str, Any]] = []
        for filing in filings:
            try:
                trades.extend(
                    extract_form4_trades(
                        filing,
                        transaction_codes=transaction_codes,
                        acquired_disposed=acquired_disposed,
                        min_value=min_value,
                    )
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


def summarize_insider_sells(
    ticker: str,
    start_date: str,
    end_date: str,
    transaction_codes: list[str] | None = None,
    min_value: float = 0.0,
    group_by: str = "insider_name",
    limit: int = 25,
    include_amendments: bool = False,
) -> list[dict[str, Any]]:
    """Return grouped summaries for Form 4 sale/disposition activity."""
    trades = get_insider_trades(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        transaction_codes=transaction_codes or ["S", "F"],
        acquired_disposed="D",
        min_value=min_value,
        limit=500,
        include_amendments=include_amendments,
    )
    return summarize_insider_sales_rows(trades, group_by=group_by, limit=limit)


def get_material_events(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    item_codes: list[str] | None = None,
    limit: int = 50,
    include_amendments: bool = False,
    summary_chars: int = 400,
) -> list[dict[str, Any]]:
    """Return structured 8-K item/event rows for a company."""
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings(
            form="8-K",
            filing_date=_build_filing_date_filter(start_date, end_date),
            amendments=include_amendments,
        )
        if filings is None:
            return []

        events: list[dict[str, Any]] = []
        for filing in filings:
            try:
                events.extend(
                    extract_material_events(
                        filing,
                        item_codes=item_codes,
                        summary_chars=summary_chars,
                    )
                )
                if len(events) >= limit:
                    break
            except Exception:
                log.warning(
                    "Could not parse 8-K for %s / %s",
                    ticker,
                    getattr(filing, "accession_no", None),
                    exc_info=True,
                )

        return events[:limit]
    except Exception:
        log.warning(
            "Could not retrieve 8-K material events for %s",
            ticker,
            exc_info=True,
        )
        return []


def summarize_material_events(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    item_codes: list[str] | None = None,
    group_by: str = "item_code",
    limit: int = 25,
    include_amendments: bool = False,
    summary_chars: int = 400,
) -> list[dict[str, Any]]:
    """Return grouped summaries of a company's 8-K material events."""
    events = get_material_events(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        item_codes=item_codes,
        limit=500,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return summarize_material_event_rows(events, group_by=group_by, limit=limit)


def get_proxy_statement_data(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
    include_amendments: bool = False,
) -> list[dict[str, Any]]:
    """Return structured DEF 14A snapshots for one or more filings."""
    try:
        from edgar import Company as EdgarCompany

        co = EdgarCompany(ticker.upper())
        filings = co.get_filings(
            form="DEF 14A",
            filing_date=_build_filing_date_filter(start_date, end_date),
            amendments=include_amendments,
        )
        if filings is None:
            return []

        records: list[dict[str, Any]] = []
        for filing in filings[:limit]:
            try:
                record = extract_proxy_statement_record(filing)
                if record:
                    records.append(record)
            except Exception:
                log.warning(
                    "Could not parse DEF 14A for %s / %s",
                    ticker,
                    getattr(filing, "accession_no", None),
                    exc_info=True,
                )
        return records
    except Exception:
        log.warning(
            "Could not retrieve proxy statement data for %s",
            ticker,
            exc_info=True,
        )
        return []


def summarize_proxy_statement(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
    include_amendments: bool = False,
) -> dict[str, Any]:
    """Return a higher-level summary across one or more proxy filings."""
    rows = get_proxy_statement_data(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        include_amendments=include_amendments,
    )
    return summarize_proxy_statement_rows(rows)


def _pick_thirteenf_filing(
    filings: Any,
    report_period: str | None = None,
    scan_limit: int = 40,
) -> Any | None:
    """Pick the best-matching 13F filing from a filings collection."""
    if filings is None:
        return None
    if report_period is None:
        if hasattr(filings, "latest"):
            try:
                return filings.latest()
            except Exception:
                pass
        try:
            return filings[0]
        except Exception:
            return None

    for filing in filings[:scan_limit]:
        try:
            thirteen_f = filing.obj()
        except Exception:
            continue
        if thirteen_f is not None and str(getattr(thirteen_f, "report_period", "") or "") == report_period:
            return filing
    return None


def get_institutional_holdings(
    manager: str,
    report_period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_value: float = 0.0,
    limit: int = 100,
    include_amendments: bool = False,
) -> list[dict[str, Any]]:
    """Return structured holdings from a manager's latest or selected 13F filing."""
    try:
        from edgar import Company as EdgarCompany

        entity = EdgarCompany(manager.strip())
        filings = entity.get_filings(
            form="13F-HR",
            filing_date=_build_filing_date_filter(start_date, end_date),
            amendments=include_amendments,
        )
        filing = _pick_thirteenf_filing(filings, report_period=report_period)
        if filing is None:
            return []
        return extract_institutional_holdings(
            filing,
            min_value=min_value,
            limit=limit,
        )
    except Exception:
        log.warning(
            "Could not retrieve institutional holdings for %s",
            manager,
            exc_info=True,
        )
        return []


def summarize_institutional_holdings(
    manager: str,
    report_period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    top_n: int = 10,
    min_value: float = 0.0,
    include_amendments: bool = False,
) -> dict[str, Any]:
    """Return a concentration-oriented summary of a manager's 13F holdings."""
    rows = get_institutional_holdings(
        manager=manager,
        report_period=report_period,
        start_date=start_date,
        end_date=end_date,
        min_value=min_value,
        limit=None,
        include_amendments=include_amendments,
    )
    return summarize_institutional_holdings_rows(rows, top_n=top_n)
