"""Golden TTM ratio data for AAPL — sourced from FMP API.

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
# TODO: The following ratios were removed from RATIO_REGISTRY and their golden
# entries removed here.  Re-add golden entries when the ratios are re-enabled:
#   - quick_ratio (needs cash+STI+AR formula + ReceivablesNetCurrent from XBRL)
#   - debt_to_equity_ratio (needs lease liabilities in debt calculation)
#   - debt_to_assets_ratio (needs lease liabilities in debt calculation)
#   - debt_to_capital_ratio (needs lease liabilities in debt calculation)
#   - net_debt_to_ebitda (needs lease liabilities in debt + near-zero instability)
#   - receivables_turnover (needs ReceivablesNetCurrent from XBRL)
#   - inventory_turnover (needs sector-specific inventory classification)
AAPL_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('asset_turnover', 1.1484852239801528, 'fmp', 15.0),
    GoldenTTMRatio('book_value_per_share', 5.979729807613941, 'fmp', 20.0),
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 11.151794534079684, 'fmp', 15.0),
    GoldenTTMRatio('cash_per_share', 4.536634337657625, 'fmp', 20.0),
    GoldenTTMRatio('cash_ratio', 0.27910228063584347, 'fmp', 15.0),
    GoldenTTMRatio('current_ratio', 0.9737446648641658, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 4.902366649779258, 'fmp', 15.0),
    GoldenTTMRatio('dividend_payout_ratio', 0.13148577396265823, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.3511777547708193, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.16557206316818635, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 4.300907132327929, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_per_share', 8.361993409617662, 'fmp', 20.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.910328333530176, 'fmp', 15.0),
    GoldenTTMRatio('gross_profit_margin', 0.4732528803972297, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 1.1502415581989693, 'fmp', 15.0),
    GoldenTTMRatio('net_income_per_share', 7.985878643285487, 'fmp', 20.0),
    GoldenTTMRatio('net_profit_margin', 0.27036823631768275, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_per_share', 9.185689494240568, 'fmp', 20.0),
    GoldenTTMRatio('operating_cash_flow_ratio', 0.8343567350508416, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.31098878142955855, 'fmp', 15.0),
    GoldenTTMRatio('operating_profit_margin', 0.3238395195779779, 'fmp', 15.0),
    GoldenTTMRatio('payables_turnover', 3.250740221287206, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.3240162803563681, 'fmp', 15.0),
    GoldenTTMRatio('research_and_development_to_revenue', 0.08532495288292238, 'fmp', 15.0),
    GoldenTTMRatio('return_on_assets', 0.3105139244444327, 'fmp', 15.0),
    GoldenTTMRatio('return_on_capital_employed', 0.650301940718204, 'fmp', 15.0),
    GoldenTTMRatio('revenue_per_share', 29.53704455837807, 'fmp', 20.0),
    GoldenTTMRatio('working_capital', -4263000000.0, 'fmp', 20.0),
]
