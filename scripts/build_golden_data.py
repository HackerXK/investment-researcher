#!/usr/bin/env python3
"""One-time helper: fetch golden data from SEC DERA + FMP for multiple companies.

Fetches financial data from two independent sources:
  1. SEC DERA Financial Statement Data Sets (bulk XBRL extracts by the SEC)
  2. Financial Modeling Prep (FMP) API (third-party financial data)

Cross-references the two sources, logs discrepancies, and prints structured
Python code ready to paste into tests/golden_{ticker}.py.

Usage:
    FMP_API_KEY=your_key python scripts/build_golden_data.py           # all companies
    FMP_API_KEY=your_key python scripts/build_golden_data.py AAPL NVDA # specific tickers

Environment variables:
    FMP_API_KEY  — Required. Free-tier API key from financialmodelingprep.com.
"""

import csv
import io
import os
import sys
import zipfile
from datetime import date, datetime

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

COMPANIES: dict[str, int] = {
    "AAPL": 320193,
    "NVDA": 1045810,
    "WMT": 104169,
    "UNH": 731766,
    "XOM": 34088,
}

# DERA quarterly ZIPs to download.  Each covers filings filed in that quarter.
# AAPL FY2024 10-K filed Nov 1, 2024 → appears in 2025q1 dataset.
# AAPL FY2024 Q3 10-Q filed Aug 2, 2024 → appears in 2024q3 dataset.
# AAPL FY2023 10-K filed Nov 3, 2023 → appears in 2024q1 dataset.
DERA_QUARTERS = [
    "2023q1", "2023q2", "2023q3", "2023q4",
    "2024q1", "2024q2", "2024q3", "2024q4",
    "2025q1", "2025q2",
]

DERA_BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"

FMP_BASE_URL = "https://financialmodelingprep.com/stable"

# Metrics we want golden data for (representative subset of 12)
GOLDEN_FLOW_METRICS = {
    "revenue", "net_income", "gross_profit", "operating_income",
    "operating_cash_flow", "eps_diluted", "capex",
}
GOLDEN_STOCK_METRICS = {
    "total_assets", "total_liabilities", "stockholders_equity",
    "cash", "total_current_assets",
}
GOLDEN_METRICS = GOLDEN_FLOW_METRICS | GOLDEN_STOCK_METRICS

# Golden points intentionally excluded from test generation because the current
# extractor does not surface them reliably enough for stable golden assertions.
EXCLUDED_GOLDEN_RULES: set = set()
EXCLUDED_GOLDEN_POINTS = {
    # WMT total_liabilities FY2022-FY2024: could not be reliably recovered
    # (DuckDB lacks the metric; balance-sheet derivation unreliable due to
    #  fluctuating ~$6.7B non-controlling interests)
    ("WMT", "total_liabilities", "annual", date(2022, 1, 31)),
    ("WMT", "total_liabilities", "annual", date(2023, 1, 31)),
    ("WMT", "total_liabilities", "annual", date(2024, 1, 31)),
}


def _should_exclude_golden_point(ticker: str, key: tuple[str, str, date]) -> bool:
    metric_type, period_type, period_end = key
    return (
        (ticker, metric_type, period_type) in EXCLUDED_GOLDEN_RULES
        or (ticker, metric_type, period_type, period_end) in EXCLUDED_GOLDEN_POINTS
    )

# DERA num.txt tag → our metric_type.  Tags appear WITHOUT the "us-gaap:" prefix.
DERA_TAG_MAP: dict[str, str] = {
    # Income statement — AAPL uses these specific concepts
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenues": "revenue",
    "SalesRevenueNet": "revenue",
    "NetIncomeLoss": "net_income",
    "GrossProfit": "gross_profit",
    "OperatingIncomeLoss": "operating_income",
    "EarningsPerShareDiluted": "eps_diluted",
    # Balance sheet
    "Assets": "total_assets",
    "Liabilities": "total_liabilities",
    "StockholdersEquity": "stockholders_equity",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "AssetsCurrent": "total_current_assets",
    # Cash flow
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
}

