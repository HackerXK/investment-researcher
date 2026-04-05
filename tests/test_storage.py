"""Tests for the edgartools storage module."""

import os
from unittest.mock import patch, MagicMock

import pytest

from investment_researcher.ingestion.edgar.storage import (
    configure_edgar,
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
            with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR", str(tmp_path / "edgar")):
                configure_edgar()
                mock_edgar.set_identity.assert_called_once_with("test@example.com")
                mock_edgar.use_local_storage.assert_called_once()


class TestIsStorageEmpty:
    def test_empty_when_dirs_missing(self, tmp_path):
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR", str(tmp_path / "nonexist")):
            assert is_storage_empty() is True

    def test_empty_when_dirs_empty(self, tmp_path):
        (tmp_path / "submissions").mkdir()
        (tmp_path / "companyfacts").mkdir()
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR", str(tmp_path)):
            assert is_storage_empty() is True

    def test_not_empty_when_populated(self, tmp_path):
        (tmp_path / "submissions").mkdir()
        (tmp_path / "companyfacts").mkdir()
        (tmp_path / "submissions" / "CIK0000320193.json").touch()
        (tmp_path / "companyfacts" / "CIK0000320193.json").touch()
        with patch("investment_researcher.ingestion.edgar.storage.EDGAR_LOCAL_DATA_DIR", str(tmp_path)):
            assert is_storage_empty() is False
