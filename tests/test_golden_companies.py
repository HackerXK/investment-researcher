"""Parametrized golden-data tests shared across all company datasets."""

from dataclasses import dataclass
from datetime import date

import pytest

from golden_aapl import AAPL_ANNUAL_GOLDEN, AAPL_QUARTERLY_GOLDEN
from golden_amzn import AMZN_ANNUAL_GOLDEN, AMZN_QUARTERLY_GOLDEN
from golden_helpers import GoldenMetric, assert_value_close, extract_ticker_rows, find_match
from golden_nvda import NVDA_ANNUAL_GOLDEN, NVDA_QUARTERLY_GOLDEN
from golden_unh import UNH_ANNUAL_GOLDEN, UNH_QUARTERLY_GOLDEN
from golden_wmt import WMT_ANNUAL_GOLDEN, WMT_QUARTERLY_GOLDEN
from golden_xom import XOM_ANNUAL_GOLDEN, XOM_QUARTERLY_GOLDEN


@dataclass(frozen=True)
class GoldenCompanyCase:
    ticker: str
    annual_metrics: tuple[GoldenMetric, ...]
    quarterly_metrics: tuple[GoldenMetric, ...]
    require_net_income_bound: bool = True


ANNUAL_START_DATE = date(2022, 1, 1)
QUARTERLY_START_DATE = date(2023, 1, 1)
QUARTERLY_METRICS_TO_CHECK = {
    "revenue",
    "net_income",
    "total_assets",
    "stockholders_equity",
    "eps_diluted",
}
CORE_METRICS = ("revenue", "net_income", "total_assets")
BALANCE_SHEET_TOLERANCE_PCT = 10.0

