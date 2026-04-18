"""Agent tools — wraps analytics functions as OpenAI Agents SDK function tools.

Each tool accepts simple JSON-serialisable arguments and returns a JSON string
so the LLM can consume the output directly.  DataFrame results are converted to
``records`` orientation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
from agents import function_tool

from investment_researcher.analytics import (
    cashflow_pivot,
    get_all_tickers,
    get_company_profile as _get_company_profile,
    get_filings_list as _get_filings_list,
    get_filing_text as _get_filing_text,
    get_ratios_by_category,
    get_ratios_latest as _get_ratios_latest,
    get_ratios_ttm as _get_ratios_ttm,
    get_ratios_wide as _get_ratios_wide,
    growth_rates,
    latest_metric_for_all,
    metric_timeseries,
    pivot_metrics,
    quarterly_detail,
    ratio_timeseries,
    search_companies as _search_companies,
    ticker_summary,
    ttm_metrics,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_FILING_CHARS = 50_000  # cap filing text so it doesn't flood context


def _df_to_json(df: pd.DataFrame) -> str:
    """Serialise a DataFrame to a compact JSON string (records orientation)."""
    if df.empty:
        return "[]"
    # Convert timestamps / dates to strings for JSON serialisability
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
    return json.dumps(df.to_dict(orient="records"), default=str)


def _dict_to_json(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)


# ---------------------------------------------------------------------------
# Company discovery tools
# ---------------------------------------------------------------------------


@function_tool
def search_companies(query: str, limit: int = 20) -> str:
    """Search for companies by ticker prefix (case-insensitive).

    Args:
        query: Ticker prefix to search for, e.g. "AAP" matches AAPL.
        limit: Maximum number of results to return.
    """
    results = _search_companies(query, limit)
    return json.dumps(results, default=str)


@function_tool
def get_company_profile(ticker: str) -> str:
    """Get a company's profile including name, CIK, industry, SIC code,
    and latest financial metrics.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL".
    """
    profile = _get_company_profile(ticker)
    return _dict_to_json(profile)


# ---------------------------------------------------------------------------
# Financial metrics tools
# ---------------------------------------------------------------------------


@function_tool
def get_ticker_summary(ticker: str, period_type: str = "annual") -> str:
    """Get the latest value for every financial metric available for a company.
    Returns metric_type, period_end, and value for each metric.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL".
        period_type: "annual" or "quarterly".
    """
    df = ticker_summary(ticker, period_type)
    return _df_to_json(df)


@function_tool
def get_metrics_timeseries(
    ticker: str, metrics: list[str], period_type: str = "annual"
) -> str:
    """Get a long-form time series of specific financial metrics.
    Returns ticker, metric_type, period, period_end, value for each row.

    Common metrics: revenue, net_income, total_assets, total_liabilities,
    operating_cash_flow, free_cash_flow, eps_diluted, gross_profit,
    operating_income, ebitda, total_equity, current_assets,
    current_liabilities, cash_and_equivalents, total_debt, capex,
    dividends_paid, common_shares_outstanding, interest_expense.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names to retrieve.
        period_type: "annual" or "quarterly".
    """
    df = metric_timeseries(ticker, metrics, period_type)
    return _df_to_json(df)


@function_tool
def get_metrics_pivot(
    ticker: str, metrics: list[str], period_type: str = "annual"
) -> str:
    """Get financial metrics in wide/pivot format — one column per period.
    Good for comparing values across years side-by-side.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names.
        period_type: "annual" or "quarterly".
    """
    df = pivot_metrics(ticker, metrics, period_type)
    return _df_to_json(df)


@function_tool
def get_growth_rates(
    ticker: str, metrics: list[str], period_type: str = "annual"
) -> str:
    """Get year-over-year growth rates for specific metrics.
    Returns metric_type, period_end, value, and growth_pct.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names to compute growth for (e.g. ["revenue", "net_income"]).
        period_type: "annual" or "quarterly".
    """
    df = growth_rates(ticker, metrics, period_type)
    return _df_to_json(df)


@function_tool
def get_cashflow_pivot(ticker: str, period_type: str = "annual") -> str:
    """Get cash flow statement in pivot format — one column per period.
    Includes operating_cash_flow, investing_cash_flow, financing_cash_flow,
    capex, dividends_paid, free_cash_flow.

    Args:
        ticker: Stock ticker symbol.
        period_type: "annual" or "quarterly".
    """
    df = cashflow_pivot(ticker, period_type)
    return _df_to_json(df)


# ---------------------------------------------------------------------------
# TTM & quarterly tools
# ---------------------------------------------------------------------------


@function_tool
def get_ttm_metrics(ticker: str, metrics: list[str]) -> str:
    """Get trailing-twelve-month (TTM) values for specified metrics.
    TTM sums the last 4 quarters of data. Returns a dict of metric → value.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names (e.g. ["revenue", "net_income", "free_cash_flow"]).
    """
    result = ttm_metrics(ticker, metrics)
    return _dict_to_json(result)


@function_tool
def get_quarterly_detail(
    ticker: str, metrics: list[str], n_quarters: int = 8
) -> str:
    """Get quarterly financial data for specified metrics.
    Returns up to n_quarters of quarterly data with metric_type, period, period_end, value.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names.
        n_quarters: Number of recent quarters to return (default 8).
    """
    df = quarterly_detail(ticker, metrics, n_quarters)
    return _df_to_json(df)


# ---------------------------------------------------------------------------
# Ratio tools
# ---------------------------------------------------------------------------


@function_tool
def get_latest_ratios(ticker: str, period_type: str = "annual") -> str:
    """Get the latest computed value for every financial ratio.
    Returns a dict of ratio_name → value. Ratios include profitability margins,
    returns, liquidity, leverage, efficiency, cash flow, and per-share metrics.

    Args:
        ticker: Stock ticker symbol.
        period_type: "annual" or "quarterly".
    """
    result = _get_ratios_latest(ticker, period_type)
    return _dict_to_json(result)


@function_tool
def get_ttm_ratios(ticker: str) -> str:
    """Get trailing-twelve-month (TTM) financial ratios.
    Uses the last 4 quarters to compute profitability, leverage, efficiency,
    cash flow, and per-share ratios.

    Args:
        ticker: Stock ticker symbol.
    """
    result = _get_ratios_ttm(ticker)
    return _dict_to_json(result)


@function_tool
def get_ratios_wide(ticker: str, period_type: str = "annual") -> str:
    """Get all financial ratios in wide format — one row per ratio, one column per period.
    Good for seeing how ratios have trended over multiple years.

    Args:
        ticker: Stock ticker symbol.
        period_type: "annual" or "quarterly".
    """
    df = _get_ratios_wide(ticker, period_type)
    return _df_to_json(df)


@function_tool
def get_ratio_timeseries(
    ticker: str,
    ratio_names: list[str] | None = None,
    period_type: str = "annual",
) -> str:
    """Get a time series for specific ratios. If ratio_names is omitted,
    returns all available ratios.

    Example ratio names: gross_profit_margin, net_profit_margin, return_on_equity,
    current_ratio, financial_leverage_ratio, operating_cash_flow_ratio,
    free_cash_flow_per_share, book_value_per_share.

    Args:
        ticker: Stock ticker symbol.
        ratio_names: Optional list of specific ratio names. None = all ratios.
        period_type: "annual" or "quarterly".
    """
    df = ratio_timeseries(ticker, ratio_names, period_type)
    return _df_to_json(df)


@function_tool
def list_available_ratios() -> str:
    """List all available financial ratios grouped by category.
    Categories: Profitability Margins, Returns, Liquidity, Leverage,
    Efficiency, Cash Flow, Per Share, Other.
    """
    categories = get_ratios_by_category()
    # Convert RatioDef objects to plain dicts
    result = {}
    for cat, defs in categories.items():
        result[cat] = [
            {"name": d.name, "display_format": d.display_format}
            for d in defs
        ]
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Cross-company comparison tool
# ---------------------------------------------------------------------------


@function_tool
def compare_metric_across_companies(
    metric_type: str, period_type: str = "annual", limit: int = 20
) -> str:
    """Compare the latest value of a single metric across all companies.
    Useful for screening and ranking companies by a specific metric.

    Args:
        metric_type: The metric to compare (e.g. "revenue", "net_income", "free_cash_flow").
        period_type: "annual" or "quarterly".
        limit: Maximum number of companies to return.
    """
    df = latest_metric_for_all(metric_type, period_type, limit)
    return _df_to_json(df)


# ---------------------------------------------------------------------------
# SEC filing tools
# ---------------------------------------------------------------------------


@function_tool
def list_filings(
    ticker: str,
    form_type: str | None = None,
    limit: int = 25,
) -> str:
    """List SEC filings for a company. Returns accession_number, form_type,
    filing_date, and description for each filing.

    Common form types: 10-K (annual report), 10-Q (quarterly report),
    8-K (current event), DEF 14A (proxy statement), 4 (insider trade).

    Args:
        ticker: Stock ticker symbol.
        form_type: Optional filter by form type (e.g. "10-K", "10-Q", "8-K").
        limit: Maximum number of filings to return.
    """
    results = _get_filings_list(ticker, form_type, limit)
    return json.dumps(results, default=str)


@function_tool
def read_filing(ticker: str, accession_number: str) -> str:
    """Read the full text of an SEC filing as markdown.
    Use list_filings first to find the accession_number.

    The filing text may be truncated to fit within context limits.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings (e.g. "0000320193-24-000123").
    """
    text = _get_filing_text(ticker, accession_number)
    if not text:
        return "Filing not found or could not be retrieved."
    if len(text) > _MAX_FILING_CHARS:
        text = text[:_MAX_FILING_CHARS] + "\n\n[... filing text truncated ...]"
    return text


@function_tool
def list_available_tickers() -> str:
    """List all company tickers available in the financial database."""
    tickers = get_all_tickers()
    return json.dumps(tickers)


# ---------------------------------------------------------------------------
# Registry — all tools in a single list for the agent
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    # Company discovery
    search_companies,
    get_company_profile,
    list_available_tickers,
    # Financial metrics
    get_ticker_summary,
    get_metrics_timeseries,
    get_metrics_pivot,
    get_growth_rates,
    get_cashflow_pivot,
    # TTM & quarterly
    get_ttm_metrics,
    get_quarterly_detail,
    # Ratios
    get_latest_ratios,
    get_ttm_ratios,
    get_ratios_wide,
    get_ratio_timeseries,
    list_available_ratios,
    # Cross-company
    compare_metric_across_companies,
    # SEC filings
    list_filings,
    read_filing,
]
