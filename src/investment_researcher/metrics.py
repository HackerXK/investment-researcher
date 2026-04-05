"""Raw financial metric computation — TTM aggregation and metric derivation.

This module owns:
  - Small math/lookup helpers (_safe_div, _get)
  - Derived-metric enrichment (_derive_ebitda, _with_derived_metrics)
  - TTM aggregation from DuckDB (compute_ttm_metrics)

``ratios.py`` imports the helpers from here and builds ratio formulas on top.
"""

from __future__ import annotations

import duckdb
import numpy as np

from investment_researcher.config import DUCKDB_PATH
from investment_researcher.ingestion.edgar.financials import FLOW_METRICS

# ── Math / lookup helpers ─────────────────────────────────────────────────────


def _safe_div(a: float | None, b: float | None) -> float | None:
    """Return a / b, or None when inputs are missing or b == 0."""
    if a is None or b is None or np.isnan(a) or np.isnan(b) or b == 0:
        return None
    return a / b


def _get(m: dict[str, float], key: str) -> float | None:
    v = m.get(key)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return v


# ── Derived-metric enrichment ─────────────────────────────────────────────────


def _derive_ebitda(m: dict[str, float]) -> float | None:
    """Derive EBITDA when the raw metric is not present in DuckDB."""
    ebitda = _get(m, "ebitda")
    if ebitda is not None:
        return ebitda

    operating_income = _get(m, "operating_income")
    depreciation_and_amortization = _get(m, "depreciation_and_amortization")
    if operating_income is not None and depreciation_and_amortization is not None:
        return operating_income + depreciation_and_amortization

    net_income = _get(m, "net_income")
    income_tax_expense = _get(m, "income_tax_expense")
    interest_expense = _get(m, "interest_expense")
    if (
        net_income is not None
        and income_tax_expense is not None
        and interest_expense is not None
        and depreciation_and_amortization is not None
    ):
        return (
            net_income
            + income_tax_expense
            + interest_expense
            + depreciation_and_amortization
        )

    return None


def _with_derived_metrics(m: dict[str, float]) -> dict[str, float]:
    """Populate derived metrics needed by ratio formulas.

    Uses ``_get`` for all reads so that NaN values from the pivot table are
    treated as missing (None) rather than as numeric 0-ish values.  This
    prevents bugs like ``max(0.0, NaN) == 0.0`` in Python, which silently
    zeroed out ``long_term_debt_noncurrent`` for companies that stopped
    reporting ``LongTermDebtCurrent`` in recent filings (e.g. UNH FY2022+).
    """
    enriched = dict(m)

    # Derive EBITDA from available components
    derived_ebitda = _derive_ebitda(enriched)
    if derived_ebitda is not None:
        enriched["ebitda"] = derived_ebitda

    # Derive free_cash_flow from operating cash flow and capex when filers do
    # not expose a direct FCF concept in XBRL.
    if _get(enriched, "free_cash_flow") is None:
        operating_cash_flow = _get(enriched, "operating_cash_flow")
        capex = _get(enriched, "capex")
        if operating_cash_flow is not None and capex is not None:
            enriched["free_cash_flow"] = operating_cash_flow - abs(capex)

    # Derive gross_profit from revenue - cost_of_revenue only when the implied
    # cost ratio looks like a real COGS signal. This avoids generating bogus
    # gross-margin values for sectors whose reported `cost_of_revenue` is only
    # a narrow subset of direct costs (for example some insurers).
    if _get(enriched, "gross_profit") is None:
        revenue = _get(enriched, "revenue")
        cost_of_revenue = _get(enriched, "cost_of_revenue")
        if revenue not in (None, 0) and cost_of_revenue is not None:
            cogs_ratio = abs(cost_of_revenue / revenue)
            if 0.2 <= cogs_ratio <= 0.95:
                enriched["gross_profit"] = revenue - cost_of_revenue

    # Derive operating_income from gross_profit - operating_expenses when the
    # direct operating-income concept is absent but both components exist.
    if _get(enriched, "operating_income") is None:
        gross_profit = _get(enriched, "gross_profit")
        operating_expenses = _get(enriched, "operating_expenses")
        if gross_profit is not None and operating_expenses is not None:
            enriched["operating_income"] = gross_profit - operating_expenses

    # Derive short_term_debt from commercial_paper + current portion of LTD
    # when not directly available (e.g. AAPL uses CommercialPaper + LongTermDebtCurrent)
    if _get(enriched, "short_term_debt") is None:
        cp = _get(enriched, "commercial_paper")
        ltd_curr = _get(enriched, "long_term_debt_current")
        if cp is not None or ltd_curr is not None:
            enriched["short_term_debt"] = (cp or 0.0) + (ltd_curr or 0.0)

    # Derive total_receivables = accounts_receivable + nontrade_receivables
    # FMP and some data providers include non-trade receivables in their
    # "net receivables" figure used for turnover ratios.
    ar = _get(enriched, "accounts_receivable")
    ntr = _get(enriched, "nontrade_receivables")
    if ar is not None or ntr is not None:
        enriched["total_receivables"] = (ar or 0.0) + (ntr or 0.0)

    return enriched


