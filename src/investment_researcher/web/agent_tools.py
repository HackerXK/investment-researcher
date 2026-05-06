"""Agent tools — wraps analytics functions as OpenAI Agents SDK function tools.

Each tool accepts simple JSON-serialisable arguments and returns a JSON string
so the LLM can consume the output directly.  DataFrame results are converted to
``records`` orientation.
"""

from __future__ import annotations

import difflib
from datetime import date, datetime, timezone
import json
import logging
import re
from typing import Any

import pandas as pd
from agents import function_tool

from investment_researcher.analytics import (
    cashflow_pivot,
    compare_filing_sections as _compare_filing_sections,
    get_all_tickers,
    get_beneficial_ownership as _get_beneficial_ownership,
    get_company_profile as _get_company_profile,
    get_filing_section as _get_filing_section,
    get_filing_sections as _get_filing_sections,
    search_filing_text as _search_filing_text,
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
    summarize_beneficial_ownership as _summarize_beneficial_ownership,
    summarize_institutional_holdings as _summarize_institutional_holdings,
    summarize_insider_sells as _summarize_insider_sells,
    summarize_material_events as _summarize_material_events,
    summarize_proxy_statement as _summarize_proxy_statement,
    ticker_summary,
    ttm_metrics,
)
from investment_researcher.analytics.sec_filings import extract_filing_item_section
from investment_researcher.web.execution_profiles import get_execution_profile

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXECUTION_PROFILE = get_execution_profile()
_MAX_FILING_CHARS = _EXECUTION_PROFILE.max_filing_chars
_FILING_HEAD_CHARS = _EXECUTION_PROFILE.filing_head_chars
_DEFAULT_TRUNCATE_FILINGS = _EXECUTION_PROFILE.default_truncate_filings
_FILING_TRUNCATION_NOTICE = "\n\n[... filing text truncated ...]"


def _df_to_json(df: pd.DataFrame) -> str:
    """Serialise a DataFrame to a compact JSON string (records orientation)."""
    return json.dumps(_df_records(df), default=str)


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records orientation."""
    if df.empty:
        return []
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
    return converted.to_dict(orient="records")


def _dict_to_json(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)


def _normalize_jsonable(data: Any) -> Any:
    """Normalize common analytics objects into JSON-safe Python values."""
    if isinstance(data, pd.DataFrame):
        return _df_records(data)
    return data


def _coerce_iso_day(value: Any) -> str | None:
    """Normalize datetime-like values to ISO dates for metadata."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _metadata_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _derive_tool_metadata(data: Any) -> dict[str, Any]:
    """Extract provenance and freshness metadata from structured tool data."""
    normalized = _normalize_jsonable(data)
    rows = _metadata_rows(normalized)
    metadata: dict[str, Any] = {}
    if isinstance(normalized, list):
        metadata["row_count"] = len(normalized)
    elif isinstance(normalized, dict):
        metadata["field_count"] = len(normalized)

    if not rows:
        return metadata

    period_ends = [
        period_end for row in rows if (period_end := _coerce_iso_day(row.get("period_end")))
    ]
    filing_dates = [
        filing_date for row in rows if (filing_date := _coerce_iso_day(row.get("filing_date")))
    ]
    accessions = sorted(
        {
            str(row.get("accession") or row.get("accession_number") or "").strip()
            for row in rows
            if str(row.get("accession") or row.get("accession_number") or "").strip()
        },
        reverse=True,
    )
    sources = sorted(
        {
            str(row.get("source") or "").strip()
            for row in rows
            if str(row.get("source") or "").strip()
        }
    )
    null_value_count = sum(1 for row in rows for value in row.values() if value is None)

    if period_ends:
        metadata["latest_period_end"] = max(period_ends)
    if filing_dates:
        metadata["latest_filing_date"] = max(filing_dates)
    if accessions:
        metadata["accession_numbers"] = accessions[:10]
    if sources:
        metadata["sources"] = sources[:5]
    if null_value_count:
        metadata["null_value_count"] = null_value_count

    freshest_reference = metadata.get("latest_filing_date") or metadata.get("latest_period_end")
    if freshest_reference:
        metadata["staleness_days"] = (
            datetime.now(timezone.utc).date() - date.fromisoformat(freshest_reference)
        ).days

    return metadata


