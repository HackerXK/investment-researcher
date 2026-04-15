"""DuckDB writer — initializes, repairs, and writes to the financial_metrics table.

Schema follows 02-graph-schema.md § Time Series Data Store exactly.
"""

import json
import logging
from datetime import date as _date
from pathlib import Path

import duckdb
import pandas as pd

from investment_researcher.config import DUCKDB_PATH_RUNTIME
from investment_researcher.signs import (
    NEGATIVE_MAGNITUDE_METRICS,
    POSITIVE_MAGNITUDE_METRICS,
    SIGN_FLIP_METRICS,
)

logger = logging.getLogger(__name__)

# SQL statements matching the exact schema from 02-graph-schema.md
_CREATE_FINANCIAL_METRICS = """
CREATE TABLE IF NOT EXISTS financial_metrics (
    ticker       VARCHAR NOT NULL,
    cik          VARCHAR,
    metric_type  VARCHAR NOT NULL,
    value        DOUBLE NOT NULL,
    currency     VARCHAR DEFAULT 'USD',
    period       VARCHAR NOT NULL,
    period_type  VARCHAR NOT NULL,
    period_end   DATE NOT NULL,
    source       VARCHAR,
    accession    VARCHAR,
    ingested_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, metric_type, period_type, period_end)
);
"""

_CREATE_MACRO_TIMESERIES = """
CREATE TABLE IF NOT EXISTS macro_timeseries (
    indicator_id  VARCHAR NOT NULL,
    name          VARCHAR NOT NULL,
    value         DOUBLE NOT NULL,
    unit          VARCHAR,
    date          DATE NOT NULL,
    source        VARCHAR,
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (indicator_id, date)
);
"""

_CREATE_DB_MAINTENANCE_RUNS = """
CREATE TABLE IF NOT EXISTS db_maintenance_runs (
    name         VARCHAR PRIMARY KEY,
    ran_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details_json VARCHAR
);
"""

_SIGN_NORMALIZATION_MAINTENANCE = "normalize_financial_metric_signs_v1"


def _ensure_maintenance_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_CREATE_DB_MAINTENANCE_RUNS)


def _has_db_maintenance_run(
    con: duckdb.DuckDBPyConnection,
    name: str,
) -> bool:
    _ensure_maintenance_tables(con)
    row = con.execute(
        "SELECT 1 FROM db_maintenance_runs WHERE name = ?",
        [name],
    ).fetchone()
    return row is not None


