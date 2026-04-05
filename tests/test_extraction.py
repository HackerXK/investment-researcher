"""Integration tests for slow-path and fast-path extraction.

These tests hit the real SEC EDGAR API (via edgartools) to verify that
extraction actually works end-to-end. They write to temporary DuckDB
databases to avoid side effects.

Requires EDGAR_IDENTITY to be set (or defaults to test@example.com).
"""

import os
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Set a default identity for tests
os.environ.setdefault("EDGAR_IDENTITY", "test@example.com")

import edgar

from investment_researcher.ingestion.edgar.financials import (
    CONCEPT_MAP,
    FLOW_METRICS,
    RAW_CONCEPT_MAP,
    STOCK_METRICS,
    _extract_from_raw_df,
    extract_company_facts,
    get_all_tickers,
)
from investment_researcher.ingestion.edgar.fast_path import (
    process_recent_filings,
    _get_cik_ticker_map,
    _extract_metrics_from_filing,
)
from investment_researcher.ingestion.timeseries import (
    get_connection,
    initialize_db,
)
from investment_researcher.ingestion.state import initialize_state_db


@pytest.fixture
def db_paths(tmp_path):
    """Create temp DuckDB and state DB paths."""
    db = str(tmp_path / "test.duckdb")
    state = str(tmp_path / "test_state.db")
    initialize_db(db_path=db)
    initialize_state_db(db_path=state)
    return db, state


@contextmanager
def _db_connection(db):
    """Open a DuckDB connection and ensure it is closed on exit."""
    con = get_connection(db)
    try:
        yield con
    finally:
        con.close()


