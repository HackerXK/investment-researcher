"""Shared SEC filing extraction helpers for analytics and agent tools."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from numbers import Number
import re
from typing import Any, Iterable

import pandas as pd

_FORM4_CODE_DESCRIPTIONS = {
    "P": "Open Market Purchase",
    "S": "Open Market Sale",
    "A": "Grant/Award",
    "M": "Option Exercise",
    "F": "Tax Withholding",
    "G": "Gift",
    "X": "Option Exercise",
    "D": "Disposition to Issuer",
    "C": "Conversion",
    "E": "Expiration of Short Position",
    "H": "Expiration of Long Position",
    "I": "Discretionary Transaction",
    "O": "Exercise of Out-of-Money Derivative",
    "U": "Disposition (Tender of Shares)",
    "Z": "Deposit/Withdrawal (Voting Trust)",
}

_NOTABLE_TRADE_VALUE = 100_000.0
_VERY_NOTABLE_TRADE_VALUE = 1_000_000.0
_DEFAULT_EVENT_SUMMARY_CHARS = 2_000
_ITEM_SECTION_HEADING_RE = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?P<heading>item\s+(?P<item_code>\d+(?:\.\d+)?[a-z]?)\.?"
    r"(?:\s+(?P<title>[^\n]+?))?)\s*$"
)


def build_filing_date_filter(
    start_date: str | None,
    end_date: str | None,
) -> str | None:
    """Build an edgartools-compatible filing date filter."""
    start_date = _normalize_optional_date_input(start_date)
    end_date = _normalize_optional_date_input(end_date)
    if start_date and end_date:
        return f"{start_date}:{end_date}"
    if start_date:
        return f"{start_date}:"
    if end_date:
        return f":{end_date}"
    return None


def _normalize_optional_date_input(value: Any) -> str | None:
    """Treat empty sentinels from tool calls as missing dates."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def normalize_number(value: Any) -> int | float | None:
    """Convert numeric-like values to JSON-safe numbers."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, Number):
        numeric = float(value)
        if pd.isna(numeric):
            return None
        return int(numeric) if numeric.is_integer() else numeric
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return int(numeric) if numeric.is_integer() else numeric


def classify_trade_significance(value: Any) -> str:
    """Bucket a trade's value for quick screening."""
    numeric = normalize_number(value)
    magnitude = abs(float(numeric)) if numeric is not None else 0.0
    if magnitude < _NOTABLE_TRADE_VALUE:
        return "Normal"
    if magnitude < _VERY_NOTABLE_TRADE_VALUE:
        return "Notable"
    return "Very notable"


def normalize_scalar(value: Any) -> Any:
    """Normalize mixed scalar values for JSON-serializable dict output."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return normalize_number(value)
    if isinstance(value, Number):
        return normalize_number(value)
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return value


def dataframe_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Convert a DataFrame to normalized record dicts."""
    if df is None or df.empty:
        return []

    records: list[dict[str, Any]] = []
    for record in df.to_dict(orient="records"):
        records.append({key: normalize_scalar(value) for key, value in record.items()})
    return records


def text_excerpt(text: Any, max_chars: int = _DEFAULT_EVENT_SUMMARY_CHARS) -> str | None:
    """Collapse whitespace and return a bounded excerpt."""
    if text is None:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    if not normalized:
        return None
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(max_chars - 3, 1)].rstrip() + "..."


def normalize_item_code(item_name: str | None) -> str | None:
    """Normalize a filing item label like 'Item 5.02' to '5.02'."""
    if not item_name:
        return None
    cleaned = re.sub(r"\s*\.\s*", ".", str(item_name)).strip()
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return match.group(1) if match else None


def normalize_item_label(item_code: str | None) -> str | None:
    if not item_code:
        return None
    return f"Item {item_code}"


def unique_nonempty(values: Iterable[Any]) -> list[Any]:
    """Return unique non-empty values preserving first-seen order."""
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in (None, "", []):
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize_section_key(value: Any) -> str | None:
    """Normalize a section selector or title into a compact lookup key."""
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())
    return normalized or None


def _normalize_section_item_code(value: str | None) -> str | None:
    """Normalize a filing item code to a stable uppercase representation."""
    if not value:
        return None
    normalized = re.sub(r"[^0-9a-z.]+", "", str(value).strip().lower())
    return normalized.upper() or None


