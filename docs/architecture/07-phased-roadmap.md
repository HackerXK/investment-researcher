# Implementation Roadmap — Phased Delivery

> **Core principle — data quality first**: The project's success hinges on the quality of the data and our ability to extract, structure, and store it. Early phases focus on SEC filing extraction and data pipeline quality, not on validating whether the graph concept works (it obviously does when populated with quality data). See [00-strategic-rationale.md](00-strategic-rationale.md) for the full strategic analysis.

---

## Specification Authority — Binding Document References

> **This section establishes binding relationships between this roadmap and the detailed design documents.** When implementing any task in this roadmap, the referenced design docs are **authoritative specifications, not optional reading**. If a task says "per 02-graph-schema.md", the implementation **MUST** match the schema defined there — do not invent properties, rename fields, change types, or omit fields that the spec defines.

### Document Hierarchy

| Document | Authority Over | How to Use |
|----------|---------------|------------|
| [02-graph-schema.md](02-graph-schema.md) | All node types, node properties, relationship types, relationship edge properties, indexes, DuckDB schema, temporal modeling, confidence/staleness rules | **Copy property lists verbatim** when implementing nodes/edges. Do not add, remove, or rename properties unless the spec changes first |
| [03-data-ingestion.md](03-data-ingestion.md) | Pipeline architecture, source URLs/APIs, rate limits, data flow (Source → DuckDB → FalkorDB snapshot), entity resolution strategy, tier classification | **Follow pipeline steps exactly** as numbered. Use the specified APIs, endpoints, and field mappings |
| [04-agent-system.md](04-agent-system.md) | Agent definitions (names, instructions, tools, handoffs, model assignments), tool function signatures, report schema, investment decision workflow | **Use the exact agent names, tool signatures, and instruction text** defined there. The Python code blocks are implementation specs, not pseudocode |
| [00-strategic-rationale.md](00-strategic-rationale.md) | Hypothesis framing, bear case requirements, confidence principles, data quality philosophy | Every agent output and report format must enforce these principles |
| [05-tech-stack.md](05-tech-stack.md) | Library choices, framework versions, infrastructure decisions | Use the specified libraries and versions. Do not substitute without updating the spec first |

### Implementation Rules

1. **Schema is law**: When a task says to create a node type (e.g., Company, Filing, Person), implement it with **every property listed** in [02-graph-schema.md](02-graph-schema.md) § Core Node Types. Do not invent new properties or omit existing ones.

2. **Edge properties are mandatory**: Relationship types in [02-graph-schema.md](02-graph-schema.md) § Core Relationships define rich edge properties (e.g., SUPPLIES_TO has 15+ properties including `product_category`, `dependency_level`, `is_sole_source`, `geographic_risk`, etc.). Implement **all specified properties**. These are what differentiate institutional-grade analysis from surface-level outputs.

