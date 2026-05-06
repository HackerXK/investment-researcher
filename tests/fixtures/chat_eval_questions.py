"""Curated question corpus for live chat evaluation.

The corpus is intentionally mixed between straightforward single-tool prompts
and multi-tool synthesis prompts so the live harness can exercise both the
agent's basic retrieval behavior and its more complex planning paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatEvalQuestion:
    """One live chat evaluation case."""

    question_id: str
    title: str
    prompt: str
    ticker: str | None = None
    difficulty: str = "simple"
    expected_tools: tuple[str, ...] = ()
    evidence_kind: str = ""
    evidence_params: dict[str, Any] = field(default_factory=dict)
    must_cover: tuple[str, ...] = ()
    evaluation_focus: tuple[str, ...] = ()
    smoke: bool = False
    chat_timeout_seconds: int = 300
    evaluation_timeout_seconds: int = 300
    notes: str = ""


CHAT_EVAL_QUESTIONS: tuple[ChatEvalQuestion, ...] = (
    ChatEvalQuestion(
        question_id="aapl-ttm-revenue-net-income",
        title="AAPL TTM revenue and net income",
        ticker="AAPL",
        prompt=(
            "What are Apple's latest trailing-twelve-month revenue and net income? "
            "Answer with the figures and a short interpretation."
        ),
        difficulty="simple",
        expected_tools=("get_ttm_metrics",),
        evidence_kind="ttm_metrics",
        evidence_params={"ticker": "AAPL", "metrics": ["revenue", "net_income"]},
        must_cover=("revenue", "net income"),
        smoke=True,
        notes="Single-tool financial snapshot using TTM metrics.",
    ),
    ChatEvalQuestion(
        question_id="nvda-latest-annual-ratios",
        title="NVDA latest annual profitability ratios",
        ticker="NVDA",
        prompt=(
            "What are NVIDIA's latest annual gross profit margin, operating margin, "
            "and return on equity?"
        ),
        difficulty="simple",
        expected_tools=("get_latest_ratios",),
        evidence_kind="latest_ratios",
        evidence_params={
            "ticker": "NVDA",
            "period_type": "annual",
            "ratio_names": [
                "gross_profit_margin",
                "operating_profit_margin",
                "return_on_equity",
            ],
        },
        must_cover=("gross profit margin", "operating margin", "return on equity"),
        smoke=True,
        notes="Straightforward ratio lookup using the latest annual snapshot.",
    ),
    ChatEvalQuestion(
        question_id="xom-annual-cash-flow-summary",
        title="XOM annual cash flow summary",
        ticker="XOM",
        prompt=(
            "For Exxon Mobil's most recent annual period only, report operating cash flow, "
            "capex, and free cash flow. Do not include prior years or any extra metrics."
        ),
        difficulty="simple",
        expected_tools=("get_cashflow_pivot",),
        evidence_kind="cashflow_summary",
        evidence_params={"ticker": "XOM", "period_type": "annual"},
        must_cover=("operating cash flow", "capex", "free cash flow"),
        smoke=True,
        notes="Single-tool cash flow summary from statement-style output.",
    ),
    ChatEvalQuestion(
        question_id="meta-recent-8k-events",
        title="META recent 8-K events",
        ticker="META",
        prompt=(
            "What recent 8-K material events has Meta reported since 2024-01-01? "
            "List the item codes and explain them briefly."
        ),
        difficulty="simple",
        expected_tools=("get_material_events",),
        evidence_kind="material_events",
        evidence_params={
            "ticker": "META",
            "start_date": "2024-01-01",
            "limit": 50,
        },
        must_cover=("item", "8-K"),
        evaluation_focus=("staleness_handling",),
        notes="Structured SEC events question that avoids raw filing scraping.",
    ),
    ChatEvalQuestion(
        question_id="aapl-proxy-ceo-compensation",
        title="AAPL proxy CEO compensation snapshot",
        ticker="AAPL",
        prompt=(
            "From Apple's recent proxy statement, what does it report about CEO "
            "compensation and pay-versus-performance?"
        ),
        difficulty="simple",
        expected_tools=("get_proxy_statement_data",),
        evidence_kind="proxy_statement",
        evidence_params={
            "ticker": "AAPL",
            "limit": 1,
            "proxy_start_date": "2024-01-01",
        },
        must_cover=("CEO compensation", "pay-versus-performance"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Structured proxy-statement question grounded in DEF 14A data.",
    ),
    ChatEvalQuestion(
        question_id="brk-top-13f-holdings",
        title="Berkshire top holdings from 13F",
        prompt=(
            "What are Berkshire Hathaway's top holdings in its latest 13F filing, "
            "and how concentrated is the portfolio?"
        ),
        difficulty="simple",
        expected_tools=("summarize_institutional_holdings",),
        evidence_kind="institutional_holdings_summary",
        evidence_params={"manager": "BRK-B", "top_n": 10},
        must_cover=("top holdings", "concentration"),
        notes="13F concentration question; keep out of smoke mode because availability depends on local cache.",
    ),
    ChatEvalQuestion(
        question_id="pltr-latest-beneficial-ownership-snapshot",
        title="PLTR latest beneficial ownership snapshot",
        ticker="PLTR",
        prompt=(
            "What does Palantir's latest beneficial ownership filing say about the filer, "
            "the reported ownership percentage, and whether the position is passive or activist?"
        ),
        difficulty="simple",
        expected_tools=("summarize_beneficial_ownership",),
        evidence_kind="beneficial_ownership_summary",
        evidence_params={"ticker": "PLTR", "limit": 10},
        must_cover=("filer", "ownership percentage", "passive or activist"),
        notes="Single-tool Schedule 13D/13G summary for a large but non-megacap software company.",
    ),
    ChatEvalQuestion(
        question_id="para-recent-beneficial-ownership-filings",
        title="WBD recent beneficial ownership filings",
        ticker="WBD",
        prompt=(
            "Since 2025-01-01, what recent beneficial ownership filings has Warner Bros. Discovery had? "
            "List the form type, filing date, and reported ownership percentage for the recent filings."
        ),
        difficulty="medium",
        expected_tools=("get_beneficial_ownership",),
        evidence_kind="beneficial_ownership_rows",
        evidence_params={
            "ticker": "WBD",
            "start_date": "2025-01-01",
            "limit": 5,
        },
        must_cover=("form type", "filing date", "ownership percentage"),
        notes="Longer-range Schedule 13D/13G history for a media company with the current WBD ticker.",
    ),
    ChatEvalQuestion(
        question_id="wmt-latest-8k-section-list",
        title="WMT latest 8-K section list",
        ticker="WMT",
        prompt=(
            "What item sections are included in Walmart's latest 8-K? Give the accession number "
            "and list the item codes with their headings."
        ),
        difficulty="medium",
        expected_tools=("list_filings", "list_filing_sections"),
        evidence_kind="latest_filing_sections",
        evidence_params={
            "ticker": "WMT",
            "form_type": "8-K",
            "limit": 1,
            "include_amendments": False,
        },
        must_cover=("accession number", "item codes", "headings"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Section-discovery question for a recent retail 8-K.",
    ),
    ChatEvalQuestion(
        question_id="unh-latest-10k-risk-section",
        title="UNH latest 10-K risk section",
        ticker="UNH",
        prompt=(
            "In UnitedHealth's latest 10-K Item 1A, what are two risk themes management highlights? "
            "Cite the accession number."
        ),
        difficulty="medium",
        expected_tools=("list_filings", "list_filing_sections", "read_filing_section"),
        evidence_kind="latest_filing_section",
        evidence_params={
            "ticker": "UNH",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "risk factors",
            "include_amendments": False,
        },
        must_cover=("two risk themes", "accession number"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Targeted Item 1A section-read question for a healthcare megacap.",
    ),
    ChatEvalQuestion(
        question_id="aapl-latest-10k-mdna-highlights",
        title="AAPL latest 10-K MD&A highlights",
        ticker="AAPL",
        prompt=(
            "In Apple's latest 10-K MD&A, what are two management highlights? "
            "Cite the accession number."
        ),
        difficulty="medium",
        expected_tools=("list_filings", "list_filing_sections", "read_filing_section"),
        evidence_kind="latest_filing_section",
        evidence_params={
            "ticker": "AAPL",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "mda",
            "include_amendments": False,
        },
        must_cover=("two highlights", "accession number"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Targeted MD&A section-read question for a large-cap hardware and services company.",
    ),
    ChatEvalQuestion(
        question_id="nke-latest-10k-china-search",
        title="NKE latest 10-K China search",
        ticker="NKE",
        prompt=(
            "In Nike's latest 10-K, what does management mention about China? "
            "Cite the accession number and the section where the match appears."
        ),
        difficulty="medium",
        expected_tools=("list_filings", "search_filing_text"),
        evidence_kind="latest_filing_search",
        evidence_params={
            "ticker": "NKE",
            "form_type": "10-K",
            "limit": 1,
            "query": "China",
            "max_matches": 5,
            "include_amendments": False,
        },
        must_cover=("China", "accession number", "section"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Search-oriented filing question for a global consumer brand.",
    ),
    ChatEvalQuestion(
        question_id="aapl-growth-and-margin-trend",
        title="AAPL growth and margin trend",
        ticker="AAPL",
        prompt=(
            "How have Apple's revenue growth and net profit margin changed over the "
            "last four annual periods? Give the direction and the numbers."
        ),
        difficulty="complex",
        expected_tools=("get_growth_rates", "get_ratio_timeseries"),
        evidence_kind="growth_and_ratio_trend",
        evidence_params={
            "ticker": "AAPL",
            "metrics": ["revenue"],
            "ratio_names": ["net_profit_margin"],
            "period_type": "annual",
        },
        must_cover=("revenue growth", "net profit margin"),
        evaluation_focus=("multi_hop_reasoning", "confidence_calibration"),
        notes="Two-tool synthesis across revenue growth and profitability trend.",
    ),
    ChatEvalQuestion(
        question_id="amzn-quarterly-trend-and-ttm-fcf",
        title="AMZN quarterly trend and TTM free cash flow",
        ticker="AMZN",
        prompt=(
            "Using the last eight quarters, describe Amazon's revenue trend and "
            "latest trailing-twelve-month free cash flow, and tell me whether the "
            "margin picture is improving."
        ),
        difficulty="complex",
        expected_tools=("get_quarterly_detail", "get_ttm_metrics", "get_ttm_ratios"),
        evidence_kind="quarterly_and_ttm",
        evidence_params={
            "ticker": "AMZN",
            "quarterly_metrics": ["revenue"],
            "quarterly_ratio_names": [
                "gross_profit_margin",
                "operating_profit_margin",
                "net_profit_margin",
            ],
            "annual_ratio_names": [
                "gross_profit_margin",
                "operating_profit_margin",
                "net_profit_margin",
                "free_cash_flow_to_operating_cash_flow_ratio",
                "capital_expenditure_coverage_ratio",
                "financial_leverage_ratio",
            ],
            "ttm_metrics": ["free_cash_flow"],
            "ttm_ratio_names": ["net_profit_margin", "operating_profit_margin"],
            "n_quarters": 8,
            "annual_periods": 4,
        },
        must_cover=("eight quarters", "free cash flow", "margin"),
        evaluation_focus=("multi_hop_reasoning", "confidence_calibration"),
        notes="Multi-tool quarterly plus TTM synthesis.",
    ),
    ChatEvalQuestion(
        question_id="amzn-bull-bear-quarterly-and-ttm",
        title="AMZN bull and bear datapoints",
        ticker="AMZN",
        prompt=(
            "Using Amazon's last eight quarters plus its latest trailing-twelve-month free cash flow, "
            "give one bull datapoint and one bear datapoint. Cite the specific quarter or TTM figure for each."
        ),
        difficulty="complex",
        expected_tools=("get_quarterly_detail", "get_ttm_metrics", "get_ttm_ratios"),
        evidence_kind="quarterly_and_ttm",
        evidence_params={
            "ticker": "AMZN",
            "quarterly_metrics": ["revenue"],
            "quarterly_ratio_names": [
                "gross_profit_margin",
                "operating_profit_margin",
                "net_profit_margin",
            ],
            "annual_ratio_names": [
                "gross_profit_margin",
                "operating_profit_margin",
                "net_profit_margin",
                "free_cash_flow_to_operating_cash_flow_ratio",
                "capital_expenditure_coverage_ratio",
                "financial_leverage_ratio",
            ],
            "ttm_metrics": ["free_cash_flow"],
            "ttm_ratio_names": ["net_profit_margin", "operating_profit_margin"],
            "n_quarters": 8,
            "annual_periods": 4,
        },
        must_cover=("bull datapoint", "bear datapoint", "specific quarter or TTM figure"),
        evaluation_focus=("disconfirming_evidence", "confidence_calibration", "multi_hop_reasoning"),
        notes="Balanced-evidence synthesis that should surface both supportive and contrary datapoints from the same evidence bundle.",
    ),
    ChatEvalQuestion(
        question_id="meta-insider-sells-and-proxy",
        title="META insider selling plus proxy context",
        ticker="META",
        prompt=(
            "Since 2024-01-01, have there been notable insider sells at Meta, and "
            "what does the latest proxy statement say about CEO compensation?"
        ),
        difficulty="complex",
        expected_tools=("summarize_insider_sells", "get_proxy_statement_data"),
        evidence_kind="insider_and_proxy",
        evidence_params={
            "ticker": "META",
            "start_date": "2024-01-01",
            "end_date": "2026-04-26",
            "transaction_codes": ["S", "F"],
            "proxy_limit": 1,
            "proxy_start_date": "2024-01-01",
        },
        must_cover=("insider sells", "CEO compensation"),
        evaluation_focus=("multi_hop_reasoning", "confidence_calibration"),
        notes="Cross-filing synthesis: Form 4 plus DEF 14A.",
    ),
    ChatEvalQuestion(
        question_id="nvda-latest-10k-risk-themes",
        title="NVDA latest 10-K risk themes",
        ticker="NVDA",
        prompt=(
            "From NVIDIA's latest 10-K, what are two risk themes management highlights? "
            "Cite the accession number."
        ),
        difficulty="complex",
        expected_tools=("list_filings", "read_filing"),
        evidence_kind="latest_filing_text",
        evidence_params={"ticker": "NVDA", "form_type": "10-K", "limit": 1},
        must_cover=("two risk themes", "accession number"),
        evaluation_focus=("source_traceability", "staleness_handling"),
        notes="Raw filing read path; keep out of smoke mode because it depends on full filing text availability.",
    ),
    ChatEvalQuestion(
        question_id="xom-8k-events-and-cashflow",
        title="XOM 8-K events plus cash flow",
        ticker="XOM",
        prompt=(
            "Have there been any recent 8-K material events for Exxon Mobil in the "
            "last year, and how does its latest annual free cash flow compare with capex?"
        ),
        difficulty="complex",
        expected_tools=("get_material_events", "get_cashflow_pivot"),
        evidence_kind="events_and_cashflow",
        evidence_params={
            "ticker": "XOM",
            "start_date": "2025-01-01",
            "events_limit": 10,
            "period_type": "annual",
        },
        must_cover=("8-K", "free cash flow", "capex"),
        evaluation_focus=("staleness_handling", "multi_hop_reasoning"),
        notes="Structured events plus financial-statement synthesis.",
    ),
    ChatEvalQuestion(
        question_id="ups-risk-factors-change",
        title="UPS risk factors change",
        ticker="UPS",
        prompt=(
            "How did UPS's latest annual risk factor section change versus the prior annual filing? "
            "Identify one new emphasis and cite both accession numbers."
        ),
        difficulty="complex",
        expected_tools=("list_filings", "compare_filing_sections"),
        evidence_kind="latest_filing_section_comparison",
        evidence_params={
            "ticker": "UPS",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "risk factors",
            "max_changes": 3,
            "include_amendments": False,
        },
        must_cover=("new emphasis", "both accession numbers"),
        evaluation_focus=("source_traceability", "multi_hop_reasoning", "staleness_handling"),
        notes="Year-over-year risk-factor comparison for an industrial/logistics company.",
    ),
    ChatEvalQuestion(
        question_id="aapl-nvda-xom-fcf-ranking",
        title="Rank AAPL NVDA XOM by free cash flow",
        prompt=(
            "Using only the latest annual free cash flow values, rank AAPL, NVDA, and XOM "
            "from highest to lowest. Provide only the ranking and the free cash flow figure "
            "for each company, with no extra metrics or commentary."
        ),
        difficulty="complex",
        expected_tools=("compare_metric_across_companies",),
        evidence_kind="cross_company_metric",
        evidence_params={
            "metric_type": "free_cash_flow",
            "period_type": "annual",
            "tickers": ["AAPL", "NVDA", "XOM"],
            "limit": 20,
        },
        must_cover=("rank", "free cash flow"),
        smoke=True,
        notes="Cross-company screening question with a constrained ticker set.",
    ),
)


def get_chat_eval_questions(smoke_only: bool = False) -> list[ChatEvalQuestion]:
    """Return the full corpus or the smoke subset."""
    if not smoke_only:
        return list(CHAT_EVAL_QUESTIONS)
    return [question for question in CHAT_EVAL_QUESTIONS if question.smoke]


def get_chat_eval_question(question_id: str) -> ChatEvalQuestion:
    """Return one question by id."""
    for question in CHAT_EVAL_QUESTIONS:
        if question.question_id == question_id:
            return question
    raise KeyError(f"Unknown chat evaluation question: {question_id}")