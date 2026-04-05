"""Service entry point: auto-seed → Prefect deployments.

This is the main entry point for the ir-service Docker container.
On startup:
1. Auto-detect empty state → run seed flow
2. After seed (or if already seeded), register and serve Prefect deployments
   (fast-path daily + slow-path weekly)
"""

import logging
import sys

from investment_researcher.ingestion.edgar.storage import configure_edgar, is_storage_empty
from investment_researcher.ingestion.timeseries import initialize_db, is_db_empty
from investment_researcher.ingestion.state import initialize_state_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_service():
    """Main service loop: auto-seed if needed, then serve Prefect deployments."""
    logger.info("=== Investment Researcher Service Starting ===")

    # Initialize databases
    initialize_db()
    initialize_state_db()

    # Configure edgartools
    configure_edgar()

    # Auto-detect empty state and seed
    if is_storage_empty() or is_db_empty():
        logger.info("Empty state detected — running seed flow...")
        from investment_researcher.flows.sec_data import seed_flow

        seed_flow()
        logger.info("Seed flow complete.")
    else:
        logger.info("Existing data detected — skipping seed.")

    # Register and serve Prefect deployments
    logger.info("Registering Prefect deployments...")
    _serve_deployments()


def _serve_deployments():
    """Register and serve Prefect deployments with cron schedules.

    This blocks forever, acting as an in-process Prefect worker.
    """
    from investment_researcher.flows.sec_data import fast_path_flow, slow_path_flow

    fast_deploy = fast_path_flow.to_deployment(
        name="sec-fast-path-daily",
        cron="0 6 * * *",  # Daily at 6 AM UTC
        parameters={"days": 1},
    )

    slow_deploy = slow_path_flow.to_deployment(
        name="sec-slow-path-weekly",
        cron="0 2 * * 0",  # Sunday at 2 AM UTC
    )

    from prefect import serve

    logger.info("Serving Prefect deployments (fast-path daily 6AM UTC, slow-path weekly Sun 2AM UTC)...")
    serve(fast_deploy, slow_deploy)


if __name__ == "__main__":
    run_service()
