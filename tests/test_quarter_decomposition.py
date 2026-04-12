"""Unit tests for quarter decomposition and period labels."""

from datetime import date

import pandas as pd
import pytest

from investment_researcher.ingestion.edgar.financials import (
    _extract_from_raw_df,
    _make_period_label,
    _select_annual_flow_rows,
)


class TestQuarterDecomposition:
    """Verify YTD→discrete-quarter subtraction produces correct values.

    Uses synthetic data with known values to test:
    - Q2 = YTD_6M − Q1
    - Q3 = YTD_9M − YTD_6M
    - Q4 = FY − YTD_9M
    - sum(Q1..Q4) = FY
    """

    def _build_raw_df(
        self,
        q1_val: float = 100.0,
        ytd_6m_val: float = 250.0,
        ytd_9m_val: float = 400.0,
        fy_val: float = 600.0,
        concept: str = "us-gaap:Revenues",
    ) -> pd.DataFrame:
        """Build a synthetic raw DataFrame mimicking edgartools to_dataframe()."""
        fy_year = 2024
        # Apple-like fiscal year: Oct 1 - Sep 30
        rows = [
            # Q1: Oct 1 - Dec 31 (92 days)
            {
                "concept": concept,
                "period_start": date(2023, 10, 1),
                "period_end": date(2023, 12, 31),
                "numeric_value": q1_val,
                "unit": "USD",
                "fiscal_period": "Q1",
                "fiscal_year": fy_year,
            },
            # YTD 6M: Oct 1 - Mar 31 (182 days)
            {
                "concept": concept,
                "period_start": date(2023, 10, 1),
                "period_end": date(2024, 3, 31),
                "numeric_value": ytd_6m_val,
                "unit": "USD",
                "fiscal_period": "Q2",
                "fiscal_year": fy_year,
            },
            # YTD 9M: Oct 1 - Jun 30 (274 days)
            {
                "concept": concept,
                "period_start": date(2023, 10, 1),
                "period_end": date(2024, 6, 30),
                "numeric_value": ytd_9m_val,
                "unit": "USD",
                "fiscal_period": "Q3",
                "fiscal_year": fy_year,
            },
            # FY: Oct 1 - Sep 30 (366 days)
            {
                "concept": concept,
                "period_start": date(2023, 10, 1),
                "period_end": date(2024, 9, 30),
                "numeric_value": fy_val,
                "unit": "USD",
                "fiscal_period": "FY",
                "fiscal_year": fy_year,
            },
        ]
        return pd.DataFrame(rows)

    def _extract_metric(self, raw_df, metric_type="revenue"):
        """Run _extract_from_raw_df and return the resulting rows."""
        all_rows: list[dict] = []
        _extract_from_raw_df(
            raw_df, ticker="TEST", cik="999999",
            target_metrics={metric_type}, all_rows=all_rows,
        )
        return all_rows

    def _get_value(self, rows, period_type, period_end):
        """Get value for a specific period from extracted rows."""
        for r in rows:
            pe = r["period_end"]
            if isinstance(pe, str):
                pe = date.fromisoformat(pe)
            if r["period_type"] == period_type and pe == period_end:
                return r["value"]
        return None

    def test_q2_derived_from_ytd(self):
        """Q2 = YTD_6M - Q1."""
        raw_df = self._build_raw_df(q1_val=100, ytd_6m_val=250)
        rows = self._extract_metric(raw_df)
        q2 = self._get_value(rows, "quarterly", date(2024, 3, 31))
        assert q2 is not None, "Q2 should be derived"
        assert q2 == pytest.approx(150.0), f"Q2 = 250 - 100 = 150, got {q2}"

    def test_q3_derived_from_ytd(self):
        """Q3 = YTD_9M - YTD_6M."""
        raw_df = self._build_raw_df(ytd_6m_val=250, ytd_9m_val=400)
        rows = self._extract_metric(raw_df)
        q3 = self._get_value(rows, "quarterly", date(2024, 6, 30))
        assert q3 is not None, "Q3 should be derived"
        assert q3 == pytest.approx(150.0), f"Q3 = 400 - 250 = 150, got {q3}"

    def test_q4_derived_from_annual(self):
        """Q4 = FY - YTD_9M."""
        raw_df = self._build_raw_df(ytd_9m_val=400, fy_val=600)
        rows = self._extract_metric(raw_df)
        q4 = self._get_value(rows, "quarterly", date(2024, 9, 30))
        assert q4 is not None, "Q4 should be derived"
        assert q4 == pytest.approx(200.0), f"Q4 = 600 - 400 = 200, got {q4}"

    def test_quarters_sum_to_annual(self):
        """Q1 + Q2 + Q3 + Q4 should equal FY."""
        q1, q2, q3, q4 = 100.0, 150.0, 150.0, 200.0
        fy = q1 + q2 + q3 + q4  # 600
        raw_df = self._build_raw_df(
            q1_val=q1,
            ytd_6m_val=q1 + q2,      # 250
            ytd_9m_val=q1 + q2 + q3,  # 400
            fy_val=fy,                 # 600
        )
        rows = self._extract_metric(raw_df)

        annual = self._get_value(rows, "annual", date(2024, 9, 30))
        assert annual == pytest.approx(fy)

        quarterly_sum = sum(
            r["value"] for r in rows if r["period_type"] == "quarterly"
        )
        assert quarterly_sum == pytest.approx(fy), (
            f"Sum of quarters ({quarterly_sum}) != FY ({fy})"
        )

    def test_negative_values_decompose_correctly(self):
        """Decomposition works for metrics with negative values (e.g., net loss)."""
        raw_df = self._build_raw_df(
            q1_val=-50, ytd_6m_val=-120, ytd_9m_val=-200, fy_val=-280,
        )
        rows = self._extract_metric(raw_df)

        q2 = self._get_value(rows, "quarterly", date(2024, 3, 31))
        q3 = self._get_value(rows, "quarterly", date(2024, 6, 30))
        q4 = self._get_value(rows, "quarterly", date(2024, 9, 30))

        assert q2 == pytest.approx(-70.0), f"Q2 = -120 - (-50) = -70, got {q2}"
        assert q3 == pytest.approx(-80.0), f"Q3 = -200 - (-120) = -80, got {q3}"
        assert q4 == pytest.approx(-80.0), f"Q4 = -280 - (-200) = -80, got {q4}"

    def test_ignores_non_fy_annual_candidates_for_flow_metrics(self):
        raw_df = pd.DataFrame([
            {
                "concept": "us-gaap:NetIncomeLoss",
                "period_start": date(2022, 7, 1),
                "period_end": date(2023, 6, 30),
                "numeric_value": 500.0,
                "unit": "USD",
                "fiscal_period": "Q2",
                "fiscal_year": 2023,
            },
            {
                "concept": "us-gaap:NetIncomeLoss",
                "period_start": date(2022, 10, 1),
                "period_end": date(2023, 9, 30),
                "numeric_value": 550.0,
                "unit": "USD",
                "fiscal_period": "Q3",
                "fiscal_year": 2023,
            },
            {
                "concept": "us-gaap:NetIncomeLoss",
                "period_start": date(2023, 4, 1),
                "period_end": date(2023, 6, 30),
                "numeric_value": 125.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "fiscal_year": 2023,
            },
            {
                "concept": "us-gaap:NetIncomeLoss",
                "period_start": date(2023, 1, 1),
                "period_end": date(2023, 12, 31),
                "numeric_value": 600.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "fiscal_year": 2023,
            },
        ])

        rows = self._extract_metric(raw_df, metric_type="net_income")

        annual_periods = sorted(
            r["period_end"]
            for r in rows
            if r["period_type"] == "annual"
        )
        assert annual_periods == [date(2023, 12, 31)]
        assert self._get_value(rows, "annual", date(2023, 6, 30)) is None
        assert self._get_value(rows, "annual", date(2023, 9, 30)) is None
        assert self._get_value(rows, "annual", date(2023, 12, 31)) == pytest.approx(600.0)

    def test_prefers_best_duplicate_fy_row_for_same_period_end(self):
        ts_df = pd.DataFrame([
            {
                "period_end": date(2024, 12, 31),
                "numeric_value": 14_200_000_000.0,
                "fiscal_period": "FY",
                "fiscal_year": 2024,
            },
            {
                "period_end": date(2024, 12, 31),
                "numeric_value": 637_959_000_000.0,
                "fiscal_period": "FY",
                "fiscal_year": 2025,
            },
            {
                "period_end": date(2025, 12, 31),
                "numeric_value": 17_400_000_000.0,
                "fiscal_period": "FY",
                "fiscal_year": 2025,
            },
            {
                "period_end": date(2025, 12, 31),
                "numeric_value": 716_924_000_000.0,
                "fiscal_period": "FY",
                "fiscal_year": 2025,
            },
        ])

        selected = _select_annual_flow_rows(ts_df)

        rows = {
            row.period_end: row.numeric_value
            for row in selected.itertuples()
        }
        assert rows == {
            date(2024, 12, 31): pytest.approx(637_959_000_000.0),
            date(2025, 12, 31): pytest.approx(716_924_000_000.0),
        }

    def test_make_period_label_quarterly(self):
        assert _make_period_label(date(2024, 9, 30), "quarterly") == "Quarter Ended 09/30/2024"

    def test_make_period_label_annual(self):
        assert _make_period_label(date(2024, 9, 30), "annual") == "Twelve Months Ended 09/30/2024"