"""Configuration — loads environment variables for all modules."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (two levels up from this file: src/investment_researcher/config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# SEC EDGAR identity
EDGAR_IDENTITY: str = os.getenv("EDGAR_IDENTITY", "")

# Local storage for edgartools
EDGAR_LOCAL_DATA_DIR: str = os.getenv(
    "EDGAR_LOCAL_DATA_DIR",
    str(PROJECT_ROOT / "data" / "edgar"),
)

# DuckDB path
DUCKDB_PATH: str = os.getenv(
    "DUCKDB_PATH",
    str(PROJECT_ROOT / "data" / "duckdb" / "financial_timeseries.duckdb"),
)

# SQLite state DB path
STATE_DB_PATH: str = os.getenv(
    "STATE_DB_PATH",
    str(PROJECT_ROOT / "data" / "state" / "ingestion_state.db"),
)

# Prefect API URL
PREFECT_API_URL: str = os.getenv("PREFECT_API_URL", "http://localhost:4200/api")

# Filing download start date
EDGAR_FILINGS_START_DATE: str = os.getenv("EDGAR_FILINGS_START_DATE", "2021-01-01")