def _normalize_section_title(value: str | None) -> str | None:
    """Normalize an extracted section title for display and matching."""
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value).strip(" .:-")
    normalized = re.sub(r"\s+\d+$", "", normalized).strip()
    return normalized or None


def _parse_filing_item_sections(text: str) -> list[dict[str, Any]]:
    """Parse item-based SEC sections from filing markdown.

    When the same item heading appears multiple times, keep the last occurrence.
    This avoids locking onto table-of-contents matches instead of the actual
    section body.
    """
    if not text:
        return []

    raw_sections: list[dict[str, Any]] = []
    for match in _ITEM_SECTION_HEADING_RE.finditer(text):
        heading = re.sub(r"\s+", " ", match.group("heading")).strip()
        item_code = _normalize_section_item_code(match.group("item_code"))
        if not item_code:
            continue
        title = _normalize_section_title(match.group("title"))
        raw_sections.append(
            {
                "heading": heading,
                "item_code": item_code,
                "item_key": _normalize_section_key(item_code),
                "title": title,
                "title_key": _normalize_section_key(title),
                "start": match.start(),
                "heading_end": match.end(),
                "line_number": text.count("\n", 0, match.start()) + 1,
            }
        )

    if not raw_sections:
        return []

    last_index_by_code = {
        section["item_key"]: index
        for index, section in enumerate(raw_sections)
    }
    sections = [
        section.copy()
        for index, section in enumerate(raw_sections)
        if last_index_by_code[section["item_key"]] == index
    ]

    for index, section in enumerate(sections):
        end = sections[index + 1]["start"] if index + 1 < len(sections) else len(text)
        content = text[section["start"]:end].strip()
        body = text[section["heading_end"]:end].strip()
        match_keys = {
            section["item_key"],
            _normalize_section_key(f"item {section['item_code']}"),
            _normalize_section_key(section["heading"]),
        }
        if section["title_key"]:
            match_keys.add(section["title_key"])

        section["content"] = content
        section["body"] = body
        section["text_length"] = len(content)
        section["match_keys"] = {key for key in match_keys if key}

    return sections


def _section_selector_matches(section: dict[str, Any], selector_key: str) -> bool:
    """Return whether a normalized selector targets the parsed filing section."""
    if selector_key in section.get("match_keys", set()):
        return True

    title_key = section.get("title_key") or ""
    if selector_key == "mda" and "management" in title_key and "discussion" in title_key:
        return True

    return False


def list_filing_item_sections(text: str) -> list[dict[str, Any]]:
    """Return the item-based sections discovered in filing markdown."""
    sections = _parse_filing_item_sections(text)
    return [
        {
            "item_code": section["item_code"],
            "heading": section["heading"],
            "title": section["title"],
            "line_number": section["line_number"],
            "text_length": section["text_length"],
            "preview": text_excerpt(section["body"] or section["content"], 280),
        }
        for section in sections
    ]


def extract_filing_item_section(text: str, section_name: str) -> dict[str, Any] | None:
    """Return one parsed filing section matched by item code or section title."""
    selector_key = _normalize_section_key(section_name)
    if not selector_key:
        return None

    for section in _parse_filing_item_sections(text):
        if _section_selector_matches(section, selector_key):
            return {
                "item_code": section["item_code"],
                "heading": section["heading"],
                "title": section["title"],
                "line_number": section["line_number"],
                "text_length": section["text_length"],
                "content": section["content"],
            }
    return None


def _build_filing_search_pattern(query: str) -> re.Pattern[str] | None:
    """Build a whitespace-tolerant case-insensitive search pattern."""
    tokens = [re.escape(token) for token in str(query).strip().split() if token]
    if not tokens:
        return None
    return re.compile(r"\s+".join(tokens), re.IGNORECASE)


def _excerpt_around_match(text: str, match: re.Match[str], context_chars: int) -> str:
    """Return a bounded excerpt around a filing-text match."""
    start = max(match.start() - context_chars, 0)
    end = min(match.end() + context_chars, len(text))
    excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
    if start > 0 and excerpt:
        excerpt = "..." + excerpt
    if end < len(text) and excerpt:
        excerpt = excerpt + "..."
    return excerpt


