#!/usr/bin/env python3
"""Fetch FMP TTM ratio data and generate golden test files.

Usage:
    FMP_API_KEY=your_key python scripts/build_golden_ttm_ratios.py
    FMP_API_KEY=your_key python scripts/build_golden_ttm_ratios.py AMZN
    FMP_API_KEY=your_key python scripts/build_golden_ttm_ratios.py --as-of 2025-12-31 AMZN

Fetches from:
  - /stable/ratios-ttm?symbol={TICKER}
  - /stable/key-metrics-ttm?symbol={TICKER}

Outputs tests/fixtures/golden_ttm_ratios_{ticker}.py for each ticker.
"""

import os
import sys
from datetime import date
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TICKERS = ["AAPL", "AMZN", "NVDA", "UNH", "WMT", "XOM"]

FMP_BASE = "https://financialmodelingprep.com/stable"

# Map FMP TTM JSON keys → our ratio names.
# FMP appends "TTM" to the base field name.
RATIOS_TTM_MAP: dict[str, str] = {
    "grossProfitMarginTTM": "gross_profit_margin",
    "operatingProfitMarginTTM": "operating_profit_margin",
    "pretaxProfitMarginTTM": "pretax_profit_margin",
    "netProfitMarginTTM": "net_profit_margin",
    "ebitdaMarginTTM": "ebitda_margin",
    "effectiveTaxRateTTM": "effective_tax_rate",
    "currentRatioTTM": "current_ratio",
    "quickRatioTTM": "quick_ratio",
    "cashRatioTTM": "cash_ratio",
    "debtToEquityRatioTTM": "debt_to_equity_ratio",
    "debtToAssetsRatioTTM": "debt_to_assets_ratio",
    "debtToCapitalRatioTTM": "debt_to_capital_ratio",
    "financialLeverageRatioTTM": "financial_leverage_ratio",
    "assetTurnoverTTM": "asset_turnover",
    "receivablesTurnoverTTM": "receivables_turnover",
    "payablesTurnoverTTM": "payables_turnover",
    "inventoryTurnoverTTM": "inventory_turnover",
    "operatingCashFlowSalesRatioTTM": "operating_cash_flow_sales_ratio",
    "freeCashFlowOperatingCashFlowRatioTTM": "free_cash_flow_to_operating_cash_flow_ratio",
    "capitalExpenditureCoverageRatioTTM": "capital_expenditure_coverage_ratio",
    "dividendPaidAndCapexCoverageRatioTTM": "dividend_paid_and_capex_coverage_ratio",
    "dividendPayoutRatioTTM": "dividend_payout_ratio",
    "interestCoverageRatioTTM": "interest_coverage_ratio",
    "operatingCashFlowRatioTTM": "operating_cash_flow_ratio",
    "revenuePerShareTTM": "revenue_per_share",
    "netIncomePerShareTTM": "net_income_per_share",
    "cashPerShareTTM": "cash_per_share",
    "bookValuePerShareTTM": "book_value_per_share",
    "operatingCashFlowPerShareTTM": "operating_cash_flow_per_share",
    "freeCashFlowPerShareTTM": "free_cash_flow_per_share",
}

KEY_METRICS_TTM_MAP: dict[str, str] = {
    "returnOnAssetsTTM": "return_on_assets",
    "returnOnEquityTTM": "return_on_equity",
    "returnOnCapitalEmployedTTM": "return_on_capital_employed",
    "incomeQualityTTM": "income_quality",
    "netDebtToEBITDATTM": "net_debt_to_ebitda",
    "workingCapitalTTM": "working_capital",
    "researchAndDevelopementToRevenueTTM": "research_and_development_to_revenue",
}

# Tolerance by ratio name
DEFAULT_TOLERANCE = 15.0
PER_SHARE_TOLERANCE = 20.0
DOLLAR_TOLERANCE = 20.0

PER_SHARE_RATIOS = {
    "revenue_per_share", "net_income_per_share", "cash_per_share",
    "book_value_per_share",
    "operating_cash_flow_per_share", "free_cash_flow_per_share",
}
DOLLAR_RATIOS = {"working_capital", "net_debt"}

# Known-bad FMP TTM datapoints with obvious data gaps / zero values that should
# not be treated as golden truth.
EXCLUDED_TTM_GOLDEN_POINTS = {
    ("AAPL", "interest_coverage_ratio"),
    ("AMZN", "cash_per_share"),
    ("AMZN", "working_capital"),
}


def _tolerance(ratio_name: str) -> float:
    if ratio_name in PER_SHARE_RATIOS:
        return PER_SHARE_TOLERANCE
    if ratio_name in DOLLAR_RATIOS:
        return DOLLAR_TOLERANCE
    return DEFAULT_TOLERANCE


