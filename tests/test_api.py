"""Tests for the FastAPI backend — verifies API endpoints return expected shapes.

Uses ``httpx.AsyncClient`` + ``pytest-asyncio`` for proper async transport.
These tests hit the **real DuckDB** so they are integration tests
(require ``data/duckdb/financial_timeseries.duckdb``).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from investment_researcher.web.app import app


@pytest_asyncio.fixture(scope="module")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Company endpoints ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_returns_list(client: AsyncClient):
    resp = await client.get("/api/companies/search", params={"q": "AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["ticker"] == "AAPL" for r in data)


@pytest.mark.asyncio
async def test_search_empty_query(client: AsyncClient):
    resp = await client.get("/api/companies/search", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_company_profile(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert "latest_metrics" in data


@pytest.mark.asyncio
async def test_all_tickers(client: AsyncClient):
    resp = await client.get("/api/companies")
    assert resp.status_code == 200
    tickers = resp.json()
    assert isinstance(tickers, list)
    assert "AAPL" in tickers


# ── Financials endpoints ───────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("tab", ["income", "balance", "cashflow", "growth", "kpi"])
async def test_financials_tabs(client: AsyncClient, tab: str):
    resp = await client.get(f"/api/companies/AAPL/financials", params={"tab": tab})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_income_pivot_shape(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "income"})
    data = resp.json()
    pivot = data["pivot"]
    assert "index" in pivot and "columns" in pivot and "data" in pivot
    assert len(pivot["index"]) > 0, "Should have at least one period"
    assert len(pivot["columns"]) > 0, "Should have at least one metric"
    assert len(pivot["data"]) == len(pivot["index"]), "One data row per period"


@pytest.mark.asyncio
async def test_cashflow_includes_derived_free_cash_flow(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "cashflow"})
    assert resp.status_code == 200

    data = resp.json()
    pivot = data["pivot"]
    assert "free_cash_flow" in pivot["columns"]

    latest_row = pivot["data"][-1]
    latest = dict(zip(pivot["columns"], latest_row))
    assert latest["capex"] < 0
    assert latest["free_cash_flow"] == latest["operating_cash_flow"] + latest["capex"]
    assert latest["free_cash_flow"] < latest["operating_cash_flow"]

    metric_names = {record["metric_type"] for record in data["timeseries"]}
    assert "free_cash_flow" in metric_names


@pytest.mark.asyncio
async def test_growth_shape(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "growth"})
    data = resp.json()
    assert "growth" in data
    assert isinstance(data["growth"], list)
    if data["growth"]:
        rec = data["growth"][0]
        assert "period_end" in rec, "Growth records must have period_end"
    assert "margins_pivot" in data
    assert "earnings_quality" in data


@pytest.mark.asyncio
async def test_kpi_shape(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "kpi"})
    data = resp.json()
    assert "summary" in data
    assert isinstance(data["summary"], list)
    if data["summary"]:
        rec = data["summary"][0]
        assert "metric_type" in rec and "value" in rec


@pytest.mark.asyncio
async def test_invalid_tab_returns_400(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "nope"})
    assert resp.status_code == 400


# ── Ratios endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ratios(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials/ratios")
    assert resp.status_code == 200
    data = resp.json()
    assert "latest" in data
    assert "wide" in data
    assert "ttm" in data
    assert "categories" in data
    assert isinstance(data["categories"], dict)


# ── Health endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "ratios_latest" in data
    assert "ratios_ttm" in data
    assert "revenue_growth" in data
    assert isinstance(data["revenue_growth"], list)


# ── Quarterly endpoint ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quarterly(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/financials/quarterly")
    assert resp.status_code == 200
    data = resp.json()
    assert "quarterly" in data
    qd = data["quarterly"]
    assert "index" in qd and "columns" in qd
    assert len(qd["data"]) > 0, "Should have quarterly data"


# ── Filings endpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filings(client: AsyncClient):
    resp = await client.get("/api/companies/AAPL/filings", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        f = data[0]
        assert "accession_number" in f
        assert "form_type" in f
        assert "filing_date" in f


@pytest.mark.asyncio
async def test_rerun_slow_path_endpoint(client: AsyncClient, monkeypatch):
    captured = {}

    def fake_rerun(tickers):
        captured["tickers"] = tickers
        return [
            {
                "ticker": "AMZN",
                "deleted_rows": 10,
                "deleted_state_rows": 1,
                "written_rows": 25,
            }
        ]

    monkeypatch.setattr("investment_researcher.web.app.initialize_db", lambda: None)
    monkeypatch.setattr("investment_researcher.web.app.initialize_state_db", lambda: None)
    monkeypatch.setattr("investment_researcher.web.app.rerun_slow_path_for_companies", fake_rerun)

    resp = await client.post(
        "/api/companies/slow-path/rerun",
        json={"tickers": ["amzn", " "]},
    )

    assert resp.status_code == 200
    assert captured["tickers"] == ["AMZN"]
    payload = resp.json()
    assert payload["tickers"] == ["AMZN"]
    assert payload["total_deleted_rows"] == 10
    assert payload["total_written_rows"] == 25


@pytest.mark.asyncio
async def test_rerun_slow_path_requires_tickers(client: AsyncClient):
    resp = await client.post("/api/companies/slow-path/rerun", json={"tickers": []})
    assert resp.status_code == 400


# ── JSON serialization (no NaN/Inf) ───────────────────────────────


@pytest.mark.asyncio
async def test_no_nan_in_response(client: AsyncClient):
    """Verify that NaN and Inf are replaced with null in JSON output."""
    resp = await client.get("/api/companies/AAPL/financials", params={"tab": "income"})
    raw = resp.text
    assert "NaN" not in raw, "Response must not contain raw NaN"
    assert "Infinity" not in raw, "Response must not contain Infinity"


# ── Cross-company validation ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["AAPL", "NVDA", "UNH", "WMT", "XOM"])
async def test_multi_company_kpi(client: AsyncClient, ticker: str):
    """Income and KPI endpoints return data for every golden company."""
    resp = await client.get(f"/api/companies/{ticker}/financials", params={"tab": "kpi"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["summary"]) > 0, f"No KPI summary for {ticker}"