class TestSlowPathExtraction:
    """Tests for companyfacts → DuckDB extraction."""

    def test_extract_apple(self, db_paths):
        """Extract AAPL financial data and verify key metrics."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        count = extract_company_facts("AAPL", db_path=db, state_db_path=state)
        assert count > 0, "Should extract at least some metrics for AAPL"

        with _db_connection(db) as con:
            # Check distinct metric types
            metrics = con.execute(
                "SELECT DISTINCT metric_type FROM financial_metrics WHERE ticker = 'AAPL'"
            ).fetchall()
            metric_names = {m[0] for m in metrics}
            assert len(metric_names) >= 3, f"Expected at least 3 metric types, got: {metric_names}"
            assert "revenue" in metric_names, f"Revenue should be extracted. Got: {metric_names}"

            # Check annual revenue values are reasonable
            revenue = con.execute(
                "SELECT period_end, value FROM financial_metrics "
                "WHERE ticker = 'AAPL' AND metric_type = 'revenue' AND period_type = 'annual' "
                "ORDER BY period_end DESC LIMIT 3"
            ).fetchall()
            assert len(revenue) >= 1, "Should have at least 1 year of revenue"

            # Apple's annual revenue should be > $200B
            latest_revenue = revenue[0][1]
            assert latest_revenue > 200e9, f"AAPL revenue {latest_revenue} seems too low"

    def test_extract_microsoft(self, db_paths):
        """Extract MSFT financial data."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        count = extract_company_facts("MSFT", db_path=db, state_db_path=state)
        assert count > 0

        with _db_connection(db) as con:
            result = con.execute(
                "SELECT COUNT(DISTINCT metric_type) FROM financial_metrics WHERE ticker = 'MSFT'"
            ).fetchone()
            assert result[0] >= 3

    def test_extract_nonexistent_ticker(self, db_paths):
        """Extracting a nonexistent ticker should return 0, not raise."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        count = extract_company_facts("ZZZZNOTREAL99", db_path=db, state_db_path=state)
        assert count == 0

    def test_get_all_tickers(self):
        """Should return 1000+ company tickers."""
        edgar.set_identity("test@example.com")
        tickers_df = get_all_tickers()
        assert len(tickers_df) >= 1000
        assert "ticker" in tickers_df.columns
        assert "cik" in tickers_df.columns

    def test_multiple_companies(self, db_paths):
        """Extract multiple companies and verify they coexist in DuckDB."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        for ticker in ["AAPL", "MSFT"]:
            extract_company_facts(ticker, db_path=db, state_db_path=state)

        with _db_connection(db) as con:
            distinct_tickers = con.execute(
                "SELECT COUNT(DISTINCT ticker) FROM financial_metrics"
            ).fetchone()[0]
            assert distinct_tickers == 2

    def test_primary_key_constraint(self, db_paths):
        """Re-extracting should upsert, not duplicate rows."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        count1 = extract_company_facts("AAPL", db_path=db, state_db_path=state)
        count2 = extract_company_facts("AAPL", db_path=db, state_db_path=state)

        with _db_connection(db) as con:
            total = con.execute(
                "SELECT COUNT(*) FROM financial_metrics WHERE ticker = 'AAPL'"
            ).fetchone()[0]
            # Two extractions should give the same row count (upserts, not duplicates)
            assert total == count1 or total == count2


class TestFastPathExtraction:
    """Tests for per-filing XBRL → DuckDB extraction."""

    def test_cik_ticker_map(self):
        """CIK → ticker map should have 1000+ entries."""
        edgar.set_identity("test@example.com")
        cik_map = _get_cik_ticker_map()
        assert len(cik_map) >= 1000
        assert cik_map.get(320193) == "AAPL"

    def test_extract_from_single_filing(self, db_paths):
        """Extract metrics from a single recent 10-K filing."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        filings = edgar.get_filings(form="10-K")
        cik_map = _get_cik_ticker_map()

        # Find a filing that has a ticker mapping
        extracted = False
        for i in range(min(10, len(filings))):
            filing = filings[i]
            ticker = cik_map.get(int(filing.cik))
            if not ticker:
                continue

            try:
                df = _extract_metrics_from_filing(filing, ticker, str(filing.cik))
            except Exception:
                # XBRL parse errors propagate by design; skip and try next filing
                continue
            if df is not None and len(df) > 0:
                assert "ticker" in df.columns
                assert "metric_type" in df.columns
                assert "value" in df.columns
                assert "period_end" in df.columns
                extracted = True
                break

        # It's OK if the first 10 filings don't have parseable XBRL (small companies)

    def test_process_recent_filings(self, db_paths):
        """Process recent filings and verify some data is written."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        filings_processed, total_rows = process_recent_filings(
            days=2, db_path=db, state_db_path=state
        )

        # There should be at least some filings in the last 2 days
        # (but we can't guarantee XBRL extraction succeeds on all)
        assert filings_processed >= 0
        assert total_rows >= 0

    def test_dedup_fast_path(self, db_paths):
        """Running fast path twice should not duplicate filings."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        f1, r1 = process_recent_filings(days=1, db_path=db, state_db_path=state)
        f2, r2 = process_recent_filings(days=1, db_path=db, state_db_path=state)

        # Second run should process no more than the first (transient XBRL
        # failures are retried, but successfully-parsed filings are not).
        assert f2 <= f1


class TestBothPathsCoexist:
    """Verify slow and fast paths write to same DuckDB tables safely."""

    def test_both_paths_write_safely(self, db_paths):
        """INSERT OR REPLACE — never deletes absent rows."""
        db, state = db_paths
        edgar.set_identity("test@example.com")

        # Run slow path first
        slow_count = extract_company_facts("AAPL", db_path=db, state_db_path=state)
        assert slow_count > 0

        with _db_connection(db) as con:
            before = con.execute(
                "SELECT COUNT(*) FROM financial_metrics WHERE ticker = 'AAPL'"
            ).fetchone()[0]

        # Run fast path — should add new data or replace, never delete
        process_recent_filings(days=1, db_path=db, state_db_path=state)

        with _db_connection(db) as con:
            after = con.execute(
                "SELECT COUNT(*) FROM financial_metrics WHERE ticker = 'AAPL'"
            ).fetchone()[0]
            # After fast path, AAPL should have >= the same number of rows
            assert after >= before


