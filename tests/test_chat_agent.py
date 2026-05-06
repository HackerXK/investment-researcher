"""Tests for the agentic chat system — agent wiring, tool registration, and SSE contract.

These tests verify:
1. All tools are registered on the agent with correct schemas
2. Tool wrapper functions return JSON-serialisable output
3. The chat handler returns a StreamingResponse with correct headers
4. The SSE stream format matches the frontend contract
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pandas as pd
import pytest
import pytest_asyncio
from agents import FunctionTool, RunItemStreamEvent
from httpx import ASGITransport, AsyncClient

from investment_researcher.web.agent_tools import (
    ALL_TOOLS,
    compare_metric_across_companies,
    compare_filing_sections,
    get_beneficial_ownership,
    get_cashflow_pivot,
    get_company_profile,
    get_institutional_holdings,
    get_growth_rates,
    get_insider_trades,
    get_latest_ratios,
    get_material_events,
    get_metrics_pivot,
    get_metrics_timeseries,
    get_proxy_statement_data,
    get_quarterly_detail,
    get_ratio_timeseries,
    get_ratios_wide,
    get_ticker_summary,
    get_ttm_metrics,
    get_ttm_ratios,
    list_filing_sections,
    list_available_ratios,
    list_available_tickers,
    list_filings,
    read_filing,
    read_filing_section,
    search_filing_text,
    search_companies,
    summarize_beneficial_ownership,
    summarize_insider_sells,
    summarize_institutional_holdings,
    summarize_material_events,
    summarize_proxy_statement,
)
from investment_researcher.web import agent_tools as agent_tools_module
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
            "list_filing_sections",
            "read_filing_section",
            "search_filing_text",
            "compare_filing_sections",
            "read_filing",
            "get_beneficial_ownership",
            "summarize_beneficial_ownership",
            "get_insider_trades",
            "summarize_insider_sells",
            "get_material_events",
            "summarize_material_events",
            "get_proxy_statement_data",
            "summarize_proxy_statement",
            "get_institutional_holdings",
            "summarize_institutional_holdings",
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

    def test_truncate_filing_text_preserves_later_item_1a_section(self):
        head = "A" * (agent_tools_module._MAX_FILING_CHARS + 500)
        risk_section = "\n## Item 1A. Risk Factors\n- Demand volatility\n- Supply constraints\n"
        trailing = "\n## Item 1B. Unresolved Staff Comments\n" + ("B" * 10_000)
        text = head + risk_section + trailing

        truncated = agent_tools_module._truncate_filing_text(text)

        assert len(truncated) <= agent_tools_module._MAX_FILING_CHARS + len(
            agent_tools_module._FILING_TRUNCATION_NOTICE
        )
        assert "[... skipped to Item 1A. Risk Factors ...]" in truncated
        assert "## Item 1A. Risk Factors" in truncated
        assert "Demand volatility" in truncated

    def test_truncate_filing_text_uses_real_item_1a_body_not_toc_match(self):
        toc = "\nItem 1A. Risk Factors\nItem 1B. Unresolved Staff Comments\n"
        head = toc + ("A" * (agent_tools_module._MAX_FILING_CHARS + 500))
        actual_section = (
            "\n## Item 1A. Risk Factors\n"
            "Actual risk discussion that should survive truncation.\n"
            "\n## Item 1B. Unresolved Staff Comments\n"
        )

        truncated = agent_tools_module._truncate_filing_text(head + actual_section)

        assert "[... skipped to Item 1A. Risk Factors ...]" in truncated
        assert "Actual risk discussion that should survive truncation." in truncated

    def test_truncate_filing_text_leaves_short_filing_unchanged(self):
        text = "Short filing text"

        assert agent_tools_module._truncate_filing_text(text) == text

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
        assert "period_end" in parsed[0]

    def test_df_to_json_preserves_named_index(self):
        from investment_researcher.web.agent_tools import _df_to_json

        df = pd.DataFrame(
            [{"value": 123.0}],
            index=pd.Index(["2025-12-31"], name="period_end"),
        )

        parsed = json.loads(_df_to_json(df))

        assert parsed == [{"period_end": "2025-12-31", "value": 123.0}]

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
        assert "metric_type" in parsed[0]

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
        assert "period_end" in parsed[0]

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
        assert "start_date" in props
        assert "end_date" in props

    def test_read_filing_schema(self):
        tool = self._get_tool_by_name("read_filing")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "accession_number" in props
        assert "truncate" in props
        assert "max_chars" in props

    def test_list_filing_sections_schema(self):
        tool = self._get_tool_by_name("list_filing_sections")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "accession_number" in props

    def test_read_filing_section_schema(self):
        tool = self._get_tool_by_name("read_filing_section")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "accession_number" in props
        assert "section_name" in props
        assert "truncate" in props
        assert "max_chars" in props

    def test_search_filing_text_schema(self):
        tool = self._get_tool_by_name("search_filing_text")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "accession_number" in props
        assert "query" in props
        assert "section_name" in props
        assert "max_matches" in props
        assert "context_chars" in props

    def test_compare_filing_sections_schema(self):
        tool = self._get_tool_by_name("compare_filing_sections")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "current_accession_number" in props
        assert "previous_accession_number" in props
        assert "section_name" in props
        assert "max_changes" in props
        assert "excerpt_chars" in props
        previous_accession_schema = props["previous_accession_number"]
        assert any(
            variant.get("type") == "null"
            for variant in previous_accession_schema.get("anyOf", [])
        )

    def test_get_beneficial_ownership_schema(self):
        tool = self._get_tool_by_name("get_beneficial_ownership")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "form_type" in props
        assert "limit" in props
        assert "start_date" in props
        assert "end_date" in props
        assert "include_amendments" in props
        assert "summary_chars" in props

    def test_summarize_beneficial_ownership_schema(self):
        tool = self._get_tool_by_name("summarize_beneficial_ownership")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "form_type" in props
        assert "limit" in props
        assert "start_date" in props
        assert "end_date" in props
        assert "include_amendments" in props
        assert "summary_chars" in props

    def test_get_insider_trades_schema(self):
        tool = self._get_tool_by_name("get_insider_trades")
        props = tool.params_json_schema.get("properties", {})
        assert "ticker" in props
        assert "start_date" in props
        assert "end_date" in props
        assert "transaction_codes" in props
        assert "acquired_disposed" in props
        assert "min_value" in props

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
    # Other data lines should be valid JSON with 'token', 'progress', or 'error' key
    for line in data_lines[:-1]:
        payload = line[6:]  # strip 'data: '
        parsed = json.loads(payload)
        assert "token" in parsed or "progress" in parsed or "error" in parsed


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

    async def fake_ground_final_output(*args, **kwargs):
        return "Final polished answer."

    monkeypatch.setattr(chat_module, "build_agent", lambda: object())
    monkeypatch.setattr(chat_module, "_ground_final_output", fake_ground_final_output)
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
        if "token" in payload:
            streamed_tokens.append(payload["token"])

    assert "".join(streamed_tokens) == "Final polished answer."
    assert "Let me try again" not in body
    assert "form type may be wrong" not in body


@pytest.mark.asyncio
async def test_handle_chat_streams_neutral_progress_updates(monkeypatch):
    """The SSE stream should include neutral progress updates derived from tool events."""

    class FakeRunResult:
        def __init__(self):
            self.final_output = "Final polished answer."

        async def stream_events(self):
            yield RunItemStreamEvent(
                name="tool_called",
                item=SimpleNamespace(name="list_filings", raw_item=SimpleNamespace(name="list_filings")),
            )
            yield RunItemStreamEvent(
                name="tool_output",
                item=SimpleNamespace(output='[{"accession_number": "123"}]'),
            )
            yield RunItemStreamEvent(
                name="tool_called",
                item=SimpleNamespace(name="get_ttm_ratios", raw_item=SimpleNamespace(name="get_ttm_ratios")),
            )

    def fake_run_streamed(*args, **kwargs):
        return FakeRunResult()

    async def fake_ground_final_output(*args, **kwargs):
        return "Grounded final answer."

    monkeypatch.setattr(chat_module, "build_agent", lambda: object())
    monkeypatch.setattr(chat_module, "_ground_final_output", fake_ground_final_output)
    monkeypatch.setattr(chat_module.Runner, "run_streamed", fake_run_streamed)

    response = await chat_module.handle_chat(ChatRequest(message="hello", ticker="AAPL"))

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]

    progress_messages: list[str] = []
    token_messages: list[str] = []
    for line in data_lines[:-1]:
        payload = json.loads(line[6:])
        if "progress" in payload:
            progress_messages.append(payload["progress"])
        if "token" in payload:
            token_messages.append(payload["token"])

    assert progress_messages[:4] == [
        "planning the analysis",
        "searching filings",
        "analyzing the retrieved data",
        "computing ratios",
    ]
    assert progress_messages[-1] == "drafting the answer"
    assert "".join(token_messages) == "Grounded final answer."


@pytest.mark.asyncio
async def test_handle_chat_recovers_from_empty_final_output_with_tool_results(monkeypatch):
    """If the agent returns no final text, the grounding pass should synthesize one from tool outputs."""

    class FakeRunResult:
        def __init__(self):
            self.final_output = ""

        async def stream_events(self):
            yield RunItemStreamEvent(
                name="tool_called",
                item=SimpleNamespace(name="get_material_events", raw_item=SimpleNamespace(name="get_material_events")),
            )
            yield RunItemStreamEvent(
                name="tool_output",
                item=SimpleNamespace(output='[{"filing_date": "2026-01-28", "item_code": "2.02"}]'),
            )

    def fake_run_streamed(*args, **kwargs):
        return FakeRunResult()

    async def fake_ground_final_output(user_message, draft_text, tool_observations):
        assert draft_text == ""
        assert tool_observations == [
            {
                "tool_name": "get_material_events",
                "output": '[{"filing_date": "2026-01-28", "item_code": "2.02"}]',
            }
        ]
        return "Recovered grounded answer."

    monkeypatch.setattr(chat_module, "build_agent", lambda: object())
    monkeypatch.setattr(chat_module, "_ground_final_output", fake_ground_final_output)
    monkeypatch.setattr(chat_module.Runner, "run_streamed", fake_run_streamed)

    response = await chat_module.handle_chat(
        ChatRequest(message="What recent 8-K events has Meta reported?", ticker="META")
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]

    token_messages: list[str] = []
    for line in data_lines[:-1]:
        payload = json.loads(line[6:])
        if "token" in payload:
            token_messages.append(payload["token"])

    assert "".join(token_messages) == "Recovered grounded answer."


@pytest.mark.asyncio
async def test_handle_chat_retries_blank_final_answer_once(monkeypatch):
    run_inputs: list[list[dict[str, str]]] = []

    class BlankRunResult:
        def __init__(self):
            self.final_output = "\n\n"

        async def stream_events(self):
            if False:
                yield None

    class FilledRunResult:
        def __init__(self):
            self.final_output = "Retried final answer."

        async def stream_events(self):
            if False:
                yield None

    def fake_run_streamed(_agent, input, max_turns):
        run_inputs.append(input)
        return BlankRunResult() if len(run_inputs) == 1 else FilledRunResult()

    async def fake_ground_final_output(_user_message, draft_text, _tool_observations):
        return draft_text

    monkeypatch.setattr(chat_module, "build_agent", lambda: object())
    monkeypatch.setattr(chat_module, "_ground_final_output", fake_ground_final_output)
    monkeypatch.setattr(chat_module.Runner, "run_streamed", fake_run_streamed)

    response = await chat_module.handle_chat(
        ChatRequest(message="What recent 8-K events has Meta reported?", ticker="META")
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]

    progress_messages: list[str] = []
    token_messages: list[str] = []
    for line in data_lines[:-1]:
        payload = json.loads(line[6:])
        if "progress" in payload:
            progress_messages.append(payload["progress"])
        if "token" in payload:
            token_messages.append(payload["token"])

    assert len(run_inputs) == 2
    assert progress_messages == [
        "planning the analysis",
        "retrying the analysis",
        "drafting the answer",
    ]
    assert run_inputs[1][-1]["content"] == chat_module._BLANK_FINAL_RETRY_INSTRUCTION
    assert "".join(token_messages) == "Retried final answer."


def test_prepare_grounding_tool_context_summarizes_material_events_and_skips_errors():
    tool_context, has_material_event_rows = chat_module._prepare_grounding_tool_context(
        [
            {
                "tool_name": "get_material_events",
                "output": (
                    "An error occurred while running the tool. Please try again. "
                    "Error: Invalid JSON input"
                ),
            },
            {
                "tool_name": "get_material_events",
                "output": json.dumps(
                    [
                        {
                            "filing_date": "2026-01-28",
                            "item_code": "2.02",
                            "content_type": "earnings",
                            "summary": "Item 2.02 Results of Operations and Financial Condition.",
                        },
                        {
                            "filing_date": "2025-04-11",
                            "item_code": "5.02",
                            "content_type": "director_change",
                            "summary": "Item 5.02 Departure of Directors or Certain Officers.",
                        },
                        {
                            "filing_date": "2024-09-10",
                            "item_code": "5.03",
                            "content_type": "governance",
                            "summary": "Item 5.03 Amendments to Articles of Incorporation or Bylaws.",
                        },
                    ]
                ),
            },
        ]
    )

    assert has_material_event_rows is True
    assert len(tool_context) == 1
    assert "An error occurred while running the tool" not in tool_context[0]
    assert "Coverage: 3 event row(s) from 2024-09-10 to 2026-01-28." in tool_context[0]
    assert "2.02: 1 row(s); recent filing dates 2026-01-28" in tool_context[0]
    assert "5.02: 1 row(s); recent filing dates 2025-04-11" in tool_context[0]


def test_prepare_grounding_tool_context_uses_wider_read_filing_limit():
    output = "A" * (chat_module._GROUNDING_MAX_TOOL_OUTPUT_CHARS + 500)

    tool_context, has_material_event_rows = chat_module._prepare_grounding_tool_context(
        [
            {
                "tool_name": "read_filing",
                "output": output,
            }
        ]
    )

    assert has_material_event_rows is False
    assert len(tool_context) == 1
    assert len(tool_context[0]) > chat_module._GROUNDING_MAX_TOOL_OUTPUT_CHARS
    assert len(tool_context[0]) == len(output) + len("Tool: read_filing\nOutput:\n")


def test_read_filing_can_return_full_text_when_truncation_disabled(monkeypatch):
    filing_text = "X" * (agent_tools_module._MAX_FILING_CHARS + 1_000)

    monkeypatch.setattr(agent_tools_module, "_get_filing_text", lambda ticker, accession_number: filing_text)

    result = asyncio.run(
        read_filing.on_invoke_tool(
            SimpleNamespace(tool_name="read_filing"),
            json.dumps(
                {
                    "ticker": "NVDA",
                    "accession_number": "0001045810-26-000023",
                    "truncate": False,
                }
            ),
        )
    )

    payload = json.loads(result)

    assert payload["validation"]["ok"] is True
    assert payload["data"]["content"] == filing_text
    assert payload["data"]["truncated"] is False
    assert payload["metadata"]["tool_name"] == "read_filing"


def test_get_ticker_summary_returns_empty_data_for_unknown_ticker():
    result = asyncio.run(
        get_ticker_summary.on_invoke_tool(
            SimpleNamespace(tool_name="get_ticker_summary"),
            json.dumps({"ticker": "NOTREAL", "period_type": "annual"}),
        )
    )

    parsed = json.loads(result)

    assert parsed["validation"]["ok"] is True
    assert parsed["data"] == []
    assert parsed["metadata"]["requested_ticker"] == "NOTREAL"


def test_resolve_ticker_request_uses_punctuation_normalization_and_runtime_search(monkeypatch):
    monkeypatch.setattr(agent_tools_module, "get_all_tickers", lambda: ["BRK-B", "META"])
    monkeypatch.setattr(
        agent_tools_module,
        "_find_company_ticker_candidates",
        lambda query, limit=5: ["META"] if query == "Meta Platforms" else [],
    )

    resolved_ticker, metadata, issues = agent_tools_module._resolve_ticker_request("BRK.B")
    assert issues == []
    assert resolved_ticker == "BRK-B"
    assert metadata["ticker_match_exact"] is True

    resolved_ticker, metadata, issues = agent_tools_module._resolve_ticker_request("Meta Platforms")
    assert issues == []
    assert resolved_ticker == "META"
    assert metadata["ticker_candidates"] == ["META"]


def test_get_insider_trades_returns_empty_data_for_reversed_date_range():
    result = asyncio.run(
        get_insider_trades.on_invoke_tool(
            SimpleNamespace(tool_name="get_insider_trades"),
            json.dumps(
                {
                    "ticker": "AAPL",
                    "start_date": "2026-12-31",
                    "end_date": "2026-01-01",
                }
            ),
        )
    )

    parsed = json.loads(result)

    assert parsed["validation"]["ok"] is True
    assert parsed["data"] == []


def test_render_material_event_answer_covers_full_range_without_extra_names():
    answer = chat_module._render_material_event_answer(
        "What recent 8-K material events has Meta reported since 2024-01-01? List the item codes and explain them briefly.",
        [
            {
                "tool_name": "get_material_events",
                "output": json.dumps(
                    [
                        {
                            "filing_date": "2026-01-28",
                            "item_code": "2.02",
                            "item": "Item 2.02",
                            "content_type": "earnings",
                            "summary": "Item 2.02 Results of Operations and Financial Condition. Quarterly earnings release.",
                        },
                        {
                            "filing_date": "2025-04-11",
                            "item_code": "5.02",
                            "item": "Item 5.02",
                            "content_type": "director_change",
                            "summary": "Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers.",
                        },
                        {
                            "filing_date": "2024-09-10",
                            "item_code": "5.03",
                            "item": "Item 5.03",
                            "content_type": "governance",
                            "summary": "Item 5.03 Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year.",
                        },
                    ]
                ),
            }
        ],
    )

    assert answer is not None
    assert "2024-09-10 through 2026-01-28" in answer
    assert "Item 2.02: Results of Operations and Financial Condition." in answer
    assert "Item 5.02: Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers." in answer
    assert "Sheryl Sandberg" not in answer


def test_render_material_event_answer_merges_multiple_tool_outputs():
    answer = chat_module._render_material_event_answer(
        "What recent 8-K material events has Meta reported since 2024-01-01? List the item codes and explain them briefly.",
        [
            {
                "tool_name": "get_material_events",
                "output": json.dumps(
                    [
                        {
                            "accession_number": "a1",
                            "filing_date": "2024-10-30",
                            "item_code": "2.02",
                            "item": "Item 2.02",
                            "content_type": "earnings",
                            "summary": "Item 2.02 Results of Operations and Financial Condition. Quarterly earnings release.",
                        }
                    ]
                ),
            },
            {
                "tool_name": "get_material_events",
                "output": json.dumps(
                    [
                        {
                            "accession_number": "a2",
                            "filing_date": "2026-04-14",
                            "item_code": "5.02",
                            "item": "Item 5.02",
                            "content_type": "director_change",
                            "summary": "Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers.",
                        }
                    ]
                ),
            },
        ],
    )

    assert answer is not None
    assert "2024-10-30 through 2026-04-14" in answer
    assert "Item 2.02" in answer
    assert "Item 5.02" in answer


def test_render_proxy_statement_answer_uses_latest_snapshot_values():
    answer = chat_module._render_proxy_statement_answer(
        "From Apple's recent proxy statement, what does it report about CEO compensation and pay-versus-performance?",
        [
            {
                "tool_name": "get_proxy_statement_data",
                "output": json.dumps(
                    [
                        {
                            "accession_number": "0001308179-26-000008",
                            "filing_date": "2026-01-08",
                            "peo_name": "Mr. Cook",
                            "peo_total_comp": 74294811,
                            "peo_actually_paid_comp": 108423733,
                            "neo_avg_total_comp": 23812358,
                            "neo_avg_actually_paid_comp": 34125743,
                            "company_selected_measure": "Net Sales",
                            "performance_measures": ["Net Sales", "Operating Income", "Relative TSR"],
                            "pay_vs_performance": [
                                {
                                    "fiscal_year_end": "2025-09-27",
                                    "peo_actually_paid_comp": 108423733,
                                    "total_shareholder_return": 233.88,
                                    "peer_group_tsr": 279.51,
                                    "net_income": 112010000000,
                                    "company_selected_measure_value": 416161000000,
                                }
                            ],
                        }
                    ]
                ),
            }
        ],
    )

    assert answer is not None
    assert "filed 2026-01-08" in answer
    assert "accession 0001308179-26-000008" in answer
    assert "Total compensation: $74.29B" not in answer
    assert "Total compensation: $74.29M" in answer
    assert "Apple's most recent retrieved proxy snapshot" not in answer
    assert "peer group TSR 279.51%" in answer


def test_render_proxy_statement_answer_prefers_latest_snapshot_across_multiple_records():
    answer = chat_module._render_proxy_statement_answer(
        "From Apple's recent proxy statement, what does it report about CEO compensation and pay-versus-performance?",
        [
            {
                "tool_name": "get_proxy_statement_data",
                "output": json.dumps(
                    [
                        {
                            "accession_number": "0001308179-25-000008",
                            "filing_date": "2025-01-10",
                            "peo_name": "Mr. Cook",
                            "peo_total_comp": 74609802,
                            "peo_actually_paid_comp": 168980568,
                            "neo_avg_total_comp": 27178896,
                            "neo_avg_actually_paid_comp": 58633525,
                            "company_selected_measure": "Net Sales",
                            "performance_measures": ["Net Sales", "Operating Income", "Relative TSR"],
                            "pay_vs_performance": [
                                {
                                    "fiscal_year_end": "2024-09-28",
                                    "peo_actually_paid_comp": 168980568,
                                    "total_shareholder_return": 207.59,
                                    "peer_group_tsr": 206.32,
                                    "net_income": 93736000000,
                                    "company_selected_measure_value": 391035000000,
                                }
                            ],
                        },
                        {
                            "accession_number": "0001308179-26-000008",
                            "filing_date": "2026-01-08",
                            "peo_name": "Mr. Cook",
                            "peo_total_comp": 74294811,
                            "peo_actually_paid_comp": 108423733,
                            "neo_avg_total_comp": 23812358,
                            "neo_avg_actually_paid_comp": 34125743,
                            "company_selected_measure": "Net Sales",
                            "performance_measures": ["Net Sales", "Operating Income", "Relative TSR"],
                            "pay_vs_performance": [
                                {
                                    "fiscal_year_end": "2025-09-27",
                                    "peo_actually_paid_comp": 108423733,
                                    "total_shareholder_return": 233.88,
                                    "peer_group_tsr": 279.51,
                                    "net_income": 112010000000,
                                    "company_selected_measure_value": 416161000000,
                                }
                            ],
                        },
                    ]
                ),
            }
        ],
    )

    assert answer is not None
    assert "filed 2026-01-08" in answer
    assert "accession 0001308179-26-000008" in answer
    assert "Actually paid compensation: $108.42M" in answer
    assert "2025-01-10" not in answer.splitlines()[0]


def test_render_institutional_holdings_answer_uses_summary_payload():
    answer = chat_module._render_institutional_holdings_answer(
        "What are Berkshire Hathaway's top holdings in its latest 13F filing, and how concentrated is the portfolio?",
        [
            {
                "tool_name": "summarize_institutional_holdings",
                "output": json.dumps(
                    {
                        "accession_number": "0001193125-26-054580",
                        "filing_date": "2026-02-17",
                        "report_period": "2025-12-31",
                        "total_value": 274160086701,
                        "total_holdings": 110,
                        "distinct_securities": 42,
                        "top_5_concentration_pct": 70.871921,
                        "top_10_concentration_pct": 88.259314,
                        "top_holdings": [
                            {
                                "ticker": "AAPL",
                                "issuer": "APPLE INC",
                                "value": 75111124482,
                                "portfolio_weight_pct": 27.395667,
                            },
                            {
                                "ticker": "GOOGL",
                                "issuer": "ALPHABET INC",
                                "value": 5585842446,
                                "portfolio_weight_pct": 2.037438,
                            },
                        ],
                    }
                ),
            }
        ],
    )

    assert answer is not None
    assert "filed 2026-02-17" in answer
    assert "report period 2025-12-31" in answer
    assert "Total portfolio value: $274.16B" in answer
    assert "Total holdings: 110 positions across 42 distinct securities" in answer
    assert "1. AAPL (APPLE INC): $75.11B (27.40%)" in answer
    assert "2. GOOGL (ALPHABET INC): $5.59B (2.04%)" in answer
    assert "Top 10 holdings: 88.26%" in answer


def test_render_institutional_holdings_answer_prefers_latest_raw_rows_over_stale_summary():
    answer = chat_module._render_institutional_holdings_answer(
        "What are Berkshire Hathaway's top holdings in its latest 13F filing, and how concentrated is the portfolio?",
        [
            {
                "tool_name": "summarize_institutional_holdings",
                "output": json.dumps(
                    {
                        "accession_number": "0000950123-24-011775",
                        "filing_date": "2024-11-14",
                        "report_period": "2024-09-30",
                        "total_value": 266380000000,
                        "total_holdings": 121,
                        "distinct_securities": 40,
                        "top_5_concentration_pct": 70.91,
                        "top_10_concentration_pct": 89.68,
                        "top_holdings": [
                            {
                                "ticker": "AAPL",
                                "issuer": "APPLE INC",
                                "value": 69900000000,
                                "portfolio_weight_pct": 26.24,
                            }
                        ],
                    }
                ),
            },
            {
                "tool_name": "get_institutional_holdings",
                "output": json.dumps(
                    [
                        {
                            "accession_number": "0001193125-26-054580",
                            "filing_date": "2026-02-17",
                            "report_period": "2025-12-31",
                            "manager_name": "Berkshire Hathaway Inc",
                            "manager_cik": 1067983,
                            "filing_signer_name": "Marc D. Hamburg",
                            "filing_signer_title": "Senior Vice President",
                            "total_value": 274160086701,
                            "total_holdings": 110,
                            "issuer": "APPLE INC",
                            "ticker": "AAPL",
                            "value": 61961735283,
                            "portfolio_weight_pct": 22.60056743802233,
                        },
                        {
                            "accession_number": "0001193125-26-054580",
                            "filing_date": "2026-02-17",
                            "report_period": "2025-12-31",
                            "manager_name": "Berkshire Hathaway Inc",
                            "manager_cik": 1067983,
                            "filing_signer_name": "Marc D. Hamburg",
                            "filing_signer_title": "Senior Vice President",
                            "total_value": 274160086701,
                            "total_holdings": 110,
                            "issuer": "AMERICAN EXPRESS CO",
                            "ticker": "AXP",
                            "value": 56088378465,
                            "portfolio_weight_pct": 20.458258216911858,
                        },
                    ]
                ),
            },
        ],
    )

    assert answer is not None
    assert "filed 2026-02-17" in answer
    assert "report period 2025-12-31" in answer
    assert "Total portfolio value: $274.16B" in answer
    assert "1. AAPL (APPLE INC): $61.96B (22.60%)" in answer
    assert "2. AXP (AMERICAN EXPRESS CO): $56.09B (20.46%)" in answer
    assert "2024-11-14" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_meta_insider_and_proxy(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_summarize_insider_sells",
        lambda *args, **kwargs: [
            {
                "insider_name": "Susan J Li",
                "position": "Chief Financial Officer",
                "total_proceeds": 191178706.3865,
                "transaction_count": 53,
                "latest_filing_date": "2026-03-03",
            },
            {
                "insider_name": "Javier Olivan",
                "position": "Chief Operating Officer",
                "total_proceeds": 12100123.0,
                "transaction_count": 4,
                "latest_filing_date": "2026-02-27",
            },
            {
                "insider_name": "Andrew Bosworth",
                "position": "Chief Technology Officer",
                "total_proceeds": 8800123.0,
                "transaction_count": 3,
                "latest_filing_date": "2026-01-17",
            },
            {
                "insider_name": "Christopher Cox",
                "position": "Chief Product Officer",
                "total_proceeds": 6100456.0,
                "transaction_count": 2,
                "latest_filing_date": "2025-11-14",
            },
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_get_proxy_statement_data",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001628280-26-025532",
                "filing_date": "2026-04-16",
                "company_name": "Meta Platforms, Inc.",
                "peo_name": "Mark Zuckerberg",
                "peo_total_comp": 25125904,
                "peo_actually_paid_comp": 25125904,
                "neo_avg_total_comp": 22057420,
            }
        ],
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Since 2024-01-01, have there been notable insider sells at Meta, and "
                "what does the latest proxy statement say about CEO compensation?"
            ),
            ticker="META",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing insider trades", "analyzing proxy statements"]
    assert "requested date range" in answer
    assert "Susan J Li (Chief Financial Officer): total proceeds $191.18M" in answer
    assert "Javier Olivan (Chief Operating Officer): total proceeds $12.10M" in answer
    assert "Andrew Bosworth (Chief Technology Officer): total proceeds $8.80M" in answer
    assert "Christopher Cox (Chief Product Officer): total proceeds $6.10M" in answer
    assert "Meta Platforms, Inc.'s latest retrieved proxy was filed 2026-04-16" in answer
    assert "CEO: Mark Zuckerberg" in answer
    assert "Total compensation: $25.13M" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_latest_proxy_statement_snapshot(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_proxy_statement_data",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001308179-25-000008",
                "filing_date": "2025-01-10",
                "peo_name": "Mr. Cook",
                "peo_total_comp": 74609802,
                "peo_actually_paid_comp": 168980568,
                "neo_avg_total_comp": 27178896,
                "neo_avg_actually_paid_comp": 58633525,
                "company_selected_measure": "Net Sales",
                "performance_measures": ["Net Sales", "Operating Income", "Relative TSR"],
                "pay_vs_performance": [
                    {
                        "fiscal_year_end": "2024-09-28",
                        "peo_actually_paid_comp": 168980568,
                        "total_shareholder_return": 207.59,
                        "peer_group_tsr": 206.32,
                        "net_income": 93736000000,
                        "company_selected_measure_value": 391035000000,
                    }
                ],
            },
            {
                "accession_number": "0001308179-26-000008",
                "filing_date": "2026-01-08",
                "peo_name": "Mr. Cook",
                "peo_total_comp": 74294811,
                "peo_actually_paid_comp": 108423733,
                "neo_avg_total_comp": 23812358,
                "neo_avg_actually_paid_comp": 34125743,
                "company_selected_measure": "Net Sales",
                "performance_measures": ["Net Sales", "Operating Income", "Relative TSR"],
                "pay_vs_performance": [
                    {
                        "fiscal_year_end": "2025-09-27",
                        "peo_actually_paid_comp": 108423733,
                        "total_shareholder_return": 233.88,
                        "peer_group_tsr": 279.51,
                        "net_income": 112010000000,
                        "company_selected_measure_value": 416161000000,
                    }
                ],
            },
        ],
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message="From Apple's recent proxy statement, what does it report about CEO compensation and pay-versus-performance?",
            ticker="AAPL",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing proxy statements"]
    assert "filed 2026-01-08" in answer
    assert "accession 0001308179-26-000008" in answer
    assert "Actually paid compensation: $108.42M" in answer
    assert "peer group TSR 279.51%" in answer
    assert "0001308179-25-000008" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_xom_events_and_cashflow(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_material_events",
        lambda *args, **kwargs: [
            {
                "filing_date": "2026-04-08",
                "item_code": "7.01",
                "item_label": "Item 7.01",
                "content_type": "regulation_fd",
                "summary": "Item 7.01 Regulation FD Disclosure.",
            },
            {
                "filing_date": "2026-03-31",
                "item_code": "8.01",
                "item_label": "Item 8.01",
                "content_type": "debt_offering",
                "summary": "Item 8.01 Other Events.",
            },
            {
                "filing_date": "2026-02-18",
                "item_code": "2.02",
                "item_label": "Item 2.02",
                "content_type": "earnings",
                "summary": "Item 2.02 Results of Operations and Financial Condition.",
            },
            {
                "filing_date": "2026-01-09",
                "item_code": "5.02",
                "item_label": "Item 5.02",
                "content_type": "director_change",
                "summary": "Item 5.02 Departure of Directors or Certain Officers.",
            },
            {
                "filing_date": "2025-12-12",
                "item_code": "1.01",
                "item_label": "Item 1.01",
                "content_type": "material_agreement",
                "summary": "Item 1.01 Entry into a Material Definitive Agreement.",
            },
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_cashflow_timeseries",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "period_end": "2025-12-31",
                    "metric_type": "free_cash_flow",
                    "value": 23612000000.0,
                },
                {
                    "period_end": "2025-12-31",
                    "metric_type": "capex",
                    "value": -28358000000.0,
                },
            ]
        ),
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Have there been any recent 8-K material events for Exxon Mobil in the "
                "last year, and how does its latest annual free cash flow compare with capex?"
            ),
            ticker="XOM",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing 8-K events", "retrieving cash flow data"]
    assert "Yes. Recent retrieved 8-K material events include:" in answer
    assert "2026-04-08: Item 7.01" in answer
    assert "2026-03-31: Item 8.01" in answer
    assert "2026-02-18: Item 2.02" in answer
    assert "2026-01-09: Item 5.02" in answer
    assert "2025-12-12: Item 1.01" in answer
    assert "free cash flow was $23.61B versus capex of $28.36B" in answer
    assert "below capex, covering 83.26% of capex" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_annual_cashflow_summary(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_cashflow_timeseries",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "period_end": "2025-12-31",
                    "metric_type": "operating_cash_flow",
                    "value": 51970000000.0,
                },
                {
                    "period_end": "2025-12-31",
                    "metric_type": "capex",
                    "value": -28358000000.0,
                },
                {
                    "period_end": "2025-12-31",
                    "metric_type": "free_cash_flow",
                    "value": 23612000000.0,
                },
                {
                    "period_end": "2024-12-31",
                    "metric_type": "free_cash_flow",
                    "value": 999.0,
                },
            ]
        ),
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "For Exxon Mobil's most recent annual period only, report operating cash flow, "
                "capex, and free cash flow. Do not include prior years or any extra metrics."
            ),
            ticker="XOM",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["retrieving cash flow data"]
    assert "Operating cash flow: $51.97B" in answer
    assert "Capex: -$28.36B" in answer
    assert "Free cash flow: $23.61B" in answer
    assert "999" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_simple_material_event_prompt(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_material_events",
        lambda *args, **kwargs: [
            {
                "accession_number": "a1",
                "filing_date": "2024-10-30",
                "item_code": "2.02",
                "item": "Item 2.02",
                "content_type": "earnings",
                "summary": "Item 2.02 Results of Operations and Financial Condition. Quarterly earnings release.",
            },
            {
                "accession_number": "a2",
                "filing_date": "2026-04-14",
                "item_code": "5.02",
                "item": "Item 5.02",
                "content_type": "director_change",
                "summary": "Item 5.02 Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers.",
            },
        ],
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "What recent 8-K material events has Meta reported since 2024-01-01? "
                "List the item codes and explain them briefly."
            ),
            ticker="META",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing 8-K events"]
    assert "2024-10-30 through 2026-04-14" in answer
    assert "Item 2.02: Results of Operations and Financial Condition." in answer
    assert "Item 5.02: Departure of Directors or Certain Officers" in answer


@pytest.mark.asyncio
async def test_handle_chat_uses_direct_13f_answer_without_agent(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_summarize_institutional_holdings",
        lambda *args, **kwargs: {
            "accession_number": "0001193125-26-054580",
            "filing_date": "2026-02-17",
            "report_period": "2025-12-31",
            "total_value": 274160086701,
            "total_holdings": 110,
            "distinct_securities": 42,
            "top_5_concentration_pct": 70.871921,
            "top_10_concentration_pct": 88.259314,
            "top_holdings": [
                {
                    "ticker": "AAPL",
                    "issuer": "APPLE INC",
                    "value": 61961735283,
                    "portfolio_weight_pct": 22.60056743802233,
                }
            ],
        },
    )

    def fail_if_agent_runs(*args, **kwargs):
        raise AssertionError("agent path should not run for direct 13F answers")

    monkeypatch.setattr(chat_module.Runner, "run_streamed", fail_if_agent_runs)

    response = await chat_module.handle_chat(
        ChatRequest(
            message=(
                "What are Berkshire Hathaway's top holdings in its latest 13F filing, "
                "and how concentrated is the portfolio?"
            )
        )
    )

    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    body = "".join(chunks)

    assert "analyzing institutional holdings" in body
    assert "filed 2026-02-17 for report period 2025-12-31" in body
    assert "$274.16B" in body
    assert "data: [DONE]" in body


@pytest.mark.asyncio
async def test_try_direct_answer_handles_quarterly_trend_and_ttm(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_quarterly_detail",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "metric_type": "revenue",
                    "Quarter Ended 12/31/2025": 213_386_000_000.0,
                    "Quarter Ended 09/30/2025": 180_169_000_000.0,
                    "Quarter Ended 06/30/2025": 167_702_000_000.0,
                    "Quarter Ended 03/31/2025": 155_667_000_000.0,
                    "Quarter Ended 12/31/2024": 187_792_000_000.0,
                    "Quarter Ended 09/30/2024": 158_877_000_000.0,
                    "Quarter Ended 06/30/2024": 147_977_000_000.0,
                    "Quarter Ended 03/31/2024": 143_313_000_000.0,
                },
                {
                    "metric_type": "net_income",
                    "Quarter Ended 12/31/2025": 21_192_000_000.0,
                    "Quarter Ended 09/30/2025": 21_187_000_000.0,
                    "Quarter Ended 06/30/2025": 18_164_000_000.0,
                    "Quarter Ended 03/31/2025": 17_127_000_000.0,
                    "Quarter Ended 12/31/2024": 20_004_000_000.0,
                    "Quarter Ended 09/30/2024": 15_328_000_000.0,
                    "Quarter Ended 06/30/2024": 13_485_000_000.0,
                    "Quarter Ended 03/31/2024": 10_431_000_000.0,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_ttm_metrics",
        lambda *args, **kwargs: {"free_cash_flow": 7_695_000_000.0},
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Using the last eight quarters, describe this company's revenue trend and latest "
                "trailing-twelve-month free cash flow, and tell me whether the margin picture is improving."
            ),
            ticker="MSFT",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing quarterly financials", "computing trailing-twelve-month metrics"]
    assert "Mar 2024 $143.31B" in answer
    assert "Dec 2025 $213.39B" in answer
    assert "Latest trailing-twelve-month free cash flow was $7.70B" in answer
    assert "quarterly net margin moved from 7.28% in Mar 2024 to 9.93% in Dec 2025" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_bull_bear_without_quarterly_fcf_fabrication(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_quarterly_detail",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "metric_type": "revenue",
                    "Quarter Ended 03/31/2026": 181_519_000_000.0,
                    "Quarter Ended 12/31/2025": 213_386_000_000.0,
                    "Quarter Ended 09/30/2025": 180_169_000_000.0,
                    "Quarter Ended 06/30/2025": 167_702_000_000.0,
                    "Quarter Ended 03/31/2025": 155_667_000_000.0,
                    "Quarter Ended 12/31/2024": 187_792_000_000.0,
                    "Quarter Ended 09/30/2024": 158_877_000_000.0,
                    "Quarter Ended 06/30/2024": 147_977_000_000.0,
                },
                {
                    "metric_type": "net_income",
                    "Quarter Ended 03/31/2026": 30_255_000_000.0,
                    "Quarter Ended 12/31/2025": 21_192_000_000.0,
                    "Quarter Ended 09/30/2025": 21_187_000_000.0,
                    "Quarter Ended 06/30/2025": 18_164_000_000.0,
                    "Quarter Ended 03/31/2025": 17_127_000_000.0,
                    "Quarter Ended 12/31/2024": 20_004_000_000.0,
                    "Quarter Ended 09/30/2024": 15_328_000_000.0,
                    "Quarter Ended 06/30/2024": 13_485_000_000.0,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_ttm_metrics",
        lambda *args, **kwargs: {"free_cash_flow": -2_472_000_000.0},
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Using this company's last eight quarters plus its latest trailing-twelve-month free cash flow, "
                "give one bull datapoint and one bear datapoint. Cite the specific quarter or TTM figure for each."
            ),
            ticker="MSFT",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing quarterly financials", "computing trailing-twelve-month metrics"]
    assert "Bull datapoint: Quarter ended March 31, 2026 generated $30.25B of net income" in answer
    assert "16.67% net margin" in answer
    assert "Bear datapoint: Latest trailing-twelve-month free cash flow was -$2.47B." in answer
    assert "$17.80B" not in answer
    assert "-$18.17B" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_ttm_revenue_and_net_income_snapshot(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_ttm_metrics",
        lambda *args, **kwargs: {"revenue": 451_442_000_000.0, "net_income": 122_575_000_000.0},
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message="What are Apple's latest trailing-twelve-month revenue and net income? Answer with the figures and a short interpretation.",
            ticker="AAPL",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["computing trailing-twelve-month metrics"]
    assert "$451.44B" in answer
    assert "$122.58B" in answer
    assert "27.15%" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_nvda_latest_10k_risk_themes(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001045810-26-000021",
                "filing_date": "2026-02-25",
            }
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filing_section",
        lambda *args, **kwargs: {
            "heading": "Item 1A. Risk Factors",
            "content": """
