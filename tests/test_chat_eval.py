from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

import investment_researcher.analytics as analytics_module
from investment_researcher.web import chat_eval


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
    assert "## Item 1B. Unresolved Staff Comments" not in excerpt


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
                                '"reason":null,'
                                '"pass_reasons":null,'
                                '"fail_reasons":null,'
                                '"unsupported_claims":null,'
                                '"missing_key_facts":null,'
                                '"ambiguity_notes":null'
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
    assert verdict.pass_reasons == []
    assert verdict.fail_reasons == []
    assert verdict.unsupported_claims == []
    assert verdict.missing_key_facts == []
    assert verdict.ambiguity_notes == []