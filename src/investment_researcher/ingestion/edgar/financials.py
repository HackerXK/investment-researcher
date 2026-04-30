"""Slow path: bulk extraction from companyfacts → DuckDB.

Uses company.get_facts().to_dataframe() to extract all historical XBRL data
for all ~10,000+ SEC-filing companies. Re-extracts all companies weekly to
catch amendments and corrections.

Stores **discrete quarter values** (Q1–Q4) for flow metrics (income statement,
cash flow) by decomposing YTD cumulative values filed in 10-Q reports:
  Q2 = YTD_6M − Q1
  Q3 = YTD_9M − YTD_6M
  Q4 = FY − YTD_9M

Balance sheet items are point-in-time and stored as-is per quarter.

This enables TTM (Trailing Twelve Months) = sum of most recent 4 discrete quarters.
"""

import logging
from collections.abc import Iterator
from datetime import date
from typing import NamedTuple

import pandas as pd

from investment_researcher.ingestion.state import update_company_extraction
from investment_researcher.signs import normalize_extracted_metric_value
from investment_researcher.ingestion.timeseries import (
    delete_company_financial_metrics,
    write_financial_metrics,
)
from investment_researcher.ingestion.state import delete_company_extraction_state

logger = logging.getLogger(__name__)

# ── Metric classification ────────────────────────────────────────────────────
# Flow metrics (income statement + cash flow): cumulative in YTD filings,
# need discrete quarter derivation.  Stock metrics (balance sheet): point-in-
# time snapshots, stored as-is.

FLOW_METRICS: set[str] = {
    "revenue", "net_income", "gross_profit", "operating_income",
    "cost_of_revenue", "operating_expenses", "income_tax_expense",
    "research_and_development", "interest_expense",
    "depreciation_and_amortization", "eps_diluted", "eps_basic",
    "ebitda", "free_cash_flow",
    "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    "capex", "dividends_paid",
}

FLOW_DERIVED_GROSS_PROFIT_COGS_RATIO_RANGE = (0.2, 0.95)

STOCK_METRICS: set[str] = {
    "total_assets", "total_liabilities", "stockholders_equity", "cash",
    "long_term_debt", "short_term_debt", "inventory", "accounts_receivable",
    "accounts_payable", "goodwill", "intangible_assets",
    "total_current_assets", "total_current_liabilities",
    "retained_earnings", "common_shares_outstanding",
    # Short-term debt components (commercial paper + current portion of LTD)
    "commercial_paper", "long_term_debt_current",
    # Liquid investments (used in cash_per_share and quick ratio)
    "short_term_investments",
    # Non-trade receivables (AAPL vendor non-trade receivables, etc.)
    "nontrade_receivables",
}

# Duration buckets (days) — matches edgartools TTMCalculator


class DurationRange(NamedTuple):
    min_days: int
    max_days: int


DURATION_QUARTER = DurationRange(70, 120)    # ~3 months (discrete Q1, or discrete Q2/Q3)
DURATION_YTD_6M = DurationRange(140, 229)    # ~6 months (Q1+Q2 cumulative)
DURATION_YTD_9M = DurationRange(230, 329)    # ~9 months (Q1+Q2+Q3 cumulative)
DURATION_ANNUAL = DurationRange(330, 420)    # ~12 months (full fiscal year)

# Map edgartools supported concept names to our metric_type names.
# These use the high-level concept names from facts.time_series().
CONCEPT_MAP: dict[str, str] = {
    "revenue": "revenue",
    "net_income": "net_income",
    "gross_profit": "gross_profit",
    "operating_income": "operating_income",
    "earnings_per_share_diluted": "eps_diluted",
    "earnings_per_share_basic": "eps_basic",
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "stockholders_equity": "stockholders_equity",
    "cash_and_equivalents": "cash",
    "long_term_debt": "long_term_debt",
    "operating_cash_flow": "operating_cash_flow",
    "cost_of_revenue": "cost_of_revenue",
    "operating_expenses": "operating_expenses",
    "income_tax_expense": "income_tax_expense",
    "research_and_development": "research_and_development",
    "free_cash_flow": "free_cash_flow",
    "ebitda": "ebitda",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
    "capex": "capex",
    "dividends_paid": "dividends_paid",
    "inventory": "inventory",
    "accounts_receivable": "accounts_receivable",
    "accounts_payable": "accounts_payable",
    "goodwill": "goodwill",
    "intangible_assets": "intangible_assets",
    "total_current_assets": "total_current_assets",
    "total_current_liabilities": "total_current_liabilities",
    "short_term_debt": "short_term_debt",
    "retained_earnings": "retained_earnings",
    "common_shares_outstanding": "common_shares_outstanding",
    "interest_expense": "interest_expense",
    "depreciation_and_amortization": "depreciation_and_amortization",
}

