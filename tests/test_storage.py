"""Tests for the edgartools storage module."""

import os
from unittest.mock import patch, MagicMock, call

import pytest

from investment_researcher.ingestion.edgar.storage import (
    configure_edgar,
    download_filing_documents,
    download_recent_filings,
    is_storage_empty,
)


class TestConfigureEdgar:
    def test_raises_without_identity(self):
        with patch.dict(os.environ, {}, clear=False):
            with patch("investment_researcher.ingestion.edgar.storage.EDGAR_IDENTITY", ""):
                with pytest.raises(ValueError, match="EDGAR_IDENTITY must be set"):
                    configure_edgar()

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_configures_with_identity(self, mock_edgar, tmp_path):
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_IDENTITY", "test@example.com"):
            with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR_RUNTIME", str(tmp_path / "edgar")):
                configure_edgar()
                mock_edgar.set_identity.assert_called_once_with("test@example.com")
                mock_edgar.use_local_storage.assert_called_once()


class TestIsStorageEmpty:
    def test_empty_when_dirs_missing(self, tmp_path):
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR_RUNTIME", str(tmp_path / "nonexist")):
            assert is_storage_empty() is True

    def test_empty_when_dirs_empty(self, tmp_path):
        (tmp_path / "submissions").mkdir()
        (tmp_path / "companyfacts").mkdir()
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR_RUNTIME", str(tmp_path)):
            assert is_storage_empty() is True

    def test_not_empty_when_populated(self, tmp_path):
        (tmp_path / "submissions").mkdir()
        (tmp_path / "companyfacts").mkdir()
        (tmp_path / "submissions" / "CIK0000320193.json").touch()
        (tmp_path / "companyfacts" / "CIK0000320193.json").touch()
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR_RUNTIME", str(tmp_path)):
            assert is_storage_empty() is False


class TestDownloadFilingDocuments:
    """Verify ticker-scoped download logic without hitting the network."""

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_all_mode_uses_date_string(self, mock_edgar):
        """When RAW_FILING_TICKERS is None (ALL), download_filings is called with a date string."""
        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", None):
            download_filing_documents(start_date="2024-01-01")
        mock_edgar.download_filings.assert_called_once_with("2024-01-01:")
        mock_edgar.Company.assert_not_called()
        mock_edgar.get_filings.assert_not_called()

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_uses_get_filings_and_filter(self, mock_edgar):
        """When RAW_FILING_TICKERS is set, uses edgar.get_filings + filter rather than Company."""
        tickers = frozenset({"AAPL", "MSFT"})
        mock_ticker_filings = MagicMock()
        mock_ticker_filings.__len__ = MagicMock(return_value=5)
        mock_all_filings = MagicMock()
        mock_all_filings.filter.return_value = mock_ticker_filings
        mock_edgar.get_filings.return_value = mock_all_filings

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            download_filing_documents(start_date="2024-01-01")

        # Never uses Company — live filing index via get_filings
        mock_edgar.Company.assert_not_called()

        # get_filings called with the exact start_date passed in, not a capped date
        mock_edgar.get_filings.assert_called_once_with(filing_date="2024-01-01:")

        # filter called with the list of tickers
        mock_all_filings.filter.assert_called_once()
        filter_kwargs = mock_all_filings.filter.call_args.kwargs
        assert set(filter_kwargs["ticker"]) == {"AAPL", "MSFT"}

        # download_filings called with the same exact start_date AND filings= kwarg
        mock_edgar.download_filings.assert_called_once_with(
            filing_date="2024-01-01:", filings=mock_ticker_filings
        )

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_skips_empty_filings(self, mock_edgar):
        """When the live index returns 0 matching filings, download_filings is not called."""
        tickers = frozenset({"AAPL"})
        mock_ticker_filings = MagicMock()
        mock_ticker_filings.__len__ = MagicMock(return_value=0)
        mock_all_filings = MagicMock()
        mock_all_filings.filter.return_value = mock_ticker_filings
        mock_edgar.get_filings.return_value = mock_all_filings

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            download_filing_documents(start_date="2024-01-01")

        mock_edgar.download_filings.assert_not_called()

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_handles_get_filings_error_gracefully(self, mock_edgar):
        """Network/API errors from edgar.get_filings are caught and do not abort the flow."""
        tickers = frozenset({"AAPL", "MSFT"})
        mock_edgar.get_filings.side_effect = RuntimeError("network error")

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            # Should not raise
            download_filing_documents(start_date="2024-01-01")

        mock_edgar.download_filings.assert_not_called()


class TestDownloadRecentFilings:
    """Verify ticker-scoped recent-filing download logic without hitting the network."""

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_all_mode_uses_date_string(self, mock_edgar):
        """ALL mode calls download_filings with a date string."""
        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", None):
            download_recent_filings(days=7)
        # download_filings called with a positional date string
        assert mock_edgar.download_filings.call_count == 1
        positional_arg = mock_edgar.download_filings.call_args.args[0]
        assert positional_arg.endswith(":")
        mock_edgar.Company.assert_not_called()
        mock_edgar.get_filings.assert_not_called()

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_uses_get_filings_and_filter(self, mock_edgar):
        """Ticker-scoped mode uses edgar.get_filings + filter, not Company."""
        tickers = frozenset({"AAPL"})
        mock_ticker_filings = MagicMock()
        mock_ticker_filings.__len__ = MagicMock(return_value=2)
        mock_all_filings = MagicMock()
        mock_all_filings.filter.return_value = mock_ticker_filings
        mock_edgar.get_filings.return_value = mock_all_filings

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            download_recent_filings(days=3)

        mock_edgar.Company.assert_not_called()

        # get_filings called with explicit filing_date
        mock_edgar.get_filings.assert_called_once()
        call_kwargs = mock_edgar.get_filings.call_args.kwargs
        assert "filing_date" in call_kwargs
        assert call_kwargs["filing_date"].endswith(":")

        # filter called with ticker list
        mock_all_filings.filter.assert_called_once()
        filter_kwargs = mock_all_filings.filter.call_args.kwargs
        assert filter_kwargs["ticker"] == ["AAPL"]

        # download_filings called with filing_date + filings
        mock_edgar.download_filings.assert_called_once()
        dl_call = mock_edgar.download_filings.call_args
        assert dl_call.kwargs.get("filings") is mock_ticker_filings
        assert "filing_date" in dl_call.kwargs

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_skips_when_no_recent_filings(self, mock_edgar):
        """When filter returns 0 results, download_filings is not called."""
        tickers = frozenset({"AAPL"})
        mock_ticker_filings = MagicMock()
        mock_ticker_filings.__len__ = MagicMock(return_value=0)
        mock_all_filings = MagicMock()
        mock_all_filings.filter.return_value = mock_ticker_filings
        mock_edgar.get_filings.return_value = mock_all_filings

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            download_recent_filings(days=3)

        mock_edgar.download_filings.assert_not_called()

    @patch("investment_researcher.ingestion.edgar.storage.edgar")
    def test_ticker_scope_handles_get_filings_error_gracefully(self, mock_edgar):
        """Network errors are caught and do not propagate."""
        tickers = frozenset({"AAPL"})
        mock_edgar.get_filings.side_effect = RuntimeError("network error")

        with patch("investment_researcher.ingestion.edgar.storage.RAW_FILING_TICKERS", tickers):
            # Should not raise
            download_recent_filings(days=3)

        mock_edgar.download_filings.assert_not_called()

