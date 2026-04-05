# Investment Researcher — SEC Data Pipeline

A data pipeline that fetches all SEC filing data via [edgartools](https://github.com/dgunning/edgartools), stores it locally for offline/fast access, and populates DuckDB with structured financial metrics for every SEC-filing company (~10,000+).

## Architecture

Two-path ingestion architecture:
- **Fast path (daily)**: Downloads recent 10-K/10-Q filings, parses XBRL directly → DuckDB. Catches new data immediately.
- **Slow path (weekly)**: Refreshes bulk companyfacts, re-extracts all ~10,000+ companies → DuckDB. Catches amendments and corrections.

## Prerequisites

- Docker & Docker Compose
- An email address for SEC EDGAR User-Agent identity

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and set EDGAR_IDENTITY to your email
```

### 2. Start with Docker Compose

```bash
docker compose up --build -d
```

This starts:
- **Prefect server** at http://localhost:4200 — monitoring dashboard
- **ir-service** — auto-detects empty state, seeds data, then serves scheduled deployments

### 3. Monitor

- Prefect dashboard: http://localhost:4200
- Check DuckDB data:
  ```bash
  docker compose exec ir-service python -c "
  import duckdb
  con = duckdb.connect('/app/data/duckdb/financial_timeseries.duckdb')
  print('Distinct tickers:', con.execute('SELECT COUNT(DISTINCT ticker) FROM financial_metrics').fetchone()[0])
  print('Total rows:', con.execute('SELECT COUNT(*) FROM financial_metrics').fetchone()[0])
  "
  ```

## Local Development

### Setup

```bash
# Create virtual environment
uv venv --python 3.12 .venv
source .venv/bin/activate

# Install with dev dependencies
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set EDGAR_IDENTITY
```

### Run tests

```bash
pytest tests/ -v
```

### Run extraction manually

```python
from investment_researcher.ingestion.edgar.storage import configure_edgar
from investment_researcher.ingestion.timeseries import initialize_db
from investment_researcher.ingestion.state import initialize_state_db
from investment_researcher.ingestion.edgar.financials import extract_company_facts

configure_edgar()
initialize_db()
initialize_state_db()

# Extract a single company
count = extract_company_facts("AAPL")
print(f"Extracted {count} metrics for AAPL")
```

### Run Prefect flows locally

```python
from investment_researcher.flows.sec_data import seed_flow, fast_path_flow

# Seed with a small subset
seed_flow(company_limit=10)

# Run fast path
fast_path_flow(days=1)
```

## Project Structure

```
├── docker-compose.yml          # Prefect server + ir-service
├── Dockerfile                  # ir-service image
├── pyproject.toml              # Python package definition
├── .env.example                # Environment template
├── src/investment_researcher/
│   ├── config.py               # Environment variable loading
│   ├── service.py              # Service entry point (auto-seed → deployments)
│   ├── ingestion/
│   │   ├── edgar/
│   │   │   ├── storage.py      # edgartools local storage setup
│   │   │   ├── financials.py   # Slow path: companyfacts → DuckDB
│   │   │   └── fast_path.py    # Fast path: per-filing XBRL → DuckDB
│   │   ├── timeseries.py       # DuckDB writer (financial_metrics table)
│   │   └── state.py            # SQLite state tracking
│   └── flows/
│       └── sec_data.py         # Prefect flows (seed, fast-path, slow-path)
├── tests/                      # Test suite
└── data/                       # Persistent data (Docker volume mount)
    ├── edgar/                  # edgartools local storage (~24 GB+)
    ├── duckdb/                 # DuckDB database
    └── state/                  # SQLite state tracking
```

## Schedules

| Flow | Schedule | What it does |
|------|----------|-------------|
| `sec-fast-path` | Daily 6 AM UTC | Process new 10-K/10-Q filings → DuckDB |
| `sec-slow-path` | Weekly Sunday 2 AM UTC | Refresh companyfacts → re-extract all companies |

## Data

- **DuckDB table**: `financial_metrics` — PK `(ticker, metric_type, period_type, period_end)`
- **Metrics**: revenue, net_income, eps, margins, assets, liabilities, cash flow, and 30+ more
- **Coverage**: All SEC-filing companies (~10,000+)
- **Both paths write safely**: `INSERT OR REPLACE` — upserts, never deletes absent rows
