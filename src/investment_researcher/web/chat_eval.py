"""Live chat evaluation helpers.

This module powers an opt-in evaluation harness that runs the real chat stack
against the configured OpenAI-compatible endpoint, then evaluates the answer
with a second LLM pass using compact SEC-derived evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI


_HOST_RUNTIME_ENV_MAP = (
    ("EDGAR_LOCAL_DATA_DIR_HOST_SOURCE", "EDGAR_LOCAL_DATA_DIR_RUNTIME"),
    ("DUCKDB_DIR_HOST_SOURCE", "DUCKDB_DIR_RUNTIME"),
    ("DUCKDB_PATH_HOST_SOURCE", "DUCKDB_PATH_RUNTIME"),
    ("STATE_DIR_HOST_SOURCE", "STATE_DIR_RUNTIME"),
    ("STATE_DB_PATH_HOST_SOURCE", "STATE_DB_PATH_RUNTIME"),
)

_MAX_EVIDENCE_CHARS = 64_000
_MAX_FILING_EXCERPT_CHARS = 24_000
_EVIDENCE_TIMEOUT_SECONDS = 300
_EMPTY_ANSWER_RETRY_SUFFIX = (
    "Provide a complete final answer. Do not return a blank or whitespace-only "
    "response. Use the tools if needed, then answer directly."
)


class ChatEvalQuestionLike(Protocol):
    question_id: str
    title: str
    prompt: str
    ticker: str | None
    difficulty: str
    expected_tools: tuple[str, ...]
    evidence_kind: str
    evidence_params: dict[str, Any]
    must_cover: tuple[str, ...]
    smoke: bool
    chat_timeout_seconds: int
    evaluation_timeout_seconds: int
    notes: str


@dataclass
class EvidenceBundle:
    kind: str
    summary: str
    payload: Any


@dataclass
class ChatRunOutcome:
    status: str
    duration_seconds: float
    session_id: str | None = None
    answer: str = ""
    progress_messages: list[str] = field(default_factory=list)
    error: str | None = None
    http_status: int | None = None
    raw_sse: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationVerdict:
    status: str
    duration_seconds: float
    overall: str = "fail"
    faithfulness: str = "fail"
    factual_grounding: str = "fail"
    completeness: str = "fail"
    reason: str = ""
    pass_reasons: list[str] = field(default_factory=list)
    fail_reasons: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    missing_key_facts: list[str] = field(default_factory=list)
    ambiguity_notes: list[str] = field(default_factory=list)
    raw_response: str = ""
    error: str | None = None


@dataclass
class ChatEvaluationResult:
    question_id: str
    title: str
    ticker: str | None
    difficulty: str
    prompt: str
    expected_tools: list[str]
    must_cover: list[str]
    smoke: bool
    notes: str
    started_at: str
    evidence_kind: str
    evidence_summary: str
    evidence_payload: Any
    chat: ChatRunOutcome
    evaluation: EvaluationVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "title": self.title,
            "ticker": self.ticker,
            "difficulty": self.difficulty,
            "prompt": self.prompt,
            "expected_tools": self.expected_tools,
            "must_cover": self.must_cover,
            "smoke": self.smoke,
            "notes": self.notes,
            "started_at": self.started_at,
            "evidence_kind": self.evidence_kind,
            "evidence_summary": self.evidence_summary,
            "evidence_payload": self.evidence_payload,
            "chat": asdict(self.chat),
            "evaluation": asdict(self.evaluation),
        }


def prepare_live_environment(project_root: Path) -> dict[str, str]:
    """Load .env and translate Docker runtime paths to host paths."""
    env_path = project_root / ".env"
    load_dotenv(env_path, override=True)

    applied: dict[str, str] = {}
    for host_var, runtime_var in _HOST_RUNTIME_ENV_MAP:
        host_value = os.getenv(host_var)
        if host_value:
            os.environ[runtime_var] = host_value
            applied[runtime_var] = host_value

    required = ["LLM_API_BASE", "LLM_MODEL", "LLM_API_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required .env settings: {', '.join(missing)}")

    return applied


def summarize_environment() -> dict[str, str | None]:
    """Return the key runtime values used by the live harness."""
    llm_api_base, _, llm_model = _get_llm_config()
    return {
        "LLM_API_BASE": llm_api_base,
        "LLM_MODEL": llm_model,
        "EDGAR_LOCAL_DATA_DIR_RUNTIME": os.getenv("EDGAR_LOCAL_DATA_DIR_RUNTIME"),
        "DUCKDB_PATH_RUNTIME": os.getenv("DUCKDB_PATH_RUNTIME"),
        "STATE_DB_PATH_RUNTIME": os.getenv("STATE_DB_PATH_RUNTIME"),
    }


def _get_llm_config() -> tuple[str, str, str]:
    """Resolve LLM settings lazily so host overrides are applied first."""
    from investment_researcher.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL

    return LLM_API_BASE, LLM_API_KEY, LLM_MODEL


def _build_eval_client() -> AsyncOpenAI:
    """Create the evaluator client using the same config-backed setup as chat.py."""
    llm_api_base, llm_api_key, _ = _get_llm_config()
    return AsyncOpenAI(base_url=llm_api_base, api_key=llm_api_key)


async def probe_llm_endpoint(timeout_seconds: float = 10.0) -> tuple[bool, str]:
    """Check whether the configured OpenAI-compatible endpoint is reachable."""
    llm_api_base, _, _ = _get_llm_config()
    base_url = llm_api_base.rstrip("/")
    if not base_url:
        return False, "LLM_API_BASE is not configured"
    models_url = f"{base_url}/models"
    try:
        async with AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(models_url)
        if response.status_code >= 400:
            return False, f"GET {models_url} returned HTTP {response.status_code}"
        return True, f"GET {models_url} returned HTTP {response.status_code}"
    except Exception as exc:
        detail = str(exc).strip() or "connection failed"
        return False, f"GET {models_url} failed: {type(exc).__name__}: {detail}"


def _build_chat_eval_session_id(question_id: str) -> str:
    """Create a readable but unique session id for one chat-eval chat request."""
    return f"chat-eval-{question_id}-{uuid4().hex}"


async def run_chat_case(app: Any, question: ChatEvalQuestionLike) -> ChatRunOutcome:
    """Run one live chat prompt through the FastAPI app and capture SSE output."""
    started = time.perf_counter()
    transport = ASGITransport(app=app)

    async def _single_attempt(message: str) -> ChatRunOutcome:
        session_id = _build_chat_eval_session_id(question.question_id)
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "source": "chat-eval",
        }
        if question.ticker:
            payload["ticker"] = question.ticker

        async with AsyncClient(transport=transport, base_url="http://chat-eval") as client:
            try:
                response = await asyncio.wait_for(
                    client.post("/api/chat", json=payload),
                    timeout=question.chat_timeout_seconds,
                )
            except asyncio.TimeoutError:
                return ChatRunOutcome(
                    status="chat_timeout",
                    duration_seconds=0.0,
                    session_id=session_id,
                    error=f"chat timed out after {question.chat_timeout_seconds} seconds",
                )
            except Exception as exc:
                return ChatRunOutcome(
                    status="chat_error",
                    duration_seconds=0.0,
                    session_id=session_id,
                    error=str(exc),
                )

        if response.status_code != 200:
            return ChatRunOutcome(
                status="chat_error",
                duration_seconds=0.0,
                session_id=session_id,
                error=f"chat returned HTTP {response.status_code}",
                http_status=response.status_code,
            )

        progress_messages: list[str] = []
        token_chunks: list[str] = []
        raw_sse: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            payload_text = line[6:]
            if payload_text == "[DONE]":
                raw_sse.append({"done": True})
                continue
            try:
                event_payload = json.loads(payload_text)
            except json.JSONDecodeError:
                raw_sse.append({"invalid_json": payload_text})
                continue
            raw_sse.append(event_payload)
            if "progress" in event_payload:
                progress_messages.append(str(event_payload["progress"]))
            if "token" in event_payload:
                token_chunks.append(str(event_payload["token"]))
            if "error" in event_payload:
                return ChatRunOutcome(
                    status="chat_error",
                    duration_seconds=0.0,
                    session_id=session_id,
                    answer="".join(token_chunks),
                    progress_messages=progress_messages,
                    error=str(event_payload["error"]),
                    http_status=response.status_code,
                    raw_sse=raw_sse,
                )

        answer = "".join(token_chunks).strip()
        if not answer:
            return ChatRunOutcome(
                status="empty_answer",
                duration_seconds=0.0,
                session_id=session_id,
                progress_messages=progress_messages,
                error="chat returned no final answer tokens",
                http_status=response.status_code,
                raw_sse=raw_sse,
            )

        return ChatRunOutcome(
            status="ok",
            duration_seconds=0.0,
            session_id=session_id,
            answer=answer,
            progress_messages=progress_messages,
            http_status=response.status_code,
            raw_sse=raw_sse,
        )

    outcome = await _single_attempt(question.prompt)
    if outcome.status == "empty_answer":
        retry_prompt = f"{question.prompt}\n\n{_EMPTY_ANSWER_RETRY_SUFFIX}"
        outcome = await _single_attempt(retry_prompt)

    outcome.duration_seconds = time.perf_counter() - started
    return outcome


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    converted = (
        df.reset_index()
        if df.index.name is not None or not isinstance(df.index, pd.RangeIndex)
        else df.copy()
    )
    for column in converted.columns:
        if pd.api.types.is_datetime64_any_dtype(converted[column]):
            converted[column] = converted[column].astype(str)
    return converted.to_dict(orient="records")


def _compact_json(payload: Any, max_chars: int = _MAX_EVIDENCE_CHARS) -> str:
    text = json.dumps(payload, default=str, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _latest_rows_by_period(rows: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: str(row.get("period_end", "")), reverse=True)
    return sorted_rows[:limit]


def _metric_snapshot(rows: list[dict[str, Any]], metrics: list[str], periods: int = 1) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("metric_type") in metrics]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in filtered:
        grouped.setdefault(str(row["metric_type"]), []).append(row)
    snapshot: list[dict[str, Any]] = []
    for metric_name in metrics:
        metric_rows = grouped.get(metric_name, [])
        snapshot.extend(_latest_rows_by_period(metric_rows, limit=periods))
    return snapshot


def _event_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    filing_dates = [str(row.get("filing_date", "")) for row in rows if row.get("filing_date")]
    if not filing_dates:
        return {
            "returned_events": len(rows),
            "earliest_filing_date": None,
            "latest_filing_date": None,
        }
    return {
        "returned_events": len(rows),
        "earliest_filing_date": min(filing_dates),
        "latest_filing_date": max(filing_dates),
    }


def _compact_material_event_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_rows: list[dict[str, Any]] = []
    for row in rows:
        compact_rows.append(
            {
                "accession_number": row.get("accession_number"),
                "filing_date": row.get("filing_date"),
                "date_of_report": row.get("date_of_report"),
                "item_code": row.get("item_code"),
                "content_type": row.get("content_type"),
                "summary": str(row.get("summary", "")).strip(),
            }
        )
    return compact_rows


def _parse_quarter_label(period_label: str) -> str | None:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", period_label)
    if not match:
        return None
    month, day, year = match.groups()
    return f"{year}-{month}-{day}"


def _quarterly_margin_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    quarter_columns = [
        column
        for column in rows[0].keys()
        if isinstance(column, str) and column.startswith("Quarter Ended ")
    ]
    if quarter_columns:
        metrics_by_period: dict[str, dict[str, float]] = {}
        labels_by_period: dict[str, str] = {}
        for row in rows:
            metric_type = str(row.get("metric_type", ""))
            if not metric_type:
                continue
            for period_label in quarter_columns:
                value = row.get(period_label)
                if value is None:
                    continue
                period_end = _parse_quarter_label(period_label) or period_label
                labels_by_period[period_end] = period_label
                metrics_by_period.setdefault(period_end, {})[metric_type] = float(value)

        margin_rows: list[dict[str, Any]] = []
        for period_end in sorted(metrics_by_period.keys(), reverse=True):
            metrics = metrics_by_period[period_end]
            revenue = metrics.get("revenue")
            if not revenue:
                continue
            row = {
                "period_end": period_end,
                "period_label": labels_by_period.get(period_end, period_end),
                "revenue": revenue,
            }
            gross_profit = metrics.get("gross_profit")
            operating_income = metrics.get("operating_income")
            net_income = metrics.get("net_income")
            if gross_profit is not None:
                row["gross_profit"] = gross_profit
                row["gross_margin"] = gross_profit / revenue
            if operating_income is not None:
                row["operating_income"] = operating_income
                row["operating_margin"] = operating_income / revenue
            if net_income is not None:
                row["net_income"] = net_income
                row["net_margin"] = net_income / revenue
            margin_rows.append(row)
        return margin_rows

    revenue_by_period: dict[str, float] = {}
    net_income_by_period: dict[str, float] = {}
    for row in rows:
        period_end = str(row.get("period_end", ""))
        metric_type = str(row.get("metric_type", ""))
        value = row.get("value")
        if value is None:
            continue
        if metric_type == "revenue":
            revenue_by_period[period_end] = float(value)
        elif metric_type == "net_income":
            net_income_by_period[period_end] = float(value)

    margin_rows: list[dict[str, Any]] = []
    for period_end in sorted(revenue_by_period.keys(), reverse=True):
        revenue = revenue_by_period[period_end]
        net_income = net_income_by_period.get(period_end)
        if not revenue or net_income is None:
            continue
        margin_rows.append(
            {
                "period_end": period_end,
                "revenue": revenue,
                "net_income": net_income,
                "net_margin": net_income / revenue,
            }
        )
    return margin_rows


def _extract_filing_excerpt(text: str, needle: str = "risk factors") -> str:
    if not text:
        return ""

    section_patterns = [
        r"(?im)^#+\s*item\s+1a\.?\s+risk factors\b",
        r"(?im)^item\s+1a\.?\s+risk factors\b",
        r"(?im)^item\s+1a\.?\b",
    ]
    for pattern in section_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        start = match.start()
        end = len(text)
        next_section_patterns = [
            r"(?im)^#+\s*item\s+1b\.?\b",
            r"(?im)^#+\s*item\s+1c\.?\b",
            r"(?im)^#+\s*item\s+2\.?\b",
            r"(?im)^item\s+1b\.?\b",
            r"(?im)^item\s+1c\.?\b",
            r"(?im)^item\s+2\.?\b",
        ]
        for end_pattern in next_section_patterns:
            end_match = re.search(end_pattern, text[start + 1 :])
            if end_match:
                end = min(end, start + 1 + end_match.start())
        return text[start:min(end, start + _MAX_FILING_EXCERPT_CHARS)]

    lower = text.lower()
    match = re.search(re.escape(needle), lower)
    if match:
        start = max(0, match.start() - 800)
        end = min(len(text), start + _MAX_FILING_EXCERPT_CHARS)
        return text[start:end]
    return text[:_MAX_FILING_EXCERPT_CHARS]


def build_evidence_bundle(question: ChatEvalQuestionLike) -> EvidenceBundle:
    """Build compact authoritative evidence for one question."""
    from investment_researcher.analytics import (
        cashflow_timeseries,
        get_filings_list,
        get_filing_text,
        get_insider_trades,
        get_institutional_holdings,
        get_material_events,
        get_proxy_statement_data,
        get_ratios_latest,
        get_ratios_ttm,
        growth_rates,
        latest_metric_for_all,
        metric_timeseries,
        quarterly_detail,
        ratio_timeseries,
        summarize_insider_sells,
        summarize_institutional_holdings,
        ttm_metrics,
    )

    params = dict(question.evidence_params)
    kind = question.evidence_kind

    if kind == "ttm_metrics":
        payload = ttm_metrics(params["ticker"], params["metrics"])
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "latest_ratios":
        ratios = get_ratios_latest(params["ticker"], params.get("period_type", "annual"))
        filtered = {
            ratio_name: ratios.get(ratio_name)
            for ratio_name in params.get("ratio_names", [])
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(filtered), payload=filtered)

    if kind == "cashflow_summary":
        rows = _df_records(
            cashflow_timeseries(
                params["ticker"],
                params.get("period_type", "annual"),
            )
        )
        payload = _metric_snapshot(
            rows,
            ["operating_cash_flow", "capex", "free_cash_flow"],
            periods=1,
        )
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "material_events":
        rows = get_material_events(
            params["ticker"],
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            item_codes=params.get("item_codes"),
            limit=params.get("limit", 10),
        )
        payload = {
            "coverage": {
                "requested_start_date": params.get("start_date"),
                "requested_end_date": params.get("end_date"),
                **_event_coverage(rows),
            },
            "events": _compact_material_event_rows(rows),
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "proxy_statement":
        payload = get_proxy_statement_data(
            params["ticker"],
            start_date=params.get("proxy_start_date", params.get("start_date")),
            end_date=params.get("proxy_end_date", params.get("end_date")),
            limit=params.get("limit", 2),
        )
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "institutional_holdings_summary":
        payload = summarize_institutional_holdings(
            params["manager"],
            report_period=params.get("report_period"),
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            top_n=params.get("top_n", 10),
            min_value=params.get("min_value", 0.0),
        )
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "growth_and_ratio_trend":
        growth_rows = _df_records(
            growth_rates(
                params["ticker"],
                params["metrics"],
                params.get("period_type", "annual"),
            )
        )
        ratio_rows = _df_records(
            ratio_timeseries(
                params["ticker"],
                params.get("ratio_names"),
                params.get("period_type", "annual"),
            )
        )
        payload = {
            "growth_rows": _latest_rows_by_period(growth_rows, limit=4),
            "ratio_rows": _latest_rows_by_period(ratio_rows, limit=4),
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "quarterly_and_ttm":
        quarterly_metrics = list(params.get("quarterly_metrics", []))
        if "net_income" not in quarterly_metrics:
            quarterly_metrics.append("net_income")
        quarterly_rows = _df_records(
            quarterly_detail(
                params["ticker"],
                quarterly_metrics,
                params.get("n_quarters", 8),
            )
        )
        quarterly_ratio_names = list(params.get("quarterly_ratio_names", []))
        annual_ratio_names = list(params.get("annual_ratio_names", []))
        quarterly_ratio_rows = []
        annual_ratio_rows = []
        if quarterly_ratio_names:
            quarterly_ratio_rows = _latest_rows_by_period(
                _df_records(
                    ratio_timeseries(
                        params["ticker"],
                        quarterly_ratio_names,
                        "quarterly",
                    )
                ),
                limit=params.get("n_quarters", 8) * len(quarterly_ratio_names),
            )
        if annual_ratio_names:
            annual_ratio_rows = _latest_rows_by_period(
                _df_records(
                    ratio_timeseries(
                        params["ticker"],
                        annual_ratio_names,
                        "annual",
                    )
                ),
                limit=params.get("annual_periods", 4) * len(annual_ratio_names),
            )
        payload = {
            "quarterly_rows": _latest_rows_by_period(quarterly_rows, limit=params.get("n_quarters", 8) * len(quarterly_metrics)),
            "quarterly_margins": _quarterly_margin_rows(quarterly_rows)[: params.get("n_quarters", 8)],
            "quarterly_ratio_rows": quarterly_ratio_rows,
            "annual_ratio_rows": annual_ratio_rows,
            "ttm_metrics": ttm_metrics(params["ticker"], params.get("ttm_metrics", [])),
            "ttm_ratios": {
                ratio_name: get_ratios_ttm(params["ticker"]).get(ratio_name)
                for ratio_name in params.get("ttm_ratio_names", [])
            },
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "insider_and_proxy":
        sells = summarize_insider_sells(
            ticker=params["ticker"],
            start_date=params["start_date"],
            end_date=params.get("end_date") or date.today().isoformat(),
            transaction_codes=params.get("transaction_codes"),
            min_value=params.get("min_value", 0.0),
            group_by=params.get("group_by", "insider_name"),
            limit=params.get("limit", 25),
            include_amendments=params.get("include_amendments", False),
        )
        proxy_rows = get_proxy_statement_data(
            params["ticker"],
            limit=params.get("proxy_limit", 1),
        )
        payload = {"insider_sells": sells, "proxy_rows": proxy_rows}
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "latest_filing_text":
        filings = get_filings_list(
            params["ticker"],
            form_type=params.get("form_type"),
            limit=params.get("limit", 1),
        )
        if not filings:
            return EvidenceBundle(kind=kind, summary="[]", payload=[])
        latest_filing = filings[0]
        filing_text = get_filing_text(params["ticker"], latest_filing["accession_number"])
        payload = {
            "filing": latest_filing,
            "excerpt": _extract_filing_excerpt(filing_text),
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "events_and_cashflow":
        events = get_material_events(
            params["ticker"],
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            limit=params.get("events_limit", 10),
        )
        cashflow_rows = _df_records(
            cashflow_timeseries(
                params["ticker"],
                params.get("period_type", "annual"),
            )
        )
        payload = {
            "events": events,
            "cashflow": _metric_snapshot(cashflow_rows, ["free_cash_flow", "capex"], periods=1),
        }
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "cross_company_metric":
        metric_name = params["metric_type"]
        period_type = params.get("period_type", "annual")
        payload = []
        for ticker in params.get("tickers", []):
            if metric_name == "free_cash_flow":
                ticker_rows = _df_records(cashflow_timeseries(ticker, period_type))
            else:
                ticker_rows = _df_records(metric_timeseries(ticker, [metric_name], period_type))
            latest_rows = _metric_snapshot(ticker_rows, [metric_name], periods=1)
            if not latest_rows:
                continue
            latest = latest_rows[0]
            payload.append(
                {
                    "ticker": ticker,
                    "metric_type": metric_name,
                    "value": latest.get("value"),
                    "period_end": latest.get("period_end"),
                }
            )
        payload.sort(key=lambda row: float(row.get("value") or 0.0), reverse=True)
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "insider_trades":
        payload = get_insider_trades(
            ticker=params["ticker"],
            start_date=params["start_date"],
            end_date=params["end_date"],
            transaction_codes=params.get("transaction_codes"),
            acquired_disposed=params.get("acquired_disposed", "D"),
            limit=params.get("limit", 100),
        )
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    if kind == "institutional_holdings":
        payload = get_institutional_holdings(
            manager=params["manager"],
            report_period=params.get("report_period"),
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            limit=params.get("limit", 100),
        )
        return EvidenceBundle(kind=kind, summary=_compact_json(payload), payload=payload)

    raise ValueError(f"Unsupported evidence kind: {kind}")


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text:
        raise ValueError("empty evaluator response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _coerce_text_field(value: Any, default: str) -> str:
    """Normalize nullable evaluator scalar fields to plain strings."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _coerce_text_list(value: Any) -> list[str]:
    """Normalize nullable or scalar evaluator list fields to string lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


async def evaluate_answer(
    question: ChatEvalQuestionLike,
    answer: str,
    evidence: EvidenceBundle,
) -> EvaluationVerdict:
    """Judge whether the answer is faithful to the supplied evidence."""
    started = time.perf_counter()
    client = _build_eval_client()
    _, _, llm_model = _get_llm_config()
    system_prompt = (
        "You are a strict financial QA judge. Evaluate the assistant answer only "
        "against the supplied authoritative evidence. Do not reward style. Fail "
        "answers that invent facts, overstate what the evidence supports, or omit "
        "key requested facts. If the evidence is insufficient, mark the result as fail. "
        "Return JSON only."
    )
    user_prompt = (
        "Evaluate the assistant answer for faithfulness and factual grounding.\n\n"
        "Return a JSON object with exactly these keys:\n"
        "overall, faithfulness, factual_grounding, completeness, reason, "
        "pass_reasons, fail_reasons, unsupported_claims, missing_key_facts, ambiguity_notes.\n\n"
        f"Question ID: {question.question_id}\n"
        f"Question: {question.prompt}\n"
        f"Expected tools: {', '.join(question.expected_tools)}\n"
        f"Must cover: {', '.join(question.must_cover) or 'none'}\n\n"
        f"Assistant answer:\n{answer}\n\n"
        f"Authoritative evidence ({evidence.kind}):\n{evidence.summary}\n"
    )
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=llm_model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            timeout=question.evaluation_timeout_seconds,
        )
    except asyncio.TimeoutError:
        return EvaluationVerdict(
            status="evaluation_timeout",
            duration_seconds=time.perf_counter() - started,
            reason=(
                f"evaluation timed out after {question.evaluation_timeout_seconds} seconds"
            ),
            fail_reasons=[
                f"evaluation timed out after {question.evaluation_timeout_seconds} seconds"
            ],
            error="timeout",
        )
    except Exception as exc:
        return EvaluationVerdict(
            status="evaluation_error",
            duration_seconds=time.perf_counter() - started,
            reason=f"evaluation failed: {exc}",
            fail_reasons=[f"evaluation failed: {exc}"],
            error=str(exc),
        )

    raw_text = response.choices[0].message.content or ""
    try:
        parsed = _extract_json_object(raw_text)
    except Exception as exc:
        return EvaluationVerdict(
            status="evaluation_error",
            duration_seconds=time.perf_counter() - started,
            reason=f"could not parse evaluator JSON: {exc}",
            fail_reasons=[f"could not parse evaluator JSON: {exc}"],
            raw_response=raw_text,
            error=str(exc),
        )

    return EvaluationVerdict(
        status="ok",
        duration_seconds=time.perf_counter() - started,
        overall=_coerce_text_field(parsed.get("overall"), "fail"),
        faithfulness=_coerce_text_field(parsed.get("faithfulness"), "fail"),
        factual_grounding=_coerce_text_field(parsed.get("factual_grounding"), "fail"),
        completeness=_coerce_text_field(parsed.get("completeness"), "fail"),
        reason=_coerce_text_field(parsed.get("reason"), ""),
        pass_reasons=_coerce_text_list(parsed.get("pass_reasons")),
        fail_reasons=_coerce_text_list(parsed.get("fail_reasons")),
        unsupported_claims=_coerce_text_list(parsed.get("unsupported_claims")),
        missing_key_facts=_coerce_text_list(parsed.get("missing_key_facts")),
        ambiguity_notes=_coerce_text_list(parsed.get("ambiguity_notes")),
        raw_response=raw_text,
    )


async def evaluate_question(app: Any, question: ChatEvalQuestionLike) -> ChatEvaluationResult:
    """Run chat plus evaluation for a single question."""
    started_at = datetime.now(timezone.utc).isoformat()

    evidence_error: str | None = None
    try:
        evidence = await asyncio.wait_for(
            asyncio.to_thread(build_evidence_bundle, question),
            timeout=_EVIDENCE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        evidence = EvidenceBundle(kind=question.evidence_kind, summary="[]", payload=[])
        evidence_error = (
            f"evidence collection timed out after {_EVIDENCE_TIMEOUT_SECONDS} seconds"
        )
    except Exception as exc:
        evidence = EvidenceBundle(kind=question.evidence_kind, summary="[]", payload=[])
        evidence_error = f"evidence collection failed: {exc}"

    chat = await run_chat_case(app, question)
    if evidence_error:
        evaluation = EvaluationVerdict(
            status="evidence_error",
            duration_seconds=0.0,
            overall="fail",
            faithfulness="fail",
            factual_grounding="fail",
            completeness="fail",
            reason=evidence_error,
            fail_reasons=[evidence_error],
        )
    elif chat.status != "ok":
        evaluation = EvaluationVerdict(
            status=chat.status,
            duration_seconds=0.0,
            overall="fail",
            faithfulness="fail",
            factual_grounding="fail",
            completeness="fail",
            reason=chat.error or chat.status,
            fail_reasons=[chat.error or chat.status],
        )
    else:
        evaluation = await evaluate_answer(question, chat.answer, evidence)

    return ChatEvaluationResult(
        question_id=question.question_id,
        title=question.title,
        ticker=question.ticker,
        difficulty=question.difficulty,
        prompt=question.prompt,
        expected_tools=list(question.expected_tools),
        must_cover=list(question.must_cover),
        smoke=question.smoke,
        notes=question.notes,
        started_at=started_at,
        evidence_kind=evidence.kind,
        evidence_summary=evidence.summary,
        evidence_payload=evidence.payload,
        chat=chat,
        evaluation=evaluation,
    )


def build_markdown_summary(results: list[ChatEvaluationResult]) -> str:
    """Render a human-readable markdown report."""
    lines = [
        "# Live Chat Evaluation Report",
        "",
        f"Generated at {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Question | Chat | Eval | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        reason = result.evaluation.reason.replace("|", "/")
        lines.append(
            "| "
            f"{result.question_id} | {result.chat.status} | {result.evaluation.overall} | {reason} |"
        )

    lines.append("")
    for result in results:
        lines.extend(
            [
                f"## {result.question_id}",
                "",
                f"- Title: {result.title}",
                f"- Ticker: {result.ticker or 'n/a'}",
                f"- Difficulty: {result.difficulty}",
                f"- Chat status: {result.chat.status}",
                f"- Chat session id: {result.chat.session_id or 'n/a'}",
                f"- Chat duration: {result.chat.duration_seconds:.2f}s",
                f"- Evaluation status: {result.evaluation.status}",
                f"- Evaluation duration: {result.evaluation.duration_seconds:.2f}s",
                f"- Overall verdict: {result.evaluation.overall}",
                f"- Reason: {result.evaluation.reason}",
                f"- Expected tools: {', '.join(result.expected_tools)}",
                f"- Must cover: {', '.join(result.must_cover) or 'none'}",
                "",
                "### Prompt",
                "",
                result.prompt,
                "",
                "### Answer",
                "",
                result.chat.answer or "[no answer]",
                "",
                "### Progress",
                "",
                ", ".join(result.chat.progress_messages) or "[none]",
                "",
                "### Pass Reasons",
                "",
                *(result.evaluation.pass_reasons or ["- none"]),
                "",
                "### Fail Reasons",
                "",
                *(result.evaluation.fail_reasons or ["- none"]),
                "",
                "### Unsupported Claims",
                "",
                *(result.evaluation.unsupported_claims or ["- none"]),
                "",
                "### Missing Key Facts",
                "",
                *(result.evaluation.missing_key_facts or ["- none"]),
                "",
            ]
        )
    return "\n".join(lines)


def write_run_artifacts(output_dir: Path, results: list[ChatEvaluationResult]) -> dict[str, Path]:
    """Write JSONL, JSON, and markdown artifacts for a run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "results.jsonl"
    json_path = output_dir / "results.json"
    md_path = output_dir / "report.md"

    serializable = [result.to_dict() for result in results]
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in serializable:
            handle.write(json.dumps(row, default=str) + "\n")

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(serializable, handle, default=str, indent=2)

    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(build_markdown_summary(results))

    return {
        "jsonl": jsonl_path,
        "json": json_path,
        "markdown": md_path,
    }