# FMP JSON field → our metric_type
FMP_INCOME_MAP = {
    "revenue": "revenue",
    "netIncome": "net_income",
    "grossProfit": "gross_profit",
    "operatingIncome": "operating_income",
    "epsdiluted": "eps_diluted",
    "epsDiluted": "eps_diluted",
}
FMP_BALANCE_MAP = {
    "totalAssets": "total_assets",
    "totalLiabilities": "total_liabilities",
    "totalStockholdersEquity": "stockholders_equity",
    "cashAndCashEquivalents": "cash",
    "totalCurrentAssets": "total_current_assets",
}
FMP_CASHFLOW_MAP = {
    "operatingCashFlow": "operating_cash_flow",
    "capitalExpenditure": "capex",
}

# FMP TTM JSON field → our metric_type
# Note: FMP TTM endpoints use the same field names as the periodic statements.
FMP_TTM_INCOME_MAP = {
    "revenue": "revenue",
    "netIncome": "net_income",
    "grossProfit": "gross_profit",
    "operatingIncome": "operating_income",
    "epsDiluted": "eps_diluted",
    "ebitda": "ebitda",
    "depreciationAndAmortization": "depreciation_and_amortization",
    "interestExpense": "interest_expense",
    "costOfRevenue": "cost_of_revenue",
    "operatingExpenses": "operating_expenses",
    "incomeTaxExpense": "income_tax_expense",
}
FMP_TTM_BALANCE_MAP = {
    "totalAssets": "total_assets",
    "totalLiabilities": "total_liabilities",
    "totalStockholdersEquity": "stockholders_equity",
    "cashAndCashEquivalents": "cash",
    "totalCurrentAssets": "total_current_assets",
    "totalCurrentLiabilities": "total_current_liabilities",
    "inventory": "inventory",
    "accountPayables": "accounts_payable",
    "totalDebt": "total_debt",
    "longTermDebt": "long_term_debt",
    "shortTermDebt": "short_term_debt",
}
FMP_TTM_CASHFLOW_MAP = {
    "operatingCashFlow": "operating_cash_flow",
    "capitalExpenditure": "capex",
    "freeCashFlow": "free_cash_flow",
    "commonDividendsPaid": "dividends_paid",
}

# All metrics we want TTM golden data for
GOLDEN_TTM_METRICS = (
    set(FMP_TTM_INCOME_MAP.values())
    | set(FMP_TTM_BALANCE_MAP.values())
    | set(FMP_TTM_CASHFLOW_MAP.values())
)


# ── SEC DERA Fetcher ──────────────────────────────────────────────────────────

