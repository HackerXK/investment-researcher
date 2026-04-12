"""Pytest configuration — executed before any test collection.

Responsibilities
----------------
1. Load ``.env.test`` (with override=True) so that every module imported
   afterwards sees test-appropriate environment variables instead of the
   production values from ``.env``.

2. Create a fresh, empty DuckDB in a per-session temp directory and point
   ``DUCKDB_PATH_RUNTIME`` at it **before** any ``investment_researcher``
   module is imported.  This guarantees that:

   * No test ever touches ``data/duckdb/financial_timeseries.duckdb``.
   * Every test session starts from a clean slate.

3. Seed the session DuckDB with annual + quarterly data for all six golden
    companies (AAPL, AMZN, NVDA, UNH, WMT, XOM) so that the API / shape tests in
   ``test_api.py`` pass without a live production database.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ── Step 1: load .env.test BEFORE any investment_researcher import ─────────────
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env.test", override=True)

# ── Step 2: fresh per-session DuckDB, override the runtime path ───────────────

_SESSION_TMPDIR = tempfile.mkdtemp(prefix="ir_pytest_")
_SESSION_DUCKDB = os.path.join(_SESSION_TMPDIR, "session.duckdb")
os.environ["DUCKDB_PATH_RUNTIME"] = _SESSION_DUCKDB

# Clean up the temp directory when the process exits.
atexit.register(shutil.rmtree, _SESSION_TMPDIR, ignore_errors=True)

# Ensure the fixtures directory is on sys.path (mirrors pyproject.toml pythonpath).
_FIXTURES_DIR = str(Path(__file__).parent / "fixtures")
if _FIXTURES_DIR not in sys.path:
    sys.path.insert(0, _FIXTURES_DIR)

# ── Step 3: fixtures ───────────────────────────────────────────────────────────
import pandas as pd  # noqa: E402 — must come after env setup
import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def session_duckdb():
    """Initialize and seed the per-session DuckDB.

    Runs once before the first test in the session.  All code that calls
    ``analytics.queries._con()`` (i.e. the default DB path) will use this
    fresh, seeded database.
    """
    # Import project modules *inside* the fixture so the module-level env vars
    # set above are already in place when config.py resolves DUCKDB_PATH_RUNTIME.
    from golden_aapl import AAPL_ANNUAL_GOLDEN, AAPL_QUARTERLY_GOLDEN
    from golden_amzn import AMZN_ANNUAL_GOLDEN, AMZN_QUARTERLY_GOLDEN
    from golden_nvda import NVDA_ANNUAL_GOLDEN, NVDA_QUARTERLY_GOLDEN
    from golden_unh import UNH_ANNUAL_GOLDEN, UNH_QUARTERLY_GOLDEN
    from golden_wmt import WMT_ANNUAL_GOLDEN, WMT_QUARTERLY_GOLDEN
    from golden_xom import XOM_ANNUAL_GOLDEN, XOM_QUARTERLY_GOLDEN
    from investment_researcher.ingestion.timeseries import (
        initialize_db,
        write_financial_metrics,
    )

    db_path = _SESSION_DUCKDB
    initialize_db(db_path=db_path)

    _COMPANY_CIKS = {
        "AAPL": "0000320193",
        "AMZN": "0001018724",
        "NVDA": "0001045810",
        "UNH": "0000731766",
        "WMT": "0000104169",
        "XOM": "0000034088",
    }

    golden_map = {
        "AAPL": (AAPL_ANNUAL_GOLDEN, AAPL_QUARTERLY_GOLDEN),
        "AMZN": (AMZN_ANNUAL_GOLDEN, AMZN_QUARTERLY_GOLDEN),
        "NVDA": (NVDA_ANNUAL_GOLDEN, NVDA_QUARTERLY_GOLDEN),
        "UNH": (UNH_ANNUAL_GOLDEN, UNH_QUARTERLY_GOLDEN),
        "WMT": (WMT_ANNUAL_GOLDEN, WMT_QUARTERLY_GOLDEN),
        "XOM": (XOM_ANNUAL_GOLDEN, XOM_QUARTERLY_GOLDEN),
    }

    rows: list[dict] = []
    for ticker, (annual, quarterly) in golden_map.items():
        cik = _COMPANY_CIKS[ticker]
        for g in annual:
            rows.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "metric_type": g.metric_type,
                    "value": g.value,
                    "currency": "USD",
                    "period": f"Fiscal Year Ended {g.period_end.strftime('%m/%d/%Y')}",
                    "period_type": "annual",
                    "period_end": str(g.period_end),
                    "source": g.source,
                    "accession": "",
                }
            )
        for g in quarterly:
            rows.append(
                {
                    "ticker": ticker,
                    "cik": cik,
                    "metric_type": g.metric_type,
                    "value": g.value,
                    "currency": "USD",
                    "period": f"Quarter Ended {g.period_end.strftime('%m/%d/%Y')}",
                    "period_type": "quarterly",
                    "period_end": str(g.period_end),
                    "source": g.source,
                    "accession": "",
                }
            )

    write_financial_metrics(pd.DataFrame(rows), db_path=db_path)

    yield db_path
