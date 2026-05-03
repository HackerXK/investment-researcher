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