# Raw XBRL concept name -> our metric_type (fallback when time_series doesn't work)
RAW_CONCEPT_MAP: dict[str, str] = {
    # Income statement
    "us-gaap:Revenues": "revenue",
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "us-gaap:SalesRevenueNet": "revenue",
    "us-gaap:NetIncomeLoss": "net_income",
    "us-gaap:GrossProfit": "gross_profit",
    "us-gaap:OperatingIncomeLoss": "operating_income",
    "us-gaap:EarningsPerShareDiluted": "eps_diluted",
    "us-gaap:EarningsPerShareBasic": "eps_basic",
    "us-gaap:CostOfGoodsAndServicesSold": "cost_of_revenue",
    "us-gaap:CostOfRevenue": "cost_of_revenue",
    "us-gaap:OperatingExpenses": "operating_expenses",
    "us-gaap:IncomeTaxExpenseBenefit": "income_tax_expense",
    "us-gaap:ResearchAndDevelopmentExpense": "research_and_development",
    "us-gaap:InterestExpense": "interest_expense",
    "us-gaap:DepreciationDepletionAndAmortization": "depreciation_and_amortization",
    "us-gaap:DepreciationAndAmortization": "depreciation_and_amortization",
    "us-gaap:DepreciationAmortizationAndAccretionNet": "depreciation_and_amortization",
    # Balance sheet
    "us-gaap:Assets": "total_assets",
    "us-gaap:Liabilities": "total_liabilities",
    "us-gaap:StockholdersEquity": "stockholders_equity",
    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "stockholders_equity",
    "us-gaap:CashAndCashEquivalentsAtCarryingValue": "cash",
    "us-gaap:LongTermDebt": "long_term_debt",
    "us-gaap:LongTermDebtNoncurrent": "long_term_debt",
    "us-gaap:LongTermDebtAndCapitalLeaseObligations": "long_term_debt",
    "us-gaap:Inventory": "inventory",
    "us-gaap:InventoryNet": "inventory",
    "us-gaap:AccountsReceivableNetCurrent": "accounts_receivable",
    "us-gaap:AccountsPayableCurrent": "accounts_payable",
    "us-gaap:Goodwill": "goodwill",
    "us-gaap:IntangibleAssetsNetExcludingGoodwill": "intangible_assets",
    "us-gaap:AssetsCurrent": "total_current_assets",
    "us-gaap:LiabilitiesCurrent": "total_current_liabilities",
    "us-gaap:ShortTermBorrowings": "short_term_debt",
    "us-gaap:ShortTermDebt": "short_term_debt",
    "us-gaap:DebtCurrent": "short_term_debt",
    # Commercial paper (AAPL, NVDA use this for short-term borrowing)
    "us-gaap:CommercialPaper": "commercial_paper",
    # Current portion of long-term debt (contributes to total short-term debt)
    "us-gaap:LongTermDebtCurrent": "long_term_debt_current",
    "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent": "long_term_debt_current",
    # Short-term investments / marketable securities (for cash_per_share)
    "us-gaap:ShortTermInvestments": "short_term_investments",
    "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent": "short_term_investments",
    "us-gaap:MarketableSecuritiesCurrent": "short_term_investments",
    # Non-trade receivables (AAPL vendor non-trade, other broad receivables)
    "us-gaap:NontradeReceivablesCurrent": "nontrade_receivables",
    "us-gaap:RetainedEarningsAccumulatedDeficit": "retained_earnings",
    "us-gaap:CommonStockSharesOutstanding": "common_shares_outstanding",
    # Cash flow
    "us-gaap:NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": "operating_cash_flow",
    "us-gaap:NetCashProvidedByUsedInInvestingActivities": "investing_cash_flow",
    "us-gaap:NetCashProvidedByUsedInInvestingActivitiesContinuingOperations": "investing_cash_flow",
    "us-gaap:NetCashProvidedByUsedInFinancingActivities": "financing_cash_flow",
    "us-gaap:NetCashProvidedByUsedInFinancingActivitiesContinuingOperations": "financing_cash_flow",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "us-gaap:PaymentsToAcquireProductiveAssets": "capex",
    "us-gaap:PaymentsOfDividends": "dividends_paid",
    "us-gaap:PaymentsOfDividendsCommonStock": "dividends_paid",
}

_LONG_TERM_DEBT_TOTAL_CONCEPTS = frozenset({
    "us-gaap:LongTermDebt",
    "us-gaap:LongTermDebtAndCapitalLeaseObligations",
})

_LONG_TERM_DEBT_NONCURRENT_CONCEPTS = frozenset({
    "us-gaap:LongTermDebtNoncurrent",
})

_LONG_TERM_DEBT_CURRENT_CONCEPTS = frozenset({
    "us-gaap:LongTermDebtCurrent",
    "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
})


def _make_period_label(period_end: date, period_type: str) -> str:
    """Create unambiguous period label using the SEC convention.

    Quarterly → 'Quarter Ended 09/30/2025'
    Annual   → 'Twelve Months Ended 09/30/2025'

    Uses the actual period_end date — no fiscal-quarter label (Q1/Q2/Q3/Q4)
    which would be ambiguous across companies with different fiscal year-ends.
    """
    pe = pd.Timestamp(period_end).date() if not isinstance(period_end, date) else period_end
    date_str = pe.strftime("%m/%d/%Y")
    if period_type == "annual":
        return f"Twelve Months Ended {date_str}"
    return f"Quarter Ended {date_str}"


