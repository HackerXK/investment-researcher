"""Financial ratio computation engine.

Computes ~46 financial ratios on-the-fly from raw SEC metrics stored in DuckDB.
Ratios are NOT persisted — they are derived each time from the underlying data.

Usage:
    from investment_researcher.ratios import compute_ratios, RATIO_REGISTRY

    df = compute_ratios("AAPL", period_type="annual")
    # → DataFrame[ticker, period_end, period, period_type, ratio_name, value]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import duckdb
import numpy as np
import pandas as pd

from investment_researcher.config import DUCKDB_PATH
from investment_researcher.ingestion.edgar.financials import FLOW_METRICS
from investment_researcher.metrics import (
    _get,
    _safe_div,
    _with_derived_metrics,
    compute_ttm_metrics,
)

# ── Ratio definition ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RatioDef:
    """Declarative definition of a single financial ratio."""

    name: str
    category: str
    inputs: tuple[str, ...]          # raw metric_type names required
    compute: Callable[[dict[str, float]], float | None]
    display_format: str = "pct"      # "pct", "multiple", "dollar", "days"


# ── Ratio registry ───────────────────────────────────────────────────────────

_RATIOS: list[RatioDef] = []


def _r(name: str, category: str, inputs: tuple[str, ...],
       compute: Callable[[dict[str, float]], float | None],
       display_format: str = "pct") -> None:
    _RATIOS.append(RatioDef(name, category, inputs, compute, display_format))


# ── Profitability Margins (7) ────────────────────────────────────────────────

_r("gross_profit_margin", "Profitability Margins",
   ("gross_profit", "revenue"),
   lambda m: _safe_div(_get(m, "gross_profit"), _get(m, "revenue")))

_r("operating_profit_margin", "Profitability Margins",
   ("operating_income", "revenue"),
   lambda m: _safe_div(_get(m, "operating_income"), _get(m, "revenue")))

_r("pretax_profit_margin", "Profitability Margins",
   ("net_income", "income_tax_expense", "revenue"),
   lambda m: _safe_div(
       (_get(m, "net_income") or 0) + (_get(m, "income_tax_expense") or 0),
       _get(m, "revenue"),
   ) if _get(m, "net_income") is not None and _get(m, "income_tax_expense") is not None else None)

_r("net_profit_margin", "Profitability Margins",
   ("net_income", "revenue"),
   lambda m: _safe_div(_get(m, "net_income"), _get(m, "revenue")))

_r("ebitda_margin", "Profitability Margins",
   ("ebitda", "revenue"),
   lambda m: _safe_div(_get(m, "ebitda"), _get(m, "revenue")))

_r("effective_tax_rate", "Profitability Margins",
   ("income_tax_expense", "net_income"),
   lambda m: _safe_div(
       _get(m, "income_tax_expense"),
       (_get(m, "net_income") or 0) + (_get(m, "income_tax_expense") or 0),
   ) if _get(m, "net_income") is not None and _get(m, "income_tax_expense") is not None else None)

_r("research_and_development_to_revenue", "Profitability Margins",
   ("research_and_development", "revenue"),
   lambda m: _safe_div(_get(m, "research_and_development"), _get(m, "revenue")))

# ── Returns (4) ──────────────────────────────────────────────────────────────

_r("return_on_assets", "Returns",
   ("net_income", "total_assets"),
   lambda m: _safe_div(_get(m, "net_income"), _get(m, "total_assets")))

_r("return_on_equity", "Returns",
   ("net_income", "stockholders_equity"),
   lambda m: _safe_div(_get(m, "net_income"), _get(m, "stockholders_equity")))

_r("return_on_capital_employed", "Returns",
   ("operating_income", "total_assets", "total_current_liabilities"),
   lambda m: _safe_div(
       _get(m, "operating_income"),
       (_get(m, "total_assets") or 0) - (_get(m, "total_current_liabilities") or 0),
   ) if _get(m, "total_assets") is not None and _get(m, "total_current_liabilities") is not None else None)

_r("income_quality", "Returns",
   ("operating_cash_flow", "net_income"),
   lambda m: _safe_div(_get(m, "operating_cash_flow"), _get(m, "net_income")),
   "multiple")

# ── Liquidity (2) ────────────────────────────────────────────────────────────

_r("current_ratio", "Liquidity",
   ("total_current_assets", "total_current_liabilities"),
   lambda m: _safe_div(_get(m, "total_current_assets"), _get(m, "total_current_liabilities")),
   "multiple")

# TODO: Re-enable quick_ratio when formula is switched to cash+STI+AR to match
# FMP, and ReceivablesNetCurrent is ingested from XBRL (needed for XOM).
# _r("quick_ratio", "Liquidity",
#    ("total_current_assets", "inventory", "total_current_liabilities"),
#    lambda m: _safe_div(
#        (_get(m, "total_current_assets") or 0) - (_get(m, "inventory") or 0),
#        _get(m, "total_current_liabilities"),
#    ) if _get(m, "total_current_assets") is not None else None,
#    "multiple")

_r("cash_ratio", "Liquidity",
   ("cash", "total_current_liabilities"),
   lambda m: _safe_div(_get(m, "cash"), _get(m, "total_current_liabilities")),
   "multiple")

# ── Leverage / Solvency (1) ──────────────────────────────────────────────────

# TODO: Re-enable debt_to_equity_ratio, debt_to_assets_ratio, debt_to_capital_ratio,
# and net_debt_to_ebitda when operating + finance lease liabilities
# (OperatingLeaseLiability, FinanceLeaseLiability) are ingested from XBRL and
# included in the total-debt calculation to match FMP's methodology.
# _r("debt_to_equity_ratio", "Leverage",
#    ("long_term_debt", "short_term_debt", "stockholders_equity"),
#    lambda m: _safe_div(
#        (_get(m, "long_term_debt") or 0) + (_get(m, "short_term_debt") or 0),
#        _get(m, "stockholders_equity"),
#    ) if _get(m, "long_term_debt") is not None or _get(m, "short_term_debt") is not None else None,
#    "multiple")

# _r("debt_to_assets_ratio", "Leverage",
#    ("long_term_debt", "short_term_debt", "total_assets"),
#    lambda m: _safe_div(
#        (_get(m, "long_term_debt") or 0) + (_get(m, "short_term_debt") or 0),
#        _get(m, "total_assets"),
#    ) if _get(m, "long_term_debt") is not None or _get(m, "short_term_debt") is not None else None)

# _r("debt_to_capital_ratio", "Leverage",
#    ("long_term_debt", "short_term_debt", "stockholders_equity"),
#    lambda m: (lambda td: _safe_div(td, td + (_get(m, "stockholders_equity") or 0))
#               if _get(m, "stockholders_equity") is not None else None)(
#        (_get(m, "long_term_debt") or 0) + (_get(m, "short_term_debt") or 0)
#    ) if _get(m, "long_term_debt") is not None or _get(m, "short_term_debt") is not None else None)

_r("financial_leverage_ratio", "Leverage",
   ("total_assets", "stockholders_equity"),
   lambda m: _safe_div(_get(m, "total_assets"), _get(m, "stockholders_equity")),
   "multiple")

# _r("net_debt_to_ebitda", "Leverage",
#    ("long_term_debt", "short_term_debt", "cash", "ebitda"),
#    lambda m: _safe_div(
#        (_get(m, "long_term_debt") or 0) + (_get(m, "short_term_debt") or 0) - (_get(m, "cash") or 0),
#        _get(m, "ebitda"),
#    ) if _get(m, "ebitda") is not None else None,
#    "multiple")

# ── Efficiency / Turnover (2) ────────────────────────────────────────────────

_r("asset_turnover", "Efficiency",
   ("revenue", "total_assets"),
   lambda m: _safe_div(_get(m, "revenue"), _get(m, "total_assets")),
   "multiple")

# TODO: Re-enable receivables_turnover when ReceivablesNetCurrent is ingested
# from XBRL alongside AccountsReceivableNetCurrent (XOM/UNH gap ~$11B).
# _r("receivables_turnover", "Efficiency",
#    ("revenue", "accounts_receivable"),
#    lambda m: _safe_div(
#        _get(m, "revenue"),
#        _get(m, "total_receivables") if _get(m, "total_receivables") is not None
#        else _get(m, "accounts_receivable"),
#    ),
#    "multiple")

_r("payables_turnover", "Efficiency",
   ("cost_of_revenue", "accounts_payable"),
   lambda m: _safe_div(_get(m, "cost_of_revenue"), _get(m, "accounts_payable")),
   "multiple")

# TODO: Re-enable inventory_turnover when sector-specific inventory
# classification is handled (UNH pharmacy inventory not in FMP scope).
# _r("inventory_turnover", "Efficiency",
#    ("cost_of_revenue", "inventory"),
#    lambda m: _safe_div(_get(m, "cost_of_revenue"), _get(m, "inventory")),
#    "multiple")

# ── Cash Flow (7) ────────────────────────────────────────────────────────────

_r("operating_cash_flow_ratio", "Cash Flow",
   ("operating_cash_flow", "total_current_liabilities"),
   lambda m: _safe_div(_get(m, "operating_cash_flow"), _get(m, "total_current_liabilities")),
   "multiple")

_r("operating_cash_flow_sales_ratio", "Cash Flow",
   ("operating_cash_flow", "revenue"),
   lambda m: _safe_div(_get(m, "operating_cash_flow"), _get(m, "revenue")))

_r("free_cash_flow_to_operating_cash_flow_ratio", "Cash Flow",
   ("free_cash_flow", "operating_cash_flow"),
   lambda m: _safe_div(_get(m, "free_cash_flow"), _get(m, "operating_cash_flow")))

_r("capital_expenditure_coverage_ratio", "Cash Flow",
   ("operating_cash_flow", "capex"),
   lambda m: _safe_div(_get(m, "operating_cash_flow"), abs(_get(m, "capex")))
   if _get(m, "capex") is not None else None,
   "multiple")

_r("dividend_payout_ratio", "Cash Flow",
   ("dividends_paid", "net_income"),
   lambda m: _safe_div(abs(_get(m, "dividends_paid")), _get(m, "net_income"))
   if _get(m, "dividends_paid") is not None else None)

_r("dividend_paid_and_capex_coverage_ratio", "Cash Flow",
   ("operating_cash_flow", "dividends_paid", "capex"),
   lambda m: _safe_div(
       _get(m, "operating_cash_flow"),
       abs(_get(m, "dividends_paid") or 0) + abs(_get(m, "capex") or 0),
   ) if _get(m, "dividends_paid") is not None or _get(m, "capex") is not None else None,
   "multiple")

_r("interest_coverage_ratio", "Cash Flow",
   ("operating_income", "interest_expense"),
   lambda m: _safe_div(_get(m, "operating_income"), _get(m, "interest_expense")),
   "multiple")

# ── Per Share (6) ─────────────────────────────────────────────────────────────

_r("revenue_per_share", "Per Share",
   ("revenue", "common_shares_outstanding"),
   lambda m: _safe_div(_get(m, "revenue"), _get(m, "common_shares_outstanding")),
   "dollar")

_r("net_income_per_share", "Per Share",
   ("net_income", "common_shares_outstanding"),
   lambda m: _safe_div(_get(m, "net_income"), _get(m, "common_shares_outstanding")),
   "dollar")

_r("cash_per_share", "Per Share",
   ("cash", "common_shares_outstanding"),
   # Include short_term_investments (marketable securities due <1yr) to match
   # FMP's definition of cash_per_share = (cash + STI) / shares.
   lambda m: _safe_div(
       (_get(m, "cash") or 0) + (_get(m, "short_term_investments") or 0),
       _get(m, "common_shares_outstanding"),
   ) if _get(m, "cash") is not None else None,
   "dollar")

_r("book_value_per_share", "Per Share",
   ("stockholders_equity", "common_shares_outstanding"),
   lambda m: _safe_div(_get(m, "stockholders_equity"), _get(m, "common_shares_outstanding")),
   "dollar")

_r("operating_cash_flow_per_share", "Per Share",
   ("operating_cash_flow", "common_shares_outstanding"),
   lambda m: _safe_div(_get(m, "operating_cash_flow"), _get(m, "common_shares_outstanding")),
   "dollar")

_r("free_cash_flow_per_share", "Per Share",
   ("free_cash_flow", "common_shares_outstanding"),
   lambda m: _safe_div(_get(m, "free_cash_flow"), _get(m, "common_shares_outstanding")),
   "dollar")

# ── Other Key Metrics (2) ────────────────────────────────────────────────────

_r("working_capital", "Other",
   ("total_current_assets", "total_current_liabilities"),
   lambda m: ((_get(m, "total_current_assets") or 0) - (_get(m, "total_current_liabilities") or 0))
   if _get(m, "total_current_assets") is not None and _get(m, "total_current_liabilities") is not None else None,
   "dollar")

_r("net_debt", "Other",
   ("long_term_debt", "short_term_debt", "cash"),
   lambda m: ((_get(m, "long_term_debt") or 0) + (_get(m, "short_term_debt") or 0) - (_get(m, "cash") or 0))
   if _get(m, "long_term_debt") is not None or _get(m, "short_term_debt") is not None else None,
   "dollar")


# ── Public API ────────────────────────────────────────────────────────────────

RATIO_REGISTRY: tuple[RatioDef, ...] = tuple(_RATIOS)

RATIO_CATEGORIES: list[str] = list(dict.fromkeys(r.category for r in RATIO_REGISTRY))

RATIO_NAMES: list[str] = [r.name for r in RATIO_REGISTRY]


def get_ratios_by_category() -> dict[str, list[RatioDef]]:
    """Return ratios grouped by category, preserving definition order."""
    result: dict[str, list[RatioDef]] = {}
    for r in RATIO_REGISTRY:
        result.setdefault(r.category, []).append(r)
    return result


def _required_metric_types() -> set[str]:
    """Return the union of all raw metric types needed by any ratio."""
    required = {inp for r in RATIO_REGISTRY for inp in r.inputs}
    if "ebitda" in required:
        required.update(
            {
                "operating_income",
                "depreciation_and_amortization",
                "net_income",
                "income_tax_expense",
                "interest_expense",
            }
        )
    # Always fetch short_term_debt component metrics so _with_derived_metrics
    # can derive short_term_debt = commercial_paper + long_term_debt_current
    # for companies that don't report ShortTermBorrowings directly (e.g. AAPL).
    if "short_term_debt" in required:
        required.update({"commercial_paper", "long_term_debt_current"})
    # Always fetch nontrade_receivables for total_receivables derivation
    required.add("nontrade_receivables")
    # Always fetch short_term_investments (used in cash_per_share)
    required.add("short_term_investments")
    return required


def _apply_share_split_adjustment(pivoted: pd.DataFrame) -> pd.DataFrame:
    """Retroactively normalize pre-split share counts for consistency.

    If consecutive annual periods show a share count jump of >=3x (a stock split),
    multiply all earlier periods by the split factor so that all periods use the
    same post-split share basis as the most recent data.
    """
    col = "common_shares_outstanding"
    if col not in pivoted.columns:
        return pivoted

    shares = pivoted[col].copy()
    valid = shares[shares.notna() & (shares > 0)]
    if len(valid) < 2:
        return pivoted

    periods = list(valid.index)
    # Walk newest-to-oldest; when a >=3x jump is found, back-adjust all earlier periods.
    # After adjusting, re-read the column so the next iteration sees updated values.
    for i in range(len(periods) - 1, 0, -1):
        curr = pivoted.loc[periods[i], col]
        prev = pivoted.loc[periods[i - 1], col]
        if pd.isna(curr) or pd.isna(prev) or prev <= 0:
            continue
        ratio = curr / prev
        if ratio >= 3.0:
            split_factor = round(ratio)
            for j in range(i):
                pe = periods[j]
                if pd.notna(pivoted.loc[pe, col]) and pivoted.loc[pe, col] > 0:
                    pivoted.loc[pe, col] *= split_factor

    return pivoted


def _query_raw_metrics(
    ticker: str,
    period_type: str,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Fetch raw metrics from DuckDB, pivoted as period_end × metric_type."""
    path = db_path or DUCKDB_PATH
    con = duckdb.connect(path, read_only=True)
    try:
        needed = _required_metric_types()
        placeholders = ", ".join(f"'{m}'" for m in needed)
        df = con.execute(
            f"""
            SELECT metric_type, value, period_end, period
            FROM financial_metrics
            WHERE ticker = $1
              AND period_type = $2
              AND metric_type IN ({placeholders})
            ORDER BY period_end
            """,
            [ticker, period_type],
        ).df()
    finally:
        con.close()
    return df