def fetch_fmp_ttm(endpoint: str, symbol: str, api_key: str) -> list[dict]:
    url = f"{FMP_BASE}/{endpoint}"
    params = {"symbol": symbol, "apikey": api_key}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code == 402:
        print(f"    ⚠ 402 Payment Required — {endpoint} not available on this plan, skipping")
        return []
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "Error Message" in data:
        print(f"  FMP error for {endpoint}?symbol={symbol}: {data['Error Message']}")
        return []
    return data if isinstance(data, list) else [data] if isinstance(data, dict) else []


def extract_ttm_ratios(
    ticker: str,
    records: list[dict],
    field_map: dict[str, str],
) -> list[dict]:
    """Extract TTM ratio values from FMP records (typically a single record)."""
    results = []
    for rec in records:
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
            if val != val:  # nan check
                continue
            if (ticker, ratio_name) in EXCLUDED_TTM_GOLDEN_POINTS:
                continue
            results.append({
                "ratio_name": ratio_name,
                "value": val,
                "tolerance_pct": _tolerance(ratio_name),
            })
    return results


def generate_golden_file(
    ticker: str,
    entries: list[dict],
    outdir: Path,
    as_of_date: date | None = None,
) -> Path:
    """Write a golden_ttm_ratios_{ticker}.py file."""
    # De-duplicate by ratio_name (keep first)
    seen = set()
    unique = []
    for e in entries:
        if e["ratio_name"] not in seen:
            seen.add(e["ratio_name"])
            unique.append(e)

    unique.sort(key=lambda e: e["ratio_name"])

    lines = [
        f'"""Golden TTM ratio data for {ticker} — sourced from FMP API.',
        "",
        "Values from Financial Modeling Prep (FMP) TTM API endpoints.",
        "Used to validate that compute_ttm_ratios() produces correct output.",
        '"""',
        "",
    ]
    if as_of_date is not None:
        lines.extend([
            "from datetime import date",
            "from golden_helpers import GoldenTTMRatio",
            "",
            f"GOLDEN_AS_OF = date({as_of_date.year}, {as_of_date.month}, {as_of_date.day})",
            "",
        ])
    else:
        lines.extend([
            "from golden_helpers import GoldenTTMRatio",
            "",
        ])
    lines.extend([
        f"{ticker}_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [",
    ])
    for e in unique:
        lines.append(
            f"    GoldenTTMRatio({e['ratio_name']!r}, {e['value']!r}, 'fmp', {e['tolerance_pct']}),",
        )
    lines.append("]")
    lines.append("")

    outpath = outdir / f"golden_ttm_ratios_{ticker.lower()}.py"
    outpath.write_text("\n".join(lines))
    return outpath


def _parse_cli_args(argv: list[str]) -> tuple[list[str], date | None]:
    tickers: list[str] = []
    as_of_date: date | None = None

    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--as-of":
            index += 1
            if index >= len(argv):
                print("ERROR: --as-of requires a YYYY-MM-DD value", file=sys.stderr)
                sys.exit(1)
            as_of_date = date.fromisoformat(argv[index])
        elif arg.startswith("--as-of="):
            as_of_date = date.fromisoformat(arg.split("=", 1)[1])
        else:
            tickers.append(arg.upper())
        index += 1

    return tickers, as_of_date


def main():
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("ERROR: Set FMP_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    outdir = PROJECT_ROOT / "tests" / "fixtures"

    tickers, as_of_date = _parse_cli_args(sys.argv[1:])
    tickers = tickers or TICKERS
    unknown = sorted(set(tickers) - set(TICKERS))
    if unknown:
        print(f"ERROR: Unknown ticker(s): {', '.join(unknown)}", file=sys.stderr)
        sys.exit(1)

    for ticker in tickers:
        print(f"\n{'='*60}")
        print(f"Fetching TTM data for {ticker}...")
        all_entries: list[dict] = []

        # Ratios TTM endpoint
        print(f"  ratios-ttm?symbol={ticker}")
        ratio_records = fetch_fmp_ttm("ratios-ttm", ticker, api_key)
        all_entries.extend(extract_ttm_ratios(ticker, ratio_records, RATIOS_TTM_MAP))

        # Key Metrics TTM endpoint
        print(f"  key-metrics-ttm?symbol={ticker}")
        km_records = fetch_fmp_ttm("key-metrics-ttm", ticker, api_key)
        all_entries.extend(extract_ttm_ratios(ticker, km_records, KEY_METRICS_TTM_MAP))

        outpath = generate_golden_file(ticker, all_entries, outdir, as_of_date=as_of_date)
        print(f"  → {outpath.name}: {len(all_entries)} TTM entries")

    print("\nDone!")


if __name__ == "__main__":
    main()