def _to_date(val) -> date | None:
    """Convert any date-like value to datetime.date, or None if invalid."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        return val
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def _make_row(
    ticker: str,
    cik: str | None,
    metric_type: str,
    value: float,
    period_end: date,
    period_type: str,
    source: str,
    accession: str | None = None,
) -> dict:
    """Build a single metric row dict matching the financial_metrics schema."""
    return {
        "ticker": ticker,
        "cik": cik,
        "metric_type": metric_type,
        "value": normalize_extracted_metric_value(metric_type, value),
        "currency": "USD",
        "period": _make_period_label(period_end, period_type),
        "period_type": period_type,
        "period_end": period_end,
        "source": source,
        "accession": accession,
    }


def _metric_row_value(metric_rows: dict[str, dict], metric_type: str) -> float | None:
    """Return a numeric row value from a period metric index, if present."""
    row = metric_rows.get(metric_type)
    if not row:
        return None
    val = row.get("value")
    if val is None or pd.isna(val):
        return None
    return float(val)


def _derive_missing_flow_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill sparse flow metrics from adjacent extracted line items.

    Some filers do not expose recent companyfacts rows for `gross_profit` or
    `operating_expenses` even though the filing still reports the required
    inputs. Derive only the missing rows and persist them during extraction so
    downstream queries and charts see complete income statement coverage.
    """
    if df.empty:
        return df.iloc[0:0].copy()

    derived_rows: list[dict] = []

    for _, period_df in df.groupby(["ticker", "period_type", "period_end"], sort=False):
        metric_rows = {
            row["metric_type"]: row
            for row in period_df.to_dict("records")
        }
        period_type = period_df["period_type"].iloc[0]
        period_end = _to_date(period_df["period_end"].iloc[0])
        if period_end is None:
            continue

        ticker = period_df["ticker"].iloc[0]
        cik_series = period_df["cik"].dropna() if "cik" in period_df.columns else pd.Series(dtype=object)
        cik = str(cik_series.iloc[0]) if not cik_series.empty else None

        accession = None
        if "accession" in period_df.columns:
            accessions = sorted({
                str(a) for a in period_df["accession"]
                if a is not None and not pd.isna(a) and str(a)
            })
            if len(accessions) == 1:
                accession = accessions[0]

        source_values = []
        if "source" in period_df.columns:
            source_values = sorted({
                str(s) for s in period_df["source"]
                if s is not None and not pd.isna(s) and str(s)
            })

        if len(source_values) == 1 and not source_values[0].endswith("-derived"):
            derived_source = f"{source_values[0]}-derived"
        else:
            derived_source = "10-K-derived" if period_type == "annual" else "10-Q-derived"

        gross_profit = _metric_row_value(metric_rows, "gross_profit")
        if gross_profit is None:
            revenue = _metric_row_value(metric_rows, "revenue")
            cost_of_revenue = _metric_row_value(metric_rows, "cost_of_revenue")
            if revenue not in (None, 0) and cost_of_revenue is not None:
                cogs_ratio = abs(cost_of_revenue / revenue)
                min_ratio, max_ratio = FLOW_DERIVED_GROSS_PROFIT_COGS_RATIO_RANGE
                if min_ratio <= cogs_ratio <= max_ratio:
                    gross_profit = revenue + cost_of_revenue
                    derived_rows.append(_make_row(
                        ticker,
                        cik,
                        "gross_profit",
                        gross_profit,
                        period_end,
                        period_type,
                        derived_source,
                        accession,
                    ))
                    metric_rows["gross_profit"] = {"value": gross_profit}

        if _metric_row_value(metric_rows, "operating_expenses") is None:
            operating_income = _metric_row_value(metric_rows, "operating_income")
            if gross_profit is not None and operating_income is not None:
                operating_expenses = operating_income - gross_profit
                if operating_expenses <= 0:
                    derived_rows.append(_make_row(
                        ticker,
                        cik,
                        "operating_expenses",
                        operating_expenses,
                        period_end,
                        period_type,
                        derived_source,
                        accession,
                    ))

    if not derived_rows:
        return df.iloc[0:0].copy()

    return pd.DataFrame(derived_rows)


