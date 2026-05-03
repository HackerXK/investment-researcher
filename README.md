# Investment Researcher

Investment Researcher is a local SEC ingestion pipeline plus financial research platform.
It downloads SEC filing data via [edgartools](https://github.com/dgunning/edgartools), stores raw filings on disk, writes normalized financial metrics into DuckDB, computes on-the-fly ratios and TTM metrics, and serves scheduled Prefect flows for ongoing updates.

Four main workflows:

- Run the long-lived ingestion service with Docker Compose.
- Develop and test the ingestion and ratio code locally.
- Explore the populated DuckDB database with the Nuxt 3 frontend web app.
- Chat with an AI financial analyst powered by the OpenAI Agents SDK that can autonomously query financials, compute ratios, and read SEC filings.

## Architecture

**Ingestion pipeline** — two extraction paths feed the same DuckDB `financial_metrics` table:

- **Fast path**: downloads recent 10-K and 10-Q filings, parses filing-level XBRL, and upserts new data. Runs daily.
- **Slow path**: refreshes bulk SEC metadata and re-extracts company facts to catch amendments, corrections, and coverage gaps. Runs weekly.

**Analytics layer** — on top of the raw metrics:

- `metrics.py` aggregates Trailing Twelve Months (TTM) metrics and derives computed values (EBITDA, FCF, gross profit, etc.).
- `ratios.py` computes ~46 financial ratios across 8 categories (profitability, returns, liquidity, leverage, efficiency, cash flow, per-share, other) entirely on-the-fly from DuckDB — ratios are never stored.

**Agentic chat** — an AI financial analyst that can autonomously plan and execute multi-step analyses:

- Built with the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) using `OpenAIChatCompletionsModel` for compatibility with local vLLM / any OpenAI-compatible endpoint.
- The agent has 29 tools wrapping the analytics and SEC research surface: company discovery, time-series analytics, ratios, cross-company comparison, filing discovery, section-aware filing reading, targeted filing search, and structured Form 4, 8-K, DEF 14A, and 13F analysis.
- Streams responses via SSE (`data: {"token": "..."}` / `data: [DONE]`) to the Nuxt 3 frontend chat panel.
- Tracing is disabled by default (no OpenAI platform key needed).

**Service startup** sequence:

1. Initialize DuckDB and SQLite state databases.
2. Configure edgartools storage.
3. Detect empty state and run the seed flow automatically (or unconditionally when `FORCE_SEED=true`).
4. Register and serve Prefect deployments for the scheduled fast and slow paths.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for local setup
- Docker and Docker Compose for the containerized service
- A valid SEC EDGAR identity string such as `Your Name your@email.com`

## Quick Start With Docker

### 1. Configure the environment

```bash
cp .env.example .env
```

