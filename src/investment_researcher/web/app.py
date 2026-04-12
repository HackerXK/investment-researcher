"""FastAPI backend — REST API for the Investment Researcher web UI.

Endpoints mirror the contract in ``05-tech-stack.md § API Contract``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from investment_researcher.analytics import (
    get_all_tickers,
    get_company_profile,
    get_filings_list,
    get_filing_text,
    get_ratios_by_category,
    get_ratios_latest,
    get_ratios_ttm,
    get_ratios_wide,
    growth_rates,
    metric_timeseries,
    pivot_metrics,
    quarterly_detail,
    search_companies,
    ticker_summary,
    ttm_metrics,
)
from investment_researcher.ingestion.edgar.financials import rerun_slow_path_for_companies
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.timeseries import initialize_db
from investment_researcher.web.chat import ChatRequest, handle_chat

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Investment Researcher API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(obj: Any) -> Any:
    """Replace NaN / Inf with None so JSON serialization works."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    return obj


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe list of dicts."""
    if df is None or df.empty:
        return []
    records = df.reset_index().to_dict(orient="records")
    return _sanitize(records)


def _df_to_wide(df: pd.DataFrame) -> dict[str, Any]:
    """Convert wide-form DataFrame to {index: [...], columns: [...], data: [...]}."""
    if df is None or df.empty:
        return {"index": [], "columns": [], "data": []}
    idx = [str(i) for i in df.index.tolist()]
    cols = list(df.columns)
    data = _sanitize(df.values.tolist())
    return {"index": idx, "columns": cols, "data": data}


class SlowPathRerunRequest(BaseModel):
    tickers: list[str]


# ---------------------------------------------------------------------------
# Company Search & Profile
# ---------------------------------------------------------------------------


@app.get("/api/companies/search")
def api_search(q: str = Query("", min_length=0), limit: int = Query(20, ge=1, le=100)):
    if not q.strip():
        return []
    return _sanitize(search_companies(q, limit=limit))


@app.get("/api/companies")
def api_all_tickers():
    return get_all_tickers()


@app.get("/api/companies/{ticker}")
def api_company_profile(ticker: str):
    profile = get_company_profile(ticker.upper())
    if not profile:
        raise HTTPException(404, "Company not found")
    return _sanitize(profile)


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------

# Income Statement metrics
_INCOME_METRICS = [
    "revenue", "cost_of_revenue", "gross_profit",
    "operating_expenses", "research_and_development",
    "depreciation_and_amortization", "operating_income",
    "interest_expense", "income_tax_expense", "net_income",
    "eps_basic", "eps_diluted",
]

# Balance Sheet metrics
_BALANCE_METRICS = [
    "total_assets", "total_current_assets", "cash",
    "accounts_receivable", "inventory", "goodwill", "intangible_assets",
    "total_liabilities", "total_current_liabilities",
    "accounts_payable", "short_term_debt", "long_term_debt",
    "stockholders_equity", "retained_earnings",
]

# Cash Flow metrics
_CASHFLOW_METRICS = [
    "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    "capex", "dividends_paid",
]

# Key metrics for KPI cards
_KEY_METRICS = [
    "revenue", "net_income", "eps_diluted", "common_shares_outstanding",
]

# Growth metrics
_GROWTH_METRICS = ["revenue", "gross_profit", "operating_income", "net_income"]


@app.get("/api/companies/{ticker}/financials")
def api_financials(
    ticker: str,
    tab: str = Query("income"),
    period_type: str = Query("annual"),
):
    ticker = ticker.upper()
    if tab == "income":
        ts = metric_timeseries(ticker, _INCOME_METRICS, period_type)
        piv = pivot_metrics(ticker, _INCOME_METRICS, period_type)
        return _sanitize({
            "timeseries": _df_to_records(ts),
            "pivot": _df_to_wide(piv),
        })
    elif tab == "balance":
        piv = pivot_metrics(ticker, _BALANCE_METRICS, period_type)
        return _sanitize({"pivot": _df_to_wide(piv)})
    elif tab == "cashflow":
        ts = metric_timeseries(ticker, _CASHFLOW_METRICS, period_type)
        piv = pivot_metrics(ticker, _CASHFLOW_METRICS, period_type)
        return _sanitize({
            "timeseries": _df_to_records(ts),
            "pivot": _df_to_wide(piv),
        })
    elif tab == "growth":
        g = growth_rates(ticker, _GROWTH_METRICS, period_type)
        margin_metrics = ["revenue", "gross_profit", "operating_income", "net_income"]
        piv = pivot_metrics(ticker, margin_metrics, period_type)
        eq = pivot_metrics(ticker, ["net_income", "operating_cash_flow"], period_type)
        return _sanitize({
            "growth": _df_to_records(g),
            "margins_pivot": _df_to_wide(piv),
            "earnings_quality": _df_to_wide(eq),
        })
    elif tab == "kpi":
        summary = ticker_summary(ticker, period_type)
        gr = growth_rates(ticker, _KEY_METRICS, period_type)
        ttm = ttm_metrics(ticker, _KEY_METRICS)
        return _sanitize({
            "summary": _df_to_records(summary),
            "growth": _df_to_records(gr),
            "ttm": ttm,
        })
    else:
        raise HTTPException(400, f"Unknown tab: {tab}")


@app.get("/api/companies/{ticker}/financials/ratios")
def api_ratios(ticker: str, period_type: str = Query("annual")):
    ticker = ticker.upper()
    latest = get_ratios_latest(ticker, period_type)
    wide = get_ratios_wide(ticker, period_type)
    ttm = get_ratios_ttm(ticker)
    categories = {
        cat: [
            {"name": r.name, "display_format": r.display_format}
            for r in defs
        ]
        for cat, defs in get_ratios_by_category().items()
    }
    return _sanitize({
        "latest": latest,
        "wide": _df_to_wide(wide),
        "ttm": ttm,
        "categories": categories,
    })


@app.get("/api/companies/{ticker}/financials/health")
def api_health(ticker: str, period_type: str = Query("annual")):
    ticker = ticker.upper()
    latest = get_ratios_latest(ticker, period_type)
    ttm = get_ratios_ttm(ticker)
    rev_growth = growth_rates(ticker, ["revenue"], "annual")
    gr_records = _df_to_records(rev_growth)
    return _sanitize({
        "ratios_latest": latest,
        "ratios_ttm": ttm,
        "revenue_growth": gr_records,
    })


@app.get("/api/companies/{ticker}/financials/quarterly")
def api_quarterly(
    ticker: str,
    n_quarters: int = Query(10, ge=1, le=20),
):
    ticker = ticker.upper()
    qd_metrics = [
        "revenue", "cost_of_revenue", "gross_profit",
        "operating_expenses", "operating_income",
        "income_tax_expense", "interest_expense", "net_income",
        "eps_basic", "eps_diluted",
        "common_shares_outstanding", "dividends_paid",
        "research_and_development", "depreciation_and_amortization",
    ]
    qd = quarterly_detail(ticker, qd_metrics, n_quarters=n_quarters)
    return _sanitize({"quarterly": _df_to_wide(qd)})


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------


@app.get("/api/companies/{ticker}/filings")
def api_filings(
    ticker: str,
    form_type: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
):
    return _sanitize(get_filings_list(ticker.upper(), form_type, limit))


@app.get("/api/companies/{ticker}/filings/{accession}")
def api_filing_text(ticker: str, accession: str):
    text = get_filing_text(ticker.upper(), accession)
    if not text:
        raise HTTPException(404, "Filing not found")
    return {"accession_number": accession, "text": text}


@app.post("/api/companies/slow-path/rerun")
def api_rerun_slow_path(request: SlowPathRerunRequest):
    tickers = [t.strip().upper() for t in request.tickers if t and t.strip()]
    if not tickers:
        raise HTTPException(400, "At least one ticker is required")

    initialize_db()
    initialize_state_db()
    results = rerun_slow_path_for_companies(tickers)
    return _sanitize(
        {
            "results": results,
            "tickers": [r["ticker"] for r in results],
            "total_deleted_rows": sum(int(r["deleted_rows"]) for r in results),
            "total_written_rows": sum(int(r["written_rows"]) for r in results),
        }
    )


# ---------------------------------------------------------------------------
# Chat (SSE)
# ---------------------------------------------------------------------------


@app.post("/api/chat")
async def api_chat(request: ChatRequest):
    return await handle_chat(request)
