# Implementation Roadmap — Phased Delivery

> **Core principle — data quality first**: The project's success hinges on the quality of the data and our ability to extract, structure, and store it. Early phases focus on SEC filing extraction and data pipeline quality, not on validating whether the graph concept works (it obviously does when populated with quality data). See [00-strategic-rationale.md](00-strategic-rationale.md) for the full strategic analysis.

## Phase Overview

```
Phase 0 ──── Phase 1 ──── Phase 2 ──── Phase 3 ──── Phase 4 ──── Phase 5 ──── Phase 6 ──── Phase 7 ──── Phase 8
Data         SEC Filing   Financial    Relationship Agent        Scale &      Mac Studio  Feedback    Web UI
Foundation   Extraction   Data         Enrichment   System       Automate     Expansion   Loop
(Week 1-3)   (Week 4-6)   (Week 7-8)   (Week 9-11)  (Week 12-14) (Week 15-17) (Week 18+)  (Week 20+)  (Future)
│            │                                       │                        │
├─ FalkorDB + schema + CLI                           │                        │
├─ SEC EDGAR pipeline (10-K, 10-Q, 8-K, DEF 14A)    │                        │
│            RTX 5090 local LLM available ────────────┘                        │
│            (Qwen 32B, Llama 8B on workstation)      Monetization begins ─────┤
└─ Mac Studio purchase gate ───────────────────────────────────────────────────┘
```

> **Infrastructure**: AMD Workstation (RTX 5090 32GB, Ryzen 9 9950X3D, 64GB DDR5) is the Docker host, GPU inference machine, and primary storage (6TB NVMe: 2TB P41 + 4TB SN5000 RAID 0) — **already purchased**. MacBook Pro M2 Pro is the dev terminal only. No NAS needed until Phase 5 (NVMe total hits 70% capacity ~4.2TB). Mac Studio cluster is deferred to Phase 6+, gated on data pipeline maturity. See [08-hardware-requirements.md](08-hardware-requirements.md).

> **Build philosophy**: Every phase extends the previous one — no throwaway code. Phase 0 establishes the final package structure, CLI framework, and graph schema. Subsequent phases add to that foundation rather than replace it. The Phase 0 constraint is *scope* (50 semiconductor companies via SEC extraction), not code quality or structure. Development effort is front-loaded on data extraction quality.

---

## Phase 0: Data Foundation (Week 1-3)

**Goal**: Establish the project's permanent structure, graph schema, CLI framework, and SEC EDGAR data extraction pipeline. All data comes from real sources (SEC filings, XBRL) — no hand-seeded toy data. See [00-strategic-rationale.md](00-strategic-rationale.md) § Data Quality First.

### Scope
- ~50 companies in the **semiconductor** sector + their supply chain
- **SEC EDGAR pipeline**: Fetch and parse 10-K filings for target companies
- **Entity and relationship extraction**: LLM-based extraction from filing text → rich graph nodes and edges
- **XBRL financial data**: Structured extraction of revenue, net income, EPS from filing XBRL
- OpenAI API primary; optionally test local LLM on RTX 5090 (Qwen 2.5 32B) for extraction quality comparison
- Minimal infrastructure (FalkorDB + CLI on AMD workstation)
- **Full production structure from day one** — scope is narrow, but code is in its final home

### Tasks

#### Infrastructure & Project Structure
- [ ] `docker-compose.yml` with FalkorDB only (bind mount `./data/falkordb:/data` — same file Phase 1 extends by adding Langfuse)
- [ ] `pyproject.toml` with `investment_researcher` package, Typer, OpenAI Agents SDK, FalkorDB client — Phase 1 adds more deps, never restructures
- [ ] `.env.example` (OpenAI key only for now — Phase 1 adds Langfuse, Phase 2 adds data API keys)
- [ ] `src/investment_researcher/config.py` — env var loading (Phase 1 expands, never replaces)
- [ ] `src/investment_researcher/graph/connection.py` — FalkorDB connection + health check (Phase 1 adds retry logic)
- [ ] `src/investment_researcher/graph/schema.py` — core ontology: Company, Industry, Filing, NewsArticle (Phase 1 adds full schema + indexes)
- [ ] `cli.py` — Typer CLI with `chat` and `ingest` commands (Phase 1 adds `health` — same file throughout)

#### SEC EDGAR Pipeline (Core Development Focus)
- [ ] Company CIK/ticker lookup from EDGAR company index
- [ ] Filing fetcher: 10-K, 10-Q, 8-K for target companies (~50 initially)
  - EDGAR SEC-API or direct EDGAR FULL-TEXT search
  - Rate-limited, polite scraping (10 req/sec max)
  - Store raw filing HTML/XML in `data/raw/filings/`
- [ ] Filing preprocessor: HTML → clean markdown (MarkItDown or custom parser)
- [ ] **LLM-based entity extraction from 10-K text** (the hardest and most valuable task):
  - [ ] Supply chain extraction from "Customers" / "Suppliers" / "Risk Factors" sections
    - Extract: supplier/customer identity, product_category, dependency_level, is_sole_source
    - Source citation: accession number + section + page
  - [ ] Competitive dynamics from "Competition" section
    - Extract: competitor identity, market_segment, intensity, differentiation
  - [ ] Executive/board extraction from filing headers and DEF 14A
  - [ ] Industry/sector classification
  - [ ] Risk factor categorization (geopolitical, regulatory, supply chain, financial)
- [ ] XBRL parser for structured financial data (revenue, net income, EPS, etc.)
  - Write parsed metrics to Filing nodes and Company snapshot properties
- [ ] Filing → FalkorDB loader: create Filing nodes, link to Company, populate edge properties
- [ ] Ingestion state tracking (SQLite) — track which filings have been fetched/parsed/loaded
- [ ] CLI commands: `ingest edgar --ticker AAPL`, `ingest edgar --list top50`

#### Agent Tools & Basic Agent (For Interactive Querying)
- [ ] `src/investment_researcher/agents/tools/graph_tools.py` — `query_graph`, `get_company_profile`, `get_related_companies` using OpenAI Agents SDK `@function_tool` (Phase 4 adds more tools to this same file)
- [ ] `src/investment_researcher/agents/definitions/ripple_effect.py` — Ripple Effect Analyzer as a single OpenAI Agents SDK agent (Phase 4 adds Triage, Screener, etc.)
- [ ] `chat` command routes to Ripple Effect Analyzer for interactive graph exploration

