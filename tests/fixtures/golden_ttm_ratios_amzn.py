"""Golden TTM ratio data for AMZN — sourced from FMP API.

Values from Financial Modeling Prep (FMP) TTM API endpoints.
Used to validate that compute_ttm_ratios() produces correct output.
"""

from golden_helpers import GoldenTTMRatio

# Anchor date for this TTM snapshot (chosen by best-fit probe)
GOLDEN_AS_OF = "2026-01-01"

AMZN_TTM_GOLDEN_RATIOS: list[GoldenTTMRatio] = [
    GoldenTTMRatio('asset_turnover', 0.8763902097936291, 'fmp', 15.0),
    GoldenTTMRatio('book_value_per_share', 38.385003268279014, 'fmp', 20.0),
    GoldenTTMRatio('capital_expenditure_coverage_ratio', 1.0583754997382775, 'fmp', 15.0),
    GoldenTTMRatio('cash_ratio', 0.39820187610375907, 'fmp', 15.0),
    GoldenTTMRatio('current_ratio', 1.0508153482718285, 'fmp', 15.0),
    GoldenTTMRatio('dividend_paid_and_capex_coverage_ratio', 1.0583754997382775, 'fmp', 15.0),
    GoldenTTMRatio('ebitda_margin', 0.23062556142631577, 'fmp', 15.0),
    GoldenTTMRatio('effective_tax_rate', 0.19726738117138812, 'fmp', 15.0),
    GoldenTTMRatio('financial_leverage_ratio', 1.9900551007748166, 'fmp', 15.0),
    GoldenTTMRatio('free_cash_flow_per_share', 0.7185544868801942, 'fmp', 20.0),
    GoldenTTMRatio('free_cash_flow_to_operating_cash_flow_ratio', 0.05515575497799504, 'fmp', 15.0),
    GoldenTTMRatio('gross_profit_margin', 0.5028566486824266, 'fmp', 15.0),
    GoldenTTMRatio('income_quality', 1.796240504699369, 'fmp', 15.0),
    GoldenTTMRatio('net_income_per_share', 7.252778037165001, 'fmp', 20.0),
    GoldenTTMRatio('net_profit_margin', 0.10833784334183261, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_per_share', 13.027733681949762, 'fmp', 20.0),
    GoldenTTMRatio('operating_cash_flow_ratio', 0.6399577991330474, 'fmp', 15.0),
    GoldenTTMRatio('operating_cash_flow_sales_ratio', 0.19460082240237458, 'fmp', 15.0),
    GoldenTTMRatio('operating_profit_margin', 0.11155296795755199, 'fmp', 15.0),
    GoldenTTMRatio('payables_turnover', 2.923606952727034, 'fmp', 15.0),
    GoldenTTMRatio('pretax_profit_margin', 0.13496130691677222, 'fmp', 15.0),
    GoldenTTMRatio('return_on_assets', 0.09494622525493801, 'fmp', 15.0),
    GoldenTTMRatio('return_on_capital_employed', 0.13328344752073623, 'fmp', 15.0),
    GoldenTTMRatio('return_on_equity', 0.21873666690604632, 'fmp', 15.0),
    GoldenTTMRatio('revenue_per_share', 66.94593332710804, 'fmp', 20.0),
]