#### Risk Factors Summary
Risks Related to Our Industry and Markets
- Failure to meet the evolving needs of our industry and markets may adversely impact our financial results.
- Competition could adversely impact our market share and financial results.
Risks Related to Demand, Supply, and Manufacturing
- Long manufacturing lead times and uncertain supply and capacity availability, combined with a failure to estimate customer demand accurately has led and could lead to mismatches between supply and demand.
- Dependency on third-party suppliers and their technology to manufacture, assemble, test, or package our products reduces our control over product quantity and quality.
## Item 1B. Unresolved Staff Comments
""",
        },
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message="From NVIDIA's latest 10-K, what are two risk themes management highlights? Cite the accession number.",
            ticker="NVDA",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["searching filings", "reading SEC filings"]
    assert "accession number 0001045810-26-000021" in answer
    assert "Risks Related to Our Industry and Markets" in answer
    assert "Failure to meet the evolving needs of our industry and markets" in answer
    assert "Risks Related to Demand, Supply, and Manufacturing" in answer
    assert "Long manufacturing lead times and uncertain supply and capacity availability" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_latest_10k_mdna_highlights(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0000320193-25-000073",
                "filing_date": "2025-11-01",
            }
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filing_section",
        lambda *args, **kwargs: {
            "heading": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            "content": """