def _tool_response_json(
    data: Any,
    *,
    tool_name: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Wrap tool outputs with structured provenance and validation metadata."""
    normalized_data = _normalize_jsonable(data)
    payload = {
        "data": normalized_data,
        "metadata": {
            "tool_name": tool_name,
            "execution_mode": _EXECUTION_PROFILE.name,
            **_derive_tool_metadata(normalized_data),
            **(metadata or {}),
        },
        "validation": {
            "ok": True,
            "issues": [],
        },
    }
    return json.dumps(payload, default=str)


def _normalize_ticker_value(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "").upper())
    normalized = re.sub(r"[./]+", "-", normalized)
    return normalized.strip("-")


def _find_company_ticker_candidates(query: str, *, limit: int = 5) -> list[str]:
    """Use the SEC company search results to suggest canonical tickers."""
    if not query or not query.strip():
        return []

    try:
        from edgar import find_company
    except Exception:
        return []

    try:
        results = find_company(query, top_n=limit)
    except Exception:
        log.debug("edgartools company search unavailable for %s", query, exc_info=True)
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    for company in getattr(results, "results", []):
        get_ticker = getattr(company, "get_ticker", None)
        ticker = get_ticker() if callable(get_ticker) else None
        if ticker and ticker not in seen:
            seen.add(ticker)
            candidates.append(ticker)
    return candidates


def _resolve_ticker_request(ticker: str) -> tuple[str | None, dict[str, Any], list[dict[str, Any]]]:
    """Resolve tickers against the local data universe and return search metadata."""
    requested_ticker = str(ticker or "").strip()
    normalized_ticker = _normalize_ticker_value(requested_ticker)
    available_tickers = get_all_tickers()
    available_set = set(available_tickers)

    resolved_ticker: str | None = None
    is_exact = False
    candidates: tuple[str, ...] = ()

    if normalized_ticker:
        if normalized_ticker in available_set:
            resolved_ticker = normalized_ticker
            is_exact = True
            candidates = (normalized_ticker,)
        else:
            prefix_matches = tuple(
                candidate for candidate in available_tickers if candidate.startswith(normalized_ticker)
            )
            if len(prefix_matches) == 1:
                resolved_ticker = prefix_matches[0]
                candidates = prefix_matches
            else:
                company_matches = tuple(_find_company_ticker_candidates(requested_ticker))
                if len(company_matches) == 1 and company_matches[0] in available_set:
                    resolved_ticker = company_matches[0]
                    candidates = company_matches
                else:
                    resolved_ticker = normalized_ticker
                    candidates = prefix_matches[:5] or company_matches[:5] or tuple(
                        difflib.get_close_matches(normalized_ticker, available_tickers, n=5, cutoff=0.6)
                    )
    elif requested_ticker:
        resolved_ticker = requested_ticker.upper()

    metadata = {
        "requested_ticker": requested_ticker,
        "resolved_ticker": resolved_ticker,
        "ticker_candidates": list(candidates),
        "ticker_match_exact": is_exact,
    }
    return resolved_ticker, metadata, []


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


def _extract_filing_section(text: str, section_name: str) -> str | None:
    """Extract one item-based filing section using the shared parser."""
    section = extract_filing_item_section(text, section_name)
    if not section:
        return None
    content = section.get("content")
    return str(content).strip() if content else None


def _truncate_text_with_notice(text: str, max_chars: int) -> str:
    """Truncate text to a hard character limit with a consistent notice."""
    if len(text) <= max_chars:
        return text

    clip_at = max(max_chars - len(_FILING_TRUNCATION_NOTICE), 1)
    return text[:clip_at].rstrip() + _FILING_TRUNCATION_NOTICE


def _truncate_filing_text(text: str, max_chars: int = _MAX_FILING_CHARS) -> str:
    """Preserve the filing front matter plus critical later sections when truncating."""
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

    preserved_sections = [
        ("1A", "[... skipped to Item 1A. Risk Factors ...]"),
        ("7", "[... skipped to Item 7. Management's Discussion and Analysis ...]"),
    ]
    appended = False
    for section_name, marker_label in preserved_sections:
        section_text = _extract_filing_section(text, section_name)
        if not section_text or section_text in head or remaining <= 256:
            continue
        marker = f"\n\n{marker_label}\n"
        excerpt_budget = max(0, remaining - len(marker))
        if not excerpt_budget:
            continue
        parts.append(marker + section_text[:excerpt_budget].rstrip())
        appended = True
        break

    if not appended:
        return _truncate_text_with_notice(text, max_chars)

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
    return _tool_response_json(
        results,
        tool_name="search_companies",
        metadata={"query": query, "limit": limit},
    )


@function_tool
def get_company_profile(ticker: str) -> str:
    """Get a company's profile including name, CIK, industry, SIC code,
    and latest financial metrics.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL".
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    profile = _get_company_profile(resolved_ticker or ticker)
    return _tool_response_json(profile, tool_name="get_company_profile", metadata=metadata)


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = ticker_summary(resolved_ticker or ticker, period_type)
    return _tool_response_json(df, tool_name="get_ticker_summary", metadata={**metadata, "period_type": period_type})


@function_tool
def get_metrics_timeseries(
    ticker: str, metrics: list[str], period_type: str = "annual"
) -> str:
    """Get a long-form time series of specific financial metrics.
    Returns ticker, metric_type, period, period_end, value for each row.

    Common metrics: revenue, net_income, total_assets, total_liabilities,
    operating_cash_flow, free_cash_flow, eps_diluted, gross_profit,
    operating_income, ebitda, total_equity, current_assets,
    current_liabilities, cash_and_equivalents, capex,
    dividends_paid, common_shares_outstanding, interest_expense.

    Args:
        ticker: Stock ticker symbol.
        metrics: List of metric names to retrieve.
        period_type: "annual" or "quarterly".
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = metric_timeseries(resolved_ticker or ticker, metrics, period_type)
    return _tool_response_json(df, tool_name="get_metrics_timeseries", metadata={**metadata, "metrics": metrics, "period_type": period_type})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = pivot_metrics(resolved_ticker or ticker, metrics, period_type)
    return _tool_response_json(df, tool_name="get_metrics_pivot", metadata={**metadata, "metrics": metrics, "period_type": period_type})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = growth_rates(resolved_ticker or ticker, metrics, period_type)
    return _tool_response_json(df, tool_name="get_growth_rates", metadata={**metadata, "metrics": metrics, "period_type": period_type})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = cashflow_pivot(resolved_ticker or ticker, period_type)
    return _tool_response_json(df, tool_name="get_cashflow_pivot", metadata={**metadata, "period_type": period_type})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = ttm_metrics(resolved_ticker or ticker, metrics)
    return _tool_response_json(
        result,
        tool_name="get_ttm_metrics",
        metadata={**metadata, "metrics": metrics, "derived_metrics": [metric for metric in metrics if metric in {"ebitda", "free_cash_flow", "gross_profit", "operating_income", "short_term_debt", "total_receivables"}]},
    )


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = quarterly_detail(resolved_ticker or ticker, metrics, n_quarters)
    return _tool_response_json(df, tool_name="get_quarterly_detail", metadata={**metadata, "metrics": metrics, "n_quarters": n_quarters, "period_type": "quarterly"})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = _get_ratios_latest(resolved_ticker or ticker, period_type)
    return _tool_response_json(result, tool_name="get_latest_ratios", metadata={**metadata, "period_type": period_type, "ratio_source": "derived_on_demand"})


@function_tool
def get_ttm_ratios(ticker: str) -> str:
    """Get trailing-twelve-month (TTM) financial ratios.
    Uses the last 4 quarters to compute profitability, leverage, efficiency,
    cash flow, and per-share ratios.

    Args:
        ticker: Stock ticker symbol.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = _get_ratios_ttm(resolved_ticker or ticker)
    return _tool_response_json(result, tool_name="get_ttm_ratios", metadata={**metadata, "period_type": "ttm", "ratio_source": "derived_on_demand"})


@function_tool
def get_ratios_wide(ticker: str, period_type: str = "annual") -> str:
    """Get all financial ratios in wide format — one row per ratio, one column per period.
    Good for seeing how ratios have trended over multiple years.

    Args:
        ticker: Stock ticker symbol.
        period_type: "annual" or "quarterly".
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = _get_ratios_wide(resolved_ticker or ticker, period_type)
    return _tool_response_json(df, tool_name="get_ratios_wide", metadata={**metadata, "period_type": period_type, "ratio_source": "derived_on_demand"})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    df = ratio_timeseries(resolved_ticker or ticker, ratio_names, period_type)
    return _tool_response_json(df, tool_name="get_ratio_timeseries", metadata={**metadata, "ratio_names": ratio_names, "period_type": period_type, "ratio_source": "derived_on_demand"})


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
    return _tool_response_json(result, tool_name="list_available_ratios")


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
    return _tool_response_json(df, tool_name="compare_metric_across_companies", metadata={"metric_type": metric_type, "period_type": period_type, "limit": limit})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _get_filings_list(
        resolved_ticker or ticker,
        form_type,
        limit,
        start_date,
        end_date,
        include_amendments,
    )
    return _tool_response_json(results, tool_name="list_filings", metadata={**metadata, "form_type": form_type, "limit": limit, "start_date": start_date, "end_date": end_date, "include_amendments": include_amendments})


@function_tool
def read_filing(
    ticker: str,
    accession_number: str,
    truncate: bool | None = None,
    max_chars: int | None = None,
) -> str:
    """Read the full text of an SEC filing as structured JSON.
    Use list_filings first to find the accession_number.

    Extremely long filings may still be truncated to stay within practical
    context limits. Set truncate=false to return the full filing text.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings (e.g. "0000320193-24-000123").
        truncate: Whether to keep the practical truncation guard. When omitted,
            research mode defaults to full-text.
        max_chars: Maximum number of characters to return when truncate=true.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    text = _get_filing_text(resolved_ticker or ticker, accession_number)
    if not text:
        return _tool_response_json(
            {},
            tool_name="read_filing",
            metadata={
                **metadata,
                "accession_number": accession_number,
                "truncate": truncate,
                "max_chars": max_chars,
            },
        )
    if truncate is None:
        truncate = _DEFAULT_TRUNCATE_FILINGS
    content = text
    if truncate:
        content = _truncate_filing_text(text, max_chars=max_chars or _MAX_FILING_CHARS)
    return _tool_response_json(
        {
            "accession_number": accession_number,
            "content": content,
            "truncated": content != text,
        },
        tool_name="read_filing",
        metadata={
            **metadata,
            "accession_number": accession_number,
            "truncate": truncate,
            "max_chars": max_chars,
            "content_chars": len(content),
        },
    )


@function_tool
def list_filing_sections(ticker: str, accession_number: str) -> str:
    """List the item-based sections available in a filing.

    Use this before read_filing_section for targeted 10-K, 10-Q, and 8-K
    narrative analysis. Returns item code, heading, preview, and length.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _get_filing_sections(resolved_ticker or ticker, accession_number)
    return _tool_response_json(results, tool_name="list_filing_sections", metadata={**metadata, "accession_number": accession_number})


@function_tool
def read_filing_section(
    ticker: str,
    accession_number: str,
    section_name: str,
    truncate: bool | None = None,
    max_chars: int | None = None,
) -> str:
    """Read one item-based section from an SEC filing as structured JSON.

    Prefer this over read_filing when the question targets a specific section,
    such as Item 1A Risk Factors or Item 7 Management's Discussion.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings.
        section_name: Item code or section title, e.g. "1A", "risk factors", "7".
        truncate: Whether to keep the practical truncation guard. When omitted,
            research mode defaults to full-text.
        max_chars: Maximum characters to return when truncate=true.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = _get_filing_section(resolved_ticker or ticker, accession_number, section_name)
    if not result:
        return _tool_response_json({}, tool_name="read_filing_section", metadata={**metadata, "accession_number": accession_number, "section_name": section_name})

    content = str(result.get("content") or "")
    if truncate is None:
        truncate = _DEFAULT_TRUNCATE_FILINGS
    if not truncate:
        result["truncated"] = False
        return _tool_response_json(result, tool_name="read_filing_section", metadata={**metadata, "accession_number": accession_number, "section_name": section_name})

    truncated_content = _truncate_text_with_notice(content, max_chars or _MAX_FILING_CHARS)
    result["content"] = truncated_content
    result["truncated"] = truncated_content != content
    return _tool_response_json(result, tool_name="read_filing_section", metadata={**metadata, "accession_number": accession_number, "section_name": section_name})


@function_tool
def search_filing_text(
    ticker: str,
    accession_number: str,
    query: str,
    section_name: str | None = None,
    max_matches: int = 5,
    context_chars: int = 280,
) -> str:
    """Search filing text and return compact evidence excerpts as JSON.

    Prefer this when the question targets a specific phrase or theme inside a
    filing, but not an entire item section.

    Args:
        ticker: Stock ticker symbol.
        accession_number: SEC accession number from list_filings.
        query: Case-insensitive phrase to search for.
        section_name: Optional item code or section title to constrain the search.
        max_matches: Maximum number of excerpt matches to return.
        context_chars: Approximate characters of context to include around each match.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _search_filing_text(
        ticker=resolved_ticker or ticker,
        accession_number=accession_number,
        query=query,
        section_name=section_name,
        max_matches=max_matches,
        context_chars=context_chars,
    )
    return _tool_response_json(results, tool_name="search_filing_text", metadata={**metadata, "accession_number": accession_number, "query": query, "section_name": section_name, "max_matches": max_matches, "context_chars": context_chars})


@function_tool
def compare_filing_sections(
    ticker: str,
    current_accession_number: str,
    section_name: str,
    previous_accession_number: str | None = None,
    max_changes: int = 5,
    excerpt_chars: int = 280,
) -> str:
    """Compare the same section across two SEC filings as structured JSON.

    Prefer this when the question asks how a risk factor, MD&A section, or
    other item changed between filings. If previous_accession_number is omitted,
    the latest earlier filing with the same base form type is selected automatically.

    Args:
        ticker: Stock ticker symbol.
        current_accession_number: The newer filing accession number.
        section_name: Item code or section title, e.g. "1A", "risk factors", "7".
        previous_accession_number: Optional older filing accession number.
        max_changes: Maximum changed excerpts to return from each filing.
        excerpt_chars: Maximum characters per changed excerpt.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = _compare_filing_sections(
        ticker=resolved_ticker or ticker,
        current_accession_number=current_accession_number,
        previous_accession_number=previous_accession_number,
        section_name=section_name,
        max_changes=max_changes,
        excerpt_chars=excerpt_chars,
    )
    if not result:
        return _tool_response_json({}, tool_name="compare_filing_sections", metadata={**metadata, "current_accession_number": current_accession_number, "previous_accession_number": previous_accession_number, "section_name": section_name, "max_changes": max_changes, "excerpt_chars": excerpt_chars})
    return _tool_response_json(result, tool_name="compare_filing_sections", metadata={**metadata, "current_accession_number": current_accession_number, "previous_accession_number": previous_accession_number, "section_name": section_name, "max_changes": max_changes, "excerpt_chars": excerpt_chars})


@function_tool
def get_beneficial_ownership(
    ticker: str,
    form_type: str | None = None,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    include_amendments: bool = True,
    summary_chars: int = 2_000,
) -> str:
    """Return structured Schedule 13D and 13G filings for a company.

    This is the preferred tool for beneficial-ownership questions because it
    returns ownership percentages, share counts, reporting persons, and the
    most relevant narrative fields directly from structured XML when available.

    Args:
        ticker: Stock ticker symbol for the issuer.
        form_type: Optional filter such as "SC 13D" or "SC 13G".
        limit: Maximum number of filings to return.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        include_amendments: Whether to include amended forms like SC 13D/A.
        summary_chars: Maximum characters for narrative excerpts such as purpose of transaction.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _get_beneficial_ownership(
        ticker=resolved_ticker or ticker,
        form_type=form_type,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return _tool_response_json(results, tool_name="get_beneficial_ownership", metadata={**metadata, "form_type": form_type, "limit": limit, "start_date": start_date, "end_date": end_date, "include_amendments": include_amendments})


@function_tool
def summarize_beneficial_ownership(
    ticker: str,
    form_type: str | None = None,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
    include_amendments: bool = True,
    summary_chars: int = 2_000,
) -> str:
    """Return a compact summary of Schedule 13D and 13G filings.

    Args:
        ticker: Stock ticker symbol for the issuer.
        form_type: Optional filter such as "SC 13D" or "SC 13G".
        limit: Maximum number of filings to consider.
        start_date: Optional earliest filing date (YYYY-MM-DD).
        end_date: Optional latest filing date (YYYY-MM-DD).
        include_amendments: Whether to include amended forms like SC 13D/A.
        summary_chars: Maximum characters for narrative excerpts.
    """
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    result = _summarize_beneficial_ownership(
        ticker=resolved_ticker or ticker,
        form_type=form_type,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return _tool_response_json(result, tool_name="summarize_beneficial_ownership", metadata={**metadata, "form_type": form_type, "limit": limit, "start_date": start_date, "end_date": end_date, "include_amendments": include_amendments})


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

    This is best for insider selling or buying questions because it returns
    structured rows with accession number, insider, transaction date, code,
    shares, price, proceeds/value, and a Normal/Notable/Very notable bucket.

    Examples:
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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _get_insider_trades(
        ticker=resolved_ticker or ticker,
        start_date=start_date,
        end_date=end_date,
        transaction_codes=transaction_codes,
        acquired_disposed=acquired_disposed,
        min_value=min_value,
        limit=limit,
        include_amendments=include_amendments,
    )
    return _tool_response_json(results, tool_name="get_insider_trades", metadata={**metadata, "start_date": start_date, "end_date": end_date, "transaction_codes": transaction_codes, "acquired_disposed": acquired_disposed, "min_value": min_value, "limit": limit, "include_amendments": include_amendments})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _summarize_insider_sells(
        ticker=resolved_ticker or ticker,
        start_date=start_date,
        end_date=end_date,
        transaction_codes=transaction_codes,
        min_value=min_value,
        group_by=group_by,
        limit=limit,
        include_amendments=include_amendments,
    )
    return _tool_response_json(results, tool_name="summarize_insider_sells", metadata={**metadata, "start_date": start_date, "end_date": end_date, "transaction_codes": transaction_codes, "min_value": min_value, "group_by": group_by, "limit": limit, "include_amendments": include_amendments})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    normalized_item_codes = _normalize_optional_str_list(item_codes)
    results = _get_material_events(
        ticker=resolved_ticker or ticker,
        start_date=start_date,
        end_date=end_date,
        item_codes=normalized_item_codes,
        limit=limit,
        include_amendments=include_amendments,
        summary_chars=summary_chars,
    )
    return _tool_response_json(results, tool_name="get_material_events", metadata={**metadata, "start_date": start_date, "end_date": end_date, "item_codes": normalized_item_codes, "limit": limit, "include_amendments": include_amendments})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    normalized_item_codes = _normalize_optional_str_list(item_codes)
    try:
        results = _summarize_material_events(
            ticker=resolved_ticker or ticker,
            start_date=start_date,
            end_date=end_date,
            item_codes=normalized_item_codes,
            group_by=group_by,
            limit=limit,
            include_amendments=include_amendments,
            summary_chars=summary_chars,
        )
    except ValueError:
        results = []
    return _tool_response_json(results, tool_name="summarize_material_events", metadata={**metadata, "start_date": start_date, "end_date": end_date, "item_codes": normalized_item_codes, "group_by": group_by, "limit": limit, "include_amendments": include_amendments})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _get_proxy_statement_data(
        ticker=resolved_ticker or ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        include_amendments=include_amendments,
    )
    return _tool_response_json(results, tool_name="get_proxy_statement_data", metadata={**metadata, "start_date": start_date, "end_date": end_date, "limit": limit, "include_amendments": include_amendments})


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
    resolved_ticker, metadata, _ = _resolve_ticker_request(ticker)
    results = _summarize_proxy_statement(
        ticker=resolved_ticker or ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        include_amendments=include_amendments,
    )
    return _tool_response_json(results, tool_name="summarize_proxy_statement", metadata={**metadata, "start_date": start_date, "end_date": end_date, "limit": limit, "include_amendments": include_amendments})


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
    return _tool_response_json(results, tool_name="get_institutional_holdings", metadata={"manager": manager, "report_period": report_period, "start_date": start_date, "end_date": end_date, "min_value": min_value, "limit": limit, "include_amendments": include_amendments})


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
    return _tool_response_json(results, tool_name="summarize_institutional_holdings", metadata={"manager": manager, "report_period": report_period, "start_date": start_date, "end_date": end_date, "top_n": top_n, "min_value": min_value, "include_amendments": include_amendments})


@function_tool
def list_available_tickers() -> str:
    """List all company tickers available in the financial database."""
    tickers = get_all_tickers()
    return _tool_response_json(tickers, tool_name="list_available_tickers")


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
    list_filing_sections,
    read_filing_section,
    search_filing_text,
    compare_filing_sections,
    read_filing,
    get_beneficial_ownership,
    summarize_beneficial_ownership,
    get_insider_trades,
    summarize_insider_sells,
    get_material_events,
    summarize_material_events,
    get_proxy_statement_data,
    summarize_proxy_statement,
    get_institutional_holdings,
    summarize_institutional_holdings,
]