### Validation Criteria

> **Note**: These are data quality milestones, not concept validation tests. The platform proves itself through data quality, not contrived comparisons with ChatGPT.

#### Data Extraction Quality
- [ ] `ingest edgar --ticker AAPL` fetches 10-K filing, extracts entities/relationships, and loads into FalkorDB
- [ ] Extracted SUPPLIES_TO relationships have rich edge properties: product_category, dependency_level, is_sole_source, source (with accession number)
- [ ] XBRL parser populates Company nodes with financial metrics: revenue_ttm, net_income, eps
- [ ] Spot-check: compare LLM-extracted supply chain data against manually reading the same 10-K section — extraction should capture the key relationships disclosed in the filing
- [ ] At least 10 companies with SEC-extracted data in the graph

#### Graph Quality
- [ ] `MATCH ()-[r:SUPPLIES_TO]->() RETURN count(r)` shows meaningful count (50+ from SEC extraction)
- [ ] Rich edge properties populated: `MATCH ()-[r:SUPPLIES_TO]->() WHERE r.product_category IS NOT NULL RETURN count(r)` > 50
- [ ] Filing nodes linked to companies: `MATCH (c:Company)-[:FILED]->(f:Filing) RETURN count(f)` > 10

#### Interactive Exploration
- [ ] `python cli.py chat "Who supplies Apple?"` returns data with source citations
- [ ] `python cli.py chat "What companies are affected if TSMC has a production disruption?"` returns multi-hop analysis using rich edge properties
- [ ] Graph in FalkorDB browser (localhost:3000) shows interconnected network

### Decision Framework

| Milestone | Assessment |
|-----------|------------|
| SEC pipeline extracts entities and relationships from 10-K filings with >80% accuracy | ✅ Core data extraction works — continue building |
| Extracted relationships include rich edge properties (product_category, dependency_level, source citations) | ✅ Pipeline is producing institutional-grade data — expand coverage |
| SEC extraction accuracy is <60% after reasonable tuning effort | ⚠️ Try different extraction methods (structured parsing, better prompts, different models) before giving up |
| After 50 companies with SEC-extracted data, multi-hop queries surface non-obvious cross-company connections | ✅ The pipeline + graph approach is working — proceed to Phase 1 |

### Deliverables
```
investment-researcher/
├── docker-compose.yml            ✓  (FalkorDB only — same file Phase 1 extends)
├── pyproject.toml                ✓  (investment_researcher package, final structure — Phase 1 adds deps)
├── .env.example                  ✓  (OPENAI_API_KEY only for now)
├── src/
│   └── investment_researcher/    ✓  (final package name — never restructured)
│       ├── __init__.py
│       ├── config.py             ✓  (env var loading)
│       ├── graph/
│       │   ├── connection.py     ✓  (FalkorDB connection + health check)
│       │   └── schema.py         ✓  (Company, Industry, Filing, NewsArticle + indexes)
│       ├── ingestion/
│       │   ├── edgar/
│       │   │   ├── fetcher.py    ✓  (EDGAR filing fetcher — 10-K, 10-Q, 8-K download)
│       │   │   ├── parser.py     ✓  (HTML → markdown, section splitting)
│       │   │   ├── xbrl.py       ✓  (XBRL financial data extraction)
│       │   │   └── extractor.py  ✓  (LLM-based entity/relationship extraction from filing text)
│       │   ├── loader.py         ✓  (Filing → FalkorDB node/edge writer)
│       │   └── state.py          ✓  (SQLite ingestion state tracker)
│       └── agents/
│           ├── tools/
│           │   └── graph_tools.py ✓ (query_graph, get_company_profile, get_related_companies — Phase 4 adds to this file)
│           └── definitions/
│               └── ripple_effect.py ✓ (single OpenAI Agents SDK agent — Phase 4 adds more agents here)
├── cli.py                        ✓  (Typer: chat, ingest edgar — Phase 1 adds health)
├── data/
│   ├── falkordb/                 ✓  (bind mount target — consistent with Phase 1+)
│   └── raw/filings/              ✓  (downloaded SEC filings — HTML/XML)
└── docs/data-quality-report.md   ✓  (SEC extraction accuracy, spot-check results)
```

### Cost Estimate
- **Hardware**: AMD workstation already purchased (~$3,764) — runs all Docker services + GPU inference
- **API costs**: ~$50–$150 in OpenAI API calls for SEC filing extraction (LLM-based entity extraction from 10-K text is the main cost driver). Or significantly less if using local LLM on RTX 5090
- **Time**: 2–3 weeks (infrastructure: 1 week, SEC pipeline: 1–2 weeks)

---

## Phase 1: Foundation (Week 4-5)

**Goal**: Expand Phase 0 foundation — add observability, GraphRAG-SDK, manual upload, and optional local LLM. Improve SEC EDGAR pipeline based on Phase 0 extraction quality results. All additions extend Phase 0 files; nothing is replaced.

### Tasks
- [ ] Expand `docker-compose.yml` — add Langfuse + Postgres services (FalkorDB section unchanged)
- [ ] Expand `pyproject.toml` — add Langfuse, GraphRAG-SDK, MarkItDown deps
- [ ] Expand `.env.example` — add Langfuse keys, workstation config
- [ ] Expand `src/investment_researcher/graph/connection.py` — add retry logic, connection pooling
- [ ] Expand `src/investment_researcher/graph/schema.py` — add full schema, all indexes, constraints
- [ ] Add `src/investment_researcher/graph/ontology.py` — ontology loading + GraphRAG-SDK integration
- [ ] Add `schemas/core_ontology.json` — hand-crafted core graph ontology
- [ ] Add `src/investment_researcher/observability/setup.py` — Langfuse + OpenInference instrumentation
- [ ] Add `src/investment_researcher/ingestion/preprocessor.py` — MarkItDown wrapper
- [ ] Expand `cli.py` — add `health` command (chat command already exists from Phase 0)
- [ ] Manual document upload via CLI (MarkItDown → GraphRAG-SDK → FalkorDB)
- [ ] **[Optional]** Local LLM inference stack on RTX 5090:
- [ ] **[Optional]** Local LLM inference stack on RTX 5090:
  - [ ] vLLM (primary) or llama.cpp (fallback) with CUDA
  - [ ] Qwen 2.5 32B Q4_K_M (~20 GB VRAM, 30-50 tok/s) for KG construction + agents
  - [ ] Llama 3.1 8B Q8 (~9 GB VRAM, 100-150 tok/s) for triage/routing
  - [ ] OpenAI-compatible API endpoint at `http://localhost:8000/v1`
  - [ ] LiteLLM configuration to switch between OpenAI API and local models
  - [ ] Benchmark: local Qwen 32B vs. GPT-4.1 quality on test queries

