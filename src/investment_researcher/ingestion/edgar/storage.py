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
    EDGAR_LOCAL_DATA_DIR_RUNTIME,
    RAW_FILING_TICKERS,
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

    data_dir = Path(EDGAR_LOCAL_DATA_DIR_RUNTIME)
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

    Both ALL mode and ticker-scoped mode use EDGAR_FILINGS_START_DATE (or the
    explicit start_date argument) as the effective window start.  No additional
    cap is applied; the configured start date is the single source of truth.

    - RAW_FILING_TICKERS is None (ALL): downloads raw filing documents for every
      company from start_date onward.
    - RAW_FILING_TICKERS is a set: fetches the live EDGAR filing index from
      start_date onward, filters to the configured tickers, then downloads only
      matching filing documents.

    Args:
        start_date: ISO date string (e.g. '2021-01-01'). Defaults to
            EDGAR_FILINGS_START_DATE from the environment.
    """
    start = start_date or EDGAR_FILINGS_START_DATE

    if RAW_FILING_TICKERS is None:
        logger.info(
            "Downloading ALL filing documents from %s (EDGAR_RAW_FILING_TICKERS=ALL)...",
            start,
        )
        edgar.download_filings(f"{start}:")
    else:
        tickers = list(RAW_FILING_TICKERS)
        tickers_display = ", ".join(sorted(tickers))
        logger.info(
            "Downloading filing documents from %s for %d tickers: %s",
            start,
            len(tickers),
            tickers_display,
        )
        try:
            all_filings = edgar.get_filings(filing_date=f"{start}:")
            ticker_filings = all_filings.filter(ticker=tickers)
            if len(ticker_filings) == 0:
                logger.info(
                    "No filing documents found for configured tickers since %s", start
                )
            else:
                logger.info(
                    "Downloading %d filing documents for configured tickers", len(ticker_filings)
                )
                edgar.download_filings(filing_date=f"{start}:", filings=ticker_filings)
        except Exception:
            logger.warning(
                "Failed to download scoped filing documents", exc_info=True
            )

    logger.info("Filing document download complete.")


def download_recent_filings(days: int = 7) -> None:
    """Download filing documents from the last N days (incremental update).

    Applies the same RAW_FILING_TICKERS scope as download_filing_documents.
    Uses the live EDGAR filing index and Filings.filter(ticker=...) to scope
    downloads accurately to the configured ticker set.
    """
    from datetime import datetime, timedelta

    recent = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    if RAW_FILING_TICKERS is None:
        logger.info(
            "Downloading ALL recent filings (last %d days, since %s, "
            "EDGAR_RAW_FILING_TICKERS=ALL)...",
            days,
            recent,
        )
        edgar.download_filings(f"{recent}:")
    else:
        tickers = list(RAW_FILING_TICKERS)
        tickers_display = ", ".join(sorted(tickers))
        logger.info(
            "Downloading recent filings (last %d days, since %s) for %d tickers: %s",
            days,
            recent,
            len(tickers),
            tickers_display,
        )
        try:
            all_filings = edgar.get_filings(filing_date=f"{recent}:")
            ticker_filings = all_filings.filter(ticker=tickers)
            if len(ticker_filings) == 0:
                logger.info(
                    "No recent filing documents found for configured tickers since %s", recent
                )
            else:
                logger.info(
                    "Downloading %d recent filing documents for configured tickers",
                    len(ticker_filings),
                )
                edgar.download_filings(filing_date=f"{recent}:", filings=ticker_filings)
        except Exception:
            logger.warning(
                "Failed to download scoped recent filings", exc_info=True
            )

    logger.info("Recent filing download complete.")


def is_storage_empty() -> bool:
    """Check if edgartools local storage is empty (no metadata downloaded yet)."""
    data_dir = Path(EDGAR_LOCAL_DATA_DIR_RUNTIME)
    submissions_dir = data_dir / "submissions"
    companyfacts_dir = data_dir / "companyfacts"
    # Consider empty if neither submissions nor companyfacts directories exist or are empty
    if not submissions_dir.exists() or not companyfacts_dir.exists():
        return True
    # Check if there are actual files
    has_submissions = any(submissions_dir.iterdir())
    has_facts = any(companyfacts_dir.iterdir())
    return not (has_submissions and has_facts)
