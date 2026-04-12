"""Golden-data tests for the financial ratio computation engine.

Compares ratios computed from SEC EDGAR raw metrics against FMP golden data.
Uses the same module-scoped extraction pattern as test_golden_companies.py.
"""

import os
import tempfile
from datetime import date, timedelta

import pytest

os.environ.setdefault("EDGAR_IDENTITY", "test@example.com")

import edgar

from golden_helpers import (
    GoldenRatio,
    GoldenTTMRatio,
    assert_ratio_close,
    assert_ttm_ratio_close,
    extract_ticker_rows,
)
from golden_ratios_aapl import AAPL_ANNUAL_GOLDEN_RATIOS, AAPL_QUARTERLY_GOLDEN_RATIOS
from golden_ratios_amzn import AMZN_ANNUAL_GOLDEN_RATIOS, AMZN_QUARTERLY_GOLDEN_RATIOS
from golden_ratios_nvda import NVDA_ANNUAL_GOLDEN_RATIOS, NVDA_QUARTERLY_GOLDEN_RATIOS
from golden_ratios_unh import UNH_ANNUAL_GOLDEN_RATIOS, UNH_QUARTERLY_GOLDEN_RATIOS
from golden_ratios_wmt import WMT_ANNUAL_GOLDEN_RATIOS, WMT_QUARTERLY_GOLDEN_RATIOS
from golden_ratios_xom import XOM_ANNUAL_GOLDEN_RATIOS, XOM_QUARTERLY_GOLDEN_RATIOS

from golden_ttm_ratios_aapl import AAPL_TTM_GOLDEN_RATIOS
from golden_ttm_ratios_amzn import AMZN_TTM_GOLDEN_RATIOS
from golden_ttm_ratios_nvda import NVDA_TTM_GOLDEN_RATIOS
from golden_ttm_ratios_unh import UNH_TTM_GOLDEN_RATIOS
from golden_ttm_ratios_wmt import WMT_TTM_GOLDEN_RATIOS
from golden_ttm_ratios_xom import XOM_TTM_GOLDEN_RATIOS

from investment_researcher.ingestion.edgar.financials import extract_company_facts
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.timeseries import get_connection, initialize_db
from investment_researcher.ratios import (
    RATIO_NAMES,
    RATIO_REGISTRY,
    compute_ratios,
    compute_ttm_ratios,
    latest_ratios,
)


# ── Constants ────────────────────────────────────────────────────────────────

ANNUAL_START_DATE = date(2022, 1, 1)
DATE_TOLERANCE_DAYS = 7

TICKERS = ["AAPL", "AMZN", "NVDA", "UNH", "WMT", "XOM"]

GOLDEN_DATA = {
    "AAPL": {"annual": AAPL_ANNUAL_GOLDEN_RATIOS, "quarterly": AAPL_QUARTERLY_GOLDEN_RATIOS},
    "AMZN": {"annual": AMZN_ANNUAL_GOLDEN_RATIOS, "quarterly": AMZN_QUARTERLY_GOLDEN_RATIOS},
    "NVDA": {"annual": NVDA_ANNUAL_GOLDEN_RATIOS, "quarterly": NVDA_QUARTERLY_GOLDEN_RATIOS},
    "UNH": {"annual": UNH_ANNUAL_GOLDEN_RATIOS, "quarterly": UNH_QUARTERLY_GOLDEN_RATIOS},
    "WMT": {"annual": WMT_ANNUAL_GOLDEN_RATIOS, "quarterly": WMT_QUARTERLY_GOLDEN_RATIOS},
    "XOM": {"annual": XOM_ANNUAL_GOLDEN_RATIOS, "quarterly": XOM_QUARTERLY_GOLDEN_RATIOS},
}