### Validation Criteria
- `docker compose up -d` starts all services cleanly on AMD workstation
- `python cli.py health` reports all services green
- Upload a test PDF → entities appear in FalkorDB browser (localhost:3000)
- `python cli.py chat` → ask a question → get a response from the graph
- Langfuse dashboard (localhost:3001) shows traces for the chat interaction
- **[If local LLM enabled]** Queries routed to local Qwen 32B produce acceptable quality

### Deliverables
```
src/investment_researcher/
├── config.py                 ← Phase 0 (expanded)
├── graph/
│   ├── connection.py         ← Phase 0 (expanded with retry logic)
│   ├── schema.py             ← Phase 0 (expanded with full schema)
│   └── ontology.py           ✓ NEW — GraphRAG-SDK integration
├── observability/
│   └── setup.py              ✓ NEW — Langfuse instrumentation
├── agents/tools/
│   └── graph_tools.py        ← Phase 0 (unchanged — Phase 4 expands)
├── agents/definitions/
│   └── ripple_effect.py      ← Phase 0 (unchanged — Phase 4 adds peers)
└── ingestion/
    ├── preprocessor.py       ✓ NEW — MarkItDown wrapper
    └── inference/            ✓ NEW (optional)
        ├── server.py         ✓ (vLLM / llama.cpp launcher)
        └── models.py         ✓ (model registry + config)
cli.py                        ← Phase 0 (expanded: health command added)
```

---

## Phase 2: Data Ingestion MVP (Week 6-8)

**Goal**: Scale SEC EDGAR pipeline from Phase 0's initial 50 companies to ~100. Add DuckDB time series store, financial data API pipelines, and macro indicators. The SEC EDGAR pipeline (fetcher, parser, XBRL, extractor) already exists from Phase 0 — this phase is about scaling it and adding complementary data sources.

