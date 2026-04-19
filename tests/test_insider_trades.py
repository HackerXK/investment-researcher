from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from investment_researcher import analytics


def test_get_filings_list_supports_date_range_and_amendments(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCompany:
        def __init__(self, ticker: str):
            captured["ticker"] = ticker

        def get_filings(self, **kwargs):
            captured["kwargs"] = kwargs
            return [
                SimpleNamespace(
                    accession_no="0000320193-24-000001",
                    form="4",
                    filing_date="2024-01-05",
                    primary_doc_url="https://example.test/form4",
                    description="Statement of changes in beneficial ownership",
                )
            ]

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    results = analytics.get_filings_list(
        ticker="AAPL",
        form_type="4",
        limit=10,
        start_date="2024-01-01",
        end_date="2024-12-31",
        include_amendments=False,
    )

    assert captured["ticker"] == "AAPL"
    assert captured["kwargs"] == {
        "form": "4",
        "filing_date": "2024-01-01:2024-12-31",
        "amendments": False,
    }
    assert results == [
        {
            "accession_number": "0000320193-24-000001",
            "form_type": "4",
            "filing_date": "2024-01-05",
            "primary_document": "https://example.test/form4",
            "description": "Statement of changes in beneficial ownership",
        }
    ]


def test_get_insider_trades_returns_structured_dated_sales(monkeypatch):
    captured: dict[str, object] = {}

    def fake_form4(insider_name: str, position: str, rows: list[dict[str, object]]):
        tx_df = pd.DataFrame(rows)
        return SimpleNamespace(
            non_derivative_table=SimpleNamespace(
                transactions=SimpleNamespace(data=tx_df)
            ),
            get_ownership_summary=lambda: SimpleNamespace(
                insider_name=insider_name,
                position=position,
                primary_activity="Sale",
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
                        "form": "4",
                        "Code": "S",
                        "TransactionType": "sale",
                        "EquitySwap": "",
                        "footnotes": "",
                    },
                    {
                        "Date": "2024-06-01",
                        "Security": "Common Stock",
                        "Shares": 250,
                        "Remaining": 119_750,
                        "Price": 200.0,
                        "AcquiredDisposed": "A",
                        "DirectIndirect": "D",
                        "NatureOfOwnership": "Direct",
                        "form": "4",
                        "Code": "P",
                        "TransactionType": "purchase",
                        "EquitySwap": "",
                        "footnotes": "",
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
                        "form": "4",
                        "Code": "F",
                        "TransactionType": "tax",
                        "EquitySwap": "",
                        "footnotes": "",
                    },
                    {
                        "Date": "2025-02-14",
                        "Security": "Common Stock",
                        "Shares": 1_000,
                        "Remaining": 79_000,
                        "Price": 185.0,
                        "AcquiredDisposed": "D",
                        "DirectIndirect": "D",
                        "NatureOfOwnership": "Direct",
                        "form": "4",
                        "Code": "G",
                        "TransactionType": "gift",
                        "EquitySwap": "",
                        "footnotes": "",
                    },
                ],
            ),
        ),
    ]

    class FakeCompany:
        def __init__(self, ticker: str):
            captured["ticker"] = ticker

        def get_filings(self, **kwargs):
            captured["kwargs"] = kwargs
            return filings

    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany))

    trades = analytics.get_insider_trades(
        ticker="AAPL",
        start_date="2024-01-01",
        end_date="2025-12-31",
        transaction_codes=["S", "F"],
        acquired_disposed="D",
        min_value=100_000,
        limit=10,
        include_amendments=False,
    )

    assert captured["ticker"] == "AAPL"
    assert captured["kwargs"] == {
        "form": "4",
        "filing_date": "2024-01-01:2025-12-31",
        "amendments": False,
    }

    assert [trade["accession_number"] for trade in trades] == [
        "0000320193-24-000111",
        "0000320193-25-000222",
    ]
    assert trades[0]["tx_date"] == "2024-06-01"
    assert trades[0]["insider_name"] == "Jane Executive"
    assert trades[0]["transaction_code"] == "S"
    assert trades[0]["proceeds"] == 1_050_000
    assert trades[0]["classification"] == "Very notable"
    assert trades[1]["transaction_code"] == "F"
    assert trades[1]["is_tax_withholding"] is True
    assert trades[1]["proceeds"] == 380_000
    assert trades[1]["classification"] == "Notable"