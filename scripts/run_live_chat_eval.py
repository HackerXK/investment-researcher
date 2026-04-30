#!/usr/bin/env python3
"""Run live chat evaluations against the real chat stack and LLM endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"

for path in (PROJECT_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from investment_researcher.web.chat_eval import (  # noqa: E402
    evaluate_question,
    prepare_live_environment,
    probe_llm_endpoint,
    summarize_environment,
    write_run_artifacts,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live chat evaluations against the real chat endpoint.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run only the smaller smoke subset.",
    )
    parser.add_argument(
        "--question",
        dest="question_ids",
        action="append",
        default=[],
        help="Run one specific question id. May be supplied multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of selected questions.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for run artifacts. Defaults to artifacts/chat-eval/<timestamp>.",
    )
    return parser.parse_args()


def _load_questions(args: argparse.Namespace):
    from tests.fixtures.chat_eval_questions import (  # noqa: E402
        get_chat_eval_question,
        get_chat_eval_questions,
    )

    if args.question_ids:
        questions = [get_chat_eval_question(question_id) for question_id in args.question_ids]
    else:
        questions = get_chat_eval_questions(smoke_only=args.smoke)

    if args.limit is not None:
        questions = questions[: args.limit]

    if not questions:
        raise SystemExit("No questions selected.")
    return questions


def _default_output_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "artifacts" / "chat-eval" / timestamp


def _write_preflight_failure(
    output_dir: Path,
    environment: dict[str, str | None],
    reason: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "preflight_failed",
        "reason": reason,
        "environment": environment,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path = output_dir / "preflight.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path


def _bootstrap_runtime() -> None:
    prepare_live_environment(PROJECT_ROOT)

    # edgartools emits repetitive parser warnings for some SGML headers that do not
    # affect the extracted 13F data used by this harness.
    logging.getLogger("edgar.core").setLevel(logging.ERROR)

    from investment_researcher.ingestion.edgar.storage import configure_edgar  # noqa: E402
    from investment_researcher.ingestion.state import initialize_state_db  # noqa: E402
    from investment_researcher.ingestion.timeseries import initialize_db  # noqa: E402

    initialize_db()
    initialize_state_db()
    configure_edgar()


def _flush_langfuse() -> None:
    try:
        from investment_researcher.web.tracing import flush_langfuse  # noqa: E402
    except Exception:
        return

    flush_langfuse()


async def _run(args: argparse.Namespace) -> int:
    try:
        _bootstrap_runtime()
        output_dir = args.output_dir or _default_output_dir()
        environment = summarize_environment()

        llm_ok, llm_message = await probe_llm_endpoint()
        if not llm_ok:
            print(f"LLM endpoint preflight failed: {llm_message}")
            artifact_path = _write_preflight_failure(output_dir, environment, llm_message)
            print(f"Preflight artifact: {artifact_path}")
            return 2

        questions = _load_questions(args)

        from investment_researcher.web.app import app  # noqa: E402

        print("Live chat evaluation environment:")
        for key, value in environment.items():
            print(f"  {key}={value}")
        print(f"Selected {len(questions)} question(s)")

        results = []
        for index, question in enumerate(questions, start=1):
            print(f"[{index}/{len(questions)}] {question.question_id} ...")
            result = await evaluate_question(app, question)
            results.append(result)
            print(
                "    "
                f"chat={result.chat.status} eval={result.evaluation.overall} "
                f"reason={result.evaluation.reason or result.chat.error or 'n/a'}"
            )

        artifacts = write_run_artifacts(output_dir, results)
        print("Artifacts:")
        for key, path in artifacts.items():
            print(f"  {key}: {path}")

        failures = [
            result
            for result in results
            if result.chat.status != "ok" or result.evaluation.overall != "pass"
        ]
        if failures:
            print(f"Completed with {len(failures)} failing question(s).")
            return 1

        print("Completed with all questions passing.")
        return 0
    finally:
        _flush_langfuse()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())