### Tasks
- [ ] **DuckDB time series store setup**:
  - [ ] Initialize `data/financial_timeseries.duckdb` with schema (see [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store)
  - [ ] `financial_metrics` table (ticker, metric_type, value, period, period_end, accession)
  - [ ] `macro_timeseries` table (FRED/WorldBank/BLS indicators)
  - [ ] Snapshot recompute logic: DuckDB window functions → FalkorDB Company node properties
  - [ ] `get_financial_history` tool with `lru_cache` (growth rates computed at query time)
- [ ] SEC EDGAR pipeline — **scale from Phase 0**:
  - [ ] ~~Company CIK/ticker lookup from EDGAR company index~~ ✅ Phase 0
  - [ ] ~~Filing fetcher (10-K, 10-Q, 8-K for tracked companies)~~ ✅ Phase 0
  - [ ] ~~MarkItDown conversion for filing HTML~~ ✅ Phase 0
  - [ ] Scale extraction to S&P 100 companies
  - [ ] Improve extraction prompts based on Phase 0 accuracy results
  - [ ] GraphRAG-SDK entity extraction from filings (augment LLM-based extraction from Phase 0)
  - [ ] ~~XBRL parser for structured financial data~~ ✅ Phase 0
  - [ ] Write financial metrics → DuckDB (`financial_metrics` table, `accession` column for provenance); recompute snapshot → FalkorDB Company node properties
- [ ] Financial data pipeline:
  - [ ] FMP or Polygon.io integration
  - [ ] Fundamental data fetcher (market cap, P/E, EPS, etc.)
  - [ ] Write time series → DuckDB; recompute latest snapshot → FalkorDB Company node
- [ ] FRED API integration for starter macro indicators (Fed Funds Rate, CPI, GDP)
- [ ] World Bank / IMF API integration for country economic data
- [ ] Region/Country nodes: GDP, growth, credit rating, trade balance
- [ ] Entity resolution: ticker/CIK-based dedup
- [ ] Ingestion state tracking (SQLite)
- [ ] CLI commands: `ingest edgar`, `ingest financials`, `ingest macro`, `ingest countries`
- [ ] Target list: Top 100 S&P 500 companies by market cap + G20 countries

> **Note**: Starter macro set here (5–10 key indicators). Full FRED indicator suite expands in Phase 3 per [03-data-ingestion.md](03-data-ingestion.md) build order.

### Validation Criteria
- `python cli.py ingest edgar --companies top100` completes successfully
- FalkorDB shows ~100 Company nodes with Filing relationships and snapshot metrics
- Company nodes have `revenue_ttm`, `pe_ratio`, `revenue_growth_yoy` populated
- DuckDB `financial_metrics` table has 20+ quarters of data for tracked companies
- `SELECT COUNT(*) FROM financial_metrics` → meaningful count (thousands of rows)
- MacroIndicator nodes show current Fed Funds Rate, CPI, GDP, etc.
- DuckDB `macro_timeseries` table has historical FRED data
- Region nodes populated for G20 countries with economic profiles
- `python cli.py chat "What is Apple's revenue trend?"` returns data-backed answer with trend
- `python cli.py chat "What is China's GDP growth?"` returns country data
- Ingestion is incremental: re-running skips already-processed filings

### Deliverables
```
src/investment_researcher/ingestion/
├── scheduler.py               ✓
├── state.py                   ✓
├── resolver.py                ✓
├── timeseries.py              ✓  (DuckDB writer + snapshot recompute)
├── pipelines/
│   ├── base.py                ✓
│   ├── edgar.py               ✓
│   ├── financial.py           ✓
│   ├── macro.py               ✓  (FRED + World Bank / IMF)
│   └── upload.py              ✓ (from Phase 1)
└── loaders/
    ├── xbrl.py                ✓
    └── structured.py          ✓
```

---

## Phase 3: Relationship Enrichment (Week 7-9)

**Goal**: Inter-company relationships populated. News pipeline running. Congressional disclosures flowing. The graph becomes a true network, not just isolated company profiles.

> **Scope discipline**: The tasks below are split into two tiers. **Tier 1** (this phase): News, supply chain, executives, competition, commodities, Congressional trades, company IR pages/press releases — the core relationship types needed to validate the Ripple Effect Analyzer. **Tier 2** (defer to Phase 5): 13F institutional holdings, government contracts, legislation/policy — valuable but not required for core validation. Complete Tier 1 before starting Tier 2. Resist the temptation to build everything at once.

### Tasks
- [ ] News pipeline:
  - [ ] NewsAPI or Finnhub integration
  - [ ] Article deduplication
  - [ ] LLM-based entity extraction + sentiment analysis
  - [ ] Impact scoring
  - [ ] Company-news relationship linking
  - [ ] Political/policy news detection and linking
- [ ] Company IR pages & press releases (Tier 1 — see [03-data-ingestion.md](03-data-ingestion.md) Pipeline 4):
  - [ ] RSS feed discovery for tracked companies (PRNewswire, BusinessWire, GlobeNewsWire)
  - [ ] Scrapy + RSS fetcher for IR pages and press release PDFs
  - [ ] LLM event classification (M&A, earnings, guidance, leadership, product launch)
  - [ ] GraphRAG-SDK entity extraction → NewsArticle, Filing, Person, Company nodes
  - [ ] Press-release-to-8-K reconciliation (link press release → filing when 8-K confirms)
  - [ ] Daily RSS polling cadence + weekly IR page deep scrape
- [ ] Supply chain relationship extraction:
  - [ ] From 10-K "Customers" / "Suppliers" sections (text mining)
  - [ ] From publicly available supply chain databases
  - [ ] From news articles mentioning supply relationships
  - [ ] **Populate edge properties**: product_category, dependency_level, is_sole_source, revenue_pct, contract_value_usd (see [03-data-ingestion.md](03-data-ingestion.md) § Edge Property Extraction Strategy)
- [ ] Executive/board member linking:
  - [ ] Extract from DEF 14A (proxy statement) filings
  - [ ] Link people across companies
- [ ] Competitive dynamics:
  - [ ] Industry peer grouping (GICS-based)
  - [ ] COMPETES_WITH relationships from filing text
  - [ ] **Populate edge properties**: market_segment, intensity, market_share_a/b, differentiation, threat_level (see [02-graph-schema.md](02-graph-schema.md) § COMPETES_WITH)
- [ ] Commodity dependencies:
  - [ ] Map key commodities to industries
  - [ ] Company-commodity relationships from filing risk factors
- [ ] Congressional investment disclosures:
  - [ ] Capitol Trades or Quiver Quantitative API integration
  - [ ] Legislator nodes + CongressionalTrade nodes
  - [ ] Committee assignment mapping (Congress.gov API)
  - [ ] Committee → Industry oversight relationships
  - [ ] Trade → Company linkage
- [ ] **[Tier 2 — defer to Phase 5]** Institutional holdings (13F):
  - [ ] EDGAR 13F filing parser (XML)
  - [ ] InstitutionalHolder nodes + HOLDS_POSITION relationships
  - [ ] Quarter-over-quarter change computation
  - [ ] Seed: Top 100 institutional filers by AUM

  > **Tier note**: Doc [03-data-ingestion.md](03-data-ingestion.md) classifies 13F as Tier 1 (Pipeline 7) due to its data importance. It is deferred here to Phase 5 for *implementation sequencing* — the Ripple Effect Analyzer can be validated without 13F data, and building the 13F parser is a separate engineering effort.

- [ ] **[Tier 2 — defer to Phase 5]** Government & policy data:
  - [ ] Congress.gov API for active bills + status tracking
  - [ ] Federal Register API for regulations/executive orders
  - [ ] Legislation nodes + AFFECTS relationships to industries
  - [ ] USAspending.gov for government contracts (> $1M)
- [ ] News pipeline scheduler (every 15-30 min)
- [ ] IR press release RSS polling (daily cadence)
- [ ] Full FRED macro indicator suite (expanding from Phase 2 starter set)
- [ ] CLI commands: `ingest news`, `ingest congressional`, `ingest ir-pages`, `graph stats`
- [ ] CLI commands (Tier 2, Phase 5): `ingest 13f`, `ingest policy`

### Validation Criteria (Tier 1)
- `MATCH ()-[r:SUPPLIES_TO]->() RETURN count(r)` → meaningful count
- `MATCH ()-[r:HAS_EXECUTIVE]->() RETURN count(r)` → executives linked across companies
- Shared board members detectable: `MATCH (c1)-[:HAS_BOARD_MEMBER]->(p)<-[:HAS_BOARD_MEMBER]-(c2)` returns results
- Congressional trade data flowing: Legislator + CongressionalTrade + Company linked
- News articles flowing in every 30 minutes
- IR press releases capturing announcements before 8-K filings arrive
- Press-release-to-8-K reconciliation linking correctly
- `python cli.py chat "Who supplies Apple?"` returns actual supplier data
- Graph in FalkorDB browser shows a rich interconnected network

> **Tier 2 validation** (deferred to Phase 5): Institutional holdings (HOLDS_POSITION), Legislation nodes with AFFECTS relationships, Government contracts linked to companies

---

## Phase 4: Agent System (Week 10-12)

**Goal**: Multi-agent system operational. Triage, Ripple Effect Analyzer, and Research Synthesizer working. CLl chat routes through agent system. Report queue receiving findings.

### Tasks
- [ ] Agent tools implementation (all in `agents/tools/` — expanding files created in Phase 0):
  - [ ] `query_graph` — ✅ Phase 0 (already in `graph_tools.py`, expand for full Cypher support)
  - [ ] `get_company_profile` — ✅ Phase 0 (already in `graph_tools.py`, expand with financial snapshot)
  - [ ] `get_related_companies` — ✅ Phase 0 (already in `graph_tools.py`, expand hop depth + filters)
  - [ ] `semantic_search_graph` — NEW: Vector similarity search (add to `graph_tools.py`)
  - [ ] `get_industry_peers` — NEW: Peer comparison (add to `graph_tools.py`)
  - [ ] `get_recent_news` — News retrieval with filters
  - [ ] `get_macro_indicators` — Macro data retrieval
  - [ ] `get_congressional_trades` — Congressional disclosure query
  - [ ] `get_institutional_holdings` — 13F holdings query *(stub until Phase 5 data pipeline)*
  - [ ] `get_policy_impacts` — Legislation/regulation query *(stub until Phase 5 data pipeline)*
  - [ ] `get_country_profile` — Country economic profile
  - [ ] `get_government_contracts` — Federal contract query *(stub until Phase 5 data pipeline)*
  - [ ] `write_report` — Report queue writer
  - [ ] `get_existing_reports` — Duplicate check
- [ ] Agent definitions (all in `agents/definitions/` \u2014 directory created in Phase 0):
  - [ ] Triage Agent (router) \u2014 NEW: add `triage.py`
  - [ ] Ripple Effect Analyzer \u2014 \u2705 Phase 0 (`ripple_effect.py` exists, expand for multi-agent handoffs)
  - [ ] Fundamental Screener (metric-based screening) \u2014 NEW: add `fundamental_screener.py`
  - [ ] Macro-Micro Linker (macro to company impact) \u2014 NEW: add `macro_micro.py`
  - [ ] Research Synthesizer (final report production) \u2014 NEW: add `research_synthesizer.py`
  - [ ] Data Monitor Agent (change detection) \u2014 NEW: add `data_monitor.py`
- [ ] Guardrails:
  - [ ] Input validation (Cypher injection prevention)
  - [ ] Output quality (report completeness check)
  - [ ] Hypothesis framing guardrail (ensure outputs are framed as hypotheses, not conclusions — see [00-strategic-rationale.md](00-strategic-rationale.md))
  - [ ] Bear case enforcement (every report must include disconfirming evidence / bear case)
  - [ ] Source citation enforcement (every claim must cite filing accession number, article URL, or Cypher query)
- [ ] Confidence decay across hops:
  - [ ] Implement hop-distance-based confidence discount (90% per hop)
  - [ ] Display confidence at each hop in ripple effect results
- [ ] Report queue (SQLite):
  - [ ] Report model (Pydantic) — includes `bear_case`, `source_citations`, `disconfirming_evidence` fields
  - [ ] SQLite store (CRUD)
  - [ ] CLI viewer
- [ ] Human review workflow:
  - [ ] Reports flagged as "needs_review" before action
  - [ ] CLI `reports review <id>` command to mark as reviewed/rejected
- [ ] Paper trading system:
  - [ ] PaperTrade model (see [04-agent-system.md](04-agent-system.md) § Investment Decision Workflow)
  - [ ] Auto-record paper trades for reports with confidence > 0.6
  - [ ] Price snapshot fetcher (30/60/90 day follow-up)
  - [ ] CLI: `paper-trades list`, `paper-trades review <id>`
  - [ ] CLI: `paper-trades performance` (hit rate, returns vs. SPY)
- [ ] CLI `chat` command routed through Triage Agent
- [ ] CLI `reports list` and `reports view` commands
- [ ] Thesis-driven research flow:
  - [ ] CLI `explore "thesis statement"` command
  - [ ] Triage Agent thesis detection and routing logic
  - [ ] Ripple Effect Analyzer thesis exploration mode (multi-directional: long, short, hedge)
  - [ ] Opportunity landscape report format (grouped by direction, ranked by confidence)
  - [ ] Domain expertise capture (user can annotate thesis with supporting reasoning)
- [ ] **Monetization — start revenue streams** (see [09-monetization-strategy.md](09-monetization-strategy.md)):
  - [ ] Newsletter (A1): Weekly research digest from agent reports — highest priority revenue stream
  - [ ] LLM Inference API (A3): Expose RTX 5090 spare capacity as OpenAI-compatible API
  - [ ] Open Source + Pro (A4): Public repo with core platform; Pro features gated
- [ ] **Personal Investment Policy checkpoints** (see [00-strategic-rationale.md](00-strategic-rationale.md) § Personal Investment Policy):
  - [ ] 90-day paper trading period before real capital deployment
  - [ ] 5% max single-position rule enforced in paper trading
  - [ ] Kill criteria tracking: false positive rate, maintenance hours/week

### Validation Criteria
- Ask via CLI: "What companies might be affected if TSMC has production issues?"
  - Triage → Ripple Effect Analyzer → traverses SUPPLIES_TO relationships
  - Returns analysis of direct + indirect impacts with reasoning
  - **Each impact includes confidence score decayed by hop distance**
  - **Report includes bear case ("why this might NOT play out")**
  - **All claims cite source: filing accession number, article URL, or Cypher query used**
- Ask: "Which tech companies look undervalued?"
  - Triage → Fundamental Screener → queries financial metrics
  - Returns ranked list with P/E, growth data
  - *(13F institutional positioning available after Phase 5 pipeline)*
- Ask: "How would rising interest rates affect the market?"
  - Triage → Macro-Micro Linker → traces rates to industries to companies
- Ask: "Which stocks are Congress members buying?"
  - Triage → Fundamental Screener → queries congressional trades
  - Returns recent trades with committee context
- **Thesis exploration** — run 3 thesis explorations end-to-end:
  - `explore "Bitcoin will crash because post-quantum computing breaks ECDSA"`
    - Must produce short, long, AND hedge candidates across at least 3 sectors
    - Must cross-reference Congressional trades for corroboration *(13F cross-reference after Phase 5)*
  - `explore "AI chip demand will exceed supply for 3 more years"`
    - Must map semiconductor supply chain AND downstream beneficiaries
  - `explore "Commercial real estate defaults will trigger regional bank failures"`
    - Must trace through LENDS_TO, HOLDS_ASSET relationships with confidence decay
  - Each must produce opportunity landscape with bear case per candidate
- All interactions traced in Langfuse with full handoff chains visible
- Reports appear in `python cli.py reports list` with "needs_review" status
- Reports include `bear_case` and `source_citations` fields
- First newsletter edition published from agent-generated reports
- LLM Inference API serving external requests (if demand exists)

---

## Phase 5: Scale & Automate (Week 13-15)

**Goal**: Scale to 5,000+ companies. All pipelines running on schedule. Autonomous agent loop running 24/7 on AMD workstation. System is self-operating.

### Tasks
- [ ] Scale company list to full S&P 500
- [ ] Scale to Russell 1000, then Russell 3000
- [ ] Scale to all SEC-filing public companies (~5,000+)
- [ ] Scale Congressional disclosures to full history (2012+)
- [ ] Scale IR pages/press releases to full tracked company list
- [ ] **[Phase 3 Tier 2]** Build + scale 13F institutional holdings pipeline (see Phase 3 deferred tasks)
- [ ] **[Phase 3 Tier 2]** Build + scale government & policy pipeline (see Phase 3 deferred tasks)
- [ ] Expand country economic data to 50+ countries
- [ ] Optimize ingestion for scale:
  - [ ] Batch processing for EDGAR API
  - [ ] Parallel pipeline execution
  - [ ] Rate limiting + exponential backoff
  - [ ] Error recovery and retry logic
- [ ] **Storage monitoring**: weekly cron alert when `/data` > 70% capacity (see [06-deployment.md](06-deployment.md) § Storage Monitoring)
- [ ] **NAS migration** (triggered when NVMe total hits 70% ~4.2TB):
  - [ ] Purchase 10-bay NAS (e.g., Synology DS1821+, 10×16TB RAID 6 ~128TB usable, ~$3,000–9,000 — see [08-hardware-requirements.md](08-hardware-requirements.md) § Tier 2: NAS)
  - [ ] SMB/CIFS mount in WSL2: `/mnt/nas/` on workstation
  - [ ] Migrate `/data/raw/`, DuckDB file, SQLite files to NAS (see [06-deployment.md](06-deployment.md) § NAS Migration)
  - [ ] Update `.env` and `docker-compose.yml` volume mounts
  - [ ] Verify checksums on critical databases post-migration
  - [ ] LLM weights stay on NVMe (GPU needs fast local access)
- [ ] Autonomous agent loop:
  - [ ] APScheduler-based trigger system
  - [ ] Data Monitor runs every 30 min
  - [ ] Fundamental screen every 6 hours
  - [ ] Macro check every 4 hours
  - [ ] Loop produces reports to queue without human intervention
- [ ] Web scraping pipeline expansion:
  - [ ] Supply chain databases
  - [ ] Additional company data sources (see [03-data-ingestion.md](03-data-ingestion.md) Tier 3 Enhancement Sources)
  - [ ] Weekly deep-scrape schedule
- [ ] Performance tuning:
  - [ ] FalkorDB memory optimization (workstation has 64 GB total — budget ~16 GB for graph)
  - [ ] Query performance profiling
  - [ ] LLM cost optimization (model tiering: local RTX 5090 for routine, OpenAI API for complex)
- [ ] Monitoring & alerting:
  - [ ] Ingestion health dashboard (via Langfuse custom metrics)
  - [ ] Agent performance metrics
  - [ ] Error rate tracking
  - [ ] RTX 5090 GPU utilization + thermal monitoring
- [ ] **Monetization scaling** (see [09-monetization-strategy.md](09-monetization-strategy.md)):
  - [ ] Signal Alerts (A2): Real-time alerts for high-confidence findings
  - [ ] Consulting (B3): Ad-hoc research requests for paying clients
  - [ ] Discord Community (B5): Paid community for research discussion
- [ ] CLI: `ingest --watch` (continuous mode), `agents --autonomous`

### Validation Criteria
- 5,000+ Company nodes in graph
- 500+ Legislator nodes with trade history
- Top 500 institutional holders with quarterly holdings
- Active legislation tracked with industry AFFECTS relationships
- All pipelines running on their cadences for 48+ hours without intervention
- Autonomous agent loop producing 5-15 reports per day
- Mean ingestion latency: < 30 min for news, < 24 hours for filings
- Langfuse shows stable costs and latencies
- No OOM crashes on FalkorDB (monitor workstation RAM: FalkorDB ~16 GB + Docker services + OS ≤ 64 GB)

---

## Phase 6: Mac Studio Expansion — Large Model Inference (Week 16+)

**Goal**: Expand inference capacity beyond RTX 5090 with Mac Studio cluster for 405B-class models and high-throughput concurrent inference. The RTX 5090 already handles local LLM inference (Qwen 32B, Llama 8B) from Phase 1 — this phase is about scaling to larger models and higher throughput. See [08-hardware-requirements.md](08-hardware-requirements.md) for full hardware specs.

> **Hardware purchase gate** (all 4 conditions from [08-hardware-requirements.md](08-hardware-requirements.md)):
> 1. The platform is producing valuable research insights consistently (Phase 5 paper trading validates)
> 2. Quantitative evidence that 32B models on RTX 5090 are insufficient (quality benchmarks show gap vs. GPT-4.1)
> 3. Revenue from monetization streams (see [09-monetization-strategy.md](09-monetization-strategy.md)) justifies the $8K–$20K Mac Studio investment
> 4. **OR**: Inference API monetization demand exceeds RTX 5090 capacity
>
> **Budget**: 1 Mac Studio M4 Ultra (192GB): ~$8,050. 2 Studios: ~$15,300. Full cluster (2-4): $15K–$20K. See [08-hardware-requirements.md](08-hardware-requirements.md) § Estimated Budget.

### Prerequisite: RTX 5090 Baseline (Already Running Since Phase 1)

Before expanding to Mac Studios, document the RTX 5090 inference baseline:

| Metric | RTX 5090 Result (from Phase 1-5) |
|--------|----------------------------------|
| KG construction quality (Qwen 32B vs. GPT-4.1) | _measured_ |
| Agent reasoning quality (Qwen 32B) | _measured_ |
| Throughput (batch ingestion tok/s) | _measured_ |
| API cost savings vs. OpenAI-only | _measured_ |
| Tasks still requiring OpenAI API fallback | _list_ |

> **Decision**: If RTX 5090 handles all workloads at acceptable quality, Mac Studios are not needed. Only proceed if the gap justifies the investment.

### Tasks
- [ ] Hardware setup:
  - [ ] Rack/shelf Mac Studios with adequate ventilation
  - [ ] Thunderbolt 5 direct connections between Mac Studios (RDMA)
  - [ ] 10 GbE connections to workstation and NAS
  - [ ] Verify RDMA connectivity and bandwidth (expect ~100+ Gbps)
- [ ] Inference stack setup:
  - [ ] Install exo on all Mac Studios (MLX backend for Apple Silicon)
  - [ ] Configure distributed inference across 2–4 units
  - [ ] Verify OpenAI-compatible API endpoint works from workstation containers
  - [ ] Test model partitioning (tensor parallelism across units)
- [ ] Model evaluation (run on Mac cluster):
  - [ ] Llama 3.1 405B (Q8, distributed across 2 Studios) for KG construction + complex agents
  - [ ] Llama 3.1 70B (Q8, single Studio) for NL→Cypher + entity extraction
  - [ ] Qwen 2.5 72B as alternative to Llama 70B
  - [ ] nomic-embed-text or mxbai-embed-large for embeddings
- [ ] Multi-tier model routing (workstation + Mac cluster):
  - [ ] RTX 5090: Llama 8B (triage) + Qwen 32B (routine agents) — existing
  - [ ] Mac Studio: 405B (complex reasoning, KG construction) — new
  - [ ] LiteLLM routing: model-aware dispatch to correct endpoint
  - [ ] `LLM_API_BASE` for Mac cluster: `http://mac-studio-1.local:8000/v1`
  - [ ] Workstation endpoint remains at `http://localhost:8000/v1`
- [ ] Benchmark: quality comparison (Mac 405B vs. RTX 5090 Qwen 32B vs. GPT-4.1)
- [ ] Benchmark: latency (expect ~5-20 tokens/sec for 405B on 2 Studios)
- [ ] Benchmark: throughput for batch ingestion with both tiers active
- [ ] Monitoring: Mac Studio thermals, memory utilization, inference throughput

### Validation Criteria
- 405B model produces measurably better output than Qwen 32B on complex reasoning tasks
- KG construction quality within acceptable range vs. GPT-4.1
- Autonomous loop runs for 48+ hours with multi-tier inference without degradation
- OpenAI API costs reduced to near-zero (or zero)
- Latency acceptable (< 60s for 405B agent responses, < 15s for 70B)
- All Mac Studios stable under sustained load (thermals, no throttling)
- Total inference capacity supports concurrent batch ingestion + interactive queries + API monetization

### Key Risks
- **RTX 5090 may be sufficient**: 32B models may match 405B quality for this domain. If so, Mac Studios are unnecessary. This is a *good* outcome — save the money
- **KG construction quality**: 405B models should match GPT-4.1 closely. 70B may have a quality gap. Mitigation: Use 405B for KG construction, 70B for simpler tasks
- **Token throughput**: 405B distributed across 2 units is slower than API calls (~5-20 tok/s). Batch processing compensates. 4 units doubles throughput
- **Thermal management**: Sustained inference generates significant heat. Ensure adequate ventilation (see hardware doc)
- **exo maturity**: Distributed inference framework is still relatively new. Have llama.cpp RPC as fallback

---

## Phase 7: Feedback Loop & Calibration (Week 18+)

**Goal**: Close the loop between predictions and outcomes. Track report accuracy, calibrate confidence thresholds, and continuously improve agent reasoning quality. See [00-strategic-rationale.md](00-strategic-rationale.md) — "the moat is in institutional knowledge: understanding which patterns produce actionable signals vs. noise."

### Tasks
- [ ] Prediction tracking system:
  - [ ] Record agent predictions with timestamps, confidence scores, and tickers
  - [ ] Track actual outcomes (price moves, earnings results) against predictions
  - [ ] Compute hit rate by report type, confidence bucket, and agent
  - [ ] Dashboard: "How accurate is the system?" with Brier score or similar calibration metric
- [ ] Confidence calibration:
  - [ ] Analyze: are 0.7-confidence reports actually correct 70% of the time?
  - [ ] Adjust confidence thresholds based on empirical accuracy
  - [ ] Tune hop-distance confidence decay factor (starting at 0.9/hop)
- [ ] Signal vs. noise analysis:
  - [ ] Which relationship types produce the most alpha? (supply chain vs. shared exec vs. political)
  - [ ] Which data sources have highest signal-to-noise ratio?
  - [ ] Prune low-value auto-detected relationships from the graph
- [ ] Agent prompt refinement:
  - [ ] Update agent instructions based on observed reasoning failures
  - [ ] Add few-shot examples from successful past analyses
  - [ ] Strengthen bear-case generation for agents that under-report risks
- [ ] Ontology refinement:
  - [ ] Review and promote validated RELATED_TO edges to named relationship types
  - [ ] Archive low-confidence, low-value relationships
  - [ ] Add new relationship types discovered through agent analysis
- [ ] Anti-confirmation-bias measures:
  - [ ] Track ratio of bull vs. bear reports — flag if heavily skewed
  - [ ] Audit: are agents seeking disconfirming evidence effectively?
  - [ ] Periodic "red team" sessions: test with scenarios where the graph should find nothing
- [ ] Historical backtesting:
  - [ ] Select 3–5 major market events from 2023–2025 (e.g., SVB collapse, AI rally, rate cut cycle)
  - [ ] Load pre-event data into a separate graph instance
  - [ ] Run agent system against pre-event state
  - [ ] Compare agent predictions vs. actual outcomes
  - [ ] Compute: would following the system's recommendations have generated alpha vs. SPY?
  - [ ] Document which relationship types and reasoning chains were most/least accurate
  - [ ] Use results to refine agent prompts, confidence thresholds, and relationship weights
  - [ ] **Critical**: Use blind selection of events (don't cherry-pick favorable cases)

### Validation Criteria
- Prediction tracking covers 100+ reports with outcome data
- Confidence calibration curve plotted (predicted confidence vs. actual accuracy)
- At least one confidence threshold adjustment made based on empirical data
- Signal analysis identifies top 3 and bottom 3 relationship types by predictive value
- At least 5 agent prompt improvements deployed based on failure analysis
- RELATED_TO → named relationship promotion rate tracked (target: >20% of validated edges promoted)

### Deliverables
```
src/investment_researcher/
├── feedback/
│   ├── tracker.py          ✓  (prediction recording + outcome tracking)
│   ├── calibration.py      ✓  (confidence calibration analysis)
│   ├── signal_analysis.py  ✓  (relationship type value analysis)
│   └── bias_audit.py       ✓  (confirmation bias detection)
└── reports/
    └── models.py           ✓  (updated: outcome_actual, accuracy fields)
```

---

## Phase 8: Web UI (Future)

**Goal**: Browser-based dashboard for exploring reports, graph, and interactive chat.

### Tasks (Rough)
- [ ] Framework selection (Next.js, or Python-based like Streamlit/Gradio for simplicity)
- [ ] Report dashboard:
  - [ ] List reports with filters (date, type, confidence, ticker)
  - [ ] Report detail view
  - [ ] Mark reports as reviewed/archived
- [ ] Interactive chat:
  - [ ] Chat interface connected to Triage Agent
  - [ ] Conversation history
  - [ ] Streaming responses
- [ ] Graph visualization:
  - [ ] Interactive graph explorer (vis.js, D3, or Cytoscape)
  - [ ] Click company → see connections
  - [ ] Highlight ripple effect paths
- [ ] Portfolio tracking:
  - [ ] Mark companies as "watching"
  - [ ] Priority alerts for watched companies

### Not in Scope (Yet)
- Trade execution
- Portfolio management
- Backtesting
- Real-time price data streaming
- Mobile app

---

## Summary Timeline

| Phase | Duration | Key Milestone |
|-------|----------|---------------|
| 0. Data Foundation | Week 1-3 | Graph schema, SEC EDGAR extraction pipeline, XBRL financials. Data quality is the validation |
| 1. Foundation + Local LLM | Week 4-5 | Docker on AMD workstation, observability, GraphRAG-SDK, improved extraction. Optional: RTX 5090 local inference (Qwen 32B) |
| 2. Ingestion MVP | Week 6-8 | Scale to 100 companies + G20 countries. DuckDB time series, financial data APIs, macro indicators |
| 3. Relationships | Week 9-11 | Supply chain, executives, news, Congressional trades, IR pages/press releases (Tier 1). 13F + legislation deferred to Phase 5 |
| 4. Agent System | Week 12-14 | Multi-agent ripple analysis, reports (bear cases + source citations), paper trading begins. **Monetization starts**: newsletter, LLM API, open source |
| 5. Scale & Automate | Week 15-17 | 5,000+ companies, Tier 2 pipelines (13F, legislation, gov contracts), 24/7 autonomous on workstation |
| 6. Mac Studio Expansion | Week 18+ | 405B models for complex reasoning. **Mac Studio purchase gate**: only buy after Phase 5 validates + RTX 5090 proven insufficient |
| 7. Feedback Loop | Week 20+ | Prediction tracking, confidence calibration, historical backtesting, signal vs. noise |
| 8. Web UI | Future | Browser dashboard for reports + graph exploration |

### Budget Summary

| Item | Cost | Status |
|------|------|--------|
| AMD Workstation (RTX 5090, Ryzen 9 9950X3D, 64GB DDR5) | ~$3,764 | **Already purchased** |
| MacBook Pro M2 Pro 14" | Owned | **Already owned** |
| NAS (10-bay, RAID 6, ~128TB usable) | ~$3,000–9,000 | Phase 5 (triggered by storage) |
| Mac Studio cluster (1–2 units, if validated) | ~$8,050–15,300 | Phase 6+ (gated) |
| **Phase 0–4 total (workstation only)** | **~$3,764** | Already purchased |
| **Phase 0–5 total (workstation + NAS)** | **~$6,764–12,764** | |
| **Phase 0–8 total (if Mac Studios purchased)** | **~$14,814–28,064** | |

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **SEC extraction pipeline fails — can't extract quality data from filings** | Critical | Medium | Try different extraction methods: structured parsing, better prompts, different models, GraphRAG-SDK. If filings can't be machine-read reliably, the entire premise collapses |
| **Building agents before data quality** | High | High | Phase 0 focuses on data extraction, not agents. Don't build sophisticated agent orchestration until the graph has quality data from SEC filings |
| **Graph noise overwhelms signal** | High | Medium | Confidence thresholds, multi-source corroboration, Phase 7 signal analysis to prune low-value relationships |
| **Confirmation bias amplification** | High | Medium | Bear case requirement in every report, Phase 7 bias auditing, explicit disconfirming evidence instructions |
| **FalkorDB OOM at 5K+ companies** | High | Medium | Monitor memory, prune old data. Workstation has 64 GB RAM total; budget ~16 GB for FalkorDB via `--maxmemory` |
| **OpenAI API cost overruns** | Medium | Medium | RTX 5090 local inference (Qwen 32B, Llama 8B) available from Phase 1. Use local models for routine tasks, API for complex only. Daily cost caps |
| **EDGAR rate limiting** | Medium | Medium | Polite scraping, queue + backoff, cache aggressively |
| **Poor entity resolution** | High | Medium | Multiple resolution strategies, human review of edge cases. Separate resolvers for companies, legislators, institutions |
| **Confidence decay compounds errors** | High | Medium | Use CIK/bioguide_id/CUSIP as ground-truth anchors. Prefer structured data over LLM extraction for critical relationships |
| **LLM reasoning errors become investment losses** | Critical | Medium | All outputs are hypotheses requiring human review. Source citations mandatory. Track prediction accuracy in Phase 7 |
| **GraphRAG-SDK ontology drift** | Medium | Medium | Regular ontology review, promote RELATED_TO to named types |
| **RTX 5090 32B models can't match GPT-4.1 quality** | Medium | Medium | Benchmark Qwen 32B vs. GPT-4.1 in Phase 1. If gap is significant for critical tasks, use hybrid: local for routine, API for complex. Mac Studio expansion (405B) is Phase 6 fallback |
| **RTX 5090 thermal/power under sustained load** | Medium | Medium | GPU power limit at 400W (vs. 575W TDP), monitor thermals, adequate case airflow. See [08-hardware-requirements.md](08-hardware-requirements.md) |
| **Mac Studio thermal throttling** | Medium | Medium | Dedicated ventilated space, monitor thermals, stagger batch jobs. Only relevant if Phase 6 gate passed |
| **exo/RDMA stability issues** | Medium | Medium | Fallback to llama.cpp RPC backend or single-node inference on largest Studio. Only relevant for Phase 6+ |
| **Survivorship bias in evaluation** | Medium | High | Track forward-looking accuracy in Phase 7. Don't cherry-pick favorable examples when evaluating extraction quality |
| **Maintenance burden** | Medium | High | Data pipelines break, APIs change, LLMs degrade. Budget ongoing maintenance. Not a "build once, run forever" system |
| **News API costs at scale** | Low | Medium | Switch to RSS feeds, use free tiers strategically |
| **No investment workflow** | High | Medium | Paper trading from Phase 4. Without tracking outcomes, no way to know if the system works. See [04-agent-system.md](04-agent-system.md) § Investment Decision Workflow |
| **Scope creep in Phase 2-3** | High | High | Tier 1/Tier 2 discipline. Complete core pipelines before adding 13F, legislation, gov contracts. Each pipeline is a separate engineering challenge |
| **Stale relationships treated as current** | High | High | Staleness decay on relationships (see [02-graph-schema.md](02-graph-schema.md) § Staleness decay). Supply chain relationships from 2-year-old 10-K filings may no longer hold |
| **Hardware purchased before validation** | High | Medium | AMD workstation already purchased (~$3,764). Mac Studio purchase gate at Phase 6 with 4 conditions (see above). Don't buy $8K–$20K in Mac Studios until Phase 5 validates + RTX 5090 proven insufficient |
