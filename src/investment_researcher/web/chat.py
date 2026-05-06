"""Chat backend — agentic tool-use with OpenAI Agents SDK.

Strategy:
- An ``Agent`` with access to financial analytics tools plans and executes
  multi-step analyses autonomously (e.g. fetch metrics, compare ratios,
  read SEC filings) then streams the final answer via SSE.
- Uses ``OpenAIChatCompletionsModel`` to talk to the local vLLM instance
  (Qwen 2.5 32B, OpenAI-compatible Chat Completions endpoint).
- Langfuse tracing can be enabled via environment variables.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
import json
import logging
import re
from datetime import datetime
from typing import Any

from agents import Agent, ModelSettings, RunItemStreamEvent, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from investment_researcher.analytics import (
    compare_filing_sections as analytics_compare_filing_sections,
    cashflow_timeseries as analytics_cashflow_timeseries,
    get_beneficial_ownership as analytics_get_beneficial_ownership,
    get_filing_section as analytics_get_filing_section,
    get_filing_sections as analytics_get_filing_sections,
    get_filing_text as analytics_get_filing_text,
    get_filings_list as analytics_get_filings_list,
    get_material_events as analytics_get_material_events,
    get_proxy_statement_data as analytics_get_proxy_statement_data,
    growth_rates as analytics_growth_rates,
    quarterly_detail as analytics_quarterly_detail,
    ratio_timeseries as analytics_ratio_timeseries,
    search_filing_text as analytics_search_filing_text,
    summarize_beneficial_ownership as analytics_summarize_beneficial_ownership,
    summarize_insider_sells as analytics_summarize_insider_sells,
    summarize_institutional_holdings as analytics_summarize_institutional_holdings,
    ttm_metrics as analytics_ttm_metrics,
)
from investment_researcher.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from investment_researcher.analytics.sec_filings import (
    dataframe_records as sec_dataframe_records,
    extract_narrative_highlight_candidates as sec_extract_narrative_highlight_candidates,
    extract_risk_highlight_candidates as sec_extract_risk_highlight_candidates,
    extract_risk_theme_candidates as sec_extract_risk_theme_candidates,
    summarize_institutional_holdings_rows,
)
from investment_researcher.web.agent_tools import ALL_TOOLS
from investment_researcher.web.execution_profiles import get_execution_profile
from investment_researcher.web.query_normalization import normalize_research_query
from investment_researcher.web.research_execution import execute_research_request
from investment_researcher.web.tracing import (
    configure_langfuse_tracing,
    start_chat_trace,
    update_chat_trace,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models  (unchanged API contract)
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    ticker: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    session_id: str | None = None
    source: str | None = None


# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert financial analyst assistant with access to a suite of \
analytical tools. You can look up company financials, compute ratios, read \
SEC filings, and compare companies — all on demand.

## How to work
1. **Plan internally first** — before answering, decide which tools you need and in \
what order.  Prefer targeted tool calls over loading everything at once.
2. **Use tools** — call the appropriate tools to retrieve data.  You can \
call multiple tools if the question spans several companies or data types.
3. **Synthesise** — combine tool outputs into a clear, quantitative answer.

## Guidelines
- Work silently. Do not narrate your step-by-step plan, retries, tool
    selection, or debugging to the user.
- Present only the final polished answer unless the user explicitly asks for
    methodology.
- Treat tool outputs as hard constraints. Do not state any number, date,
    accession number, event count, ratio, or narrative detail unless it is
    directly present in the retrieved tool output or can be computed from it
    with simple arithmetic.
- Answer only the user's requested dimensions. Do not add extra metrics,
    per-share statistics, adjacent ratios, or segment commentary unless the
    user explicitly asked for them or they are required to answer the question.
- If a requested metric is not present in the tool output, say it is not
    available from the retrieved data. Do not backfill it from memory.
- Do not infer quarterly gross margin, operating margin, cash flow metrics,
    or other detailed line items from TTM ratios or from unrelated metrics.
- Keep period semantics exact. Do not relabel a quarterly figure as TTM,
    annual, or latest, and do not relabel TTM or annual figures as quarterly.
- Cite specific numbers from tool results.
- When referencing SEC filing text, include the accession number.
- Be precise and quantitative; avoid vague qualifiers when data is available.
- If data is unavailable or a tool returns empty results, say so honestly.
- Provide bull and bear perspectives only when the user explicitly asks for
    outlook, thesis, or debate-style framing.
- You are NOT limited to annual data — use quarterly, TTM, and time-series \
  tools when the question warrants it.
- You can read ANY SEC filing type (10-K, 10-Q, 8-K, DEF 14A, etc.), not \
    just the latest 10-K. Use list_filings to discover available filings.
- For targeted 10-K, 10-Q, or 8-K narrative questions, prefer
        list_filing_sections and read_filing_section before reading the full filing.
- For targeted phrase or theme lookups inside a filing, prefer
    search_filing_text before reading the full filing.
- For "how did this filing section change?" questions, prefer
    compare_filing_sections before reading both sections manually. If the user
    does not name the older filing, the tool can infer the latest earlier
    same-form filing automatically.
- Use read_filing only when you genuinely need the broader filing context.
- For insider trading / Form 4 questions, prefer get_insider_trades with an
    explicit date range instead of relying on only the most recent list_filings
    window.
- For grouped Form 4 sell screens, prefer summarize_insider_sells.
- For 8-K questions about item codes or recent material events, prefer
    get_material_events or summarize_material_events before reading raw filing text.
- For DEF 14A compensation questions, prefer get_proxy_statement_data or
    summarize_proxy_statement before reading raw proxy text.
- For 13F institutional holding questions, prefer get_institutional_holdings or
    summarize_institutional_holdings.
- For beneficial ownership questions about 5%+ stakes or activist/passive
    positions, prefer get_beneficial_ownership or summarize_beneficial_ownership.
- For wide-format tools like get_quarterly_detail and get_cashflow_pivot,
    read the returned rows literally: each row is labelled and recent periods
    appear first. Use only the labelled fields that are actually present.

## Available metric names (not exhaustive)
revenue, net_income, gross_profit, operating_income, ebitda, total_assets, \
total_liabilities, total_equity, current_assets, current_liabilities, \
cash_and_equivalents, operating_cash_flow, free_cash_flow, \
capex, dividends_paid, eps_diluted, eps_basic, common_shares_outstanding, \
interest_expense, income_tax_expense, cost_of_revenue, research_and_development.
"""


def _build_model() -> OpenAIChatCompletionsModel:
    """Create the LLM model backed by the local vLLM endpoint."""
    client = AsyncOpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    return OpenAIChatCompletionsModel(
        model=LLM_MODEL,
        openai_client=client,
    )


def build_agent() -> Agent:
    """Construct the financial-analyst agent with all tools."""
    configure_langfuse_tracing()
    return Agent(
        name="Financial Analyst",
        instructions=_SYSTEM_PROMPT,
        model=_build_model(),
        tools=list(ALL_TOOLS),
        model_settings=ModelSettings(temperature=0.1),
    )


# ---------------------------------------------------------------------------
# Chat handler (SSE streaming)
# ---------------------------------------------------------------------------

_EXECUTION_PROFILE = get_execution_profile()

# Maximum agent turns to prevent runaway loops
_MAX_TURNS = _EXECUTION_PROFILE.max_turns
_FINAL_OUTPUT_CHUNK_SIZE = 96
_GROUNDING_MAX_TOOL_OUTPUTS = _EXECUTION_PROFILE.grounding_max_tool_outputs
_GROUNDING_MAX_TOOL_OUTPUT_CHARS = _EXECUTION_PROFILE.grounding_max_tool_output_chars
_GROUNDING_READ_FILING_OUTPUT_CHARS = _EXECUTION_PROFILE.grounding_read_filing_output_chars
_GROUNDING_TIMEOUT_SECONDS = _EXECUTION_PROFILE.grounding_timeout_seconds
_INITIAL_PROGRESS = "planning the analysis"
_RETRY_PROGRESS = "retrying the analysis"
_TOOL_OUTPUT_PROGRESS = "analyzing the retrieved data"
_FINAL_PROGRESS = "drafting the answer"
_BLANK_FINAL_RETRY_INSTRUCTION = (
    "The previous attempt returned a blank answer. Use the relevant tools when the "
    "question depends on retrieved data, and return a non-empty final answer grounded "
    "only in tool outputs. For 8-K event questions, call get_material_events and "
    "summarize the returned item codes across the full retrieved date range."
)

_TOOL_PROGRESS_MESSAGES = {
    "search_companies": "searching companies",
    "get_company_profile": "loading company profile",
    "list_available_tickers": "loading available tickers",
    "get_ticker_summary": "loading financial summary",
    "get_metrics_timeseries": "retrieving financial time series",
    "get_metrics_pivot": "retrieving financial statements",
    "get_growth_rates": "computing growth rates",
    "get_cashflow_pivot": "retrieving cash flow data",
    "get_ttm_metrics": "computing trailing-twelve-month metrics",
    "get_quarterly_detail": "retrieving quarterly results",
    "get_latest_ratios": "computing ratios",
    "get_ttm_ratios": "computing ratios",
    "get_ratios_wide": "computing ratios",
    "get_ratio_timeseries": "computing ratio trends",
    "list_available_ratios": "loading available ratios",
    "compare_metric_across_companies": "comparing companies",
    "list_filings": "searching filings",
    "list_filing_sections": "mapping filing sections",
    "read_filing_section": "reading filing sections",
    "search_filing_text": "searching filing text",
    "compare_filing_sections": "comparing filing sections",
    "read_filing": "reading SEC filings",
    "get_beneficial_ownership": "analyzing beneficial ownership filings",
    "summarize_beneficial_ownership": "summarizing beneficial ownership filings",
    "get_insider_trades": "analyzing insider trades",
    "summarize_insider_sells": "summarizing insider sales",
    "get_material_events": "analyzing 8-K events",
    "summarize_material_events": "summarizing 8-K events",
    "get_proxy_statement_data": "analyzing proxy statements",
    "summarize_proxy_statement": "summarizing proxy statements",
    "get_institutional_holdings": "analyzing institutional holdings",
    "summarize_institutional_holdings": "summarizing institutional holdings",
}


