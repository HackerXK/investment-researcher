"""Console entry points for Investment Researcher."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from investment_researcher.ingestion.edgar.financials import rerun_slow_path_for_companies
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.timeseries import (
    initialize_db,
    normalize_financial_metric_signs,
)


def _parse_cli_tickers(values: Sequence[str]) -> list[str]:
    tickers: list[str] = []
    for value in values:
        for item in value.split(","):
            ticker = item.strip().upper()
            if ticker:
                tickers.append(ticker)
    return tickers


def _write_json_payload(payload: dict[str, object], compact: bool) -> None:
    dump_kwargs = {"sort_keys": False}
    if compact:
        dump_kwargs["separators"] = (",", ":")
    else:
        dump_kwargs["indent"] = 2

    json.dump(payload, sys.stdout, **dump_kwargs)
    sys.stdout.write("\n")


def rerun_slow_path_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ir-rerun-slow-path",
        description="Delete then re-extract slow-path data for the selected ticker symbols.",
    )
    parser.add_argument(
        "tickers",
        nargs="+",
        help="Ticker symbols as separate arguments and/or comma-separated lists.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the DuckDB path used for financial_metrics.",
    )
    parser.add_argument(
        "--state-db-path",
        default=None,
        help="Override the SQLite path used for company_extraction_state.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact single-line JSON instead of pretty-printed JSON.",
    )

    args = parser.parse_args(argv)
    tickers = _parse_cli_tickers(args.tickers)
    if not tickers:
        parser.error("At least one ticker is required.")

    initialize_db(db_path=args.db_path)
    initialize_state_db(db_path=args.state_db_path)

    results = rerun_slow_path_for_companies(
        tickers,
        db_path=args.db_path,
        state_db_path=args.state_db_path,
    )
    payload = {
        "tickers": [str(result["ticker"]) for result in results],
        "results": results,
        "total_deleted_rows": sum(int(result["deleted_rows"]) for result in results),
        "total_deleted_state_rows": sum(
            int(result["deleted_state_rows"]) for result in results
        ),
        "total_written_rows": sum(int(result["written_rows"]) for result in results),
    }

    _write_json_payload(payload, compact=args.compact)
    return 0


def normalize_metric_signs_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ir-normalize-metric-signs",
        description="Normalize stored financial metric signs in DuckDB to the canonical repo convention.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the DuckDB path used for financial_metrics.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would change without writing to DuckDB.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow rerunning the migration after it has already been recorded.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact single-line JSON instead of pretty-printed JSON.",
    )

    args = parser.parse_args(argv)

    initialize_db(db_path=args.db_path)
    try:
        payload = normalize_financial_metric_signs(
            db_path=args.db_path,
            dry_run=args.dry_run,
            allow_rerun=args.force,
        )
    except ValueError as exc:
        parser.error(str(exc))

    _write_json_payload(payload, compact=args.compact)
    return 0


if __name__ == "__main__":
    raise SystemExit(rerun_slow_path_cli())