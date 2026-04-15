import json

import pytest

from investment_researcher.cli import (
    _parse_cli_tickers,
    normalize_metric_signs_cli,
    rerun_slow_path_cli,
)


def test_parse_cli_tickers_supports_commas_and_whitespace():
    assert _parse_cli_tickers([" aapl ", "MSFT,nvda", " , ", "GOOGL"]) == [
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOGL",
    ]


def test_rerun_slow_path_cli_initializes_and_prints_json(monkeypatch, capsys):
    captured = {}

    def fake_initialize_db(db_path=None):
        captured["initialize_db"] = db_path

    def fake_initialize_state_db(db_path=None):
        captured["initialize_state_db"] = db_path

    def fake_rerun(tickers, db_path=None, state_db_path=None):
        captured["tickers"] = tickers
        captured["rerun_db_path"] = db_path
        captured["rerun_state_db_path"] = state_db_path
        return [
            {
                "ticker": "AAPL",
                "deleted_rows": 10,
                "deleted_state_rows": 1,
                "written_rows": 25,
            },
            {
                "ticker": "MSFT",
                "deleted_rows": 8,
                "deleted_state_rows": 1,
                "written_rows": 20,
            },
            {
                "ticker": "NVDA",
                "deleted_rows": 6,
                "deleted_state_rows": 1,
                "written_rows": 18,
            },
        ]

    monkeypatch.setattr("investment_researcher.cli.initialize_db", fake_initialize_db)
    monkeypatch.setattr(
        "investment_researcher.cli.initialize_state_db",
        fake_initialize_state_db,
    )
    monkeypatch.setattr(
        "investment_researcher.cli.rerun_slow_path_for_companies",
        fake_rerun,
    )

    exit_code = rerun_slow_path_cli(
        [
            "--db-path",
            "/tmp/financial_metrics.duckdb",
            "--state-db-path",
            "/tmp/ingestion_state.db",
            "aapl",
            "MSFT,nvda",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "initialize_db": "/tmp/financial_metrics.duckdb",
        "initialize_state_db": "/tmp/ingestion_state.db",
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "rerun_db_path": "/tmp/financial_metrics.duckdb",
        "rerun_state_db_path": "/tmp/ingestion_state.db",
    }

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "results": [
            {
                "ticker": "AAPL",
                "deleted_rows": 10,
                "deleted_state_rows": 1,
                "written_rows": 25,
            },
            {
                "ticker": "MSFT",
                "deleted_rows": 8,
                "deleted_state_rows": 1,
                "written_rows": 20,
            },
            {
                "ticker": "NVDA",
                "deleted_rows": 6,
                "deleted_state_rows": 1,
                "written_rows": 18,
            },
        ],
        "total_deleted_rows": 24,
        "total_deleted_state_rows": 3,
        "total_written_rows": 63,
    }


def test_rerun_slow_path_cli_rejects_blank_tickers():
    with pytest.raises(SystemExit):
        rerun_slow_path_cli([",", " "])


def test_rerun_slow_path_cli_compact_output(monkeypatch, capsys):
    monkeypatch.setattr("investment_researcher.cli.initialize_db", lambda db_path=None: None)
    monkeypatch.setattr(
        "investment_researcher.cli.initialize_state_db",
        lambda db_path=None: None,
    )
    monkeypatch.setattr(
        "investment_researcher.cli.rerun_slow_path_for_companies",
        lambda tickers, db_path=None, state_db_path=None: [
            {
                "ticker": tickers[0],
                "deleted_rows": 1,
                "deleted_state_rows": 1,
                "written_rows": 2,
            }
        ],
    )

    rerun_slow_path_cli(["--compact", "AAPL"])

    assert capsys.readouterr().out == (
        '{"tickers":["AAPL"],"results":[{"ticker":"AAPL","deleted_rows":1,'
        '"deleted_state_rows":1,"written_rows":2}],"total_deleted_rows":1,'
        '"total_deleted_state_rows":1,"total_written_rows":2}\n'
    )


def test_normalize_metric_signs_cli_initializes_and_prints_json(monkeypatch, capsys):
    captured = {}

    def fake_initialize_db(db_path=None):
        captured["initialize_db"] = db_path

    def fake_normalize(db_path=None, dry_run=False, allow_rerun=False):
        captured["normalize_db_path"] = db_path
        captured["dry_run"] = dry_run
        captured["allow_rerun"] = allow_rerun
        return {
            "dry_run": False,
            "already_applied": False,
            "maintenance_name": "normalize_financial_metric_signs_v1",
            "rows_changed": 12,
            "by_rule": {
                "negative_magnitude": 8,
                "positive_magnitude": 3,
                "sign_flip": 1,
            },
            "by_metric_type": [
                {
                    "metric_type": "capex",
                    "rule": "negative_magnitude",
                    "rows_changed": 10,
                }
            ],
        }

    monkeypatch.setattr("investment_researcher.cli.initialize_db", fake_initialize_db)
    monkeypatch.setattr(
        "investment_researcher.cli.normalize_financial_metric_signs",
        fake_normalize,
    )

    exit_code = normalize_metric_signs_cli([
        "--db-path",
        "/tmp/financial_metrics.duckdb",
        "--compact",
    ])

    assert exit_code == 0
    assert captured == {
        "initialize_db": "/tmp/financial_metrics.duckdb",
        "normalize_db_path": "/tmp/financial_metrics.duckdb",
        "dry_run": False,
        "allow_rerun": False,
    }
    assert capsys.readouterr().out == (
        '{"dry_run":false,"already_applied":false,'
        '"maintenance_name":"normalize_financial_metric_signs_v1",'
        '"rows_changed":12,"by_rule":{"negative_magnitude":8,'
        '"positive_magnitude":3,"sign_flip":1},"by_metric_type":'
        '[{"metric_type":"capex","rule":"negative_magnitude",'
        '"rows_changed":10}]}\n'
    )


def test_normalize_metric_signs_cli_rejects_repeat_without_force(monkeypatch):
    monkeypatch.setattr("investment_researcher.cli.initialize_db", lambda db_path=None: None)

    def fake_normalize(db_path=None, dry_run=False, allow_rerun=False):
        raise ValueError("Financial metric sign normalization has already been applied")

    monkeypatch.setattr(
        "investment_researcher.cli.normalize_financial_metric_signs",
        fake_normalize,
    )

    with pytest.raises(SystemExit):
        normalize_metric_signs_cli([])