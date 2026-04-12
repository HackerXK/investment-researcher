#!/usr/bin/env python3
"""Fetch FMP ratio data and generate golden test files.

Usage:
    FMP_API_KEY=your_key python scripts/build_golden_ratios.py
    FMP_API_KEY=your_key python scripts/build_golden_ratios.py AMZN

Fetches from:
  - /api/v3/ratios/{symbol}?period=annual
  - /api/v3/ratios/{symbol}?period=quarter
  - /api/v3/key-metrics/{symbol}?period=annual
  - /api/v3/key-metrics/{symbol}?period=quarter

Outputs tests/fixtures/golden_ratios_{ticker}.py for each ticker.
"""

import json
import os
import sys
import textwrap
from datetime import date, datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TICKERS = ["AAPL", "AMZN", "NVDA", "UNH", "WMT", "XOM"]

# Minimum fiscal year to include (we need matching SEC data)
MIN_YEAR = 2021

FMP_BASE = "https://financialmodelingprep.com/stable"

# Map FMP JSON keys → our ratio names
# "ratios" endpoint
RATIOS_MAP: dict[str, str] = {
    "grossProfitMargin": "gross_profit_margin",
    "operatingProfitMargin": "operating_profit_margin",
    "pretaxProfitMargin": "pretax_profit_margin",
    "netProfitMargin": "net_profit_margin",
    "ebitdaMargin": "ebitda_margin",
    "effectiveTaxRate": "effective_tax_rate",
    "currentRatio": "current_ratio",
    "quickRatio": "quick_ratio",
    "cashRatio": "cash_ratio",
    "debtToEquityRatio": "debt_to_equity_ratio",
    "debtToAssetsRatio": "debt_to_assets_ratio",
    "debtToCapitalRatio": "debt_to_capital_ratio",
    "financialLeverageRatio": "financial_leverage_ratio",
    "assetTurnover": "asset_turnover",
    "receivablesTurnover": "receivables_turnover",
    "payablesTurnover": "payables_turnover",
    "inventoryTurnover": "inventory_turnover",
    "operatingCashFlowSalesRatio": "operating_cash_flow_sales_ratio",
    "freeCashFlowOperatingCashFlowRatio": "free_cash_flow_to_operating_cash_flow_ratio",
    "capitalExpenditureCoverageRatio": "capital_expenditure_coverage_ratio",
    "dividendPaidAndCapexCoverageRatio": "dividend_paid_and_capex_coverage_ratio",
    "dividendPayoutRatio": "dividend_payout_ratio",
    "interestCoverageRatio": "interest_coverage_ratio",
    "operatingCashFlowRatio": "operating_cash_flow_ratio",
    "revenuePerShare": "revenue_per_share",
    "netIncomePerShare": "net_income_per_share",
    "cashPerShare": "cash_per_share",
    "bookValuePerShare": "book_value_per_share",
    "operatingCashFlowPerShare": "operating_cash_flow_per_share",
    "freeCashFlowPerShare": "free_cash_flow_per_share",
}

# "key-metrics" endpoint (additional ratios not in ratios endpoint)
KEY_METRICS_MAP: dict[str, str] = {
    "returnOnAssets": "return_on_assets",
    "returnOnEquity": "return_on_equity",
    "returnOnCapitalEmployed": "return_on_capital_employed",
    "incomeQuality": "income_quality",
    "netDebtToEBITDA": "net_debt_to_ebitda",
    "workingCapital": "working_capital",
    "netCurrentAssetValue": "_skip_",  # not one of our ratios
    "researchAndDevelopementToRevenue": "research_and_development_to_revenue",
}

# Tolerance by ratio name or category
DEFAULT_TOLERANCE = 5.0
PER_SHARE_TOLERANCE = 10.0
DOLLAR_TOLERANCE = 10.0

PER_SHARE_RATIOS = {
    "revenue_per_share", "net_income_per_share", "cash_per_share",
    "book_value_per_share",
    "operating_cash_flow_per_share", "free_cash_flow_per_share",
}
DOLLAR_RATIOS = {"working_capital", "net_debt"}

# Known-bad FMP datapoints with obvious data gaps / zero values that should not
# be used as golden truth.
EXCLUDED_GOLDEN_POINTS = {
    ("AMZN", "ebitda_margin", "annual", date(2022, 12, 31)),
    ("AMZN", "ebitda_margin", "annual", date(2025, 12, 31)),
    ("WMT", "capital_expenditure_coverage_ratio", "annual", date(2026, 1, 31)),
    ("WMT", "dividend_paid_and_capex_coverage_ratio", "annual", date(2026, 1, 31)),
    ("WMT", "free_cash_flow_to_operating_cash_flow_ratio", "annual", date(2026, 1, 31)),
    ("XOM", "research_and_development_to_revenue", "annual", date(2025, 12, 31)),
}


def _tolerance(ratio_name: str) -> float:
    if ratio_name in PER_SHARE_RATIOS:
        return PER_SHARE_TOLERANCE
    if ratio_name in DOLLAR_RATIOS:
        return DOLLAR_TOLERANCE
    return DEFAULT_TOLERANCE


def fetch_fmp(endpoint: str, symbol: str, period: str, api_key: str) -> list[dict]:
    url = f"{FMP_BASE}/{endpoint}"
    params = {"symbol": symbol, "period": period, "apikey": api_key}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code == 402:
        print(f"    ⚠ 402 Payment Required — {endpoint}?period={period} not available on this plan, skipping")
        return []
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "Error Message" in data:
        print(f"  FMP error for {endpoint}?symbol={symbol}: {data['Error Message']}")
        return []
    return data if isinstance(data, list) else []


def parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def extract_ratios(
    ticker: str,
    records: list[dict],
    field_map: dict[str, str],
    period_type: str,
) -> list[dict]:
    """Extract ratio values from FMP records."""
    results = []
    for rec in records:
        raw_date = rec.get("date") or rec.get("period")
        if not raw_date:
            continue
        pe = parse_date(raw_date)
        if pe.year < MIN_YEAR:
            continue

        for fmp_key, ratio_name in field_map.items():
            if ratio_name == "_skip_":
                continue
            val = rec.get(fmp_key)
            if val is None or val == "":
                continue
            try:
                val = float(val)
            except (ValueError, TypeError):
                continue
            # Skip zero / nan
            if val != val:  # nan check
                continue
            if (ticker, ratio_name, period_type, pe) in EXCLUDED_GOLDEN_POINTS:
                continue
            results.append({
                "ratio_name": ratio_name,
                "period_type": period_type,
                "period_end": pe,
                "value": val,
                "tolerance_pct": _tolerance(ratio_name),
            })
    return results


def generate_golden_file(ticker: str, entries: list[dict], outdir: Path) -> Path:
    """Write a golden_ratios_{ticker}.py file."""
    # De-duplicate: same (ratio_name, period_type, period_end) keep first
    seen = set()
    unique = []
    for e in entries:
        key = (e["ratio_name"], e["period_type"], str(e["period_end"]))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    # Sort
    unique.sort(key=lambda e: (e["ratio_name"], e["period_type"], e["period_end"]))

    # Separate annual and quarterly
    annual = [e for e in unique if e["period_type"] == "annual"]
    quarterly = [e for e in unique if e["period_type"] == "quarterly"]

    lines = [
        f'"""Golden ratio data for {ticker} — sourced from FMP API.',
        "",
        "Values from Financial Modeling Prep (FMP) API.",
        "Used to validate that compute_ratios() produces correct output.",
        '"""',
        "",
        "from datetime import date",
        "",
        "from golden_helpers import GoldenRatio",
        "",
    ]

    for label, data, var_suffix in [
        ("annual", annual, "ANNUAL"),
        ("quarterly", quarterly, "QUARTERLY"),
    ]:
        lines.append(f"{ticker}_{var_suffix}_GOLDEN_RATIOS: list[GoldenRatio] = [")
        for e in data:
            lines.append(
                f"    GoldenRatio({e['ratio_name']!r}, {e['period_type']!r}, "
                f"date({e['period_end'].year}, {e['period_end'].month}, {e['period_end'].day}), "
                f"{e['value']!r}, 'fmp', {e['tolerance_pct']}),",
            )
        lines.append("]")
        lines.append("")

    outpath = outdir / f"golden_ratios_{ticker.lower()}.py"
    outpath.write_text("\n".join(lines))
    return outpath


def main():
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("ERROR: Set FMP_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    outdir = PROJECT_ROOT / "tests" / "fixtures"

    tickers = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else TICKERS
    unknown = sorted(set(tickers) - set(TICKERS))
    if unknown:
        print(f"ERROR: Unknown ticker(s): {', '.join(unknown)}", file=sys.stderr)
        sys.exit(1)

    for ticker in tickers:
        print(f"\n{'='*60}")
        print(f"Fetching {ticker}...")
        all_entries: list[dict] = []

        for period, period_type in [("annual", "annual"), ("quarter", "quarterly")]:
            # Ratios endpoint
            print(f"  ratios/{ticker}?period={period}")
            ratio_records = fetch_fmp("ratios", ticker, period, api_key)
            all_entries.extend(extract_ratios(ticker, ratio_records, RATIOS_MAP, period_type))

            # Key Metrics endpoint
            print(f"  key-metrics/{ticker}?period={period}")
            km_records = fetch_fmp("key-metrics", ticker, period, api_key)
            all_entries.extend(extract_ratios(ticker, km_records, KEY_METRICS_MAP, period_type))

        outpath = generate_golden_file(ticker, all_entries, outdir)
        annual_count = sum(1 for e in all_entries if e["period_type"] == "annual")
        quarterly_count = sum(1 for e in all_entries if e["period_type"] == "quarterly")
        print(f"  → {outpath.name}: {annual_count} annual + {quarterly_count} quarterly entries")

    # Also update golden_helpers.py with GoldenRatio dataclass if needed
    helpers_path = outdir / "golden_helpers.py"
    content = helpers_path.read_text()
    if "GoldenRatio" not in content:
        # Add GoldenRatio dataclass
        addition = textwrap.dedent("""

        @dataclass(frozen=True)
        class GoldenRatio:
            \"\"\"A single known-correct financial ratio value.\"\"\"
            ratio_name: str
            period_type: str   # "annual" or "quarterly"
            period_end: date
            value: float
            source: str        # "fmp"
            tolerance_pct: float = 5.0  # percentage tolerance for comparison
        """)
        # Insert after GoldenMetric class
        marker = "# ── Constants"
        if marker in content:
            content = content.replace(marker, addition + "\n" + marker)
            helpers_path.write_text(content)
            print(f"\nAdded GoldenRatio dataclass to {helpers_path.name}")
    else:
        print(f"\nGoldenRatio already exists in {helpers_path.name}")

    print("\nDone! Now run: pytest tests/test_ratios.py -v")


if __name__ == "__main__":
    main()