def _dedup_period_end(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate rows by period_end, keeping the max numeric_value."""
    agg_cols: dict[str, str] = {"numeric_value": "max"}
    if "fiscal_year" in df.columns:
        agg_cols["fiscal_year"] = "first"
    return df.groupby("period_end", as_index=False).agg(agg_cols)


def _iter_deduped_period_values(df_part: pd.DataFrame) -> Iterator[tuple[date, float]]:
    """Yield validated period_end/value pairs from a deduplicated metric slice."""
    deduped = _dedup_period_end(df_part)
    for _, row in deduped.iterrows():
        pe_date = _to_date(row["period_end"])
        value = row["numeric_value"]
        if pe_date is None or pd.isna(value):
            continue
        yield pe_date, float(value)


def _select_annual_flow_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return only credible annual flow rows.

    Some companyfacts series include noisy contexts where quarter or short-period
    values are mislabeled as ``FY``, or 12-month rolling values are attached to
    quarter fiscal periods. We only persist annual flow rows when they satisfy
    the annual-duration check (when available) and are tagged as ``FY``.

    Some time_series() frames also expose multiple FY-labelled rows for the same
    period_end with conflicting fiscal_year labels. In that case, keep the row
    selected by _dedup_period_end() for that period_end and ignore fiscal_year.
    """
    annual_df = df.copy()

    if "_duration" not in annual_df.columns and {
        "period_start", "period_end",
    }.issubset(annual_df.columns):
        annual_df["_duration"] = _vectorized_duration_bucket(
            annual_df["period_start"], annual_df["period_end"],
        )

    if "_duration" in annual_df.columns:
        annual_df = annual_df[annual_df["_duration"] == "annual"]
    if "fiscal_period" in annual_df.columns:
        annual_df = annual_df[annual_df["fiscal_period"] == "FY"]
    if annual_df.empty:
        return annual_df

    return _dedup_period_end(annual_df)


def _duration_bucket(period_start, period_end) -> str | None:
    """Classify a duration period into a bucket based on day count."""
    ps = _to_date(period_start)
    pe = _to_date(period_end)
    if ps is None or pe is None:
        return None
    days = (pe - ps).days

    if DURATION_QUARTER.min_days <= days <= DURATION_QUARTER.max_days:
        return "quarter"
    if DURATION_YTD_6M.min_days <= days <= DURATION_YTD_6M.max_days:
        return "ytd_6m"
    if DURATION_YTD_9M.min_days <= days <= DURATION_YTD_9M.max_days:
        return "ytd_9m"
    if DURATION_ANNUAL.min_days <= days <= DURATION_ANNUAL.max_days:
        return "annual"
    return None


def _vectorized_duration_bucket(
    period_start: pd.Series, period_end: pd.Series,
) -> pd.Series:
    """Vectorized duration bucket classification for entire Series.

    Equivalent to applying _duration_bucket row-by-row but operates on
    whole columns — significantly faster on large DataFrames.
    """
    ps = pd.to_datetime(period_start, errors="coerce")
    pe = pd.to_datetime(period_end, errors="coerce")
    days = (pe - ps).dt.days

    result = pd.Series(None, index=period_start.index, dtype=object)
    result[(days >= DURATION_QUARTER.min_days) & (days <= DURATION_QUARTER.max_days)] = "quarter"
    result[(days >= DURATION_YTD_6M.min_days) & (days <= DURATION_YTD_6M.max_days)] = "ytd_6m"
    result[(days >= DURATION_YTD_9M.min_days) & (days <= DURATION_YTD_9M.max_days)] = "ytd_9m"
    result[(days >= DURATION_ANNUAL.min_days) & (days <= DURATION_ANNUAL.max_days)] = "annual"
    return result


def extract_company_facts(
    ticker: str,
    cik: str | None = None,
    db_path: str | None = None,
    state_db_path: str | None = None,
) -> int:
    """Extract all financial facts for a company from companyfacts → DuckDB.

    Runs **both** extraction strategies and merges at the period level:
      - Strategy 1: edgartools TTMCalculator.quarterize() for flow metrics
        (gives discrete Q1–Q4 including derived Q4 = FY − YTD_9M), and
        query().by_period_length() for stock (balance sheet) metrics.
      - Strategy 2: raw to_dataframe() with duration-based filtering
        (keeps ~90-day discrete periods for flow metrics, derives Q4
        from annual − YTD_9M when only YTD is available).

    Strategy 1 data is preferred when both cover the same period; Strategy 2
    fills any period-level gaps.

    Returns:
        Number of rows written to DuckDB.
    """
    import edgar
    from edgar.ttm.calculator import TTMCalculator

    logger.info("Starting extraction for %s", ticker)

    try:
        company = edgar.Company(ticker)
    except Exception as e:
        logger.warning("Failed to lookup company %s: %s", ticker, e)
        return 0

    # Prefer caller-provided CIK when present; fall back to company lookup.
    if cik is not None and str(cik).strip():
        company_cik = str(cik)
    else:
        company_cik = str(company.cik) if hasattr(company, "cik") else None

    try:
        facts = company.get_facts()
    except Exception as e:
        logger.warning("Failed to get facts for %s: %s", ticker, e)
        return 0

    if facts is None:
        logger.debug("No facts available for %s", ticker)
        return 0

    # ── Strategy 1 ────────────────────────────────────────────────────────
    strategy1_rows: list[dict] = []
    s1_metrics_found: set[str] = set()
    s1_metrics_empty: set[str] = set()

    for concept_name, metric_type in CONCEPT_MAP.items():
        before = len(strategy1_rows)
        try:
            if metric_type in FLOW_METRICS:
                _extract_flow_s1(facts, concept_name, metric_type,
                                 ticker, company_cik, strategy1_rows,
                                 TTMCalculator)
            else:
                _extract_stock_s1(facts, concept_name, metric_type,
                                  ticker, company_cik, strategy1_rows)
        except Exception as e:
            logger.debug("S1 failed for %s/%s: %s", ticker, concept_name, e)
        added = len(strategy1_rows) - before
        if added > 0:
            s1_metrics_found.add(metric_type)
            logger.debug("S1 %s/%s: +%d rows", ticker, concept_name, added)
        else:
            s1_metrics_empty.add(metric_type)

    logger.info(
        "S1 %s: %d rows across %d metrics; missing: %s",
        ticker, len(strategy1_rows), len(s1_metrics_found),
        sorted(s1_metrics_empty - s1_metrics_found) or "none",
    )

    # ── Strategy 2: raw to_dataframe() with duration-based filtering ──────
    strategy2_rows: list[dict] = []
    raw_df = None
    try:
        raw_df = facts.to_dataframe()
        if raw_df is not None and len(raw_df) > 0:
            logger.debug("S2 %s: raw dataframe has %d rows", ticker, len(raw_df))
            _extract_from_raw_df(
                raw_df, ticker, company_cik,
                target_metrics=set(RAW_CONCEPT_MAP.values()),
                all_rows=strategy2_rows,
            )
            logger.info("S2 %s: %d rows extracted", ticker, len(strategy2_rows))
        else:
            logger.warning("S2 %s: to_dataframe() returned empty", ticker)
    except Exception as e:
        logger.debug("to_dataframe failed for %s: %s", ticker, e)

    # ── Merge: Strategy 1 is primary, Strategy 2 fills period-level gaps ──
    s1_keys = {
        (r["metric_type"], r["period_type"], r["period_end"])
        for r in strategy1_rows
    }
    merged_rows = list(strategy1_rows)
    s2_added = 0
    for row in strategy2_rows:
        key = (row["metric_type"], row["period_type"], row["period_end"])
        if key not in s1_keys:
            merged_rows.append(row)
            s1_keys.add(key)
            s2_added += 1

    if s2_added > 0:
        logger.debug(
            "%s: Strategy 2 filled %d period-level gaps (S1: %d, total: %d)",
            ticker, s2_added, len(strategy1_rows), len(merged_rows),
        )

    if not merged_rows:
        logger.debug("No financial data extracted for %s", ticker)
        return 0

    df = pd.DataFrame(merged_rows)
    df = df.drop_duplicates(
        subset=["ticker", "metric_type", "period_type", "period_end"],
        keep="first",
    )

    canonical_long_term_debt_df = _extract_canonical_long_term_debt_from_raw(
        raw_df,
        ticker,
        company_cik,
    )
    if not canonical_long_term_debt_df.empty:
        override_keys = canonical_long_term_debt_df[["period_type", "period_end"]].drop_duplicates()
        override_keys["_override"] = True
        df = df.merge(override_keys, on=["period_type", "period_end"], how="left")
        df = df[
            ~(
                (df["metric_type"] == "long_term_debt")
                & df["_override"].eq(True)
            )
        ].drop(columns=["_override"])
        df = pd.concat([df, canonical_long_term_debt_df], ignore_index=True)
        df = df.drop_duplicates(
            subset=["ticker", "metric_type", "period_type", "period_end"],
            keep="last",
        )

    derived_df = _derive_missing_flow_rows(df)
    if not derived_df.empty:
        df = pd.concat([df, derived_df], ignore_index=True)
        df = df.drop_duplicates(
            subset=["ticker", "metric_type", "period_type", "period_end"],
            keep="first",
        )
        logger.info("%s: derived %d fallback flow rows", ticker, len(derived_df))

    # Log per-metric coverage summary
    coverage = (
        df.groupby(["metric_type", "period_type"])
        .agg(count=("value", "size"),
             min_date=("period_end", "min"),
             max_date=("period_end", "max"))
        .reset_index()
    )
    for _, cov in coverage.iterrows():
        logger.info(
            "%s coverage: %s %s — %d periods (%s to %s)",
            ticker, cov["metric_type"], cov["period_type"],
            cov["count"], cov["min_date"], cov["max_date"],
        )

    # Flag expected metrics with no data
    all_expected = set(CONCEPT_MAP.values()) | set(RAW_CONCEPT_MAP.values())
    extracted_metrics = set(df["metric_type"].unique())
    missing = sorted(all_expected - extracted_metrics)
    if missing:
        logger.warning("%s: no data for metrics: %s", ticker, missing)

    count = write_financial_metrics(df, db_path=db_path)
    update_company_extraction(ticker, cik=company_cik, db_path=state_db_path)

    logger.info("Extracted %d rows for %s (after dedup)", count, ticker)
    return count


# ── Strategy 1 helpers ───────────────────────────────────────────────────────

def _extract_flow_s1(
    facts,
    concept_name: str,
    metric_type: str,
    ticker: str,
    cik: str | None,
    rows: list[dict],
    TTMCalculator,
) -> None:
    """Strategy 1 for flow metrics: use TTMCalculator.quarterize().

    Gives discrete Q1–Q4 (Q4 derived from FY − YTD_9M).
    Also extracts annual (FY) rows from time_series for annual comparisons.
    """
    # Get all facts for this concept
    concept_facts = facts.query().by_concept(concept_name).execute()
    if not concept_facts:
        logger.debug("S1 %s/%s: no facts from query().by_concept()", ticker, concept_name)
        return

    # Filter to the primary XBRL concept (avoid deferred revenue, etc.)
    # by_concept('revenue') may return multiple XBRL concepts — keep only
    # the ones that map to our target metric via RAW_CONCEPT_MAP.
    target_xbrl = {raw for raw, mt in RAW_CONCEPT_MAP.items() if mt == metric_type}
    found_xbrl_tags = {f.concept for f in concept_facts}
    filtered = [f for f in concept_facts if f.concept in target_xbrl]

    # If no match via RAW_CONCEPT_MAP, use all facts (the concept might use
    # a name not in our raw map — time_series resolved it for us).
    if not filtered:
        logger.debug(
            "S1 %s/%s: XBRL tags %s not in RAW_CONCEPT_MAP targets %s — using all",
            ticker, concept_name, sorted(found_xbrl_tags), sorted(target_xbrl),
        )
        filtered = concept_facts
    else:
        logger.debug(
            "S1 %s/%s: matched XBRL tags %s (%d facts)",
            ticker, concept_name,
            sorted(f.concept for f in filtered), len(filtered),
        )

    # Quarterly: use TTMCalculator to get discrete Q1–Q4
    try:
        calc = TTMCalculator(filtered)
        quarters = calc.quarterize()
    except Exception as e:
        logger.debug("quarterize failed for %s/%s: %s", ticker, concept_name, e)
        quarters = []

    for q in quarters:
        pe = q.period_end
        if pe is None or q.value is None:
            continue
        pe_date = _to_date(pe)
        if pe_date is None:
            continue
        fp = q.fiscal_period  # Q1, Q2, Q3, or Q4
        if fp not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        rows.append(_make_row(
            ticker, cik, metric_type, float(q.value), pe_date,
            "quarterly", "10-Q" if fp != "Q4" else "10-K",
        ))

    # Annual: extract FY rows from time_series
    try:
        ts = facts.time_series(concept_name)
        if ts is not None and len(ts) > 0 and "fiscal_period" in ts.columns:
            fy_data = _select_annual_flow_rows(ts)
            if not fy_data.empty:
                for _, row in fy_data.iterrows():
                    pe = row["period_end"]
                    val = row["numeric_value"]
                    if pd.isna(pe) or pd.isna(val):
                        continue
                    pe_date = _to_date(pe)
                    if pe_date is None:
                        continue
                    rows.append(_make_row(
                        ticker, cik, metric_type, float(val), pe_date,
                        "annual", "10-K",
                    ))
    except Exception as e:
        logger.debug("time_series FY failed for %s/%s: %s", ticker, concept_name, e)


def _extract_stock_s1(
    facts,
    concept_name: str,
    metric_type: str,
    ticker: str,
    cik: str | None,
    rows: list[dict],
) -> None:
    """Strategy 1 for stock (balance sheet) metrics: point-in-time snapshots.

    Uses time_series() and stores each quarter + annual as-is.
    """
    try:
        ts = facts.time_series(concept_name)
        if ts is None or len(ts) == 0:
            return
        if "fiscal_period" not in ts.columns:
            return
    except Exception:
        return

    for fiscal_period, period_type in [
        ("FY", "annual"),
        ("Q1", "quarterly"), ("Q2", "quarterly"), ("Q3", "quarterly"),
        ("Q4", "quarterly"),
    ]:
        period_data = ts[ts["fiscal_period"] == fiscal_period].copy()
        if period_data.empty:
            continue
        for pe_date, value in _iter_deduped_period_values(period_data):
            rows.append(_make_row(
                ticker, cik, metric_type, value, pe_date,
                period_type, "10-K" if period_type == "annual" else "10-Q",
            ))


def _extract_from_raw_df(
    raw_df: pd.DataFrame,
    ticker: str,
    cik: str | None,
    target_metrics: set[str],
    all_rows: list[dict],
) -> None:
    """Extract metrics from raw to_dataframe() output with duration filtering.

    For **flow metrics** (income statement / cash flow):
      - Keep only ~90-day (discrete quarter) and ~365-day (annual) rows.
      - When only YTD cumulative rows exist for Q2/Q3, derive discrete values:
          Q2 = YTD_6M − Q1,  Q3 = YTD_9M − YTD_6M,  Q4 = FY − YTD_9M
    For **stock metrics** (balance sheet):
      - Store per-quarter and annual as-is (point-in-time snapshots).

    Multiple raw XBRL concepts may map to the same metric_type.  The caller is
    responsible for dedup at the (metric_type, period_type, period_end) level.
    """
    if "concept" not in raw_df.columns:
        return

    has_period_start = "period_start" in raw_df.columns

    for raw_concept, metric_type in RAW_CONCEPT_MAP.items():
        if metric_type not in target_metrics:
            continue

        concept_df = raw_df[raw_df["concept"] == raw_concept].copy()
        if concept_df.empty:
            continue

        logger.debug(
            "S2 %s: tag %s → %s — %d raw rows",
            ticker, raw_concept, metric_type, len(concept_df),
        )

        # Filter for appropriate unit
        # edgartools may report units as "USD/shares" or "USD per share"
        # depending on the XBRL taxonomy version.
        if "unit" in concept_df.columns:
            if metric_type in ("eps_diluted", "eps_basic"):
                concept_df = concept_df[
                    concept_df["unit"].str.lower().str.contains("usd")
                    & concept_df["unit"].str.lower().str.contains("share")
                ]
            elif metric_type == "common_shares_outstanding":
                concept_df = concept_df[
                    concept_df["unit"].str.lower().str.contains("share")
                ]
            else:
                concept_df = concept_df[concept_df["unit"] == "USD"]

        if concept_df.empty:
            logger.debug(
                "S2 %s: tag %s → %s — no rows after unit filter",
                ticker, raw_concept, metric_type,
            )
            continue

        if "fiscal_period" not in concept_df.columns:
            continue

        is_flow = metric_type in FLOW_METRICS

        if is_flow and has_period_start:
            _extract_flow_from_raw(concept_df, ticker, cik, metric_type, all_rows)
        elif is_flow:
            # No period_start → fall back to fiscal_period labels only.
            # This may store YTD values for Q2/Q3 which is suboptimal,
            # but better than dropping data entirely.
            _extract_by_fiscal_period(concept_df, ticker, cik, metric_type, all_rows)
        else:
            # Stock metrics: store per-quarter and annual as-is
            _extract_by_fiscal_period(
                concept_df, ticker, cik, metric_type, all_rows,
                include_q4=True,
            )


def _extract_canonical_long_term_debt_from_raw(
    raw_df: pd.DataFrame | None,
    ticker: str,
    cik: str | None,
) -> pd.DataFrame:
    """Build canonical long-term debt rows from raw SEC concepts.

    Canonical ``long_term_debt`` is the noncurrent portion only.
    Prefer ``LongTermDebtNoncurrent`` when present. When only a broader total
    long-term-debt concept plus a current portion is available, derive the
    noncurrent value as ``total - current``.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()
    if "concept" not in raw_df.columns or "fiscal_period" not in raw_df.columns:
        return pd.DataFrame()

    debt_df = raw_df[
        raw_df["concept"].isin(
            _LONG_TERM_DEBT_TOTAL_CONCEPTS
            | _LONG_TERM_DEBT_NONCURRENT_CONCEPTS
            | _LONG_TERM_DEBT_CURRENT_CONCEPTS
        )
    ].copy()
    if debt_df.empty:
        return pd.DataFrame()

    if "unit" in debt_df.columns:
        debt_df = debt_df[debt_df["unit"] == "USD"]
    if debt_df.empty:
        return pd.DataFrame()

    def _build_value_map(df_part: pd.DataFrame, concepts: frozenset[str]) -> dict[date, float]:
        subset = df_part[df_part["concept"].isin(concepts)]
        if subset.empty:
            return {}
        result: dict[date, float] = {}
        for pe_date, value in _iter_deduped_period_values(subset):
            result[pe_date] = value
        return result

    rows: list[dict] = []
    for fiscal_period, period_type in [
        ("FY", "annual"),
        ("Q1", "quarterly"),
        ("Q2", "quarterly"),
        ("Q3", "quarterly"),
        ("Q4", "quarterly"),
    ]:
        period_df = debt_df[debt_df["fiscal_period"] == fiscal_period]
        if period_df.empty:
            continue

        noncurrent_by_period = _build_value_map(period_df, _LONG_TERM_DEBT_NONCURRENT_CONCEPTS)
        total_by_period = _build_value_map(period_df, _LONG_TERM_DEBT_TOTAL_CONCEPTS)
        current_by_period = _build_value_map(period_df, _LONG_TERM_DEBT_CURRENT_CONCEPTS)

        for period_end in sorted(
            set(noncurrent_by_period) | set(total_by_period) | set(current_by_period)
        ):
            value = noncurrent_by_period.get(period_end)
            if value is None:
                total_value = total_by_period.get(period_end)
                current_value = current_by_period.get(period_end)
                if (
                    total_value is not None
                    and current_value is not None
                    and total_value >= current_value
                ):
                    value = total_value - current_value
                else:
                    value = total_value
            if value is None:
                continue

            rows.append(
                _make_row(
                    ticker,
                    cik,
                    "long_term_debt",
                    value,
                    period_end,
                    period_type,
                    "10-K" if period_type == "annual" else "10-Q",
                )
            )

    return pd.DataFrame(rows)


def _extract_flow_from_raw(
    concept_df: pd.DataFrame,
    ticker: str,
    cik: str | None,
    metric_type: str,
    all_rows: list[dict],
) -> None:
    """Extract discrete-quarter + annual rows for a flow metric using duration.

    Uses period_start/period_end to classify each row, then derives Q4 and
    any missing Q2/Q3 from YTD cumulative values.
    """
    # Classify each row by duration bucket
    concept_df = concept_df.copy()
    concept_df["_duration"] = _vectorized_duration_bucket(
        concept_df["period_start"], concept_df["period_end"],
    )

    bucket_counts = concept_df["_duration"].value_counts().to_dict()
    unclassified = concept_df["_duration"].isna().sum()
    logger.debug(
        "S2 %s/%s: duration buckets: %s (unclassified: %d)",
        ticker, metric_type, bucket_counts, unclassified,
    )

    # Annual (FY) rows. Some filers expose rolling 12-month values on Q1/Q2/Q3
    # contexts, so require a true FY label in addition to annual duration.
    fy_df = _select_annual_flow_rows(concept_df)
    if not fy_df.empty:
        _emit_rows(fy_df, ticker, cik, metric_type, "annual", "FY", all_rows)

    # Discrete quarter rows (~90 days)
    q_df = concept_df[concept_df["_duration"] == "quarter"]
    emitted_keys: set[tuple[str, date]] = set()  # (quarter_label, period_end)

    if not q_df.empty:
        # Emit the discrete quarter rows directly
        for fiscal_period in ("Q1", "Q2", "Q3", "Q4"):
            fp_df = q_df[q_df["fiscal_period"] == fiscal_period]
            if not fp_df.empty:
                for pe_date, value in _iter_deduped_period_values(fp_df):
                    emitted_keys.add((fiscal_period, pe_date))
                    all_rows.append(_make_row(
                        ticker, cik, metric_type, value, pe_date,
                        "quarterly", "10-Q" if fiscal_period != "Q4" else "10-K",
                    ))

    # ── Derive missing quarters from YTD cumulative ──────────────────────
    # Group YTD and annual by fiscal_year for subtraction
    ytd_6m = concept_df[concept_df["_duration"] == "ytd_6m"]
    ytd_9m = concept_df[concept_df["_duration"] == "ytd_9m"]

    # Build lookup: fiscal_year → {bucket: (value, period_end)}
    # For each fiscal year, collect the available data points.
    year_data: dict[int, dict[str, tuple[float, date]]] = {}

    for df_part, bucket in [
        (q_df[q_df["fiscal_period"] == "Q1"], "q1"),
        (ytd_6m, "ytd_6m"),
        (ytd_9m, "ytd_9m"),
        (fy_df, "annual"),
    ]:
        if df_part.empty:
            continue
        for fy in df_part["fiscal_year"].dropna().unique():
            fy_int = int(fy)
            subset = df_part[df_part["fiscal_year"] == fy]
            deduped = _dedup_period_end(subset)
            if deduped.empty:
                continue
            best = deduped.sort_values("period_end").iloc[-1]
            pe_date = _to_date(best["period_end"])
            val = best["numeric_value"]
            if pe_date is None or pd.isna(val):
                continue
            year_data.setdefault(fy_int, {})[bucket] = (float(val), pe_date)

    derived_quarters: list[str] = []

    for fy, data in year_data.items():
        # Q2 = YTD_6M - Q1
        if "ytd_6m" in data and "q1" in data:
            q2_val = data["ytd_6m"][0] - data["q1"][0]
            q2_pe = data["ytd_6m"][1]
            if ("Q2", q2_pe) not in emitted_keys:
                derived_quarters.append(f"Q2-FY{fy}")
                all_rows.append(_make_row(
                    ticker, cik, metric_type, q2_val, q2_pe, "quarterly", "10-Q",
                ))
                emitted_keys.add(("Q2", q2_pe))

        # Q3 = YTD_9M - YTD_6M
        if "ytd_9m" in data and "ytd_6m" in data:
            q3_val = data["ytd_9m"][0] - data["ytd_6m"][0]
            q3_pe = data["ytd_9m"][1]
            if ("Q3", q3_pe) not in emitted_keys:
                derived_quarters.append(f"Q3-FY{fy}")
                all_rows.append(_make_row(
                    ticker, cik, metric_type, q3_val, q3_pe, "quarterly", "10-Q",
                ))
                emitted_keys.add(("Q3", q3_pe))

        # Q4 = FY - YTD_9M
        if "annual" in data and "ytd_9m" in data:
            q4_val = data["annual"][0] - data["ytd_9m"][0]
            q4_pe = data["annual"][1]  # same period_end as FY
            if ("Q4", q4_pe) not in emitted_keys:
                derived_quarters.append(f"Q4-FY{fy}")
                all_rows.append(_make_row(
                    ticker, cik, metric_type, q4_val, q4_pe, "quarterly", "10-K",
                ))
                emitted_keys.add(("Q4", q4_pe))

    if derived_quarters:
        logger.debug(
            "S2 %s/%s: derived quarters from YTD: %s",
            ticker, metric_type, derived_quarters,
        )


def _extract_by_fiscal_period(
    concept_df: pd.DataFrame,
    ticker: str,
    cik: str | None,
    metric_type: str,
    all_rows: list[dict],
    include_q4: bool = False,
) -> None:
    """Simple extraction by fiscal_period label (no duration filtering).

    Used for stock metrics (balance sheet) and as fallback when period_start
    is not available.
    """
    quarters = [("FY", "annual"), ("Q1", "quarterly"), ("Q2", "quarterly"), ("Q3", "quarterly")]
    if include_q4:
        quarters.append(("Q4", "quarterly"))

    for fiscal_period, period_type in quarters:
        period_data = concept_df[concept_df["fiscal_period"] == fiscal_period]
        if period_data.empty:
            continue
        for pe_date, value in _iter_deduped_period_values(period_data):
            all_rows.append(_make_row(
                ticker, cik, metric_type, value, pe_date,
                period_type, "10-K" if period_type == "annual" else "10-Q",
            ))


def _emit_rows(
    df_part: pd.DataFrame,
    ticker: str,
    cik: str | None,
    metric_type: str,
    period_type: str,
    fiscal_period: str,
    all_rows: list[dict],
) -> None:
    """Emit deduplicated rows for a single fiscal_period slice."""
    for pe_date, value in _iter_deduped_period_values(df_part):
        all_rows.append(_make_row(
            ticker, cik, metric_type, value, pe_date,
            period_type, "10-K" if period_type == "annual" else "10-Q",
        ))


def get_all_tickers() -> pd.DataFrame:
    """Get all SEC-filing company tickers from edgartools reference data.

    Returns:
        DataFrame with columns: cik, ticker, exchange, company
    """
    from edgar.reference.tickers import get_company_tickers

    return get_company_tickers()


def extract_all_companies(
    db_path: str | None = None,
    state_db_path: str | None = None,
    limit: int | None = None,
) -> tuple[int, int]:
    """Extract financial facts for all SEC companies.

    Args:
        db_path: Override DuckDB path.
        state_db_path: Override state DB path.
        limit: Max companies to process (None for all).

    Returns:
        Tuple of (companies_processed, total_rows_written).
    """
    tickers_df = get_all_tickers()
    total_tickers = len(tickers_df)

    if limit:
        tickers_df = tickers_df.head(limit)

    logger.info(
        "Starting slow-path extraction for %d/%d companies",
        len(tickers_df),
        total_tickers,
    )

    companies_processed = 0
    total_rows = 0

    for idx, row in enumerate(tickers_df.itertuples()):
        ticker = row.ticker
        cik = str(row.cik)

        try:
            count = extract_company_facts(
                ticker=ticker,
                cik=cik,
                db_path=db_path,
                state_db_path=state_db_path,
            )
            if count > 0:
                companies_processed += 1
                total_rows += count
        except Exception as e:
            logger.warning("Failed to extract %s: %s", ticker, e)
            continue

        if (idx + 1) % 100 == 0:
            logger.info(
                "Progress: %d/%d companies, %d extracted, %d total rows",
                idx + 1,
                len(tickers_df),
                companies_processed,
                total_rows,
            )

    logger.info(
        "Slow-path extraction complete: %d companies, %d total rows",
        companies_processed,
        total_rows,
    )
    return companies_processed, total_rows


def rerun_slow_path_for_companies(
    tickers: list[str],
    db_path: str | None = None,
    state_db_path: str | None = None,
) -> list[dict[str, int | str]]:
    """Delete then re-extract slow-path data for the requested tickers.

    This intentionally does not use upsert semantics for the selected companies.
    Existing `financial_metrics` rows and company extraction state are deleted
    first, then the slow-path extractor is re-run for each ticker.
    """
    from investment_researcher.ingestion.edgar.storage import configure_edgar

    normalized = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not normalized:
        return []

    configure_edgar()

    results: list[dict[str, int | str]] = []
    for ticker in normalized:
        deleted_rows = delete_company_financial_metrics(ticker, db_path=db_path)
        deleted_state_rows = delete_company_extraction_state(ticker, db_path=state_db_path)
        written_rows = extract_company_facts(
            ticker,
            db_path=db_path,
            state_db_path=state_db_path,
        )
        results.append(
            {
                "ticker": ticker,
                "deleted_rows": deleted_rows,
                "deleted_state_rows": deleted_state_rows,
                "written_rows": written_rows,
            }
        )

    return results