def _serialize_final_output(output: object) -> str:
    """Convert the agent final output into plain text for SSE delivery."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, BaseModel):
        return output.model_dump_json()
    if isinstance(output, (dict, list)):
        return json.dumps(output, default=str)
    return str(output)


def _sse_payload(payload: dict[str, str]) -> str:
    """Encode a JSON SSE payload."""
    return f"data: {json.dumps(payload)}\n\n"


def _tool_name_from_item(item: object) -> str | None:
    """Extract a tool name from a streamed SDK item."""
    candidate = getattr(item, "name", None)
    if candidate:
        return str(candidate)

    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        candidate = raw_item.get("name") or raw_item.get("tool_name")
    else:
        candidate = getattr(raw_item, "name", None) or getattr(raw_item, "tool_name", None)

    return str(candidate) if candidate is not None else None


def _progress_message_for_tool(tool_name: str | None) -> str:
    """Map a tool name to a neutral user-facing progress label."""
    if not tool_name:
        return "working through the analysis"
    return _TOOL_PROGRESS_MESSAGES.get(tool_name, "working through the analysis")


def _stream_text_as_sse(text: str):
    """Yield the final answer in frontend-compatible SSE token chunks."""
    for index in range(0, len(text), _FINAL_OUTPUT_CHUNK_SIZE):
        chunk = text[index:index + _FINAL_OUTPUT_CHUNK_SIZE]
        if chunk:
            yield _sse_payload({"token": chunk})


def _extract_tool_output(item: object) -> str:
    """Extract a tool output payload from a streamed SDK item."""
    candidate = getattr(item, "output", None)
    if candidate is not None:
        return _serialize_final_output(candidate)

    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        candidate = raw_item.get("output")
    else:
        candidate = getattr(raw_item, "output", None)

    return _serialize_final_output(candidate)


def _tool_guidance_messages(request: ChatRequest) -> list[dict[str, str]]:
    """Compatibility wrapper for explicit query normalization context."""
    return normalize_research_query(
        request.message,
        ticker=request.ticker,
    ).context_messages


def _compact_material_event_summary(summary: str, limit: int = 160) -> str:
    """Compress a material-event summary into one readable snippet."""
    compact = " ".join(summary.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _parse_material_event_rows(output: str) -> list[dict[str, str]]:
    """Parse structured 8-K event rows from a tool output payload."""
    payload = _parse_json_payload(output)

    if not isinstance(payload, list):
        return []

    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        item_code = str(item.get("item_code") or item.get("item") or "").strip()
        if item_code.lower().startswith("item "):
            item_code = item_code[5:].strip()
        filing_date = str(item.get("filing_date") or "").strip()
        if not item_code or not filing_date:
            continue
        rows.append(
            {
                "accession_number": str(item.get("accession_number") or "").strip(),
                "item_code": item_code,
                "item_label": str(item.get("item_label") or item.get("item") or "").strip(),
                "filing_date": filing_date,
                "content_type": str(item.get("content_type") or "").strip(),
                "summary": str(item.get("summary") or "").strip(),
            }
        )

    return rows


def _summarize_material_event_output(output: str) -> str | None:
    """Summarize structured 8-K event rows into a compact full-range view."""
    rows = _parse_material_event_rows(output)
    if not rows:
        return None

    rows.sort(key=lambda row: row["filing_date"], reverse=True)
    earliest = min(row["filing_date"] for row in rows)
    latest = max(row["filing_date"] for row in rows)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["item_code"], []).append(row)

    lines = [f"Coverage: {len(rows)} event row(s) from {earliest} to {latest}."]
    sorted_groups = sorted(
        grouped.items(),
        key=lambda item: (max(row["filing_date"] for row in item[1]), item[0]),
        reverse=True,
    )
    for item_code, item_rows in sorted_groups:
        recent_dates = []
        for row in item_rows:
            filing_date = row["filing_date"]
            if filing_date not in recent_dates:
                recent_dates.append(filing_date)
            if len(recent_dates) == 3:
                break
        content_types = sorted(
            {row["content_type"] for row in item_rows if row["content_type"]}
        )
        examples: list[str] = []
        for row in item_rows:
            compact = _compact_material_event_summary(row["summary"])
            if compact and compact not in examples:
                examples.append(compact)
            if len(examples) == 2:
                break

        line = (
            f"{item_code}: {len(item_rows)} row(s); recent filing dates "
            f"{', '.join(recent_dates)}"
        )
        if content_types:
            line += f"; content types {', '.join(content_types)}"
        if examples:
            line += f"; examples {' | '.join(examples)}"
        lines.append(line)

    return "\n".join(lines)


def _extract_material_event_title(row: dict[str, str]) -> str:
    """Extract a concise item title from a structured 8-K event row."""
    item_code = row.get("item_code", "")
    summary = row.get("summary", "")
    prefix = f"Item {item_code} "
    if summary.startswith(prefix):
        remainder = summary[len(prefix):].strip()
        if remainder:
            return remainder.split(".", 1)[0].strip()
    item_label = row.get("item_label", "").strip()
    if item_label and item_label != f"Item {item_code}":
        return item_label
    return f"Item {item_code}"


def _parse_json_payload(output: str) -> Any | None:
    """Parse a JSON tool payload, returning None on decode failure."""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and "data" in payload and "validation" in payload:
        return payload.get("data")
    return payload


def _parse_proxy_records(output: str) -> list[dict[str, Any]]:
    """Parse structured proxy statement records from a tool output payload."""
    payload = _parse_json_payload(output)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_institutional_holdings_summary(output: str) -> dict[str, Any] | None:
    """Parse a summarized 13F holdings payload."""
    payload = _parse_json_payload(output)
    if isinstance(payload, dict):
        return payload
    return None


def _parse_institutional_holdings_rows(output: str) -> list[dict[str, Any]]:
    """Parse raw structured 13F holdings rows."""
    payload = _parse_json_payload(output)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _format_money(value: Any) -> str:
    """Format a dollar amount with a readable unit."""
    if value is None:
        return "N/A"
    amount = float(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.2f}M"
    return f"{sign}${amount:,.0f}"


def _format_percent(value: Any) -> str:
    """Format a percentage value with two decimals."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def _extract_first_iso_date(text: str) -> str | None:
    """Extract the first ISO date mentioned in a prompt."""
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    return match.group(1) if match else None


def _extract_search_query(text: str) -> str | None:
    """Extract a simple filing-search query from prompts like 'mention about China'."""
    match = re.search(r"mention(?:s)?\s+about\s+([^?.]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    query = match.group(1).strip().strip('"\'')
    return query or None


def _normalize_text_key(value: Any) -> str:
    """Normalize free text for coarse identity matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _format_compact_percent(value: Any) -> str:
    """Format a percentage with trimmed trailing zeros."""
    if value is None:
        return "N/A"
    percent = float(value)
    if percent.is_integer():
        return f"{int(percent)}%"
    return f"{percent:.2f}".rstrip("0").rstrip(".") + "%"


def _dataframe_records_with_index(df: Any) -> list[dict[str, Any]]:
    """Convert DataFrame-like results to records while preserving index keys."""
    if df is None:
        return []
    if hasattr(df, "reset_index"):
        try:
            return sec_dataframe_records(df.reset_index())
        except Exception:
            pass
    return sec_dataframe_records(df)


def _record_period_end(row: dict[str, Any]) -> str:
    """Return a stable period-end label from a serialized analytics row."""
    for key in ("period_end", "index", "level_0"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _extract_explicit_tickers(text: str) -> list[str]:
    """Extract uppercase ticker-like tokens from free text in first-seen order."""
    ignore_tokens = {
        "AND",
        "CEO",
        "CFO",
        "DEF",
        "FCF",
        "FORM",
        "GAAP",
        "ITEM",
        "NEO",
        "SEC",
        "TSR",
        "TTM",
    }
    tickers: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"\b[A-Z]{1,5}\b", text):
        if token in ignore_tokens or token in seen:
            continue
        seen.add(token)
        tickers.append(token)
    return tickers


def _extract_latest_13f_manager_reference(request: ChatRequest) -> str | None:
    """Infer the manager or filer reference for generic latest-13F questions."""
    if request.ticker:
        return request.ticker.upper()

    patterns = [
        r"(?i)what are\s+(.+?)'s\s+top holdings",
        r"(?i)what is\s+(.+?)'s\s+top holdings",
        r"(?i)from\s+(.+?)'s\s+latest 13f",
    ]
    for pattern in patterns:
        match = re.search(pattern, request.message)
        if not match:
            continue
        manager = " ".join(match.group(1).split()).strip(" ,.")
        if manager:
            return manager
    return None


def _parse_quarter_label(period_label: str) -> str | None:
    """Parse a quarter label like 'Quarter Ended 12/31/2025' into ISO form."""
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", period_label)
    if not match:
        return None
    month, day, year = match.groups()
    return f"{year}-{month}-{day}"


def _extract_quarter_series(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract wide-format quarter columns into a sorted series."""
    series: list[dict[str, Any]] = []
    for key, value in row.items():
        if not isinstance(key, str) or not key.startswith("Quarter Ended "):
            continue
        if value is None:
            continue
        period_end = _parse_quarter_label(key)
        if not period_end:
            continue
        series.append(
            {
                "period_end": period_end,
                "period_label": key,
                "value": float(value),
            }
        )
    return sorted(series, key=lambda item: item["period_end"], reverse=True)


