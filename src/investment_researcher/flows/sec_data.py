"""Prefect flows for the SEC data pipeline.

Three flows:
- seed_flow: auto-triggered on empty state (full download + batch extraction)
- fast_path_flow: daily — process new 10-K/10-Q filings
- slow_path_flow: weekly — refresh companyfacts + re-extract all companies
"""

from prefect import flow, task
from prefect.logging import get_run_logger

from investment_researcher.ingestion.edgar.storage import (
    configure_edgar,
    download_filing_documents,
    download_metadata,
    download_recent_filings,
)
from investment_researcher.ingestion.timeseries import initialize_db
from investment_researcher.ingestion.state import initialize_state_db


@task(name="configure-edgar", retries=0)
def task_configure_edgar():
    configure_edgar()


@task(name="initialize-databases", retries=0)
def task_initialize_databases():
    initialize_db()
    initialize_state_db()


@task(name="download-metadata", retries=3, retry_delay_seconds=60)
def task_download_metadata():
    logger = get_run_logger()
    logger.info("Downloading SEC metadata...")
    download_metadata()
    logger.info("SEC metadata download complete.")


@task(name="download-filing-documents", retries=3, retry_delay_seconds=120)
def task_download_filing_documents():
    logger = get_run_logger()
    logger.info("Downloading filing documents...")
    download_filing_documents()
    logger.info("Filing document download complete.")


@task(name="download-recent-filings", retries=3, retry_delay_seconds=60)
def task_download_recent_filings(days: int = 7):
    logger = get_run_logger()
    logger.info("Downloading recent filings (last %d days)...", days)
    download_recent_filings(days=days)


@task(name="extract-all-companies", retries=1, retry_delay_seconds=300)
def task_extract_all_companies(limit: int | None = None) -> tuple[int, int]:
    logger = get_run_logger()
    from investment_researcher.ingestion.edgar.financials import extract_all_companies

    logger.info("Starting slow-path extraction for all companies...")
    companies, rows = extract_all_companies(limit=limit)
    logger.info("Extraction complete: %d companies, %d rows", companies, rows)
    return companies, rows


@task(name="process-recent-filings", retries=1, retry_delay_seconds=60)
def task_process_recent_filings(days: int = 1) -> tuple[int, int]:
    logger = get_run_logger()
    from investment_researcher.ingestion.edgar.fast_path import process_recent_filings

    logger.info("Starting fast-path extraction (last %d days)...", days)
    filings, rows = process_recent_filings(days=days)
    logger.info("Fast path complete: %d filings, %d rows", filings, rows)
    return filings, rows


@flow(name="sec-seed", log_prints=True)
def seed_flow(company_limit: int | None = None):
    """Full seed flow: download all data + extract all companies.

    Auto-triggered on first start when state is empty.
    """
    logger = get_run_logger()
    logger.info("=== SEC Seed Flow Starting ===")

    task_configure_edgar()
    task_initialize_databases()

    # Step 1: Download all metadata
    task_download_metadata()

    # Step 2: Download filing documents
    task_download_filing_documents()

    # Step 3: Extract financial data for all companies
    companies, rows = task_extract_all_companies(limit=company_limit)

    logger.info(
        "=== SEC Seed Flow Complete: %d companies, %d rows ===",
        companies,
        rows,
    )
    return {"companies": companies, "rows": rows}


@flow(name="sec-fast-path", log_prints=True)
def fast_path_flow(days: int = 1):
    """Daily fast path: download recent filings + extract XBRL.

    Runs daily to catch new filings before companyfacts bulk data updates.
    """
    logger = get_run_logger()
    logger.info("=== Fast Path Flow Starting (last %d days) ===", days)

    task_configure_edgar()
    task_initialize_databases()

    # Download recent filing documents
    task_download_recent_filings(days=days)

    # Process individual filings
    filings, rows = task_process_recent_filings(days=days)

    logger.info(
        "=== Fast Path Complete: %d filings, %d rows ===",
        filings,
        rows,
    )
    return {"filings": filings, "rows": rows}


@flow(name="sec-slow-path", log_prints=True)
def slow_path_flow(company_limit: int | None = None):
    """Weekly slow path: refresh companyfacts + re-extract all companies.

    Re-extracts all ~10,000+ companies weekly to catch amendments and
    corrections in bulk data.
    """
    logger = get_run_logger()
    logger.info("=== Slow Path Flow Starting ===")

    task_configure_edgar()
    task_initialize_databases()

    # Refresh metadata (catches amended filings)
    task_download_metadata()

    # Re-extract all companies
    companies, rows = task_extract_all_companies(limit=company_limit)

    logger.info(
        "=== Slow Path Complete: %d companies, %d rows ===",
        companies,
        rows,
    )
    return {"companies": companies, "rows": rows}