COMPANY_CASES = (
    GoldenCompanyCase(
        ticker="AAPL",
        annual_metrics=tuple(AAPL_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(AAPL_QUARTERLY_GOLDEN),
    ),
    GoldenCompanyCase(
        ticker="AMZN",
        annual_metrics=tuple(AMZN_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(AMZN_QUARTERLY_GOLDEN),
        require_net_income_bound=False,
    ),
    GoldenCompanyCase(
        ticker="NVDA",
        annual_metrics=tuple(NVDA_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(NVDA_QUARTERLY_GOLDEN),
        require_net_income_bound=False,
    ),
    GoldenCompanyCase(
        ticker="UNH",
        annual_metrics=tuple(UNH_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(UNH_QUARTERLY_GOLDEN),
    ),
    GoldenCompanyCase(
        ticker="WMT",
        annual_metrics=tuple(WMT_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(WMT_QUARTERLY_GOLDEN),
    ),
    GoldenCompanyCase(
        ticker="XOM",
        annual_metrics=tuple(XOM_ANNUAL_GOLDEN),
        quarterly_metrics=tuple(XOM_QUARTERLY_GOLDEN),
    ),
)

COMPANY_PARAMS = [pytest.param(case, id=case.ticker) for case in COMPANY_CASES]


def _build_annual_params():
    params = []
    for case in COMPANY_CASES:
        for golden in case.annual_metrics:
            if golden.period_end < ANNUAL_START_DATE:
                continue
            params.append(
                pytest.param(
                    case.ticker,
                    golden,
                    id=f"{case.ticker}_{golden.metric_type}_annual_{golden.period_end}",
                )
            )
    return params


def _build_quarterly_params():
    params = []
    for case in COMPANY_CASES:
        for golden in case.quarterly_metrics:
            if golden.period_end < QUARTERLY_START_DATE:
                continue
            if golden.metric_type not in QUARTERLY_METRICS_TO_CHECK:
                continue
            params.append(
                pytest.param(
                    case.ticker,
                    golden,
                    id=(
                        f"{case.ticker}_{golden.metric_type}"
                        f"_quarterly_{golden.period_end}"
                    ),
                )
            )
    return params


def _annual_metrics_by_date(metrics: tuple[GoldenMetric, ...]) -> dict[date, dict[str, float]]:
    by_date: dict[date, dict[str, float]] = {}
    for metric in metrics:
        by_date.setdefault(metric.period_end, {})[metric.metric_type] = metric.value
    return by_date


@pytest.fixture(scope="module")
def extracted_rows_by_ticker() -> dict[str, list[dict]]:
    return {case.ticker: extract_ticker_rows(case.ticker) for case in COMPANY_CASES}


@pytest.mark.integration
@pytest.mark.parametrize(("ticker", "golden"), _build_annual_params())
def test_annual_value_matches_golden(extracted_rows_by_ticker, ticker, golden):
    match = find_match(extracted_rows_by_ticker[ticker], golden.metric_type, "annual", golden.period_end)
    if match is None:
        pytest.skip(f"No extracted annual {golden.metric_type} near {golden.period_end} for {ticker}")

    assert_value_close(
        match["value"],
        golden,
        f"{ticker} {golden.metric_type} annual {golden.period_end}",
    )


@pytest.mark.integration
@pytest.mark.parametrize(("ticker", "golden"), _build_quarterly_params())
def test_quarterly_value_matches_golden(extracted_rows_by_ticker, ticker, golden):
    match = find_match(
        extracted_rows_by_ticker[ticker],
        golden.metric_type,
        "quarterly",
        golden.period_end,
    )
    if match is None:
        pytest.skip(
            f"No extracted quarterly {golden.metric_type} near {golden.period_end} for {ticker}"
        )

    assert_value_close(
        match["value"],
        golden,
        f"{ticker} {golden.metric_type} quarterly {golden.period_end}",
    )


@pytest.mark.integration
@pytest.mark.parametrize("case", COMPANY_PARAMS)
def test_extraction_has_core_metrics(extracted_rows_by_ticker, case):
    metric_names = {row["metric_type"] for row in extracted_rows_by_ticker[case.ticker]}
    for expected in CORE_METRICS:
        assert expected in metric_names, (
            f"Missing core metric '{expected}' for {case.ticker}. Got: {sorted(metric_names)}"
        )


@pytest.mark.integration
@pytest.mark.parametrize("case", COMPANY_PARAMS)
def test_extraction_has_annual_and_quarterly_periods(extracted_rows_by_ticker, case):
    period_types = {row["period_type"] for row in extracted_rows_by_ticker[case.ticker]}
    assert "annual" in period_types
    assert "quarterly" in period_types


@pytest.mark.integration
@pytest.mark.parametrize("case", COMPANY_PARAMS)
def test_period_labels_follow_expected_format(extracted_rows_by_ticker, case):
    for row in extracted_rows_by_ticker[case.ticker]:
        period = row["period"]
        if row["period_type"] == "annual":
            assert period.startswith("Twelve Months Ended "), (
                f"Bad annual period label for {case.ticker}: {period}"
            )
        elif row["period_type"] == "quarterly":
            assert period.startswith("Quarter Ended "), (
                f"Bad quarterly period label for {case.ticker}: {period}"
            )


@pytest.mark.parametrize("case", COMPANY_PARAMS)
def test_operating_income_within_expected_bounds(case):
    annual_by_date = _annual_metrics_by_date(case.annual_metrics)

    for period_end, metrics in annual_by_date.items():
        required_metrics = {"operating_income", "gross_profit"}
        if case.require_net_income_bound:
            required_metrics.add("net_income")
        if not required_metrics.issubset(metrics):
            continue

        operating_income = metrics["operating_income"]
        gross_profit = metrics["gross_profit"]
        if case.require_net_income_bound:
            net_income = metrics["net_income"]
            assert net_income < operating_income < gross_profit, (
                f"FY {period_end}: expected NI ({net_income:,.0f}) < "
                f"OI ({operating_income:,.0f}) < GP ({gross_profit:,.0f})"
            )
        else:
            assert operating_income < gross_profit, (
                f"FY {period_end}: expected OI ({operating_income:,.0f}) < "
                f"GP ({gross_profit:,.0f})"
            )


@pytest.mark.parametrize("case", COMPANY_PARAMS)
def test_balance_sheet_identity(case):
    annual_by_date = _annual_metrics_by_date(case.annual_metrics)

    for period_end, metrics in annual_by_date.items():
        required_metrics = {"total_assets", "total_liabilities", "stockholders_equity"}
        if not required_metrics.issubset(metrics):
            continue

        total_assets = metrics["total_assets"]
        total_liabilities = metrics["total_liabilities"]
        stockholders_equity = metrics["stockholders_equity"]
        diff_pct = abs(total_assets - (total_liabilities + stockholders_equity)) / total_assets * 100
        assert diff_pct < BALANCE_SHEET_TOLERANCE_PCT, (
            f"{case.ticker} FY {period_end}: A ({total_assets:,.0f}) != "
            f"L ({total_liabilities:,.0f}) + E ({stockholders_equity:,.0f}), "
            f"diff={diff_pct:.2f}%"
        )