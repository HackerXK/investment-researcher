"""Ingestion state tracking via SQLite.

Tracks:
- Company-level: last extraction timestamp per ticker (slow path)
- Filing-level: processed accession numbers (fast path dedup)
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from investment_researcher.config import STATE_DB_PATH_RUNTIME

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS company_extraction_state (
    ticker        TEXT PRIMARY KEY,
    cik           TEXT,
    last_extracted TIMESTAMP NOT NULL,
    extraction_type TEXT NOT NULL DEFAULT 'slow_path'
);

CREATE TABLE IF NOT EXISTS processed_filings (
    accession_number TEXT PRIMARY KEY,
    ticker           TEXT,
    form_type        TEXT,
    filed_date       TEXT,
    processed_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Get a SQLite connection, creating the database file if needed."""
    path = db_path or STATE_DB_PATH_RUNTIME
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def initialize_state_db(db_path: str | None = None) -> None:
    """Create state tracking tables if they don't exist."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_CREATE_TABLES)
        conn.commit()
        logger.info("State DB initialized at %s", db_path or STATE_DB_PATH_RUNTIME)
    finally:
        conn.close()


def update_company_extraction(
    ticker: str,
    cik: str | None = None,
    extraction_type: str = "slow_path",
    db_path: str | None = None,
) -> None:
    """Record that a company's financial data has been extracted."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO company_extraction_state
                (ticker, cik, last_extracted, extraction_type)
            VALUES (?, ?, ?, ?)
            """,
            (ticker, cik, datetime.now(timezone.utc).isoformat(), extraction_type),
        )
        conn.commit()
    finally:
        conn.close()


def delete_company_extraction_state(
    tickers: list[str] | tuple[str, ...] | str,
    db_path: str | None = None,
) -> int:
    """Delete company extraction state rows for the requested ticker(s)."""
    if isinstance(tickers, str):
        ticker_list = [tickers]
    else:
        ticker_list = list(tickers)

    normalized = sorted({t.strip().upper() for t in ticker_list if t and t.strip()})
    if not normalized:
        return 0

    placeholders = ", ".join("?" for _ in normalized)
    conn = get_connection(db_path)
    try:
        delete_count = conn.execute(
            f"SELECT COUNT(*) FROM company_extraction_state WHERE ticker IN ({placeholders})",
            normalized,
        ).fetchone()[0]
        conn.execute(
            f"DELETE FROM company_extraction_state WHERE ticker IN ({placeholders})",
            normalized,
        )
        conn.commit()
        return delete_count
    finally:
        conn.close()


def get_company_last_extracted(ticker: str, db_path: str | None = None) -> str | None:
    """Get the last extraction timestamp for a company."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT last_extracted FROM company_extraction_state WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        return row["last_extracted"] if row else None
    finally:
        conn.close()


def mark_filing_processed(
    accession_number: str,
    ticker: str | None = None,
    form_type: str | None = None,
    filed_date: str | None = None,
    db_path: str | None = None,
) -> None:
    """Record that a filing has been processed (fast path dedup)."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_filings
                (accession_number, ticker, form_type, filed_date, processed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (accession_number, ticker, form_type, filed_date, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def is_filing_processed(accession_number: str, db_path: str | None = None) -> bool:
    """Check if a filing has already been processed."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM processed_filings WHERE accession_number = ?",
            (accession_number,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_processed_accessions(db_path: str | None = None) -> set[str]:
    """Return all processed accession numbers as a set for O(1) lookups."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT accession_number FROM processed_filings").fetchall()
        return {r["accession_number"] for r in rows}
    finally:
        conn.close()


def mark_filings_processed_batch(
    filings: list[tuple[str, str | None, str | None, str | None]],
    db_path: str | None = None,
) -> None:
    """Bulk-insert processed filings in a single transaction.

    Args:
        filings: List of (accession_number, ticker, form_type, filed_date) tuples.
    """
    if not filings:
        return
    conn = get_connection(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO processed_filings "
            "(accession_number, ticker, form_type, filed_date, processed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(a, t, f, d, now) for a, t, f, d in filings],
        )
        conn.commit()
    finally:
        conn.close()


def get_processed_filing_count(db_path: str | None = None) -> int:
    """Get the total number of processed filings."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM processed_filings").fetchone()
        return row["cnt"]
    finally:
        conn.close()


def get_company_extraction_count(db_path: str | None = None) -> int:
    """Get the total number of companies with extraction state."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM company_extraction_state").fetchone()
        return row["cnt"]
    finally:
        conn.close()
