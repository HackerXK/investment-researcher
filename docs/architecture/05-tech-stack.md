# Technology Stack — Integration Details

> Cross-references: [00-strategic-rationale.md](00-strategic-rationale.md) for why these technologies were chosen, [08-hardware-requirements.md](08-hardware-requirements.md) for hardware specs.

## Stack Overview

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Graph Database | FalkorDB | latest | Property graph storage, Cypher queries, vector indexing |
| SEC Data Access | edgartools | 5.x+ | **Primary SEC EDGAR interface.** Structured Python objects for all SEC filing types (10-K, 10-Q, 8-K, DEF 14A, 13F, Form 4, 13D/G, etc.), financial statements (XBRL), full-text search, filing content extraction (HTML, markdown). Replaces raw EDGAR API calls, `sec-edgar-downloader`, and manual XML parsing. Free, MIT licensed, no API keys |
| Knowledge Graph SDK | GraphRAG-SDK | 0.8.1+ | Ontology management, document→KG extraction, NL→Cypher |
| Document Processing | Docling | 2.x+ | AI-powered document conversion (PDF/DOCX/PPTX/XLSX/HTML/images → Markdown/JSON). Advanced table extraction, layout analysis, OCR. **Not needed for SEC filings** — edgartools provides `.markdown()` natively. MIT licensed, IBM/LF AI & Data |
| Agent Orchestration | OpenAI Agents SDK | 0.9+ | Multi-agent system, handoffs, guardrails, tools |
| Observability | Langfuse | latest | LLM tracing, cost tracking, prompt management |
| LLM Provider (Initial) | OpenAI API | — | GPT-4.1, GPT-4.1-mini, text-embedding-3-small |
| LLM Provider (Future) | exo / MLX on Mac Studio cluster | — | Distributed local model serving via Thunderbolt 5 RDMA (Phase 6+, gated on RTX 5090 proving insufficient) |
| Task Scheduling | APScheduler | 3.x | Cron-like scheduling for ingestion + agent loops |
| Report Storage | SQLite | 3.x | Report queue, ingestion state tracking |
| Time Series Store | DuckDB | 1.x+ | Financial metrics time series, macro time series, growth computations. See [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store |
| CLI Framework | Typer | 0.9+ | Interactive command-line interface |
| Frontend Framework | Nuxt 3 + Vue 3 | 3.x | SSR/SPA framework for the web UI. File-based routing, composables, TypeScript. Simply Wall St-style company profiles + chat interface |
| UI Components | shadcn-vue | latest | Accessible, professional component primitives (buttons, cards, tabs, dialogs, sheets). Tailwind-based, copy-paste ownership — no heavy dependency |
| CSS Framework | Tailwind CSS | 3.x | Utility-first styling. Consistent design tokens, responsive, dark-mode ready |
| Charting | Apache ECharts | 5.x | Rich interactive financial charts — candlestick, bar, line, treemap, pie. Better financial chart vocabulary than Chart.js |
| Data Tables | TanStack Vue Table | 8.x | Headless table engine for filings lists, financial data grids. Sorting, filtering, pagination |
| State / Data Fetching | TanStack Vue Query + Pinia | latest | Server-state caching + client-state management. Eliminates manual loading/error boilerplate |
| Forms / Validation | vee-validate + zod | latest | Schema-driven form validation (search, chat input, filters) |
| API Backend | FastAPI | 0.115+ | REST API serving analytics, company data, chat SSE streaming. Proxy target for Nuxt `server/api` or direct fetch |
| Web Server | Uvicorn | 0.30+ | ASGI server for FastAPI. Launched via `ir web` CLI command |
| HTTP Client | httpx | — | Async HTTP for API calls |
| Container Runtime | Docker + Compose | — | Runs on AMD workstation (RTX 5090). See [08-hardware-requirements.md](08-hardware-requirements.md) |

---

## FalkorDB — Deep Dive

### What It Does
FalkorDB is an in-memory property graph database built as a Redis module. It stores nodes and relationships with properties, supports OpenCypher queries, and provides vector similarity indexing for RAG use cases.

### How We Use It
- **Primary data store** for the entire knowledge graph
- **Cypher queries** for graph traversals (ripple effect analysis, relationship discovery)
- **Vector indexes** for semantic search across company descriptions, news, filings
- **Full-text indexes** for keyword search
- **Browser UI** (port 3000) for visual graph exploration during development

### Configuration
```yaml
# docker-compose.yml (runs on AMD workstation)
falkordb:
  image: falkordb/falkordb:latest
  ports:
    - "6379:6379"   # Data (Redis protocol)
    - "3000:3000"   # Browser UI
  volumes:
    - ./data/falkordb:/data    # bind mount — deterministic path
  environment:
    - FALKORDB_ARGS=--maxmemory 16gb --save 60 1000
  restart: unless-stopped
```

> **Note**: FalkorDB `--maxmemory` set to 16 GB (workstation has 64 GB total — 16 GB budgeted for graph). Data persists via bind mount to `./data/falkordb/` on the SK Hynix P41 2TB Gen4 volume (latency-sensitive databases; this is a standalone drive, not part of the RAID 0 array).

### Python Client
```python
from falkordb import FalkorDB

db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("investment_graph")

# Query
result = graph.query("""
    MATCH (c:Company {ticker: $ticker})-[:SUPPLIES_TO]->(customer)
    RETURN customer.name, customer.ticker
""", params={"ticker": "TSM"})

for record in result.result_set:
    print(record)
```

### Memory Sizing
- **Estimate**: ~1KB per node, ~0.5KB per relationship (with properties)
- **At full build (5,000 companies + legislators + institutions + all relationships + metrics)**: ~800K nodes, ~3M+ relationships
- **Phase 1 (SEC-only, ~50 companies)**: ~5K nodes, ~20K relationships — well within 1 GB
- **Estimated RAM (full build)**: 3-6 GB for graph data + 2-4 GB for vector indexes
- **Recommendation**: Set `--maxmemory 16gb`, monitor with FalkorDB UI
- **Growth note**: Congressional trades + 13F holdings + government contracts (Phase 3–5) add significant node/relationship volume over time

---

## GraphRAG-SDK — Deep Dive

### What It Does
GraphRAG-SDK automates the pipeline from unstructured documents to a queryable knowledge graph. It handles ontology detection, entity/relationship extraction, and natural language → Cypher translation.

### How We Use It

**1. Ontology Management (Hybrid Approach)**
```python
from graphrag_sdk import Ontology
from graphrag_sdk.models.litellm import LiteModel

model = LiteModel(model_name="openai/gpt-4.1")

# Start with hand-crafted core ontology loaded from JSON
core_ontology = Ontology.from_json("schemas/core_ontology.json")

# Auto-extend from new document sources
extended = Ontology.from_sources(
    sources=new_sources,
    model=model,
    existing_ontology=core_ontology  # Extend, don't replace
)
```

**2. Knowledge Graph Construction**
```python
from graphrag_sdk import KnowledgeGraph
from graphrag_sdk.model_config import KnowledgeGraphModelConfig

model_config = KnowledgeGraphModelConfig.with_model(model)

kg = KnowledgeGraph(
    name="investment_graph",
    model_config=model_config,
    ontology=ontology,
    host="localhost",
    port=6379,
)

# Process documents → extract entities → load into FalkorDB
kg.process_sources(sources)
```

**3. Natural Language Queries (as Agent Tool)**
```python
# Exposed as a tool to OpenAI Agents SDK agents
chat = kg.chat_session()
response = chat.send_message("Which companies supply Apple?")
# Internally: NL → Cypher → FalkorDB query → NL response
```

### Key Decision: GraphRAG-SDK vs. Direct Cypher

| Use Case | Approach |
|----------|----------|
| Unstructured text → entities | GraphRAG-SDK `process_sources()` |
| Structured data → nodes | Direct Cypher `MERGE` (skip GraphRAG-SDK) |
| Agent ad-hoc queries | Both: GraphRAG-SDK for NL→Cypher, direct Cypher for precise queries |
| Multi-hop traversals | Direct Cypher (more control over traversal depth/filters) |

---

## edgartools — Deep Dive

### What It Does
edgartools is a Python library for accessing SEC EDGAR filings as structured data. It parses financial statements, insider trades, fund holdings, proxy statements, and 20+ other filing types into typed Python objects with properties, methods, and DataFrames. Free, MIT licensed, no API keys required.

### How We Use It
- **Primary and sole interface to SEC EDGAR** — all SEC data flows through edgartools
- **Offline-first via local storage** — all SEC metadata and filings are downloaded locally for maximum performance (10-100x faster) and offline capability. See [Local Storage](#edgartools-local-storage) below
- **Company lookup**: by ticker or CIK, with metadata (industry, SIC, shares outstanding, public float)
- **Filing access**: fetch, filter, and parse all filing types (10-K, 10-Q, 8-K, DEF 14A, 13F-HR, Form 4, 13D/G, S-1, N-PORT, etc.)
- **Financial statements**: `company.get_financials()` → parsed income statement, balance sheet, cash flow as DataFrames
- **Historical XBRL data**: `company.get_facts()` → all historical XBRL facts as structured data (for granular concept-level queries)
- **Filing content extraction**: `.markdown()` for LLM-ready text, `.html()`, `.xbrl()`, `.sections()`, `.search()`
- **13F institutional holdings**: `filing.obj()` → `.holdings` DataFrame with complete portfolio positions
- **Insider trades (Form 4)**: `filing.obj()` → `.transactions` with buy/sell details
- **Proxy statements (DEF 14A)**: `filing.obj()` → executive compensation, pay vs performance, TSR
- **8-K events**: `filing.obj()` → `.items` with structured event data
- **10-K data objects**: `.auditor`, `.subsidiaries` as structured objects
- **Schedule 13D/G**: beneficial ownership data
- **Full-text search**: via EFTS (`find("supply chain disruption", form="10-K")`)

### Integration Pattern
```python
from edgar import *

# Set identity (required by SEC)
set_identity("your.name@example.com")

# Enable local storage for offline-first operation (see Local Storage section below)
use_local_storage("./data/edgar")

# Company lookup
company = Company("AAPL")

# Get financial statements (parsed from XBRL)
financials = company.get_financials()
income = financials.income_statement()   # DataFrame
balance = financials.balance_sheet()     # DataFrame
cashflow = financials.cashflow_statement()  # DataFrame

# Get all historical XBRL facts (granular concept-level data)
facts = company.get_facts()
revenue_df = facts.to_pandas("us-gaap:Revenues")  # Revenue history as DataFrame

# Get filings
filings = company.get_filings(form="10-K")
tenkfiling = filings.latest()

# Extract filing content as markdown (for LLM/GraphRAG-SDK ingestion)
markdown_text = tenkfiling.markdown()

# Parse 10-K into structured data object
tenk = tenkfiling.obj()
subsidiaries = tenk.subsidiaries  # Structured subsidiaries list
auditor = tenk.auditor            # Auditor info

# 13F institutional holdings
thirteenf_filing = get_filings(form="13F-HR")[0]
holdings = thirteenf_filing.obj().holdings  # DataFrame of all positions

# Insider trades (Form 4)
form4 = company.get_filings(form="4")[0].obj()
transactions = form4.transactions  # Insider buy/sell transactions

# Proxy statement (DEF 14A) — executive compensation
proxy = company.get_filings(form="DEF 14A").latest().obj()
ceo_comp = proxy.peo_total_comp
exec_comp_df = proxy.executive_compensation  # 5-year exec compensation DataFrame

# 8-K events
eightk = company.get_filings(form="8-K")[0].obj()
items = eightk.items  # List of reported event items

# Full-text search across all filings
results = find("supply chain disruption", form="10-K")

# Feed markdown to GraphRAG-SDK for entity extraction
from graphrag_sdk.source import Source
source = Source(content=markdown_text, metadata={"type": "10-K", "ticker": "AAPL"})
kg.process_sources([source])
```

### What edgartools Replaces

| Previously | Now |
|-----------|-----|
| Direct `data.sec.gov/submissions/CIK{cik}.json` API calls | `Company(ticker_or_cik)` |
| Direct `data.sec.gov/api/xbrl/companyfacts/` API calls | `company.get_facts()` |
| `sec-edgar-downloader` for filing downloads | `company.get_filings()` |
| Manual HTML/XML parsing of filings | `filing.obj()` → typed Python objects |
| Docling / any converter for SEC filing HTML → Markdown | `filing.markdown()` |
| Custom 13F XML parser | `filing.obj().holdings` DataFrame |
| Custom Form 4 XML parser | `filing.obj().transactions` |
| Custom DEF 14A HTML parser | `filing.obj()` → proxy data object |
| Custom 8-K parser | `filing.obj().items` |
| Raw EFTS search API calls | `find(query, form=...)` |

### edgartools Local Storage

edgartools supports downloading all SEC data locally for **offline operation and maximum performance** (10-100x faster than remote requests). We use the **Offline Research Environment** pattern — all SEC metadata, financial facts, and filing documents are stored on the local NVMe.

#### Setup
```python
from edgar import use_local_storage, download_edgar_data, download_filings

# Enable local storage (pointed at project data directory)
use_local_storage("./data/edgar")

# Step 1: Download metadata (~24 GB) — company info, filing indexes, financial facts
download_edgar_data()  # submissions + facts + reference data

# Step 2: Download actual filing documents for offline XBRL parsing and content access
download_filings("2021-01-01:")  # 5 years of filings
```

#### What Gets Downloaded

| Function | What | Size | Enables |
|----------|------|------|--------|
| `download_edgar_data(reference=True)` | Ticker/CIK mappings, exchanges | ~50 MB | `Company("AAPL")` lookups |
| `download_edgar_data(facts=True)` | Pre-processed XBRL financial facts | ~2 GB | `company.get_facts()`, `company.get_financials()` |
| `download_edgar_data(submissions=True)` | Company metadata + filing indexes | ~5 GB | `company.get_filings()` browsing |
| `download_edgar_data()` | All of the above | ~24 GB | Full metadata offline |
| `download_filings("2021-01-01:")` | Actual filing documents (HTML, XBRL, attachments) | ~50-150 GB/year | `filing.markdown()`, `filing.xbrl()`, `filing.obj()` |

#### Directory Structure (under `./data/edgar/`)
```
data/edgar/
├── reference/              # Ticker and exchange data
├── companyfacts/           # Company financial facts (XBRL)
├── submissions/            # Company metadata + filing indexes
└── filings/                # Filing documents by date
    ├── 20250115/
    │   ├── filing1.nc
    │   └── filing2.nc.gz   # Compressed filings
    └── ...
```

#### Incremental Updates
```python
# Weekly: download only the last 7 days of new filings
from datetime import datetime, timedelta
recent = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
download_filings(f"{recent}:")
```

#### Configuration
- **Environment variable**: `EDGAR_LOCAL_DATA_DIR=./data/edgar`
- **Programmatic**: `use_local_storage("./data/edgar")`
- **Compression**: `download_filings("2025-01-15", compression_level=9)` for maximum space savings
- When local storage is enabled, edgartools checks local storage first before making SEC requests

### When to Use edgartools vs. Other Tools

| Data Source | Tool | Why |
|------------|------|-----|
| Any SEC EDGAR data | **edgartools** (always) | Structured Python objects, no raw parsing needed |
| Non-SEC documents (uploaded PDFs, DOCX, PPTX) | Docling | edgartools is SEC-only. Docling provides AI-powered table extraction and layout analysis |
| Scraped web pages (IR pages, news) | Docling | HTML cleanup for non-SEC content |
| Non-SEC structured data (FMP, FRED, APIs) | httpx / custom parsers | Not SEC data |

---

## Docling — Deep Dive

### What It Does
IBM's AI-powered document understanding and conversion library (LF AI & Data Foundation project, MIT licensed). Uses deep learning models for page layout analysis, table structure recognition, OCR, and formula detection. Produces high-fidelity Markdown, JSON, and its own `DoclingDocument` structured format.

### Why Docling over MarkItDown
- **AI-powered table extraction** — critical for financial documents (compensation tables, balance sheets, earnings summaries). Uses trained models to detect table structure vs. MarkItDown's heuristic approach
- **Advanced PDF layout analysis** — handles multi-column layouts, figures, reading order detection in investor presentations and research reports
- **Built-in OCR** — processes scanned financial documents without extra dependencies
- **XBRL parsing** — native support for eXtensible Business Reporting Language financial reports
- **Visual Language Model support** — optional GraniteDocling VLM for complex document understanding
- **MCP server** — built-in Model Context Protocol server for agentic applications
- **Native RAG integrations** — LangChain, LlamaIndex, Crew AI, Haystack

### How We Use It
- **NOT used for SEC filings** — edgartools provides `.markdown()` natively for all filing types
- Converts **non-SEC** uploaded documents (PDF, DOCX, PPTX, XLSX, images) → Markdown
- Converts scraped web pages (company IR pages, news articles) → clean Markdown (strips boilerplate)
- Converts investor presentation PDFs from company websites → Markdown with accurate table preservation

### Integration Pattern
```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()

# Convert non-SEC document (e.g., uploaded investor presentation PDF)
result = converter.convert("uploads/company_presentation.pdf")
markdown_text = result.document.export_to_markdown()

# Convert scraped IR page HTML
result = converter.convert("data/raw/ir_pages/aapl_press_release.html")
markdown_text = result.document.export_to_markdown()

# Feed to GraphRAG-SDK
from graphrag_sdk.source import Source
source = Source(content=markdown_text, metadata={"type": "press_release", "ticker": "AAPL"})
kg.process_sources([source])
```

### When Docling Is Needed vs. Not

| Format | Docling Needed? | Why |
|--------|----------------|-----|
| SEC filings (10-K, 10-Q, 8-K, etc.) | **No** | edgartools provides `.markdown()` natively |
| Non-SEC PDF (investor presentations, reports) | Yes | AI-powered table extraction and layout analysis |
| Non-SEC HTML (IR pages, news articles) | Yes | Clean up web boilerplate before entity extraction |
| DOCX/PPTX/XLSX | Yes | GraphRAG-SDK doesn't handle these natively |
| Scanned documents / images | Yes | Built-in OCR support |
| JSON/CSV | No | Custom parsers for structured data |
| Plain text | No | Pass directly to GraphRAG-SDK |

---

## Frontend (Nuxt 3 + Vue 3) — Deep Dive

### What It Does
Nuxt 3 is an opinionated full-stack Vue framework with file-based routing, auto-imports, server routes, and SSR/SPA flexibility. Combined with shadcn-vue components and Tailwind CSS, it produces a professional, maintainable frontend without heavy UI framework lock-in.

### Why This Stack

| Decision | Choice | Rationale |
|----------|--------|----------|
| Framework | Nuxt 3 (not plain Vite + Vue) | File-based routing, layouts, composables, sensible defaults — less boilerplate to maintain |
| UI Components | shadcn-vue (not PrimeVue, Vuetify) | Copy-paste ownership, Tailwind-native, professional look without heavy dependency. No version-upgrade breakage risk |
| Charting | Apache ECharts (not Chart.js) | Richer financial chart vocabulary: candlestick, treemap, heatmap, radar — better fit for "Simply Wall St" style. Better performance at large datasets |
| Data fetching | TanStack Vue Query (not raw fetch/axios) | Automatic caching, deduplication, background refetch, loading/error states — eliminates boilerplate |
| State | Pinia | Nuxt-native, lightweight, TypeScript-first client state (user preferences, chat history) |
| Tables | TanStack Vue Table | Headless — style with Tailwind/shadcn. Sorting, filtering, pagination built-in |
| Validation | vee-validate + zod | Schema-driven, composable, works with shadcn-vue form components |

### Project Structure
```
frontend/
├── nuxt.config.ts
├── package.json
├── tailwind.config.ts
├── tsconfig.json
├── app.vue                     # Root layout
├── pages/
│   ├── index.vue               # Company search / landing
│   ├── company/
│   │   └── [ticker].vue        # Company profile (tabs, charts, chat)
│   └── chat.vue                # Standalone chat page
├── components/
│   ├── ui/                     # shadcn-vue primitives (auto-generated)
│   │   ├── button/
│   │   ├── card/
│   │   ├── tabs/
│   │   ├── input/
│   │   ├── sheet/
│   │   └── ...
│   ├── company/
│   │   ├── SearchBar.vue       # Autocomplete search (all SEC tickers)
│   │   ├── KpiCards.vue        # Revenue, net income, EPS, etc.
│   │   ├── IncomeTab.vue       # Revenue & net income charts
│   │   ├── MarginsTab.vue      # Gross/operating/net margin trends
│   │   ├── BalanceSheetTab.vue # Assets vs. liabilities, D/E ratio
│   │   ├── CashFlowTab.vue     # Operating/investing/financing breakdown
│   │   ├── EarningsTab.vue     # EPS trends
│   │   └── FilingsTab.vue      # Filing list with links to full text
│   └── chat/
│       ├── ChatPanel.vue       # Chat input + streaming message display
│       ├── ChatMessage.vue     # Single message (user/assistant) with citations
│       └── SourceCitation.vue  # Filing accession number badge
├── composables/
│   ├── useCompany.ts           # TanStack Query: fetch company profile
│   ├── useFinancials.ts        # TanStack Query: fetch metrics by tab
│   ├── useChat.ts              # SSE streaming chat composable
│   └── useSearch.ts            # Debounced search with TanStack Query
├── lib/
│   ├── api.ts                  # Typed API client (FastAPI base URL)
│   └── charts.ts               # ECharts option builders per chart type
├── stores/
│   └── chat.ts                 # Pinia: chat history within session
└── public/
    └── favicon.ico
```

### API Contract (Frontend ↔ FastAPI)

The Nuxt frontend consumes the FastAPI backend via REST + SSE:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/companies/search?q=` | GET | Autocomplete search by ticker/name |
| `/api/companies/{ticker}` | GET | Company profile (metadata + latest KPIs) |
| `/api/companies/{ticker}/financials?tab=income` | GET | Financial data for a specific tab |
| `/api/companies/{ticker}/filings` | GET | Filing list (form type, date, accession) |
| `/api/companies/{ticker}/filings/{accession}` | GET | Full filing text (markdown) |
| `/api/chat` | POST (SSE) | Chat message → streaming LLM response |

### Development & Build
```bash
# Development (hot reload)
cd frontend && npm run dev      # → localhost:3000 (proxies /api → FastAPI :8080)

# Production build
npm run build                    # → .output/ (Nitro server or static)

# Docker: Nuxt container serves frontend, proxies /api to FastAPI container
```

### Deployment (Docker)
```yaml
# docker-compose.yml (Phase 1 addition)
frontend:
  build: ./frontend
  ports:
    - "3000:3000"
  environment:
    - NUXT_PUBLIC_API_BASE=http://api:8080
  depends_on:
    - api

api:
  build: .
  ports:
    - "8080:8080"
  volumes:
    - ./data:/app/data
```

### Key Libraries (package.json)
```json
{
  "dependencies": {
    "nuxt": "^3.15",
    "vue": "^3.5",
    "@tanstack/vue-query": "^5",
    "@tanstack/vue-table": "^8",
    "pinia": "^2",
    "echarts": "^5",
    "vue-echarts": "^7",
    "vee-validate": "^4",
    "zod": "^3",
    "@vee-validate/zod": "^4"
  },
  "devDependencies": {
    "@nuxtjs/tailwindcss": "^6",
    "shadcn-nuxt": "latest",
    "typescript": "^5",
    "vitest": "^2",
    "@playwright/test": "^1",
    "eslint": "^9",
    "prettier": "^3"
  }
}
```

---

## OpenAI Agents SDK — Deep Dive

### What It Does
Lightweight Python framework for building multi-agent systems with tool use, handoffs between agents, guardrails, and built-in tracing.

### How We Use It
- **Outer orchestration layer** for all agent logic
- **Handoffs** for routing between specialized agents
- **Function tools** wrapping graph queries, report writing
- **Guardrails** for input validation and output quality control
- **Tracing** to Langfuse via OpenInference bridge

### Key Integration: Wrapping GraphRAG-SDK as a Tool
```python
from agents import Agent, function_tool, Runner

# GraphRAG-SDK's chat session wrapped as an agent tool
@function_tool
def ask_knowledge_graph(question: str) -> str:
    """Ask a natural language question against the investment knowledge graph.
    The question is automatically converted to a Cypher query and executed.
    
    Args:
        question: Natural language question about companies, relationships, etc.
    """
    chat = kg.chat_session()
    response = chat.send_message(question)
    return response.response

# Also expose direct Cypher for precise queries
@function_tool  
def query_graph(cypher_query: str) -> str:
    """Execute a Cypher query directly against the FalkorDB graph.
    Use this when you need precise control over the graph traversal.
    
    Args:
        cypher_query: Valid Cypher query string.
    """
    result = graph.query(cypher_query)
    return format_result(result)
```

### Local LLM Migration Path (Mac Studio Cluster)

The Mac Studio cluster runs **exo** for distributed inference and exposes an OpenAI-compatible API. All agents switch to the local endpoint by changing one line — no framework changes needed. See **08-hardware-requirements.md** for full hardware specs and model capacity analysis.

```python
from agents.extensions.models.litellm_model import LitellmModel

# Initial: OpenAI
model = LitellmModel(model="openai/gpt-4.1")

# Local: exo cluster on Mac Studio (OpenAI-compatible API)
model = LitellmModel(
    model="openai/meta-llama/Llama-3.1-70B",
    api_base="http://mac-studio-1.local:52415/v1"
)

# Local: 405B model across full cluster (RDMA distributed)
model = LitellmModel(
    model="openai/meta-llama/Llama-3.1-405B",
    api_base="http://mac-studio-1.local:52415/v1"
)

agent = Agent(
    name="Ripple Effect Analyzer",
    instructions="...",
    model=model,
    tools=[...],
)
```

---

## Langfuse — Deep Dive

### What It Does
Open-source LLM observability platform. Captures traces, costs, latencies across all LLM interactions.

### How We Use It
- **Trace all agent runs**: Every CLI query and autonomous cycle gets a trace
- **Cost tracking**: Monitor OpenAI API spend, identify expensive agents/tools
- **Latency monitoring**: Detect slow queries, optimize bottlenecks
- **Debug agent behavior**: Inspect handoff chains, tool calls, LLM reasoning
- **Prompt management**: Version control agent instructions (future)

### Integration with OpenAI Agents SDK
```python
# Install bridge
# pip install openinference-instrumentation-openai-agents langfuse

from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
from langfuse import get_client

# Initialize Langfuse (reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST from env)
langfuse = get_client()

# Instrument OpenAI Agents SDK — captures all agent activity
OpenAIAgentsInstrumentor().instrument()

# Now all Runner.run() calls are automatically traced to Langfuse
result = await Runner.run(triage_agent, input="What companies are affected by rising oil prices?")
# → Full trace visible in Langfuse UI: triage handoff → macro-micro analysis → synthesis
```

### Self-Hosted Deployment
```yaml
# docker-compose.yml
langfuse:
  image: langfuse/langfuse:latest
  ports:
    - "3001:3000"
  environment:
    - DATABASE_URL=postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
    - NEXTAUTH_SECRET=your-secret-here
    - SALT=your-salt-here
    - NEXTAUTH_URL=http://localhost:3001
  depends_on:
    - langfuse-db

langfuse-db:
  image: postgres:16
  environment:
    - POSTGRES_USER=langfuse
    - POSTGRES_PASSWORD=langfuse
    - POSTGRES_DB=langfuse
  volumes:
    - ./data/postgres:/var/lib/postgresql/data    # bind mount — deterministic path
```

---

## Python Dependencies Summary

```toml
# pyproject.toml dependencies
[project]
dependencies = [
    # Core
    "falkordb>=1.0.0",
    "graphrag-sdk>=0.8.1",
    "docling>=2.0.0",
    "openai-agents>=0.9.0",
    
    # Observability
    "langfuse>=2.0.0",
    "openinference-instrumentation-openai-agents",
    
    # LLM
    "openai>=1.0.0",
    "litellm>=1.0.0",
    
    # Data fetching
    "httpx>=0.27.0",
    "aiohttp>=3.9.0",
    
    # Document processing
    # python-xbrl removed — using edgartools (get_financials(), get_facts()) instead of parsing XBRL directly
    
    # Data source APIs
    "edgartools>=5.0.0",      # SEC EDGAR data (primary and sole SEC library)
    "congress-api>=0.1.0",    # Congress.gov API wrapper
    "fredapi>=0.5.0",         # FRED economic data
    "wbgapi>=1.0.0",          # World Bank data API
    
    # Scheduling
    "apscheduler>=3.10.0",
    
    # CLI
    "typer>=0.9.0",
    "rich>=13.0.0",            # Pretty terminal output
    
    # Data
    "pydantic>=2.0.0",
    "duckdb>=1.0.0",           # Financial time series analytical store
    
    # Utilities
    "python-dotenv>=1.0.0",
]
```

---

## Integration Architecture Diagram

```
┌────────────────────────────────────────────────┐
│  Nuxt 3 Frontend (localhost:3000)               │
│  Vue 3 + shadcn-vue + Tailwind + ECharts        │
│                                                 │
│  /company/[ticker]  /chat  /filings             │
│  TanStack Vue Query  ◄──── SSE (chat stream)    │
└───────────┬─────────────────────┬───────────────┘
            │ REST / SSE          │
            ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend (localhost:8080)            │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  OpenAI Agents SDK                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │   │
│  │  │ Agent 1  │→→│ Agent 2  │→→│ Agent N              │   │   │
│  │  │          │  │          │  │                      │   │   │
│  │  │ tools:   │  │ tools:   │  │ tools:               │   │   │
│  │  │ ┌──────┐ │  │ ┌──────┐ │  │ ┌──────┐ ┌────────┐ │   │   │
│  │  │ │graph │ │  │ │graph │ │  │ │graph │ │report  │ │   │   │
│  │  │ │query │ │  │ │query │ │  │ │query │ │writer  │ │   │   │
│  │  │ └──┬───┘ │  │ └──┬───┘ │  │ └──┬───┘ └───┬────┘ │   │   │
│  │  └────┼─────┘  └────┼─────┘  └────┼─────────┼──────┘   │   │
│  └───────┼──────────────┼─────────────┼─────────┼──────────┘   │
│          │              │             │         │               │
│          ▼              ▼             ▼         ▼               │
│  ┌───────────────────────────────┐  ┌──────────────────────┐   │
│  │  GraphRAG-SDK                 │  │  SQLite              │   │
│  │  ┌──────────┐ ┌────────────┐  │  │  Report Queue        │   │
│  │  │ KG Chat  │ │ Ontology   │  │  │  Ingestion State     │   │
│  │  │ Session  │ │ Manager    │  │  └──────────────────────┘   │
│  │  └────┬─────┘ └─────┬──────┘  │                             │
│  │       │              │         │  ┌──────────────────────┐   │
│  │       ▼              ▼         │  │  DuckDB              │   │
│  │  ┌─────────────────────────┐   │  │  Financial Time      │   │
│  │  │  FalkorDB Python Client │   │  │  Series + Macro      │   │
│  │  └────────────┬────────────┘   │  │  Growth Computations │   │
│  └───────────────┼────────────────┘  └──────────────────────┘   │
│                  │                                              │
└──────────────────┼──────────────────────────────────────────────┘
                   │ Redis Protocol (port 6379)
                   ▼
          ┌─────────────────┐         ┌──────────────────┐
          │    FalkorDB      │         │    Langfuse       │
          │    Container     │         │    Container      │
          │    (port 6379,   │         │    (port 3001)    │
          │     3000)        │         │    + Postgres     │
          └─────────────────┘         └──────────────────┘
```