def search_filing_text_matches(
    text: str,
    query: str,
    section_name: str | None = None,
    max_matches: int = 5,
    context_chars: int = 280,
) -> list[dict[str, Any]]:
    """Search filing text and return compact evidence excerpts.

    When item sections can be parsed, search runs over those parsed section bodies
    instead of the raw filing so table-of-contents hits do not crowd out the real
    section body.
    """
    pattern = _build_filing_search_pattern(query)
    if not pattern or max_matches <= 0:
        return []

    parsed_sections = _parse_filing_item_sections(text)
    search_sources: list[dict[str, Any]]
    if section_name:
        selector_key = _normalize_section_key(section_name)
        if not selector_key:
            return []
        search_sources = [
            section
            for section in parsed_sections
            if _section_selector_matches(section, selector_key)
        ]
    elif parsed_sections:
        search_sources = parsed_sections
    else:
        search_sources = [
            {
                "item_code": None,
                "heading": None,
                "title": None,
                "line_number": 1,
                "content": text,
            }
        ]

    results: list[dict[str, Any]] = []
    context_chars = max(context_chars, 0)

    for source in search_sources:
        content = str(source.get("content") or "")
        if not content:
            continue
        for match in pattern.finditer(content):
            line_number = int(source.get("line_number") or 1) + content.count(
                "\n", 0, match.start()
            )
            results.append(
                {
                    "query": str(query).strip(),
                    "matched_text": re.sub(r"\s+", " ", match.group(0)).strip(),
                    "excerpt": _excerpt_around_match(content, match, context_chars),
                    "line_number": line_number,
                    "item_code": source.get("item_code"),
                    "heading": source.get("heading"),
                    "title": source.get("title"),
                }
            )
            if len(results) >= max_matches:
                return results

    return results


def extract_form4_trades(
    filing: Any,
    transaction_codes: list[str] | None = None,
    acquired_disposed: str | None = "D",
    min_value: float = 0.0,
) -> list[dict[str, Any]]:
    """Extract normalized Form 4 non-derivative transaction rows from a filing."""
    form4 = filing.obj()
    if form4 is None:
        return []

    tx_df = getattr(
        getattr(getattr(form4, "non_derivative_table", None), "transactions", None),
        "data",
        None,
    )
    if tx_df is None or tx_df.empty:
        return []

    normalized_codes = (
        {code.strip().upper() for code in transaction_codes if code and code.strip()}
        if transaction_codes
        else None
    )
    normalized_acquired_disposed = acquired_disposed.upper() if acquired_disposed else None

    filtered = tx_df.copy()
    if normalized_acquired_disposed and "AcquiredDisposed" in filtered.columns:
        filtered = filtered[
            filtered["AcquiredDisposed"].astype(str).str.upper() == normalized_acquired_disposed
        ]
    if normalized_codes and "Code" in filtered.columns:
        filtered = filtered[filtered["Code"].astype(str).str.upper().isin(normalized_codes)]
    if filtered.empty:
        return []

    summary = form4.get_ownership_summary() if hasattr(form4, "get_ownership_summary") else None
    trades: list[dict[str, Any]] = []
    for row in filtered.itertuples(index=False):
        shares = normalize_number(getattr(row, "Shares", None))
        price = normalize_number(getattr(row, "Price", None))
        value = (
            normalize_number(float(shares) * float(price))
            if shares is not None and price is not None
            else None
        )
        if value is not None and abs(float(value)) < min_value:
            continue

        code = str(getattr(row, "Code", "") or "")
        acquired_disposed_code = str(getattr(row, "AcquiredDisposed", "") or "")
        trades.append(
            {
                "accession_number": getattr(filing, "accession_no", None),
                "filing_date": str(getattr(filing, "filing_date", "") or ""),
                "tx_date": str(getattr(row, "Date", "") or ""),
                "insider_name": getattr(summary, "insider_name", None),
                "position": getattr(summary, "position", None),
                "transaction_code": code,
                "transaction_type": str(getattr(row, "TransactionType", "") or ""),
                "code_description": _FORM4_CODE_DESCRIPTIONS.get(
                    code,
                    f"Other ({code})" if code else "Other",
                ),
                "acquired_disposed": acquired_disposed_code,
                "shares": shares,
                "price": price,
                "proceeds": value if acquired_disposed_code == "D" else None,
                "value": value,
                "remaining_shares": normalize_number(getattr(row, "Remaining", None)),
                "security": getattr(row, "Security", None),
                "is_direct": getattr(row, "DirectIndirect", None) == "D",
                "ownership_nature": getattr(row, "NatureOfOwnership", None),
                "primary_activity": getattr(summary, "primary_activity", None),
                "classification": classify_trade_significance(value),
                "is_tax_withholding": code == "F",
            }
        )

    trades.sort(
        key=lambda trade: (
            float(trade["proceeds"] or trade["value"] or 0.0),
            str(trade["tx_date"] or trade["filing_date"] or ""),
            str(trade["accession_number"] or ""),
        ),
        reverse=True,
    )
    return trades


