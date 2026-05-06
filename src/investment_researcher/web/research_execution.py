"""Research-core orchestration independent of HTTP and SSE transport."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agents import RunItemStreamEvent


ProgressHandler = Callable[[str], Awaitable[None] | None]
ToolObservation = dict[str, str]


@dataclass
class ResearchExecutionResult:
    """Result returned by the backend research execution path."""

    final_text: str
    progress_messages: list[str] = field(default_factory=list)
    tool_observations: list[ToolObservation] = field(default_factory=list)
    used_direct_answer: bool = False


async def _call_progress_handler(
    progress_handler: ProgressHandler | None,
    message: str,
) -> None:
    """Invoke a progress callback without coupling to any transport."""
    if progress_handler is None:
        return
    result = progress_handler(message)
    if inspect.isawaitable(result):
        await result


async def execute_research_request(
    request: Any,
    *,
    input_items: list[dict[str, str]],
    build_agent_fn: Callable[[], Any],
    try_direct_answer_fn: Callable[[Any], Awaitable[tuple[list[str], str] | None]],
    ground_final_output_fn: Callable[[str, str, list[ToolObservation]], Awaitable[str]],
    serialize_final_output_fn: Callable[[object], str],
    run_streamed_fn: Callable[..., Any],
    tool_name_from_item_fn: Callable[[object], str | None],
    extract_tool_output_fn: Callable[[object], str],
    progress_message_for_tool_fn: Callable[[str | None], str],
    max_turns: int,
    grounding_max_tool_outputs: int,
    initial_progress: str,
    retry_progress: str,
    tool_output_progress: str,
    final_progress: str,
    blank_final_retry_instruction: str,
    progress_handler: ProgressHandler | None = None,
) -> ResearchExecutionResult:
    """Execute one research query without any UI or SSE assumptions."""
    progress_messages: list[str] = []
    last_progress: str | None = None

    async def emit_progress(message: str) -> None:
        nonlocal last_progress
        if not message or message == last_progress:
            return
        last_progress = message
        progress_messages.append(message)
        await _call_progress_handler(progress_handler, message)

    direct_answer = await try_direct_answer_fn(request)
    if direct_answer is not None:
        direct_progress_messages, direct_text = direct_answer
        for message in direct_progress_messages:
            await emit_progress(message)
        if direct_text:
            await emit_progress(final_progress)
        return ResearchExecutionResult(
            final_text=direct_text,
            progress_messages=progress_messages,
            used_direct_answer=True,
        )

    agent = build_agent_fn()
    run_inputs = list(input_items)
    final_text = ""
    final_tool_observations: list[ToolObservation] = []

    for attempt in range(2):
        current_tool_name: str | None = None
        tool_observations: list[ToolObservation] = []
        await emit_progress(initial_progress if attempt == 0 else retry_progress)

        result = run_streamed_fn(
            agent,
            input=run_inputs,
            max_turns=max_turns,
        )

        async for event in result.stream_events():
            if not isinstance(event, RunItemStreamEvent):
                continue

            if event.name == "tool_called":
                current_tool_name = tool_name_from_item_fn(event.item)
                await emit_progress(progress_message_for_tool_fn(current_tool_name))
                continue

            if event.name != "tool_output":
                continue

            tool_output = extract_tool_output_fn(event.item).strip()
            if tool_output:
                tool_observations.append(
                    {
                        "tool_name": current_tool_name or "unknown_tool",
                        "output": tool_output,
                    }
                )
                if len(tool_observations) > grounding_max_tool_outputs:
                    tool_observations = tool_observations[-grounding_max_tool_outputs:]
            await emit_progress(tool_output_progress)

        final_tool_observations = tool_observations
        final_text = serialize_final_output_fn(result.final_output)
        final_text = await ground_final_output_fn(
            request.message,
            final_text,
            tool_observations,
        )
        final_text = final_text.strip()
        if final_text:
            break
        if attempt == 0:
            run_inputs = list(input_items) + [
                {"role": "user", "content": blank_final_retry_instruction}
            ]

    if final_text:
        await emit_progress(final_progress)

    return ResearchExecutionResult(
        final_text=final_text,
        progress_messages=progress_messages,
        tool_observations=final_tool_observations,
    )
