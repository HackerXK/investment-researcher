"""Langfuse tracing helpers for the chat backend."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from agents import set_tracing_disabled

from investment_researcher.config import (
    LANGFUSE_BASE_URL,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)

log = logging.getLogger(__name__)

_LANGFUSE_INSTRUMENTED = False
_LANGFUSE_INSTRUMENTATION_FAILED = False


def langfuse_configured() -> bool:
    """Return True when Langfuse credentials are configured."""
    return bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


@lru_cache(maxsize=1)
def _langfuse_modules():
    """Import Langfuse modules lazily after environment loading."""
    from langfuse import get_client, propagate_attributes
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

    return get_client, propagate_attributes, OpenAIAgentsInstrumentor


def configure_langfuse_tracing() -> bool:
    """Enable OpenAI Agents tracing via Langfuse when configured."""
    global _LANGFUSE_INSTRUMENTED, _LANGFUSE_INSTRUMENTATION_FAILED

    if _LANGFUSE_INSTRUMENTED:
        return True

    if not langfuse_configured():
        set_tracing_disabled(True)
        return False

    if _LANGFUSE_INSTRUMENTATION_FAILED:
        return False

    try:
        get_client, _, OpenAIAgentsInstrumentor = _langfuse_modules()
        OpenAIAgentsInstrumentor().instrument()
        client = get_client()
        if not client.auth_check():
            raise RuntimeError("Langfuse auth check failed")
    except Exception as exc:
        _LANGFUSE_INSTRUMENTATION_FAILED = True
        set_tracing_disabled(True)
        log.warning("Disabled Langfuse tracing: %s", exc)
        return False

    set_tracing_disabled(False)
    _LANGFUSE_INSTRUMENTED = True
    log.info("Langfuse tracing enabled via %s", LANGFUSE_BASE_URL)
    return True


@contextmanager
def start_chat_trace(
    *,
    message: str,
    ticker: str | None,
    history_length: int,
    session_id: str | None,
    source: str | None,
) -> Iterator[Any | None]:
    """Create a root Langfuse span for one chat request when enabled."""
    if not configure_langfuse_tracing():
        yield None
        return

    get_client, propagate_attributes, _ = _langfuse_modules()
    client = get_client()

    metadata: dict[str, str] = {
        "historyLength": str(history_length),
    }
    if ticker:
        metadata["ticker"] = ticker
    if source:
        metadata["source"] = source

    tags = ["chat"]
    if source:
        tags.append(source)

    propagated_attrs: dict[str, Any] = {
        "tags": tags,
        "metadata": metadata,
        "trace_name": "chat-response",
    }
    if session_id:
        propagated_attrs["session_id"] = session_id

    with client.start_as_current_observation(
        as_type="span",
        name="chat-response",
        input={
            "message": message,
            "ticker": ticker,
            "historyLength": history_length,
        },
    ) as span:
        with propagate_attributes(**propagated_attrs):
            yield span


def update_chat_trace(
    span: Any | None,
    *,
    output: dict[str, Any],
    status: str,
    progress_count: int,
) -> None:
    """Update the root chat span if tracing is active."""
    if span is None:
        return

    span.update(
        output=output,
        metadata={
            "status": status,
            "progressCount": str(progress_count),
        },
    )


def flush_langfuse() -> None:
    """Flush buffered Langfuse spans in short-lived processes."""
    if not configure_langfuse_tracing():
        return

    get_client, _, _ = _langfuse_modules()
    get_client().flush()


def shutdown_langfuse() -> None:
    """Shutdown the Langfuse client when the server exits."""
    if not configure_langfuse_tracing():
        return

    get_client, _, _ = _langfuse_modules()
    get_client().shutdown()