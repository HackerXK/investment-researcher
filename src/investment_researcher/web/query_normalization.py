from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryNormalization:
    """Explicit normalized intent metadata for research requests."""

    intent: str | None = None
    context_messages: list[dict[str, str]] = field(default_factory=list)


def normalize_research_query(message: str, ticker: str | None = None) -> QueryNormalization:
    """Normalize narrow request patterns into explicit research context.

    This keeps the transport layer free of ad-hoc hidden hints while still
    steering the agent toward the exact tool contract needed for high-accuracy
    recent-filing questions.
    """
    lowered_message = message.lower()
    context_messages: list[dict[str, str]] = []
    intent: str | None = None

    if "proxy statement" in lowered_message and any(
        keyword in lowered_message for keyword in ["recent", "latest"]
    ):
        intent = intent or "latest_proxy_statement"
        context_messages.append(
            {
                "role": "user",
                "content": (
                    "[Normalized research intent: latest_proxy_statement. Prefer "
                    "get_proxy_statement_data with limit=1 and do not set start_date "
                    "or end_date unless the user explicitly asked for a historical range. "
                    "Use the newest filing returned.]"
                ),
            }
        )

    if ("13f" in lowered_message or "top holdings" in lowered_message) and any(
        keyword in lowered_message
        for keyword in ["latest", "recent", "concentrated", "concentration"]
    ):
        intent = intent or "latest_institutional_holdings"
        ticker_context = (
            "the current ticker if the user is asking about the company currently in view"
            if ticker
            else "the manager or filer named in the question"
        )
        context_messages.append(
            {
                "role": "user",
                "content": (
                    "[Normalized research intent: latest_institutional_holdings. Prefer "
                    "summarize_institutional_holdings and do not set report_period or end_date "
                    "unless the user explicitly asked for a historical filing. Use "
                    f"{ticker_context}.]"
                ),
            }
        )

    return QueryNormalization(intent=intent, context_messages=context_messages)