Edit `.env` before starting the stack. See [Environment Variables](#environment-variables) for a full reference.

**Required:**

- `EDGAR_IDENTITY` — your SEC EDGAR user-agent identity string
- `EDGAR_LOCAL_DATA_DIR_HOST_SOURCE` / `EDGAR_LOCAL_DATA_DIR_RUNTIME` — host path and container path for the edgartools offline cache
- `DUCKDB_DIR_HOST_SOURCE` / `DUCKDB_DIR_RUNTIME` — host and container directories for the DuckDB file (directory-level bind mount)
- `DUCKDB_PATH_HOST_SOURCE` / `DUCKDB_PATH_RUNTIME` — full path to the DuckDB file itself
- `STATE_DIR_HOST_SOURCE` / `STATE_DIR_RUNTIME` — host and container directories for the SQLite state DB
- `STATE_DB_PATH_HOST_SOURCE` / `STATE_DB_PATH_RUNTIME` — full path to the SQLite state DB file

For Docker, the `_HOST_SOURCE` variables are the host-side bind mount sources; the container reads and writes the `_RUNTIME` paths. For local development, set `_RUNTIME` to the same paths as `_HOST_SOURCE`.

**Optional (defaults shown):**

```bash
PREFECT_API_URL=http://localhost:4200/api
EDGAR_FILINGS_START_DATE=2021-01-01   # seed window start
EDGAR_RAW_FILING_TICKERS=             # unset → default top-10 tickers
FORCE_SEED=false
FMP_API_KEY=                          # only needed for golden-data scripts
```

Note: Docker will create missing host directories for bind mounts, but the container user must be able to write them. Pre-create directories with the correct ownership if needed.

### 2. Raw filing scope

Control which companies have raw filing documents downloaded locally via `EDGAR_RAW_FILING_TICKERS`:

- **unset / empty** → default top-10 tickers: `AAPL, NVDA, UNH, WMT, XOM, MSFT, AMZN, GOOGL, META, TSLA`
- **`ALL`** → every company (large, unbounded disk usage)
- **comma-separated list** → only those tickers, e.g. `AAPL,MSFT,GOOGL`

The seed download window starts at `EDGAR_FILINGS_START_DATE`. The daily incremental download uses a rolling `days`-based window and is unaffected by that setting.

Bulk SEC metadata (submissions, companyfacts, reference data) is always downloaded for all companies regardless of this setting. Raw filing storage covers every filing form; the fast-path extractor only processes `10-K`, `10-K/A`, `10-Q`, and `10-Q/A`.

### 3. Start the services

```bash
docker compose up --build -d
```

This starts:

- `prefect-server` — Prefect UI and API at http://localhost:4200
- `ir-service` — the ingestion service container

On a fresh start, `ir-service` auto-seeds the local dataset before switching into scheduled service mode. The initial seed can take a long time and uses substantial disk space. The service logs `storage_empty`, `db_empty`, and `force_seed` on startup so you can see exactly why a seed did or did not run.

### 4. Monitor the service

```bash
docker compose ps
docker compose logs -f prefect-server ir-service
```

Inspect DuckDB contents inside the container:

```bash
docker compose exec ir-service python -c "
import duckdb
con = duckdb.connect('/app/data/duckdb/financial_timeseries.duckdb')
print('Distinct tickers:', con.execute('SELECT COUNT(DISTINCT ticker) FROM financial_metrics').fetchone()[0])
print('Total rows:', con.execute('SELECT COUNT(*) FROM financial_metrics').fetchone()[0])
"
```

Stop the stack:

```bash
docker compose down
```

### Force re-seed

To force a full re-seed on the next startup (e.g. after clearing data or changing the filing scope), set `FORCE_SEED=true`. The service will run `seed_flow` unconditionally, then continue into normal scheduled mode.

**Docker:**
```bash
FORCE_SEED=true docker compose up -d
```

**Locally:**
```bash
FORCE_SEED=true python -m investment_researcher.service
```

Remove or reset `FORCE_SEED=false` after the seed completes to avoid re-seeding on every restart.

### Inspect DuckDB (local CLI)

```bash
DB=${DUCKDB_PATH_RUNTIME:-./data/duckdb/financial_timeseries.duckdb}

# Interactive
duckdb "$DB"

# One-liners
duckdb "$DB" -c "SELECT COUNT(*) FROM financial_metrics;"
duckdb "$DB" -c "SELECT COUNT(DISTINCT ticker) FROM financial_metrics;"
duckdb "$DB" -c "SELECT table_name FROM information_schema.tables WHERE table_schema='main';"
duckdb "$DB" -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='financial_metrics' ORDER BY ordinal_position;"
duckdb "$DB" -c "SELECT MIN(period_end), MAX(period_end) FROM financial_metrics;"
duckdb "$DB" -c "COPY (SELECT * FROM financial_metrics LIMIT 1000) TO 'sample.csv' (HEADER, DELIMITER ',');"
```

Primary columns: `ticker`, `metric_type`, `value`, `period`, `period_type`, `period_end`.

## Local Development

### Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env
```

If `DUCKDB_PATH_RUNTIME`, `STATE_DB_PATH_RUNTIME`, or `EDGAR_LOCAL_DATA_DIR_RUNTIME` are not set, the code defaults to repository-local paths under `data/`.

### Run the service locally

```bash
python -m investment_researcher.service
```

Same startup logic as Docker: initialize storage, auto-seed if empty, then serve Prefect deployments in-process.

### Run flows manually

```python
from investment_researcher.flows.sec_data import fast_path_flow, seed_flow, slow_path_flow

# Small seed for local experimentation
seed_flow(company_limit=10)

# Process recent filings
fast_path_flow(days=1)

# Re-extract a subset or full companyfacts refresh
slow_path_flow(company_limit=10)
```

### Run one-off extraction

```python
from investment_researcher.ingestion.edgar.financials import extract_company_facts
from investment_researcher.ingestion.edgar.storage import configure_edgar
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.timeseries import initialize_db

configure_edgar()
initialize_db()
initialize_state_db()

count = extract_company_facts('AAPL')
print(f'Extracted {count} metrics for AAPL')
```

### Re-run slow-path extraction for selected companies

Use the installed `ir-rerun-slow-path` command when you want to repair or reprocess specific tickers without re-running the full weekly slow path. It deletes existing rows for those tickers from `financial_metrics` and `company_extraction_state`, then runs the slow-path companyfacts extractor again for those tickers only.

This helper reuses the SEC metadata already present in your local edgartools cache. It does not refresh bulk metadata first.

**Docker Compose (recommended when using the containerized stack):**

If the rerun helper was added after your containers were built, rebuild the Python service images first so the installed package in the containers includes the new code:

```bash
docker compose up -d --build ir-service api
```

```bash
docker compose exec -T ir-service ir-rerun-slow-path AAPL MSFT
```

The command also accepts comma-separated input, for example `docker compose exec -T ir-service ir-rerun-slow-path AAPL,MSFT,NVDA`.

Each result row includes `ticker`, `deleted_rows`, `deleted_state_rows`, and `written_rows`. Add `--compact` if you want single-line JSON output.

### Normalize stored metric signs in an existing DuckDB

Databases populated before the canonical sign change can still contain mixed conventions, for example positive `capex` or positive `cost_of_revenue`. New ingestions now normalize signs on write, but existing rows need a one-time repair.

Preview the change first:

```bash
docker compose exec -T ir-service ir-normalize-metric-signs --dry-run
```

Then apply it once:

```bash
docker compose exec -T ir-service ir-normalize-metric-signs
```

This command records a maintenance marker inside DuckDB and refuses to run again unless you pass `--force`. That guard matters because `income_tax_expense` uses a full sign flip rather than a magnitude-only normalization.

**HTTP API (for a writable API process):**

```bash
curl -X POST http://localhost:8080/api/companies/slow-path/rerun \
    -H "Content-Type: application/json" \
    -d '{"tickers":["AAPL","MSFT"]}'
```

The default Docker Compose `api` container mounts DuckDB read-only, so Docker-based reruns should go through `ir-service`. If you need fresh bulk SEC metadata before re-extracting, refresh metadata separately first, then run the targeted rerun.

## Nuxt Web App

The Nuxt frontend replaces the old Streamlit demo. Populate the database first (via Docker or a local seed run), then launch the web app from `frontend/`:

```bash
cd frontend
npm install
npm run dev
```

The frontend provides the company dashboard, chat panel, financial tables, and charts.

## Agentic Chat

The chat backend uses the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) to create a **Financial Analyst** agent that autonomously plans and executes multi-step analyses. Instead of stuffing a fixed context window, the agent decides which tools to call, retrieves only the data it needs, and synthesises a quantitative answer.

### How it works

1. The user sends a question via the Nuxt 3 frontend chat panel (or the `/api/chat` REST endpoint).
2. The backend constructs an `Agent` with 29 tools wrapping the full analytics surface.
3. `Runner.run_streamed()` lets the agent plan tool calls, execute them, and stream the final response token-by-token via SSE.
4. The frontend renders tokens incrementally — same SSE format as before (`data: {"token": "..."}` / `data: [DONE]`).

### Available tools

| Tool | Description |
|------|-------------|
| `search_companies` | Full-text search across known companies |
| `get_company_profile` | Company profile (name, sector, industry, CIK, SIC) |
| `list_available_tickers` | All tickers with data in DuckDB |
| `get_ticker_summary` | High-level financial summary for a ticker |
| `get_metrics_timeseries` | Time-series for specific metrics |
| `get_metrics_pivot` | Multi-metric pivot table (periods as columns) |
| `get_growth_rates` | Year-over-year growth rates |
| `get_cashflow_pivot` | Full cash flow statement pivot |
| `get_ttm_metrics` | Trailing Twelve Months aggregated metrics |
| `get_quarterly_detail` | Recent quarterly breakdown |
| `get_latest_ratios` | Latest-period financial ratios |
| `get_ttm_ratios` | TTM financial ratios |
| `get_ratios_wide` | Multi-period ratio table |
| `get_ratio_timeseries` | Historical time-series for a single ratio |
| `list_available_ratios` | All ~46 ratios grouped by category |
| `compare_metric_across_companies` | Cross-company metric comparison |
| `list_filings` | Discover SEC filings by type (10-K, 10-Q, 8-K, etc.) |
| `list_filing_sections` | List item-based sections inside a filing so the agent can target Item 1A, Item 7, Item 5.02, and similar sections directly |
| `read_filing_section` | Read one item-based filing section with accession and section metadata instead of loading the whole filing |
| `search_filing_text` | Search a filing or one section for a phrase and return compact evidence excerpts with section metadata |
| `read_filing` | Read full text of any SEC filing by accession number |
| `get_insider_trades` | Structured Form 4 transactions across a date range, including insider, tx date, code, shares, proceeds, and significance bucket |
| `summarize_insider_sells` | Grouped Form 4 sell summaries by insider or transaction code |
| `get_material_events` | Structured 8-K event rows with item codes and excerpts |
| `summarize_material_events` | Grouped summaries of 8-K event activity by item code or content type |
| `get_proxy_statement_data` | Structured DEF 14A snapshots including CEO comp and pay-vs-performance fields |
| `summarize_proxy_statement` | High-level summary across recent proxy statement filings |
| `get_institutional_holdings` | Structured holdings from a manager's selected 13F filing |
| `summarize_institutional_holdings` | Concentration-oriented summary of a manager's 13F portfolio |

### Configuration

Set three environment variables (see [Environment Variables](#environment-variables)):

```bash
LLM_API_BASE=http://localhost:8000/v1   # your vLLM or OpenAI-compatible endpoint
LLM_MODEL=Qwen/Qwen2.5-32B-Instruct    # model name
LLM_API_KEY=EMPTY                        # API key (EMPTY for local vLLM)
```

The agent uses `OpenAIChatCompletionsModel` (not the Responses API), so it works with any OpenAI-compatible endpoint including vLLM, Ollama, and llama.cpp.

## Live Chat Evaluation

The repository includes a live chat evaluation harness that runs the real chat stack
against the configured OpenAI-compatible endpoint and grades answers against compact
SEC-derived evidence.

Run the smoke subset first:

```bash
python scripts/run_live_chat_eval.py --smoke
```

For the reusable question corpus, smoke-subset contents, and eval-specific notes, see
[`docs/chat-eval-questions.md`](docs/chat-eval-questions.md).

## Financial Ratios & TTM Metrics

Ratios and TTM metrics are computed on-the-fly from DuckDB — they are never persisted separately.

**`ratios.py`** — ~46 ratios across 8 categories:

| Category | Examples |
|----------|---------|
| Profitability Margins | gross margin, operating margin, net margin, EBITDA margin |
| Returns | ROA, ROE, ROCE, return on invested capital |
| Liquidity | current ratio, quick ratio |
| Leverage / Solvency | debt-to-equity |
| Efficiency / Turnover | asset turnover, inventory turnover |
| Cash Flow | FCF margin, OCF-to-revenue, capex-to-revenue, FCF yield |
| Per Share | EPS (diluted), book value per share, FCF per share, revenue per share |
| Other | interest coverage, payout ratio |

Key functions: `compute_ratios()` (long form), `compute_ratios_wide()` (periods × ratio names), `latest_ratios()` (most recent snapshot).

**`metrics.py`** — TTM aggregation and derived metric computation:

- Flow metrics (revenue, net income, OCF, etc.) are summed across the four most recent quarters.
- Stock metrics (balance sheet items, shares outstanding) use the latest quarterly snapshot.
- Derived metrics computed from components: EBITDA, free cash flow, gross profit.
- Share split normalization: retroactively adjusts all earlier periods when a ≥3× jump in shares outstanding is detected.

## Running Tests

```bash
# Fast local tests only
pytest tests/ -v -m "not integration"

# Full suite (requires SEC network access)
pytest tests/ -v

# Single module
pytest tests/test_ratios.py -v
```

- The `integration` marker covers tests that hit the real SEC EDGAR API (slow, network-dependent).
- `tests/fixtures` is added to `pythonpath` in `pyproject.toml` so golden-data modules import cleanly.

## Golden Data Helpers

Three scripts generate fixture data from independent sources for golden-data validation. All require `FMP_API_KEY` in `.env` for FMP-backed output; some FMP endpoints require a paid plan.

**`build_golden_data.py`** — fetches raw financial statement data from SEC DERA bulk extracts and FMP, writing golden fixtures for the five core tickers (AAPL, NVDA, UNH, WMT, XOM):

```bash
python scripts/build_golden_data.py AAPL NVDA UNH WMT XOM
```

**`build_golden_ratios.py`** — fetches annual and quarterly financial ratios from FMP and writes `tests/fixtures/golden_ratios_{ticker}.py`:

```bash
python scripts/build_golden_ratios.py
```

**`build_golden_ttm_ratios.py`** — fetches Trailing Twelve Months ratios from FMP TTM endpoints and writes `tests/fixtures/golden_ttm_ratios_{ticker}.py`:

```bash
python scripts/build_golden_ttm_ratios.py
```

## Environment Variables

Full reference for all variables read by the application. Copy `.env.example` as a starting point.

### Required

| Variable | Description |
|----------|-------------|
| `EDGAR_IDENTITY` | SEC EDGAR User-Agent identity (e.g. `name@example.com`) |

### Data paths — host vs. runtime

Each data store has a `_HOST_SOURCE` variable (Docker bind mount source on the host) and a `_RUNTIME` variable (the path the process actually reads/writes). For local development, set both to the same path.

| Variable | Example (local) | Example (Docker runtime) |
|----------|-----------------|--------------------------|
| `EDGAR_LOCAL_DATA_DIR_HOST_SOURCE` | `/path/to/edgar-offline` | same as host |
| `EDGAR_LOCAL_DATA_DIR_RUNTIME` | `/path/to/edgar-offline` | `/app/data/edgar` |
| `DUCKDB_DIR_HOST_SOURCE` | `./data/duckdb` | same as host |
| `DUCKDB_DIR_RUNTIME` | `./data/duckdb` | `/app/data/duckdb` |
| `DUCKDB_PATH_HOST_SOURCE` | `./data/duckdb/financial_timeseries.duckdb` | same as host |
| `DUCKDB_PATH_RUNTIME` | `./data/duckdb/financial_timeseries.duckdb` | `/app/data/duckdb/financial_timeseries.duckdb` |
| `STATE_DIR_HOST_SOURCE` | `./data/state` | same as host |
| `STATE_DIR_RUNTIME` | `./data/state` | `/app/data/state` |
| `STATE_DB_PATH_HOST_SOURCE` | `./data/state/ingestion_state.db` | same as host |
| `STATE_DB_PATH_RUNTIME` | `./data/state/ingestion_state.db` | `/app/data/state/ingestion_state.db` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PREFECT_API_URL` | `http://localhost:4200/api` | Prefect server endpoint |
| `EDGAR_FILINGS_START_DATE` | `2021-01-01` | Earliest filing date for the seed download window |
| `EDGAR_RAW_FILING_TICKERS` | top-10 tickers | Raw filing download scope (see [Raw filing scope](#2-raw-filing-scope)) |
| `FORCE_SEED` | `false` | Set `true` to force seed flow on the next startup |
| `FMP_API_KEY` | — | Financial Modeling Prep API key (golden-data scripts only) |
| `LLM_API_BASE` | `http://localhost:8000/v1` | OpenAI-compatible Chat Completions endpoint for the agentic chat |
| `LLM_MODEL` | `Qwen/Qwen2.5-32B-Instruct` | Model name to pass to the Chat Completions endpoint |
| `LLM_API_KEY` | `EMPTY` | API key for the LLM endpoint (set `EMPTY` for local vLLM) |

## Project Structure

```text
├── docker-compose.yml              # Prefect server + ingestion service
├── Dockerfile                      # Container image for ir-service
├── pyproject.toml                  # Package metadata, extras, pytest config
├── scripts/
│   ├── build_golden_data.py        # Golden raw metrics from SEC DERA + FMP
│   ├── build_golden_ratios.py      # Golden annual/quarterly ratios from FMP
│   └── build_golden_ttm_ratios.py  # Golden TTM ratios from FMP
├── src/investment_researcher/
│   ├── config.py                   # Environment loading and path defaults
│   ├── metrics.py                  # TTM aggregation and derived metrics
│   ├── ratios.py                   # ~46-ratio registry and on-the-fly computation
│   ├── service.py                  # Auto-seed then serve Prefect deployments
│   ├── web/
│   │   ├── app.py                  # FastAPI REST API + chat endpoint
│   │   ├── chat.py                 # Agentic chat — Agent + Runner streaming
│   │   └── agent_tools.py          # 29 @function_tool wrappers for analytics + SEC research
│   ├── flows/
│   │   └── sec_data.py             # Seed, fast-path, and slow-path Prefect flows
│   └── ingestion/
│       ├── edgar/
│       │   ├── financials.py       # Slow-path companyfacts extraction
│       │   ├── fast_path.py        # Filing-level fast-path XBRL extraction
│       │   └── storage.py          # edgartools storage configuration
│       ├── state.py                # SQLite ingestion state (dedup, progress)
│       └── timeseries.py           # DuckDB schema initialization and writes
├── tests/                          # Unit, integration, and golden-data tests
│   └── fixtures/                   # Golden data fixtures (AAPL, NVDA, UNH, WMT, XOM)
└── data/                           # Local persistent data (git-ignored)
    ├── duckdb/
    ├── edgar/
    └── state/
```

## Prefect Schedules

`service.py` serves two deployments:

| Deployment | Schedule | Purpose |
|---|---|---|
| `sec-fast-path-daily` | Daily at 06:00 UTC | Download recent filings and extract filing-level XBRL |
| `sec-slow-path-weekly` | Sunday at 02:00 UTC | Refresh bulk metadata and re-extract all companyfacts |

## Data Model

### `financial_metrics` (primary table)

| Column | Type | Notes |
|--------|------|-------|
| `ticker` | VARCHAR | Company ticker symbol |
| `cik` | VARCHAR | SEC CIK number |
| `metric_type` | VARCHAR | e.g. `revenue`, `net_income`, `total_assets` |
| `value` | DOUBLE | Numeric value |
| `currency` | VARCHAR | Default `USD` |
| `period` | VARCHAR | Human-readable label, e.g. `Quarter Ended 09/30/2025` |
| `period_type` | VARCHAR | `quarterly` or `annual` |
| `period_end` | DATE | End date of the reporting period |
| `source` | VARCHAR | Filing form, e.g. `10-Q`, `10-K` |
| `accession` | VARCHAR | SEC accession number (fast-path only) |
| `ingested_at` | TIMESTAMP | Write timestamp |

Primary key: `(ticker, metric_type, period_type, period_end)`. Writes use `INSERT OR REPLACE` (upsert).

### `macro_timeseries` (reserved)

Schema exists for future macro-economic indicator ingestion; not yet populated by any flow.
