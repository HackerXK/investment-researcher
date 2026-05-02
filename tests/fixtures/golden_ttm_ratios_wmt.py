"""Golden TTM ratio data for WMT — sourced from FMP API.

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
GOLDEN_AS_OF = "2026-01-31"

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
WMT_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('asset_turnover', 2.5052447061137886, 'fmp', 15.0),
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 1.5601306208242625, 'fmp', 15.0),
    GoldenTTMRatio('cash_ratio', 0.09981483032316296, 'fmp', 15.0),
    GoldenTTMRatio('current_ratio', 0.7897533242144247, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 1.2171659492225249, 'fmp', 15.0),
    GoldenTTMRatio('dividend_payout_ratio', 0.34289498926597545, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.06516182135079919, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.24429061047202144, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 2.857624702611, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.35902802838926984, 'fmp', 15.0),
    GoldenTTMRatio('gross_profit_margin', 0.24926699786724774, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 1.8794935564096766, 'fmp', 15.0),
    GoldenTTMRatio('net_profit_margin', 0.03069845182658102, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_ratio', 0.3867626943583731, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.05828260860420409, 'fmp', 15.0),
    GoldenTTMRatio('operating_profit_margin', 0.041820733829433104, 'fmp', 15.0),
    GoldenTTMRatio('payables_turnover', 8.490112747974184, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.04132154921104993, 'fmp', 15.0),
    GoldenTTMRatio('return_on_assets', 0.07690713392443127, 'fmp', 15.0),
    GoldenTTMRatio('return_on_capital_employed', 0.16831359093448608, 'fmp', 15.0),
    GoldenTTMRatio('return_on_equity', 0.23692825488212027, 'fmp', 15.0),
    GoldenTTMRatio('working_capital', -22595000000.0, 'fmp', 20.0),
]