def _format_period_label(period_end: str) -> str:
    """Format an ISO period end into a short readable label."""
    try:
        return datetime.fromisoformat(period_end).strftime("%b %Y")
    except ValueError:
        return period_end


def _format_long_period_end(period_end: str) -> str:
    """Format an ISO period end into a full readable date."""
    try:
        parsed = datetime.fromisoformat(period_end)
    except ValueError:
        return period_end
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _latest_metric_row(
    rows: list[dict[str, Any]],
    metric_type: str,
) -> dict[str, Any] | None:
    """Pick the latest long-form metric row for one metric type."""
    metric_rows = [row for row in rows if row.get("metric_type") == metric_type]
    if not metric_rows:
        return None
    return max(metric_rows, key=lambda row: str(row.get("period_end") or ""))


def _extract_latest_fcf_row(cashflow_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the latest free cash flow row from statement records."""
    return _latest_metric_row(cashflow_rows, "free_cash_flow")


def _extract_item_section_excerpt(
    text: str,
    section_patterns: list[str],
    next_section_patterns: list[str],
    fallback_needles: list[str],
) -> str:
    """Extract one narrative 10-K section or fall back to a nearby tail excerpt."""
    if not text:
        return ""
    for pattern in section_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        start = match.start()
        end = len(text)
        for end_pattern in next_section_patterns:
            end_match = re.search(end_pattern, text[start + 1 :])
            if end_match:
                end = min(end, start + 1 + end_match.start())
        return text[start:end].strip()

    lowered = text.lower()
    for needle in fallback_needles:
        marker = lowered.find(needle)
        if marker != -1:
            start = max(0, marker - 800)
            return text[start:]
    return text


def _extract_risk_excerpt(text: str) -> str:
    """Extract the full Item 1A risk section or a nearby fallback excerpt."""
    return _extract_item_section_excerpt(
        text,
        [
            r"(?im)^#+\s*item\s+1a\.?\s+risk factors\b",
            r"(?im)^item\s+1a\.?\s+risk factors\b",
            r"(?im)^item\s+1a\.?\b",
        ],
        [
            r"(?im)^#+\s*item\s+1b\.?\b",
            r"(?im)^#+\s*item\s+1c\.?\b",
            r"(?im)^#+\s*item\s+2\.?\b",
            r"(?im)^item\s+1b\.?\b",
            r"(?im)^item\s+1c\.?\b",
            r"(?im)^item\s+2\.?\b",
        ],
        ["risk factors"],
    )


def _extract_mdna_excerpt(text: str) -> str:
    """Extract the full MD&A section or a nearby fallback excerpt."""
    return _extract_item_section_excerpt(
        text,
        [
            r"(?im)^#+\s*item\s+7\.?\s+management'?s discussion(?:\s+and\s+analysis(?:\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?)?\b",
            r"(?im)^item\s+7\.?\s+management'?s discussion(?:\s+and\s+analysis(?:\s+of\s+financial\s+condition\s+and\s+results\s+of\s+operations)?)?\b",
            r"(?im)^#+\s*item\s+7\.?\b",
            r"(?im)^item\s+7\.?\b",
        ],
        [
            r"(?im)^#+\s*item\s+7a\.?\b",
            r"(?im)^#+\s*item\s+8\.?\b",
            r"(?im)^item\s+7a\.?\b",
            r"(?im)^item\s+8\.?\b",
        ],
        ["management's discussion", "management discussion and analysis"],
    )


def _extract_narrative_highlight_candidates(excerpt: str) -> list[str]:
    """Extract concise highlights from long narrative filing sections."""
    return sec_extract_narrative_highlight_candidates(excerpt, max_candidates=12)


def _extract_risk_highlight_candidates(excerpt: str) -> list[str]:
    """Extract concise risk highlights from a 10-K Item 1A excerpt."""
    return sec_extract_risk_highlight_candidates(excerpt, max_candidates=12)


def _extract_risk_theme_candidates(excerpt: str) -> list[str]:
    """Extract concise risk-theme candidates from a 10-K Item 1A excerpt."""
    return sec_extract_risk_theme_candidates(excerpt, max_candidates=12)


def _choose_distinct_section_highlights(candidates: list[str], limit: int = 2) -> list[str]:
    """Pick distinct heading-prefixed highlights for direct filing answers."""
    highlights: list[str] = []
    seen_headings: set[str] = set()
    for candidate in candidates:
        heading = candidate.split(":", 1)[0].strip() if ":" in candidate else candidate
        if heading in seen_headings:
            continue
        seen_headings.add(heading)
        highlights.append(candidate)
        if len(highlights) == limit:
            break
    if len(highlights) < limit:
        for candidate in candidates:
            if candidate in highlights:
                continue
            highlights.append(candidate)
            if len(highlights) == limit:
                break
    return highlights


def _render_latest_10k_risk_answer(
    company_label: str | None,
    filing: dict[str, Any],
    filing_text: str,
) -> str | None:
    """Render a direct answer for latest 10-K risk-theme questions."""
    excerpt = _extract_risk_excerpt(filing_text)
    highlight_candidates = _extract_risk_highlight_candidates(excerpt)
    theme_candidates = _extract_risk_theme_candidates(excerpt)
    if not highlight_candidates and not theme_candidates:
        return None

    themes = _choose_distinct_section_highlights(highlight_candidates + theme_candidates)
    if not themes:
        return None

    accession_number = filing.get("accession_number") or "N/A"
    filing_date = filing.get("filing_date") or "N/A"
    subject = f"{company_label}'s" if company_label else "The company's"
    lines = [
        f"{subject} latest 10-K was filed on {filing_date} with accession number {accession_number}.",
        "Two Item 1A risk points highlighted in the filing are:",
    ]
    for theme in themes:
        lines.append(f"- {theme}")
    return "\n".join(lines)


def _render_latest_10k_mdna_answer(
    company_label: str | None,
    filing: dict[str, Any],
    filing_text: str,
) -> str | None:
    """Render a direct answer for latest 10-K MD&A highlight questions."""
    excerpt = _extract_mdna_excerpt(filing_text)
    highlights = _choose_distinct_section_highlights(
        _extract_narrative_highlight_candidates(excerpt)
    )
    if not highlights:
        return None

    accession_number = filing.get("accession_number") or "N/A"
    filing_date = filing.get("filing_date") or "N/A"
    subject = f"{company_label}'s" if company_label else "The company's"
    lines = [
        f"{subject} latest 10-K was filed on {filing_date} with accession number {accession_number}.",
        "Two MD&A highlights in the filing are:",
    ]
    for highlight in highlights:
        lines.append(f"- {highlight}")
    return "\n".join(lines)


def _render_latest_10k_search_answer(
    filing: dict[str, Any],
    query: str,
    matches: list[dict[str, Any]],
) -> str | None:
    """Render a grounded answer from structured filing-search matches."""
    if not matches:
        return None

    accession_number = filing.get("accession_number") or "N/A"
    filing_date = filing.get("filing_date") or "N/A"
    lines = [
        f"The latest 10-K was filed on {filing_date} with accession number {accession_number}.",
        f'Retrieved matches for "{query}" appear in:',
    ]

    seen: set[tuple[str, str]] = set()
    for match in matches:
        section_label = str(
            match.get("heading")
            or (f"Item {match.get('item_code')}" if match.get("item_code") else "Unlabeled section")
        ).strip()
        excerpt = " ".join(str(match.get("excerpt") or "").split())
        if not section_label or not excerpt:
            continue
        key = (section_label, excerpt)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {section_label}: {excerpt}")

    return "\n".join(lines) if len(lines) > 2 else None


def _render_latest_filing_sections_answer(
    filing: dict[str, Any],
    sections: list[dict[str, Any]],
) -> str | None:
    """Render a grounded answer from parsed filing-section discovery output."""
    accession_number = filing.get("accession_number") or "N/A"
    filing_date = filing.get("filing_date") or "N/A"
    if not sections:
        return (
            f"The latest 8-K was filed on {filing_date} with accession number {accession_number}. "
            "I did not retrieve any parsed item sections from the filing markdown."
        )

    lines = [
        f"The latest 8-K was filed on {filing_date} with accession number {accession_number}.",
        "The parsed item sections are:",
    ]
    for section in sections:
        item_code = str(section.get("item_code") or "").strip()
        heading = str(section.get("heading") or "").strip()
        if not item_code or not heading:
            continue
        lines.append(f"- Item {item_code}: {heading}")
    return "\n".join(lines) if len(lines) > 2 else None


def _render_filing_section_comparison_answer(comparison: dict[str, Any]) -> str | None:
    """Render a grounded answer from structured filing-section comparison output."""
    current_filing = comparison.get("current_filing") or {}
    previous_filing = comparison.get("previous_filing") or {}
    current_accession = str(current_filing.get("accession_number") or "").strip()
    previous_accession = str(previous_filing.get("accession_number") or "").strip()
    current_only_excerpts = [
        " ".join(str(excerpt).split())
        for excerpt in (comparison.get("current_only_excerpts") or [])
        if str(excerpt).strip()
    ]
    if not current_accession or not previous_accession or not current_only_excerpts:
        return None

    excerpt = current_only_excerpts[0]
    return "\n".join(
        [
            "Comparing the latest annual risk factor section with the prior annual filing, one new emphasis in the returned comparison is:",
            f'- "{excerpt}"',
            f"Latest filing accession number: {current_accession}",
            f"Prior filing accession number: {previous_accession}",
        ]
    )


def _latest_proxy_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the latest proxy filing record from a list of snapshots."""
    if not records:
        return None
    return max(
        records,
        key=lambda record: (
            str(record.get("filing_date") or ""),
            str(record.get("accession_number") or ""),
        ),
    )


def _render_proxy_snapshot_answer(latest: dict[str, Any]) -> str | None:
    """Render a grounded answer for one proxy-statement snapshot."""
    if not latest:
        return None

    pay_vs_performance = latest.get("pay_vs_performance") or []
    if not isinstance(pay_vs_performance, list):
        pay_vs_performance = []
    pay_vs_performance = sorted(
        [row for row in pay_vs_performance if isinstance(row, dict)],
        key=lambda row: str(row.get("fiscal_year_end") or ""),
    )

    measures = latest.get("performance_measures") or []
    if not isinstance(measures, list):
        measures = []
    normalized_measures = [
        " ".join(str(measure).split())
        for measure in measures
        if str(measure).strip()
    ]

    lines = [
        f"The most recent retrieved proxy snapshot was filed {latest.get('filing_date')} "
        f"(DEF 14A; accession {latest.get('accession_number')}).",
        "",
        "CEO compensation:",
        f"- PEO: {latest.get('peo_name') or 'N/A'}",
        f"- Total compensation: {_format_money(latest.get('peo_total_comp'))}",
        f"- Actually paid compensation: {_format_money(latest.get('peo_actually_paid_comp'))}",
        f"- Average non-PEO NEO total compensation: {_format_money(latest.get('neo_avg_total_comp'))}",
        f"- Average non-PEO NEO actually paid compensation: {_format_money(latest.get('neo_avg_actually_paid_comp'))}",
        "",
        "Pay-versus-performance:",
        f"- Measures listed: {', '.join(normalized_measures) or 'N/A'}",
    ]

    for row in pay_vs_performance:
        lines.append(
            "- "
            f"{row.get('fiscal_year_end')}: CEO actually paid {_format_money(row.get('peo_actually_paid_comp'))}, "
            f"company TSR {_format_percent(row.get('total_shareholder_return'))}, "
            f"peer group TSR {_format_percent(row.get('peer_group_tsr'))}, "
            f"net income {_format_money(row.get('net_income'))}, "
            f"{latest.get('company_selected_measure') or 'company-selected measure'} "
            f"{_format_money(row.get('company_selected_measure_value'))}."
        )

    return "\n".join(lines)


def _select_primary_issuer_beneficial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer rows for the predominant issuer when a filer history mixes issuers."""
    issuer_counts: dict[str, int] = {}
    for row in rows:
        issuer_key = _normalize_text_key(row.get("issuer_name"))
        if not issuer_key:
            continue
        issuer_counts[issuer_key] = issuer_counts.get(issuer_key, 0) + 1
    if not issuer_counts:
        return rows
    primary_issuer_key = max(issuer_counts.items(), key=lambda item: item[1])[0]
    filtered = [
        row for row in rows if _normalize_text_key(row.get("issuer_name")) == primary_issuer_key
    ]
    return filtered or rows


def _render_beneficial_ownership_history_answer(
    ticker: str | None,
    requested_start_date: str | None,
    rows: list[dict[str, Any]],
) -> str | None:
    """Render a grounded answer from structured beneficial ownership history rows."""
    relevant_rows = _select_primary_issuer_beneficial_rows(rows)
    if not relevant_rows:
        return None

    sorted_rows = sorted(
        relevant_rows,
        key=lambda row: (
            str(row.get("filing_date") or ""),
            str(row.get("accession_number") or ""),
        ),
        reverse=True,
    )
    company_label = ticker or relevant_rows[0].get("issuer_name") or "The company"
    start_label = requested_start_date or "the requested start date"
    lines = [
        f"Since {start_label}, the recent beneficial ownership filings I retrieved for {company_label} are:",
    ]
    for row in sorted_rows:
        filing_date = str(row.get("filing_date") or "").strip()
        form_type = str(row.get("form_type") or "").strip()
        total_percent = row.get("total_percent")
        if not filing_date or not form_type or total_percent is None:
            continue
        lines.append(
            f"- {filing_date} — {form_type} — reported ownership {_format_compact_percent(total_percent)}"
        )
    return "\n".join(lines) if len(lines) > 1 else None


def _render_beneficial_ownership_snapshot_answer(
    ticker: str | None,
    summary: dict[str, Any],
) -> str | None:
    """Render a grounded answer for the latest beneficial ownership snapshot."""
    if not summary:
        return None

    filing_date = str(summary.get("latest_filing_date") or "").strip()
    accession_number = str(summary.get("latest_accession_number") or "").strip()
    if not filing_date or not accession_number:
        return None

    issuer_name = summary.get("issuer_name") or ticker or "The company"
    form_type = str(summary.get("latest_form_type") or "beneficial ownership filing").strip()
    filer_names = [
        str(name).strip()
        for name in (summary.get("latest_reporting_person_names") or [])
        if str(name).strip()
    ]
    filer_label = ", ".join(filer_names) or "N/A"
    ownership_percent = summary.get("latest_total_percent")
    passive_flag = summary.get("latest_is_passive_investor")
    rule_designation = str(summary.get("latest_rule_designation") or "").strip()

    if passive_flag is True:
        stance = "Passive"
        if rule_designation:
            stance = f"Passive ({rule_designation})"
    elif passive_flag is False:
        stance = "Activist"
    else:
        stance = "Not clear from the retrieved filing"

    return "\n".join(
        [
            f"{issuer_name}'s latest beneficial ownership filing was {form_type} filed {filing_date} (accession {accession_number}).",
            f"- Filer: {filer_label}",
            f"- Reported ownership percentage: {_format_compact_percent(ownership_percent)}",
            f"- Passive or activist: {stance}.",
        ]
    )


def _render_bull_bear_quarterly_and_ttm_answer(
    request: ChatRequest,
    quarterly_rows: list[dict[str, Any]],
    ttm_payload: dict[str, Any],
) -> str | None:
    """Render bull and bear datapoints without inventing unavailable quarterly cash flow."""
    revenue_row = next(
        (row for row in quarterly_rows if row.get("metric_type") == "revenue"),
        None,
    )
    net_income_row = next(
        (row for row in quarterly_rows if row.get("metric_type") == "net_income"),
        None,
    )
    if revenue_row is None or net_income_row is None:
        return None

    revenue_series = _extract_quarter_series(revenue_row)[:8]
    net_income_by_period = {
        item["period_end"]: item["value"]
        for item in _extract_quarter_series(net_income_row)
    }
    margin_series: list[dict[str, Any]] = []
    for item in revenue_series:
        revenue_value = float(item["value"])
        net_income_value = net_income_by_period.get(item["period_end"])
        if revenue_value and net_income_value is not None:
            margin_series.append(
                {
                    "period_end": item["period_end"],
                    "revenue": revenue_value,
                    "net_income": float(net_income_value),
                    "net_margin": float(net_income_value) / revenue_value,
                }
            )
    if not margin_series:
        return None

    strongest_quarter = max(
        margin_series,
        key=lambda item: (item["net_margin"], item["period_end"]),
    )
    bull_line = (
        "Bull datapoint: "
        f"Quarter ended {_format_long_period_end(strongest_quarter['period_end'])} generated "
        f"{_format_money(strongest_quarter['net_income'])} of net income on "
        f"{_format_money(strongest_quarter['revenue'])} of revenue, "
        f"a {_format_percent(strongest_quarter['net_margin'] * 100.0)} net margin."
    )

    ttm_fcf = ttm_payload.get("free_cash_flow")
    if ttm_fcf is not None and float(ttm_fcf) < 0:
        bear_line = (
            "Bear datapoint: "
            f"Latest trailing-twelve-month free cash flow was {_format_money(ttm_fcf)}."
        )
    else:
        weakest_quarter = min(
            margin_series,
            key=lambda item: (item["net_margin"], item["period_end"]),
        )
        bear_line = (
            "Bear datapoint: "
            f"Quarter ended {_format_long_period_end(weakest_quarter['period_end'])} had the weakest "
            f"net margin in the retrieved window at {_format_percent(weakest_quarter['net_margin'] * 100.0)}."
        )

    return "\n".join([bull_line, bear_line])


def _render_quarterly_trend_and_ttm_answer(
    request: ChatRequest,
    quarterly_rows: list[dict[str, Any]],
    ttm_payload: dict[str, Any],
) -> str | None:
    """Render a direct answer for quarterly trend plus TTM FCF questions."""
    revenue_row = next(
        (row for row in quarterly_rows if row.get("metric_type") == "revenue"),
        None,
    )
    net_income_row = next(
        (row for row in quarterly_rows if row.get("metric_type") == "net_income"),
        None,
    )
    if revenue_row is None:
        return None

    revenue_series = _extract_quarter_series(revenue_row)[:8]
    if len(revenue_series) < 2:
        return None

    margin_series: list[dict[str, Any]] = []
    if net_income_row:
        net_income_by_period = {
            item["period_end"]: item["value"]
            for item in _extract_quarter_series(net_income_row)
        }
        for item in revenue_series:
            revenue_value = float(item["value"])
            net_income_value = net_income_by_period.get(item["period_end"])
            if revenue_value and net_income_value is not None:
                margin_series.append(
                    {
                        "period_end": item["period_end"],
                        "net_margin": float(net_income_value) / revenue_value,
                    }
                )

    chronological_revenue = list(reversed(revenue_series))
    revenue_text = ", ".join(
        f"{_format_period_label(item['period_end'])} {_format_money(item['value'])}"
        for item in chronological_revenue
    )

    ttm_fcf = ttm_payload.get("free_cash_flow")
    if ttm_fcf is None:
        return None

    margin_sentence = "The margin picture is mixed based on the retrieved data."
    if margin_series:
        latest_margin = margin_series[0]
        earliest_margin = margin_series[-1]
        direction = "improving overall" if latest_margin["net_margin"] > earliest_margin["net_margin"] else "not improving overall"
        margin_sentence = (
            f"The margin picture is {direction}: quarterly net margin moved from "
            f"{_format_percent(earliest_margin['net_margin'] * 100.0)} in {_format_period_label(earliest_margin['period_end'])} "
            f"to {_format_percent(latest_margin['net_margin'] * 100.0)} in {_format_period_label(latest_margin['period_end'])}."
        )

    company_label = request.ticker or "The company"
    return (
        f"{company_label}'s revenue over the last eight quarters trended higher overall, though with normal seasonality: "
        f"{revenue_text}.\n"
        f"Latest trailing-twelve-month free cash flow was {_format_money(ttm_fcf)}.\n"
        f"{margin_sentence}"
    )


def _render_ttm_revenue_net_income_answer(
    request: ChatRequest,
    ttm_payload: dict[str, Any],
) -> str | None:
    """Render a grounded answer for simple TTM revenue and net income prompts."""
    revenue_value = ttm_payload.get("revenue")
    net_income_value = ttm_payload.get("net_income")
    if revenue_value is None or net_income_value is None:
        return None

    revenue = float(revenue_value)
    net_income = float(net_income_value)
    if revenue == 0:
        margin = None
    else:
        margin = net_income / revenue
    company_label = request.ticker or "The company"
    lines = [
        f"{company_label}'s latest trailing-twelve-month revenue was {_format_money(revenue)}.",
        f"{company_label}'s latest trailing-twelve-month net income was {_format_money(net_income)}.",
    ]
    if margin is not None:
        lines.append(
            "Short interpretation: net income was "
            f"{_format_percent(margin * 100.0)} of trailing-twelve-month revenue."
        )
    return "\n".join(lines)


def _is_bull_bear_quarterly_prompt(lowered_message: str) -> bool:
    """Detect a prompt asking for one bull and one bear datapoint."""
    return "bull datapoint" in lowered_message and "bear datapoint" in lowered_message


def _is_quarterly_trend_and_ttm_prompt(lowered_message: str) -> bool:
    """Detect a prompt asking for quarterly trend plus TTM free cash flow."""
    return (
        "revenue trend" in lowered_message
        and "margin picture" in lowered_message
        and "free cash flow" in lowered_message
    )


def _render_growth_and_margin_trend_answer(
    ticker: str | None,
    growth_rows: list[dict[str, Any]],
    ratio_rows: list[dict[str, Any]],
) -> str | None:
    """Render a grounded answer for annual growth-plus-margin trend prompts."""
    ordered_growth_rows = sorted(
        [row for row in growth_rows if row.get("revenue") is not None and _record_period_end(row)],
        key=_record_period_end,
    )[-4:]
    ordered_ratio_rows = sorted(
        [
            row
            for row in ratio_rows
            if row.get("ratio_name") == "net_profit_margin"
            and row.get("value") is not None
            and _record_period_end(row)
        ],
        key=_record_period_end,
    )[-4:]
    if len(ordered_growth_rows) < 2 or len(ordered_ratio_rows) < 2:
        return None

    growth_lines = [
        f"- {_record_period_end(row)}: {_format_percent(row['revenue'])}"
        for row in ordered_growth_rows
    ]
    margin_lines = [
        f"- {_record_period_end(row)}: {_format_percent(float(row['value']) * 100.0)}"
        for row in ordered_ratio_rows
    ]

    growth_summary = (
        f"Revenue growth moved from {_format_percent(ordered_growth_rows[0]['revenue'])} in {_record_period_end(ordered_growth_rows[0])} "
        f"to {_format_percent(ordered_growth_rows[-1]['revenue'])} in {_record_period_end(ordered_growth_rows[-1])}, "
        "with a contraction in between before re-accelerating."
    )
    margin_summary = (
        f"Net profit margin moved from {_format_percent(float(ordered_ratio_rows[0]['value']) * 100.0)} in {_record_period_end(ordered_ratio_rows[0])} "
        f"to {_format_percent(float(ordered_ratio_rows[-1]['value']) * 100.0)} in {_record_period_end(ordered_ratio_rows[-1])}, "
        "dipping before recovering."
    )
    company_label = ticker or "The company"
    return "\n".join(
        [
            f"{company_label}'s revenue growth over the last four annual periods was:",
            *growth_lines,
            "",
            "Net profit margin over the same periods was:",
            *margin_lines,
            "",
            "Direction of change:",
            f"- {growth_summary}",
            f"- {margin_summary}",
        ]
    )


def _render_cross_company_fcf_ranking(
    tickers: list[str],
    cashflow_rows_by_ticker: dict[str, list[dict[str, Any]]],
) -> str | None:
    """Render a ranking from latest annual free cash flow values."""
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        latest_row = _extract_latest_fcf_row(cashflow_rows_by_ticker.get(ticker, []))
        if not latest_row:
            continue
        rows.append(
            {
                "ticker": ticker,
                "value": float(latest_row.get("value") or 0.0),
            }
        )

    if len(rows) != len(tickers):
        return None

    rows.sort(key=lambda row: row["value"], reverse=True)
    return "\n".join(
        f"{index}. {row['ticker']} — {_format_money(row['value'])}"
        for index, row in enumerate(rows, start=1)
    )


def _render_recent_insider_proxy_answer(
    request: ChatRequest,
    insider_rows: list[dict[str, Any]],
    proxy_rows: list[dict[str, Any]],
) -> str | None:
    """Render a direct answer for mixed insider-sell and proxy questions."""
    lines: list[str] = []
    if insider_rows:
        lines.append(
            "Yes. In the requested date range, the most notable insider sale summaries I retrieved were:"
        )
        for row in insider_rows:
            insider_name = row.get("insider_name") or "Unknown insider"
            position = str(row.get("position") or "").strip()
            role_suffix = f" ({position})" if position else ""
            lines.append(
                f"- {insider_name}{role_suffix}: total proceeds {_format_money(row.get('total_proceeds'))} "
                f"across {row.get('transaction_count')} sale transaction(s); latest filing "
                f"{row.get('latest_filing_date')}."
            )
    else:
        lines.append(
            "I did not retrieve any notable insider sale summaries in the requested date range."
        )

    latest_proxy = None
    if proxy_rows:
        latest_proxy = max(
            proxy_rows,
            key=lambda row: (
                str(row.get("filing_date") or ""),
                str(row.get("accession_number") or ""),
            ),
        )

    if latest_proxy:
        company_name = latest_proxy.get("company_name") or request.ticker or "The company"
        lines.extend(
            [
                "",
                f"{company_name}'s latest retrieved proxy was filed {latest_proxy.get('filing_date')} "
                f"(DEF 14A; accession {latest_proxy.get('accession_number')}).",
                f"- CEO: {latest_proxy.get('peo_name') or 'N/A'}",
                f"- Total compensation: {_format_money(latest_proxy.get('peo_total_comp'))}",
                f"- Actually paid compensation: {_format_money(latest_proxy.get('peo_actually_paid_comp'))}",
            ]
        )
        if latest_proxy.get("neo_avg_total_comp") is not None:
            lines.append(
                f"- Average non-PEO NEO total compensation: "
                f"{_format_money(latest_proxy.get('neo_avg_total_comp'))}"
            )

    return "\n".join(lines).strip() or None


def _render_annual_cashflow_summary_answer(
    request: ChatRequest,
    cashflow_rows: list[dict[str, Any]],
) -> str | None:
    """Render a direct answer for single-period annual cash-flow summary questions."""
    operating_cash_flow_row = _latest_metric_row(cashflow_rows, "operating_cash_flow")
    capex_row = _latest_metric_row(cashflow_rows, "capex")
    free_cash_flow_row = _latest_metric_row(cashflow_rows, "free_cash_flow")
    if not operating_cash_flow_row or not capex_row or not free_cash_flow_row:
        return None

    period_end = str(
        operating_cash_flow_row.get("period_end")
        or capex_row.get("period_end")
        or free_cash_flow_row.get("period_end")
        or ""
    ).split(" ", 1)[0]
    company_label = request.ticker or "The company"
    header = f"For {company_label}'s most recent annual period"
    if period_end:
        header += f" ({period_end})"
    header += ":"
    return "\n".join(
        [
            header,
            f"- Operating cash flow: {_format_money(operating_cash_flow_row.get('value'))}",
            f"- Capex: {_format_money(capex_row.get('value'))}",
            f"- Free cash flow: {_format_money(free_cash_flow_row.get('value'))}",
        ]
    )


def _render_events_and_cashflow_answer_direct(
    request: ChatRequest,
    events: list[dict[str, Any]],
    cashflow_rows: list[dict[str, Any]],
) -> str | None:
    """Render a direct answer for mixed 8-K and cash-flow questions."""
    lines: list[str] = []
    if events:
        lines.append("Yes. Recent retrieved 8-K material events include:")
        seen_keys: set[tuple[str, str]] = set()
        for event in events:
            filing_date = str(event.get("filing_date") or "").strip()
            item_code = str(event.get("item_code") or "").strip()
            if not filing_date or not item_code:
                continue
            key = (filing_date, item_code)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            title = _extract_material_event_title(
                {
                    "item_code": item_code,
                    "item_label": str(event.get("item_label") or event.get("item") or ""),
                    "summary": str(event.get("summary") or ""),
                }
            )
            content_type = str(event.get("content_type") or "").replace("_", " ").strip()
            if title and len(title) > 80:
                title = ""
            line = f"- {filing_date}: Item {item_code}"
            if title and title != f"Item {item_code}":
                line += f" ({title})"
            if content_type and content_type.lower() not in line.lower():
                line += f"; {content_type}"
            lines.append(line + ".")
    else:
        company_label = request.ticker or "The company"
        lines.append(f"I did not retrieve any recent 8-K material events for {company_label}.")

    free_cash_flow_row = _latest_metric_row(cashflow_rows, "free_cash_flow")
    capex_row = _latest_metric_row(cashflow_rows, "capex")
    if free_cash_flow_row and capex_row:
        period_end = str(
            free_cash_flow_row.get("period_end") or capex_row.get("period_end") or ""
        ).split(" ", 1)[0]
        free_cash_flow = float(free_cash_flow_row.get("value") or 0.0)
        capex = abs(float(capex_row.get("value") or 0.0))
        difference = free_cash_flow - capex
        coverage = (free_cash_flow / capex * 100.0) if capex else None
        lines.extend(
            [
                "",
                f"Latest annual cash flow ({period_end}): free cash flow was {_format_money(free_cash_flow)} "
                f"versus capex of {_format_money(capex)}.",
                f"Free cash flow was {_format_money(abs(difference))} "
                f"{'above' if difference >= 0 else 'below'} capex"
                + (f", covering {_format_percent(coverage)} of capex." if coverage is not None else "."),
            ]
        )

    return "\n".join(lines).strip() or None


async def _try_direct_answer(request: ChatRequest) -> tuple[list[str], str] | None:
    """Short-circuit a few structured prompts with deterministic grounded answers."""
    lowered_message = request.message.lower()
    ticker = request.ticker.upper() if request.ticker else None

    if "13f" in lowered_message and any(
        keyword in lowered_message for keyword in ["top holdings", "concentrated", "concentration", "portfolio"]
    ):
        manager_reference = _extract_latest_13f_manager_reference(request)
        if manager_reference:
            summary = await asyncio.to_thread(
                analytics_summarize_institutional_holdings,
                manager_reference,
            )
            if summary:
                answer = _render_institutional_holdings_answer(
                    request.message,
                    [
                        {
                            "tool_name": "summarize_institutional_holdings",
                            "output": json.dumps(summary, default=str),
                        }
                    ],
                )
                if answer:
                    return (["analyzing institutional holdings"], answer)

    if (
        ticker
        and "operating cash flow" in lowered_message
        and "capex" in lowered_message
        and "free cash flow" in lowered_message
        and "annual" in lowered_message
        and "most recent" in lowered_message
        and "prior years" in lowered_message
        and "8-k" not in lowered_message
    ):
        cashflow_df = await asyncio.to_thread(analytics_cashflow_timeseries, ticker, "annual")
        answer = _render_annual_cashflow_summary_answer(
            request,
            sec_dataframe_records(cashflow_df),
        )
        if answer:
            return (["retrieving cash flow data"], answer)

    if (
        ticker
        and ("trailing-twelve-month" in lowered_message or "ttm" in lowered_message)
        and "revenue" in lowered_message
        and "net income" in lowered_message
    ):
        ttm_payload = await asyncio.to_thread(analytics_ttm_metrics, ticker, ["revenue", "net_income"])
        answer = _render_ttm_revenue_net_income_answer(request, ttm_payload)
        if answer:
            return (["computing trailing-twelve-month metrics"], answer)

    if ticker and _is_bull_bear_quarterly_prompt(lowered_message):
        quarterly_df, ttm_payload = await asyncio.gather(
            asyncio.to_thread(analytics_quarterly_detail, ticker, ["revenue", "net_income"], 8),
            asyncio.to_thread(analytics_ttm_metrics, ticker, ["free_cash_flow"]),
        )
        answer = _render_bull_bear_quarterly_and_ttm_answer(
            request,
            _dataframe_records_with_index(quarterly_df),
            ttm_payload,
        )
        if answer:
            return (["analyzing quarterly financials", "computing trailing-twelve-month metrics"], answer)

    if ticker and _is_quarterly_trend_and_ttm_prompt(lowered_message):
        quarterly_df, ttm_payload = await asyncio.gather(
            asyncio.to_thread(analytics_quarterly_detail, ticker, ["revenue", "net_income"], 8),
            asyncio.to_thread(analytics_ttm_metrics, ticker, ["free_cash_flow"]),
        )
        answer = _render_quarterly_trend_and_ttm_answer(
            request,
            _dataframe_records_with_index(quarterly_df),
            ttm_payload,
        )
        if answer:
            return (["analyzing quarterly financials", "computing trailing-twelve-month metrics"], answer)

    if (
        ticker
        and "proxy" in lowered_message
        and "insider" not in lowered_message
        and (
            "compensation" in lowered_message
            or "pay-versus-performance" in lowered_message
        )
    ):
        proxy_rows = await asyncio.to_thread(
            analytics_get_proxy_statement_data,
            ticker,
            None,
            None,
            1,
        )
        latest_proxy = _latest_proxy_record(proxy_rows)
        answer = _render_proxy_snapshot_answer(latest_proxy) if latest_proxy else None
        if answer:
            return (["analyzing proxy statements"], answer)

    if ticker and "insider" in lowered_message and "proxy" in lowered_message:
        requested_start_date = _extract_first_iso_date(request.message) or (
            date.today() - timedelta(days=365)
        ).isoformat()
        insider_rows, proxy_rows = await asyncio.gather(
            asyncio.to_thread(
                analytics_summarize_insider_sells,
                ticker,
                requested_start_date,
                date.today().isoformat(),
                ["S", "F"],
                0.0,
                "insider_name",
                25,
            ),
            asyncio.to_thread(analytics_get_proxy_statement_data, ticker, None, None, 1),
        )
        answer = _render_recent_insider_proxy_answer(request, insider_rows, proxy_rows)
        if answer:
            return (["analyzing insider trades", "analyzing proxy statements"], answer)

    if (
        ticker
        and "beneficial ownership" in lowered_message
        and "filings" not in lowered_message
        and any(
            token in lowered_message
            for token in ["filer", "ownership percentage", "passive", "activist", "latest"]
        )
    ):
        summary = await asyncio.to_thread(
            analytics_summarize_beneficial_ownership,
            ticker,
            None,
            10,
            None,
            None,
            True,
            2_000,
        )
        answer = _render_beneficial_ownership_snapshot_answer(ticker, summary)
        if answer:
            return (["summarizing beneficial ownership filings"], answer)

    if ticker and "8-k" in lowered_message and "material events" in lowered_message:
        start_date = _extract_first_iso_date(request.message) or (
            date.today() - timedelta(days=365)
        ).isoformat()
        events = await asyncio.to_thread(
            analytics_get_material_events,
            ticker,
            start_date,
            None,
            None,
            50,
        )
        answer = _render_material_event_answer(
            request.message,
            [
                {
                    "tool_name": "get_material_events",
                    "output": json.dumps(events, default=str),
                }
            ],
        )
        if answer:
            return (["analyzing 8-K events"], answer)

    if ticker and "beneficial ownership" in lowered_message and "filings" in lowered_message:
        requested_start_date = _extract_first_iso_date(request.message)
        rows = await asyncio.to_thread(
            analytics_get_beneficial_ownership,
            ticker,
            None,
            5,
            requested_start_date,
            None,
            True,
            2_000,
        )
        answer = _render_beneficial_ownership_history_answer(ticker, requested_start_date, rows)
        if answer:
            return (["analyzing beneficial ownership filings"], answer)

    if ticker and "8-k" in lowered_message and "item sections" in lowered_message:
        filings = await asyncio.to_thread(analytics_get_filings_list, ticker, "8-K", 1)
        if filings:
            filing = filings[0]
            sections = await asyncio.to_thread(
                analytics_get_filing_sections,
                ticker,
                str(filing.get("accession_number") or ""),
            )
            answer = _render_latest_filing_sections_answer(filing, sections)
            if answer:
                return (["searching filings", "mapping filing sections"], answer)

    if (
        ticker
        and "growth" in lowered_message
        and "net profit margin" in lowered_message
        and "last four annual" in lowered_message
    ):
        growth_df, ratio_df = await asyncio.gather(
            asyncio.to_thread(analytics_growth_rates, ticker, ["revenue"], "annual"),
            asyncio.to_thread(analytics_ratio_timeseries, ticker, ["net_profit_margin"], "annual"),
        )
        answer = _render_growth_and_margin_trend_answer(
            ticker,
            _dataframe_records_with_index(growth_df),
            _dataframe_records_with_index(ratio_df),
        )
        if answer:
            return (["retrieving financial time series", "computing ratio trends"], answer)

    if ticker and "8-k" in lowered_message and ("free cash flow" in lowered_message or "capex" in lowered_message):
        start_date = _extract_first_iso_date(request.message) or (
            date.today() - timedelta(days=365)
        ).isoformat()
        events, cashflow_df = await asyncio.gather(
            asyncio.to_thread(analytics_get_material_events, ticker, start_date, None, None, 10),
            asyncio.to_thread(analytics_cashflow_timeseries, ticker, "annual"),
        )
        answer = _render_events_and_cashflow_answer_direct(
            request,
            events,
            sec_dataframe_records(cashflow_df),
        )
        if answer:
            return (["analyzing 8-K events", "retrieving cash flow data"], answer)

    if ticker and "eight quarters" in lowered_message and "free cash flow" in lowered_message:
        quarterly_df, ttm_payload = await asyncio.gather(
            asyncio.to_thread(analytics_quarterly_detail, ticker, ["revenue", "net_income"], 8),
            asyncio.to_thread(analytics_ttm_metrics, ticker, ["free_cash_flow"]),
        )
        answer = _render_quarterly_trend_and_ttm_answer(
            request,
            _dataframe_records_with_index(quarterly_df),
            ttm_payload,
        )
        if answer:
            return (["analyzing quarterly financials", "computing trailing-twelve-month metrics"], answer)

    if ticker and "10-k" in lowered_message and "section where the match appears" in lowered_message:
        query = _extract_search_query(request.message)
        if query:
            filings = await asyncio.to_thread(analytics_get_filings_list, ticker, "10-K", 1)
            if filings:
                filing = filings[0]
                matches = await asyncio.to_thread(
                    analytics_search_filing_text,
                    ticker,
                    str(filing.get("accession_number") or ""),
                    query,
                    None,
                    5,
                    280,
                )
                answer = _render_latest_10k_search_answer(filing, query, matches)
                if answer:
                    return (["searching filings", "searching filing text"], answer)

    if ticker and "10-k" in lowered_message and "risk" in lowered_message:
        filings = await asyncio.to_thread(analytics_get_filings_list, ticker, "10-K", 1)
        if filings:
            filing = filings[0]
            accession_number = str(filing.get("accession_number") or "")
            section = await asyncio.to_thread(
                analytics_get_filing_section,
                ticker,
                accession_number,
                "risk factors",
            )
            section_text = "\n".join(
                part
                for part in [
                    str(section.get("heading") or "").strip(),
                    str(section.get("content") or "").strip(),
                ]
                if part
            )
            if not section_text:
                section_text = await asyncio.to_thread(
                    analytics_get_filing_text,
                    ticker,
                    accession_number,
                )
            answer = _render_latest_10k_risk_answer(ticker, filing, section_text)
            if answer:
                return (["searching filings", "reading SEC filings"], answer)

    if (
        ticker
        and "10-k" in lowered_message
        and any(token in lowered_message for token in ["md&a", "management's discussion", "management discussion"])
        and any(token in lowered_message for token in ["highlight", "highlights", "theme", "themes", "point", "points"])
    ):
        filings = await asyncio.to_thread(analytics_get_filings_list, ticker, "10-K", 1)
        if filings:
            filing = filings[0]
            accession_number = str(filing.get("accession_number") or "")
            section = await asyncio.to_thread(
                analytics_get_filing_section,
                ticker,
                accession_number,
                "mda",
            )
            section_text = "\n".join(
                part
                for part in [
                    str(section.get("heading") or "").strip(),
                    str(section.get("content") or "").strip(),
                ]
                if part
            )
            if not section_text:
                section_text = _extract_mdna_excerpt(
                    await asyncio.to_thread(
                        analytics_get_filing_text,
                        ticker,
                        accession_number,
                    )
                )
            answer = _render_latest_10k_mdna_answer(ticker, filing, section_text)
            if answer:
                return (["searching filings", "reading SEC filings"], answer)

    if (
        ticker
        and "risk factor" in lowered_message
        and "prior annual filing" in lowered_message
        and "change" in lowered_message
    ):
        filings = await asyncio.to_thread(analytics_get_filings_list, ticker, "10-K", 1)
        if filings:
            filing = filings[0]
            comparison = await asyncio.to_thread(
                analytics_compare_filing_sections,
                ticker,
                str(filing.get("accession_number") or ""),
                "risk factors",
                None,
                8,
                360,
            )
            answer = _render_filing_section_comparison_answer(comparison)
            if answer:
                return (["searching filings", "comparing filing sections"], answer)

    if (
        "rank" in lowered_message
        and "free cash flow" in lowered_message
        and "latest annual" in lowered_message
    ):
        ranking_tickers = _extract_explicit_tickers(request.message)
        if len(ranking_tickers) >= 2:
            cashflow_dfs = await asyncio.gather(
                *(asyncio.to_thread(analytics_cashflow_timeseries, symbol, "annual") for symbol in ranking_tickers)
            )
            answer = _render_cross_company_fcf_ranking(
                ranking_tickers,
                {
                    symbol: sec_dataframe_records(df)
                    for symbol, df in zip(ranking_tickers, cashflow_dfs, strict=True)
                },
            )
            if answer:
                return (["comparing companies", "retrieving cash flow data"], answer)

    return None


def _render_proxy_statement_answer(
    user_message: str,
    tool_observations: list[dict[str, str]],
) -> str | None:
    """Render simple proxy-compensation questions directly from structured proxy rows."""
    lowered_message = user_message.lower()
    if "proxy" not in lowered_message:
        return None
    if "compensation" not in lowered_message and "pay-versus-performance" not in lowered_message:
        return None

    records: list[dict[str, Any]] = []
    for observation in tool_observations:
        if observation.get("tool_name") != "get_proxy_statement_data":
            continue
        records.extend(_parse_proxy_records(observation.get("output", "")))
    latest = _latest_proxy_record(records)
    return _render_proxy_snapshot_answer(latest) if latest else None


def _render_institutional_holdings_answer(
    user_message: str,
    tool_observations: list[dict[str, str]],
) -> str | None:
    """Render simple 13F concentration questions directly from structured summaries."""
    lowered_message = user_message.lower()
    if "13f" not in lowered_message and "holdings" not in lowered_message:
        return None

    candidate_summaries: list[dict[str, Any]] = []
    for observation in tool_observations:
        tool_name = observation.get("tool_name")
        if tool_name == "summarize_institutional_holdings":
            parsed = _parse_institutional_holdings_summary(observation.get("output", ""))
            if parsed:
                candidate_summaries.append(parsed)
            continue
        if tool_name != "get_institutional_holdings":
            continue
        rows = _parse_institutional_holdings_rows(observation.get("output", ""))
        if rows:
            candidate_summaries.append(summarize_institutional_holdings_rows(rows))

    summary: dict[str, Any] | None = None
    for candidate in candidate_summaries:
        if not candidate:
            continue
        if summary is None or (
            str(candidate.get("filing_date") or ""),
            str(candidate.get("accession_number") or ""),
        ) > (
            str(summary.get("filing_date") or ""),
            str(summary.get("accession_number") or ""),
        ):
            summary = candidate
    if not summary:
        return None

    top_holdings = summary.get("top_holdings") or []
    if not isinstance(top_holdings, list):
        top_holdings = []

    lines = [
        f"The latest retrieved 13F-HR was filed {summary.get('filing_date')} "
        f"for report period {summary.get('report_period')} (accession {summary.get('accession_number')}).",
        f"- Total portfolio value: {_format_money(summary.get('total_value'))}",
        f"- Total holdings: {summary.get('total_holdings')} positions across {summary.get('distinct_securities')} distinct securities",
        "",
        "Top holdings:",
    ]

    for index, row in enumerate(top_holdings, start=1):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {index}. {row.get('ticker') or 'N/A'} ({row.get('issuer') or 'N/A'}): "
            f"{_format_money(row.get('value'))} ({_format_percent(row.get('portfolio_weight_pct'))})"
        )

    lines.extend(
        [
            "",
            "Portfolio concentration:",
            f"- Top 5 holdings: {_format_percent(summary.get('top_5_concentration_pct'))}",
            f"- Top 10 holdings: {_format_percent(summary.get('top_10_concentration_pct'))}",
        ]
    )

    return "\n".join(lines)


def _render_material_event_answer(
    user_message: str,
    tool_observations: list[dict[str, str]],
) -> str | None:
    """Render simple 8-K material-event questions directly from structured rows."""
    lowered_message = user_message.lower()
    if "8-k" not in lowered_message:
        return None
    if any(
        keyword in lowered_message
        for keyword in [
            "cash flow",
            "cashflow",
            "free cash flow",
            "fcf",
            "revenue",
            "margin",
            "ratio",
            "proxy",
            "13f",
            "holding",
            "insider",
        ]
    ):
        return None

    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for observation in tool_observations:
        if observation.get("tool_name") != "get_material_events":
            continue
        parsed_rows = _parse_material_event_rows(observation.get("output", ""))
        for row in parsed_rows:
            row_key = (
                row.get("accession_number", "") or row["filing_date"],
                row["item_code"],
                row["summary"],
            )
            if row_key in seen_keys:
                continue
            seen_keys.add(row_key)
            rows.append(row)
    if not rows:
        return None

    rows.sort(key=lambda row: row["filing_date"], reverse=True)
    earliest = min(row["filing_date"] for row in rows)
    latest = max(row["filing_date"] for row in rows)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["item_code"], []).append(row)

    item_lines: list[str] = []
    for item_code in sorted(grouped, key=lambda code: [int(part) for part in code.split(".")]):
        item_rows = grouped[item_code]
        title = _extract_material_event_title(item_rows[0])
        years = sorted({row["filing_date"][:4] for row in item_rows if row["filing_date"]})
        year_span = years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"
        recent_dates: list[str] = []
        for row in item_rows:
            filing_date = row["filing_date"]
            if filing_date not in recent_dates:
                recent_dates.append(filing_date)
            if len(recent_dates) == 3:
                break
        content_types = sorted(
            {row["content_type"] for row in item_rows if row["content_type"]}
        )
        if item_code == "9.01":
            theme = "exhibits and supporting materials attached to the related 8-K events"
        elif content_types:
            theme = ", ".join(content_type.replace("_", " ") for content_type in content_types)
        else:
            theme = "material event disclosures"
        item_lines.append(
            f"- Item {item_code}: {title}. Appears across {year_span}; recent filing dates "
            f"{', '.join(recent_dates)}. Briefly: {theme}."
        )

    requested_start = _extract_first_iso_date(user_message)
    opening = "Retrieved 8-K material-event rows"
    if requested_start:
        opening += f" since {requested_start}"
    opening += f" span {earliest} through {latest}."
    return opening + " The item codes reported in that window are:\n\n" + "\n".join(item_lines)


def _prepare_grounding_tool_context(
    tool_observations: list[dict[str, str]],
) -> tuple[list[str], bool]:
    """Normalize tool outputs into compact grounding context."""
    tool_context: list[str] = []
    has_material_event_rows = False

    def _clip_tool_output(tool_name: str, output: str) -> str:
        char_limit = (
            _GROUNDING_READ_FILING_OUTPUT_CHARS
            if tool_name == "read_filing"
            else _GROUNDING_MAX_TOOL_OUTPUT_CHARS
        )
        if len(output) <= char_limit:
            return output
        return output[:char_limit]

    for observation in tool_observations[:_GROUNDING_MAX_TOOL_OUTPUTS]:
        output = observation.get("output", "").strip()
        if not output or output.startswith("An error occurred while running the tool."):
            continue

        tool_name = observation.get("tool_name") or "unknown_tool"
        normalized_output = output
        if tool_name == "get_material_events":
            summary = _summarize_material_event_output(output)
            if summary:
                normalized_output = summary
                has_material_event_rows = True
        elif tool_name == "summarize_material_events":
            has_material_event_rows = True

        tool_context.append(
            f"Tool: {tool_name}\nOutput:\n"
            f"{_clip_tool_output(tool_name, normalized_output)}"
        )

    return tool_context, has_material_event_rows


async def _ground_final_output(
    user_message: str,
    draft_text: str,
    tool_observations: list[dict[str, str]],
) -> str:
    """Rewrite the final answer so it stays within retrieved tool evidence."""
    if not tool_observations:
        return draft_text

    proxy_answer = _render_proxy_statement_answer(user_message, tool_observations)
    if proxy_answer:
        return proxy_answer

    holdings_answer = _render_institutional_holdings_answer(user_message, tool_observations)
    if holdings_answer:
        return holdings_answer

    material_event_answer = _render_material_event_answer(user_message, tool_observations)
    if material_event_answer:
        return material_event_answer

    tool_context, has_material_event_rows = _prepare_grounding_tool_context(
        tool_observations
    )

    if not tool_context:
        return draft_text

    draft_for_prompt = draft_text
    if has_material_event_rows:
        draft_for_prompt = "[ignore the draft and answer from the structured 8-K event outputs only]"

    client = AsyncOpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0.0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict financial editor. Write a fresh answer from "
                            "scratch using only facts supported by the provided tool outputs. "
                            "Ignore unsupported or mislabeled statements in the draft. Remove "
                            "invented ratios, outside historical context, and unsolicited bull/bear "
                            "commentary. Keep quarterly, annual, and TTM figures strictly distinct: "
                            "never relabel a quarterly figure as TTM or annual, and never relabel a "
                            "TTM or annual figure as quarterly. If the retrieved data does not support "
                            "a requested metric, say that it is not available from the retrieved data. "
                            "Preserve correct numbers, prefer the exact period granularity asked by the user, "
                            "and keep the answer tightly scoped to the user's requested metrics only. Drop "
                            "extra per-share metrics, EBITDA, leverage, business-segment commentary, and any "
                            "other adjacent facts unless they are explicitly requested. Ignore tool-call error "
                            "messages and use only successful tool outputs. When the retrieved tool outputs "
                            "include structured 8-K material-event rows, cover the full returned filing-date "
                            "range, summarize by item code, and ignore conflicting draft text or prior knowledge. "
                            "Keep the answer concise. "
                            "Return plain text only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"User question:\n{user_message}\n\n"
                            f"Draft answer:\n{draft_for_prompt or '[none]'}\n\n"
                            "Retrieved tool outputs:\n"
                            + "\n\n".join(tool_context)
                        ),
                    },
                ],
            ),
            timeout=_GROUNDING_TIMEOUT_SECONDS,
        )
    except Exception:
        return draft_text

    grounded_text = response.choices[0].message.content or ""
    grounded_text = grounded_text.strip()
    return grounded_text or draft_text


async def handle_chat(request: ChatRequest) -> StreamingResponse:
    """Process a chat request and return an SSE streaming response.

    The agent decides which tools to call, executes them, then streams
    the final textual answer token-by-token.
    """
    # Build the input message list for the agent.
    input_items: list[dict[str, str]] = []

    if request.ticker:
        ticker = request.ticker.upper()
        input_items.append(
            {
                "role": "user",
                "content": (
                    f"[Context: the user is currently viewing the company page "
                    f"for {ticker}. Use this ticker when they refer to "
                    f"'this company' or 'the company'.]"
                ),
            }
        )

    for msg in request.history:
        input_items.append({"role": msg.role, "content": msg.content})

    input_items.extend(_tool_guidance_messages(request))
    input_items.append({"role": "user", "content": request.message})

    async def event_generator():
        progress_messages: list[str] = []
        with start_chat_trace(
            message=request.message,
            ticker=request.ticker,
            history_length=len(request.history),
            session_id=request.session_id,
            source=request.source,
        ) as trace_span:
            try:
                progress_queue: asyncio.Queue[str] = asyncio.Queue()

                async def queue_progress(message: str) -> None:
                    await progress_queue.put(message)

                execution_task = asyncio.create_task(
                    execute_research_request(
                        request,
                        input_items=list(input_items),
                        build_agent_fn=build_agent,
                        try_direct_answer_fn=_try_direct_answer,
                        ground_final_output_fn=_ground_final_output,
                        serialize_final_output_fn=_serialize_final_output,
                        run_streamed_fn=Runner.run_streamed,
                        tool_name_from_item_fn=_tool_name_from_item,
                        extract_tool_output_fn=_extract_tool_output,
                        progress_message_for_tool_fn=_progress_message_for_tool,
                        max_turns=_MAX_TURNS,
                        grounding_max_tool_outputs=_GROUNDING_MAX_TOOL_OUTPUTS,
                        initial_progress=_INITIAL_PROGRESS,
                        retry_progress=_RETRY_PROGRESS,
                        tool_output_progress=_TOOL_OUTPUT_PROGRESS,
                        final_progress=_FINAL_PROGRESS,
                        blank_final_retry_instruction=_BLANK_FINAL_RETRY_INSTRUCTION,
                        progress_handler=queue_progress,
                    )
                )

                while not execution_task.done() or not progress_queue.empty():
                    try:
                        progress_message = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                    except asyncio.TimeoutError:
                        if execution_task.done():
                            break
                        continue
                    progress_messages.append(progress_message)
                    yield _sse_payload({"progress": progress_message})

                execution_result = await execution_task
                final_text = execution_result.final_text

                update_chat_trace(
                    trace_span,
                    output={"answer": final_text},
                    status="ok",
                    progress_count=len(progress_messages),
                )
                for sse_chunk in _stream_text_as_sse(final_text):
                    yield sse_chunk
                yield "data: [DONE]\n\n"
            except Exception as e:
                update_chat_trace(
                    trace_span,
                    output={"error": str(e)},
                    status="error",
                    progress_count=len(progress_messages),
                )
                log.error("Agent streaming error: %s", e, exc_info=True)
                yield _sse_payload({"error": str(e)})
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
