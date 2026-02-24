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

**Goal**: Establish the project's permanent structure, graph schema, CLI framework, and SEC EDGAR data extraction pipeline. All data comes from real sources (SEC filings, Company Facts API) — no hand-seeded toy data. See [00-strategic-rationale.md](00-strategic-rationale.md) § Data Quality First.

### Scope
- ~50 companies in the **semiconductor** sector + their supply chain
- **SEC EDGAR pipeline**: Fetch and parse 10-K filings for target companies
- **Entity and relationship extraction**: LLM-based extraction from filing text → rich graph nodes and edges
- **SEC Company Facts API**: Structured financial data (revenue, net income, EPS, etc.) fetched via `data.sec.gov/api/xbrl/companyfacts/` — one API call per CIK returns all historical XBRL facts as JSON, eliminating the need to parse XBRL from individual filings
- OpenAI API primary; optionally test local LLM on RTX 5090 (Qwen 2.5 32B) for extraction quality comparison
- Minimal infrastructure (FalkorDB + DuckDB + CLI on AMD workstation)
- **Full production structure from day one** — scope is narrow, but code is in its final home

### Tasks

#### Infrastructure & Project Structure
- [ ] `docker-compose.yml` with FalkorDB only (bind mount `./data/falkordb:/data` — same file Phase 1 extends by adding Langfuse)
- [ ] `pyproject.toml` with `investment_researcher` package, Typer, OpenAI Agents SDK, FalkorDB client — Phase 1 adds more deps, never restructures. **MUST use libraries specified in [05-tech-stack.md](05-tech-stack.md)**
- [ ] `.env.example` (OpenAI key only for now — Phase 1 adds Langfuse, Phase 2 adds data API keys)
- [ ] `src/investment_researcher/config.py` — env var loading (Phase 1 expands, never replaces)
- [ ] `src/investment_researcher/graph/connection.py` — FalkorDB connection + health check (Phase 1 adds retry logic)
- [ ] `src/investment_researcher/graph/schema.py` — **MUST implement exactly per [02-graph-schema.md](02-graph-schema.md) § Core Node Types and § Core Relationships**. Company node properties: `ticker`, `cik`, `name`, `legal_name`, `status`, `market_cap`, `summary`, `risk_factors`, `opportunities`, `embedding`, `last_updated`. Person: `name`, `title`, `bio`, `last_updated`. Filing: `accession_number`, `form_type`, `filed_date`, `period_of_report`, `filing_url`, `file_path`, `summary`, `key_topics`, `sentiment`, `summary_embedding`, `last_updated` (pipeline state tracked in SQLite, not here). Industry: `name`, `gics_code`, `description`. Sector: `name`, `gics_code`, `description`. Region: `name`, `region_type`, `iso_code`, `last_updated`. **Do NOT invent properties or omit properties — use the exact property names and types from the schema doc.** Indexes per § Indexes. Phase 1 adds full relationship schema + auto-extension via GraphRAG-SDK
- [ ] `src/investment_researcher/ingestion/timeseries.py` — DuckDB writer module: initialize `data/duckdb/financial_timeseries.duckdb` with **exact schema** from [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store (`financial_metrics` table with PK `(ticker, metric_type, period_type, period_end)`; `macro_timeseries` table with PK `(indicator_id, date)`). Expose `write_financial_metrics()` and `recompute_snapshot()` — Phase 2 reuses this module for FMP/FRED data without changes
- [ ] `cli.py` — Typer CLI with `chat`, `ingest`, and `web` commands (Phase 1 adds `health` — same file throughout)
- [ ] `README.md` — developer guide covering: project setup, common CLI commands, financial dashboard usage, how to access and query each database (FalkorDB, SQLite, DuckDB) for debugging, and a map of the `src/investment_researcher/` module structure

#### Financial Dashboard (Web UI for DuckDB Data Presentation)
> **Purpose**: Provide a web-based interface to browse and visualize all financial data stored in DuckDB. Select a company and see its key financial metrics over time — revenue, EPS, margins, balance sheet ratios — with interactive charts and tables. Uses only Phase 0 infrastructure (DuckDB + CLI); no external service dependencies beyond FastAPI/Uvicorn.

- [ ] Analytics layer that queries DuckDB and computes derived metrics on the fly:
  - Auto-detects each company's fiscal year-end month (Company Facts API data includes comparative and quarterly values mixed into annual filings; must filter correctly)
  - Annual and quarterly time series with YoY/QoQ growth computed via SQL window functions per [02-graph-schema.md](02-graph-schema.md) § Growth Rate Strategy
  - Derived metrics: gross/operating/net margins, EPS trends, debt-to-equity, ROE, ROA
  - Note: true P/E ratio deferred to Phase 2 (requires FMP market price data)
- [ ] FastAPI backend exposing a REST API for ticker discovery, per-company dashboards, and individual metric queries — serves static HTML at root
- [ ] Single-page web dashboard (Chart.js) with:
  - Company selector, KPI summary cards, and tabbed views (Overview, Income Statement, Margins, Earnings, Balance Sheet, Quarterly Detail)
  - Interactive bar/line charts, data tables with color-coded growth indicators
- [ ] `ir web` CLI command to launch the dashboard server
- [ ] FastAPI + Uvicorn added to project dependencies — **per [05-tech-stack.md](05-tech-stack.md)**

#### SEC EDGAR Pipeline (Core Development Focus)
> **Implementation spec**: Follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 1: SEC EDGAR — pipeline steps 1-7, source table fields, rate limits, and data flow. All extracted entities and relationships **MUST** conform to [02-graph-schema.md](02-graph-schema.md) property definitions.

- [ ] Company CIK/ticker lookup from EDGAR company index — use `data.sec.gov/submissions/CIK{cik}.json` per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 1 Sources
- [ ] Filing fetcher: 10-K, 10-Q, 8-K for target companies (~50 initially)
  - EDGAR SEC-API or direct EDGAR FULL-TEXT search
  - Rate-limited, polite scraping (10 req/sec max, `User-Agent` header required per [03-data-ingestion.md](03-data-ingestion.md))
  - **Save raw file to disk first** before any processing: `data/raw/filings/{cik}/{accession}.html` per [02-graph-schema.md](02-graph-schema.md) § Original Source Storage
  - Populate `file_path` on the Filing node with the local path
- [ ] Filing preprocessor: HTML → clean markdown (MarkItDown or custom parser)
- [ ] **LLM-based entity extraction from 10-K text** (the hardest and most valuable task):
  - [ ] Supply chain extraction from "Customers" / "Suppliers" / "Risk Factors" sections
    - **MUST populate all SUPPLIES_TO edge properties** per [02-graph-schema.md](02-graph-schema.md) § Company ↔ Company: `product_category`, `dependency_level` ("critical"|"important"|"optional"), `is_sole_source`, `contract_value_usd`, `revenue_pct`, `volume_estimate`, `geographic_risk`, `alternative_suppliers`, `lead_time_weeks`, `confidence`, `source`, `last_confirmed`, `created_at`, `valid_from`, `valid_to`, `description` (LLM-generated narrative per § Edge Property Best Practices)
    - Source citation: accession number + section + page
  - [ ] Competitive dynamics from "Competition" section
    - **MUST populate all COMPETES_WITH edge properties** per [02-graph-schema.md](02-graph-schema.md) § Company ↔ Company: `market_segment`, `intensity` ("direct"|"partial"|"adjacent"|"emerging"), `geographic_overlap`, `market_share_a`, `market_share_b`, `differentiation`, `competitive_moat`, `threat_level` ("existential"|"significant"|"moderate"|"low"), `confidence`, `source`, `last_confirmed`, `created_at`, `valid_from`, `description`
  - [ ] Executive/board extraction from filing headers and DEF 14A — **MUST populate HAS_EXECUTIVE and HAS_BOARD_MEMBER edge properties** per [02-graph-schema.md](02-graph-schema.md) § Company ↔ People: `title`, `start_date`, `end_date`, `compensation_usd`, `stock_ownership_pct`, `source`, `last_confirmed`, `description` (for executives); `role`, `committee`, `is_independent`, `start_date`, `end_date`, `stock_ownership_shares`, `source`, `last_confirmed`, `description` (for board members)
  - [ ] Industry/sector classification — use SIC from EDGAR submissions JSON, map to Industry/Sector nodes per [03-data-ingestion.md](03-data-ingestion.md) § SIC/NAICS source table. Create OPERATES_IN (with `revenue_pct`, `is_primary`) and BELONGS_TO relationships per [02-graph-schema.md](02-graph-schema.md) § Company ↔ Industry / Sector
  - [ ] Risk factor categorization (geopolitical, regulatory, supply chain, financial)
- [ ] SEC Company Facts API fetcher for structured financial data (revenue, net income, EPS, etc.) — one `GET` per CIK to `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` returns all historical facts as JSON. **Prefer this over LLM extraction** per [03-data-ingestion.md](03-data-ingestion.md) § XBRL source notes and [02-graph-schema.md](02-graph-schema.md) § Confidence & Data Quality Principles ("prefer structured over extracted")
  - Map US GAAP concept names (e.g. `Revenues`, `NetIncomeLoss`, `EarningsPerShareDiluted`) → our `metric_type` names
  - Filter to 10-K FY entries; de-duplicate by keeping the earliest filing per period to avoid restated comparatives
  - Write full time series → DuckDB `financial_metrics` table (via `timeseries.py`), `accession` column preserved for provenance, per [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store
  - Generate `summary`, `risk_factors`, `opportunities` on Company node via LLM extraction from 10-K text; update `last_updated`
  - `market_cap` is populated in Phase 2 (requires price feed from FMP); leave null in Phase 0
- [ ] Filing → FalkorDB loader: create Filing nodes (keyed on `accession_number`), link to Company via `FILED` relationship, populate edge properties. Use MERGE operations per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 1 step 7
- [ ] Ingestion state tracking (SQLite) — track which filings have been fetched/parsed/loaded
- [ ] CLI commands: `ingest edgar --ticker AAPL`, `ingest edgar --list top50`

#### Financial Data Validation & Testing
> **Purpose**: Ensure that financial metrics fetched from the SEC Company Facts API and stored in DuckDB are correct, and that derived metrics (margins, growth rates, ratios) computed by the analytics layer are mathematically accurate. Tests should cover internal consistency, time-series sanity (no duplicate periods, monotonic dates), and — critically — cross-validation against the SEC Company Facts API itself to confirm that stored values match the authoritative source.

- [ ] Unit tests for the analytics layer: verify margin, growth-rate, and ratio calculations against hand-computed expected values
- [ ] Data integrity tests on the DuckDB store: no duplicate (ticker, metric, period) rows, no NULL values in required columns, fiscal year-end filtering produces exactly one row per year
- [ ] **Third-party cross-validation test**: for at least two ingested tickers, fetch the same metrics (revenue, net income, EPS) from a reputable public source and assert they match the values stored in DuckDB within an acceptable tolerance (e.g. ≤1% difference to account for rounding)
- [ ] Test runner invocable via `pytest tests/` — all financial-validation tests are part of the standard test suite

#### Agent Tools & Basic Agent (For Interactive Querying)
> **Implementation spec**: Tool signatures **MUST match** [04-agent-system.md](04-agent-system.md) § Agent Tools — exact function names, parameter names, types, and docstrings. Agent definition **MUST match** [04-agent-system.md](04-agent-system.md) § 3. Ripple Effect Analyzer.

- [ ] `src/investment_researcher/agents/tools/graph_tools.py` — `query_graph(cypher_query: str)`, `get_company_profile(ticker: str)`, `get_related_companies(ticker: str, relationship_types: list[str], max_depth: int)` using OpenAI Agents SDK `@function_tool` — **implement with exact signatures and docstrings from [04-agent-system.md](04-agent-system.md) § Graph Query Tools** (Phase 4 adds `semantic_search_graph`, `get_industry_peers`, and data tools to this same file)
- [ ] `src/investment_researcher/agents/tools/timeseries_tools.py` — `get_financial_history(ticker: str, metrics: list[str], quarters: int)` querying DuckDB `financial_metrics` table — **MUST match tool signature in [04-agent-system.md](04-agent-system.md) § Data Tools**. Growth rates computed at query time via SQL window functions per [02-graph-schema.md](02-graph-schema.md) § Growth Rate Strategy. Phase 2 expands this tool's usefulness as more data sources populate DuckDB
- [ ] `src/investment_researcher/agents/definitions/ripple_effect.py` — Ripple Effect Analyzer as a single OpenAI Agents SDK agent. **MUST use the exact `name`, `instructions`, `tools`, and `model` from [04-agent-system.md](04-agent-system.md) § 3. Ripple Effect Analyzer** — including confidence decay rules (0.9/hop), staleness decay, edge property usage instructions, and the "CRITICAL: Use edge properties for nuanced analysis" block (Phase 4 adds Triage, Screener, etc.)
- [ ] `chat` command routes to Ripple Effect Analyzer for interactive graph exploration

### Validation Criteria

> **Note**: These are data quality milestones, not concept validation tests. The platform proves itself through data quality, not contrived comparisons with ChatGPT.

#### Data Extraction Quality
- [ ] `ingest edgar --ticker AAPL` fetches 10-K filing, extracts entities/relationships, and loads into FalkorDB
- [ ] Extracted SUPPLIES_TO relationships have rich edge properties: product_category, dependency_level, is_sole_source, source (with accession number)
- [ ] Company Facts API fetcher writes financial metrics to DuckDB (`financial_metrics` table) with provenance
- [ ] `SELECT COUNT(*) FROM financial_metrics` → rows present for all ingested companies
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

#### Financial Dashboard
- [ ] `ir web` launches dashboard; selecting any ingested ticker shows its financial data
- [ ] Annual revenue chart shows correct fiscal-year values (not polluted by quarterly comparatives from Company Facts API data)
- [ ] Computed metrics (margins, growth rates, balance sheet ratios) are mathematically accurate
- [ ] Dashboard renders all charts and tables in the browser without errors

#### Financial Data Validation
- [ ] All analytics unit tests pass (`pytest tests/`)
- [ ] Third-party cross-validation passes for at least two tickers — computed revenue, net income, and EPS match a reputable source within ≤1% tolerance
- [ ] No data-integrity failures: no duplicate periods, no NULL required fields, fiscal-year filtering is correct

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
│       │   └── schema.py         ✓  (Company, Person, Industry, Sector, Filing, Region + indexes)
│       ├── ingestion/
│       │   ├── edgar/
│       │   │   ├── fetcher.py    ✓  (EDGAR filing fetcher — 10-K, 10-Q, 8-K download)
│       │   │   ├── parser.py     ✓  (HTML → markdown, section splitting)
│       │   │   ├── company_facts.py ✓  (SEC Company Facts API fetcher — replaces XBRL parsing)
│       │   │   └── extractor.py  ✓  (LLM-based entity/relationship extraction from filing text)
│       │   ├── loader.py         ✓  (Filing → FalkorDB node/edge writer)
│       │   ├── timeseries.py     ✓  (DuckDB writer: financial_metrics + macro_timeseries tables, recompute_snapshot)
│       │   └── state.py          ✓  (SQLite ingestion state tracker)
│       ├── analytics/
│       │   └── __init__.py       ✓  (financial analytics: margins, ratios, growth, FY-end detection)
│       ├── web/
│       │   ├── app.py            ✓  (FastAPI backend — REST API + static serving)
│       │   └── static/
│       │       └── index.html    ✓  (single-page financial dashboard — Chart.js)
│       └── agents/
│           ├── tools/
│           │   ├── graph_tools.py    ✓  (query_graph, get_company_profile, get_related_companies — Phase 4 expands)
│           │   └── timeseries_tools.py ✓  (get_financial_history — queries DuckDB; Phase 4 expands)
│           └── definitions/
│               └── ripple_effect.py ✓ (single OpenAI Agents SDK agent — Phase 4 adds more agents here)
├── tests/
│   ├── test_analytics.py         ✓  (unit tests for margin/growth/ratio calculations)
│   ├── test_data_integrity.py    ✓  (DuckDB uniqueness, NULLs, FY-end filtering)
│   └── test_crossvalidation.py   ✓  (compare DuckDB values vs third-party source)
├── cli.py                        ✓  (Typer: chat, ingest edgar, web — Phase 1 adds health)
├── README.md                     ✓  (setup, CLI usage, database debugging guide)
├── data/
│   ├── falkordb/                 ✓  (bind mount target — consistent with Phase 1+)
│   ├── duckdb/
│   │   └── financial_timeseries.duckdb ✓  (financial_metrics + macro_timeseries tables, seeded from Company Facts API)
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
- [ ] Expand `pyproject.toml` — add Langfuse, GraphRAG-SDK, MarkItDown deps **per [05-tech-stack.md](05-tech-stack.md)**
- [ ] Expand `.env.example` — add Langfuse keys, workstation config
- [ ] Expand `src/investment_researcher/graph/connection.py` — add retry logic, connection pooling
- [ ] Expand `src/investment_researcher/graph/schema.py` — add full relationship schema with **all edge properties exactly as defined in [02-graph-schema.md](02-graph-schema.md) § Core Relationships** (SUPPLIES_TO: 15+ properties, COMPETES_WITH: 13+ properties, OWNS_STAKE_IN, ACQUIRED, MERGED_WITH, JOINT_VENTURE_WITH, PARTNER_WITH, HAS_EXECUTIVE, HAS_BOARD_MEMBER, OPERATES_IN, BELONGS_TO, HEADQUARTERED_IN, HAS_MARKET_IN, HAS_OPERATIONS_IN, FILED). Add all indexes and constraints per [02-graph-schema.md](02-graph-schema.md) § Indexes
- [ ] Add `src/investment_researcher/graph/ontology.py` — ontology loading + GraphRAG-SDK integration. Auto-extended relationships stored as RELATED_TO per [02-graph-schema.md](02-graph-schema.md) § Auto-Extended Relationships (with `relationship_detail`, `source_document`, `confidence`, `auto_detected`, `detected_date`)
- [ ] Add `schemas/core_ontology.json` — hand-crafted core graph ontology **reflecting the exact node types and relationship types in [02-graph-schema.md](02-graph-schema.md)**
- [ ] Add `src/investment_researcher/observability/setup.py` — Langfuse + OpenInference instrumentation
- [ ] Add `src/investment_researcher/ingestion/preprocessor.py` — MarkItDown wrapper per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline Architecture (step 3 in every pipeline)
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

**Goal**: Scale SEC EDGAR pipeline from Phase 0's initial 50 companies to ~100. Add financial data API pipelines (FMP) and macro indicators (FRED). DuckDB is already initialized with its full schema in Phase 0 — this phase adds new ingestion pipelines that write to the existing store.

### Tasks
> **Implementation spec**: Financial data pipeline **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 2: Financial Data APIs. DuckDB schema was established in Phase 0 — all writes here use the same `timeseries.py` module via `write_financial_metrics()`. Growth rates are **computed at query time** via SQL window functions, NOT precomputed — see [02-graph-schema.md](02-graph-schema.md) § Growth Rate Strategy.

- [ ] SEC EDGAR pipeline — **scale from Phase 0** (fetcher, parser, Company Facts API, DuckDB write, and snapshot recompute already exist):
  - [ ] Scale extraction to S&P 100 companies
  - [ ] Improve extraction prompts based on Phase 0 accuracy results
  - [ ] GraphRAG-SDK entity extraction from filings (augment LLM-based extraction from Phase 0)
- [ ] Financial data pipeline **per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 2: Financial Data APIs**:
  - [ ] FMP or Polygon.io integration — use source table in [03-data-ingestion.md](03-data-ingestion.md) § Financial Modeling Prep for API endpoints, pricing tiers, and rate limits
  - [ ] Fundamental data fetcher (market cap, P/E, EPS, etc.)
  - [ ] Write time series → DuckDB (`financial_metrics` table with all columns per schema); recompute latest snapshot → FalkorDB Company node per [02-graph-schema.md](02-graph-schema.md) § Data Flow diagram
- [ ] FRED API integration for starter macro indicators — **use series IDs from [03-data-ingestion.md](03-data-ingestion.md) § FRED source table**: GDP, GDPC1, UNRATE, CPIAUCSL, CPILFESL, FEDFUNDS, DFF, T10YIE, T10Y2Y. Write to DuckDB `macro_timeseries` table. Create MacroIndicator graph nodes per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → MacroIndicator (`indicator_id`, `name`, `unit`, `source`)
- [ ] World Bank / IMF API integration for country economic data — **per [03-data-ingestion.md](03-data-ingestion.md) § World Bank / IMF source table**: use indicators NY.GDP.MKTP.CD, NY.GDP.MKTP.KD.ZG, FP.CPI.TOTL.ZG, NE.TRD.GNFS.ZS, GC.DOD.TOTL.GD.ZS
- [ ] Region/Country nodes: **MUST use exact Region node schema from [02-graph-schema.md](02-graph-schema.md) § Region** — identifier-only (`name`, `region_type`, `iso_code`, `last_updated`). Economic data stored as MacroIndicator nodes linked to Region via REPORTS_INDICATOR, NOT as properties on Region nodes
- [ ] Entity resolution: ticker/CIK-based dedup
- [ ] Ingestion state tracking (SQLite)
- [ ] CLI commands: `ingest edgar`, `ingest financials`, `ingest macro`, `ingest countries`
- [ ] Target list: Top 100 S&P 500 companies by market cap + G20 countries

> **Note**: Starter macro set here (5–10 key indicators). Full FRED indicator suite expands in Phase 3 per [03-data-ingestion.md](03-data-ingestion.md) build order.

### Validation Criteria
- `python cli.py ingest edgar --companies top100` completes successfully
- FalkorDB shows ~100 Company nodes with `summary`, `risk_factors`, `opportunities` populated from 10-K text
- Company nodes have `market_cap` populated (from FMP price feed)
- DuckDB `financial_metrics` table has 20+ quarters of data for tracked companies
- `SELECT COUNT(*) FROM financial_metrics` → meaningful count (thousands of rows)
- MacroIndicator nodes show current Fed Funds Rate, CPI, GDP, etc.
- DuckDB `macro_timeseries` table has historical FRED data
- Region nodes populated for G20 countries (identifier-only). MacroIndicator nodes linked to Regions for economic profiles
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
│   ├── company_facts.py        ✓
    └── structured.py          ✓
```

---

## Phase 3: Relationship Enrichment (Week 7-9)

**Goal**: Inter-company relationships populated. News pipeline running. Congressional disclosures flowing. The graph becomes a true network, not just isolated company profiles.

> **Scope discipline**: The tasks below are split into two tiers. **Tier 1** (this phase): News, supply chain, executives, competition, commodities, Congressional trades, company IR pages/press releases — the core relationship types needed to validate the Ripple Effect Analyzer. **Tier 2** (defer to Phase 5): 13F institutional holdings, government contracts, legislation/policy — valuable but not required for core validation. Complete Tier 1 before starting Tier 2. Resist the temptation to build everything at once.

### Tasks
> **Implementation spec**: All new node types and relationship types **MUST match** [02-graph-schema.md](02-graph-schema.md) § Future Data Sources (Phase 2-3 sections) and § Core Relationships. News pipeline **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 3: News. IR pages **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 4: Web Scraping. Congressional disclosures **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 6. Edge property extraction **MUST follow** [03-data-ingestion.md](03-data-ingestion.md) § Edge Property Extraction Strategy (includes exact LLM extraction prompts and confidence scoring tables).

- [ ] News pipeline **per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 3: News**:
  - [ ] NewsAPI or Finnhub integration — use source table in [03-data-ingestion.md](03-data-ingestion.md) § News APIs for API endpoints, pricing. **Recommended: Marketaux** per doc recommendation
  - [ ] Article deduplication (by URL hash per Pipeline 3 step 2)
  - [ ] LLM-based entity extraction + sentiment analysis (Pipeline 3 steps 4-5)
  - [ ] Impact scoring
  - [ ] Company-news relationship linking — create **NewsArticle nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → NewsArticle (`article_id`, `title`, `source`, `url`, `published_date`, `summary`, `sentiment`, `impact_score`, `embedding`). Link via **MENTIONED_IN** relationship
  - [ ] Political/policy news detection and linking
- [ ] Company IR pages & press releases (Tier 1 — **MUST follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 4: Web Scraping**, including pipeline steps 1-5):
  - [ ] RSS feed discovery for tracked companies (PRNewswire, BusinessWire, GlobeNewsWire) — use source table in [03-data-ingestion.md](03-data-ingestion.md) § Company Investor Relations Pages
  - [ ] Scrapy + RSS fetcher for IR pages and press release PDFs
  - [ ] LLM event classification (M&A, earnings, guidance, leadership, product launch) per Pipeline 4 step 2
  - [ ] GraphRAG-SDK entity extraction → NewsArticle, Filing, Person, Company nodes
  - [ ] Press-release-to-8-K reconciliation per Pipeline 4 step 4 (link press release → filing when 8-K confirms within 48 hrs)
  - [ ] Daily RSS polling cadence + weekly IR page deep scrape per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 4 Cadence
- [ ] Supply chain relationship extraction — **populate ALL SUPPLIES_TO edge properties per [02-graph-schema.md](02-graph-schema.md) § Company ↔ Company** and use **extraction prompts from [03-data-ingestion.md](03-data-ingestion.md) § Edge Property Extraction Strategy → SUPPLIES_TO Edges**:
  - [ ] From 10-K "Customers" / "Suppliers" sections (text mining) — extract from Item 1, Item 1A, Note 14/15 per [03-data-ingestion.md](03-data-ingestion.md) § SUPPLIES_TO Edges
  - [ ] From publicly available supply chain databases (ImportYeti per [03-data-ingestion.md](03-data-ingestion.md) § Company Supply Chain source table)
  - [ ] From news articles mentioning supply relationships
  - [ ] **Populate edge properties**: `product_category`, `dependency_level`, `is_sole_source`, `revenue_pct`, `contract_value_usd`, `volume_estimate`, `geographic_risk`, `alternative_suppliers`, `lead_time_weeks`, `confidence`, `source`, `last_confirmed`, `created_at`, `valid_from`, `valid_to`, `description` (LLM-generated narrative). Apply **confidence scoring by source** per [03-data-ingestion.md](03-data-ingestion.md) § Confidence Scoring by Source table (Company Facts API: 0.95-1.0, 10-K suppliers: 0.80-0.90, Risk Factors: 0.70-0.85, News: 0.60-0.75)
- [ ] Executive/board member linking — **use extraction strategy from [03-data-ingestion.md](03-data-ingestion.md) § HAS_EXECUTIVE / HAS_BOARD_MEMBER Edges** (parse DEF 14A tables structurally, not via LLM, per doc recommendation for Summary Compensation Table):
  - [ ] Extract from DEF 14A (proxy statement) filings
  - [ ] **Populate HAS_EXECUTIVE edge properties** per [02-graph-schema.md](02-graph-schema.md): `title`, `start_date`, `end_date`, `compensation_usd`, `stock_ownership_pct`, `source`, `last_confirmed`, `description`
  - [ ] **Populate HAS_BOARD_MEMBER edge properties** per [02-graph-schema.md](02-graph-schema.md): `role`, `committee` (array), `is_independent`, `start_date`, `end_date`, `stock_ownership_shares`, `source`, `last_confirmed`, `description`
  - [ ] Link people across companies (enables board interlock queries per [02-graph-schema.md](02-graph-schema.md) § Example Traversals)
- [ ] Competitive dynamics — **use extraction prompts from [03-data-ingestion.md](03-data-ingestion.md) § COMPETES_WITH Edges**:
  - [ ] Industry peer grouping (GICS-based)
  - [ ] COMPETES_WITH relationships from filing text — extract from 10-K Item 1 → Competition section
  - [ ] **Populate ALL COMPETES_WITH edge properties** per [02-graph-schema.md](02-graph-schema.md) § Company ↔ Company: `market_segment`, `intensity` ("direct"|"partial"|"adjacent"|"emerging"), `geographic_overlap` (array), `market_share_a`, `market_share_b`, `differentiation`, `competitive_moat`, `threat_level` ("existential"|"significant"|"moderate"|"low"), `confidence`, `source`, `last_confirmed`, `created_at`, `valid_from`, `description`
- [ ] Commodity dependencies — create **Commodity nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → Commodity:
  - [ ] Map key commodities to industries via DEPENDS_ON / PRODUCES / AFFECTS_INDUSTRY relationships
  - [ ] Company-commodity relationships from filing risk factors
- [ ] Congressional investment disclosures — **MUST follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 6: Congressional Investment Disclosures** (pipeline steps 1-3, source tables, entity resolution):
  - [ ] Capitol Trades or Quiver Quantitative API integration — use source table in [03-data-ingestion.md](03-data-ingestion.md) § Congressional Disclosures for API endpoints
  - [ ] **Legislator nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → Legislator (keyed on `bioguide_id`) + **CongressionalTrade nodes** per § CongressionalTrade
  - [ ] Committee assignment mapping — use Congress.gov API per [03-data-ingestion.md](03-data-ingestion.md) § Congressional Committee Assignments source table (API key, 5000 req/hr)
  - [ ] Relationships: `DISCLOSED_TRADE` (Legislator → CongressionalTrade), `INVOLVES` (CongressionalTrade → Company), `MEMBER_OF` (Legislator → Committee) per [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 6
  - [ ] Trade → Company linkage (match asset description → Company node by ticker per Pipeline 6 step 2)
- [ ] **[Tier 2 — defer to Phase 5]** Institutional holdings (13F) — **when built, MUST follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 7: Institutional Holdings — 13F** (pipeline steps 1-5, CUSIP→ticker mapping via OpenFIGI):
  - [ ] EDGAR 13F filing parser (XML)
  - [ ] **InstitutionalHolder nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → InstitutionalHolder (keyed on CIK) + **HOLDS_POSITION relationships** (shares, value, quarter, position change type)
  - [ ] Quarter-over-quarter change computation per Pipeline 7 step 3
  - [ ] Seed: Top 100 institutional filers by AUM

  > **Tier note**: Doc [03-data-ingestion.md](03-data-ingestion.md) classifies 13F as Tier 1 (Pipeline 7) due to its data importance. It is deferred here to Phase 5 for *implementation sequencing* — the Ripple Effect Analyzer can be validated without 13F data, and building the 13F parser is a separate engineering effort.

- [ ] **[Tier 2 — defer to Phase 5]** Government & policy data — **when built, MUST follow [03-data-ingestion.md](03-data-ingestion.md) § Pipeline 8: Government & Policy Data** (pipeline steps 1-3):
  - [ ] Congress.gov API for active bills + status tracking — use source table in [03-data-ingestion.md](03-data-ingestion.md) § Legislation & Bill Tracking
  - [ ] Federal Register API for regulations/executive orders
  - [ ] **Legislation nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → Legislation + **AFFECTS relationships** to industries (with `impact_type`, `direction`, `confidence`)
  - [ ] USAspending.gov for government contracts (> $1M) — **GovernmentContract nodes** per [02-graph-schema.md](02-graph-schema.md) § Future Data Sources → GovernmentContract, use source table in [03-data-ingestion.md](03-data-ingestion.md) § Federal Government Contracts
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
> **Implementation spec**: All agent definitions, tools, guardrails, report schema, and handoff flows **MUST match** [04-agent-system.md](04-agent-system.md) exactly. Agent `name`, `instructions`, `tools` list, `handoffs` list, and `model` are defined as Python code blocks in that document — treat them as implementation specs, not pseudocode. Tool function signatures (parameter names, types, docstrings) are contracts. Report JSON schema is defined in [04-agent-system.md](04-agent-system.md) § 6. Research Synthesizer. Paper trading model is defined in [04-agent-system.md](04-agent-system.md) § Paper Trading Protocol. LLM model assignments per agent are defined in [04-agent-system.md](04-agent-system.md) § LLM Model Strategy.

- [ ] Agent tools implementation (all in `agents/tools/` — expanding files created in Phase 0) — **MUST implement exact function signatures from [04-agent-system.md](04-agent-system.md) § Agent Tools**:
  - [ ] `query_graph(cypher_query: str)` — ✅ Phase 0 (already in `graph_tools.py`, expand for full Cypher support)
  - [ ] `get_company_profile(ticker: str)` — ✅ Phase 0 (expand: must query **both FalkorDB and DuckDB** per [04-agent-system.md](04-agent-system.md) § Graph Query Tools docstring)
  - [ ] `get_related_companies(ticker: str, relationship_types: list[str], max_depth: int)` — ✅ Phase 0 (expand hop depth + filters)
  - [ ] `semantic_search_graph(query: str, node_type: str, limit: int)` — NEW: **exact signature from [04-agent-system.md](04-agent-system.md) § Graph Query Tools**
  - [ ] `get_industry_peers(ticker: str)` — NEW: **per [04-agent-system.md](04-agent-system.md) § Graph Query Tools** (uses Company node snapshots + DuckDB growth rates)
  - [ ] `get_recent_news(ticker: str, industry: str, hours: int, min_impact_score: float)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Data Tools**
  - [ ] `get_macro_indicators(indicator_type: str)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Data Tools**
  - [ ] `get_congressional_trades(legislator: str, ticker: str, party: str, chamber: str, days: int, transaction_type: str)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Political & Government Tools**
  - [ ] `get_institutional_holdings(ticker: str, holder: str, quarter: str, min_value_usd: float)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Political & Government Tools** *(stub until Phase 5 data pipeline)*
  - [ ] `get_policy_impacts(industry: str, legislation_type: str, status: str, days: int)` — **exact signature** *(stub until Phase 5 data pipeline)*
  - [ ] `get_country_profile(country: str)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Political & Government Tools**
  - [ ] `get_government_contracts(ticker: str, agency: str, min_value: float, days: int)` — **exact signature** *(stub until Phase 5 data pipeline)*
  - [ ] `write_report(title, ticker, thesis, direction, confidence, time_horizon, catalysts, risks, bear_case, supporting_evidence, source_citations, related_companies, macro_context, report_type)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Report Tools**. Reports created with `status='needs_review'`
  - [ ] `get_existing_reports(ticker: str, report_type: str, days: int)` — Duplicate check
  - [ ] `get_financial_history(ticker: str, metrics: list[str], quarters: int)` — **exact signature from [04-agent-system.md](04-agent-system.md) § Data Tools** with `lru_cache`, DuckDB window functions for growth rates
  - [ ] `get_recent_ingestion_stats()` — per [04-agent-system.md](04-agent-system.md) § Data Tools
  - [ ] `get_commodity_impacts(commodity: str)` — per [04-agent-system.md](04-agent-system.md) § Data Tools
- [ ] Agent definitions (all in `agents/definitions/` — directory created in Phase 0) — **MUST use exact `name`, `instructions`, `tools`, `handoffs`, `model` from [04-agent-system.md](04-agent-system.md) § Agent Definitions**:
  - [ ] Triage Agent (router) — NEW: add `triage.py`. **Use exact instructions from [04-agent-system.md](04-agent-system.md) § 1. Triage Agent** including thesis detection routing logic, `model="gpt-4.1"`, handoffs to all 5 specialists
  - [ ] Ripple Effect Analyzer — ✅ Phase 0 (`ripple_effect.py` exists, expand). **Update instructions to match full spec in [04-agent-system.md](04-agent-system.md) § 3. Ripple Effect Analyzer** — must include: confidence decay (0.9/hop), staleness decay, ALL edge property usage instructions (SUPPLIES_TO 6 properties, COMPETES_WITH 4 properties, HAS_EXECUTIVE 3 properties, example Cypher queries), thesis exploration mode, `model="gpt-4.1"`
  - [ ] Fundamental Screener — NEW: add `fundamental_screener.py`. **Use exact spec from [04-agent-system.md](04-agent-system.md) § 4. Fundamental Screener** including screening criteria, DuckDB integration, `model="gpt-4.1"`
  - [ ] Macro-Micro Linker — NEW: add `macro_micro.py`. **Use exact spec from [04-agent-system.md](04-agent-system.md) § 5. Macro-Micro Linker** including analytical chains, country data, `model="gpt-4.1"`
  - [ ] Research Synthesizer — NEW: add `research_synthesizer.py`. **Use exact spec from [04-agent-system.md](04-agent-system.md) § 6. Research Synthesizer** including report JSON schema (must include `bear_case`, `source_citations`, `report_type`, `status: "needs_review"`), `model="gpt-4.1"`
  - [ ] Data Monitor Agent — NEW: add `data_monitor.py`. **Use exact spec from [04-agent-system.md](04-agent-system.md) § 2. Data Monitor Agent** including significance thresholds, `model="gpt-4.1"`
- [ ] Guardrails — **implement per [04-agent-system.md](04-agent-system.md) § Guardrails** (exact guardrail function signatures defined there):
  - [ ] Input: `validate_query_safety` — Cypher injection prevention per [04-agent-system.md](04-agent-system.md) § Input Guardrails
  - [ ] Input: `check_market_hours` — stale data sensitivity flag per [04-agent-system.md](04-agent-system.md) § Input Guardrails
  - [ ] Output: `validate_report_quality` — confidence > 0.5, all required fields, thesis specificity per [04-agent-system.md](04-agent-system.md) § Output Guardrails
  - [ ] Output: `enforce_bear_case` — reject reports with empty/dismissive bear case per [04-agent-system.md](04-agent-system.md) § Output Guardrails
  - [ ] Output: `enforce_source_citations` — every factual claim must reference filing accession, article URL, Cypher query, or data source per [04-agent-system.md](04-agent-system.md) § Output Guardrails
  - [ ] Hypothesis framing guardrail (ensure outputs are framed as hypotheses, not conclusions — per [00-strategic-rationale.md](00-strategic-rationale.md))
- [ ] Confidence decay across hops:
  - [ ] Implement hop-distance-based confidence discount (90% per hop)
  - [ ] Display confidence at each hop in ripple effect results
- [ ] Report queue (SQLite) — **report JSON schema MUST match [04-agent-system.md](04-agent-system.md) § 6. Research Synthesizer** output format:
  - [ ] Report model (Pydantic) — fields: `title`, `ticker`, `thesis`, `direction`, `confidence`, `time_horizon`, `catalysts`, `risks`, `bear_case`, `supporting_evidence`, `source_citations` (array of `{type, accession_number/url/query, detail}`), `related_companies`, `macro_context`, `report_type` ("opportunity"|"risk"|"ripple_effect"|"macro_impact"|"political_signal"), `status` ("needs_review")
  - [ ] SQLite store (CRUD)
  - [ ] CLI viewer
- [ ] Human review workflow:
  - [ ] Reports flagged as "needs_review" before action
  - [ ] CLI `reports review <id>` command to mark as reviewed/rejected
- [ ] Paper trading system — **MUST implement exact `PaperTrade` model from [04-agent-system.md](04-agent-system.md) § Paper Trading Protocol**:
  - [ ] PaperTrade model: `report_id`, `ticker`, `direction`, `entry_price`, `entry_date`, `thesis`, `confidence`, `time_horizon`, `price_30d`, `price_60d`, `price_90d`, `return_30d`, `return_60d`, `return_90d`, `thesis_correct`, `notes`
  - [ ] Auto-record paper trades for reports with confidence > 0.6 per [04-agent-system.md](04-agent-system.md) § Decision Framework
  - [ ] Price snapshot fetcher (30/60/90 day follow-up)
  - [ ] CLI: `paper-trades list`, `paper-trades review <id>`
  - [ ] CLI: `paper-trades performance` (hit rate, returns vs. SPY) — tracking metrics per [04-agent-system.md](04-agent-system.md) § Performance Tracking
- [ ] CLI `chat` command routed through Triage Agent
- [ ] CLI `reports list` and `reports view` commands
- [ ] Thesis-driven research flow — **handoff flow per [04-agent-system.md](04-agent-system.md) § Handoff Flow Examples → Thesis-Driven**:
  - [ ] CLI `explore "thesis statement"` command
  - [ ] Triage Agent thesis detection and routing logic (per [04-agent-system.md](04-agent-system.md) § 1. Triage Agent instructions: distinguish QUESTION vs THESIS)
  - [ ] Ripple Effect Analyzer thesis exploration mode per [04-agent-system.md](04-agent-system.md) § 3. Ripple Effect Analyzer "FOR THESIS EXPLORATION" block (multi-directional: long, short, hedge)
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
- [ ] Autonomous agent loop — **MUST implement exact scheduler configuration from [04-agent-system.md](04-agent-system.md) § Autonomous Agent Loop** (includes `run_data_monitor`, `run_fundamental_screen`, `run_macro_check` functions with exact input strings):
  - [ ] APScheduler-based trigger system
  - [ ] Data Monitor runs every 30 min (per [04-agent-system.md](04-agent-system.md) § Autonomous Agent Loop)
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
- [ ] Multi-tier model routing (workstation + Mac cluster) — **model assignments per agent MUST follow [04-agent-system.md](04-agent-system.md) § LLM Model Strategy** (Triage/Monitor: mini/8B, Ripple/Synthesizer: 4.1/405B, Screener/Macro: 4.1/70B):
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
| 0. Data Foundation | Week 1-3 | Graph schema, SEC EDGAR extraction pipeline, Company Facts API financials. Data quality is the validation |
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
