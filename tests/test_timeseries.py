"""Tests for the DuckDB timeseries writer module."""

import os
import tempfile

import duckdb
import pandas as pd
import pytest

from investment_researcher.analytics import queries as analytics_queries
from investment_researcher.ingestion.timeseries import (
    get_connection,
    initialize_db,
    is_db_empty,
    write_financial_metrics,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary DuckDB database path."""
    return str(tmp_path / "test.duckdb")


class TestInitializeDb:
    def test_creates_tables(self, tmp_db):
        initialize_db(db_path=tmp_db)
        con = get_connection(tmp_db)
        try:
            tables = con.execute(
                "SELECT table_name FROM information_schema.tables ORDER BY table_name"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert "financial_metrics" in table_names
            assert "macro_timeseries" in table_names
        finally:
            con.close()

    def test_idempotent(self, tmp_db):
        initialize_db(db_path=tmp_db)
        initialize_db(db_path=tmp_db)  # Should not raise
        con = get_connection(tmp_db)
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'financial_metrics'"
            ).fetchone()[0]
            assert count == 1
        finally:
            con.close()

    def test_financial_metrics_schema(self, tmp_db):
        initialize_db(db_path=tmp_db)
        con = get_connection(tmp_db)
        try:
            columns = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'financial_metrics' ORDER BY ordinal_position"
            ).fetchall()
            col_dict = {name: dtype for name, dtype in columns}

            # Verify all required columns exist with correct types
            assert "ticker" in col_dict
            assert "cik" in col_dict
            assert "metric_type" in col_dict
            assert "value" in col_dict
            assert "currency" in col_dict
            assert "period" in col_dict
            assert "period_type" in col_dict
            assert "period_end" in col_dict
            assert "source" in col_dict
            assert "accession" in col_dict
            assert "ingested_at" in col_dict

            assert col_dict["value"] == "DOUBLE"
            assert col_dict["period_end"] == "DATE"
        finally:
            con.close()

    def test_macro_timeseries_schema(self, tmp_db):
        initialize_db(db_path=tmp_db)
        con = get_connection(tmp_db)
        try:
            columns = con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'macro_timeseries' ORDER BY ordinal_position"
            ).fetchall()
            col_names = [c[0] for c in columns]
            assert "indicator_id" in col_names
            assert "name" in col_names
            assert "value" in col_names
            assert "unit" in col_names
            assert "date" in col_names
            assert "source" in col_names
            assert "ingested_at" in col_names
        finally:
            con.close()


class TestWriteFinancialMetrics:
    def test_write_basic(self, tmp_db):
        initialize_db(db_path=tmp_db)
        df = pd.DataFrame([{
            "ticker": "AAPL",
            "cik": "320193",
            "metric_type": "revenue",
            "value": 383285000000.0,
            "currency": "USD",
            "period": "Twelve Months Ended 09/30/2023",
            "period_type": "annual",
            "period_end": "2023-09-30",
            "source": "10-K",
            "accession": "0000320193-23-000106",
        }])
        count = write_financial_metrics(df, db_path=tmp_db)
        assert count == 1

        con = get_connection(tmp_db)
        try:
            result = con.execute("SELECT * FROM financial_metrics").fetchall()
            assert len(result) == 1
            assert result[0][0] == "AAPL"
        finally:
            con.close()

    def test_upsert_behavior(self, tmp_db):
        """INSERT OR REPLACE should update existing rows."""
        initialize_db(db_path=tmp_db)

        df1 = pd.DataFrame([{
            "ticker": "AAPL",
            "metric_type": "revenue",
            "value": 100.0,
            "period": "Twelve Months Ended 09/30/2023",
            "period_type": "annual",
            "period_end": "2023-09-30",
        }])
        write_financial_metrics(df1, db_path=tmp_db)

        df2 = pd.DataFrame([{
            "ticker": "AAPL",
            "metric_type": "revenue",
            "value": 200.0,
            "period": "Twelve Months Ended 09/30/2023",
            "period_type": "annual",
            "period_end": "2023-09-30",
        }])
        write_financial_metrics(df2, db_path=tmp_db)

        con = get_connection(tmp_db)
        try:
            result = con.execute(
                "SELECT value FROM financial_metrics WHERE ticker = 'AAPL'"
            ).fetchone()
            assert result[0] == 200.0
        finally:
            con.close()

    def test_multiple_metrics(self, tmp_db):
        initialize_db(db_path=tmp_db)
        df = pd.DataFrame([
            {
                "ticker": "AAPL",
                "metric_type": "revenue",
                "value": 383285000000.0,
                "period": "Twelve Months Ended 09/30/2023",
                "period_type": "annual",
                "period_end": "2023-09-30",
            },
            {
                "ticker": "AAPL",
                "metric_type": "net_income",
                "value": 96995000000.0,
                "period": "Twelve Months Ended 09/30/2023",
                "period_type": "annual",
                "period_end": "2023-09-30",
            },
            {
                "ticker": "MSFT",
                "metric_type": "revenue",
                "value": 211915000000.0,
                "period": "Twelve Months Ended 06/30/2023",
                "period_type": "annual",
                "period_end": "2023-06-30",
            },
        ])
        count = write_financial_metrics(df, db_path=tmp_db)
        assert count == 3

        con = get_connection(tmp_db)
        try:
            tickers = con.execute(
                "SELECT COUNT(DISTINCT ticker) FROM financial_metrics"
            ).fetchone()[0]
            assert tickers == 2
        finally:
            con.close()

    def test_empty_dataframe(self, tmp_db):
        initialize_db(db_path=tmp_db)
        df = pd.DataFrame()
        count = write_financial_metrics(df, db_path=tmp_db)
        assert count == 0

    def test_missing_required_columns(self, tmp_db):
        initialize_db(db_path=tmp_db)
        df = pd.DataFrame([{"ticker": "AAPL"}])
        with pytest.raises(ValueError, match="missing required columns"):
            write_financial_metrics(df, db_path=tmp_db)

    def test_no_deletion_of_absent_rows(self, tmp_db):
        """Both paths write safely — INSERT OR REPLACE never deletes absent rows."""
        initialize_db(db_path=tmp_db)

        # Slow path writes revenue and net_income
        df1 = pd.DataFrame([
            {
                "ticker": "AAPL",
                "metric_type": "revenue",
                "value": 383285000000.0,
                "period": "Twelve Months Ended 09/30/2023",
                "period_type": "annual",
                "period_end": "2023-09-30",
            },
            {
                "ticker": "AAPL",
                "metric_type": "net_income",
                "value": 96995000000.0,
                "period": "Twelve Months Ended 09/30/2023",
                "period_type": "annual",
                "period_end": "2023-09-30",
            },
        ])
        write_financial_metrics(df1, db_path=tmp_db)

        # Fast path writes only revenue (updated)
        df2 = pd.DataFrame([{
            "ticker": "AAPL",
            "metric_type": "revenue",
            "value": 391000000000.0,
            "period": "Twelve Months Ended 09/30/2023",
            "period_type": "annual",
            "period_end": "2023-09-30",
        }])
        write_financial_metrics(df2, db_path=tmp_db)

        # net_income should still be there (not deleted)
        con = get_connection(tmp_db)
        try:
            result = con.execute("SELECT COUNT(*) FROM financial_metrics").fetchone()[0]
            assert result == 2
            ni = con.execute(
                "SELECT value FROM financial_metrics "
                "WHERE ticker = 'AAPL' AND metric_type = 'net_income'"
            ).fetchone()
            assert ni is not None
            assert ni[0] == 96995000000.0
        finally:
            con.close()


class TestIsDbEmpty:
    def test_nonexistent_db(self, tmp_path):
        assert is_db_empty(str(tmp_path / "nonexistent.duckdb")) is True

    def test_empty_table(self, tmp_db):
        initialize_db(db_path=tmp_db)
        assert is_db_empty(tmp_db) is True

    def test_nonempty_table(self, tmp_db):
        initialize_db(db_path=tmp_db)
        df = pd.DataFrame([{
            "ticker": "AAPL",
            "metric_type": "revenue",
            "value": 100.0,
            "period": "Twelve Months Ended 09/30/2023",
            "period_type": "annual",
            "period_end": "2023-09-30",
        }])
        write_financial_metrics(df, db_path=tmp_db)
        assert is_db_empty(tmp_db) is False


class TestQuarterlyDetail:
    def test_uses_global_latest_quarter_window(self, tmp_db, monkeypatch):
        initialize_db(db_path=tmp_db)

        df = pd.DataFrame([
            {
                "ticker": "AAPL",
                "metric_type": "revenue",
                "value": 100.0,
                "period": "Quarter Ended 12/27/2025",
                "period_type": "quarterly",
                "period_end": "2025-12-27",
            },
            {
                "ticker": "AAPL",
                "metric_type": "revenue",
                "value": 90.0,
                "period": "Quarter Ended 09/27/2025",
                "period_type": "quarterly",
                "period_end": "2025-09-27",
            },
            {
                "ticker": "AAPL",
                "metric_type": "revenue",
                "value": 80.0,
                "period": "Quarter Ended 06/28/2025",
                "period_type": "quarterly",
                "period_end": "2025-06-28",
            },
            {
                "ticker": "AAPL",
                "metric_type": "interest_expense",
                "value": 7.0,
                "period": "Quarter Ended 09/30/2023",
                "period_type": "quarterly",
                "period_end": "2023-09-30",
            },
            {
                "ticker": "AAPL",
                "metric_type": "interest_expense",
                "value": 6.0,
                "period": "Quarter Ended 07/01/2023",
                "period_type": "quarterly",
                "period_end": "2023-07-01",
            },
        ])
        write_financial_metrics(df, db_path=tmp_db)

        monkeypatch.setattr(analytics_queries, "_DB_PATH", tmp_db)

        result = analytics_queries.quarterly_detail(
            "AAPL",
            ["revenue", "interest_expense"],
            n_quarters=2,
        )

        assert result.columns.tolist() == [
            "TTM",
            "Quarter Ended 12/27/2025",
            "Quarter Ended 09/27/2025",
        ]
        assert result.loc["revenue", "Quarter Ended 12/27/2025"] == 100.0
        assert pd.isna(result.loc["interest_expense", "Quarter Ended 12/27/2025"])