# ── TTM aggregation ───────────────────────────────────────────────────────────

# SQL placeholders for flow-metric names (built once at import time)
_FLOW_PH = ", ".join(f"'{m}'" for m in FLOW_METRICS)


def compute_ttm_metrics(
    ticker: str,
    db_path: str | None = None,
) -> dict[str, float]:
    """Compute TTM (Trailing Twelve Months) raw metrics for *ticker*.

    For flow metrics (income/cash-flow), sums the 4 most recent discrete
    quarterly values.  For stock metrics (balance-sheet), uses the latest
    available snapshot across quarterly filings.

    The returned dict is enriched via ``_with_derived_metrics`` (EBITDA, FCF,
    gross_profit, operating_income, short_term_debt, total_receivables) so
    callers get a complete set without duplicating derivation logic.

    Returns:
        dict mapping metric_type → TTM value.
    """
    path = db_path or DUCKDB_PATH
    con = duckdb.connect(path, read_only=True)
    try:
        # ── Flow metrics: sum of 4 most recent quarters ───────────────
        flow_df = con.execute(
            f"""
            WITH ranked AS (
                SELECT metric_type, value, period_end,
                       ROW_NUMBER() OVER (
                           PARTITION BY metric_type
                           ORDER BY period_end DESC
                       ) AS rn
                FROM financial_metrics
                WHERE ticker = $1
                  AND period_type = 'quarterly'
                  AND metric_type IN ({_FLOW_PH})
            )
            SELECT metric_type, SUM(value) AS ttm_value, COUNT(*) AS n
            FROM ranked WHERE rn <= 4
            GROUP BY metric_type
            """,
            [ticker],
        ).df()

        ttm: dict[str, float] = {}
        for _, row in flow_df.iterrows():
            if row["n"] == 4:
                ttm[row["metric_type"]] = row["ttm_value"]

        # ── Stock metrics: latest quarterly snapshot ──────────────────
        stock_df = con.execute(
            f"""
            WITH ranked AS (
                SELECT metric_type, value, period_end,
                       ROW_NUMBER() OVER (
                           PARTITION BY metric_type
                           ORDER BY period_end DESC
                       ) AS rn
                FROM financial_metrics
                WHERE ticker = $1
                  AND period_type = 'quarterly'
                  AND metric_type NOT IN ({_FLOW_PH})
            )
            SELECT metric_type, value, period_end FROM ranked WHERE rn = 1
            """,
            [ticker],
        ).df()

        latest_stock_pe = stock_df["period_end"].max() if not stock_df.empty else None
        for _, row in stock_df.iterrows():
            ttm[row["metric_type"]] = row["value"]

        # Some filers only expose share counts and Q4 working-capital balances in
        # the annual 10-K. Fill just those missing inputs from the latest overall
        # snapshot so per-share and liquidity ratios can still be computed
        # without broadly enabling noisy balance-sheet fallbacks.
        fallback_df = con.execute(
            """
            WITH ranked AS (
                SELECT metric_type, value, period_end, period_type,
                       ROW_NUMBER() OVER (
                           PARTITION BY metric_type
                           ORDER BY period_end DESC,
                                    CASE WHEN period_type = 'quarterly' THEN 0 ELSE 1 END
                       ) AS rn
                FROM financial_metrics
                WHERE ticker = $1
                  AND period_type IN ('quarterly', 'annual')
                  AND metric_type IN ('common_shares_outstanding', 'total_current_assets', 'total_current_liabilities')
            )
            SELECT metric_type, value, period_end FROM ranked WHERE rn = 1
            """,
            [ticker],
        ).df()

        for _, row in fallback_df.iterrows():
            # Ignore extremely stale share-count fallbacks; using a decade-old
            # shares-outstanding value creates bogus per-share TTM ratios.
            if (
                row["metric_type"] == "common_shares_outstanding"
                and latest_stock_pe is not None
                and (latest_stock_pe - row["period_end"]).days > 400
            ):
                continue
            ttm.setdefault(row["metric_type"], row["value"])
            if latest_stock_pe is None or row["period_end"] > latest_stock_pe:
                latest_stock_pe = row["period_end"]

    finally:
        con.close()

    return _with_derived_metrics(ttm)
