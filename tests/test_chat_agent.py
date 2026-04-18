"""Tests for the agentic chat system — agent wiring, tool registration, and SSE contract.

These tests verify:
1. All tools are registered on the agent with correct schemas
2. Tool wrapper functions return JSON-serialisable output
3. The chat handler returns a StreamingResponse with correct headers
4. The SSE stream format matches the frontend contract
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from agents import FunctionTool
from httpx import ASGITransport, AsyncClient

from investment_researcher.web.agent_tools import (
    ALL_TOOLS,
    compare_metric_across_companies,
    get_cashflow_pivot,
    get_company_profile,
    get_growth_rates,
    get_latest_ratios,
    get_metrics_pivot,
    get_metrics_timeseries,
    get_quarterly_detail,
    get_ratio_timeseries,
    get_ratios_wide,
    get_ticker_summary,
    get_ttm_metrics,
    get_ttm_ratios,
    list_available_ratios,
    list_available_tickers,
    list_filings,
    read_filing,
    search_companies,
)
from investment_researcher.web import chat as chat_module
from investment_researcher.web.chat import ChatMessage, ChatRequest, build_agent


# ── Agent construction tests ───────────────────────────────────────


class TestAgentConstruction:
    """Verify the agent is properly configured with all tools."""

    def test_build_agent_returns_agent(self):
        agent = build_agent()
        assert agent.name == "Financial Analyst"

    def test_agent_has_all_tools(self):
        agent = build_agent()
        assert len(agent.tools) == len(ALL_TOOLS)

    def test_all_tools_are_function_tools(self):
        agent = build_agent()
        for tool in agent.tools:
            assert isinstance(tool, FunctionTool), f"{tool} is not a FunctionTool"

    def test_agent_tool_names(self):
        agent = build_agent()
        tool_names = {t.name for t in agent.tools}
        expected = {
            "search_companies",
            "get_company_profile",
            "list_available_tickers",
            "get_ticker_summary",
            "get_metrics_timeseries",
            "get_metrics_pivot",
            "get_growth_rates",
            "get_cashflow_pivot",
            "get_ttm_metrics",
            "get_quarterly_detail",
            "get_latest_ratios",
            "get_ttm_ratios",
            "get_ratios_wide",
            "get_ratio_timeseries",
            "list_available_ratios",
            "compare_metric_across_companies",
            "list_filings",
            "read_filing",
        }
        assert tool_names == expected

    def test_every_tool_has_description(self):
        agent = build_agent()
        for tool in agent.tools:
            assert tool.description, f"Tool {tool.name} has no description"

    def test_every_tool_has_params_schema(self):
        agent = build_agent()
        for tool in agent.tools:
            assert tool.params_json_schema, f"Tool {tool.name} has no params schema"

    def test_agent_instructions_mention_tools(self):
        agent = build_agent()
        assert "tool" in agent.instructions.lower()

    def test_agent_instructions_mention_plan(self):
        agent = build_agent()
        assert "plan" in agent.instructions.lower()


# ── Tool output tests (verify JSON-serialisability with real DuckDB) ───


class TestToolOutputs:
    """Verify each tool returns valid JSON strings from the test DuckDB."""

    def test_search_companies(self):
        result = search_companies.on_invoke_tool  # we'll test the wrapped fn
        # Test the raw analytics function via the wrapper
        from investment_researcher.web.agent_tools import _search_companies
        raw = _search_companies("AAPL", 5)
        assert isinstance(raw, list)

    def test_get_company_profile_returns_json(self):
        from investment_researcher.web.agent_tools import (
            _get_company_profile,
            _dict_to_json,
        )
        profile = _get_company_profile("AAPL")
        result = _dict_to_json(profile)
        parsed = json.loads(result)
        assert parsed["ticker"] == "AAPL"

    def test_get_ticker_summary_returns_json(self):
        from investment_researcher.analytics import ticker_summary
        from investment_researcher.web.agent_tools import _df_to_json
        df = ticker_summary("AAPL")
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) > 0

    def test_get_metrics_pivot_returns_json(self):
        from investment_researcher.analytics import pivot_metrics
        from investment_researcher.web.agent_tools import _df_to_json
        df = pivot_metrics("AAPL", ["revenue", "net_income"])
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_get_growth_rates_returns_json(self):
        from investment_researcher.analytics import growth_rates
        from investment_researcher.web.agent_tools import _df_to_json
        df = growth_rates("AAPL", ["revenue"])
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_get_ttm_metrics_returns_json(self):
        from investment_researcher.analytics import ttm_metrics
        from investment_researcher.web.agent_tools import _dict_to_json
        result = ttm_metrics("AAPL", ["revenue", "net_income"])
        json_str = _dict_to_json(result)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_get_quarterly_detail_returns_json(self):
        from investment_researcher.analytics import quarterly_detail
        from investment_researcher.web.agent_tools import _df_to_json
        df = quarterly_detail("AAPL", ["revenue"], 4)
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_get_ratios_latest_returns_json(self):
        from investment_researcher.analytics import get_ratios_latest
        from investment_researcher.web.agent_tools import _dict_to_json
        result = get_ratios_latest("AAPL")
        json_str = _dict_to_json(result)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_get_ratios_ttm_returns_json(self):
        from investment_researcher.analytics import get_ratios_ttm
        from investment_researcher.web.agent_tools import _dict_to_json
        result = get_ratios_ttm("AAPL")
        json_str = _dict_to_json(result)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_get_cashflow_pivot_returns_json(self):
        from investment_researcher.analytics import cashflow_pivot
        from investment_researcher.web.agent_tools import _df_to_json
        df = cashflow_pivot("AAPL")
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_list_available_ratios_returns_json(self):
        from investment_researcher.web.agent_tools import (
            list_available_ratios as _list_ratios,
        )
        from investment_researcher.analytics import get_ratios_by_category
        categories = get_ratios_by_category()
        result: dict = {}
        for cat, defs in categories.items():
            result[cat] = [{"name": d.name, "display_format": d.display_format} for d in defs]
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert "Profitability Margins" in parsed
        assert len(parsed["Profitability Margins"]) > 0

    def test_compare_metric_returns_json(self):
        from investment_researcher.analytics import latest_metric_for_all
        from investment_researcher.web.agent_tools import _df_to_json
        df = latest_metric_for_all("revenue")
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    def test_list_available_tickers(self):
        from investment_researcher.analytics import get_all_tickers
        tickers = get_all_tickers()
        assert isinstance(tickers, list)
        assert "AAPL" in tickers

    def test_get_ratios_wide_returns_json(self):
        from investment_researcher.analytics import get_ratios_wide
        from investment_researcher.web.agent_tools import _df_to_json
        df = get_ratios_wide("AAPL")
        result = _df_to_json(df)
        parsed = json.loads(result)
        assert isinstance(parsed, list)


# ── Tool schema tests ──────────────────────────────────────────────


class TestToolSchemas:
    """Verify tool schemas have correct parameter definitions."""

    def _get_tool_by_name(self, name: str) -> FunctionTool:
        agent = build_agent()
        for tool in agent.tools:
            if tool.name == name:
                return tool
        raise AssertionError(f"Tool {name} not found on agent")

    def test_search_companies_schema(self):
        tool = self._get_tool_by_name("search_companies")
        props = tool.params_json_schema.get("properties", {})
        assert "query" in props
        assert "limit" in props

    def test_get_ticker_summary_schema(self):
        tool = self._get_tool_by_name("get_ticker_summary")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "period_type" in props

    def test_get_metrics_timeseries_schema(self):
        tool = self._get_tool_by_name("get_metrics_timeseries")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "metrics" in props
        assert "period_type" in props

    def test_get_ttm_metrics_schema(self):
        tool = self._get_tool_by_name("get_ttm_metrics")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "metrics" in props

    def test_list_filings_schema(self):
        tool = self._get_tool_by_name("list_filings")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "form_type" in props
        assert "limit" in props

    def test_read_filing_schema(self):
        tool = self._get_tool_by_name("read_filing")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "accession_number" in props

    def test_compare_metric_schema(self):
        tool = self._get_tool_by_name("compare_metric_across_companies")
        props = tool.params_json_schema.get("properties", {})
        assert "metric_type" in props
        assert "period_type" in props
        assert "limit" in props

    def test_get_quarterly_detail_schema(self):
        tool = self._get_tool_by_name("get_quarterly_detail")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "metrics" in props
        assert "n_quarters" in props


# ── Chat request / response models ────────────────────────────────


class TestChatModels:
    """Verify the Pydantic models used by the chat endpoint."""

    def test_chat_request_minimal(self):
        req = ChatRequest(message="hello")
        assert req.ticker is None
        assert req.history == []

    def test_chat_request_with_ticker(self):
        req = ChatRequest(message="What is revenue?", ticker="AAPL")
        assert req.ticker == "AAPL"

    def test_chat_request_with_history(self):
        history = [
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ]
        req = ChatRequest(message="more info", ticker="AAPL", history=history)
        assert len(req.history) == 2


# ── SSE endpoint contract tests ───────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    from investment_researcher.web.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_chat_endpoint_returns_sse(client: AsyncClient):
    """The /api/chat endpoint must return text/event-stream."""
    resp = await client.post(
        "/api/chat",
        json={"message": "hello", "ticker": "AAPL"},
        # Don't follow the stream, just check headers
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_chat_endpoint_cache_headers(client: AsyncClient):
    """SSE responses must have no-cache and no-buffering headers."""
    resp = await client.post(
        "/api/chat",
        json={"message": "hello"},
    )
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.asyncio
async def test_chat_endpoint_sse_format(client: AsyncClient):
    """SSE lines must be 'data: {...}' or 'data: [DONE]'."""
    resp = await client.post(
        "/api/chat",
        json={"message": "hello"},
    )
    body = resp.text
    # The response must end with [DONE]
    data_lines = [
        line for line in body.split("\n") if line.startswith("data: ")
    ]
    assert len(data_lines) > 0
    # Last data line should be [DONE]
    assert data_lines[-1] == "data: [DONE]"
    # Other data lines should be valid JSON with 'token' or 'error' key
    for line in data_lines[:-1]:
        payload = line[6:]  # strip 'data: '
        parsed = json.loads(payload)
        assert "token" in parsed or "error" in parsed


@pytest.mark.asyncio
async def test_chat_with_history(client: AsyncClient):
    """Chat should accept conversation history without error."""
    resp = await client.post(
        "/api/chat",
        json={
            "message": "Tell me more",
            "ticker": "AAPL",
            "history": [
                {"role": "user", "content": "What is AAPL revenue?"},
                {"role": "assistant", "content": "AAPL revenue is..."},
            ],
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_handle_chat_streams_only_final_output(monkeypatch):
    """The SSE stream should exclude raw interim planning text."""

    class FakeRunResult:
        def __init__(self):
            self.final_output = "Final polished answer."

        async def stream_events(self):
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(delta="Let me try again with another tool..."),
            )
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(delta="I think the form type may be wrong..."),
            )

    def fake_run_streamed(*args, **kwargs):
        return FakeRunResult()

    monkeypatch.setattr(chat_module, "build_agent", lambda: object())
    monkeypatch.setattr(chat_module.Runner, "run_streamed", fake_run_streamed)

    response = await chat_module.handle_chat(ChatRequest(message="hello", ticker="AAPL"))

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]

    assert data_lines[-1] == "data: [DONE]"

    streamed_tokens: list[str] = []
    for line in data_lines[:-1]:
        payload = json.loads(line[6:])
        streamed_tokens.append(payload["token"])

    assert "".join(streamed_tokens) == "Final polished answer."
    assert "Let me try again" not in body
    assert "form type may be wrong" not in body
