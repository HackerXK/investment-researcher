"""Agent tools — wraps analytics functions as OpenAI Agents SDK function tools.

Each tool accepts simple JSON-serialisable arguments and returns a JSON string
so the LLM can consume the output directly.  DataFrame results are converted to
``records`` orientation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd
from agents import function_tool

from investment_researcher.analytics import (
    cashflow_pivot,
    get_all_tickers,
    get_company_profile as _get_company_profile,
    get_filings_list as _get_filings_list,
    get_filing_text as _get_filing_text,
    get_insider_trades as _get_insider_trades,
    get_institutional_holdings as _get_institutional_holdings,
    get_material_events as _get_material_events,
    get_proxy_statement_data as _get_proxy_statement_data,
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
    summarize_institutional_holdings as _summarize_institutional_holdings,
    summarize_insider_sells as _summarize_insider_sells,
    summarize_material_events as _summarize_material_events,
    summarize_proxy_statement as _summarize_proxy_statement,
    ticker_summary,
    ttm_metrics,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_FILING_CHARS = 200_000
_FILING_HEAD_CHARS = 80_000
_FILING_TRUNCATION_NOTICE = "\n\n[... filing text truncated ...]"


def _df_to_json(df: pd.DataFrame) -> str:
    """Serialise a DataFrame to a compact JSON string (records orientation)."""
    if df.empty:
        return "[]"
    converted = (
        df.reset_index()
        if df.index.name is not None or not isinstance(df.index, pd.RangeIndex)
        else df.copy()
    )
    if "period_end" in converted.columns:
        converted = converted.sort_values("period_end", ascending=False)
    # Convert timestamps / dates to strings for JSON serialisability
    for col in converted.columns:
        if pd.api.types.is_datetime64_any_dtype(converted[col]):
            converted[col] = converted[col].astype(str)
    return json.dumps(converted.to_dict(orient="records"), default=str)


def _dict_to_json(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)


def _normalize_optional_str_list(value: list[str] | str | None) -> list[str] | None:
    """Accept sloppy LLM list arguments like "" or "None" and normalize them."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "none":
            return None
        return [stripped]

    normalized = [str(item).strip() for item in value if str(item).strip()]
    return normalized or None


def _extract_filing_section(text: str, heading_patterns: list[str]) -> str | None:
    """Extract a filing section starting at a matched heading through the next item."""
    for pattern in heading_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        start = match.start()
        end = len(text)
        search_start = match.end()
        next_match = re.search(
            r"(?im)^#+\s*item\s+\d+[a-z]?\.?\b|^item\s+\d+[a-z]?\.?\b",
            text[search_start:],
        )
        if next_match:
            end = search_start + next_match.start()
        return text[start:end].strip()
    return None


def _truncate_text_with_notice(text: str, max_chars: int) -> str:
    """Truncate text to a hard character limit with a consistent notice."""
    if len(text) <= max_chars:
        return text

    clip_at = max(max_chars - len(_FILING_TRUNCATION_NOTICE), 1)
    return text[:clip_at].rstrip() + _FILING_TRUNCATION_NOTICE


def _truncate_filing_text(text: str, max_chars: int = _MAX_FILING_CHARS) -> str:
    """Preserve the filing front matter plus a later risk-factors section when truncating."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    if max_chars <= len(_FILING_TRUNCATION_NOTICE) + 256:
        return _truncate_text_with_notice(text, max_chars)

    head_chars = min(_FILING_HEAD_CHARS, max_chars)
    head = text[:head_chars].rstrip()
    parts = [head]
    remaining = max_chars - len(head) - len(_FILING_TRUNCATION_NOTICE)
    if remaining <= 256:
        return _truncate_text_with_notice(text, max_chars)

    risk_section = _extract_filing_section(
        text,
        [
            r"(?im)^#+\s*item\s+1a\.?\s+risk factors\b",
            r"(?im)^item\s+1a\.?\s+risk factors\b",
        ],
    )
    if risk_section and risk_section not in head and remaining > 256:
        marker = "\n\n[... skipped to Item 1A. Risk Factors ...]\n"
        excerpt_budget = max(0, remaining - len(marker))
        if excerpt_budget:
            parts.append(marker + risk_section[:excerpt_budget].rstrip())

    return "".join(parts).rstrip() + _FILING_TRUNCATION_NOTICE


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

    Returns one row per period_end. Each requested metric appears as its own
    column containing the YoY growth percentage for that period.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names to compute growth for (e.g. ["revenue", "net_income"]).
        period_type: "annual" or "quarterly".
    """
    df = growth_rates(ticker, metrics, period_type)
    return _df_to_json(df)