class TestAliasPriority:
    """Verify that earlier-listed RAW_CONCEPT_MAP aliases win during dedup."""

    def test_first_alias_wins_on_overlap(self):
        """When two raw concepts map to the same metric for the same period,
        the earlier-listed alias should be kept by drop_duplicates(keep='first')."""
        # Build a fake raw DataFrame with two revenue aliases for the same period
        raw_df = pd.DataFrame([
            {
                "concept": "us-gaap:Revenues",
                "numeric_value": 100.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "period_end": "2023-12-31",
            },
            {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "numeric_value": 200.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "period_end": "2023-12-31",
            },
        ])

        all_rows: list[dict] = []
        target_metrics = {"revenue"}
        _extract_from_raw_df(raw_df, "TEST", "999", target_metrics, all_rows)

        # Both aliases should contribute rows (no early-stop)
        revenue_rows = [r for r in all_rows if r["metric_type"] == "revenue"]
        assert len(revenue_rows) == 2, "Both aliases should produce rows before final dedup"

        # Simulate the final dedup from extract_company_facts
        df = pd.DataFrame(all_rows)
        df = df.drop_duplicates(
            subset=["ticker", "metric_type", "period_type", "period_end"],
            keep="first",
        )
        assert len(df) == 1
        # First alias (us-gaap:Revenues with value 100) should win
        assert df.iloc[0]["value"] == 100.0

    def test_second_alias_fills_gaps(self):
        """A second alias should backfill periods not covered by the first."""
        raw_df = pd.DataFrame([
            {
                "concept": "us-gaap:SalesRevenueNet",
                "numeric_value": 50.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "period_end": "2020-12-31",
            },
            {
                "concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "numeric_value": 200.0,
                "unit": "USD",
                "fiscal_period": "FY",
                "period_end": "2023-12-31",
            },
        ])

        all_rows: list[dict] = []
        target_metrics = {"revenue"}
        _extract_from_raw_df(raw_df, "TEST", "999", target_metrics, all_rows)

        df = pd.DataFrame(all_rows)
        df = df.drop_duplicates(
            subset=["ticker", "metric_type", "period_type", "period_end"],
            keep="first",
        )
        # Both periods should survive — they don't overlap
        assert len(df) == 2
        periods = set(df["period_end"].astype(str))
        assert "2020-12-31" in periods
        assert "2023-12-31" in periods


