"""Canonical sign conventions for stored financial metrics."""

from __future__ import annotations

import math

NEGATIVE_MAGNITUDE_METRICS: frozenset[str] = frozenset(
    {
        "capex",
        "cost_of_revenue",
        "depreciation_and_amortization",
        "dividends_paid",
        "interest_expense",
        "operating_expenses",
        "research_and_development",
    }
)

# SEC/companyfacts commonly reports tax expense as positive expense / negative
# benefit. The canonical DB convention is the opposite: negative expense /
# positive benefit.
SIGN_FLIP_METRICS: frozenset[str] = frozenset({"income_tax_expense"})

POSITIVE_MAGNITUDE_METRICS: frozenset[str] = frozenset(
    {
        "accounts_payable",
        "accounts_receivable",
        "cash",
        "commercial_paper",
        "common_shares_outstanding",
        "goodwill",
        "intangible_assets",
        "inventory",
        "long_term_debt",
        "long_term_debt_current",
        "nontrade_receivables",
        "short_term_debt",
        "short_term_investments",
        "total_assets",
        "total_current_assets",
        "total_current_liabilities",
        "total_liabilities",
    }
)

CANONICAL_SIGNED_METRICS: frozenset[str] = (
    NEGATIVE_MAGNITUDE_METRICS
    | SIGN_FLIP_METRICS
    | POSITIVE_MAGNITUDE_METRICS
)


def normalize_extracted_metric_value(metric_type: str, value: float | int | None):
    """Normalize a raw extracted metric value into the canonical DB convention."""
    if value is None:
        return value

    numeric_value = float(value)
    if math.isnan(numeric_value):
        return numeric_value

    if metric_type in NEGATIVE_MAGNITUDE_METRICS:
        return -abs(numeric_value)
    if metric_type in SIGN_FLIP_METRICS:
        return -numeric_value
    if metric_type in POSITIVE_MAGNITUDE_METRICS:
        return abs(numeric_value)
    return numeric_value