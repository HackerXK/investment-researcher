# Technology Stack — Integration Details

> Cross-references: [00-strategic-rationale.md](00-strategic-rationale.md) for why these technologies were chosen, [08-hardware-requirements.md](08-hardware-requirements.md) for hardware specs.

## Stack Overview

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Graph Database | FalkorDB | latest | Property graph storage, Cypher queries, vector indexing |
| Knowledge Graph SDK | GraphRAG-SDK | 0.8.1+ | Ontology management, document→KG extraction, NL→Cypher |
| Document Processing | MarkItDown | 0.1.4+ | Convert PDF/DOCX/PPTX/XLSX/HTML → Markdown |
| Agent Orchestration | OpenAI Agents SDK | 0.9+ | Multi-agent system, handoffs, guardrails, tools |
| Observability | Langfuse | latest | LLM tracing, cost tracking, prompt management |
| LLM Provider (Initial) | OpenAI API | — | GPT-4.1, GPT-4.1-mini, text-embedding-3-small |
| LLM Provider (Future) | exo / MLX on Mac Studio cluster | — | Distributed local model serving via Thunderbolt 5 RDMA (Phase 6+, gated on RTX 5090 proving insufficient) |
| Task Scheduling | APScheduler | 3.x | Cron-like scheduling for ingestion + agent loops |
| Report Storage | SQLite | 3.x | Report queue, ingestion state tracking |
| Time Series Store | DuckDB | 1.x+ | Financial metrics time series, macro time series, growth computations. See [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store |
| CLI Framework | Click or Typer | — | Interactive command-line interface |
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
- **5,000 companies + legislators + institutions + all relationships + metrics**: ~800K nodes, ~3M+ relationships
- **Estimated RAM**: 3-6 GB for graph data + 2-4 GB for vector indexes
- **Recommendation**: Set `--maxmemory 16gb`, monitor with FalkorDB UI
- **Growth note**: Congressional trades + 13F holdings + government contracts add significant node/relationship volume over time

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

## MarkItDown — Deep Dive

### What It Does
Microsoft's lightweight converter for turning documents into Markdown optimized for LLM consumption.

### How We Use It
- **Preprocessing step** before GraphRAG-SDK ingestion
- Converts SEC filings (HTML) → clean Markdown
- Converts uploaded documents (PDF, DOCX, PPTX, XLSX) → Markdown
- Converts scraped web pages → clean Markdown (strips boilerplate)

### Integration Pattern
```python
from markitdown import MarkItDown

md = MarkItDown()

# Convert filing HTML
result = md.convert("filings/aapl_10k_2025.html")
markdown_text = result.text_content

# Feed to GraphRAG-SDK
from graphrag_sdk.source import Source
source = Source(content=markdown_text, metadata={"type": "10-K", "ticker": "AAPL"})
kg.process_sources([source])
```

### When MarkItDown Is Needed vs. Not

| Format | MarkItDown Needed? | Why |
|--------|-------------------|-----|
| PDF | Optional | GraphRAG-SDK handles PDF natively, but MarkItDown may offer better extraction |
| HTML | Yes | Clean up web boilerplate before entity extraction |
| DOCX/PPTX/XLSX | Yes | GraphRAG-SDK doesn't handle these natively |
| JSON/CSV | No | Custom parsers for structured data |
| Plain text | No | Pass directly to GraphRAG-SDK |

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
    "markitdown[all]>=0.1.4",
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
    "python-xbrl>=1.0.0",     # SEC XBRL parsing
    
    # Data source APIs
    "congress-api>=0.1.0",    # Congress.gov API wrapper
    "fredapi>=0.5.0",         # FRED economic data
    "wbgapi>=1.0.0",          # World Bank data API
    "sec-edgar-downloader>=5.0.0",  # SEC EDGAR filing downloads
    
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
┌─────────────────────────────────────────────────────────────────┐
│                      Python Application                         │
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
