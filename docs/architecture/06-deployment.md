# Deployment Architecture — AMD Workstation + MacBook Pro

## Overview

The platform runs on hardware you already own:

| Machine | Role | Specs |
|---------|------|-------|
| **AMD Workstation** | Docker host, GPU inference, all data storage | Ryzen 9 9950X3D, 64 GB DDR5, RTX 5090 32GB, 6TB NVMe (3×2TB) |
| **MacBook Pro M2 Pro** | Development terminal only | 14", 16 GB unified memory |

All Docker containers, databases, and raw data live on the AMD workstation. The MacBook connects via VS Code Remote SSH and SSH tunnels for UI access. No NAS is needed until Phase 5 (when total NVMe usage approaches 70% capacity ~4.2TB). See [Phase 5 NAS Migration](#nas-migration-phase-5) below.

## Deployment Topology

```
┌──────────────────────────────────────────────────────────────┐
│              AMD Workstation (Windows 11 + WSL2)              │
│                                                               │
│  Docker containers:                                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                │
│  │ FalkorDB   │ │  Langfuse  │ │ Langfuse   │                │
│  │ :6379 data │ │  Server    │ │ Postgres   │                │
│  │ :3000 UI   │ │  :3001     │ │ :5432      │                │
│  └────────────┘ └────────────┘ └────────────┘                │
│                                                               │
│  ┌────────────┐ ┌────────────┐                               │
│  │ Ingestion  │ │  Agent     │                               │
│  │ Worker     │ │  Runner    │                               │
│  └────────────┘ └────────────┘                               │
│                                                               │
│  GPU inference (bare metal):                                  │
│    vLLM → RTX 5090 (Qwen 32B / Llama 8B)                    │
│                                                               │
│  Local storage (6TB NVMe — 2 volumes: 2TB P41 + 4TB SN5000 RAID 0):        │
│    /data/edgar/    ← edgartools local storage (SEC metadata + filings)  │
│    /data/raw/      ← non-SEC raw files (PDFs, CSVs, news)               │
│    /data/duckdb/   ← financial time series                              │
│    /data/sqlite/   ← report queue + ingestion state                     │
│    /models/        ← LLM weights (~20GB)                                │
└──────────────────────────────────────────────────────────────┘
                │
                │ SSH + VS Code Remote SSH
                │ SSH tunnels for UI access
                │
┌──────────────────────┐
│  MacBook Pro M2 Pro  │
│  (Dev terminal only) │
│                      │
│  VS Code Remote SSH  │ → edits files on workstation
│  Terminal (SSH)      │ → runs CLI commands on workstation
│  Browser             │ → http://localhost:3000 (FalkorDB UI)
│                      │ → http://localhost:3001 (Langfuse)
└──────────────────────┘
```

## docker-compose.yml

```yaml
version: "3.8"

services:
  # ─── Graph Database ───────────────────────────────────
  falkordb:
    image: falkordb/falkordb:latest
    container_name: ir-falkordb
    ports:
      - "6379:6379"    # Redis protocol (data)
      - "3000:3000"    # Browser UI
    volumes:
      - ./data/falkordb:/data    # bind mount — path is always ./data/falkordb
    environment:
      - FALKORDB_ARGS=--maxmemory 16gb --save 60 1000
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ─── Observability: Langfuse ──────────────────────────
  langfuse-db:
    image: postgres:16-alpine
    container_name: ir-langfuse-db
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: langfuse
      POSTGRES_DB: langfuse
    volumes:
      - ./data/postgres:/var/lib/postgresql/data    # bind mount — path is always ./data/postgres
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5

  langfuse:
    image: langfuse/langfuse:latest
    container_name: ir-langfuse
    ports:
      - "3001:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET:-change-me-in-production}
      SALT: ${LANGFUSE_SALT:-change-me-in-production}
      NEXTAUTH_URL: http://localhost:3001
      TELEMETRY_ENABLED: "true"
      LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES: "true"
    depends_on:
      langfuse-db:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/public/health"]
      interval: 15s
      timeout: 10s
      retries: 5

# No named volumes — all data is in ./data/ subdirectories (bind mounts above)
```

## Environment Variables

```bash
# .env file (not committed to git)

# ─── OpenAI (primary LLM provider) ─────────────────────
OPENAI_API_KEY=sk-...

# ─── FalkorDB ──────────────────────────────────────────
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
FALKORDB_GRAPH_NAME=investment_graph

# ─── Langfuse ──────────────────────────────────────────
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-...          # Get from Langfuse UI after first setup
LANGFUSE_SECRET_KEY=sk-...          # Get from Langfuse UI after first setup
LANGFUSE_NEXTAUTH_SECRET=generate-a-random-secret
LANGFUSE_SALT=generate-a-random-salt

# ─── SEC EDGAR (via edgartools) ────────────────────────
EDGAR_IDENTITY=your@email.com                   # Required by edgartools for SEC rate limiting. Alternatively: set_identity("your@email.com") in codeEDGAR_LOCAL_DATA_DIR=./data/edgar                # edgartools local storage directory for offline operation. All SEC metadata, facts, and filings stored here
# ─── Data Source API Keys ──────────────────────────────
ALPHA_VANTAGE_API_KEY=...                       # Financial data
NEWSAPI_KEY=...                                 # News
POLYGON_API_KEY=...                             # Alternative financial data

# ─── Application Config ───────────────────────────────
LOG_LEVEL=INFO
REPORT_DB_PATH=./data/reports.db
INGESTION_DB_PATH=./data/ingestion.db
```

## Directory Structure

```
investment-researcher/
├── docker-compose.yml
├── pyproject.toml
├── .env                          # API keys (gitignored)
├── .env.example                  # Template
├── .gitignore
├── README.md
│
├── docs/
│   └── architecture/
│       ├── 00-strategic-rationale.md
│       ├── 01-system-overview.md
│       ├── 02-graph-schema.md
│       ├── 03-data-ingestion.md
│       ├── 04-agent-system.md
│       ├── 05-tech-stack.md
│       ├── 06-deployment.md
│       ├── 07-phased-roadmap.md
│       └── 08-hardware-requirements.md
│
├── schemas/
│   └── core_ontology.json        # Hand-crafted core graph ontology
│
├── src/
│   └── investment_researcher/
│       ├── __init__.py
│       ├── config.py             # Settings, env var loading
│       │
│       ├── graph/
│       │   ├── __init__.py
│       │   ├── connection.py     # FalkorDB connection management
│       │   ├── schema.py         # Schema creation (indexes, constraints)
│       │   ├── ontology.py       # Ontology loading + GraphRAG-SDK integration
│       │   └── queries.py        # Reusable Cypher query builders
│       │
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── scheduler.py      # APScheduler setup
│       │   ├── state.py          # Ingestion state tracking (SQLite)
│       │   ├── resolver.py       # Entity resolution logic
│       │   ├── preprocessor.py   # Docling wrapper
│       │   ├── timeseries.py     # DuckDB time series writer + snapshot recompute
│       │   ├── pipelines/
│       │   │   ├── __init__.py
│       │   │   ├── base.py       # Base pipeline class
│       │   │   ├── edgar.py      # SEC EDGAR pipeline
│       │   │   ├── financial.py  # Financial data API pipeline
│       │   │   ├── news.py       # News pipeline
│       │   │   ├── scraper.py    # Web scraping pipeline
│       │   │   ├── upload.py     # Manual upload pipeline
│       │   │   ├── congressional.py  # Congressional disclosure pipeline
│       │   │   ├── institutional.py  # 13F institutional holdings pipeline
│       │   │   └── policy.py         # Government & policy pipeline
│       │   └── loaders/
│       │       ├── __init__.py
│       │       ├── financials.py # Structured financial data fetcher (via edgartools)
│       │       └── structured.py # Structured data → Cypher loader
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── registry.py       # Agent creation and registration
│       │   ├── tools/
│       │   │   ├── __init__.py
│       │   │   ├── graph_tools.py    # query_graph, get_related_companies, etc.
│       │   │   ├── data_tools.py     # get_recent_news, get_macro_indicators, etc.
│       │   │   ├── financial_tools.py # get_financial_history (DuckDB queries)
│       │   │   └── report_tools.py   # write_report, get_existing_reports
│       │   ├── definitions/
│       │   │   ├── __init__.py
│       │   │   ├── triage.py
│       │   │   ├── data_monitor.py
│       │   │   ├── ripple_effect.py
│       │   │   ├── fundamental_screener.py
│       │   │   ├── macro_micro.py
│       │   │   └── research_synthesizer.py
│       │   ├── guardrails.py     # Input/output guardrails (bear case, source citations)
│       │   └── loop.py           # Autonomous agent loop (scheduler)
│       │
│       ├── reports/
│       │   ├── __init__.py
│       │   ├── models.py         # Report Pydantic models (includes bear_case, source_citations)
│       │   ├── store.py          # SQLite report queue (needs_review workflow)
│       │   └── viewer.py         # Report formatting for CLI
│       │
│       ├── paper_trades/         # Phase 4: Investment Decision Workflow
│       │   ├── __init__.py
│       │   ├── models.py         # PaperTrade Pydantic model
│       │   ├── tracker.py        # Auto-record paper trades, price snapshots
│       │   └── performance.py    # Hit rate, returns vs. SPY baseline
│       │
│       ├── feedback/             # Phase 7: Feedback Loop
│       │   ├── __init__.py
│       │   ├── tracker.py        # Prediction recording + outcome tracking
│       │   ├── calibration.py    # Confidence calibration analysis
│       │   ├── signal_analysis.py # Relationship type value analysis
│       │   └── bias_audit.py     # Confirmation bias detection
│       │
│       └── observability/
│           ├── __init__.py
│           └── setup.py          # Langfuse + OpenInference setup
│
├── cli.py                        # Typer CLI entry point
│
├── data/                         # Local data (gitignored — add data/ to .gitignore)
│   ├── edgar/                    # edgartools local storage (~24 GB metadata + filings)
│   │   ├── reference/            # Ticker and exchange data (~50 MB)
│   │   ├── companyfacts/         # Company financial facts from XBRL (~2 GB)
│   │   ├── submissions/          # Company metadata + filing indexes (~5 GB)
│   │   └── filings/              # Filing documents by date (~50-150 GB/year)
│   ├── falkordb/                 # FalkorDB RDB persistence (bind-mounted into container)
│   │   └── dump.rdb
│   ├── postgres/                 # Langfuse Postgres data (bind-mounted into container)
│   ├── duckdb/
│   │   └── financial_timeseries.duckdb
│   ├── sqlite/
│   │   ├── reports.db            # SQLite report queue
│   │   └── ingestion.db          # Ingestion state tracking
│   ├── raw/                      # Raw non-SEC source files (PDFs, CSVs, HTML)
│   └── uploads/                  # Manual upload staging
│
└── tests/
    ├── __init__.py
    ├── test_graph/
    ├── test_ingestion/
    ├── test_agents/
    └── test_reports/
```

## Running the System

### First-Time Setup

```bash
# 1. Clone and enter project
cd investment-researcher

# 2. Copy environment template
cp .env.example .env
# Edit .env with your API keys

# 3. Start infrastructure
docker compose up -d

# 4. Wait for services to be healthy
docker compose ps

# 5. Set up Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 6. Initialize graph schema
python -m investment_researcher.graph.schema

# 7. Verify setup
python cli.py health
```

### Day-to-Day Operations

```bash
# Start infrastructure (if not running)
docker compose up -d

# Run ingestion worker (foreground, for development)
python cli.py ingest --watch

# Run autonomous agent loop (foreground, for development)
python cli.py agents --autonomous

# Interactive CLI chat
python cli.py chat

# Thesis-driven research — explore an investment theory
python cli.py explore "Bitcoin will crash because post-quantum computing breaks ECDSA"
python cli.py explore "AI chip demand will exceed supply for 3 more years"

# View reports
python cli.py reports list
python cli.py reports view <report_id>

# Upload a document
python cli.py upload path/to/document.pdf --ticker AAPL

# Check system health
python cli.py health
```

### Monitoring

| Service | URL | Purpose |
|---------|-----|---------|
| FalkorDB Browser | http://localhost:3000 | Visual graph exploration, run Cypher |
| Langfuse Dashboard | http://localhost:3001 | LLM traces, costs, agent debugging |

## Resource Requirements

### AMD Workstation (Docker Host + GPU Inference)
- **CPU**: Ryzen 9 9950X3D (16 cores)
- **RAM**: 64 GB DDR5 — budget: FalkorDB 16 GB + Docker services 8 GB + OS/misc 8 GB + GPU inference 32 GB
- **Storage**: 6TB NVMe (2 volumes: 2TB P41 standalone + 4TB SN5000 RAID 0) — estimated usage by phase:

| Phase | Companies | Estimated Storage Used |
|-------|-----------|------------------------|
| Phase 0–1 | 50–100 | ~10–20 GB |
| Phase 2–3 | 100–500 | ~50–150 GB |
| Phase 4–5 | 500–5,000 | ~300–800 GB |
| Phase 5 (NAS trigger) | 5,000+ | >4.2 TB (70% of 6TB) → buy NAS |

- **GPU**: RTX 5090 32GB for vLLM inference (Qwen 32B, Llama 8B)

### MacBook Pro M2 Pro (Development Only)
- **Role**: VS Code Remote SSH, SSH tunnels for UI, git operations
- **Does NOT run**: Docker containers, vLLM, DuckDB (except ad-hoc read-only queries)
- **SSH tunnel setup** for UI access from MacBook:

```bash
# Forward workstation ports to MacBook localhost
ssh -L 3000:localhost:3000 -L 3001:localhost:3001 <workstation-ip> -N
# Then open: http://localhost:3000 (FalkorDB UI)
#            http://localhost:3001 (Langfuse UI)
```

## Storage Monitoring

Run this weekly inside WSL2 (or schedule with Windows Task Scheduler via `wsl -e bash -c "..."`):

```bash
# Alert when /data hits 70% capacity — time to plan NAS purchase
# Run inside WSL2 terminal
df -h /data | awk 'NR==2 {gsub("%","",$5); if ($5+0 > 70) \
  print "\u26a0️  Storage at " $5 "% — plan NAS purchase (Phase 5 trigger)"}'
```

> **Windows Task Scheduler alternative**: create a Basic Task that runs weekly and executes `wsl -e bash -c "df -h /data | awk '...'"` in PowerShell.

## NAS Migration (Phase 5)

**Trigger**: Total NVMe usage approaches 70% of combined capacity (~4.2TB across 6TB). The RAID 0 volume (4TB, no redundancy) is the most likely bottleneck—and also the highest data-loss risk on failure. Prioritise the NAS deployment once data on that volume is irreplaceable.

### What to Buy
10-bay NAS (e.g., Synology DS1821+) with 10 × 16TB drives in RAID 6 (~128TB usable). Cost ~$3,000–9,000 depending on drives. See [08-hardware-requirements.md](08-hardware-requirements.md) § Tier 2: NAS for full hardware spec, storage capacity analysis, and NAS selection criteria.

> **Windows + WSL2 note**: On Windows, the NAS is accessed via **SMB** (the native Windows protocol). All steps below run inside the **WSL2 terminal** (e.g., Ubuntu in Windows Terminal), where Docker bind mounts and all data paths live.

> **Why this is simple**: Because all Docker volumes are bind-mounted to `./data/`, there is no `docker volume inspect` or hidden path to hunt down. Everything lives in one known directory.

### Migration Steps

```bash
# ── On the NAS ─────────────────────────────────────────────────────────
# 1. Create shared folder: investment-researcher
# 2. Enable SMB/CIFS on the NAS (Synology: Control Panel > File Services > SMB)
# 3. Create a dedicated NAS user with read/write access to the share

# ── Inside WSL2 terminal on the workstation ────────────────────────────
# 4. Install CIFS utilities (one-time)
sudo apt-get install -y cifs-utils

# 5. Create mount point and mount the SMB share
sudo mkdir -p /mnt/nas
sudo mount -t cifs //<nas-ip>/investment-researcher /mnt/nas \
  -o username=<nas-user>,password=<nas-password>,uid=$(id -u),gid=$(id -g)

# 6. Flush FalkorDB to disk before stopping (while container is still running)
docker exec ir-falkordb redis-cli BGSAVE
sleep 10   # wait for background save to complete

# 7. Stop all services (no writes in flight during copy)
docker compose down

# 8. Copy all data in one command — everything is under ./data/
rsync -avh --progress ./data/ /mnt/nas/data/

# 9. Verify checksums on critical files
md5sum ./data/falkordb/dump.rdb
md5sum /mnt/nas/data/falkordb/dump.rdb

md5sum ./data/duckdb/financial_timeseries.duckdb
md5sum /mnt/nas/data/duckdb/financial_timeseries.duckdb
# (hashes must match)

# 10. Update docker-compose.yml bind mount paths from ./data/ to /mnt/nas/data/
#   falkordb:  ./data/falkordb  →  /mnt/nas/data/falkordb
#   postgres:  ./data/postgres  →  /mnt/nas/data/postgres

# 11. Update .env to point to new paths
# REPORT_DB_PATH=/mnt/nas/data/sqlite/reports.db
# INGESTION_DB_PATH=/mnt/nas/data/sqlite/ingestion.db
# DUCKDB_PATH=/mnt/nas/data/duckdb/financial_timeseries.duckdb

# 12. Restart and verify
docker compose up -d
python cli.py health

# 13. Make SMB mount permanent (add to WSL2's /etc/fstab)
echo "//<nas-ip>/investment-researcher /mnt/nas cifs username=<nas-user>,password=<nas-password>,uid=$(id -u),gid=$(id -g),_netdev 0 0" \
  | sudo tee -a /etc/fstab
```

> **Also map as a Windows network drive** (optional but convenient): In File Explorer, map `\\<nas-ip>\investment-researcher` as a drive letter (e.g., `Z:`). This gives Windows-side tools (e.g., VS Code file browser) direct access without going through WSL2.

### What Stays on Workstation After Migration
| Item | Stays on NVMe | Moves to NAS |
|------|-------------|-------------|
| Docker images | ✅ | |
| LLM model weights | ✅ (GPU inference needs fast local access) | |
| OS + code | ✅ | |
| FalkorDB data (`./data/falkordb/`) | | ✅ |
| DuckDB file | | ✅ |
| SQLite databases | | ✅ |
| Raw files (PDFs, CSVs) | | ✅ |

## Backup & Recovery

**Until NAS is purchased**, use a combination of an external USB drive (for raw files) and Backblaze B2 (for databases — ~$5/mo at this scale):

```bash
# Back up all data to external USB drive (weekly) — one command covers everything
rsync -avh --progress ./data/  /media/usb-backup/data/

# Or selectively back up just the critical databases
rsync -avh --progress ./data/falkordb/   /media/usb-backup/falkordb/
rsync -avh --progress ./data/duckdb/     /media/usb-backup/duckdb/
rsync -avh --progress ./data/sqlite/     /media/usb-backup/sqlite/

# Flush FalkorDB before backup to ensure dump.rdb is current
docker exec ir-falkordb redis-cli BGSAVE && sleep 10

# Backup Langfuse Postgres
docker exec ir-langfuse-db pg_dump -U langfuse langfuse > \
  /media/usb-backup/langfuse_$(date +%Y%m%d).sql
```

**After NAS is purchased (Phase 5)**, the NAS RAID 6 provides hardware redundancy. Keep external USB as a second backup for the databases.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| FalkorDB OOM | Increase `--maxmemory` in docker-compose, or reduce graph size |
| Langfuse not starting | Check Postgres is healthy first: `docker compose logs langfuse-db` |
| Slow graph queries | Check indexes exist: `CALL db.indexes()` in FalkorDB browser |
| High OpenAI costs | Check Langfuse cost dashboard, switch expensive agents to `gpt-4.1-mini` |
| Ingestion stalled | Check `data/ingestion.db` for error counts, reset with `python cli.py ingest --reset` |
