from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SPEC = spec_from_file_location(
    "build_golden_data",
    Path(__file__).resolve().parents[1] / "scripts" / "build_golden_data.py",
)
assert _SPEC and _SPEC.loader
build_golden_data = module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_golden_data)


def test_canonicalize_dera_debt_metrics_prefers_noncurrent_and_derives_short_term():
    results = {
        ("__long_term_debt_total", "annual", date(2024, 9, 30)): 96_662_000_000.0,
        ("__long_term_debt_noncurrent", "annual", date(2024, 9, 30)): 85_750_000_000.0,
        ("__long_term_debt_current", "annual", date(2024, 9, 30)): 10_912_000_000.0,
        ("__commercial_paper", "annual", date(2024, 9, 30)): 10_000_000_000.0,
    }

    canonical = build_golden_data._canonicalize_dera_debt_metrics(results)

    assert canonical[("long_term_debt", "annual", date(2024, 9, 30))] == 85_750_000_000.0
    assert canonical[("short_term_debt", "annual", date(2024, 9, 30))] == 20_912_000_000.0
    assert not any(key[0].startswith("__") for key in canonical)


def test_canonicalize_dera_debt_metrics_falls_back_to_total_minus_current():
    results = {
        ("__long_term_debt_total", "quarterly", date(2025, 3, 31)): 50_000_000_000.0,
        ("__debt_current", "quarterly", date(2025, 3, 31)): 5_000_000_000.0,
    }

    canonical = build_golden_data._canonicalize_dera_debt_metrics(results)

    assert canonical[("long_term_debt", "quarterly", date(2025, 3, 31))] == 45_000_000_000.0
    assert canonical[("short_term_debt", "quarterly", date(2025, 3, 31))] == 5_000_000_000.0