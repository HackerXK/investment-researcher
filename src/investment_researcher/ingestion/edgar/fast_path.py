"""Fast path: per-filing XBRL extraction → DuckDB.

Fetches recent 10-K/10-Q filings and extracts XBRL data directly from
individual filings. This catches new data immediately, bypassing the
companyfacts bulk data delay.
"""

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from investment_researcher.ingestion.edgar.financials import (
    FLOW_METRICS,
    RAW_CONCEPT_MAP,
    _dedup_period_end,
    _duration_bucket,
    _make_row,
    _to_date,
    _vectorized_duration_bucket,
)
from investment_researcher.ingestion.state import (
    get_processed_accessions,
    mark_filings_processed_batch,
)
from investment_researcher.ingestion.timeseries import write_financial_metrics

logger = logging.getLogger(__name__)

# Forms to process in fast path
TARGET_FORMS = ["10-K", "10-K/A", "10-Q", "10-Q/A"]


@lru_cache(maxsize=1)
def _get_cik_ticker_map() -> dict[int, str]:
    """Build a CIK → ticker mapping from edgartools reference data (cached)."""
    from edgar.reference.tickers import get_company_tickers

    tickers_df = get_company_tickers()
    return dict(zip(tickers_df["cik"].astype(int), tickers_df["ticker"]))