### Executive Overview
Net sales grew due to Services strength and improved iPhone demand.

### Liquidity and Capital Resources
The company returned substantial capital to shareholders while maintaining a strong net cash position.
""",
        },
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message="In Apple's latest 10-K MD&A, what are two management highlights? Cite the accession number.",
            ticker="AAPL",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["searching filings", "reading SEC filings"]
    assert "accession number 0000320193-25-000073" in answer
    assert "Executive Overview" in answer
    assert "Net sales grew due to Services strength and improved iPhone demand." in answer
    assert "Liquidity and Capital Resources" in answer
    assert "returned substantial capital to shareholders" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_recent_beneficial_ownership_filings(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_beneficial_ownership",
        lambda *args, **kwargs: [
            {
                "filing_date": "2026-04-30",
                "form_type": "SCHEDULE 13G",
                "issuer_name": "Warner Bros Discovery Inc",
                "total_percent": 7.22,
            },
            {
                "filing_date": "2026-03-27",
                "form_type": "SCHEDULE 13G/A",
                "issuer_name": "Warner Bros Discovery Inc",
                "total_percent": 0,
            },
            {
                "filing_date": "2025-12-17",
                "form_type": "SCHEDULE 13D/A",
                "issuer_name": "Anghami Inc",
                "total_percent": 71.3,
            },
        ],
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Since 2025-01-01, what recent beneficial ownership filings has Warner Bros. Discovery had? "
                "List the form type, filing date, and reported ownership percentage for the recent filings."
            ),
            ticker="WBD",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["analyzing beneficial ownership filings"]
    assert "2026-04-30 — SCHEDULE 13G — reported ownership 7.22%" in answer
    assert "2026-03-27 — SCHEDULE 13G/A — reported ownership 0%" in answer
    assert "Anghami" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_latest_beneficial_ownership_snapshot(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_summarize_beneficial_ownership",
        lambda *args, **kwargs: {
            "issuer_name": "Palantir Technologies Inc",
            "latest_accession_number": "0002100119-26-000893",
            "latest_form_type": "SCHEDULE 13G",
            "latest_filing_date": "2026-04-30",
            "latest_total_percent": 7.28,
            "latest_reporting_person_names": ["Vanguard Capital Management"],
            "latest_rule_designation": "Rule 13d-1(b)",
            "latest_is_passive_investor": True,
        },
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "What does Palantir's latest beneficial ownership filing say about the filer, "
                "the reported ownership percentage, and whether the position is passive or activist?"
            ),
            ticker="PLTR",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["summarizing beneficial ownership filings"]
    assert "filed 2026-04-30" in answer
    assert "accession 0002100119-26-000893" in answer
    assert "Filer: Vanguard Capital Management" in answer
    assert "Reported ownership percentage: 7.28%" in answer
    assert "Passive or activist: Passive (Rule 13d-1(b))." in answer
    assert "Surf Air" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_latest_8k_section_list_with_empty_sections(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001193125-26-194086",
                "filing_date": "2026-04-30",
            }
        ],
    )
    monkeypatch.setattr(chat_module, "analytics_get_filing_sections", lambda *args, **kwargs: [])

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "What item sections are included in Walmart's latest 8-K? "
                "Give the accession number and list the item codes with their headings."
            ),
            ticker="WMT",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["searching filings", "mapping filing sections"]
    assert "accession number 0001193125-26-194086" in answer
    assert "did not retrieve any parsed item sections" in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_growth_and_margin_trend(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_growth_rates",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"period_end": "2025-09-27", "revenue": 6.425511782832749},
                {"period_end": "2024-09-28", "revenue": 2.021994077514111},
                {"period_end": "2023-09-30", "revenue": -2.800460530319937},
                {"period_end": "2022-09-24", "revenue": 7.79378760418461},
            ]
        ).set_index("period_end"),
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_ratio_timeseries",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"period_end": "2025-09-27", "ratio_name": "net_profit_margin", "value": 0.2691506412181824},
                {"period_end": "2024-09-28", "ratio_name": "net_profit_margin", "value": 0.23971255769943867},
                {"period_end": "2023-09-30", "ratio_name": "net_profit_margin", "value": 0.2530623426432028},
                {"period_end": "2022-09-24", "ratio_name": "net_profit_margin", "value": 0.2530964070519973},
            ]
        ),
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "How have Apple's revenue growth and net profit margin changed over the last four annual periods? "
                "Give the direction and the numbers."
            ),
            ticker="AAPL",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["retrieving financial time series", "computing ratio trends"]
    assert "2022-09-24: 7.79%" in answer
    assert "2025-09-27: 6.43%" in answer
    assert "2024-09-28: 23.97%" in answer
    assert "$394.33B" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_latest_10k_search_prompt(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0000320187-25-000047",
                "filing_date": "2025-07-17",
            }
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_search_filing_text",
        lambda *args, **kwargs: [
            {
                "item_code": "1",
                "heading": "Item 1. Business",
                "excerpt": "Greater China is listed as a reportable operating segment.",
            },
            {
                "item_code": "1",
                "heading": "Item 1. Business",
                "excerpt": "For fiscal 2025, factories in China manufactured approximately 17% of total NIKE Brand footwear and 15% of total NIKE Brand apparel.",
            },
            {
                "item_code": "7",
                "heading": "Item 7. Management's Discussion and Analysis",
                "excerpt": "Greater China revenues were $6,586 million in fiscal 2025, a 13% reported decrease and a 12% currency-neutral decrease from fiscal 2024.",
            },
        ],
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "In Nike's latest 10-K, what does management mention about China? "
                "Cite the accession number and the section where the match appears."
            ),
            ticker="NKE",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["searching filings", "searching filing text"]
    assert "accession number 0000320187-25-000047" in answer
    assert 'Retrieved matches for "China" appear in:' in answer
    assert "Item 1. Business" in answer
    assert "17% of total NIKE Brand footwear" in answer
    assert "Item 7. Management's Discussion and Analysis" in answer
    assert "6,586 million in fiscal 2025" in answer
    assert "Item 1A" not in answer
    assert "Shanghai" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_risk_factor_section_comparison(monkeypatch):
    monkeypatch.setattr(
        chat_module,
        "analytics_get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001628280-26-008432",
                "filing_date": "2026-02-17",
            }
        ],
    )
    monkeypatch.setattr(
        chat_module,
        "analytics_compare_filing_sections",
        lambda *args, **kwargs: {
            "current_filing": {"accession_number": "0001628280-26-008432"},
            "previous_filing": {"accession_number": "0001090727-25-000019"},
            "current_only_excerpts": [
                "Changes or continued uncertainty in general economic conditions may adversely affect us."
            ],
        },
    )

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "How did UPS's latest annual risk factor section change versus the prior annual filing? "
                "Identify one new emphasis and cite both accession numbers."
            ),
            ticker="UPS",
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["searching filings", "comparing filing sections"]
    assert "0001628280-26-008432" in answer
    assert "0001090727-25-000019" in answer
    assert "continued uncertainty in general economic conditions" in answer
    assert "Paris Climate" not in answer


@pytest.mark.asyncio
async def test_try_direct_answer_handles_cross_company_fcf_ranking(monkeypatch):
    def fake_cashflow(symbol, period_type):
        values = {
            "AAPL": 98_767_000_000.0,
            "NVDA": 96_676_000_000.0,
            "XOM": 23_612_000_000.0,
        }
        return pd.DataFrame(
            [
                {
                    "period_end": "2025-12-31",
                    "metric_type": "free_cash_flow",
                    "value": values[symbol],
                }
            ]
        )

    monkeypatch.setattr(chat_module, "analytics_cashflow_timeseries", fake_cashflow)

    result = await chat_module._try_direct_answer(
        ChatRequest(
            message=(
                "Using only the latest annual free cash flow values, rank AAPL, NVDA, and XOM "
                "from highest to lowest. Provide only the ranking and the free cash flow figure for each company, with no extra metrics or commentary."
            )
        )
    )

    assert result is not None
    progress_messages, answer = result
    assert progress_messages == ["comparing companies", "retrieving cash flow data"]
    assert answer == "1. AAPL — $98.77B\n2. NVDA — $96.68B\n3. XOM — $23.61B"


def test_tool_guidance_messages_add_latest_proxy_and_13f_hints():
    proxy_guidance = chat_module._tool_guidance_messages(
        ChatRequest(
            message="From Apple's recent proxy statement, what does it report about CEO compensation and pay-versus-performance?",
            ticker="AAPL",
        )
    )
    holdings_guidance = chat_module._tool_guidance_messages(
        ChatRequest(
            message="What are Berkshire Hathaway's top holdings in its latest 13F filing, and how concentrated is the portfolio?",
        )
    )

    assert any("Normalized research intent: latest_proxy_statement" in message["content"] for message in proxy_guidance)
    assert any("get_proxy_statement_data with limit=1" in message["content"] for message in proxy_guidance)
    assert any("Normalized research intent: latest_institutional_holdings" in message["content"] for message in holdings_guidance)
    assert any("the manager or filer named in the question" in message["content"] for message in holdings_guidance)


def test_normalize_optional_str_list_handles_empty_sentinels():
    assert agent_tools_module._normalize_optional_str_list("") is None
    assert agent_tools_module._normalize_optional_str_list("None") is None
    assert agent_tools_module._normalize_optional_str_list(["", "5.02", "  "]) == ["5.02"]