def get_connection(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection, creating the database file if needed."""
    path = db_path or DUCKDB_PATH_RUNTIME
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(path)


def initialize_db(db_path: str | None = None) -> None:
    """Create the financial_metrics and macro_timeseries tables if they don't exist."""
    con = get_connection(db_path)
    try:
        con.execute(_CREATE_FINANCIAL_METRICS)
        con.execute(_CREATE_MACRO_TIMESERIES)
        _ensure_maintenance_tables(con)
        logger.info("DuckDB tables initialized at %s", db_path or DUCKDB_PATH_RUNTIME)
    finally:
        con.close()


def normalize_financial_metric_signs(
    db_path: str | None = None,
    dry_run: bool = False,
    allow_rerun: bool = False,
) -> dict[str, object]:
    """Rewrite stored financial metrics into the repo's canonical sign convention.

    This is primarily intended as a one-time migration for databases populated
    before sign normalization moved into the ingestion boundary.
    """
    metric_rules: list[tuple[str, str, str, str]] = []
    metric_rules.extend(
        (metric_type, "negative_magnitude", "value > 0", "value = -ABS(value)")
        for metric_type in sorted(NEGATIVE_MAGNITUDE_METRICS)
    )
    metric_rules.extend(
        (metric_type, "positive_magnitude", "value < 0", "value = ABS(value)")
        for metric_type in sorted(POSITIVE_MAGNITUDE_METRICS)
    )
    metric_rules.extend(
        (metric_type, "sign_flip", "value <> 0", "value = -value")
        for metric_type in sorted(SIGN_FLIP_METRICS)
    )

    con = get_connection(db_path)
    try:
        con.execute(_CREATE_FINANCIAL_METRICS)
        _ensure_maintenance_tables(con)

        already_applied = _has_db_maintenance_run(con, _SIGN_NORMALIZATION_MAINTENANCE)
        if already_applied and not allow_rerun:
            if dry_run:
                return {
                    "dry_run": True,
                    "already_applied": True,
                    "maintenance_name": _SIGN_NORMALIZATION_MAINTENANCE,
                    "rows_changed": 0,
                    "by_rule": {
                        "negative_magnitude": 0,
                        "positive_magnitude": 0,
                        "sign_flip": 0,
                    },
                    "by_metric_type": [],
                }
            raise ValueError(
                "Financial metric sign normalization has already been applied to this database. "
                "Use --force only if you intentionally want to rerun the migration."
            )

        metric_summaries: list[dict[str, object]] = []
        by_rule = {
            "negative_magnitude": 0,
            "positive_magnitude": 0,
            "sign_flip": 0,
        }

        for metric_type, rule_name, predicate, assignment in metric_rules:
            rows_changed = con.execute(
                f"SELECT COUNT(*) FROM financial_metrics WHERE metric_type = ? AND {predicate}",
                [metric_type],
            ).fetchone()[0]
            if not dry_run and rows_changed:
                con.execute(
                    f"UPDATE financial_metrics SET {assignment}, ingested_at = CURRENT_TIMESTAMP "
                    f"WHERE metric_type = ? AND {predicate}",
                    [metric_type],
                )
            metric_summaries.append(
                {
                    "metric_type": metric_type,
                    "rule": rule_name,
                    "rows_changed": int(rows_changed),
                }
            )
            by_rule[rule_name] += int(rows_changed)

        total_rows_changed = sum(item["rows_changed"] for item in metric_summaries)
        payload = {
            "dry_run": dry_run,
            "already_applied": already_applied,
            "maintenance_name": _SIGN_NORMALIZATION_MAINTENANCE,
            "rows_changed": int(total_rows_changed),
            "by_rule": by_rule,
            "by_metric_type": [
                item for item in metric_summaries if item["rows_changed"] > 0
            ],
        }

        if dry_run:
            return payload

        con.execute(
            """
            INSERT OR REPLACE INTO db_maintenance_runs (name, ran_at, details_json)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            """,
            [_SIGN_NORMALIZATION_MAINTENANCE, json.dumps(payload, sort_keys=True)],
        )
        return payload
    finally:
        con.close()


def write_financial_metrics(df: pd.DataFrame, db_path: str | None = None) -> int:
    """Write financial metrics to DuckDB using INSERT OR REPLACE (upsert).

    Args:
        df: DataFrame with columns matching financial_metrics table schema:
            ticker, cik, metric_type, value, currency, period, period_type,
            period_end, source, accession
        db_path: Optional override for the DuckDB path.

    Returns:
        Number of rows written.
    """
    if df.empty:
        return 0

    required_cols = {"ticker", "metric_type", "value", "period", "period_type", "period_end"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    # Ensure optional columns exist with defaults
    if "cik" not in df.columns:
        df = df.assign(cik=None)
    if "currency" not in df.columns:
        df = df.assign(currency="USD")
    if "source" not in df.columns:
        df = df.assign(source=None)
    if "accession" not in df.columns:
        df = df.assign(accession=None)

    # Convert period_end to date only if needed
    sample = df["period_end"].iloc[0]
    if not isinstance(sample, _date) or isinstance(sample, pd.Timestamp):
        df = df.copy()
        df["period_end"] = pd.to_datetime(df["period_end"]).dt.date

    con = get_connection(db_path)
    try:
        # Use INSERT OR REPLACE to upsert — both paths coexist safely
        con.execute("""
            INSERT OR REPLACE INTO financial_metrics
                (ticker, cik, metric_type, value, currency, period, period_type,
                 period_end, source, accession, ingested_at)
            SELECT
                ticker, cik, metric_type, value, currency, period, period_type,
                period_end, source, accession, CURRENT_TIMESTAMP
            FROM df
        """)
        count = len(df)
        logger.info("Wrote %d rows to financial_metrics", count)
        return count
    finally:
        con.close()


def delete_company_financial_metrics(
    tickers: list[str] | tuple[str, ...] | str,
    db_path: str | None = None,
) -> int:
    """Delete all financial metric rows for the requested ticker(s)."""
    if isinstance(tickers, str):
        ticker_list = [tickers]
    else:
        ticker_list = list(tickers)

    normalized = sorted({t.strip().upper() for t in ticker_list if t and t.strip()})
    if not normalized:
        return 0

    placeholders = ", ".join("?" for _ in normalized)
    con = get_connection(db_path)
    try:
        delete_count = con.execute(
            f"SELECT COUNT(*) FROM financial_metrics WHERE ticker IN ({placeholders})",
            normalized,
        ).fetchone()[0]
        con.execute(
            f"DELETE FROM financial_metrics WHERE ticker IN ({placeholders})",
            normalized,
        )
        logger.info("Deleted %d financial_metrics rows for tickers=%s", delete_count, normalized)
        return delete_count
    finally:
        con.close()


def is_db_empty(db_path: str | None = None) -> bool:
    """Check if the financial_metrics table is empty or doesn't exist."""
    path = db_path or DUCKDB_PATH_RUNTIME
    if not Path(path).exists():
        return True
    con = get_connection(db_path)
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM financial_metrics"
        ).fetchone()[0]
        return count == 0
    except duckdb.CatalogException:
        return True
    finally:
        con.close()
