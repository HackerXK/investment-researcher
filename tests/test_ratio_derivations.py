from investment_researcher.metrics import _with_derived_metrics


def test_derives_ebitda_from_operating_income_and_dna():
    metrics = {
        "operating_income": 100.0,
        "depreciation_and_amortization": -15.0,
    }

    enriched = _with_derived_metrics(metrics)

    assert enriched["ebitda"] == 115.0


def test_derives_ebitda_from_net_income_tax_interest_and_dna():
    metrics = {
        "net_income": 80.0,
        "income_tax_expense": -10.0,
        "interest_expense": -5.0,
        "depreciation_and_amortization": -15.0,
    }

    enriched = _with_derived_metrics(metrics)

    assert enriched["ebitda"] == 110.0


def test_preserves_existing_ebitda():
    metrics = {
        "ebitda": 125.0,
        "operating_income": 100.0,
        "depreciation_and_amortization": -15.0,
    }

    enriched = _with_derived_metrics(metrics)

    assert enriched["ebitda"] == 125.0


def test_derives_free_cash_flow_from_operating_cash_flow_and_capex():
    metrics = {
        "operating_cash_flow": 111_482.0,
        "capex": -12_715.0,
    }

    enriched = _with_derived_metrics(metrics)

    assert enriched["free_cash_flow"] == 98_767.0


def test_canonical_free_cash_flow_overrides_inconsistent_existing_value():
    metrics = {
        "operating_cash_flow": 111_482.0,
        "capex": -12_715.0,
        "free_cash_flow": 124_197.0,
    }

    enriched = _with_derived_metrics(metrics)

    assert enriched["free_cash_flow"] == 98_767.0