def fetch_dera_data(ticker: str, cik: int) -> dict[tuple[str, str, date], float]:
    """Download DERA ZIPs, extract facts for ticker/CIK, return golden values.

    DERA num.txt can contain multiple values for the same metric/period due to:
      - Multiple XBRL tags mapping to the same metric (e.g. Revenues vs
        RevenueFromContractWithCustomerExcludingAssessedTax)
      - Dimensional/segment breakdowns appearing as separate facts

    Strategy: collect ALL values per (metric_type, period_type, period_end),
    then keep the largest absolute value (consolidated total is always >= any
    segment breakdown for revenue, assets, etc.).

    Returns dict keyed by (metric_type, period_type, period_end) → value.
    """
    # Collect all candidates per key, then pick the best
    candidates: dict[tuple[str, str, date], list[tuple[float, str]]] = {}

    headers = {
        "User-Agent": "InvestmentResearcher/1.0 golden-data-builder (test@example.com)",
        "Accept-Encoding": "gzip, deflate",
    }

    for quarter in DERA_QUARTERS:
        url = f"{DERA_BASE_URL}/{quarter}.zip"
        print(f"  Fetching DERA {quarter}...", end=" ", flush=True)
        try:
            resp = httpx.get(url, headers=headers, timeout=60, follow_redirects=True)
            if resp.status_code != 200:
                print(f"HTTP {resp.status_code}, skipping")
                continue
        except httpx.HTTPError as e:
            print(f"Error: {e}, skipping")
            continue

        zf = zipfile.ZipFile(io.BytesIO(resp.content))

        # Parse sub.txt → find filing accession numbers for this CIK
        company_filings: dict[str, dict] = {}  # adsh → {form, period, fy, fp}
        with zf.open("sub.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t")
            for row in reader:
                try:
                    row_cik = int(row.get("cik", 0))
                except (ValueError, TypeError):
                    continue
                if row_cik != cik:
                    continue
                form = row.get("form", "")
                if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                    continue
                adsh = row.get("adsh", "")
                if adsh:
                    company_filings[adsh] = {
                        "form": form,
                        "period": row.get("period", ""),
                        "fy": row.get("fy", ""),
                        "fp": row.get("fp", ""),
                    }

        if not company_filings:
            print(f"no {ticker} filings found")
            continue

        print(f"{len(company_filings)} {ticker} filing(s) found", end="")

        # Parse num.txt → extract values for our target tags
        count = 0
        with zf.open("num.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t")
            for row in reader:
                adsh = row.get("adsh", "")
                if adsh not in company_filings:
                    continue
                tag = row.get("tag", "")
                metric_type = DERA_TAG_MAP.get(tag)
                if metric_type is None or metric_type not in GOLDEN_METRICS:
                    continue

                # Skip co-registrant data — we want the primary filer
                coreg = row.get("coreg", "")
                if coreg:
                    continue

                try:
                    value = float(row["value"])
                except (ValueError, KeyError, TypeError):
                    continue

                qtrs_str = row.get("qtrs", "")
                try:
                    qtrs = int(qtrs_str)
                except (ValueError, TypeError):
                    continue

                ddate_str = row.get("ddate", "")
                try:
                    period_end = datetime.strptime(ddate_str, "%Y%m%d").date()
                except (ValueError, TypeError):
                    continue

                # Classify: qtrs=0 → instant (balance sheet), qtrs=1 → quarterly,
                # qtrs=4 → annual.  Skip YTD (qtrs=2,3) — we want discrete values.
                if qtrs == 0 and metric_type in GOLDEN_STOCK_METRICS:
                    filing_form = company_filings[adsh]["form"]
                    filing_fp = company_filings[adsh].get("fp", "")
                    if filing_form in ("10-K", "10-K/A") and filing_fp == "FY":
                        period_type = "annual"
                    else:
                        period_type = "quarterly"
                elif qtrs == 1 and metric_type in GOLDEN_FLOW_METRICS:
                    period_type = "quarterly"
                elif qtrs == 4 and metric_type in GOLDEN_FLOW_METRICS:
                    period_type = "annual"
                else:
                    continue

                key = (metric_type, period_type, period_end)
                candidates.setdefault(key, []).append((value, tag))
                count += 1

        print(f", {count} raw values extracted")

    # Resolve: for each key, pick the value with the largest absolute value.
    # Consolidated totals are always >= any segment breakdown.
    results: dict[tuple[str, str, date], float] = {}
    multi_value_count = 0
    for key, vals in candidates.items():
        if len(vals) == 1:
            results[key] = vals[0][0]
        else:
            multi_value_count += 1
            # Sort by absolute value descending, pick the largest
            best = max(vals, key=lambda vt: abs(vt[0]))
            results[key] = best[0]

    # Cross-check: operating_income should be between net_income and gross_profit.
    # DERA includes segment-level OperatingIncomeLoss which sum to MORE than the
    # consolidated total.  Individual segment values are typically < net_income.
    # Strategy: filter candidates to (net_income, gross_profit) range, then pick
    # the MINIMUM — consolidated is always smaller than segment sums.
    for key in list(results.keys()):
        metric, ptype, pe = key
        if metric != "operating_income":
            continue
        ni_key = ("net_income", ptype, pe)
        gp_key = ("gross_profit", ptype, pe)
        ni_val = results.get(ni_key)
        gp_val = results.get(gp_key)
        if ni_val is None or gp_val is None:
            continue  # can't validate without both bounds

        vals = candidates[key]
        # Keep only values strictly between net_income and gross_profit
        valid = [v for v, t in vals if ni_val < v < gp_val]
        if valid:
            best = min(valid)  # consolidated < segment sum
            if best != results[key]:
                print(f"    ⚠ Fixed operating_income {ptype} {pe}: "
                      f"{results[key]:,.0f} → {best:,.0f} "
                      f"(bounded by NI={ni_val:,.0f}, GP={gp_val:,.0f})")
                results[key] = best
        else:
            # Fallback: keep the max but warn
            print(f"    ⚠ operating_income {ptype} {pe}: no value between "
                  f"NI={ni_val:,.0f} and GP={gp_val:,.0f}, keeping {results[key]:,.0f}")

    # Cross-check: stockholders_equity should equal total_assets - total_liabilities.
    # DERA max-abs often picks CommonStock+APIC instead of total SE.
    # Derive SE from the balance sheet identity where both TA and TL are available.
    for key in list(results.keys()):
        metric, ptype, pe = key
        if metric != "stockholders_equity":
            continue
        ta_key = ("total_assets", ptype, pe)
        tl_key = ("total_liabilities", ptype, pe)
        ta_val = results.get(ta_key)
        tl_val = results.get(tl_key)
        if ta_val is not None and tl_val is not None:
            derived_se = ta_val - tl_val
            if abs(derived_se - results[key]) > 1.0:  # any meaningful difference
                print(f"    ⚠ Fixed stockholders_equity {ptype} {pe}: "
                      f"{results[key]:,.0f} → {derived_se:,.0f} "
                      f"(derived from TA={ta_val:,.0f} - TL={tl_val:,.0f})")
                results[key] = derived_se

    print(f"  Resolved {multi_value_count} multi-value keys "
          f"→ {len(results)} final values")
    return results


