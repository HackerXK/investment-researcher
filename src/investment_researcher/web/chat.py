"""Chat backend — agentic tool-use with OpenAI Agents SDK.

Strategy:
- An ``Agent`` with access to financial analytics tools plans and executes
  multi-step analyses autonomously (e.g. fetch metrics, compare ratios,
  read SEC filings) then streams the final answer via SSE.
- Uses ``OpenAIChatCompletionsModel`` to talk to the local vLLM instance
  (Qwen 2.5 32B, OpenAI-compatible Chat Completions endpoint).
- Tracing is disabled (no OpenAI platform key required).
"""

from __future__ import annotations

import json
import logging

from agents import Agent, ModelSettings, RunItemStreamEvent, Runner, set_tracing_disabled
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from investment_researcher.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from investment_researcher.web.agent_tools import ALL_TOOLS

log = logging.getLogger(__name__)

# Disable tracing — we don't have an OpenAI platform key
set_tracing_disabled(True)


# ---------------------------------------------------------------------------
# Request / response models  (unchanged API contract)
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    ticker: str | None = None
    history: list[ChatMessage] = []


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
- Cite specific numbers from tool results.
- When referencing SEC filing text, include the accession number.
- Be precise and quantitative; avoid vague qualifiers when data is available.
- If data is unavailable or a tool returns empty results, say so honestly.
- Provide both bull and bear perspectives when discussing company outlook.
- You are NOT limited to annual data — use quarterly, TTM, and time-series \
  tools when the question warrants it.
- You can read ANY SEC filing type (10-K, 10-Q, 8-K, DEF 14A, etc.), not \
  just the latest 10-K.  Use list_filings to discover available filings, \
  then read_filing to read them.
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

## Available metric names (not exhaustive)
revenue, net_income, gross_profit, operating_income, ebitda, total_assets, \
total_liabilities, total_equity, current_assets, current_liabilities, \
cash_and_equivalents, total_debt, operating_cash_flow, free_cash_flow, \
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
    return Agent(
        name="Financial Analyst",
        instructions=_SYSTEM_PROMPT,
        model=_build_model(),
        tools=list(ALL_TOOLS),
        model_settings=ModelSettings(temperature=0.7),
    )


# ---------------------------------------------------------------------------
# Chat handler (SSE streaming)
# ---------------------------------------------------------------------------

# Maximum agent turns to prevent runaway loops
_MAX_TURNS = 15
_FINAL_OUTPUT_CHUNK_SIZE = 96
_INITIAL_PROGRESS = "planning the analysis"
_TOOL_OUTPUT_PROGRESS = "analyzing the retrieved data"
_FINAL_PROGRESS = "drafting the answer"

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
    "read_filing": "reading SEC filings",
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


async def handle_chat(request: ChatRequest) -> StreamingResponse:
    """Process a chat request and return an SSE streaming response.

    The agent decides which tools to call, executes them, then streams
    the final textual answer token-by-token.
    """
    # Build the input message list for the agent
    input_items: list[dict[str, str]] = []

    # Inject ticker hint so the agent knows the context without a tool call
    if request.ticker:
        ticker = request.ticker.upper()
        input_items.append({
            "role": "user",
            "content": (
                f"[Context: the user is currently viewing the company page "
                f"for {ticker}. Use this ticker when they refer to "
                f"'this company' or 'the company'.]"
            ),
        })

    # Conversation history
    for msg in request.history:
        input_items.append({"role": msg.role, "content": msg.content})

    # Current user message
    input_items.append({"role": "user", "content": request.message})

    agent = build_agent()

    async def event_generator():
        try:
            last_progress: str | None = None

            def emit_progress(message: str):
                nonlocal last_progress
                if message and message != last_progress:
                    last_progress = message
                    return _sse_payload({"progress": message})
                return None

            result = Runner.run_streamed(
                agent,
                input=input_items,
                max_turns=_MAX_TURNS,
            )
            planning_update = emit_progress(_INITIAL_PROGRESS)
            if planning_update:
                yield planning_update

            # Consume the full agent run first. Raw stream events include interim
            # planning text and tool-call chatter, which should not be exposed to
            # the user-facing chat UI.
            async for event in result.stream_events():
                if isinstance(event, RunItemStreamEvent):
                    progress_update = None
                    if event.name == "tool_called":
                        tool_name = _tool_name_from_item(event.item)
                        progress_update = emit_progress(_progress_message_for_tool(tool_name))
                    elif event.name == "tool_output":
                        progress_update = emit_progress(_TOOL_OUTPUT_PROGRESS)

                    if progress_update:
                        yield progress_update

            final_text = _serialize_final_output(result.final_output)
            final_progress = emit_progress(_FINAL_PROGRESS)
            if final_progress and final_text:
                yield final_progress
            for sse_chunk in _stream_text_as_sse(final_text):
                yield sse_chunk
            yield "data: [DONE]\n\n"
        except Exception as e:
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