3. **DuckDB schema is exact**: The `financial_metrics` and `macro_timeseries` table schemas in [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store define exact column names, types, and primary keys. Use them verbatim.

4. **Agent definitions are specs**: The Python code blocks in [04-agent-system.md](04-agent-system.md) § Agent Definitions are implementation specifications. Use the exact `name`, `instructions`, `tools` list, `handoffs` list, and `model` assignment for each agent.

5. **Tool signatures are contracts**: The `@function_tool` decorated functions in [04-agent-system.md](04-agent-system.md) § Agent Tools define the exact function names, parameter names, parameter types, and docstrings. Implement them as specified.

6. **Pipeline steps are ordered**: The numbered pipeline steps in [03-data-ingestion.md](03-data-ingestion.md) define the exact processing sequence. Follow the step numbers and data flow arrows.

7. **When in doubt, read the spec**: If this roadmap gives a brief task description and the design doc gives a detailed specification, **the design doc wins**. This roadmap defines *what to build and when*; the design docs define *exactly how to build it*.

---

## Phase Overview

```
Phase 0 ──── Phase 1 ──── Phase 2 ──── Phase 3 ──── Phase 4 ──── Phase 5 ──── Phase 6 ──── Phase 7 ──── Phase 8
SEC Data     Company      Knowledge    External     Agent        Observ. &    Scale &      Mac Studio  Feedback
Pipeline     Profiles +   Graph +      Data         System       RAG          Automate     Expansion   Loop
             Chat UI      Extraction   Sources
(Week 1-2)   (Week 3-6)   (Week 7-10)  (Week 11-13) (Week 14-16) (Week 17-19) (Week 20-22) (Week 23+)  (Week 25+)
│            │            │                          │                         │
├─ Prefect + edgartools   │                          │                         │
│  local storage + DuckDB │                          │                         │
│            ├─ Simply Wall St-style web UI          │                         │
│            ├─ Chat (local LLM + full-context)      │                         │
│            │            ├─ FalkorDB + entity extraction                      │
│            │            │            RTX 5090 local LLM ─────────────────────┤
│            │            │            (Qwen 32B, Llama 8B)                    │
│            │            │                          Monetization begins ──────┤
└─ Mac Studio purchase gate ──────────────────────────────────────────────────┘
```

> **Infrastructure**: AMD Workstation (RTX 5090 32GB, Ryzen 9 9950X3D, 64GB DDR5) is the Docker host, GPU inference machine, and primary storage (6TB NVMe: 2TB P41 + 4TB SN5000 RAID 0) — **already purchased**. MacBook Pro M2 Pro is the dev terminal only. No NAS needed until Phase 6 (NVMe total hits 70% capacity ~4.2TB). Mac Studio cluster is deferred to Phase 7+, gated on data pipeline maturity. See [08-hardware-requirements.md](08-hardware-requirements.md).

> **Build philosophy**: Every phase extends the previous one — no throwaway code. Phase 0 establishes the data pipeline with Prefect and edgartools, populating DuckDB for all SEC-filing companies. Phase 1 builds a Simply Wall St-style web UI and chat interface on top of that data — all strictly from SEC filings. Subsequent phases add the knowledge graph, external data sources, and multi-agent intelligence layer.

---

## Phase 0: SEC Data Pipeline (Week 1-2)

**Goal**: Build a reliable, scheduled pipeline that fetches all SEC filing data via edgartools, stores it locally for offline/fast access, and populates DuckDB with structured financial metrics for every SEC-filing company. No UI, no graph, no LLM — just rock-solid data ingestion with Prefect orchestration.

### Scope
- **All SEC-filing companies** (~10,000+) — not a subset
- **edgartools local storage**: `download_edgar_data()` for metadata (~24 GB: submissions, companyfacts, reference) + `download_filings()` for filing documents (configurable year range, e.g., last 3-5 years)
- **DuckDB**: Structured financial metrics extracted from edgartools XBRL data (`company.get_financials()`, `company.get_facts()`)
- **Prefect**: Task orchestration with monitoring dashboard, scheduled flows, failure alerting — foundation for all future ingestion pipelines
- **No UI, no graph, no chat** — Phase 1 adds those

### Tasks

#### Project Scaffolding
- [ ] `pyproject.toml` with `investment_researcher` package, edgartools, DuckDB, Prefect, Typer — **MUST use libraries specified in [05-tech-stack.md](05-tech-stack.md)**
- [ ] `.env.example` — `EDGAR_IDENTITY`, `EDGAR_LOCAL_DATA_DIR=~/edgar-offline`, `PREFECT_API_URL`
- [ ] `src/investment_researcher/config.py` — env var loading (future phases expand, never replace)
- [ ] `cli.py` — Typer CLI with `ingest` command group

#### edgartools Local Storage Setup
- [ ] Configure `use_local_storage("~/edgar-offline")` in config module
- [ ] `download_edgar_data()` — full metadata download (~24 GB: submissions ~5 GB, companyfacts ~2 GB, reference ~50 MB)
- [ ] `download_filings("YYYY-01-01:")` — historical filing documents for configurable year range
- [ ] Verify offline operation: disable network → confirm edgartools reads from local storage
- [ ] See [05-tech-stack.md](05-tech-stack.md) § edgartools Local Storage for full setup details

#### DuckDB Financial Data Store
- [ ] `src/investment_researcher/ingestion/timeseries.py` — DuckDB writer module: initialize `data/duckdb/financial_timeseries.duckdb` with **exact schema** from [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store (`financial_metrics` table with PK `(ticker, metric_type, period_type, period_end)`; `macro_timeseries` table with PK `(indicator_id, date)`). Expose `write_financial_metrics()`
- [ ] Structured financial data extraction — use **edgartools**: `company.get_financials()` returns parsed income statement, balance sheet, and cash flow as DataFrames; `company.get_facts()` returns all historical XBRL data as structured objects
  - Map US GAAP concept names (e.g., `Revenues`, `NetIncomeLoss`, `EarningsPerShareDiluted`) → our `metric_type` names
  - Filter to 10-K FY entries; de-duplicate by keeping the earliest filing per period to avoid restated comparatives
  - Write full time series → DuckDB `financial_metrics` table, `accession` column preserved for provenance
- [ ] Batch processing: iterate all SEC-filing companies, extract financials, write to DuckDB
- [ ] Ingestion state tracking (SQLite) — track which companies have been processed, last update timestamp

#### Prefect Orchestration
- [ ] `src/investment_researcher/flows/sec_data.py` — Prefect flow for the full SEC data pipeline:
  - Task 1: `sync_edgar_metadata` — incremental `download_edgar_data()` update
  - Task 2: `sync_edgar_filings` — incremental `download_filings()` for recent dates
  - Task 3: `extract_financials` — batch extract structured financials → DuckDB for all companies (incremental: skip already-processed)
- [ ] Prefect deployment with schedule — daily (or configurable) run
- [ ] Prefect server (`prefect server start`) added to `docker-compose.yml` or run standalone
- [ ] Failure alerting: Prefect notifications on flow/task failure (email or webhook)
- [ ] CLI commands: `ir ingest sec --full` (initial seed), `ir ingest sec --incremental` (daily update)

### Validation Criteria
- [ ] `ir ingest sec --full` completes: edgartools local storage populated, DuckDB has financial metrics for 1,000+ companies
- [ ] `SELECT COUNT(DISTINCT ticker) FROM financial_metrics` → 1,000+ tickers
- [ ] `SELECT COUNT(*) FROM financial_metrics` → tens of thousands of rows (multiple metrics × multiple years × companies)
- [ ] Prefect dashboard (localhost:4200) shows successful flow runs with task-level status
- [ ] Re-running `ir ingest sec --incremental` skips already-processed data, only fetches new filings
- [ ] Simulated failure (e.g., kill mid-run) → Prefect shows failed state, re-run recovers gracefully
- [ ] Offline test: disconnect network → edgartools reads from local storage → DuckDB queries work

### Deliverables
```
investment-researcher/
├── docker-compose.yml            ✓  (Prefect server — future phases add more services)
├── pyproject.toml                ✓  (investment_researcher package, final structure)
├── .env.example                  ✓  (EDGAR_IDENTITY, EDGAR_LOCAL_DATA_DIR, PREFECT_API_URL)
├── src/
│   └── investment_researcher/
│       ├── __init__.py
│       ├── config.py             ✓  (env var loading)
│       ├── ingestion/
│       │   ├── edgar/
│       │   │   └── financials.py ✓  (edgartools: get_financials(), get_facts() → DuckDB)
│       │   ├── timeseries.py     ✓  (DuckDB writer: financial_metrics table)
│       │   └── state.py          ✓  (SQLite ingestion state tracker)
│       └── flows/
│           └── sec_data.py       ✓  (Prefect flow: sync metadata, sync filings, extract financials)
├── cli.py                        ✓  (Typer: ingest sec --full / --incremental)
├── README.md                     ✓  (setup, Prefect dashboard, CLI usage)
├── data/
│   ├── edgar/                    ✓  (edgartools local storage — ~24 GB metadata + filing documents)
│   └── duckdb/
│       └── financial_timeseries.duckdb ✓  (financial_metrics table, seeded via edgartools)
└── docs/
```

### Cost Estimate
- **Hardware**: AMD workstation already purchased (~$3,764)
- **API costs**: $0 — edgartools/SEC EDGAR is free (just need a valid User-Agent identity)
- **Time**: 1–2 weeks (edgartools setup + DuckDB schema + Prefect flows + batch processing)

---

## Phase 1: Company Profiles + Chat UI (Week 3-6)

**Goal**: Build a [Simply Wall St](https://simplywall.st)-style web application where users can browse any SEC-filing company's financial profile, plus a chat interface powered by a local LLM for asking questions about companies and their filings. All data strictly from SEC via edgartools — no external financial APIs. The local LLM runs on the RTX 5090.

### Scope
- **All SEC-filing companies** (~10,000+) — same dataset from Phase 0's DuckDB
- **Web UI**: Company profile pages with financial charts, balance sheet health, margin analysis, cash flow — everything derivable from SEC XBRL data
- **Chat interface**: Ask questions about any company. The LLM has access to both structured financial data (DuckDB) and raw filing text (edgartools local storage, full-context stuffing)
- **Local LLM**: Qwen 2.5 32B (or similar) on RTX 5090 — no OpenAI API dependency
- **No graph, no entity extraction, no external data** — pure SEC data presentation + conversational Q&A

### Tasks

#### Analytics Layer
- [ ] `src/investment_researcher/analytics/__init__.py` — financial analytics module querying DuckDB:
  - Auto-detect each company's fiscal year-end month (edgartools financial data includes comparative and quarterly values mixed into annual filings; must filter correctly)
  - Annual and quarterly time series with YoY/QoQ growth computed via SQL window functions per [02-graph-schema.md](02-graph-schema.md) § Growth Rate Strategy
  - Derived metrics: gross margin, operating margin, net margin, EPS trends, debt-to-equity, current ratio, ROE, ROA, free cash flow
  - Revenue breakdown by segment (where available from XBRL data)
  - Note: P/E, P/S, and other valuation ratios deferred to Phase 3 (require market price data from FMP)

#### Simply Wall St-Style Web UI
- [ ] FastAPI backend — `src/investment_researcher/web/app.py`:
  - REST API: company search/autocomplete, company profile endpoint, individual metric queries
  - Serve filing text via edgartools (`filing.markdown()`) for the chat context
  - Chat SSE endpoint for streaming LLM responses
- [ ] Nuxt 3 + Vue 3 frontend — `frontend/` (separate directory, **per [05-tech-stack.md](05-tech-stack.md) § Frontend Deep Dive**):
  - **shadcn-vue** UI components + **Tailwind CSS** for professional, consistent styling
  - Company search with autocomplete (search by ticker or name across all SEC companies) — `SearchBar.vue` + `useSearch.ts` composable
  - **Company profile page** (`pages/company/[ticker].vue`) inspired by Simply Wall St:
    - Header: company name, ticker, CIK, SIC industry, last filing date
    - KPI summary cards: revenue, net income, EPS, total assets, total debt (latest available) — `KpiCards.vue`
    - **Income Statement tab**: revenue & net income bar chart over time, EPS line chart, YoY growth indicators — `IncomeTab.vue`
    - **Margins tab**: gross/operating/net margin trend lines — `MarginsTab.vue`
    - **Balance Sheet tab**: assets vs. liabilities stacked bars, debt-to-equity trend, current ratio — `BalanceSheetTab.vue`
    - **Cash Flow tab**: operating/investing/financing cash flow breakdown — `CashFlowTab.vue`
    - **Earnings tab**: EPS trend, quarterly earnings if available — `EarningsTab.vue`
    - **Filings tab**: list of recent filings (10-K, 10-Q, 8-K) with links to full text view — `FilingsTab.vue`
    - Color-coded growth indicators (green/red for positive/negative trends)
  - Interactive charts via **Apache ECharts** (`vue-echarts`) — richer financial chart types than Chart.js
  - Server-state management via **TanStack Vue Query** (`useCompany.ts`, `useFinancials.ts`) — automatic caching, loading states
  - Responsive design (works on desktop and mobile)
- [ ] `ir web` CLI command to launch the FastAPI backend (Nuxt runs separately via `npm run dev` in development, or as a Docker container in production)
- [ ] FastAPI + Uvicorn + Nuxt added to project dependencies — **per [05-tech-stack.md](05-tech-stack.md)**

#### Local LLM Inference
- [ ] vLLM (primary) or llama.cpp (fallback) with CUDA on RTX 5090
- [ ] Qwen 2.5 32B Q4_K_M (~20 GB VRAM, 30-50 tok/s) for chat responses
- [ ] OpenAI-compatible API endpoint at `http://localhost:8000/v1`
- [ ] `EDGAR_IDENTITY` and `LLM_API_BASE` in config
- [ ] Model download + setup documented in README

#### Chat Interface (Web-based)
- [ ] Chat panel component (`ChatPanel.vue`) embedded in the company profile page — text input + streaming response display
- [ ] Chat backend: receives user question + current company context (if viewing a company profile)
- [ ] **Full-context stuffing** strategy for filing Q&A:
  - When user asks about a specific company, load the most recent 10-K filing text via `filing.markdown()` from edgartools local storage
  - Stuff the full filing text (~50-100K tokens) into the LLM context window (Qwen 2.5 32B supports 128K context)
  - Prepend structured financial summary from DuckDB as system context
  - LLM answers based on both structured data and raw filing text
- [ ] For general questions (not company-specific): provide DuckDB financial data as context, let LLM reason over it
- [ ] Streaming responses via SSE (Server-Sent Events) for responsive UX
- [ ] Chat history within session (not persisted across page reloads for now)
- [ ] Source attribution: when answering from filing text, cite the filing accession number and section

#### Financial Data Validation & Testing
- [ ] Unit tests for the analytics layer: verify margin, growth-rate, and ratio calculations against hand-computed expected values
- [ ] Data integrity tests on the DuckDB store: no duplicate (ticker, metric, period) rows, no NULL values in required columns, fiscal year-end filtering produces exactly one row per year
- [ ] **Third-party cross-validation test**: for at least two tickers, fetch the same metrics (revenue, net income, EPS) from a reputable public source and assert they match within ≤1% tolerance
- [ ] Test runner invocable via `pytest tests/`

### Validation Criteria
- [ ] `ir web` launches the web app; homepage shows company search
- [ ] Search "AAPL" → Apple company profile loads with all financial tabs populated
- [ ] Income Statement tab shows correct multi-year revenue and net income chart
- [ ] Balance Sheet tab shows assets/liabilities breakdown with debt-to-equity trend
- [ ] Margins tab shows gross/operating/net margin trends that match SEC filings
- [ ] Filing tab lists recent 10-K, 10-Q, 8-K filings
- [ ] Browse to any of 1,000+ companies — all have profile data (coverage depends on Phase 0 DuckDB seeding)
- [ ] Chat: "What are Apple's main risk factors?" → LLM responds with specific risks from the latest 10-K, citing the filing
- [ ] Chat: "Compare Intel and AMD revenue trends" → LLM pulls structured data from DuckDB for both companies
- [ ] Chat: "What did TSMC say about AI demand in their latest annual report?" → LLM answers from full filing text
- [ ] Chat responses stream in real-time (not blocked until complete)
- [ ] All analytics unit tests pass (`pytest tests/`)
- [ ] Cross-validation passes for at least two tickers

### Deliverables
```
investment-researcher/
├── docker-compose.yml            ← Phase 0 (expanded: frontend + api services)
├── pyproject.toml                ← Phase 0 (expanded: FastAPI, Uvicorn, vLLM/llama-cpp-python)
├── .env.example                  ← Phase 0 (expanded: LLM_API_BASE)
├── frontend/                     ✓  NEW — Nuxt 3 + Vue 3 app (see 05-tech-stack.md § Frontend Deep Dive)
│   ├── nuxt.config.ts
│   ├── package.json              ✓  (Nuxt, Vue, shadcn-vue, ECharts, TanStack Query/Table, Pinia)
│   ├── tailwind.config.ts
│   ├── pages/
│   │   ├── index.vue             ✓  NEW — company search landing page
│   │   └── company/
│   │       └── [ticker].vue      ✓  NEW — company profile (tabs + chat panel)
│   ├── components/
│   │   ├── ui/                   ✓  shadcn-vue primitives (button, card, tabs, input, sheet…)
│   │   ├── company/              ✓  NEW — SearchBar, KpiCards, IncomeTab, MarginsTab, etc.
│   │   └── chat/                 ✓  NEW — ChatPanel, ChatMessage, SourceCitation
│   ├── composables/              ✓  NEW — useCompany, useFinancials, useChat, useSearch
│   ├── lib/                      ✓  NEW — api.ts (typed client), charts.ts (ECharts options)
│   └── stores/                   ✓  NEW — chat.ts (Pinia session chat history)
├── src/
│   └── investment_researcher/
│       ├── config.py             ← Phase 0 (expanded: LLM config)
│       ├── analytics/
│       │   └── __init__.py       ✓  NEW — financial analytics (margins, ratios, growth, FY-end detection)
│       ├── web/
│       │   ├── app.py            ✓  NEW — FastAPI backend (REST API + chat SSE endpoint)
│       │   └── chat.py           ✓  NEW — chat logic (context stuffing, LLM calls, streaming)
│       ├── ingestion/            ← Phase 0 (unchanged)
│       └── flows/                ← Phase 0 (unchanged)
├── tests/
│   ├── test_analytics.py         ✓  NEW — margin/growth/ratio calculation tests
│   ├── test_data_integrity.py    ✓  NEW — DuckDB uniqueness, NULLs, FY-end filtering
│   └── test_crossvalidation.py   ✓  NEW — compare DuckDB values vs third-party source
├── cli.py                        ← Phase 0 (expanded: `ir web` command)
├── data/                         ← Phase 0 (unchanged)
└── models/
    └── qwen2.5-32b-q4.gguf      ✓  (~20 GB — local LLM for chat)
```

### Cost Estimate
- **Hardware**: Already purchased (RTX 5090 handles local LLM inference)
- **API costs**: $0 — all local (LLM on RTX 5090, data from edgartools local storage + DuckDB)
- **Time**: 3–4 weeks (analytics + web UI: 2 weeks, LLM setup + chat: 1–2 weeks)

---

## Phase 2: Knowledge Graph + Entity Extraction (Week 7-10)

**Goal**: Introduce FalkorDB as the knowledge graph and use LLM-based extraction to turn SEC filing text into a rich, interconnected graph. This is where the platform diverges from a simple financial data viewer — entities, relationships, and supply chains emerge from SEC filings.

### Tasks

#### FalkorDB Setup
- [ ] Add FalkorDB to `docker-compose.yml` (bind mount `./data/falkordb:/data`)
- [ ] `src/investment_researcher/graph/connection.py` — FalkorDB connection + health check + retry logic
- [ ] `src/investment_researcher/graph/schema.py` — **MUST implement exactly per [02-graph-schema.md](02-graph-schema.md) § Core Node Types and § Core Relationships**. Company, Person, Filing, Industry, Sector, Region node types. All indexes per § Indexes
- [ ] Add GraphRAG-SDK integration — `src/investment_researcher/graph/ontology.py` + `schemas/core_ontology.json`

#### LLM-Based Entity Extraction from SEC Filings
> **Implementation spec**: Follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 1: SEC EDGAR — pipeline steps for entity/relationship extraction. All extracted entities and relationships **MUST** conform to [02-graph-schema.md](02-graph-schema.md) property definitions.

- [ ] Filing preprocessor: `filing.markdown()` via edgartools (no Docling needed for SEC filings). For structured data: `filing.obj()` returns typed data object (10-K → subsidiaries/auditor, DEF 14A → exec compensation, 8-K → event items)
- [ ] **LLM-based entity extraction from 10-K text** (the core value-add):
  - [ ] Supply chain extraction from "Customers" / "Suppliers" / "Risk Factors" sections — **MUST populate all SUPPLIES_TO edge properties** per [02-graph-schema.md](02-graph-schema.md)  
  - [ ] Competitive dynamics from "Competition" section — **MUST populate all COMPETES_WITH edge properties**
  - [ ] Executive/board extraction from filing headers and DEF 14A — **MUST populate HAS_EXECUTIVE and HAS_BOARD_MEMBER edge properties**
  - [ ] Industry/sector classification via SIC from edgartools
  - [ ] Risk factor categorization (geopolitical, regulatory, supply chain, financial)
- [ ] Filing → FalkorDB loader: create Filing nodes (keyed on `accession_number`), link to Company via `FILED` relationship. Use MERGE operations
- [ ] Generate `summary`, `risk_factors`, `opportunities` on Company node via LLM extraction from 10-K text
- [ ] Prefect flow: `extract_entities` — batch entity extraction across all companies, integrated into the SEC data pipeline
- [ ] Start with ~50 semiconductor companies for initial quality validation, then scale
- [ ] CLI commands: `ir ingest extract --ticker AAPL`, `ir ingest extract --all`

#### Graph-Aware Chat Enhancement
- [ ] Expand Phase 1 chat to also query FalkorDB for relationship data
- [ ] `src/investment_researcher/agents/tools/graph_tools.py` — `query_graph()`, `get_company_profile()`, `get_related_companies()` — **MUST match signatures in [04-agent-system.md](04-agent-system.md) § Graph Query Tools**
- [ ] Chat can now answer questions like "Who supplies Apple?" from graph data + filing context

### Validation Criteria
- [ ] FalkorDB browser (localhost:3000) shows interconnected company network
- [ ] `MATCH ()-[r:SUPPLIES_TO]->() RETURN count(r)` → 50+ supply chain relationships
- [ ] Rich edge properties populated: `product_category`, `dependency_level`, `is_sole_source` present on SUPPLIES_TO edges
- [ ] Filing nodes linked to companies: `MATCH (c:Company)-[:FILED]->(f:Filing) RETURN count(f)` > 10
- [ ] Spot-check: LLM-extracted supply chain data matches manually reading the same 10-K section
- [ ] Chat: "Who supplies Apple?" → returns graph-backed answer with source citations
- [ ] At least 10 companies with SEC-extracted data in the graph

### Deliverables
```
src/investment_researcher/
├── graph/
│   ├── connection.py         ✓  NEW — FalkorDB connection
│   ├── schema.py             ✓  NEW — full node/edge schema
│   └── ontology.py           ✓  NEW — GraphRAG-SDK integration
├── ingestion/
│   ├── edgar/
│   │   ├── parser.py         ✓  NEW — filing.markdown() → LLM-ready text
│   │   └── extractor.py      ✓  NEW — LLM entity/relationship extraction
│   └── loader.py             ✓  NEW — Filing → FalkorDB node/edge writer
├── agents/tools/
│   └── graph_tools.py        ✓  NEW — graph query tools
├── flows/
│   └── sec_data.py           ← Phase 0 (expanded: entity extraction task)
└── web/
    └── chat.py               ← Phase 1 (expanded: graph-aware chat)
schemas/
└── core_ontology.json        ✓  NEW — graph ontology
```

---

## Phase 3: External Data Sources (Week 11-13)

**Goal**: Enrich the platform with non-SEC data — market prices (FMP), macro indicators (FRED), country data. This unlocks valuation metrics (P/E, P/S) in the web UI and macro context for the chat. News and Congressional data pipelines add real-time information flow.

### Tasks
> **Implementation spec**: Financial data pipeline **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 2: Financial Data APIs. Growth rates are **computed at query time** via SQL window functions, NOT precomputed — see [02-graph-schema.md](02-graph-schema.md) § Growth Rate Strategy.

#### Financial Data APIs
- [ ] FMP or Polygon.io integration — market cap, P/E, EPS, price history per [03-data-ingestion.md](03-data-ingestion.md) § Financial Modeling Prep
- [ ] Write to DuckDB `financial_metrics` table via existing `timeseries.py`
- [ ] Populate `market_cap` on Company nodes in FalkorDB (was null in Phase 2)
- [ ] Update web UI: add valuation metrics (P/E, P/S) now that market price data is available

#### Macro Indicators
- [ ] FRED API integration — starter set: GDP, GDPC1, UNRATE, CPIAUCSL, FEDFUNDS, T10YIE, T10Y2Y per [03-data-ingestion.md](03-data-ingestion.md) § FRED source table
- [ ] Write to DuckDB `macro_timeseries` table
- [ ] MacroIndicator graph nodes per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources

#### Country / Region Data
- [ ] World Bank / IMF API per [03-data-ingestion.md](03-data-ingestion.md) § World Bank / IMF source table
- [ ] Region/Country nodes per [02-graph-schema.md](02-graph-schema.md) § Region
- [ ] G20 countries initially

#### News Pipeline
- [ ] News API integration (Marketaux recommended) per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 3
- [ ] NewsArticle nodes, MENTIONED_IN relationships
- [ ] LLM-based entity extraction + sentiment analysis
- [ ] Prefect flow: news polling every 15-30 minutes

#### Congressional Investment Disclosures
- [ ] Capitol Trades or Quiver Quantitative API per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 6
- [ ] Legislator + CongressionalTrade nodes
- [ ] Committee assignment mapping via Congress.gov API
- [ ] Trade → Company linkage

#### Prefect Integration
- [ ] New Prefect flows for each data source (financial, macro, news, congressional)
- [ ] All pipelines monitored in Prefect dashboard

### Validation Criteria
- [ ] Company profiles now show P/E, P/S ratios (from FMP price data)
- [ ] Chat: "What is the current Fed Funds Rate?" → answers from FRED data
- [ ] Chat: "Which stocks are Congress members buying?" → returns recent trades with committee context
- [ ] News articles flowing into graph every 30 minutes
- [ ] DuckDB `macro_timeseries` has historical FRED data
- [ ] Prefect dashboard shows all pipelines running on schedule

---

## Phase 4: Agent System (Week 14-16)

**Goal**: Multi-agent system operational with Triage, Ripple Effect Analyzer, Fundamental Screener, Macro-Micro Linker, and Research Synthesizer. The chat interface upgrades from simple Q&A to intelligent multi-agent routing. Report queue receiving findings. Paper trading begins.

### Tasks
> **Implementation spec**: All agent definitions, tools, guardrails, report schema, and handoff flows **MUST match** [04-agent-system.md](04-agent-system.md) exactly.

#### Agent Tools
- [ ] Expand `graph_tools.py`: add `semantic_search_graph()`, `get_industry_peers()` — **exact signatures from [04-agent-system.md](04-agent-system.md)**
- [ ] Add data tools: `get_recent_news()`, `get_macro_indicators()`, `get_financial_history()`, `get_commodity_impacts()`, `get_recent_ingestion_stats()` — **exact signatures from [04-agent-system.md](04-agent-system.md) § Data Tools**
- [ ] Add political tools: `get_congressional_trades()`, `get_institutional_holdings()` (stub until Phase 5), `get_policy_impacts()` (stub), `get_country_profile()`, `get_government_contracts()` (stub) — **exact signatures from [04-agent-system.md](04-agent-system.md) § Political & Government Tools**
- [ ] Report tools: `write_report()`, `get_existing_reports()` — **exact signatures**

#### Agent Definitions
- [ ] Triage Agent (router) — **per [04-agent-system.md](04-agent-system.md) § 1. Triage Agent**
- [ ] Data Monitor Agent — **per § 2. Data Monitor Agent**
- [ ] Ripple Effect Analyzer — **per § 3. Ripple Effect Analyzer** (confidence decay 0.9/hop, staleness decay, edge property usage)
- [ ] Fundamental Screener — **per § 4. Fundamental Screener**
- [ ] Macro-Micro Linker — **per § 5. Macro-Micro Linker**
- [ ] Research Synthesizer — **per § 6. Research Synthesizer** (report JSON schema, bear case required)

#### Guardrails
- [ ] Input: `validate_query_safety` (Cypher injection prevention), `check_market_hours`
- [ ] Output: `validate_report_quality`, `enforce_bear_case`, `enforce_source_citations`

#### Report & Paper Trading
- [ ] Report queue (SQLite) — report schema per [04-agent-system.md](04-agent-system.md) § 6. Research Synthesizer
- [ ] Human review workflow: `ir reports review <id>`
- [ ] Paper trading: auto-record trades for confidence > 0.6, track 30/60/90 day outcomes per [04-agent-system.md](04-agent-system.md) § Paper Trading Protocol

#### Web UI Integration
- [ ] Chat routes through Triage Agent (replaces Phase 1's direct LLM chat)
- [ ] Report viewer in web UI
- [ ] Thesis exploration: `ir explore "thesis statement"` via CLI or web

#### Monetization — Start Revenue Streams
> See [09-monetization-strategy.md](09-monetization-strategy.md)
- [ ] Newsletter (A1): Weekly research digest from agent reports
- [ ] LLM Inference API (A3): Expose RTX 5090 spare capacity
- [ ] Open Source (A4): Public repo with core platform

### Validation Criteria
- [ ] "What companies might be affected if TSMC has production issues?" → Triage → Ripple Effect Analyzer → multi-hop analysis with confidence decay and bear case
- [ ] "Which tech companies look undervalued?" → Triage → Fundamental Screener → ranked list
- [ ] "How would rising interest rates affect the market?" → Triage → Macro-Micro Linker → industry/company trace
- [ ] Reports appear in `ir reports list` with "needs_review" status, including bear case and source citations
- [ ] Paper trading system recording trades
- [ ] First newsletter edition published

---

## Phase 5: Observability + RAG (Week 17-19)

**Goal**: Add Langfuse observability for tracing agent interactions, embeddings/vector search for improved chat retrieval, and Docling for non-SEC document processing. Implement deferred Tier 2 data pipelines (13F, legislation, government contracts).

### Tasks

#### Observability
- [ ] Langfuse + Postgres added to `docker-compose.yml`
- [ ] `src/investment_researcher/observability/setup.py` — Langfuse + OpenInference instrumentation
- [ ] All agent interactions traced with full handoff chains visible
- [ ] Cost tracking per agent per model

#### RAG (Retrieval-Augmented Generation)
- [ ] Embedding model: nomic-embed-text or mxbai-embed-large on RTX 5090
- [ ] Vector store: ChromaDB or LanceDB for filing chunk embeddings
- [ ] Filing chunking + embedding pipeline (replaces full-context stuffing for very long filings or multi-filing queries)
- [ ] Chat now combines: structured data (DuckDB) + graph data (FalkorDB) + semantic search (vector store) + full-context stuffing (for single-filing deep dives)

#### Docling for Non-SEC Documents
- [ ] `src/investment_researcher/ingestion/preprocessor.py` — Docling wrapper for uploaded PDFs, PPTX, XLSX, scraped web pages
- [ ] Manual document upload via web UI

#### Tier 2 Data Pipelines
- [ ] 13F institutional holdings per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 7 — InstitutionalHolder nodes, HOLDS_POSITION relationships
- [ ] Government & policy data per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 8 — Legislation nodes, AFFECTS relationships
- [ ] Company IR pages & press releases per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 4

### Validation Criteria
- [ ] Langfuse dashboard shows full agent interaction traces
- [ ] Chat semantic search returns relevant filing sections for vague queries
- [ ] Upload a PDF → entities appear in knowledge graph
- [ ] 13F data: "Show institutional holders of AAPL" → returns quarterly holdings data
- [ ] Congressional + 13F cross-reference working

---

## Phase 6: Scale & Automate (Week 20-22)

**Goal**: Scale to 5,000+ companies. All pipelines running on schedule via Prefect. Autonomous agent loop running 24/7 producing reports without human intervention. System is self-operating.

### Tasks
- [ ] Scale to S&P 500, then Russell 1000, then all SEC-filing public companies (~5,000+)
- [ ] Scale all Tier 2 pipelines to full breadth (13F top 500 filers, full Congressional history 2012+)
- [ ] Autonomous agent loop — **per [04-agent-system.md](04-agent-system.md) § Autonomous Agent Loop**: Data Monitor every 30 min, Fundamental screen every 6 hours, Macro check every 4 hours
- [ ] Orchestrate via Prefect (replaces APScheduler-based triggers from the agent system spec — Prefect provides better monitoring, retry, alerting)
- [ ] **Storage monitoring**: weekly alert when `/data` > 70% capacity
- [ ] **NAS migration** (triggered when NVMe total hits 70% ~4.2TB):
  - [ ] Purchase 10-bay NAS (see [08-hardware-requirements.md](08-hardware-requirements.md) § Tier 2: NAS)
  - [ ] SMB mount in WSL2, migrate bulk data, update volume mounts
- [ ] Performance tuning: FalkorDB memory, query profiling, LLM cost optimization (local RTX 5090 for routine, API for complex)
- [ ] Monitoring: ingestion health dashboard, agent performance metrics, GPU utilization
- [ ] **Monetization scaling**: Signal Alerts (A2), Consulting (B3), Discord Community (B5)

### Validation Criteria
- [ ] 5,000+ Company nodes in graph
- [ ] All pipelines running for 48+ hours without intervention
- [ ] Autonomous agent loop producing 5-15 reports per day
- [ ] Prefect dashboard shows all flows healthy
- [ ] No OOM crashes (FalkorDB ~16 GB, total ≤ 64 GB RAM)

---

## Phase 7: Mac Studio Expansion — Large Model Inference (Week 23+)

**Goal**: Expand inference capacity beyond RTX 5090 with Mac Studio cluster for 405B-class models and high-throughput concurrent inference. See [08-hardware-requirements.md](08-hardware-requirements.md) for full hardware specs.

> **Hardware purchase gate** (all 4 conditions from [08-hardware-requirements.md](08-hardware-requirements.md)):
> 1. Platform producing valuable research insights consistently (Phase 6 paper trading validates)
> 2. Quantitative evidence that 32B models on RTX 5090 are insufficient
> 3. Revenue from monetization justifies the $8K–$20K investment
> 4. **OR**: Inference API monetization demand exceeds RTX 5090 capacity

### Tasks
- [ ] Hardware setup: rack Mac Studios, Thunderbolt 5 RDMA, 10 GbE to workstation/NAS
- [ ] Inference stack: exo on all Mac Studios (MLX backend), distributed inference
- [ ] Model evaluation: Llama 3.1 405B (distributed), Llama 3.1 70B (single Studio), Qwen 2.5 72B
- [ ] Multi-tier model routing via LiteLLM: RTX 5090 (8B triage + 32B routine) + Mac Studio (405B complex reasoning)
- [ ] Benchmarks: quality (405B vs. 32B vs. GPT-4.1), latency, throughput

### Validation Criteria
- [ ] 405B produces measurably better output than 32B on complex reasoning
- [ ] Autonomous loop runs 48+ hours with multi-tier inference
- [ ] OpenAI API costs reduced to near-zero
- [ ] All Mac Studios stable under sustained load

---

## Phase 8: Feedback Loop & Calibration (Week 25+)

**Goal**: Close the loop between predictions and outcomes. Track report accuracy, calibrate confidence thresholds, and continuously improve agent reasoning quality. See [00-strategic-rationale.md](00-strategic-rationale.md) — "the moat is in institutional knowledge."

### Tasks
- [ ] Prediction tracking: record predictions → track outcomes → compute hit rates by report type, confidence bucket, agent
- [ ] Confidence calibration: are 0.7-confidence reports correct 70% of the time? Adjust thresholds empirically
- [ ] Signal vs. noise analysis: which relationship types and data sources produce the most alpha?
- [ ] Agent prompt refinement based on observed failure modes
- [ ] Anti-confirmation-bias measures: bull/bear ratio tracking, red team sessions
- [ ] Historical backtesting: load pre-event data, run agents, compare vs. actual outcomes (blind event selection)
- [ ] Ontology refinement: promote validated RELATED_TO edges, archive low-value relationships

### Validation Criteria
- [ ] 100+ reports with outcome data tracked
- [ ] Confidence calibration curve plotted
- [ ] Top 3 and bottom 3 relationship types by predictive value identified
- [ ] At least 5 agent prompt improvements deployed from failure analysis

---

## Summary Timeline

| Phase | Duration | Key Milestone |
|-------|----------|---------------|
| 0. SEC Data Pipeline | Week 1-2 | Prefect + edgartools local storage + DuckDB. Scheduled fetching for all SEC companies. No UI |
| 1. Company Profiles + Chat | Week 3-6 | Simply Wall St-style web UI + chat with local LLM (Qwen 32B on RTX 5090). All data from SEC only |
| 2. Knowledge Graph + Extraction | Week 7-10 | FalkorDB, LLM entity extraction from 10-K text, supply chain / competitive / executive relationships |
| 3. External Data Sources | Week 11-13 | FMP (market prices → P/E), FRED (macro), news pipeline, Congressional trades |
| 4. Agent System | Week 14-16 | Multi-agent system (Triage, Ripple Effect, Screener, Macro-Micro, Synthesizer). Reports, paper trading. **Monetization starts** |
| 5. Observability + RAG | Week 17-19 | Langfuse tracing, embeddings/vector search, Docling for non-SEC docs, 13F + legislation pipelines |
| 6. Scale & Automate | Week 20-22 | 5,000+ companies, 24/7 autonomous agent loop, NAS migration if needed |
| 7. Mac Studio Expansion | Week 23+ | 405B models for complex reasoning. **Mac Studio purchase gate**: only buy after Phase 6 validates + RTX 5090 proven insufficient |
| 8. Feedback Loop | Week 25+ | Prediction tracking, confidence calibration, historical backtesting, signal vs. noise |

### Budget Summary

| Item | Cost | Status |
|------|------|--------|
| AMD Workstation (RTX 5090, Ryzen 9 9950X3D, 64GB DDR5) | ~$3,764 | **Already purchased** |
| MacBook Pro M2 Pro 14" | Owned | **Already owned** |
| NAS (10-bay, RAID 6, ~128TB usable) | ~$3,000–9,000 | Phase 6 (triggered by storage) |
| Mac Studio cluster (1–2 units, if validated) | ~$8,050–15,300 | Phase 7+ (gated) |
| **Phase 0–4 total (workstation only)** | **~$3,764** | Already purchased |
| **Phase 0–6 total (workstation + NAS)** | **~$6,764–12,764** | |
| **Phase 0–8 total (if Mac Studios purchased)** | **~$14,814–28,064** | |

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **edgartools local storage download failures** | Medium | Medium | Prefect retry logic, incremental downloads. `download_edgar_data()` is idempotent |
| **DuckDB financial data quality issues** | High | Medium | Cross-validation tests against third-party source. Fiscal year-end detection edge cases |
| **SEC extraction pipeline fails — can't extract quality data from filings** | Critical | Medium | Try different extraction methods: structured parsing, better prompts, different models, GraphRAG-SDK |
| **Full-context stuffing exceeds LLM context window** | Medium | Low | Qwen 2.5 32B supports 128K tokens. For edge cases, truncate to most relevant sections. Phase 5 adds RAG as alternative |
| **RTX 5090 32B chat quality insufficient** | Medium | Medium | Benchmark early in Phase 1. Fallback: use OpenAI API for complex queries, local for routine |
| **Graph noise overwhelms signal** | High | Medium | Confidence thresholds, multi-source corroboration, Phase 8 signal analysis |
| **Confirmation bias amplification** | High | Medium | Bear case requirement in every report, Phase 8 bias auditing |
| **FalkorDB OOM at 5K+ companies** | High | Medium | Monitor memory, prune old data. Budget ~16 GB for FalkorDB via `--maxmemory` |
| **EDGAR rate limiting** | Medium | Medium | edgartools handles rate limiting. Local storage eliminates most network requests |
| **Prefect operational overhead** | Low | Low | Prefect is lightweight for local deployment. Dashboard provides visibility without custom monitoring |
| **Confidence decay compounds errors** | High | Medium | Use CIK/CUSIP as ground-truth anchors. Prefer structured data over LLM extraction |
| **LLM reasoning errors become investment losses** | Critical | Medium | All outputs are hypotheses requiring human review. Source citations mandatory. Track accuracy in Phase 8 |
| **Scope creep in early phases** | High | High | Phase 0 is data only. Phase 1 is UI only. No graph until Phase 2. No agents until Phase 4. Each phase has clear boundaries |
| **Stale relationships treated as current** | High | High | Staleness decay on relationships. Supply chain data from 2-year-old filings may be outdated |
| **Hardware purchased before validation** | High | Medium | AMD workstation already purchased. Mac Studio gate at Phase 7 with 4 conditions. Don't buy until Phase 6 validates |
| **Maintenance burden** | Medium | High | Data pipelines break, APIs change, LLMs degrade. Budget ongoing maintenance. Prefect monitoring helps catch failures early |
