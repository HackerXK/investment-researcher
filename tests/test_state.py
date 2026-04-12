"""Tests for the SQLite state tracking module."""

import pytest

from investment_researcher.ingestion.state import (
    delete_company_extraction_state,
    get_company_extraction_count,
    get_connection,
    get_company_last_extracted,
    get_processed_filing_count,
    initialize_state_db,
    is_filing_processed,
    mark_filing_processed,
    update_company_extraction,
)


@pytest.fixture
def state_db(tmp_path):
    """Create a temporary state database."""
    path = str(tmp_path / "test_state.db")
    initialize_state_db(db_path=path)
    return path


class TestInitializeStateDb:
    def test_creates_tables(self, state_db):
        conn = get_connection(state_db)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            assert "company_extraction_state" in table_names
            assert "processed_filings" in table_names
        finally:
            conn.close()

    def test_idempotent(self, tmp_path):
        path = str(tmp_path / "test_state.db")
        initialize_state_db(db_path=path)
        initialize_state_db(db_path=path)  # Should not raise


class TestCompanyExtractionState:
    def test_update_and_get(self, state_db):
        update_company_extraction("AAPL", cik="320193", db_path=state_db)
        ts = get_company_last_extracted("AAPL", db_path=state_db)
        assert ts is not None

    def test_nonexistent_company(self, state_db):
        assert get_company_last_extracted("NONEXIST", db_path=state_db) is None

    def test_count(self, state_db):
        assert get_company_extraction_count(db_path=state_db) == 0
        update_company_extraction("AAPL", db_path=state_db)
        update_company_extraction("MSFT", db_path=state_db)
        assert get_company_extraction_count(db_path=state_db) == 2

    def test_upsert(self, state_db):
        update_company_extraction("AAPL", db_path=state_db)
        ts1 = get_company_last_extracted("AAPL", db_path=state_db)
        update_company_extraction("AAPL", db_path=state_db)
        ts2 = get_company_last_extracted("AAPL", db_path=state_db)
        assert ts2 >= ts1
        assert get_company_extraction_count(db_path=state_db) == 1

    def test_delete_company_state(self, state_db):
        update_company_extraction("AAPL", db_path=state_db)
        update_company_extraction("MSFT", db_path=state_db)

        deleted = delete_company_extraction_state(["aapl"], db_path=state_db)

        assert deleted == 1
        assert get_company_last_extracted("AAPL", db_path=state_db) is None
        assert get_company_last_extracted("MSFT", db_path=state_db) is not None


class TestProcessedFilings:
    def test_mark_and_check(self, state_db):
        accession = "0000320193-23-000106"
        assert is_filing_processed(accession, db_path=state_db) is False
        mark_filing_processed(
            accession, ticker="AAPL", form_type="10-K", filed_date="2023-11-03",
            db_path=state_db,
        )
        assert is_filing_processed(accession, db_path=state_db) is True

    def test_count(self, state_db):
        assert get_processed_filing_count(db_path=state_db) == 0
        mark_filing_processed("acc-1", db_path=state_db)
        mark_filing_processed("acc-2", db_path=state_db)
        assert get_processed_filing_count(db_path=state_db) == 2

    def test_duplicate_insert_ignored(self, state_db):
        mark_filing_processed("acc-1", ticker="AAPL", db_path=state_db)
        mark_filing_processed("acc-1", ticker="AAPL", db_path=state_db)  # Should not raise
        assert get_processed_filing_count(db_path=state_db) == 1
