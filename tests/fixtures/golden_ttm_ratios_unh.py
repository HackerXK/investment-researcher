"""Golden TTM ratio data for UNH — sourced from FMP API.

Values from Financial Modeling Prep (FMP) TTM API endpoints.
Used to validate that compute_ttm_ratios() produces correct output.
"""

from golden_helpers import GoldenTTMRatio

# Anchor date for this TTM snapshot (chosen by best-fit probe)
GOLDEN_AS_OF = "2026-01-01"

# TODO: The following ratios were removed from RATIO_REGISTRY and their golden
# entries removed here.  Re-add golden entries when the ratios are re-enabled:
#   - quick_ratio (needs cash+STI+AR formula + ReceivablesNetCurrent from XBRL)
#   - debt_to_equity_ratio (needs lease liabilities in debt calculation)
#   - debt_to_assets_ratio (needs lease liabilities in debt calculation)
#   - debt_to_capital_ratio (needs lease liabilities in debt calculation)
#   - net_debt_to_ebitda (needs lease liabilities in debt + near-zero instability)
#   - receivables_turnover (needs ReceivablesNetCurrent from XBRL)
#   - inventory_turnover (needs sector-specific inventory classification)
UNH_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('asset_turnover', 1.4457185679999742, 'fmp', 15.0),
    GoldenTTMRatio('book_value_per_share', 111.75604395604395, 'fmp', 20.0),
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 5.4381557150745445, 'fmp', 15.0),
    GoldenTTMRatio('cash_per_share', 30.9021978021978, 'fmp', 20.0),
    GoldenTTMRatio('cash_ratio', 0.21205949676666927, 'fmp', 15.0),
    GoldenTTMRatio('current_ratio', 0.7883756756051071, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 1.7071416189980932, 'fmp', 15.0),
    GoldenTTMRatio('dividend_payout_ratio', 0.6566025215660252, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.05152301219705653, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.12859767299448868, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 3.289565402188928, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_per_share', 17.664835164835164, 'fmp', 20.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.8161141290551861, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 1.5379870383384087, 'fmp', 15.0),
    GoldenTTMRatio('interest_coverage_ratio', 4.738630684657672, 'fmp', 15.0),
    GoldenTTMRatio('net_income_per_share', 13.248351648351647, 'fmp', 20.0),
    GoldenTTMRatio('net_profit_margin', 0.026936749134766416, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_per_share', 21.645054945054945, 'fmp', 20.0),
    GoldenTTMRatio('operating_cash_flow_ratio', 0.1714318041376189, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.04400905339312326, 'fmp', 15.0),
    GoldenTTMRatio('operating_profit_margin', 0.04237130977038075, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.032837541641810054, 'fmp', 15.0),
    GoldenTTMRatio('return_on_assets', 0.03894295838568904, 'fmp', 15.0),
    GoldenTTMRatio('return_on_capital_employed', 0.09740913480306548, 'fmp', 15.0),
    GoldenTTMRatio('return_on_equity', 0.12701924621831695, 'fmp', 15.0),
    GoldenTTMRatio('revenue_per_share', 491.83186813186813, 'fmp', 20.0),
    GoldenTTMRatio('working_capital', -24315000000.0, 'fmp', 20.0),
]
