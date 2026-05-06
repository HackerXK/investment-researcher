"""Configuration — loads environment variables for all modules."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (two levels up from this file: src/investment_researcher/config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# SEC EDGAR identity
EDGAR_IDENTITY: str = os.getenv("EDGAR_IDENTITY", "")

# Local storage for edgartools (runtime path the process sees)
EDGAR_LOCAL_DATA_DIR_RUNTIME: str = os.getenv(
    "EDGAR_LOCAL_DATA_DIR_RUNTIME"
)

# DuckDB path (runtime path the process sees)
DUCKDB_PATH_RUNTIME: str = os.getenv(
    "DUCKDB_PATH_RUNTIME"
)

# SQLite state DB path (runtime path the process sees)
STATE_DB_PATH_RUNTIME: str = os.getenv(
    "STATE_DB_PATH_RUNTIME"
)

# Prefect API URL
PREFECT_API_URL: str = os.getenv("PREFECT_API_URL", "http://localhost:4200/api")

# Filing download start date
EDGAR_FILINGS_START_DATE: str = os.getenv("EDGAR_FILINGS_START_DATE", "2021-01-01")

# Force seed flow on startup regardless of detected state.
# Set to 'true' (case-insensitive) to bypass the empty-state check.
FORCE_SEED: bool = os.getenv("FORCE_SEED", "").strip().lower() == "true"

# Raw SEC filing document storage ticker scope.
#
#  Semantics of the EDGAR_RAW_FILING_TICKERS env var:
#    unset / empty  → use DEFAULT_RAW_FILING_TICKERS (10 tickers)
#    "ALL"          → no ticker filter; every company's raw filing documents are stored
#    "AAPL,MSFT,…"  → explicit comma-separated list
#
#  RAW_FILING_TICKERS is None when ALL mode is active, otherwise a frozenset of
#  uppercase ticker strings.  Callers check: if RAW_FILING_TICKERS is None → all companies.

DEFAULT_RAW_FILING_TICKERS: list[str] = [
    "AAPL", "NVDA", "UNH", "WMT", "XOM",
    "MSFT", "AMZN", "GOOGL", "META", "TSLA",
]


def _parse_raw_filing_tickers(value: str | None) -> frozenset[str] | None:
    """Return a frozenset of tickers, or None when ALL mode is requested."""
    if not value or value.strip().upper() == "ALL":
        if value and value.strip().upper() == "ALL":
            return None
        # unset / empty → default list
        return frozenset(t.strip().upper() for t in DEFAULT_RAW_FILING_TICKERS)
    return frozenset(t.strip().upper() for t in value.split(",") if t.strip())


RAW_FILING_TICKERS: frozenset[str] | None = _parse_raw_filing_tickers(
    os.getenv("EDGAR_RAW_FILING_TICKERS")
)

# ── Phase 1: Web API & LLM ──────────────────────────────────────────────────

# FastAPI host/port
WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))

# Local LLM inference (OpenAI-compatible endpoint served by vLLM)
LLM_API_BASE: str = os.getenv("LLM_API_BASE", "http://localhost:8000/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-32B-Instruct")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "EMPTY")

# Langfuse tracing
LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL: str = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
