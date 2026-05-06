from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

import investment_researcher.analytics as analytics_module
from investment_researcher.web import chat_eval
from tests.fixtures.chat_eval_questions import get_chat_eval_question, get_chat_eval_questions


def test_quarterly_margin_rows_supports_wide_rows():
    rows = [
        {
            "metric_type": "revenue",
            "TTM": 300.0,
            "Quarter Ended 12/31/2025": 120.0,
            "Quarter Ended 09/30/2025": 100.0,
        },
        {
            "metric_type": "gross_profit",
            "TTM": 150.0,
            "Quarter Ended 12/31/2025": 60.0,
            "Quarter Ended 09/30/2025": 45.0,
        },
        {
            "metric_type": "operating_income",
            "TTM": 45.0,
            "Quarter Ended 12/31/2025": 18.0,
            "Quarter Ended 09/30/2025": 14.0,
        },
        {
            "metric_type": "net_income",
            "TTM": 36.0,
            "Quarter Ended 12/31/2025": 15.0,
            "Quarter Ended 09/30/2025": 12.0,
        },
    ]

    margins = chat_eval._quarterly_margin_rows(rows)

    assert margins == [
        {
            "period_end": "2025-12-31",
            "period_label": "Quarter Ended 12/31/2025",
            "revenue": 120.0,
            "gross_profit": 60.0,
            "gross_margin": 0.5,
            "operating_income": 18.0,
            "operating_margin": 0.15,
            "net_income": 15.0,
            "net_margin": 0.125,
        },
        {
            "period_end": "2025-09-30",
            "period_label": "Quarter Ended 09/30/2025",
            "revenue": 100.0,
            "gross_profit": 45.0,
            "gross_margin": 0.45,
            "operating_income": 14.0,
            "operating_margin": 0.14,
            "net_income": 12.0,
            "net_margin": 0.12,
        },
    ]


