"""Golden TTM ratio data for NVDA — sourced from FMP API.

Values from Financial Modeling Prep (FMP) TTM API endpoints.
Used to validate that compute_ttm_ratios() produces correct output.
"""

# TODO: The following ratios were removed from RATIO_REGISTRY and their golden
# entries removed here.  Re-add golden entries when the ratios are re-enabled:
#   - quick_ratio (needs cash+STI+AR formula + ReceivablesNetCurrent from XBRL)
#   - debt_to_equity_ratio (needs lease liabilities in debt calculation)
#   - debt_to_assets_ratio (needs lease liabilities in debt calculation)
#   - debt_to_capital_ratio (needs lease liabilities in debt calculation)
#   - net_debt_to_ebitda (needs lease liabilities in debt + near-zero instability)
#   - receivables_turnover (needs ReceivablesNetCurrent from XBRL)
#   - inventory_turnover (needs sector-specific inventory classification)
from golden_helpers import GoldenTTMRatio

# Anchor date for this TTM snapshot (chosen by best-fit probe)
GOLDEN_AS_OF = "2026-01-25"

# TODO: The following ratios were removed from RATIO_REGISTRY and their golden
# entries removed here.  Re-add golden entries when the ratios are re-enabled:
#   - quick_ratio (needs cash+STI+AR formula + ReceivablesNetCurrent from XBRL)
#   - debt_to_equity_ratio (needs lease liabilities in debt calculation)
#   - debt_to_assets_ratio (needs lease liabilities in debt calculation)
#   - debt_to_capital_ratio (needs lease liabilities in debt calculation)
#   - net_debt_to_ebitda (needs lease liabilities in debt + near-zero instability)
#   - receivables_turnover (needs ReceivablesNetCurrent from XBRL)
#   - inventory_turnover (needs sector-specific inventory classification)
# TODO: The following ratios were removed from RATIO_REGISTRY and their golden
# entries removed here.  Re-add golden entries when the ratios are re-enabled:
#   - quick_ratio (needs cash+STI+AR formula + ReceivablesNetCurrent from XBRL)
#   - debt_to_equity_ratio (needs lease liabilities in debt calculation)
#   - debt_to_assets_ratio (needs lease liabilities in debt calculation)
#   - debt_to_capital_ratio (needs lease liabilities in debt calculation)
#   - net_debt_to_ebitda (needs lease liabilities in debt + near-zero instability)
#   - receivables_turnover (needs ReceivablesNetCurrent from XBRL)
#   - inventory_turnover (needs sector-specific inventory classification)
NVDA_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 17.00066203243959, 'fmp', 15.0),
    GoldenTTMRatio('cash_per_share', 2.573897300855826, 'fmp', 20.0),
    GoldenTTMRatio('current_ratio', 3.905263812455306, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 14.64053591790194, 'fmp', 15.0),
    GoldenTTMRatio('dividend_payout_ratio', 0.008112137389957273, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.6694143689392326, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.1511700247437257, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 1.3147628947251309, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_per_share', 3.977781435154707, 'fmp', 20.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.9411787612687162, 'fmp', 15.0),
    GoldenTTMRatio('gross_profit_margin', 0.7106808435754708, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 0.855505675997568, 'fmp', 15.0),
    GoldenTTMRatio('interest_coverage_ratio', 503.42471042471044, 'fmp', 15.0),
    GoldenTTMRatio('net_income_per_share', 4.94021560236998, 'fmp', 20.0),
    GoldenTTMRatio('net_profit_margin', 0.5560253406070261, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_per_share', 4.2263824884792625, 'fmp', 20.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.47568283488779184, 'fmp', 15.0),
    GoldenTTMRatio('operating_profit_margin', 0.6038168363141272, 'fmp', 15.0),
    GoldenTTMRatio('payables_turnover', 6.367203424378312, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.6550491344737841, 'fmp', 15.0),
    GoldenTTMRatio('research_and_development_to_revenue', 0.08565884652076058, 'fmp', 15.0),
    GoldenTTMRatio('return_on_equity', 1.0436887718291739, 'fmp', 15.0),
    GoldenTTMRatio('revenue_per_share', 8.88487491770902, 'fmp', 20.0),
    GoldenTTMRatio('working_capital', 93442000000.0, 'fmp', 20.0),
]