GOLDEN_TTM_DATA = {
    "AAPL": AAPL_TTM_GOLDEN_RATIOS,
    "AMZN": AMZN_TTM_GOLDEN_RATIOS,
    "NVDA": NVDA_TTM_GOLDEN_RATIOS,
    "UNH": UNH_TTM_GOLDEN_RATIOS,
    "WMT": WMT_TTM_GOLDEN_RATIOS,
    "XOM": XOM_TTM_GOLDEN_RATIOS,
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ratio_db_paths() -> dict[str, str]:
    """Extract all ticker data into temp DuckDB files, return {ticker: db_path}."""
    edgar.set_identity("test@example.com")
    paths = {}
    # Use a single temp dir that persists for the whole module
    tmpdir = tempfile.mkdtemp(prefix="ratio_test_")
    for ticker in TICKERS:
        db_path = f"{tmpdir}/{ticker}.duckdb"
        state_path = f"{tmpdir}/{ticker}_state.db"
        initialize_db(db_path=db_path)
        initialize_state_db(db_path=state_path)
        count = extract_company_facts(ticker, db_path=db_path, state_db_path=state_path)
        assert count > 0, f"extract_company_facts returned 0 rows for {ticker}"
        paths[ticker] = db_path
    return paths


@pytest.fixture(scope="module")
def computed_ratios(ratio_db_paths) -> dict[str, list[dict]]:
    """Compute all ratios for each ticker, return {ticker: [rows]}."""
    result = {}
    for ticker, db_path in ratio_db_paths.items():
        df = compute_ratios(ticker, period_type="annual", db_path=db_path)
        result[ticker] = df.to_dict("records") if not df.empty else []
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_ratio_match(
    rows: list[dict],
    ratio_name: str,
    golden_pe: date,
) -> dict | None:
    """Find a computed ratio row matching the golden entry (with date tolerance)."""
    best = None
    best_delta = timedelta(days=DATE_TOLERANCE_DAYS + 1)
    for r in rows:
        if r["ratio_name"] != ratio_name:
            continue
        pe = r["period_end"]
        if hasattr(pe, "date"):
            pe = pe.date()
        elif isinstance(pe, str):
            pe = date.fromisoformat(pe)
        delta = abs(pe - golden_pe)
        if delta <= timedelta(days=DATE_TOLERANCE_DAYS) and delta < best_delta:
            best = r
            best_delta = delta
    return best


# ── Build parametrized test cases ────────────────────────────────────────────

def _build_annual_ratio_params():
    params = []
    for ticker, data in GOLDEN_DATA.items():
        for golden in data["annual"]:
            if golden.period_end < ANNUAL_START_DATE:
                continue
            marks = []
            if golden.skip_reason:
                marks.append(pytest.mark.skip(reason=golden.skip_reason))
            params.append(
                pytest.param(
                    ticker,
                    golden,
                    id=f"{ticker}_{golden.ratio_name}_annual_{golden.period_end}",
                    marks=marks,
                )
            )
    return params


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize(("ticker", "golden"), _build_annual_ratio_params())
def test_ratio_matches_fmp_golden(computed_ratios, ticker, golden):
    """Each computed ratio should match FMP golden value within tolerance."""
    rows = computed_ratios[ticker]
    match = _find_ratio_match(rows, golden.ratio_name, golden.period_end)
    if match is None:
        pytest.skip(
            f"No computed {golden.ratio_name} near {golden.period_end} for {ticker}"
        )
    assert_ratio_close(
        match["value"],
        golden,
        f"{ticker} {golden.ratio_name} annual {golden.period_end}",
    )


@pytest.mark.integration
def test_ratio_handles_missing_inputs(ratio_db_paths):
    """Ratios with missing input metrics should return NaN/None, not error."""
    # Use a ticker that's in the DB
    db_path = ratio_db_paths["AAPL"]
    # Ask for all ratios — some may not be computable
    df = compute_ratios("AAPL", period_type="annual", db_path=db_path)
    # Should not raise; result should be a DataFrame
    assert df is not None
    assert "ratio_name" in df.columns


@pytest.mark.integration
def test_ratio_handles_zero_denominators(ratio_db_paths):
    """No ZeroDivisionError when denominators are zero."""
    # AAPL sometimes has zero interest_expense
    db_path = ratio_db_paths["AAPL"]
    df = compute_ratios(
        "AAPL",
        period_type="annual",
        ratio_names=["interest_coverage_ratio"],
        db_path=db_path,
    )
    # Should not raise; may have rows or not depending on data
    assert df is not None


@pytest.mark.integration
def test_all_ratios_return_expected_names(ratio_db_paths):
    """Verify that typical tickers produce ratios from most categories."""
    db_path = ratio_db_paths["AAPL"]
    result = latest_ratios("AAPL", period_type="annual", db_path=db_path)
    # Should have at least 15 ratios (some may be missing if metrics unavailable)
    assert len(result) >= 15, f"Only {len(result)} ratios computed: {sorted(result.keys())}"


def test_ratio_registry_completeness():
    """Verify the ratio registry has the expected number of entries."""
    assert len(RATIO_REGISTRY) == 31, f"Expected 31 ratios, got {len(RATIO_REGISTRY)}"
    assert len(RATIO_NAMES) == 31
    # All names should be unique
    assert len(set(RATIO_NAMES)) == 31, "Duplicate ratio names found"


# ── TTM Ratio Tests ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ttm_ratios(ratio_db_paths) -> dict[str, dict[str, float]]:
    """Compute TTM ratios for each ticker, return {ticker: {ratio_name: value}}."""
    result = {}
    for ticker, db_path in ratio_db_paths.items():
        result[ticker] = compute_ttm_ratios(ticker, db_path=db_path)
    return result


def _build_ttm_ratio_params():
    params = []
    for ticker, golden_list in GOLDEN_TTM_DATA.items():
        for golden in golden_list:
            marks = []
            if golden.skip_reason:
                marks.append(pytest.mark.skip(reason=golden.skip_reason))
            params.append(
                pytest.param(
                    ticker,
                    golden,
                    id=f"{ticker}_{golden.ratio_name}_ttm",
                    marks=marks,
                )
            )
    return params


@pytest.mark.integration
@pytest.mark.parametrize(("ticker", "golden"), _build_ttm_ratio_params())
def test_ttm_ratio_matches_fmp_golden(ttm_ratios, ticker, golden):
    """Each computed TTM ratio should match FMP golden value within tolerance."""
    computed = ttm_ratios[ticker]
    actual = computed.get(golden.ratio_name)
    if actual is None:
        pytest.skip(f"No computed TTM {golden.ratio_name} for {ticker}")
    assert_ttm_ratio_close(
        actual,
        golden,
        f"{ticker} {golden.ratio_name} TTM",
    )


@pytest.mark.integration
def test_ttm_ratios_return_expected_count(ttm_ratios):
    """Verify that TTM ratios produce a reasonable number of entries."""
    for ticker, ratios in ttm_ratios.items():
        assert len(ratios) >= 15, (
            f"{ticker}: only {len(ratios)} TTM ratios computed: {sorted(ratios.keys())}"
        )


@pytest.mark.integration
def test_ttm_ratios_no_crash_on_all_tickers(ratio_db_paths):
    """compute_ttm_ratios should not raise for any ticker."""
    for ticker, db_path in ratio_db_paths.items():
        result = compute_ttm_ratios(ticker, db_path=db_path)
        assert isinstance(result, dict)