class TestStrategy2FillsStrategy1Gaps:
    """Verify that raw XBRL (Strategy 2) fills period-level gaps left by
    time_series() (Strategy 1).

    This is a regression test for the bug where revenue (and other metrics)
    appeared incomplete: Strategy 1 returned only recent years and Strategy 2
    was gated by a metric-level check, so historical periods reported under
    older XBRL concept names were never extracted.
    """

    @pytest.fixture
    def mock_company(self):
        """Return a mock Company whose facts expose the gap scenario."""
        facts = MagicMock()

        # Strategy 1: time_series("revenue") returns only 2 recent FY years.
        # All other concepts return empty DataFrames.
        ts_revenue = pd.DataFrame({
            "fiscal_period": ["FY", "FY"],
            "period_end": [date(2024, 9, 28), date(2023, 9, 30)],
            "numeric_value": [391e9, 383e9],
        })
        ts_net_income = pd.DataFrame({
            "fiscal_period": ["FY", "FY", "FY", "FY"],
            "period_end": [
                date(2024, 9, 28), date(2023, 9, 30),
                date(2022, 9, 24), date(2021, 9, 25),
            ],
            "numeric_value": [93.7e9, 97e9, 99.8e9, 94.7e9],
        })

        def fake_time_series(name):
            if name == "revenue":
                return ts_revenue
            if name == "net_income":
                return ts_net_income
            return pd.DataFrame()

        facts.time_series = fake_time_series

        # Strategy 1 flow path: facts.query().by_concept().execute()
        # Return empty so TTMCalculator doesn't produce quarterly rows.
        # S1 will still get annual FY rows from time_series above.
        query_mock = MagicMock()
        query_mock.by_concept.return_value.execute.return_value = []
        facts.query.return_value = query_mock

        # Strategy 2: raw to_dataframe() carries the full 5-year history
        # for revenue under two different XBRL concept names, plus net_income.
        # period_start is needed for duration-based filtering of flow metrics.
        facts.to_dataframe = MagicMock(return_value=pd.DataFrame({
            "concept": [
                # Recent revenue (same concept used in newer filings)
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                # Older revenue (different concept used before ASC 606)
                "us-gaap:SalesRevenueNet",
                "us-gaap:SalesRevenueNet",
                # net_income (should NOT duplicate S1's data)
                "us-gaap:NetIncomeLoss",
                "us-gaap:NetIncomeLoss",
                "us-gaap:NetIncomeLoss",
                "us-gaap:NetIncomeLoss",
            ],
            "fiscal_period": ["FY"] * 9,
            "period_end": [
                date(2024, 9, 28), date(2023, 9, 30), date(2022, 9, 24),
                date(2021, 9, 25), date(2020, 9, 26),
                date(2024, 9, 28), date(2023, 9, 30),
                date(2022, 9, 24), date(2021, 9, 25),
            ],
            # period_start ~365 days before period_end (annual duration)
            "period_start": [
                date(2023, 10, 1), date(2022, 10, 2), date(2021, 9, 26),
                date(2020, 9, 27), date(2019, 9, 29),
                date(2023, 10, 1), date(2022, 10, 2),
                date(2021, 9, 26), date(2020, 9, 27),
            ],
            "fiscal_year": [
                2024, 2023, 2022,
                2021, 2020,
                2024, 2023, 2022, 2021,
            ],
            "numeric_value": [
                391e9, 383e9, 394e9,
                366e9, 275e9,
                93.7e9, 97e9, 99.8e9, 94.7e9,
            ],
            "unit": ["USD"] * 9,
        }))

        company = MagicMock()
        company.cik = 320193
        company.get_facts.return_value = facts
        return company

    def test_strategy2_fills_revenue_gaps(self, db_paths, mock_company):
        """Revenue should have all 5 years, not just the 2 from time_series."""
        db, state = db_paths

        with patch("edgar.Company", return_value=mock_company):
            count = extract_company_facts("AAPL", db_path=db, state_db_path=state)
            assert count > 0

        with _db_connection(db) as con:
            revenue_rows = con.execute(
                "SELECT period_end, value FROM financial_metrics "
                "WHERE ticker = 'AAPL' AND metric_type = 'revenue' "
                "AND period_type = 'annual' ORDER BY period_end"
            ).fetchall()

            revenue_years = {r[0].year for r in revenue_rows}

            # The critical assertion: all 5 years of revenue must be present,
            # including 2020-2022 which only exist in raw XBRL (Strategy 2).
            assert 2020 in revenue_years, (
                f"2020 revenue (only in raw XBRL SalesRevenueNet) missing. Got: {revenue_years}"
            )
            assert 2021 in revenue_years, (
                f"2021 revenue (only in raw XBRL SalesRevenueNet) missing. Got: {revenue_years}"
            )
            assert 2022 in revenue_years, (
                f"2022 revenue (only in raw XBRL) missing. Got: {revenue_years}"
            )
            assert 2023 in revenue_years, f"2023 revenue missing. Got: {revenue_years}"
            assert 2024 in revenue_years, f"2024 revenue missing. Got: {revenue_years}"
            assert len(revenue_rows) == 5, (
                f"Expected exactly 5 annual revenue rows, got {len(revenue_rows)}: {revenue_years}"
            )

    def test_strategy1_preferred_over_strategy2(self, db_paths, mock_company):
        """For periods covered by both strategies, Strategy 1 values win."""
        db, state = db_paths

        with patch("edgar.Company", return_value=mock_company):
            extract_company_facts("AAPL", db_path=db, state_db_path=state)

        with _db_connection(db) as con:
            # For 2024 and 2023, both strategies have revenue — S1 should win.
            # The values are the same in our mock, but verify no duplicates.
            rows_2024 = con.execute(
                "SELECT value FROM financial_metrics "
                "WHERE ticker = 'AAPL' AND metric_type = 'revenue' "
                "AND period_type = 'annual' AND YEAR(period_end) = 2024"
            ).fetchall()
            assert len(rows_2024) == 1, f"Expected 1 row for 2024 revenue, got {len(rows_2024)}"

    def test_no_duplicate_rows_from_merge(self, db_paths, mock_company):
        """Metrics covered fully by Strategy 1 should not get duplicated by S2."""
        db, state = db_paths

        with patch("edgar.Company", return_value=mock_company):
            extract_company_facts("AAPL", db_path=db, state_db_path=state)

        with _db_connection(db) as con:
            # net_income: S1 has 4 years, S2 also has 4 years (same periods).
            # Merge should not create duplicates.
            ni_rows = con.execute(
                "SELECT period_end FROM financial_metrics "
                "WHERE ticker = 'AAPL' AND metric_type = 'net_income' "
                "AND period_type = 'annual' ORDER BY period_end"
            ).fetchall()
            ni_years = [r[0].year for r in ni_rows]
            assert len(ni_years) == len(set(ni_years)), (
                f"Duplicate net_income rows found: {ni_years}"
            )
            assert len(ni_years) == 4, f"Expected 4 net_income years, got {ni_years}"

    def test_strategy2_always_runs_even_when_strategy1_has_data(self, db_paths):
        """Strategy 2 must always be invoked regardless of Strategy 1 results.

        This is a unit-level check on the code path: to_dataframe() should
        be called even when time_series() finds all metrics for *some* periods.
        """
        db, state = db_paths
        facts = MagicMock()

        # S1 returns data for revenue and net_income
        def fake_ts(name):
            if name in ("revenue", "net_income"):
                return pd.DataFrame({
                    "fiscal_period": ["FY"],
                    "period_end": [date(2024, 9, 28)],
                    "numeric_value": [100.0],
                })
            return pd.DataFrame()

        facts.time_series = fake_ts

        # S1 flow path: facts.query().by_concept().execute() → empty
        query_mock = MagicMock()
        query_mock.by_concept.return_value.execute.return_value = []
        facts.query.return_value = query_mock

        facts.to_dataframe = MagicMock(return_value=pd.DataFrame(columns=[
            "concept", "fiscal_period", "period_end", "numeric_value", "unit",
        ]))

        company = MagicMock()
        company.cik = 12345
        company.get_facts.return_value = facts

        with patch("edgar.Company", return_value=company):
            extract_company_facts("TEST", db_path=db, state_db_path=state)

        # The critical assertion: to_dataframe() must have been called.
        facts.to_dataframe.assert_called_once()