def _extract_metrics_from_filing(
    filing,
    ticker: str,
    cik: str,
) -> pd.DataFrame | None:
    """Extract financial metrics from a single filing's XBRL data.

    For flow metrics (income statement / cash flow), keeps only discrete-quarter
    (~90 day) and annual (~365 day) durations to avoid storing YTD cumulative
    values.  For stock metrics (balance sheet), stores as-is (point-in-time).

    Returns DataFrame with columns matching financial_metrics schema, or None.
    """
    xbrl = filing.xbrl()
    if xbrl is None:
        return None
    facts = xbrl.facts
    if facts is None:
        return None
    df = facts.to_dataframe()
    if df is None or len(df) == 0:
        return None

    rows: list[dict] = []
    accession = filing.accession_no
    form = filing.form
    filing_source = "10-K" if form in ("10-K", "10-K/A") else "10-Q"

    has_period_start = "period_start" in df.columns

    for raw_concept, metric_type in RAW_CONCEPT_MAP.items():
        concept_df = df[df["concept"] == raw_concept].copy()
        if concept_df.empty:
            continue

        # Filter by unit
        if "unit_ref" in concept_df.columns:
            if metric_type in ("eps_diluted", "eps_basic"):
                concept_df = concept_df[
                    concept_df["unit_ref"].str.contains("shares", case=False, na=False)
                    | concept_df["unit_ref"].str.contains("perShare", case=False, na=False)
                ]
            elif metric_type == "common_shares_outstanding":
                concept_df = concept_df[
                    concept_df["unit_ref"].str.contains("shares", case=False, na=False)
                ]
            else:
                concept_df = concept_df[
                    concept_df["unit_ref"].str.contains("USD", case=False, na=False)
                    & ~concept_df["unit_ref"].str.contains("shares", case=False, na=False)
                ]

        if concept_df.empty:
            continue

        # Filter out dimensioned (segment-level) data — keep only consolidated
        if "is_dimensioned" in concept_df.columns:
            non_dim = concept_df[concept_df["is_dimensioned"] == False]  # noqa: E712
            if not non_dim.empty:
                concept_df = non_dim

        if "fiscal_period" not in concept_df.columns:
            continue

        is_flow = metric_type in FLOW_METRICS

        # ── Flow metrics: emit discrete quarters + annual, derive from YTD ──
        if is_flow and has_period_start:
            concept_df["_duration"] = _vectorized_duration_bucket(
                concept_df["period_start"], concept_df["period_end"],
            )
            direct_df = concept_df[concept_df["_duration"].isin(["quarter", "annual"])]

            emitted_keys: set[tuple[str, date]] = set()

            # Emit direct quarter and annual rows
            for fiscal_period in ("FY", "Q1", "Q2", "Q3", "Q4"):
                period_data = direct_df[direct_df["fiscal_period"] == fiscal_period]
                if period_data.empty:
                    continue
                period_type = "annual" if fiscal_period == "FY" else "quarterly"
                valid = period_data.dropna(subset=["numeric_value", "period_end"])
                if valid.empty:
                    continue
                deduped = _dedup_period_end(valid)
                for _, row in deduped.iterrows():
                    pe_date = _to_date(row["period_end"])
                    val = row["numeric_value"]
                    if pe_date is None or pd.isna(val):
                        continue
                    emitted_keys.add((fiscal_period, pe_date))
                    rows.append(_make_row(
                        ticker, cik, metric_type, float(val), pe_date,
                        period_type, filing_source, accession,
                    ))

            # Derive missing quarters from within-filing YTD data
            if "fiscal_year" in concept_df.columns:
                ytd_6m = concept_df[concept_df["_duration"] == "ytd_6m"]
                ytd_9m = concept_df[concept_df["_duration"] == "ytd_9m"]
                fy_df = concept_df[concept_df["_duration"] == "annual"]
                q1_df = direct_df[
                    (direct_df["_duration"] == "quarter")
                    & (direct_df["fiscal_period"] == "Q1")
                ]

                year_data: dict[int, dict[str, tuple[float, date]]] = {}
                for df_part, bucket in [
                    (q1_df, "q1"),
                    (ytd_6m, "ytd_6m"),
                    (ytd_9m, "ytd_9m"),
                    (fy_df, "annual"),
                ]:
                    if df_part.empty:
                        continue
                    for fy_val in df_part["fiscal_year"].dropna().unique():
                        fy_int = int(fy_val)
                        subset = df_part[df_part["fiscal_year"] == fy_val]
                        valid_s = subset.dropna(subset=["numeric_value", "period_end"])
                        if valid_s.empty:
                            continue
                        best = valid_s.sort_values("period_end").iloc[-1]
                        pe_d = _to_date(best["period_end"])
                        val = best["numeric_value"]
                        if pe_d is None or pd.isna(val):
                            continue
                        year_data.setdefault(fy_int, {})[bucket] = (float(val), pe_d)

                for fy_int, data in year_data.items():
                    # Q2 = YTD_6M - Q1
                    if "ytd_6m" in data and "q1" in data:
                        q2_pe = data["ytd_6m"][1]
                        if ("Q2", q2_pe) not in emitted_keys:
                            rows.append(_make_row(
                                ticker, cik, metric_type,
                                data["ytd_6m"][0] - data["q1"][0],
                                q2_pe, "quarterly", filing_source, accession,
                            ))
                            emitted_keys.add(("Q2", q2_pe))
                    if "ytd_6m" in data and "q1" not in data:
                        logger.debug(
                            "Fast path: cannot derive Q2 for %s/%s FY%d — Q1 not in filing",
                            ticker, metric_type, fy_int,
                        )
                    # Q3 = YTD_9M - YTD_6M
                    if "ytd_9m" in data and "ytd_6m" in data:
                        q3_pe = data["ytd_9m"][1]
                        if ("Q3", q3_pe) not in emitted_keys:
                            rows.append(_make_row(
                                ticker, cik, metric_type,
                                data["ytd_9m"][0] - data["ytd_6m"][0],
                                q3_pe, "quarterly", filing_source, accession,
                            ))
                            emitted_keys.add(("Q3", q3_pe))
                    # Q4 = FY - YTD_9M
                    if "annual" in data and "ytd_9m" in data:
                        q4_pe = data["annual"][1]
                        if ("Q4", q4_pe) not in emitted_keys:
                            rows.append(_make_row(
                                ticker, cik, metric_type,
                                data["annual"][0] - data["ytd_9m"][0],
                                q4_pe, "quarterly", filing_source, accession,
                            ))
                            emitted_keys.add(("Q4", q4_pe))

            continue  # flow metric fully handled

        # ── Stock metrics (or flow without period_start): emit as-is ──
        for fiscal_period in ("FY", "Q1", "Q2", "Q3", "Q4"):
            period_data = concept_df[concept_df["fiscal_period"] == fiscal_period]
            if period_data.empty:
                continue

            period_type = "annual" if fiscal_period == "FY" else "quarterly"

            if "numeric_value" not in period_data.columns or "period_end" not in period_data.columns:
                continue

            valid = period_data.dropna(subset=["numeric_value", "period_end"])
            if valid.empty:
                continue

            deduped = _dedup_period_end(valid)
            for _, row in deduped.iterrows():
                pe_date = _to_date(row["period_end"])
                val = row["numeric_value"]
                if pe_date is None or pd.isna(val):
                    continue
                rows.append(_make_row(
                    ticker, cik, metric_type, float(val), pe_date,
                    period_type, filing_source, accession,
                ))

    if not rows:
        return None

    result = pd.DataFrame(rows)
    result = result.drop_duplicates(
        subset=["ticker", "metric_type", "period_type", "period_end"],
        keep="first",
    )
    return result


