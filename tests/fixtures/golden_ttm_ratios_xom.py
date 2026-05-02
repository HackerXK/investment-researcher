"""Golden TTM ratio data for XOM — sourced from FMP API.

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
XOM_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('asset_turnover', 0.7214241168871665, 'fmp', 15.0),
    GoldenTTMRatio('book_value_per_share', 61.56222581389979, 'fmp', 20.0),
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 1.8326398194513012, 'fmp', 15.0),
    GoldenTTMRatio('current_ratio', 1.1527996681874741, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 1.1399679747307465, 'fmp', 15.0),
    GoldenTTMRatio('dividend_payout_ratio', 0.5973859381500486, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.20951822293573732, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.27876320635843754, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 1.730933820637968, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_per_share', 5.451858693142461, 'fmp', 20.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.45433904175485856, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 1.7524278392230914, 'fmp', 15.0),
    GoldenTTMRatio('net_income_per_share', 6.659893788963288, 'fmp', 20.0),
    GoldenTTMRatio('net_profit_margin', 0.08905080193266544, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_per_share', 11.999538212883861, 'fmp', 20.0),
    GoldenTTMRatio('operating_cash_flow_ratio', 0.7185123738421125, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.16044827958815086, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.12740772757444313, 'fmp', 15.0),
    GoldenTTMRatio('return_on_assets', 0.06424339614236714, 'fmp', 15.0),
    GoldenTTMRatio('return_on_equity', 0.11038019248799341, 'fmp', 15.0),
    GoldenTTMRatio('revenue_per_share', 74.78757792657585, 'fmp', 20.0),
    GoldenTTMRatio('working_capital', 11052000000.0, 'fmp', 20.0),
]
