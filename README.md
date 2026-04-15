# Investment Researcher

Investment Researcher is a local SEC ingestion pipeline plus financial research platform.
It downloads SEC filing data via [edgartools](https://github.com/dgunning/edgartools), stores raw filings on disk, writes normalized financial metrics into DuckDB, computes on-the-fly ratios and TTM metrics, and serves scheduled Prefect flows for ongoing updates.

Three main workflows:

- Run the long-lived ingestion service with Docker Compose.
- Develop and test the ingestion and ratio code locally.
- Explore the populated DuckDB database with the multi-tab Streamlit analytics dashboard.

## Architecture

**Ingestion pipeline** — two extraction paths feed the same DuckDB `financial_metrics` table:

- **Fast path**: downloads recent 10-K and 10-Q filings, parses filing-level XBRL, and upserts new data. Runs daily.
- **Slow path**: refreshes bulk SEC metadata and re-extracts company facts to catch amendments, corrections, and coverage gaps. Runs weekly.

**Analytics layer** — on top of the raw metrics:

- `metrics.py` aggregates Trailing Twelve Months (TTM) metrics and derives computed values (EBITDA, FCF, gross profit, etc.).
- `ratios.py` computes ~46 financial ratios across 8 categories (profitability, returns, liquidity, leverage, efficiency, cash flow, per-share, other) entirely on-the-fly from DuckDB — ratios are never stored.

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
uv pip install -e ".[dev,demo]"
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

## Streamlit Demo

The demo is a multi-tab financial analytics dashboard that reads directly from DuckDB. Populate the database first (via Docker or a local seed run), then launch:

```bash
streamlit run src/investment_researcher/demo/app.py
```

**Dashboard tabs:**

| Tab | Contents |
|-----|----------|
| Income Statement | Revenue vs. net income trends, earnings waterfall, period detail table |
| Balance Sheet | Assets / liabilities / equity comparisons, composition breakdowns |
| Cash Flow | OCF / investing / financing flows, FCF trend, CapEx and dividends |
| Financial Health | Radar chart across 6 dimensions (profitability, ROE, liquidity, debt health, growth, cash generation) plus ratio cards with TTM deltas |
| Financial Ratios | All ~46 computed ratios organized by category with metric cards and time-series charts |
| Growth & Margins | YoY revenue and earnings growth, profitability margins trends, earnings quality (net income vs. OCF) |
| Quarterly Detail | Discrete 10-quarter breakdown with a TTM summary column |

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
│   ├── demo/
│   │   ├── app.py                  # 7-tab Streamlit analytics dashboard
│   │   └── data.py                 # DuckDB query helpers for the dashboard
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
