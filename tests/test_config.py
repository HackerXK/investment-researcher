"""Tests for the config module."""

from investment_researcher.config import (
    DEFAULT_RAW_FILING_TICKERS,
    PROJECT_ROOT,
    _parse_raw_filing_tickers,
)


class TestConfig:
    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()

    def test_project_root_contains_pyproject(self):
        assert (PROJECT_ROOT / "pyproject.toml").exists()


class TestRawFilingTickersConfig:
    def test_default_when_unset(self):
        """Unset env var → default 10-ticker frozenset."""
        result = _parse_raw_filing_tickers(None)
        assert result is not None
        assert isinstance(result, frozenset)
        assert result == frozenset(t.upper() for t in DEFAULT_RAW_FILING_TICKERS)

    def test_default_when_empty_string(self):
        """Empty string → default 10-ticker frozenset (same as unset)."""
        result = _parse_raw_filing_tickers("")
        assert result is not None
        assert result == frozenset(t.upper() for t in DEFAULT_RAW_FILING_TICKERS)

    def test_all_returns_none(self):
        """'ALL' → None (no filtering)."""
        assert _parse_raw_filing_tickers("ALL") is None

    def test_all_case_insensitive(self):
        """'all' and 'All' are also accepted."""
        assert _parse_raw_filing_tickers("all") is None
        assert _parse_raw_filing_tickers("All") is None

    def test_explicit_comma_list(self):
        """Comma-separated list → frozenset of uppercased tickers."""
        result = _parse_raw_filing_tickers("AAPL,MSFT,GOOGL")
        assert result == frozenset({"AAPL", "MSFT", "GOOGL"})

    def test_explicit_list_is_uppercased(self):
        """Lowercase tickers are uppercased."""
        result = _parse_raw_filing_tickers("aapl,msft")
        assert result == frozenset({"AAPL", "MSFT"})

    def test_explicit_list_strips_whitespace(self):
        """Spaces around commas are stripped."""
        result = _parse_raw_filing_tickers(" AAPL , MSFT ")
        assert result == frozenset({"AAPL", "MSFT"})

    def test_default_contains_expected_tickers(self):
        """Default set contains all 10 intended tickers."""
        result = _parse_raw_filing_tickers(None)
        for ticker in ["AAPL", "NVDA", "UNH", "WMT", "XOM", "MSFT", "AMZN", "GOOGL", "META", "TSLA"]:
            assert ticker in result, f"{ticker} missing from default set"

    def test_raw_filing_tickers_module_constant(self):
        """RAW_FILING_TICKERS module constant is consistent with _parse_raw_filing_tickers."""
        from investment_researcher.config import RAW_FILING_TICKERS
        # In tests the env var is likely unset → should equal default set
        # We can't assert the exact value (env may differ), but it must be
        # either None or a frozenset.
        assert RAW_FILING_TICKERS is None or isinstance(RAW_FILING_TICKERS, frozenset)

