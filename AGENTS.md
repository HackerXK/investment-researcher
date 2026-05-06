# AGENTS.md

Repo-wide instructions for AI coding agents. Keep changes aligned with the existing architecture, prefer linked docs over duplicated explanations, and validate behavior with the narrowest relevant test command.

## Project Priorities

- Accuracy first. Prefer evidence-rich, traceable, backend-enforced correctness over speed, token savings, UI polish, or minimal tool usage.
- Local-LLM first. Assume the primary chat and evaluation runtime is a local OpenAI-compatible model endpoint; optimize prompts, tool contracts, and validation for research quality rather than hosted-model cost control.
- Backend first. The product value is the ingestion, analytics, SEC research, and evaluation stack. Treat the frontend as a demonstration and interaction layer for backend capabilities, not the source of business logic.
- Preserve evidence contracts. When changing agent or chat behavior, prefer structured tool outputs, provenance metadata, explicit validation, and evaluator-visible evidence over hidden prompt tricks.

## Read First

Read the relevant docs before architecture, ingestion, analytics, agent, or evaluation changes:

- [README.md](README.md)
- [docs/architecture/01-system-overview.md](docs/architecture/01-system-overview.md)
- [docs/architecture/03-data-ingestion.md](docs/architecture/03-data-ingestion.md)
- [docs/architecture/04-agent-system.md](docs/architecture/04-agent-system.md)
- [docs/architecture/05-tech-stack.md](docs/architecture/05-tech-stack.md)
- [docs/chat-eval-questions.md](docs/chat-eval-questions.md)

Prefer linking to these docs over duplicating long explanations.

## Architecture

- `src/investment_researcher/ingestion/`: SEC ingestion, DuckDB writes, SQLite state, Prefect flows.
- `src/investment_researcher/analytics/`: DuckDB-backed metrics, TTM, ratios, and structured SEC helpers. Ratios are computed on demand, not persisted.
- `src/investment_researcher/web/`: FastAPI API, OpenAI Agents SDK tool wrappers, SSE chat, live chat eval, tracing hooks, and research-execution orchestration for the local-LLM backend.
- `frontend/`: Nuxt 3 UI and SSE chat client used primarily to demonstrate and inspect backend research capabilities.
- `src/investment_researcher/service.py`: service entrypoint; auto-seeds on empty state and registers Prefect deployments.

## Commands

- Setup: `uv venv --python 3.12 .venv && source .venv/bin/activate && uv pip install -e ".[dev,demo]"`
- Fast tests: `pytest tests/ -v -m "not integration"`
- Full tests: `pytest tests/ -v`
- Targeted chat tests: `pytest tests/test_chat_agent.py -v`
- Live eval smoke: `python scripts/run_live_chat_eval.py --smoke`
- Live eval full: `python scripts/run_live_chat_eval.py`
- Local service: `python -m investment_researcher.service`
- Docker stack: `docker compose up --build -d`

## Validation Strategy

- Prefer the narrowest relevant test command for the change.
- For pure analytics changes, run focused analytics or unit tests before broader test suites.
- For chat, agent tools, or response behavior changes, run `pytest tests/test_chat_agent.py -v`.
- For evaluation, evidence, or answer-quality rubric changes, run `pytest tests/test_chat_eval.py -v` before broader suites.
- Run `python scripts/run_live_chat_eval.py --smoke` only when live credentials and network access are available.
- Keep full live eval opt-in because it may use networked services and model or API calls.

## Coding Style

### General Engineering Practices

- Prefer small, focused changes that solve the requested problem without unrelated rewrites.
- Follow existing patterns in nearby files before introducing new abstractions.
- Keep logic simple and explicit; avoid clever code when straightforward code is easier to maintain.
- Preserve public APIs, data contracts, and file organization unless the task explicitly asks to change them.
- Prefer clear names that reflect domain concepts, especially for financial metrics, filings, tools, and API payloads.
- Keep functions focused. Extract helpers when logic is reused, deeply nested, or hard to test.
- Make invalid states hard to represent where practical.
- Handle errors deliberately; avoid broad `except Exception` blocks unless they add useful context or preserve a required boundary.
- Do not add new dependencies when the standard library or existing project dependencies are sufficient.
- Update nearby docs or comments when changing behavior that future maintainers need to understand.