@function_tool
def get_cashflow_pivot(ticker: str, period_type: str = "annual") -> str:
    """Get cash flow statement in pivot format.

    Returns one row per period with a period_end field plus statement metrics
    such as operating_cash_flow, capex, dividends_paid, and free_cash_flow.
    Rows are serialized most recent period first.

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
    """Get quarterly financial data for specified metrics in wide format.

    Returns one row per requested metric_type. Each row includes a TTM field
    plus columns like "Quarter Ended 12/31/2025" for the most recent quarters.
    It does not invent or derive other metrics you did not request.

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
    start_date: str | None = None,
    end_date: str | None = None,
    include_amendments: bool = True,
) -> str:
    """List SEC filings for a company. Returns accession_number, form_type,
    filing_date, and description for each filing.

    Common form types: 10-K (annual report), 10-Q (quarterly report),
    8-K (current event), DEF 14A (proxy statement), 4 (insider trade).

    Args:
        ticker: Stock ticker symbol.
        form_type: Optional filter by form type (e.g. "10-K", "10-Q", "8-K").
        limit: Maximum number of filings to return.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        include_amendments: Whether to include amended forms like 4/A.
    """
    results = _get_filings_list(
        ticker,
        form_type,
        limit,
        start_date,
        end_date,
        include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def read_filing(
    ticker: str,
    accession_number: str,
    truncate: bool = True,
    max_chars: int = _MAX_FILING_CHARS,
) -> str:
    """Read the full text of an SEC filing as markdown.
    Use list_filings first to find the accession_number.

    Extremely long filings may still be truncated to stay within practical
    context limits. Set truncate=false to return the full filing text.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings (e.g. "0000320193-24-000123").
        truncate: Whether to keep the practical truncation guard.
        max_chars: Maximum number of characters to return when truncate=true.
    """
    text = _get_filing_text(ticker, accession_number)
    if not text:
        return "Filing not found or could not be retrieved."
    if not truncate:
        return text
    return _truncate_filing_text(text, max_chars=max_chars)


@function_tool
def get_insider_trades(
    ticker: str,
    start_date: str,
    end_date: str,
    transaction_codes: list[str] | None = None,
    acquired_disposed: str | None = "D",
    min_value: float = 0.0,
    limit: int = 200,
    include_amendments: bool = False,
) -> str:
    """Return structured Form 4 insider transactions for a date range.

    This is the preferred tool for insider-trading questions because it returns
    structured rows with accession number, insider, transaction date, code,
    shares, price, proceeds/value, and a Normal/Notable/Very notable bucket.

    Examples:
    - Use transaction_codes=["S", "F"] to capture discretionary sales plus tax withholding.
    - Use transaction_codes=["S"] to isolate discretionary open-market sales.
    - Use acquired_disposed="A" for acquisitions instead of dispositions.

    Args:
        ticker: Stock ticker symbol.
        start_date: Earliest filing date, inclusive (YYYY-MM-DD).
        end_date: Latest filing date, inclusive (YYYY-MM-DD).
        transaction_codes: Optional Form 4 transaction codes to include (e.g. ["S", "F"]).
        acquired_disposed: Optional acquisition/disposition filter: "A", "D", or None.
        min_value: Minimum absolute transaction value/proceeds in dollars.
        limit: Maximum number of transaction rows to return.
        include_amendments: Whether to include amended forms like 4/A.
    """
    results = _get_insider_trades(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        transaction_codes=transaction_codes,
        acquired_disposed=acquired_disposed,
        min_value=min_value,
        limit=limit,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def summarize_insider_sells(
    ticker: str,
    start_date: str,
    end_date: str,
    transaction_codes: list[str] | None = None,
    min_value: float = 0.0,
    group_by: str = "insider_name",
    limit: int = 25,
    include_amendments: bool = False,
) -> str:
    """Return grouped Form 4 sell summaries for a date range.

    This complements get_insider_trades by aggregating rows into grouped insider
    sell summaries such as total proceeds per insider or per transaction code.

    Args:
        ticker: Stock ticker symbol.
        start_date: Earliest filing date, inclusive (YYYY-MM-DD).
        end_date: Latest filing date, inclusive (YYYY-MM-DD).
        transaction_codes: Optional Form 4 transaction codes to include. Defaults to ["S", "F"].
        min_value: Minimum absolute transaction value/proceeds in dollars.
        group_by: One of "insider_name", "insider_name_and_code", or "transaction_code".
        limit: Maximum number of grouped summary rows to return.
        include_amendments: Whether to include amended forms like 4/A.
    """
    results = _summarize_insider_sells(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        transaction_codes=transaction_codes,
        min_value=min_value,
        group_by=group_by,
        limit=limit,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def get_material_events(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    item_codes: list[str] | str | None = None,
    limit: int = 50,
    include_amendments: bool = False,
    summary_chars: int = 2_000,
) -> str:
    """Return structured 8-K event rows for a company.

    Use this instead of reading raw 8-K text when the user asks about specific
    SEC item codes or recent material events.

    Args:
        ticker: Stock ticker symbol.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        item_codes: Optional list of item codes such as ["1.01", "2.02", "5.02"].
        limit: Maximum number of event rows to return.
        include_amendments: Whether to include amended forms like 8-K/A.
        summary_chars: Maximum characters to include in the per-item text excerpt.
    """
    results = _get_material_events(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        item_codes=_normalize_optional_str_list(item_codes),
        limit=limit,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return json.dumps(results, default=str)


@function_tool
def summarize_material_events(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    item_codes: list[str] | str | None = None,
    group_by: str = "item_code",
    limit: int = 25,
    include_amendments: bool = False,
    summary_chars: int = 2_000,
) -> str:
    """Return grouped summaries of a company's 8-K filings.

    Args:
        ticker: Stock ticker symbol.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        item_codes: Optional list of item codes to include.
        group_by: One of "item_code" or "content_type".
        limit: Maximum number of grouped summaries to return.
        include_amendments: Whether to include amended forms like 8-K/A.
        summary_chars: Maximum characters to include in sampled event excerpts.
    """
    results = _summarize_material_events(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        item_codes=_normalize_optional_str_list(item_codes),
        group_by=group_by,
        limit=limit,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return json.dumps(results, default=str)


@function_tool
def get_proxy_statement_data(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
    include_amendments: bool = False,
) -> str:
    """Return structured DEF 14A snapshots for one or more filings.

    Includes CEO compensation, pay-vs-performance metrics, and a compact
    executive-compensation history when XBRL data is available.

    Args:
        ticker: Stock ticker symbol.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        limit: Maximum number of proxy filings to return.
        include_amendments: Whether to include amended proxy forms.
    """
    results = _get_proxy_statement_data(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def summarize_proxy_statement(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
    include_amendments: bool = False,
) -> str:
    """Return a higher-level summary of recent proxy statement filings.

    Args:
        ticker: Stock ticker symbol.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        limit: Maximum number of proxy filings to incorporate.
        include_amendments: Whether to include amended proxy forms.
    """
    results = _summarize_proxy_statement(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def get_institutional_holdings(
    manager: str,
    report_period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_value: float = 0.0,
    limit: int = 100,
    include_amendments: bool = False,
) -> str:
    """Return structured holdings from a manager's latest or selected 13F filing.

    The manager argument may be a filer ticker, company name, or manager name,
    such as "BRK" or "Berkshire Hathaway".

    Args:
        manager: Institutional manager identifier or name.
        report_period: Optional 13F report period to target (YYYY-MM-DD).
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        min_value: Minimum holding value in dollars.
        limit: Maximum number of holdings rows to return.
        include_amendments: Whether to include amended 13F forms.
    """
    results = _get_institutional_holdings(
        manager=manager,
        report_period=report_period,
        start_date=start_date,
        end_date=end_date,
        min_value=min_value,
        limit=limit,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


@function_tool
def summarize_institutional_holdings(
    manager: str,
    report_period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    top_n: int = 10,
    min_value: float = 0.0,
    include_amendments: bool = False,
) -> str:
    """Return a concentration-oriented 13F summary for an institutional manager.

    Args:
        manager: Institutional manager identifier or name.
        report_period: Optional 13F report period to target (YYYY-MM-DD).
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        top_n: Number of top holdings to include in the summary.
        min_value: Minimum holding value in dollars for included positions.
        include_amendments: Whether to include amended 13F forms.
    """
    results = _summarize_institutional_holdings(
        manager=manager,
        report_period=report_period,
        start_date=start_date,
        end_date=end_date,
        top_n=top_n,
        min_value=min_value,
        include_amendments=include_amendments,
    )
    return json.dumps(results, default=str)


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
    get_insider_trades,
    summarize_insider_sells,
    get_material_events,
    summarize_material_events,
    get_proxy_statement_data,
    summarize_proxy_statement,
    get_institutional_holdings,
    summarize_institutional_holdings,
]