def process_recent_filings(
    days: int = 1,
    db_path: str | None = None,
    state_db_path: str | None = None,
) -> tuple[int, int]:
    """Process recent 10-K/10-Q filings filed in the last N days.

    Args:
        days: Look back N days for new filings.
        db_path: Override DuckDB path.
        state_db_path: Override state DB path.

    Returns:
        Tuple of (filings_processed, total_rows_written).
    """
    import edgar

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    logger.info("Fast path: fetching filings since %s", since)

    cik_ticker_map = _get_cik_ticker_map()
    # Load all processed accessions once — O(1) lookup instead of per-filing DB query
    processed = get_processed_accessions(db_path=state_db_path)
    filings_processed = 0
    total_rows = 0
    newly_processed: list[tuple[str, str | None, str | None, str | None]] = []

    for form in TARGET_FORMS:
        try:
            filings = edgar.get_filings(form=form, filing_date=f"{since}:")
        except Exception as e:
            logger.warning("Failed to get %s filings: %s", form, e)
            continue

        logger.info("Found %d %s filings since %s", len(filings), form, since)

        for i in range(len(filings)):
            try:
                filing = filings[i]
            except Exception:
                continue

            accession = filing.accession_no
            cik = int(filing.cik)

            # Skip already processed (in-memory set check)
            if accession in processed:
                continue

            # Look up ticker — skip without marking so stale reference
            # data can be retried on the next run after a refresh.
            ticker = cik_ticker_map.get(cik)
            if not ticker:
                logger.debug("No ticker found for CIK %s, skipping", cik)
                continue

            # Extract metrics — let transient XBRL failures propagate
            # so we skip marking and can retry on the next run.
            try:
                metrics_df = _extract_metrics_from_filing(filing, ticker, str(cik))
            except Exception as e:
                logger.debug("XBRL parse failed for %s/%s: %s", ticker, accession, e)
                continue

            if metrics_df is not None and len(metrics_df) > 0:
                count = write_financial_metrics(metrics_df, db_path=db_path)
                total_rows += count
                filings_processed += 1
                logger.debug(
                    "Fast path: %s (%s) — %d metrics from %s",
                    ticker, accession, count, filing.form,
                )

            # Queue for batch marking after all filings processed
            newly_processed.append((
                accession, ticker, filing.form, str(filing.filing_date),
            ))
            processed.add(accession)  # prevent re-processing within this run

    # Batch-mark all processed filings in a single transaction
    mark_filings_processed_batch(newly_processed, db_path=state_db_path)

    logger.info(
        "Fast path complete: %d filings processed, %d rows written",
        filings_processed,
        total_rows,
    )
    return filings_processed, total_rows