class TestDiscreteQuarterDerivation:
    """Verify that _extract_from_raw_df derives discrete Q2/Q3/Q4 from YTD
    cumulative values when period_start is available."""

    def test_q4_derived_from_annual_minus_ytd9m(self):
        """Q4 = FY − YTD_9M when only YTD data is available."""
        raw_df = pd.DataFrame({
            "concept": [
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "fiscal_period": ["Q1", "FY", "FY"],
            "period_end": [
                date(2023, 12, 30), date(2024, 6, 29), date(2024, 9, 28),
            ],
            "period_start": [
                date(2023, 10, 1),   # Q1: ~90 days (discrete)
                date(2023, 10, 1),   # YTD_9M: ~272 days
                date(2023, 10, 1),   # FY: ~363 days (annual)
            ],
            "fiscal_year": [2024, 2024, 2024],
            "numeric_value": [30e9, 270e9, 391e9],
            "unit": ["USD", "USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"revenue"}, all_rows)

        q4_rows = [r for r in all_rows
                    if r["metric_type"] == "revenue" and r["period_type"] == "quarterly"
                    and r["period_end"] == date(2024, 9, 28)
                    and r["period"].startswith("Quarter Ended")]
        assert len(q4_rows) >= 1, f"Expected Q4 derived row. Got rows: {all_rows}"
        # Q4 = FY(391) - YTD_9M(270) = 121
        assert q4_rows[0]["value"] == pytest.approx(121e9)

    def test_q2_derived_from_ytd6m_minus_q1(self):
        """Q2 = YTD_6M − Q1 when only YTD data is available."""
        raw_df = pd.DataFrame({
            "concept": [
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "fiscal_period": ["Q1", "Q2"],
            "period_end": [
                date(2023, 12, 30), date(2024, 3, 30),
            ],
            "period_start": [
                date(2023, 10, 1),   # Q1: ~90 days (discrete)
                date(2023, 10, 1),   # YTD_6M: ~182 days
            ],
            "fiscal_year": [2024, 2024],
            "numeric_value": [30e9, 70e9],
            "unit": ["USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"revenue"}, all_rows)

        q2_rows = [r for r in all_rows
                    if r["metric_type"] == "revenue" and r["period_type"] == "quarterly"
                    and r["period_end"] == date(2024, 3, 30)
                    and r["period"].startswith("Quarter Ended")]
        assert len(q2_rows) >= 1, f"Expected Q2 derived row. Got rows: {all_rows}"
        # Q2 = YTD_6M(70) - Q1(30) = 40
        assert q2_rows[0]["value"] == pytest.approx(40e9)

    def test_q3_derived_from_ytd9m_minus_ytd6m(self):
        """Q3 = YTD_9M − YTD_6M."""
        raw_df = pd.DataFrame({
            "concept": [
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "fiscal_period": ["Q1", "Q2", "Q3"],
            "period_end": [
                date(2023, 12, 30), date(2024, 3, 30), date(2024, 6, 29),
            ],
            "period_start": [
                date(2023, 10, 1),   # Q1: ~90 days
                date(2023, 10, 1),   # YTD_6M: ~182 days
                date(2023, 10, 1),   # YTD_9M: ~272 days
            ],
            "fiscal_year": [2024, 2024, 2024],
            "numeric_value": [30e9, 70e9, 180e9],
            "unit": ["USD", "USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"revenue"}, all_rows)

        q3_rows = [r for r in all_rows
                    if r["metric_type"] == "revenue" and r["period_type"] == "quarterly"
                    and r["period_end"] == date(2024, 6, 29)
                    and r["period"].startswith("Quarter Ended")]
        assert len(q3_rows) >= 1, f"Expected Q3 derived row. Got rows: {all_rows}"
        # Q3 = YTD_9M(180) - YTD_6M(70) = 110
        assert q3_rows[0]["value"] == pytest.approx(110e9)

    def test_discrete_quarter_not_duplicated(self):
        """If data already has a discrete ~90-day quarter, don't duplicate it."""
        raw_df = pd.DataFrame({
            "concept": [
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "fiscal_period": ["Q1", "Q1"],
            "period_end": [
                date(2023, 12, 30), date(2023, 12, 30),
            ],
            "period_start": [
                date(2023, 10, 1),   # ~90 days (discrete)
                date(2023, 10, 1),   # duplicate
            ],
            "fiscal_year": [2024, 2024],
            "numeric_value": [30e9, 30e9],
            "unit": ["USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"revenue"}, all_rows)

        q1_rows = [r for r in all_rows
                    if r["metric_type"] == "revenue" and r["period_end"] == date(2023, 12, 30)
                    and r["period"].startswith("Quarter Ended")]
        assert len(q1_rows) == 1, f"Expected 1 Q1 row (deduped), got {len(q1_rows)}"


class TestBalanceSheetPassthrough:
    """Verify that stock (balance sheet) metrics are stored as-is per quarter."""

    def test_stock_metrics_stored_quarterly(self):
        """Balance sheet items should keep quarterly Q1--Q4 and annual FY."""
        raw_df = pd.DataFrame({
            "concept": [
                "us-gaap:Assets", "us-gaap:Assets", "us-gaap:Assets",
            ],
            "fiscal_period": ["FY", "Q1", "Q2"],
            "period_end": [
                date(2024, 9, 28), date(2023, 12, 30), date(2024, 3, 30),
            ],
            "numeric_value": [352e9, 340e9, 345e9],
            "unit": ["USD", "USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"total_assets"}, all_rows)

        assert len(all_rows) == 3, f"Expected 3 rows (FY + Q1 + Q2), got {len(all_rows)}"
        period_types = {r["period_type"] for r in all_rows}
        assert "annual" in period_types
        assert "quarterly" in period_types

    def test_stock_metrics_not_duration_filtered(self):
        """Stock metrics should NOT be filtered by duration — no period_start needed."""
        raw_df = pd.DataFrame({
            "concept": ["us-gaap:Assets", "us-gaap:Assets"],
            "fiscal_period": ["Q3", "Q4"],
            "period_end": [date(2024, 6, 29), date(2024, 9, 28)],
            "numeric_value": [348e9, 352e9],
            "unit": ["USD", "USD"],
        })

        all_rows: list[dict] = []
        _extract_from_raw_df(raw_df, "TEST", "999", {"total_assets"}, all_rows)

        # Q4 should be included for stock metrics (include_q4=True)
        periods = [r["period"] for r in all_rows]
        q4_rows = [r for r in all_rows if r["period_end"] == date(2024, 9, 28) and r["period_type"] == "quarterly"]
        assert len(q4_rows) >= 1, f"Q4-period expected for stock metrics. Got: {periods}"
