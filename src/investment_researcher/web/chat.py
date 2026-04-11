"""Chat backend — full-context stuffing with local LLM via OpenAI-compatible API.

Strategy:
- If a ticker is provided, load the latest 10-K filing text via edgartools
  ``filing.markdown()`` and structured financial data from DuckDB.
- Stuff both into the LLM context window (Qwen 2.5 32B supports 128K tokens).
- Stream responses via SSE for responsive UX.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

from investment_researcher.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL

log = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    ticker: str | None = None
    history: list[ChatMessage] = []


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


def _build_financial_context(ticker: str) -> str:
    """Build a structured financial summary for the given ticker."""
    try:
        from investment_researcher.analytics import (
            get_company_profile,
            get_ratios_latest,
            get_ratios_ttm,
            pivot_metrics,
            ticker_summary,
        )

        parts: list[str] = []

        profile = get_company_profile(ticker)
        name = profile.get("name", ticker)
        parts.append(f"Company: {name} ({ticker})")
        if profile.get("sic_description"):
            parts.append(f"Industry: {profile['sic_description']}")

        summary = ticker_summary(ticker)
        if not summary.empty:
            parts.append("\n--- Latest Financial Metrics (Annual) ---")
            for _, row in summary.iterrows():
                metric = row.get("metric_type", "")
                value = row.get("value")
                if value is not None:
                    parts.append(f"  {metric}: {value:,.2f}")

        ratios = get_ratios_latest(ticker)
        if ratios:
            parts.append("\n--- Key Financial Ratios ---")
            for name_r, val in ratios.items():
                if val is not None:
                    parts.append(f"  {name_r}: {val:.4f}")

        ttm = get_ratios_ttm(ticker)
        if ttm:
            parts.append("\n--- TTM Ratios ---")
            for name_r, val in ttm.items():
                if val is not None:
                    parts.append(f"  {name_r}: {val:.4f}")

        return "\n".join(parts)
    except Exception:
        log.warning("Could not build financial context for %s", ticker, exc_info=True)
        return ""


def _build_filing_context(ticker: str) -> str:
    """Load the latest 10-K filing text for full-context stuffing."""
    try:
        from investment_researcher.analytics import get_filings_list, get_filing_text

        filings = get_filings_list(ticker, form_type="10-K", limit=1)
        if not filings:
            return ""
        accession = filings[0].get("accession_number", "")
        if not accession:
            return ""
        text = get_filing_text(ticker, accession)
        # Truncate to ~100K chars to stay within context window
        if len(text) > 100_000:
            text = text[:100_000] + "\n\n[... filing text truncated ...]"
        return f"\n--- Latest 10-K Filing (accession: {accession}) ---\n{text}"
    except Exception:
        log.warning("Could not load filing context for %s", ticker, exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert financial analyst assistant. You answer questions about \
public companies using SEC filing data and financial metrics.

When answering:
- Cite specific numbers from the financial data provided.
- Reference the filing accession number when citing filing text.
- Be precise and quantitative.
- If data is unavailable, say so honestly.
- Provide both bull and bear perspectives when discussing company outlook.
"""


def _get_client() -> OpenAI:
    return OpenAI(base_url=LLM_API_BASE, api_key=LLM_API_KEY)


async def handle_chat(request: ChatRequest) -> StreamingResponse:
    """Process a chat request and return an SSE streaming response."""
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    # Add company context if a ticker is specified
    if request.ticker:
        ticker = request.ticker.upper()
        financial_ctx = _build_financial_context(ticker)
        filing_ctx = _build_filing_context(ticker)
        context = financial_ctx + filing_ctx
        if context:
            messages.append({
                "role": "system",
                "content": f"Here is the financial data and filing context for {ticker}:\n\n{context}",
            })

    # Add conversation history
    for msg in request.history:
        messages.append({"role": msg.role, "content": msg.content})

    # Add current user message
    messages.append({"role": "user", "content": request.message})

    async def event_generator():
        try:
            client = _get_client()
            stream = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                stream=True,
                max_tokens=4096,
                temperature=0.7,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error("LLM streaming error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
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
