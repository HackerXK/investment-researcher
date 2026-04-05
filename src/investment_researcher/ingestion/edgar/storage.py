"""edgartools local storage setup and download helpers.

Configures edgartools for offline-first operation by downloading all SEC
metadata and filing documents to local storage.
"""

import logging
from pathlib import Path

import edgar

from investment_researcher.config import (
    EDGAR_FILINGS_START_DATE,
    EDGAR_IDENTITY,
    EDGAR_LOCAL_DATA_DIR,
)

logger = logging.getLogger(__name__)


def configure_edgar() -> None:
    """Set up edgartools identity and local storage."""
    if not EDGAR_IDENTITY:
        raise ValueError(
            "EDGAR_IDENTITY must be set (e.g. 'your.name@example.com'). "
            "SEC requires a valid User-Agent identity."
        )
    edgar.set_identity(EDGAR_IDENTITY)

    data_dir = Path(EDGAR_LOCAL_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    edgar.use_local_storage(str(data_dir))
    logger.info("edgartools configured: identity=%s, local_storage=%s", EDGAR_IDENTITY, data_dir)


def download_metadata() -> None:
    """Download all SEC metadata (~24 GB: submissions, companyfacts, reference).

    This is idempotent — safe to re-run.
    """
    logger.info("Downloading SEC metadata (submissions, companyfacts, reference)...")
    edgar.download_edgar_data()
    logger.info("SEC metadata download complete.")


def download_filing_documents(start_date: str | None = None) -> None:
    """Download filing documents from a start date.

    Args:
        start_date: ISO date string (e.g. '2021-01-01'). Defaults to config value.
    """
    start = start_date or EDGAR_FILINGS_START_DATE
    logger.info("Downloading filing documents from %s...", start)
    edgar.download_filings(f"{start}:")
    logger.info("Filing document download complete.")


def download_recent_filings(days: int = 7) -> None:
    """Download filing documents from the last N days (incremental update)."""
    from datetime import datetime, timedelta

    recent = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    logger.info("Downloading recent filings (last %d days, since %s)...", days, recent)
    edgar.download_filings(f"{recent}:")
    logger.info("Recent filing download complete.")


def is_storage_empty() -> bool:
    """Check if edgartools local storage is empty (no metadata downloaded yet)."""
    data_dir = Path(EDGAR_LOCAL_DATA_DIR)
    submissions_dir = data_dir / "submissions"
    companyfacts_dir = data_dir / "companyfacts"
    # Consider empty if neither submissions nor companyfacts directories exist or are empty
    if not submissions_dir.exists() or not companyfacts_dir.exists():
        return True
    # Check if there are actual files
    has_submissions = any(submissions_dir.iterdir())
    has_facts = any(companyfacts_dir.iterdir())
    return not (has_submissions and has_facts)