def test_build_evidence_bundle_includes_optional_ratio_trends(monkeypatch):
    def fake_quarterly_detail(ticker, metrics, n_quarters):
        assert ticker == "AMZN"
        assert metrics == ["revenue", "net_income"]
        assert n_quarters == 2
        return pd.DataFrame(
            [
                {
                    "metric_type": "revenue",
                    "TTM": 300.0,
                    "Quarter Ended 12/31/2025": 120.0,
                    "Quarter Ended 09/30/2025": 100.0,
                },
                {
                    "metric_type": "net_income",
                    "TTM": 30.0,
                    "Quarter Ended 12/31/2025": 15.0,
                    "Quarter Ended 09/30/2025": 10.0,
                },
            ]
        ).set_index("metric_type")

    def fake_ratio_timeseries(ticker, ratio_names, period_type):
        assert ticker == "AMZN"
        data = [
            {
                "period_end": "2025-12-31",
                "ratio_name": ratio_names[0],
                "value": 0.5 if period_type == "quarterly" else 2.0,
            },
            {
                "period_end": "2025-09-30" if period_type == "quarterly" else "2024-12-31",
                "ratio_name": ratio_names[0],
                "value": 0.45 if period_type == "quarterly" else 1.8,
            },
        ]
        return pd.DataFrame(data)

    monkeypatch.setattr(analytics_module, "quarterly_detail", fake_quarterly_detail)
    monkeypatch.setattr(analytics_module, "ratio_timeseries", fake_ratio_timeseries)
    monkeypatch.setattr(analytics_module, "ttm_metrics", lambda ticker, metrics: {"free_cash_flow": 7.5})
    monkeypatch.setattr(analytics_module, "get_ratios_ttm", lambda ticker: {"net_profit_margin": 0.1})

    question = SimpleNamespace(
        evidence_kind="quarterly_and_ttm",
        evidence_params={
            "ticker": "AMZN",
            "quarterly_metrics": ["revenue"],
            "quarterly_ratio_names": ["gross_profit_margin"],
            "annual_ratio_names": ["financial_leverage_ratio"],
            "ttm_metrics": ["free_cash_flow"],
            "ttm_ratio_names": ["net_profit_margin"],
            "n_quarters": 2,
            "annual_periods": 2,
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert evidence.kind == "quarterly_and_ttm"
    assert evidence.payload["quarterly_margins"] == [
        {
            "period_end": "2025-12-31",
            "period_label": "Quarter Ended 12/31/2025",
            "revenue": 120.0,
            "net_income": 15.0,
            "net_margin": 0.125,
        },
        {
            "period_end": "2025-09-30",
            "period_label": "Quarter Ended 09/30/2025",
            "revenue": 100.0,
            "net_income": 10.0,
            "net_margin": 0.1,
        },
    ]
    assert evidence.payload["quarterly_ratio_rows"] == [
        {
            "period_end": "2025-12-31",
            "ratio_name": "gross_profit_margin",
            "value": 0.5,
        },
        {
            "period_end": "2025-09-30",
            "ratio_name": "gross_profit_margin",
            "value": 0.45,
        },
    ]
    assert evidence.payload["annual_ratio_rows"] == [
        {
            "period_end": "2025-12-31",
            "ratio_name": "financial_leverage_ratio",
            "value": 2.0,
        },
        {
            "period_end": "2024-12-31",
            "ratio_name": "financial_leverage_ratio",
            "value": 1.8,
        },
    ]
    assert evidence.payload["ttm_metrics"] == {"free_cash_flow": 7.5}
    assert evidence.payload["ttm_ratios"] == {"net_profit_margin": 0.1}


def test_build_evidence_bundle_compacts_material_events(monkeypatch):
    long_summary = "x" * 300

    monkeypatch.setattr(
        analytics_module,
        "get_material_events",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001",
                "filing_date": "2026-04-14",
                "date_of_report": "2026-04-08",
                "item_code": "5.02",
                "content_type": "director_change",
                "summary": long_summary,
            },
            {
                "accession_number": "0002",
                "filing_date": "2024-01-18",
                "date_of_report": "2024-01-18",
                "item_code": "5.02",
                "content_type": "director_change",
                "summary": long_summary,
            },
        ],
    )

    question = SimpleNamespace(
        evidence_kind="material_events",
        evidence_params={
            "ticker": "META",
            "start_date": "2024-01-01",
            "limit": 50,
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert evidence.kind == "material_events"
    assert evidence.payload["coverage"] == {
        "requested_start_date": "2024-01-01",
        "requested_end_date": None,
        "returned_events": 2,
        "earliest_filing_date": "2024-01-18",
        "latest_filing_date": "2026-04-14",
    }
    assert evidence.payload["events"] == [
        {
            "accession_number": "0001",
            "filing_date": "2026-04-14",
            "date_of_report": "2026-04-08",
            "item_code": "5.02",
            "content_type": "director_change",
            "summary": long_summary,
        },
        {
            "accession_number": "0002",
            "filing_date": "2024-01-18",
            "date_of_report": "2024-01-18",
            "item_code": "5.02",
            "content_type": "director_change",
            "summary": long_summary,
        },
    ]
    assert "2024-01-18" in evidence.summary


def test_extract_filing_excerpt_prefers_actual_item_1a_section():
    text = "".join(
        [
            "Intro text mentioning Risk Factors in passing.\n",
            "#### NVIDIA Corporation\n",
            "| Item 1A. | Risk Factors | 12 |\n",
            "Forward-looking statements reference the heading \"Risk Factors.\"\n",
            "\n## Item 1A. Risk Factors\n",
            "The following risk factors should be considered.\n",
            "#### Risk Factors Summary\n",
            "- Demand volatility\n",
            "- Supply constraints\n",
            "\n## Item 1B. Unresolved Staff Comments\n",
            "Other section text\n",
        ]
    )

    excerpt = chat_eval._extract_filing_excerpt(text)

    assert excerpt.startswith("## Item 1A. Risk Factors")
    assert "Demand volatility" in excerpt
    assert "Forward-looking statements" not in excerpt


def test_compact_filing_section_includes_risk_theme_candidates():
    compact = chat_eval._compact_filing_section(
        {
            "section_key": "item-1a",
            "item_code": "1A",
            "heading": "Item 1A. Risk Factors",
            "content": """
Risks Related to Our Business and Our Industry
• Industry changes could pressure revenue.
Risks Related to Demand, Supply, and Manufacturing
• Supply constraints could delay product delivery.
""",
        }
    )

    assert compact["theme_candidates"] == [
        "Risks Related to Our Business and Our Industry",
        "Risks Related to Demand, Supply, and Manufacturing",
    ]
    assert compact["risk_highlights"] == [
        "Risks Related to Our Business and Our Industry: Industry changes could pressure revenue.",
        "Risks Related to Demand, Supply, and Manufacturing: Supply constraints could delay product delivery.",
    ]


def test_compact_filing_section_includes_mdna_highlights():
    compact = chat_eval._compact_filing_section(
        {
            "section_key": "item-7",
            "item_code": "7",
            "heading": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            "content": """
### Executive Overview
Revenue growth was driven by Services and iPhone demand.

### Liquidity and Capital Resources
The company maintained strong liquidity while returning capital to shareholders.
""",
        }
    )

    assert compact["section_highlights"] == [
        "Executive Overview: Revenue growth was driven by Services and iPhone demand.",
        "Liquidity and Capital Resources: The company maintained strong liquidity while returning capital to shareholders.",
    ]


def test_build_evidence_bundle_uses_full_insider_proxy_summary(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "summarize_insider_sells",
        lambda **kwargs: [
            {
                "insider_name": "Susan J Li",
                "total_proceeds": 191178706.3865,
                "transaction_count": 53,
            }
        ],
    )
    monkeypatch.setattr(
        analytics_module,
        "get_proxy_statement_data",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001628280-26-025532",
                "filing_date": "2026-04-16",
                "peo_name": "Mark Zuckerberg",
            }
        ],
    )

    question = SimpleNamespace(
        evidence_kind="insider_and_proxy",
        evidence_params={
            "ticker": "META",
            "start_date": "2024-01-01",
            "end_date": "2026-04-26",
            "proxy_limit": 1,
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert evidence.kind == "insider_and_proxy"
    assert evidence.payload["insider_sells"][0]["insider_name"] == "Susan J Li"
    assert evidence.payload["proxy_rows"][0]["accession_number"] == "0001628280-26-025532"


def test_build_evidence_bundle_summarizes_beneficial_ownership(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "summarize_beneficial_ownership",
        lambda **kwargs: {
            "issuer_name": "Palantir Technologies Inc.",
            "latest_form_type": "SC 13G/A",
            "latest_total_percent": 6.3,
            "latest_reporting_person_names": ["Passive Manager LLC"],
            "latest_is_passive_investor": True,
        },
    )

    question = SimpleNamespace(
        evidence_kind="beneficial_ownership_summary",
        evidence_params={"ticker": "PLTR", "limit": 10},
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert evidence.kind == "beneficial_ownership_summary"
    assert evidence.payload["issuer_name"] == "Palantir Technologies Inc."
    assert evidence.payload["latest_form_type"] == "SC 13G/A"
    assert evidence.payload["latest_total_percent"] == 6.3
    assert evidence.payload["latest_is_passive_investor"] is True


def test_build_evidence_bundle_compacts_beneficial_ownership_rows(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "get_beneficial_ownership",
        lambda **kwargs: [
            {
                "accession_number": "0001321655-26-000001",
                "form_type": "SC 13D",
                "filing_date": "2026-03-15",
                "event_date": "2026-03-10",
                "issuer_name": "Paramount Global",
                "total_shares": 12_000_000,
                "total_percent": 6.1,
                "reporting_person_names": ["Example Capital"],
                "is_amendment": False,
                "rule_designation": None,
                "is_passive_investor": False,
                "purpose_of_transaction": "Potential strategic engagement.",
                "ignored_field": "ignored",
            }
        ],
    )

    question = SimpleNamespace(
        evidence_kind="beneficial_ownership_rows",
        evidence_params={"ticker": "PARA", "start_date": "2025-01-01", "limit": 3},
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert evidence.kind == "beneficial_ownership_rows"
    assert evidence.payload == [
        {
            "accession_number": "0001321655-26-000001",
            "form_type": "SC 13D",
            "filing_date": "2026-03-15",
            "event_date": "2026-03-10",
            "issuer_name": "Paramount Global",
            "total_shares": 12_000_000,
            "total_percent": 6.1,
            "reporting_person_names": ["Example Capital"],
            "is_amendment": False,
            "rule_designation": None,
            "is_passive_investor": False,
            "purpose_of_transaction": "Potential strategic engagement.",
        }
    ]


def test_build_evidence_bundle_lists_latest_filing_sections(monkeypatch):
    seen_get_filings_list: list[tuple[object, ...]] = []

    def fake_get_filings_list(
        ticker,
        form_type=None,
        limit=None,
        start_date=None,
        end_date=None,
        include_amendments=None,
    ):
        seen_get_filings_list.append(
            (ticker, form_type, limit, start_date, end_date, include_amendments)
        )
        return [
            {
                "accession_number": "0000104169-26-000001",
                "form_type": "8-K",
                "filing_date": "2026-04-10",
                "description": "Current report",
            }
        ]

    monkeypatch.setattr(analytics_module, "get_filings_list", fake_get_filings_list)
    monkeypatch.setattr(
        analytics_module,
        "get_filing_sections",
        lambda ticker, accession_number: [
            {
                "section_key": "item-5-02",
                "item_code": "5.02",
                "heading": "Item 5.02 Departure of Directors or Certain Officers",
                "content": "ignored",
            },
            {
                "section_key": "item-9-01",
                "item_code": "9.01",
                "heading": "Item 9.01 Financial Statements and Exhibits",
                "content": "ignored",
            },
        ],
    )

    question = SimpleNamespace(
        evidence_kind="latest_filing_sections",
        evidence_params={"ticker": "WMT", "form_type": "8-K", "limit": 1},
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert seen_get_filings_list == [("WMT", "8-K", 1, None, None, False)]
    assert evidence.payload == {
        "filing": {
            "accession_number": "0000104169-26-000001",
            "form_type": "8-K",
            "filing_date": "2026-04-10",
            "description": "Current report",
        },
        "sections": [
            {
                "section_key": "item-5-02",
                "item_code": "5.02",
                "heading": "Item 5.02 Departure of Directors or Certain Officers",
            },
            {
                "section_key": "item-9-01",
                "item_code": "9.01",
                "heading": "Item 9.01 Financial Statements and Exhibits",
            },
        ],
    }


def test_build_evidence_bundle_reads_and_searches_latest_filing(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0000731766-26-000001",
                "form_type": "10-K",
                "filing_date": "2026-07-25",
                "description": "Annual report",
            }
        ],
    )
    monkeypatch.setattr(
        analytics_module,
        "get_filing_section",
        lambda ticker, accession_number, section_name: {
            "section_key": "item-1a",
            "item_code": "1A",
            "heading": "Item 1A. Risk Factors",
            "content": "A" * 30_000,
        },
    )
    monkeypatch.setattr(
        analytics_module,
        "search_filing_text",
        lambda ticker, accession_number, query, section_name=None, max_matches=5, context_chars=280: [
            {
                "item_code": "1A",
                "heading": "Item 1A. Risk Factors",
                "line_number": 120,
                "excerpt": "China demand softness may affect results.",
                "ignored_field": "ignored",
            }
        ],
    )

    section_question = SimpleNamespace(
        evidence_kind="latest_filing_section",
        evidence_params={
            "ticker": "UNH",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "risk factors",
        },
    )
    search_question = SimpleNamespace(
        evidence_kind="latest_filing_search",
        evidence_params={
            "ticker": "NKE",
            "form_type": "10-K",
            "limit": 1,
            "query": "China",
            "max_matches": 3,
        },
    )

    section_evidence = chat_eval.build_evidence_bundle(section_question)
    search_evidence = chat_eval.build_evidence_bundle(search_question)

    assert section_evidence.payload["section_name"] == "risk factors"
    assert section_evidence.payload["section"]["item_code"] == "1A"
    assert len(section_evidence.payload["section"]["content"]) == 30_000
    assert search_evidence.payload == {
        "filing": {
            "accession_number": "0000731766-26-000001",
            "form_type": "10-K",
            "filing_date": "2026-07-25",
            "description": "Annual report",
        },
        "query": "China",
        "matches": [
            {
                "item_code": "1A",
                "heading": "Item 1A. Risk Factors",
                "line_number": 120,
                "excerpt": "China demand softness may affect results.",
            }
        ],
    }


def test_build_evidence_bundle_keeps_large_risk_section_in_summary(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0000731766-26-000001",
                "form_type": "10-K",
                "filing_date": "2026-07-25",
                "description": "Annual report",
            }
        ],
    )
    monkeypatch.setattr(
        analytics_module,
        "get_filing_section",
        lambda ticker, accession_number, section_name: {
            "section_key": "item-1a",
            "item_code": "1A",
            "heading": "Item 1A. Risk Factors",
            "content": "A" * 80_000 + "TAIL-MARKER",
        },
    )

    question = SimpleNamespace(
        evidence_kind="latest_filing_section",
        evidence_params={
            "ticker": "UNH",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "risk factors",
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert "TAIL-MARKER" in evidence.summary
    assert "... [truncated]" not in evidence.summary


def test_build_evidence_bundle_keeps_large_mdna_section_in_summary(monkeypatch):
    monkeypatch.setattr(
        analytics_module,
        "get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0000320193-25-000073",
                "form_type": "10-K",
                "filing_date": "2025-11-01",
                "description": "Annual report",
            }
        ],
    )
    monkeypatch.setattr(
        analytics_module,
        "get_filing_section",
        lambda ticker, accession_number, section_name: {
            "section_key": "item-7",
            "item_code": "7",
            "heading": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            "content": "B" * 80_000 + "TAIL-MARKER",
        },
    )

    question = SimpleNamespace(
        evidence_kind="latest_filing_section",
        evidence_params={
            "ticker": "AAPL",
            "form_type": "10-K",
            "limit": 1,
            "section_name": "mda",
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert "TAIL-MARKER" in evidence.summary
    assert "... [truncated]" not in evidence.summary


def test_build_evidence_bundle_compares_latest_filing_section(monkeypatch):
    seen_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        analytics_module,
        "get_filings_list",
        lambda *args, **kwargs: [
            {
                "accession_number": "0001090727-26-000001",
                "form_type": "10-K",
                "filing_date": "2026-02-20",
                "description": "Annual report",
            }
        ],
    )

    def fake_compare_filing_sections(**kwargs):
        seen_kwargs.update(kwargs)
        return {
            "ticker": "UPS",
            "requested_section": "risk factors",
            "previous_selection_mode": "latest_prior_same_form",
            "current_filing": {"accession_number": "0001090727-26-000001"},
            "previous_filing": {"accession_number": "0001090727-25-000010"},
            "current_only_excerpts": ["Labor disruption risk increased."],
            "previous_only_excerpts": ["Fuel cost volatility remained elevated."],
        }

    monkeypatch.setattr(analytics_module, "compare_filing_sections", fake_compare_filing_sections)

    question = SimpleNamespace(
        evidence_kind="latest_filing_section_comparison",
        evidence_params={
            "ticker": "UPS",
            "form_type": "10-K",
            "section_name": "risk factors",
            "max_changes": 2,
        },
    )

    evidence = chat_eval.build_evidence_bundle(question)

    assert seen_kwargs == {
        "ticker": "UPS",
        "current_accession_number": "0001090727-26-000001",
        "section_name": "risk factors",
        "previous_accession_number": None,
        "max_changes": 2,
        "excerpt_chars": 280,
    }
    assert evidence.payload["previous_selection_mode"] == "latest_prior_same_form"
    assert evidence.payload["previous_filing"]["accession_number"] == "0001090727-25-000010"


def test_extract_json_object_repairs_repeated_field_name():
    raw_text = (
        '{'
        '"overall":"pass",'
        '"faithfulness":"pass",'
        '"factual_grounding":"pass",'
        '"completeness":"completeness":"pass"'
        '}'
    )

    parsed = chat_eval._extract_json_object(raw_text)

    assert parsed["overall"] == "pass"
    assert parsed["completeness"] == "pass"


def test_chat_eval_question_corpus_includes_recent_sec_tool_questions():
    questions = {question.question_id: question for question in get_chat_eval_questions()}

    expected_tools = {
        "pltr-latest-beneficial-ownership-snapshot": ("summarize_beneficial_ownership",),
        "para-recent-beneficial-ownership-filings": ("get_beneficial_ownership",),
        "wmt-latest-8k-section-list": ("list_filings", "list_filing_sections"),
        "unh-latest-10k-risk-section": (
            "list_filings",
            "list_filing_sections",
            "read_filing_section",
        ),
        "aapl-latest-10k-mdna-highlights": (
            "list_filings",
            "list_filing_sections",
            "read_filing_section",
        ),
        "nke-latest-10k-china-search": ("list_filings", "search_filing_text"),
        "ups-risk-factors-change": ("list_filings", "compare_filing_sections"),
    }

    for question_id, tools in expected_tools.items():
        assert get_chat_eval_question(question_id) == questions[question_id]
        assert questions[question_id].expected_tools == tools

    assert {question.difficulty for question in questions.values()} >= {"simple", "medium", "complex"}
    assert [question.question_id for question in get_chat_eval_questions(smoke_only=True)] == [
        "aapl-ttm-revenue-net-income",
        "nvda-latest-annual-ratios",
        "xom-annual-cash-flow-summary",
        "aapl-nvda-xom-fcf-ranking",
    ]


@pytest.mark.asyncio
async def test_run_chat_case_retries_empty_answer():
    app = FastAPI()
    seen_messages: list[str] = []

    @app.post("/api/chat")
    async def chat_endpoint(request: Request):
        payload = await request.json()
        seen_messages.append(payload["message"])
        if len(seen_messages) == 1:
            body = "".join(
                [
                    'data: {"progress": "planning the analysis"}\n\n',
                    'data: {"token": "   "}\n\n',
                    'data: [DONE]\n\n',
                ]
            )
        else:
            body = "".join(
                [
                    'data: {"progress": "planning the analysis"}\n\n',
                    'data: {"token": "Recovered answer."}\n\n',
                    'data: [DONE]\n\n',
                ]
            )
        return Response(body, media_type="text/event-stream")

    question = SimpleNamespace(
        question_id="meta-recent-8k-events",
        prompt="What recent 8-K material events has Meta reported since 2024-01-01?",
        ticker="META",
        chat_timeout_seconds=5,
    )

    outcome = await chat_eval.run_chat_case(app, question)

    assert outcome.status == "ok"
    assert outcome.answer == "Recovered answer."
    assert len(seen_messages) == 2
    assert seen_messages[1].endswith(chat_eval._EMPTY_ANSWER_RETRY_SUFFIX)


@pytest.mark.asyncio
async def test_evaluate_answer_handles_nullable_evaluator_fields(monkeypatch):
    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{'
                                '"overall":"pass",'
                                '"faithfulness":"pass",'
                                '"factual_grounding":"pass",'
                                '"completeness":"pass",'
                                '"source_traceability":null,'
                                '"confidence_calibration":null,'
                                '"staleness_handling":null,'
                                '"disconfirming_evidence":null,'
                                '"multi_hop_reasoning":null,'
                                '"reason":null,'
                                '"pass_reasons":null,'
                                '"fail_reasons":null,'
                                '"unsupported_claims":null,'
                                '"missing_key_facts":null,'
                                '"ambiguity_notes":null,'
                                '"citation_gaps":null,'
                                '"stale_data_concerns":null,'
                                '"reasoning_gaps":null'
                                '}'
                            )
                        )
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(chat_eval, "_build_eval_client", lambda: fake_client)

    question = SimpleNamespace(
        question_id="brk-top-13f-holdings",
        prompt="What are Berkshire Hathaway's top holdings in its latest 13F filing?",
        expected_tools=("summarize_institutional_holdings",),
        must_cover=("top holdings",),
        evaluation_focus=(),
        notes="",
        evaluation_timeout_seconds=5,
    )
    evidence = chat_eval.EvidenceBundle(
        kind="institutional_holdings_summary",
        summary="{}",
        payload={},
    )

    verdict = await chat_eval.evaluate_answer(question, "answer", evidence)

    assert verdict.status == "ok"
    assert verdict.overall == "pass"
    assert verdict.reason == ""
    assert verdict.source_traceability == "not_applicable"
    assert verdict.confidence_calibration == "not_applicable"
    assert verdict.staleness_handling == "not_applicable"
    assert verdict.disconfirming_evidence == "not_applicable"
    assert verdict.multi_hop_reasoning == "not_applicable"
    assert verdict.pass_reasons == []
    assert verdict.fail_reasons == []
    assert verdict.unsupported_claims == []
    assert verdict.missing_key_facts == []
    assert verdict.ambiguity_notes == []
    assert verdict.citation_gaps == []
    assert verdict.stale_data_concerns == []
    assert verdict.reasoning_gaps == []