def compute_ratios(
    ticker: str,
    period_type: str = "annual",
    ratio_names: list[str] | None = None,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Compute financial ratios for *ticker*.

    Args:
        ticker: Company ticker symbol.
        period_type: "annual" or "quarterly".
        ratio_names: If given, only compute these ratios.  Otherwise all.
        db_path: Optional DuckDB path override (for testing).

    Returns:
        Long-form DataFrame with columns:
        [ticker, period_end, period, period_type, ratio_name, value]
    """
    raw = _query_raw_metrics(ticker, period_type, db_path)
    if raw.empty:
        return pd.DataFrame(
            columns=["ticker", "period_end", "period", "period_type", "ratio_name", "value"]
        )

    # Pivot: rows = period_end, columns = metric_type, values = value
    pivoted = raw.pivot_table(
        index="period_end", columns="metric_type", values="value", aggfunc="first",
    )

    # Normalize share counts for stock splits so per-share ratios are consistent
    # across periods regardless of which split-adjusted filing was ingested.
    if period_type == "annual":
        pivoted = _apply_share_split_adjustment(pivoted)

    # Also keep the period label for each period_end
    period_labels = (
        raw.drop_duplicates(subset=["period_end"])
        .set_index("period_end")["period"]
    )

    # Determine which ratios to compute
    if ratio_names is not None:
        ratios = [r for r in RATIO_REGISTRY if r.name in ratio_names]
    else:
        ratios = list(RATIO_REGISTRY)

    rows: list[dict] = []
    periods = list(pivoted.index)
    for i, pe in enumerate(periods):
        base_row = pivoted.loc[pe].to_dict()
        metric_row = _with_derived_metrics(base_row)
        period_label = period_labels.get(pe, "")
        for rdef in ratios:
            val = rdef.compute(metric_row)
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                rows.append({
                    "ticker": ticker,
                    "period_end": pe,
                    "period": period_label,
                    "period_type": period_type,
                    "ratio_name": rdef.name,
                    "value": val,
                })

    return pd.DataFrame(rows)


def compute_ratios_wide(
    ticker: str,
    period_type: str = "annual",
    ratio_names: list[str] | None = None,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Wide-form ratios: rows = period_end, columns = ratio_name.

    Convenience wrapper around compute_ratios() for display.
    """
    long = compute_ratios(ticker, period_type, ratio_names, db_path)
    if long.empty:
        return long
    return long.pivot_table(
        index="period_end", columns="ratio_name", values="value", aggfunc="first",
    ).sort_index()


def latest_ratios(
    ticker: str,
    period_type: str = "annual",
    db_path: str | None = None,
) -> dict[str, float]:
    """Return the most recent value of every computable ratio.

    Returns:
        dict mapping ratio_name → value
    """
    df = compute_ratios(ticker, period_type, db_path=db_path)
    if df.empty:
        return {}
    latest_pe = df["period_end"].max()
    latest_df = df[df["period_end"] == latest_pe]
    return dict(zip(latest_df["ratio_name"], latest_df["value"]))


def compute_ttm_ratios(
    ticker: str,
    db_path: str | None = None,
) -> dict[str, float]:
    """Compute TTM (Trailing Twelve Months) ratios for *ticker*.

    Gathers TTM metrics via :func:`compute_ttm_metrics`, then runs every
    ratio in RATIO_REGISTRY against the assembled metric dict.

    Returns:
        dict mapping ratio_name → value (single snapshot).
    """
    metric_row = compute_ttm_metrics(ticker, db_path=db_path)

    result: dict[str, float] = {}
    for rdef in RATIO_REGISTRY:
        val = rdef.compute(metric_row)
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            result[rdef.name] = val

    return result
