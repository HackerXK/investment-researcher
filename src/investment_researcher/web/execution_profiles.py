"""Execution profiles for research-first versus demo-friendly behavior."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ExecutionProfile:
    """Behavior knobs for the repo's fixed research execution path."""

    name: str
    max_turns: int
    grounding_max_tool_outputs: int
    grounding_max_tool_output_chars: int
    grounding_read_filing_output_chars: int
    grounding_timeout_seconds: float
    max_filing_chars: int
    filing_head_chars: int
    default_truncate_filings: bool


_RESEARCH_PROFILE = ExecutionProfile(
    name="research",
    max_turns=24,
    grounding_max_tool_outputs=24,
    grounding_max_tool_output_chars=160_000,
    grounding_read_filing_output_chars=400_000,
    grounding_timeout_seconds=120.0,
    max_filing_chars=400_000,
    filing_head_chars=160_000,
    default_truncate_filings=False,
)

@lru_cache(maxsize=4)
def get_execution_profile() -> ExecutionProfile:
    """Return the fixed research execution profile."""
    return _RESEARCH_PROFILE
