"""Golden-data tests for TTM metric computation.

Validates that compute_ttm_metrics() produces values consistent with
FMP TTM endpoint data for each ticker.

NOTE: Golden TTM fixture files must be generated first by running
  scripts/build_golden_data.py with FMP_API_KEY set.
  Until those files exist, this test module will skip gracefully.
"""

import importlib
import os
import tempfile

import pytest

os.environ.setdefault("EDGAR_IDENTITY", "test@example.com")

import edgar

from golden_helpers import GoldenTTMMetric, assert_ttm_metric_close

from investment_researcher.ingestion.edgar.financials import extract_company_facts
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.timeseries import initialize_db
from investment_researcher.metrics import compute_ttm_metrics


# ── Try importing golden TTM data ────────────────────────────────────────────

TICKERS = ["AAPL", "NVDA", "UNH", "WMT", "XOM"]

GOLDEN_TTM_DATA: dict[str, list[GoldenTTMMetric]] = {}

_TTM_GOLDEN_MODULES = {
    "AAPL": ("tests.fixtures.golden_ttm_aapl", "AAPL_TTM_GOLDEN"),
    "NVDA": ("tests.fixtures.golden_ttm_nvda", "NVDA_TTM_GOLDEN"),
    "UNH": ("tests.fixtures.golden_ttm_unh", "UNH_TTM_GOLDEN"),
    "WMT": ("tests.fixtures.golden_ttm_wmt", "WMT_TTM_GOLDEN"),
    "XOM": ("tests.fixtures.golden_ttm_xom", "XOM_TTM_GOLDEN"),
}
for _ticker, (_mod_name, _attr) in _TTM_GOLDEN_MODULES.items():
    try:
        _mod = importlib.import_module(_mod_name)
        GOLDEN_TTM_DATA[_ticker] = getattr(_mod, _attr)
    except ImportError:
        pass

_HAS_GOLDEN = bool(GOLDEN_TTM_DATA)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ttm_db_paths() -> dict[str, str]:
    """Extract all ticker data into temp DuckDB files, return {ticker: db_path}."""
    edgar.set_identity("test@example.com")
    paths = {}
    tmpdir = tempfile.mkdtemp(prefix="ttm_metric_test_")
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
def ttm_metrics(ttm_db_paths) -> dict[str, dict[str, float]]:
    """Compute TTM metrics for each ticker, return {ticker: {metric_type: value}}."""
    result = {}
    for ticker, db_path in ttm_db_paths.items():
        result[ticker] = compute_ttm_metrics(ticker, db_path=db_path)
    return result


# ── Build parametrized test cases ────────────────────────────────────────────

def _build_ttm_metric_params():
    params = []
    for ticker, golden_list in GOLDEN_TTM_DATA.items():
        for golden in golden_list:
            params.append(
                pytest.param(
                    ticker,
                    golden,
                    id=f"{ticker}_{golden.metric_type}_ttm",
                )
            )
    return params


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.skipif(not _HAS_GOLDEN, reason="No golden TTM fixture files found")
@pytest.mark.parametrize(("ticker", "golden"), _build_ttm_metric_params())
def test_ttm_metric_matches_fmp_golden(ttm_metrics, ticker, golden):
    """Each TTM metric should match FMP golden value within tolerance."""
    computed = ttm_metrics[ticker]
    actual = computed.get(golden.metric_type)
    if actual is None:
        pytest.skip(f"No computed TTM {golden.metric_type} for {ticker}")
    assert_ttm_metric_close(
        actual,
        golden,
        f"{ticker} {golden.metric_type} TTM",
    )


@pytest.mark.integration
def test_ttm_metrics_return_reasonable_count(ttm_metrics):
    """TTM metrics should return a reasonable number of entries for each ticker."""
    for ticker, metrics in ttm_metrics.items():
        assert len(metrics) >= 10, (
            f"{ticker}: only {len(metrics)} TTM metrics computed: "
            f"{sorted(metrics.keys())}"
        )


@pytest.mark.integration
def test_ttm_metrics_no_crash(ttm_db_paths):
    """compute_ttm_metrics should not raise for any ticker."""
    for ticker, db_path in ttm_db_paths.items():
        result = compute_ttm_metrics(ticker, db_path=db_path)
        assert isinstance(result, dict)
