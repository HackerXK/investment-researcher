from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from investment_researcher import analytics


def test_summarize_insider_sells_groups_sale_activity(monkeypatch):
    def fake_form4(insider_name: str, position: str, rows: list[dict[str, object]]):
        return SimpleNamespace(
            non_derivative_table=SimpleNamespace(
                transactions=SimpleNamespace(data=pd.DataFrame(rows))
            ),
            get_ownership_summary=lambda: SimpleNamespace(
                insider_name=insider_name,
                position=position,
                primary_activity="Executive",
            ),
        )

    filings = [
        SimpleNamespace(
            accession_no="0000320193-24-000111",
            filing_date="2024-06-03",
            obj=lambda: fake_form4(
                insider_name="Jane Executive",
                position="SVP",
                rows=[
                    {
                        "Date": "2024-06-01",
                        "Security": "Common Stock",
                        "Shares": 5_000,
                        "Remaining": 120_000,
                        "Price": 210.0,
                        "AcquiredDisposed": "D",
                        "DirectIndirect": "D",
                        "NatureOfOwnership": "Direct",
                        "Code": "S",
                        "TransactionType": "sale",
                    },
                    {
                        "Date": "2024-06-02",
                        "Security": "Common Stock",
                        "Shares": 1_000,
                        "Remaining": 119_000,
                        "Price": 205.0,
                        "AcquiredDisposed": "D",
                        "DirectIndirect": "D",
                        "NatureOfOwnership": "Direct",
                        "Code": "F",
                        "TransactionType": "tax",
                    },
                ],
            ),
        ),
        SimpleNamespace(
            accession_no="0000320193-25-000222",
            filing_date="2025-02-18",
            obj=lambda: fake_form4(
                insider_name="John Officer",
                position="CFO",
                rows=[
                    {
                        "Date": "2025-02-14",
                        "Security": "Common Stock",
                        "Shares": 2_000,
                        "Remaining": 80_000,
                        "Price": 190.0,
                        "AcquiredDisposed": "D",
                        "DirectIndirect": "D",
                        "NatureOfOwnership": "Direct",
                        "Code": "F",
                        "TransactionType": "tax",
                    }
                ],
            ),
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            assert kwargs == {
                "form": "4",
                "filing_date": "2024-01-01:2025-12-31",
                "amendments": False,
            }
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    summaries = analytics.summarize_insider_sells(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2025-12-31",
        limit=10,
        include_amendments=False,
    )

    assert summaries[0]["insider_name"] == "Jane Executive"
    assert summaries[0]["transaction_count"] == 2
    assert summaries[0]["total_proceeds"] == 1_255_000
    assert summaries[0]["classification"] == "Very notable"
    assert summaries[0]["transaction_codes"] == ["S", "F"]


def test_get_material_events_returns_item_rows(monkeypatch):
    class FakeCurrentReport:
        items = ["Item 5.02", "Item 9.01"]
        content_type = "management_changes"
        date_of_report = "2024-05-10"
        press_releases = [object()]

        def __getitem__(self, item_name: str) -> str:
            mapping = {
                "Item 5.02": "Departure of directors and appointment of executive officers.",
                "5.02": "Departure of directors and appointment of executive officers.",
                "Item 9.01": "Financial statements and exhibits attached to the filing.",
                "9.01": "Financial statements and exhibits attached to the filing.",
            }
            return mapping[item_name]

    filing = SimpleNamespace(
        accession_no="0000320193-24-000050",
        form="8-K",
        filing_date="2024-05-11",
        obj=lambda: FakeCurrentReport(),
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            assert kwargs == {
                "form": "8-K",
                "filing_date": "2024-01-01:2024-12-31",
                "amendments": False,
            }
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    events = analytics.get_material_events(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2024-12-31",
        item_codes=["5.02"],
        limit=10,
    )

    assert len(events) == 1
    assert events[0]["accession_number"] == "0000320193-24-000050"
    assert events[0]["item_code"] == "5.02"
    assert events[0]["item_label"] == "Item 5.02"
    assert events[0]["content_type"] == "management_changes"
    assert events[0]["summary"] == "Departure of directors and appointment of executive officers."
    assert events[0]["text_length"] == len(
        "Departure of directors and appointment of executive officers."
    )
    assert events[0]["has_press_release"] is True


def test_summarize_material_events_groups_by_item_code(monkeypatch):
    class FakeCurrentReport:
        def __init__(self, summary: str):
            self.items = ["Item 5.02"]
            self.content_type = "management_changes"
            self.date_of_report = "2024-05-10"
            self.press_releases = []
            self._summary = summary

        def __getitem__(self, item_name: str) -> str:
            return self._summary

    filings = [
        SimpleNamespace(
            accession_no="acc-1",
            form="8-K",
            filing_date="2024-05-11",
            obj=lambda: FakeCurrentReport("Executive departure announcement."),
        ),
        SimpleNamespace(
            accession_no="acc-2",
            form="8-K",
            filing_date="2024-06-01",
            obj=lambda: FakeCurrentReport("New CFO appointment announcement."),
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    summary = analytics.summarize_material_events(
        ticker="AAPL",
        group_by="item_code",
        limit=10,
    )

    assert summary[0]["item_code"] == "5.02"
    assert summary[0]["event_count"] == 2
    assert summary[0]["latest_filing_date"] == "2024-06-01"
    assert summary[0]["sample_summaries"] == [
        "New CFO appointment announcement.",
        "Executive departure announcement.",
    ]


def test_get_proxy_statement_data_returns_structured_rows(monkeypatch):
    proxy = SimpleNamespace(
        company_name="Apple Inc.",
        cik="0000320193",
        fiscal_year_end="2024-09-28",
        peo_name="Timothy D. Cook",
        peo_total_comp=9_800_000,
        peo_actually_paid_comp=8_750_000,
        neo_avg_total_comp=6_500_000,
        neo_avg_actually_paid_comp=5_900_000,
        total_shareholder_return=42.5,
        peer_group_tsr=38.1,
        net_income=93_736_000_000,
        company_selected_measure="Operating income",
        company_selected_measure_value=123_450_000_000,
        performance_measures=["Operating income", "Revenue"],
        insider_trading_policy_adopted=True,
        has_xbrl=True,
        executive_compensation=pd.DataFrame(
            [
                {
                    "fiscal_year_end": "2024-09-28",
                    "peo_total_comp": 9_800_000,
                    "peo_actually_paid_comp": 8_750_000,
                    "neo_avg_total_comp": 6_500_000,
                    "neo_avg_actually_paid_comp": 5_900_000,
                }
            ]
        ),
        pay_vs_performance=pd.DataFrame(
            [
                {
                    "fiscal_year_end": "2024-09-28",
                    "total_shareholder_return": 42.5,
                    "peer_group_tsr": 38.1,
                }
            ]
        ),
    )
    filing = SimpleNamespace(
        accession_no="0000320193-25-000001",
        form="DEF 14A",
        filing_date="2025-01-10",
        obj=lambda: proxy,
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    rows = analytics.get_proxy_statement_data("AAPL")

    assert rows[0]["peo_name"] == "Timothy D. Cook"
    assert rows[0]["peo_total_comp"] == 9_800_000
    assert rows[0]["executive_compensation"] == [
        {
            "fiscal_year_end": "2024-09-28",
            "peo_total_comp": 9_800_000,
            "peo_actually_paid_comp": 8_750_000,
            "neo_avg_total_comp": 6_500_000,
            "neo_avg_actually_paid_comp": 5_900_000,
        }
    ]


def test_get_proxy_statement_data_prefers_most_recent_filing(monkeypatch):
    def fake_proxy(total_comp: int, filing_year: str):
        return SimpleNamespace(
            company_name="Apple Inc.",
            cik="0000320193",
            fiscal_year_end=filing_year,
            peo_name="Timothy D. Cook",
            peo_total_comp=total_comp,
            peo_actually_paid_comp=total_comp,
            neo_avg_total_comp=5_000_000,
            neo_avg_actually_paid_comp=4_500_000,
            total_shareholder_return=30.0,
            peer_group_tsr=28.0,
            net_income=90_000_000_000,
            company_selected_measure="Operating income",
            company_selected_measure_value=120_000_000_000,
            performance_measures=["Operating income"],
            insider_trading_policy_adopted=True,
            has_xbrl=True,
            executive_compensation=pd.DataFrame(),
            pay_vs_performance=pd.DataFrame(),
        )

    filings = [
        SimpleNamespace(
            accession_no="proxy-2025",
            form="DEF 14A",
            filing_date="2025-01-10",
            obj=lambda: fake_proxy(74_609_802, "2024-09-28"),
        ),
        SimpleNamespace(
            accession_no="proxy-2026",
            form="DEF 14A",
            filing_date="2026-01-08",
            obj=lambda: fake_proxy(74_294_811, "2025-09-27"),
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    rows = analytics.get_proxy_statement_data("AAPL", limit=1)

    assert rows[0]["accession_number"] == "proxy-2026"
    assert rows[0]["filing_date"] == "2026-01-08"
    assert rows[0]["peo_total_comp"] == 74_294_811


def test_summarize_proxy_statement_returns_latest_snapshot(monkeypatch):
    def fake_proxy(total_comp: int, filing_year: str):
        return SimpleNamespace(
            company_name="Apple Inc.",
            cik="0000320193",
            fiscal_year_end=filing_year,
            peo_name="Timothy D. Cook",
            peo_total_comp=total_comp,
            peo_actually_paid_comp=total_comp - 500_000,
            neo_avg_total_comp=5_000_000,
            neo_avg_actually_paid_comp=4_500_000,
            total_shareholder_return=30.0,
            peer_group_tsr=28.0,
            net_income=90_000_000_000,
            company_selected_measure="Operating income",
            company_selected_measure_value=120_000_000_000,
            performance_measures=["Operating income"],
            insider_trading_policy_adopted=True,
            has_xbrl=True,
            executive_compensation=pd.DataFrame(),
            pay_vs_performance=pd.DataFrame(),
        )

    filings = [
        SimpleNamespace(
            accession_no="proxy-2025",
            form="DEF 14A",
            filing_date="2025-01-10",
            obj=lambda: fake_proxy(9_800_000, "2024-09-28"),
        ),
        SimpleNamespace(
            accession_no="proxy-2024",
            form="DEF 14A",
            filing_date="2024-01-11",
            obj=lambda: fake_proxy(8_000_000, "2023-09-30"),
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "AAPL"

        def get_filings(self, **kwargs):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    summary = analytics.summarize_proxy_statement("AAPL", limit=5)

    assert summary["latest_accession_number"] == "proxy-2025"
    assert summary["latest_peo_total_comp"] == 9_800_000
    assert summary["peo_total_comp_change"] == 1_800_000
    assert summary["peo_total_comp_change_pct"] == 22.5


def test_get_institutional_holdings_returns_structured_rows(monkeypatch):
    thirteen_f = SimpleNamespace(
        report_period="2024-12-31",
        management_company_name="Berkshire Hathaway Inc",
        filing_signer_name="Marc D. Hamburg",
        filing_signer_title="Senior Vice President",
        total_value=300_000_000,
        total_holdings=3,
        holdings=pd.DataFrame(
            [
                {
                    "Issuer": "Apple Inc.",
                    "Class": "COM",
                    "Cusip": "037833100",
                    "Ticker": "AAPL",
                    "Value": 120_000_000,
                    "SharesPrnAmount": 500_000,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 500_000,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                },
                {
                    "Issuer": "Bank of America Corp",
                    "Class": "COM",
                    "Cusip": "060505104",
                    "Ticker": "BAC",
                    "Value": 80_000_000,
                    "SharesPrnAmount": 2_000_000,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 2_000_000,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                },
            ]
        ),
    )
    filing = SimpleNamespace(
        accession_no="0000950123-25-000001",
        form="13F-HR",
        filing_date="2025-02-14",
        cik="1067983",
        obj=lambda: thirteen_f,
    )

    class FakeCompany:
        def __init__(self, manager: str):
            assert manager == "BRK"

        def get_filings(self, **kwargs):
            assert kwargs == {
                "form": "13F-HR",
                "filing_date": None,
                "amendments": False,
            }
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    holdings = analytics.get_institutional_holdings(manager="BRK", limit=10)

    assert holdings[0]["issuer"] == "Apple Inc."
    assert holdings[0]["ticker"] == "AAPL"
    assert holdings[0]["portfolio_weight_pct"] == 40


def test_summarize_institutional_holdings_returns_concentration_metrics(monkeypatch):
    thirteen_f = SimpleNamespace(
        report_period="2024-12-31",
        management_company_name="Berkshire Hathaway Inc",
        filing_signer_name="Marc D. Hamburg",
        filing_signer_title="Senior Vice President",
        total_value=300_000_000,
        total_holdings=3,
        holdings=pd.DataFrame(
            [
                {
                    "Issuer": "Apple Inc.",
                    "Class": "COM",
                    "Cusip": "037833100",
                    "Ticker": "AAPL",
                    "Value": 120_000_000,
                    "SharesPrnAmount": 500_000,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 500_000,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                },
                {
                    "Issuer": "Bank of America Corp",
                    "Class": "COM",
                    "Cusip": "060505104",
                    "Ticker": "BAC",
                    "Value": 80_000_000,
                    "SharesPrnAmount": 2_000_000,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 2_000_000,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                },
                {
                    "Issuer": "Coca-Cola Co",
                    "Class": "COM",
                    "Cusip": "191216100",
                    "Ticker": "KO",
                    "Value": 60_000_000,
                    "SharesPrnAmount": 1_500_000,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 1_500_000,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                },
            ]
        ),
    )
    filing = SimpleNamespace(
        accession_no="0000950123-25-000001",
        form="13F-HR",
        filing_date="2025-02-14",
        cik="1067983",
        obj=lambda: thirteen_f,
    )

    class FakeCompany:
        def __init__(self, manager: str):
            assert manager == "BRK"

        def get_filings(self, **kwargs):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    summary = analytics.summarize_institutional_holdings(manager="BRK", top_n=2)

    assert summary["manager_name"] == "Berkshire Hathaway Inc"
    assert summary["top_5_concentration_pct"] == 86.666667
    assert [holding["ticker"] for holding in summary["top_holdings"]] == ["AAPL", "BAC"]


def test_get_institutional_holdings_prefers_latest_report_period(monkeypatch):
    def make_thirteen_f(report_period: str, total_value: int, ticker: str):
        return SimpleNamespace(
            report_period=report_period,
            management_company_name="Berkshire Hathaway Inc",
            filing_signer_name="Marc D. Hamburg",
            filing_signer_title="Senior Vice President",
            total_value=total_value,
            total_holdings=1,
            holdings=pd.DataFrame(
                [
                    {
                        "Issuer": "Apple Inc.",
                        "Class": "COM",
                        "Cusip": "037833100",
                        "Ticker": ticker,
                        "Value": total_value,
                        "SharesPrnAmount": 1,
                        "Type": "Shares",
                        "PutCall": "",
                        "SoleVoting": 1,
                        "SharedVoting": 0,
                        "NonVoting": 0,
                    }
                ]
            ),
        )

    filings = [
        SimpleNamespace(
            accession_no="0000950123-24-011775",
            form="13F-HR",
            filing_date="2024-11-14",
            cik="1067983",
            obj=lambda: make_thirteen_f("2024-09-30", 266_380_000_000, "DVA"),
        ),
        SimpleNamespace(
            accession_no="0001193125-26-054580",
            form="13F-HR",
            filing_date="2026-02-17",
            cik="1067983",
            obj=lambda: make_thirteen_f("2025-12-31", 274_160_086_701, "GOOGL"),
        ),
    ]

    class FakeCompany:
        def __init__(self, manager: str):
            assert manager == "BRK"

        def get_filings(self, **kwargs):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    holdings = analytics.get_institutional_holdings(manager="BRK", limit=10)

    assert holdings[0]["accession_number"] == "0001193125-26-054580"
    assert holdings[0]["report_period"] == "2025-12-31"
    assert holdings[0]["ticker"] == "GOOGL"


def test_get_institutional_holdings_normalizes_berkshire_manager_alias(monkeypatch):
    thirteen_f = SimpleNamespace(
        report_period="2025-12-31",
        management_company_name="Berkshire Hathaway Inc",
        filing_signer_name="Marc D. Hamburg",
        filing_signer_title="Senior Vice President",
        total_value=274_160_086_701,
        total_holdings=1,
        holdings=pd.DataFrame(
            [
                {
                    "Issuer": "Alphabet Inc.",
                    "Class": "COM",
                    "Cusip": "02079K305",
                    "Ticker": "GOOGL",
                    "Value": 5_585_842_446,
                    "SharesPrnAmount": 1,
                    "Type": "Shares",
                    "PutCall": "",
                    "SoleVoting": 1,
                    "SharedVoting": 0,
                    "NonVoting": 0,
                }
            ]
        ),
    )
    filing = SimpleNamespace(
        accession_no="0001193125-26-054580",
        form="13F-HR",
        filing_date="2026-02-17",
        cik="1067983",
        obj=lambda: thirteen_f,
    )

    class FakeCompany:
        def __init__(self, manager: str):
            assert manager == "BRK-B"

        def get_filings(self, **kwargs):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    holdings = analytics.get_institutional_holdings(manager="Berkshire Hathaway", limit=10)

    assert holdings[0]["ticker"] == "GOOGL"


def test_get_filing_sections_dedupes_table_of_contents_matches(monkeypatch):
    filing_text = """# NVIDIA CORPORATION

Item 1. Business
Item 1A. Risk Factors
Item 1B. Unresolved Staff Comments

## Item 1. Business
Actual business discussion.

## Item 1A. Risk Factors
Actual risk discussion that should be surfaced.
More risk detail.

## Item 1B. Unresolved Staff Comments
None.
"""
    filing = SimpleNamespace(
        accession_no="0001045810-26-000010",
        form="10-K",
        filing_date="2026-02-20",
        markdown=lambda: filing_text,
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    sections = analytics.get_filing_sections("NVDA", "0001045810-26-000010")

    risk_sections = [section for section in sections if section["item_code"] == "1A"]
    assert len(risk_sections) == 1
    assert risk_sections[0]["heading"] == "Item 1A. Risk Factors"
    assert risk_sections[0]["preview"].startswith(
        "Actual risk discussion that should be surfaced."
    )


def test_get_filing_section_returns_actual_body_not_toc(monkeypatch):
    filing_text = """# NVIDIA CORPORATION

Item 1. Business
Item 1A. Risk Factors
Item 1B. Unresolved Staff Comments

## Item 1. Business
Actual business discussion.

## Item 1A. Risk Factors
Actual risk discussion that should be surfaced.
More risk detail.

## Item 1B. Unresolved Staff Comments
None.
"""
    filing = SimpleNamespace(
        accession_no="0001045810-26-000010",
        form="10-K",
        filing_date="2026-02-20",
        markdown=lambda: filing_text,
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    section = analytics.get_filing_section("NVDA", "0001045810-26-000010", "risk factors")

    assert section["accession_number"] == "0001045810-26-000010"
    assert section["form_type"] == "10-K"
    assert section["item_code"] == "1A"
    assert section["heading"] == "Item 1A. Risk Factors"
    assert "Actual risk discussion that should be surfaced." in section["content"]
    assert "## Item 1A. Risk Factors" in section["content"]


def test_get_filing_sections_falls_back_to_8k_report_items(monkeypatch):
    class FakeCurrentReport:
        items = ["Item 8.01", "Item 9.01"]
        content_type = "other_events"
        date_of_report = "2026-04-30"
        press_releases = []

        def __getitem__(self, item_name: str) -> str:
            mapping = {
                "Item 8.01": "The company announced a financing update.",
                "8.01": "The company announced a financing update.",
                "Item 9.01": "Exhibits were attached to the filing.",
                "9.01": "Exhibits were attached to the filing.",
            }
            return mapping[item_name]

    filing = SimpleNamespace(
        accession_no="0001193125-26-194086",
        form="8-K",
        filing_date="2026-04-30",
        markdown=lambda: "",
        obj=lambda: FakeCurrentReport(),
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "WMT"

        def get_filings(self):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    sections = analytics.get_filing_sections("WMT", "0001193125-26-194086")

    assert sections == [
        {
            "accession_number": "0001193125-26-194086",
            "form_type": "8-K",
            "filing_date": "2026-04-30",
            "item_code": "8.01",
            "heading": "Item 8.01. Other Events",
            "title": "Other Events",
            "line_number": None,
            "text_length": len("The company announced a financing update."),
            "preview": "The company announced a financing update.",
        },
        {
            "accession_number": "0001193125-26-194086",
            "form_type": "8-K",
            "filing_date": "2026-04-30",
            "item_code": "9.01",
            "heading": "Item 9.01. Financial Statements and Exhibits",
            "title": "Financial Statements and Exhibits",
            "line_number": None,
            "text_length": len("Exhibits were attached to the filing."),
            "preview": "Exhibits were attached to the filing.",
        },
    ]


def test_search_filing_text_avoids_toc_hits(monkeypatch):
    filing_text = """# NVIDIA CORPORATION

Item 1. Business
Item 1A. Risk Factors
Item 1B. Unresolved Staff Comments

## Item 1. Business
Actual business discussion.

## Item 1A. Risk Factors
Actual risk discussion that should be surfaced.
More risk detail.

## Item 1B. Unresolved Staff Comments
None.
"""
    filing = SimpleNamespace(
        accession_no="0001045810-26-000010",
        form="10-K",
        filing_date="2026-02-20",
        markdown=lambda: filing_text,
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    matches = analytics.search_filing_text(
        "NVDA",
        "0001045810-26-000010",
        "risk factors",
        max_matches=1,
    )

    assert len(matches) == 1
    assert matches[0]["item_code"] == "1A"
    assert matches[0]["heading"] == "Item 1A. Risk Factors"
    assert matches[0]["line_number"] == 10
    assert matches[0]["excerpt"].startswith("## Item 1A. Risk Factors")
    assert "Actual risk discussion that should be surfaced." in matches[0]["excerpt"]


def test_search_filing_text_can_restrict_to_one_section(monkeypatch):
    filing_text = """# NVIDIA CORPORATION

## Item 1. Business
Actual business discussion.

## Item 1A. Risk Factors
Actual risk discussion that should be surfaced.
More risk detail.

## Item 1B. Unresolved Staff Comments
None.
"""
    filing = SimpleNamespace(
        accession_no="0001045810-26-000010",
        form="10-K",
        filing_date="2026-02-20",
        markdown=lambda: filing_text,
    )

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return [filing]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    matches = analytics.search_filing_text(
        "NVDA",
        "0001045810-26-000010",
        "Actual",
        section_name="1A",
        max_matches=5,
    )

    assert len(matches) == 1
    assert matches[0]["item_code"] == "1A"
    assert "risk discussion" in matches[0]["excerpt"]


def test_compare_filing_sections_returns_changed_excerpts(monkeypatch):
    current_filing_text = """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Shared baseline risk paragraph.

Supply chain concentration and export controls may disrupt revenue.
"""
    previous_filing_text = """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Shared baseline risk paragraph.

Demand concentration may affect results.
"""
    filings = [
        SimpleNamespace(
            accession_no="0001045810-26-000010",
            form="10-K",
            filing_date="2026-02-20",
            markdown=lambda: current_filing_text,
        ),
        SimpleNamespace(
            accession_no="0001045810-25-000011",
            form="10-K",
            filing_date="2025-02-21",
            markdown=lambda: previous_filing_text,
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    comparison = analytics.compare_filing_sections(
        ticker="NVDA",
        current_accession_number="0001045810-26-000010",
        previous_accession_number="0001045810-25-000011",
        section_name="risk factors",
        max_changes=3,
    )

    assert comparison["ticker"] == "NVDA"
    assert comparison["item_code"] == "1A"
    assert comparison["previous_selection_mode"] == "explicit_previous_accession"
    assert comparison["current_filing"]["accession_number"] == "0001045810-26-000010"
    assert comparison["previous_filing"]["accession_number"] == "0001045810-25-000011"
    assert comparison["similarity_ratio"] < 1
    assert comparison["current_only_count"] == 1
    assert comparison["previous_only_count"] == 1
    assert "Supply chain concentration and export controls" in comparison["current_only_excerpts"][0]
    assert "Demand concentration may affect results" in comparison["previous_only_excerpts"][0]


def test_compare_filing_sections_auto_selects_latest_prior_same_form(monkeypatch):
    filings = [
        SimpleNamespace(
            accession_no="0001045810-26-000010",
            form="10-K",
            filing_date="2026-02-20",
            markdown=lambda: """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Current risk paragraph.
""",
        ),
        SimpleNamespace(
            accession_no="0001045810-25-000099",
            form="10-Q",
            filing_date="2025-11-20",
            markdown=lambda: """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Quarterly risk paragraph.
""",
        ),
        SimpleNamespace(
            accession_no="0001045810-25-000011",
            form="10-K/A",
            filing_date="2025-02-21",
            markdown=lambda: """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Prior annual risk paragraph.
""",
        ),
        SimpleNamespace(
            accession_no="0001045810-24-000005",
            form="10-K",
            filing_date="2024-02-22",
            markdown=lambda: """# NVIDIA CORPORATION

## Item 1A. Risk Factors

Older annual risk paragraph.
""",
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    comparison = analytics.compare_filing_sections(
        ticker="NVDA",
        current_accession_number="0001045810-26-000010",
        section_name="risk factors",
        max_changes=2,
    )

    assert comparison["previous_selection_mode"] == "latest_prior_same_form"
    assert comparison["current_filing"]["accession_number"] == "0001045810-26-000010"
    assert comparison["previous_filing"]["accession_number"] == "0001045810-25-000011"
    assert "Current risk paragraph." in comparison["current_only_excerpts"][0]
    assert "Prior annual risk paragraph." in comparison["previous_only_excerpts"][0]


def test_get_beneficial_ownership_returns_structured_rows(monkeypatch):
    issuer_address = SimpleNamespace(
        street1="123 Market St",
        street2=None,
        city="San Francisco",
        state_or_country="CA",
        zipcode="94105",
    )
    activist_person = SimpleNamespace(
        cik="0001111111",
        name="Activist Capital",
        citizenship="Delaware",
        sole_voting_power=5_000_000,
        shared_voting_power=250_000,
        sole_dispositive_power=5_000_000,
        shared_dispositive_power=250_000,
        aggregate_amount=5_250_000,
        percent_of_class=6.8,
        type_of_reporting_person="IA",
        fund_type="HF",
        comment=None,
        member_of_group=None,
        is_aggregate_exclude_shares=False,
        no_cik=False,
    )
    passive_person = SimpleNamespace(
        cik="",
        name="Index Manager LLC",
        citizenship="Delaware",
        sole_voting_power=0,
        shared_voting_power=4_100_000,
        sole_dispositive_power=0,
        shared_dispositive_power=4_100_000,
        aggregate_amount=4_100_000,
        percent_of_class=5.1,
        type_of_reporting_person="IA",
        fund_type=None,
        comment=None,
        member_of_group=None,
        is_aggregate_exclude_shares=False,
        no_cik=True,
    )
    schedule_13d = SimpleNamespace(
        issuer_info=SimpleNamespace(name="NVIDIA Corporation", cik="0001045810", cusip="67066G104", address=issuer_address),
        security_info=SimpleNamespace(title="Common Stock", cusip="67066G104"),
        reporting_persons=[activist_person],
        items=SimpleNamespace(
            item3_source_of_funds="Working capital.",
            item4_purpose_of_transaction=(
                "The filer may engage management regarding capital allocation and board composition."
            ),
            item5_transactions="Open-market purchases in February 2026.",
            item10_certification=None,
        ),
        date_of_event="2026-02-15",
        event_date=None,
        previously_filed=False,
        amendment_number=None,
        is_amendment=False,
        rule_designation=None,
        is_passive_investor=False,
        total_shares=5_250_000,
        total_percent=6.8,
    )
    schedule_13g = SimpleNamespace(
        issuer_info=SimpleNamespace(name="NVIDIA Corporation", cik="0001045810", cusip="67066G104", address=issuer_address),
        security_info=SimpleNamespace(title="Common Stock", cusip="67066G104"),
        reporting_persons=[passive_person],
        items=SimpleNamespace(
            item3_source_of_funds=None,
            item4_purpose_of_transaction=None,
            item5_transactions=None,
            item10_certification="Passive investor certification.",
        ),
        date_of_event=None,
        event_date="2026-01-10",
        previously_filed=False,
        amendment_number=2,
        is_amendment=True,
        rule_designation="Rule 13d-1(b)",
        is_passive_investor=True,
        total_shares=4_100_000,
        total_percent=5.1,
    )
    filings = [
        SimpleNamespace(
            accession_no="0001045810-26-000020",
            form="SC 13D",
            filing_date="2026-02-20",
            obj=lambda: schedule_13d,
        ),
        SimpleNamespace(
            accession_no="0001045810-26-000010",
            form="SC 13G/A",
            filing_date="2026-01-12",
            obj=lambda: schedule_13g,
        ),
        SimpleNamespace(
            accession_no="0001045810-26-000005",
            form="10-K",
            filing_date="2026-01-01",
            obj=lambda: None,
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self, **kwargs):
            assert kwargs == {
                "filing_date": "2026-01-01:2026-12-31",
                "amendments": True,
            }
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    rows = analytics.get_beneficial_ownership(
        ticker="NVDA",
        start_date="2026-01-01",
        end_date="2026-12-31",
        limit=10,
    )

    assert [row["accession_number"] for row in rows] == [
        "0001045810-26-000020",
        "0001045810-26-000010",
    ]
    assert rows[0]["issuer_name"] == "NVIDIA Corporation"
    assert rows[0]["issuer_address"] == "123 Market St, San Francisco, CA, 94105"
    assert rows[0]["total_shares"] == 5_250_000
    assert rows[0]["total_percent"] == 6.8
    assert rows[0]["reporting_person_names"] == ["Activist Capital"]
    assert rows[0]["reporting_persons"][0]["total_voting_power"] == 5_250_000
    assert "capital allocation" in rows[0]["purpose_of_transaction"]
    assert rows[1]["form_type"] == "SC 13G/A"
    assert rows[1]["is_amendment"] is True
    assert rows[1]["amendment_number"] == 2
    assert rows[1]["rule_designation"] == "Rule 13d-1(b)"
    assert rows[1]["is_passive_investor"] is True
    assert rows[1]["certification"] == "Passive investor certification."


def test_summarize_beneficial_ownership_returns_latest_snapshot_and_history(monkeypatch):
    schedule_13d = SimpleNamespace(
        issuer_info=SimpleNamespace(name="NVIDIA Corporation", cik="0001045810", cusip="67066G104", address=None),
        security_info=SimpleNamespace(title="Common Stock", cusip="67066G104"),
        reporting_persons=[
            SimpleNamespace(
                cik="0001111111",
                name="Activist Capital",
                citizenship="Delaware",
                sole_voting_power=5_000_000,
                shared_voting_power=0,
                sole_dispositive_power=5_000_000,
                shared_dispositive_power=0,
                aggregate_amount=5_000_000,
                percent_of_class=6.4,
                type_of_reporting_person="IA",
                fund_type="HF",
                comment=None,
                member_of_group=None,
                is_aggregate_exclude_shares=False,
                no_cik=False,
            )
        ],
        items=SimpleNamespace(
            item3_source_of_funds="Working capital.",
            item4_purpose_of_transaction="Potential strategic engagement.",
            item5_transactions=None,
            item10_certification=None,
        ),
        date_of_event="2026-02-15",
        event_date=None,
        previously_filed=False,
        amendment_number=None,
        is_amendment=False,
        rule_designation=None,
        is_passive_investor=False,
        total_shares=5_000_000,
        total_percent=6.4,
    )
    schedule_13g = SimpleNamespace(
        issuer_info=SimpleNamespace(name="NVIDIA Corporation", cik="0001045810", cusip="67066G104", address=None),
        security_info=SimpleNamespace(title="Common Stock", cusip="67066G104"),
        reporting_persons=[
            SimpleNamespace(
                cik="",
                name="Index Manager LLC",
                citizenship="Delaware",
                sole_voting_power=0,
                shared_voting_power=4_000_000,
                sole_dispositive_power=0,
                shared_dispositive_power=4_000_000,
                aggregate_amount=4_000_000,
                percent_of_class=5.0,
                type_of_reporting_person="IA",
                fund_type=None,
                comment=None,
                member_of_group=None,
                is_aggregate_exclude_shares=False,
                no_cik=True,
            )
        ],
        items=SimpleNamespace(
            item3_source_of_funds=None,
            item4_purpose_of_transaction=None,
            item5_transactions=None,
            item10_certification="Passive investor certification.",
        ),
        date_of_event=None,
        event_date="2026-01-10",
        previously_filed=False,
        amendment_number=1,
        is_amendment=True,
        rule_designation="Rule 13d-1(b)",
        is_passive_investor=True,
        total_shares=4_000_000,
        total_percent=5.0,
    )
    filings = [
        SimpleNamespace(
            accession_no="0001045810-26-000020",
            form="SC 13D",
            filing_date="2026-02-20",
            obj=lambda: schedule_13d,
        ),
        SimpleNamespace(
            accession_no="0001045810-26-000010",
            form="SC 13G/A",
            filing_date="2026-01-12",
            obj=lambda: schedule_13g,
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            assert ticker == "NVDA"

        def get_filings(self, **kwargs):
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    summary = analytics.summarize_beneficial_ownership("NVDA", limit=10)

    assert summary["issuer_name"] == "NVIDIA Corporation"
    assert summary["filings_count"] == 2
    assert summary["latest_accession_number"] == "0001045810-26-000020"
    assert summary["latest_form_type"] == "SC 13D"
    assert summary["latest_total_percent"] == 6.4
    assert summary["latest_reporting_person_names"] == ["Activist Capital"]
    assert summary["latest_purpose_of_transaction"] == "Potential strategic engagement."
    assert summary["form_types_present"] == ["SC 13D", "SC 13G/A"]
    assert len(summary["history"]) == 2
    assert summary["history"][1]["form_type"] == "SC 13G/A"