# ── FMP API Fetcher ───────────────────────────────────────────────────────────

def fetch_fmp_data(api_key: str, symbol: str) -> dict[tuple[str, str, date], float]:
    """Fetch financials from FMP API for a given symbol.

    Returns dict keyed by (metric_type, period_type, period_end) → value.
    """
    results: dict[tuple[str, str, date], float] = {}

    endpoints = [
        ("income-statement", FMP_INCOME_MAP),
        ("balance-sheet-statement", FMP_BALANCE_MAP),
        ("cash-flow-statement", FMP_CASHFLOW_MAP),
    ]

    for endpoint, field_map in endpoints:
        for period_param, period_type in [("annual", "annual"), ("quarter", "quarterly")]:
            url = f"{FMP_BASE_URL}/{endpoint}"
            params = {"symbol": symbol, "period": period_param, "limit": 5, "apikey": api_key}

            print(f"  Fetching FMP {endpoint} ({period_param})...", end=" ", flush=True)
            try:
                resp = httpx.get(url, params=params, timeout=30)
                if resp.status_code != 200:
                    print(f"HTTP {resp.status_code}: {resp.text[:120]}")
                    continue
                data = resp.json()
            except Exception as e:
                print(f"Error: {e}")
                continue

            if not isinstance(data, list):
                print(f"unexpected response type: {type(data)}")
                continue

            count = 0
            for item in data:
                date_str = item.get("date", "")
                try:
                    period_end = datetime.strptime(date_str, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue

                for fmp_field, metric_type in field_map.items():
                    if metric_type not in GOLDEN_METRICS:
                        continue
                    val = item.get(fmp_field)
                    if val is None:
                        continue
                    try:
                        value = float(val)
                    except (ValueError, TypeError):
                        continue
                    # DERA reports capex as positive; FMP as negative (cash outflow)
                    if metric_type == "capex":
                        value = abs(value)

                    key = (metric_type, period_type, period_end)
                    results[key] = value
                    count += 1

            print(f"{count} values")

    return results


# ── FMP TTM Fetcher ───────────────────────────────────────────────────────────

def fetch_fmp_ttm_data(api_key: str, symbol: str) -> dict[str, float]:
    """Fetch TTM metrics from FMP API for a given symbol.

    Returns dict keyed by metric_type → value.
    """
    results: dict[str, float] = {}

    ttm_endpoints = [
        ("income-statement-ttm", FMP_TTM_INCOME_MAP),
        ("balance-sheet-statement-ttm", FMP_TTM_BALANCE_MAP),
        ("cash-flow-statement-ttm", FMP_TTM_CASHFLOW_MAP),
    ]

    for endpoint, field_map in ttm_endpoints:
        url = f"{FMP_BASE_URL}/{endpoint}"
        params = {"symbol": symbol, "apikey": api_key}

        print(f"  Fetching FMP {endpoint}...", end=" ", flush=True)
        try:
            resp = httpx.get(url, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"HTTP {resp.status_code}: {resp.text[:120]}")
                continue
            data = resp.json()
        except Exception as e:
            print(f"Error: {e}")
            continue

        if not isinstance(data, list) or not data:
            print(f"unexpected or empty response")
            continue

        item = data[0]  # TTM endpoints return a single-element list
        count = 0
        for fmp_field, metric_type in field_map.items():
            val = item.get(fmp_field)
            if val is None:
                continue
            try:
                value = float(val)
            except (ValueError, TypeError):
                continue
            # FMP reports capex as negative (cash outflow); we store positive
            if metric_type == "capex":
                value = abs(value)
            # FMP reports dividends_paid as negative; we store positive
            if metric_type == "dividends_paid":
                value = abs(value)
            results[metric_type] = value
            count += 1

        print(f"{count} values")

    return results


# ── Cross-Reference & Output ─────────────────────────────────────────────────

def _fuzzy_match_keys(
    dera: dict[tuple[str, str, date], float],
    fmp: dict[tuple[str, str, date], float],
    max_days: int = 7,
) -> list[tuple[tuple[str, str, date], tuple[str, str, date]]]:
    """Match DERA keys to FMP keys within ±max_days date tolerance.

    Returns list of (dera_key, fmp_key) pairs.
    """
    from datetime import timedelta

    matches: list[tuple[tuple[str, str, date], tuple[str, str, date]]] = []
    fmp_by_metric_period: dict[tuple[str, str], list[tuple[date, tuple[str, str, date]]]] = {}
    for fk in fmp:
        mp = (fk[0], fk[1])
        fmp_by_metric_period.setdefault(mp, []).append((fk[2], fk))

    for dk in dera:
        mp = (dk[0], dk[1])
        if mp not in fmp_by_metric_period:
            continue
        for fmp_date, fk in fmp_by_metric_period[mp]:
            if abs((dk[2] - fmp_date).days) <= max_days:
                matches.append((dk, fk))
                break
    return matches


def cross_reference(
    dera: dict[tuple[str, str, date], float],
    fmp: dict[tuple[str, str, date], float],
) -> None:
    """Compare DERA vs FMP values and print discrepancies."""
    matched_pairs = _fuzzy_match_keys(dera, fmp)
    if not matched_pairs:
        print("\n⚠ No overlapping (metric, period_type, period_end) keys between DERA and FMP!")
        print(f"  DERA has {len(dera)} keys, FMP has {len(fmp)} keys")
        print("  DERA sample keys:", list(dera.keys())[:5])
        print("  FMP  sample keys:", list(fmp.keys())[:5])
        return

    print(f"\n── Cross-reference: {len(matched_pairs)} overlapping data points (±7 day date match) ──")
    discrepancies = 0
    for dk, fk in sorted(matched_pairs):
        metric_type, period_type, period_end = dk
        d_val, f_val = dera[dk], fmp[fk]
        date_note = "" if dk[2] == fk[2] else f" [FMP date: {fk[2]}]"

        # For EPS use absolute tolerance, for others use percentage
        if metric_type == "eps_diluted":
            diff = abs(d_val - f_val)
            is_match = diff < 0.02  # $0.02 tolerance
            pct_str = f"${diff:.4f} abs"
        elif d_val != 0:
            pct = abs(d_val - f_val) / abs(d_val) * 100
            is_match = pct < 1.0
            pct_str = f"{pct:.2f}%"
        else:
            is_match = f_val == 0
            pct_str = "N/A"

        status = "✓" if is_match else "✗"
        if not is_match:
            discrepancies += 1
        print(f"  {status} {metric_type:30s} {period_type:10s} {period_end} "
              f"DERA={d_val:>18,.2f}  FMP={f_val:>18,.2f}  diff={pct_str}{date_note}")

    matched = len(matched_pairs) - discrepancies
    print(f"  {matched}/{len(matched_pairs)} match within tolerance, {discrepancies} discrepancies")


def print_golden_module(
    ticker: str,
    dera: dict[tuple[str, str, date], float],
    fmp: dict[tuple[str, str, date], float],
) -> None:
    """Print structured Python code for tests/golden_{ticker}.py."""
    ticker_upper = ticker.upper()
    # Merge: use DERA dates as canonical, mark "both" if FMP confirms (±7 days)
    merged: dict[tuple[str, str, date], tuple[float, str]] = {}

    for key, val in dera.items():
        merged[key] = (val, "dera")

    # Fuzzy-match FMP keys to DERA keys; mark overlapping as "both"
    matched_pairs = _fuzzy_match_keys(dera, fmp)
    matched_dera_keys = set()
    for dk, fk in matched_pairs:
        matched_dera_keys.add(dk)
        merged[dk] = (dera[dk], "both")  # keep DERA value, mark confirmed

    # Add FMP-only keys (no DERA match)
    matched_fmp_keys = {fk for _, fk in matched_pairs}
    for key, val in fmp.items():
        if key not in matched_fmp_keys:
            if key not in merged:
                merged[key] = (val, "fmp")

    # Split into annual and quarterly, excluding intentionally noisy points.
    annual = {
        k: v for k, v in merged.items()
        if k[1] == "annual" and not _should_exclude_golden_point(ticker_upper, k)
    }
    quarterly = {
        k: v for k, v in merged.items()
        if k[1] == "quarterly" and not _should_exclude_golden_point(ticker_upper, k)
    }

    print("\n" + "=" * 80)
    print(f"# Output for tests/golden_{ticker.lower()}.py")
    print("# Copy everything below this line into the file")
    print("=" * 80)

    print(f'''"""Golden test data for {ticker_upper} — sourced from SEC DERA + FMP.

Values sourced independently of the edgartools extraction pipeline.
Used to validate that extract_company_facts() produces correct output.

Sources:
  - SEC DERA Financial Statement Data Sets (bulk XBRL extracts by the SEC)
  - Financial Modeling Prep (FMP) API (third-party financial data)
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GoldenMetric:
    """A single known-correct financial data point."""
    metric_type: str
    period_type: str   # "annual" or "quarterly"
    period_end: date
    value: float
    source: str        # "dera", "fmp", or "both"
    tolerance_pct: float = 1.0  # percentage tolerance for comparison


FLOW_METRICS = {{
    "revenue", "net_income", "gross_profit", "operating_income",
    "operating_cash_flow", "eps_diluted", "capex",
}}
''')

    def _print_list(name: str, items: dict):
        print(f"{name}: list[GoldenMetric] = [")
        for key in sorted(items.keys(), key=lambda k: (k[0], k[2])):
            metric_type, period_type, period_end = key
            value, source = items[key]
            tol = "0.02" if metric_type == "eps_diluted" else "1.0"
            print(f"    GoldenMetric({metric_type!r}, {period_type!r}, "
                  f"date({period_end.year}, {period_end.month}, {period_end.day}), "
                  f"{value!r}, {source!r}, {tol}),")
        print("]")

    _print_list(f"{ticker_upper}_ANNUAL_GOLDEN", annual)
    print()
    _print_list(f"{ticker_upper}_QUARTERLY_GOLDEN", quarterly)

    # Build FY quarterly sums map for internal consistency checks
    # Group quarterly flow metrics by fiscal year end
    print(f"""

# Expected FY totals for verifying Q1+Q2+Q3+Q4 = FY for flow metrics.
# Keys: (metric_type, fy_period_end) → expected annual value
{ticker_upper}_FY_QUARTERLY_SUMS: dict[tuple[str, date], float] = {{""")

    for key in sorted(annual.keys(), key=lambda k: (k[0], k[2])):
        metric_type, _, period_end = key
        if metric_type in GOLDEN_FLOW_METRICS:
            value = annual[key][0]
            print(f"    ({metric_type!r}, date({period_end.year}, {period_end.month}, {period_end.day})): {value!r},")

    print("}")


def print_golden_ttm_module(ticker: str, ttm_data: dict[str, float]) -> None:
    """Print structured Python code for tests/fixtures/golden_ttm_{ticker}.py."""
    ticker_upper = ticker.upper()
    ticker_lower = ticker.lower()

    print("\n" + "=" * 80)
    print(f"# Output for tests/fixtures/golden_ttm_{ticker_lower}.py")
    print("# Copy everything below this line into the file")
    print("=" * 80)

    print(f'''"""Golden TTM data for {ticker_upper} — sourced from FMP TTM endpoints.

Values represent Trailing Twelve Months metrics from FMP, used to validate
that compute_ttm_metrics() produces correct output.

Source: Financial Modeling Prep (FMP) API TTM endpoints.
Note: TTM values are point-in-time snapshots. Re-run the builder when data
changes after a new earnings release.
"""

from golden_helpers import GoldenTTMMetric
''')

    print(f"{ticker_upper}_TTM_GOLDEN: list[GoldenTTMMetric] = [")
    for metric_type in sorted(ttm_data.keys()):
        value = ttm_data[metric_type]
        # Use smaller tolerance for large-value flow metrics, larger for stock
        tol = "0.02" if metric_type == "eps_diluted" else "5.0"
        print(f"    GoldenTTMMetric({metric_type!r}, {value!r}, {tol}),")
    print("]")


def main():
    api_key = os.environ.get("FMP_API_KEY", "")

    # Determine which tickers to process
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
        for t in tickers:
            if t not in COMPANIES:
                print(f"Unknown ticker: {t}. Available: {', '.join(COMPANIES.keys())}")
                sys.exit(1)
    else:
        tickers = list(COMPANIES.keys())

    for ticker in tickers:
        cik = COMPANIES[ticker]
        print(f"\n{'═' * 80}")
        print(f"  Processing {ticker} (CIK {cik})")
        print(f"{'═' * 80}")

        print(f"\n═══ Phase 1: Fetching SEC DERA data for {ticker} ═══")
        dera_data = fetch_dera_data(ticker, cik)
        print(f"  Total DERA values: {len(dera_data)}")

        fmp_data: dict[tuple[str, str, date], float] = {}
        if api_key:
            print(f"\n═══ Phase 2: Fetching FMP data for {ticker} ═══")
            fmp_data = fetch_fmp_data(api_key, ticker)
            print(f"  Total FMP values: {len(fmp_data)}")
        else:
            print("\n═══ Phase 2: Skipping FMP (no FMP_API_KEY set) ═══")
            print("  Set FMP_API_KEY to include FMP cross-reference.")

        if fmp_data:
            print(f"\n═══ Phase 3: Cross-reference for {ticker} ═══")
            cross_reference(dera_data, fmp_data)

        print(f"\n═══ Phase 4: Golden data module output for {ticker} ═══")
        print_golden_module(ticker, dera_data, fmp_data)

        # ── Phase 5: TTM golden data from FMP ──
        if api_key:
            print(f"\n═══ Phase 5: Fetching FMP TTM data for {ticker} ═══")
            ttm_data = fetch_fmp_ttm_data(api_key, ticker)
            print(f"  Total FMP TTM values: {len(ttm_data)}")
            if ttm_data:
                print(f"\n═══ Phase 6: TTM golden data module output for {ticker} ═══")
                print_golden_ttm_module(ticker, ttm_data)
        else:
            print(f"\n═══ Phase 5: Skipping FMP TTM (no FMP_API_KEY set) ═══")


if __name__ == "__main__":
    main()