def summarize_insider_sales_rows(
    trades: list[dict[str, Any]],
    group_by: str = "insider_name",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Aggregate Form 4 sale rows into grouped insider-sale summaries."""
    group_fields_by_name = {
        "insider_name": ("insider_name", "position", "primary_activity"),
        "insider_name_and_code": (
            "insider_name",
            "position",
            "primary_activity",
            "transaction_code",
            "code_description",
        ),
        "transaction_code": ("transaction_code", "code_description"),
    }
    if group_by not in group_fields_by_name:
        raise ValueError(
            "group_by must be one of insider_name, insider_name_and_code, transaction_code"
        )

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    group_fields = group_fields_by_name[group_by]
    for trade in trades:
        key = tuple(trade.get(field) for field in group_fields)
        groups[key].append(trade)

    summaries: list[dict[str, Any]] = []
    for key, grouped_trades in groups.items():
        total_proceeds = sum(float(trade.get("proceeds") or trade.get("value") or 0.0) for trade in grouped_trades)
        total_shares = sum(float(trade.get("shares") or 0.0) for trade in grouped_trades)
        sorted_group = sorted(
            grouped_trades,
            key=lambda trade: (
                str(trade.get("tx_date") or trade.get("filing_date") or ""),
                str(trade.get("accession_number") or ""),
            ),
            reverse=True,
        )
        summary: dict[str, Any] = {
            field: value for field, value in zip(group_fields, key, strict=False)
        }
        summary.update(
            {
                "transaction_count": len(grouped_trades),
                "transaction_codes": unique_nonempty(
                    trade.get("transaction_code") for trade in grouped_trades
                ),
                "accession_numbers": unique_nonempty(
                    trade.get("accession_number") for trade in sorted_group
                ),
                "first_tx_date": min(
                    unique_nonempty(trade.get("tx_date") for trade in grouped_trades),
                    default=None,
                ),
                "last_tx_date": max(
                    unique_nonempty(trade.get("tx_date") for trade in grouped_trades),
                    default=None,
                ),
                "latest_filing_date": max(
                    unique_nonempty(trade.get("filing_date") for trade in grouped_trades),
                    default=None,
                ),
                "latest_accession_number": sorted_group[0].get("accession_number") if sorted_group else None,
                "total_shares": normalize_number(total_shares),
                "total_proceeds": normalize_number(total_proceeds),
                "average_price": normalize_number(total_proceeds / total_shares) if total_shares else None,
                "max_trade_value": normalize_number(
                    max(float(trade.get("proceeds") or trade.get("value") or 0.0) for trade in grouped_trades)
                ),
                "classification": classify_trade_significance(total_proceeds),
            }
        )
        summaries.append(summary)

    summaries.sort(
        key=lambda summary: (
            float(summary.get("total_proceeds") or 0.0),
            str(summary.get("last_tx_date") or summary.get("latest_filing_date") or ""),
        ),
        reverse=True,
    )
    return summaries[:limit]


def extract_material_events(
    filing: Any,
    item_codes: list[str] | None = None,
    summary_chars: int = _DEFAULT_EVENT_SUMMARY_CHARS,
) -> list[dict[str, Any]]:
    """Extract normalized 8-K item/event rows from a filing."""
    report = filing.obj()
    if report is None:
        return []

    target_codes = (
        {code for code in (normalize_item_code(item_code) for item_code in item_codes) if code}
        if item_codes
        else None
    )

    events: list[dict[str, Any]] = []
    for item_name in list(getattr(report, "items", []) or []):
        item_code = normalize_item_code(item_name)
        if target_codes and item_code not in target_codes:
            continue

        item_text = None
        for lookup in unique_nonempty([item_name, item_code]):
            try:
                item_text = report[lookup]
                if item_text:
                    break
            except Exception:
                continue

        press_releases = getattr(report, "press_releases", None)
        events.append(
            {
                "accession_number": getattr(filing, "accession_no", None),
                "form_type": getattr(filing, "form", None),
                "filing_date": str(getattr(filing, "filing_date", "") or ""),
                "date_of_report": str(getattr(report, "date_of_report", "") or ""),
                "item": item_name,
                "item_code": item_code,
                "item_label": normalize_item_label(item_code) or item_name,
                "content_type": getattr(report, "content_type", None),
                "summary": text_excerpt(item_text, summary_chars),
                "text_length": len(str(item_text)) if item_text else 0,
                "has_press_release": bool(press_releases),
            }
        )

    events.sort(
        key=lambda event: (
            str(event.get("filing_date") or ""),
            str(event.get("date_of_report") or ""),
            str(event.get("item_code") or ""),
        ),
        reverse=True,
    )
    return events


def summarize_material_event_rows(
    events: list[dict[str, Any]],
    group_by: str = "item_code",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Aggregate 8-K event rows into grouped summaries."""
    group_fields_by_name = {
        "item_code": ("item_code", "item_label"),
        "content_type": ("content_type",),
    }
    if group_by not in group_fields_by_name:
        raise ValueError("group_by must be one of item_code, content_type")

    group_fields = group_fields_by_name[group_by]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[tuple(event.get(field) for field in group_fields)].append(event)

    summaries: list[dict[str, Any]] = []
    for key, grouped_events in groups.items():
        sorted_group = sorted(
            grouped_events,
            key=lambda event: (
                str(event.get("filing_date") or ""),
                str(event.get("date_of_report") or ""),
                str(event.get("accession_number") or ""),
            ),
            reverse=True,
        )
        summary: dict[str, Any] = {
            field: value for field, value in zip(group_fields, key, strict=False)
        }
        summary.update(
            {
                "event_count": len(grouped_events),
                "accession_numbers": unique_nonempty(
                    event.get("accession_number") for event in sorted_group
                ),
                "latest_filing_date": max(
                    unique_nonempty(event.get("filing_date") for event in grouped_events),
                    default=None,
                ),
                "latest_date_of_report": max(
                    unique_nonempty(event.get("date_of_report") for event in grouped_events),
                    default=None,
                ),
                "content_types": unique_nonempty(
                    event.get("content_type") for event in sorted_group
                ),
                "sample_summaries": unique_nonempty(
                    event.get("summary") for event in sorted_group
                )[:3],
                "has_press_release": any(bool(event.get("has_press_release")) for event in grouped_events),
            }
        )
        summaries.append(summary)

    summaries.sort(
        key=lambda summary: (
            int(summary.get("event_count") or 0),
            str(summary.get("latest_filing_date") or ""),
        ),
        reverse=True,
    )
    return summaries[:limit]


def extract_proxy_statement_record(filing: Any) -> dict[str, Any] | None:
    """Extract a normalized DEF 14A snapshot from a filing."""
    proxy = filing.obj()
    if proxy is None:
        return None

    return {
        "accession_number": getattr(filing, "accession_no", None),
        "form_type": getattr(filing, "form", None),
        "filing_date": str(getattr(filing, "filing_date", "") or ""),
        "company_name": getattr(proxy, "company_name", None),
        "cik": getattr(proxy, "cik", None),
        "fiscal_year_end": normalize_scalar(getattr(proxy, "fiscal_year_end", None)),
        "peo_name": getattr(proxy, "peo_name", None),
        "peo_total_comp": normalize_scalar(getattr(proxy, "peo_total_comp", None)),
        "peo_actually_paid_comp": normalize_scalar(getattr(proxy, "peo_actually_paid_comp", None)),
        "neo_avg_total_comp": normalize_scalar(getattr(proxy, "neo_avg_total_comp", None)),
        "neo_avg_actually_paid_comp": normalize_scalar(getattr(proxy, "neo_avg_actually_paid_comp", None)),
        "total_shareholder_return": normalize_scalar(getattr(proxy, "total_shareholder_return", None)),
        "peer_group_tsr": normalize_scalar(getattr(proxy, "peer_group_tsr", None)),
        "net_income": normalize_scalar(getattr(proxy, "net_income", None)),
        "company_selected_measure": getattr(proxy, "company_selected_measure", None),
        "company_selected_measure_value": normalize_scalar(
            getattr(proxy, "company_selected_measure_value", None)
        ),
        "performance_measures": list(getattr(proxy, "performance_measures", []) or []),
        "insider_trading_policy_adopted": getattr(
            proxy, "insider_trading_policy_adopted", None
        ),
        "has_xbrl": bool(getattr(proxy, "has_xbrl", False)),
        "executive_compensation": dataframe_records(
            getattr(proxy, "executive_compensation", None)
        ),
        "pay_vs_performance": dataframe_records(getattr(proxy, "pay_vs_performance", None)),
    }


def summarize_proxy_statement_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize one or more proxy statement snapshots."""
    if not rows:
        return {}

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("fiscal_year_end") or ""),
            str(row.get("filing_date") or ""),
            str(row.get("accession_number") or ""),
        ),
        reverse=True,
    )
    latest = sorted_rows[0]
    previous = sorted_rows[1] if len(sorted_rows) > 1 else None

    latest_comp = normalize_number(latest.get("peo_total_comp"))
    previous_comp = normalize_number(previous.get("peo_total_comp")) if previous else None
    comp_change = (
        normalize_number(float(latest_comp) - float(previous_comp))
        if latest_comp is not None and previous_comp is not None
        else None
    )
    comp_change_pct = (
        normalize_number((float(latest_comp) - float(previous_comp)) / float(previous_comp) * 100.0)
        if latest_comp is not None and previous_comp not in (None, 0)
        else None
    )

    compensation_history = [
        {
            "filing_date": row.get("filing_date"),
            "fiscal_year_end": row.get("fiscal_year_end"),
            "peo_name": row.get("peo_name"),
            "peo_total_comp": row.get("peo_total_comp"),
            "peo_actually_paid_comp": row.get("peo_actually_paid_comp"),
            "neo_avg_total_comp": row.get("neo_avg_total_comp"),
            "neo_avg_actually_paid_comp": row.get("neo_avg_actually_paid_comp"),
        }
        for row in sorted(
            rows,
            key=lambda row: (
                str(row.get("fiscal_year_end") or ""),
                str(row.get("filing_date") or ""),
            ),
        )
    ]

    return {
        "company_name": latest.get("company_name"),
        "cik": latest.get("cik"),
        "filings_count": len(rows),
        "latest_accession_number": latest.get("accession_number"),
        "latest_form_type": latest.get("form_type"),
        "latest_filing_date": latest.get("filing_date"),
        "latest_fiscal_year_end": latest.get("fiscal_year_end"),
        "latest_peo_name": latest.get("peo_name"),
        "latest_peo_total_comp": latest.get("peo_total_comp"),
        "latest_peo_actually_paid_comp": latest.get("peo_actually_paid_comp"),
        "latest_neo_avg_total_comp": latest.get("neo_avg_total_comp"),
        "latest_neo_avg_actually_paid_comp": latest.get("neo_avg_actually_paid_comp"),
        "latest_total_shareholder_return": latest.get("total_shareholder_return"),
        "latest_peer_group_tsr": latest.get("peer_group_tsr"),
        "latest_net_income": latest.get("net_income"),
        "latest_company_selected_measure": latest.get("company_selected_measure"),
        "latest_company_selected_measure_value": latest.get("company_selected_measure_value"),
        "insider_trading_policy_adopted": latest.get("insider_trading_policy_adopted"),
        "has_xbrl": latest.get("has_xbrl"),
        "available_performance_measures": sorted(
            {measure for row in rows for measure in row.get("performance_measures", [])}
        ),
        "compensation_history": compensation_history,
        "pay_vs_performance": latest.get("pay_vs_performance", []),
        "peo_total_comp_change": comp_change,
        "peo_total_comp_change_pct": comp_change_pct,
    }


def extract_institutional_holdings(
    filing: Any,
    min_value: float = 0.0,
    limit: int | None = 100,
) -> list[dict[str, Any]]:
    """Extract normalized 13F holdings rows from a filing."""
    thirteen_f = filing.obj()
    if thirteen_f is None:
        return []

    holdings = getattr(thirteen_f, "holdings", None)
    if holdings is None or len(holdings) == 0:
        return []

    df = holdings.copy()
    for column in [
        "Value",
        "SharesPrnAmount",
        "SoleVoting",
        "SharedVoting",
        "NonVoting",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "Value" in df.columns:
        df = df[df["Value"].fillna(0) >= min_value]
        df = df.sort_values("Value", ascending=False)
    if limit is not None:
        df = df.head(limit)

    total_value = normalize_number(getattr(thirteen_f, "total_value", None))
    total_holdings = normalize_number(getattr(thirteen_f, "total_holdings", None))
    rows: list[dict[str, Any]] = []
    for record in dataframe_records(df):
        value = normalize_number(record.get("Value"))
        portfolio_weight_pct = (
            normalize_number(float(value) / float(total_value) * 100.0)
            if value is not None and total_value not in (None, 0)
            else None
        )
        rows.append(
            {
                "accession_number": getattr(filing, "accession_no", None),
                "form_type": getattr(filing, "form", None),
                "filing_date": str(getattr(filing, "filing_date", "") or ""),
                "report_period": normalize_scalar(getattr(thirteen_f, "report_period", None)),
                "manager_name": getattr(thirteen_f, "management_company_name", None),
                "manager_cik": getattr(filing, "cik", None),
                "filing_signer_name": getattr(thirteen_f, "filing_signer_name", None),
                "filing_signer_title": getattr(thirteen_f, "filing_signer_title", None),
                "total_value": total_value,
                "total_holdings": total_holdings,
                "issuer": record.get("Issuer"),
                "issuer_class": record.get("Class"),
                "cusip": record.get("Cusip"),
                "ticker": record.get("Ticker"),
                "value": value,
                "shares": normalize_number(record.get("SharesPrnAmount")),
                "security_type": record.get("Type"),
                "put_call": record.get("PutCall"),
                "sole_voting": normalize_number(record.get("SoleVoting")),
                "shared_voting": normalize_number(record.get("SharedVoting")),
                "non_voting": normalize_number(record.get("NonVoting")),
                "portfolio_weight_pct": portfolio_weight_pct,
            }
        )

    return rows


def summarize_institutional_holdings_rows(
    rows: list[dict[str, Any]],
    top_n: int = 10,
) -> dict[str, Any]:
    """Summarize a normalized 13F holdings result set."""
    if not rows:
        return {}

    sorted_rows = sorted(
        rows,
        key=lambda row: float(row.get("value") or 0.0),
        reverse=True,
    )
    first_row = sorted_rows[0]
    total_value = normalize_number(first_row.get("total_value"))
    if total_value in (None, 0):
        total_value = normalize_number(
            sum(float(row.get("value") or 0.0) for row in sorted_rows)
        )

    top_holdings = sorted_rows[:top_n]
    top_5_value = sum(float(row.get("value") or 0.0) for row in sorted_rows[:5])
    top_10_value = sum(float(row.get("value") or 0.0) for row in sorted_rows[:10])

    return {
        "manager_name": first_row.get("manager_name"),
        "manager_cik": first_row.get("manager_cik"),
        "filing_signer_name": first_row.get("filing_signer_name"),
        "filing_signer_title": first_row.get("filing_signer_title"),
        "accession_number": first_row.get("accession_number"),
        "form_type": first_row.get("form_type"),
        "filing_date": first_row.get("filing_date"),
        "report_period": first_row.get("report_period"),
        "total_value": total_value,
        "total_holdings": first_row.get("total_holdings"),
        "distinct_securities": len(sorted_rows),
        "top_5_concentration_pct": normalize_number(
            round(top_5_value / float(total_value) * 100.0, 6)
        )
        if total_value not in (None, 0)
        else None,
        "top_10_concentration_pct": normalize_number(
            round(top_10_value / float(total_value) * 100.0, 6)
        )
        if total_value not in (None, 0)
        else None,
        "top_holdings": top_holdings,
    }