### Python Practices

- Use Python 3.12 features where appropriate.
- Add `from __future__ import annotations` to new Python modules.
- Use explicit type hints for public functions, API boundaries, tool inputs, and non-trivial return values.
- Prefer dataclasses, TypedDicts, Pydantic models, or well-typed dictionaries at API and tool boundaries instead of unstructured nested dictionaries.
- Keep I/O, database access, and external service calls separate from pure transformation logic where practical.
- Prefer pure functions for analytics, normalization, parsing, and formatting logic.
- Use pathlib instead of string path manipulation.
- Use logging instead of `print` outside scripts and CLI-oriented utilities.
- Avoid mutable default arguments.
- Prefer targeted exceptions and meaningful error messages.
- Keep tests deterministic; mock or fixture external APIs, clocks, and network access in unit tests.

### Frontend Practices

- Follow existing Nuxt 3, Vue, and TypeScript patterns in `frontend/`.
- Keep components focused on presentation and user interaction; move reusable logic into composables or utilities.
- Prefer typed props, emits, API responses, and shared interfaces where practical.
- Keep API and SSE client behavior compatible with the backend contracts.
- Do not move research logic, evidence selection, or financial interpretation into the frontend unless the task explicitly requires a presentation-only transform.
- Treat SSE event semantics as a backend contract; parse and present `progress`, `token`, `error`, and `data: [DONE]` without redefining their meaning or order in the frontend.
- Handle loading, empty, error, and partial-streaming states explicitly.
- Avoid duplicating backend business logic in the frontend unless needed for user experience.
- Prefer accessible markup: semantic elements, labels, keyboard-friendly controls, and meaningful button/link text.
- Avoid introducing new UI dependencies unless existing project dependencies are insufficient.
- Keep client-side state minimal and close to where it is used unless it is shared across views.

## Domain Invariants

- Keep tickers uppercase and dates as ISO `YYYY-MM-DD` strings across API and tool boundaries.
- Treat `capex` as a negative cash outflow. Canonical free cash flow is `operating_cash_flow + capex`.
- Ratios are derived in analytics on demand; do not persist derived ratio values unless the task explicitly changes that architecture.

## Layer Boundaries And Contracts

- Preserve the current boundary: ingestion writes normalized metrics, analytics derives TTM and ratios, and the web layer formats and streams results.
- Prefer explicit query normalization and structured evidence contracts over hidden prompt-only steering when agent routing needs to be more accurate.
- Prefer existing structured SEC helpers in `src/investment_researcher/analytics/sec_filings.py` and `src/investment_researcher/web/agent_tools.py` over adding new raw parsing paths.
- For SEC question answering, prefer structured tool outputs before raw filing text. Use full filing text only when the structured tools cannot answer the question.
- Agent and API outputs must remain JSON-safe; sanitize `NaN` and `Inf` to `None`.
- Preserve the SSE chat contract: `progress`, `token`, `error`, then `data: [DONE]`. Do not expose raw model planning text in streamed output.

## Testing

- Unit tests must not touch real runtime databases. `tests/conftest.py` loads `.env.test` and seeds a temporary DuckDB with golden fixtures.
- Prefer fixture-based tests over live SEC access for unit coverage.
- For analytics or ratio changes, add or update focused unit tests first.
- For chat or tool changes, run `tests/test_chat_agent.py` first; use live eval selectively when response behavior or evidence grounding changes.
- `integration` tests hit the real SEC API and network. Keep them opt-in.

## Security And Dependencies

- Never hardcode secrets or real API keys. Use environment variables; local chat commonly uses `LLM_API_KEY=EMPTY`.
- `EDGAR_IDENTITY` is required for live SEC access. Do not remove or bypass that requirement.
- Keep `edgartools` as the primary SEC interface unless the task explicitly requires a new dependency.
- Manage Python dependencies in `pyproject.toml` with `uv`. Manage frontend dependencies in `frontend/package.json`.
- If a change affects installed CLI entrypoints or container runtime behavior, rebuild Docker images before validating container flows.
- Keep local `.env` paths host-visible for direct Python runs. Container-only `/app/...` paths belong in `docker-compose.yml`, not shared local runtime config.
- FastAPI CORS is intentionally open for local development. Tighten it explicitly if a task changes deployment exposure.