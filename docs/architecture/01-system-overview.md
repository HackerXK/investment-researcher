# System Overview — Investment Research Graph Platform

> **Strategic context**: See [00-strategic-rationale.md](00-strategic-rationale.md) for the competitive landscape analysis, edge assessment, risk evaluation, and data-quality-first development philosophy that inform this architecture.

## Vision

A **one-person institutional research desk** that maintains a living knowledge graph capturing the full picture of the economic world: 5,000+ US public companies, their interconnections, industry dynamics, macroeconomic indicators, country-level economic profiles, US Congressional investment disclosures, institutional holdings, government contracts, legislation, trade policy, and any other data that influences markets. Multi-agent AI systems continuously scan for investment opportunities by traversing graph relationships to uncover ripple effects — subtle, multi-hop connections that institutional analysts trace with teams of people and proprietary tools. The graph is designed to grow: any data source that contributes to a more accurate understanding of the global economic landscape is a candidate for inclusion.

**What this system is**: A research force multiplier that closes the gap between retail and institutional analysis. It replicates the *structure* of institutional research workflows — multi-hop relationship traversal, cross-domain signal integration, continuous monitoring — so a solo investor can see the same opportunities at roughly the same time, rather than weeks or months later.

**What this system is not**: Not a way to beat institutions. Not a trading system, not a speed advantage, not a data exclusivity play. All outputs require human judgment before action.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCES                                   │
│  SEC EDGAR │ Financial APIs │ News APIs │ Web Scraping │ Manual Uploads │
│  Congressional Disclosures │ 13F Inst. Holdings │ Gov Contracts/Policy  │
│  Country Economic Data (FRED, BLS, BEA, World Bank, IMF)               │
└──────┬─────────────┬────────────┬────────────┬───────────────┬──────────┘
       │             │            │            │               │
       ▼             ▼            ▼            ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       DATA INGESTION LAYER                              │
│                                                                         │
│  ┌──────────┐  ┌───────────────┐  ┌────────────────┐  ┌─────────────┐  │
│  │MarkItDown│  │ Custom Parsers│  │ Entity Resolver│  │ Scheduler   │  │
│  │(doc→md)  │  │ (XBRL, JSON)  │  │ (dedup/merge)  │  │ (APScheduler│  │
│  └────┬─────┘  └───────┬───────┘  └───────┬────────┘  │  + cron)    │  │
│       │                │                   │           └─────────────┘  │
│       ▼                ▼                   ▼                            │
│  ┌─────────────────────────────────────────────────────┐                │
│  │              GraphRAG-SDK                           │                │
│  │  Ontology Detection → Entity Extraction → KG Load   │                │
│  └──────────────────────┬──────────────────────────────┘                │
└─────────────────────────┼───────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     KNOWLEDGE GRAPH LAYER                                │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        FalkorDB                                   │  │
│  │                                                                   │  │
│  │  Phase 1 (SEC-only):                                              │  │
│  │    Nodes: Company, Person, Filing, Industry, Sector, Region       │  │
│  │    Rels:  SUPPLIES_TO, COMPETES_WITH, HAS_EXECUTIVE,              │  │
│  │           HAS_BOARD_MEMBER, OPERATES_IN, BELONGS_TO,              │  │
│  │           FILED, OWNS_STAKE_IN, PARTNER_WITH,                     │  │
│  │           JOINT_VENTURE_WITH, MERGED_WITH, HEADQUARTERED_IN       │  │
│  │                                                                   │  │
│  │  Future phases add:                                               │  │
│  │    Nodes: NewsArticle, MacroIndicator, Commodity,                 │  │
│  │           Legislator, CongressionalTrade, Legislation,            │  │
│  │           InstitutionalHolder, GovernmentContract,                │  │
│  │           ResearchReport                                         │  │
│  │    Rels:  MENTIONED_IN, DISCLOSED_TRADE, HOLDS_POSITION,         │  │
│  │           AWARDED_CONTRACT, AFFECTS_INDUSTRY, DEPENDS_ON, ...    │  │
│  │                                                                   │  │
│  │  Indexes: Full-text, Vector (embeddings), Range (dates/metrics)   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  See 02-graph-schema.md for current phase scope and future stubs.       │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       AGENT SYSTEM LAYER                                │
│                                                                         │
│  ┌─────────────────── OpenAI Agents SDK ──────────────────────────┐    │
│  │                                                                 │    │
│  │  ┌──────────┐  ┌──────────────┐  ┌─────────────────────────┐   │    │
│  │  │ Triage   │  │ Data Monitor │  │ Ripple Effect Analyzer  │   │    │
│  │  │ Agent    │──│ Agent        │──│                         │   │    │
│  │  └──────────┘  └──────────────┘  └─────────────────────────┘   │    │
│  │                                                                 │    │
│  │  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐   │    │
│  │  │ Fundamental  │  │ Macro-Micro   │  │ Research           │   │    │
│  │  │ Screener     │  │ Linker        │  │ Synthesizer        │   │    │
│  │  └──────────────┘  └───────────────┘  └────────────────────┘   │    │
│  │                                                                 │    │
│  │  Tools: query_graph(), semantic_search(), get_company_profile() │    │
│  │         get_related_companies(), write_report()                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                          │                                              │
│                          ▼                                              │
│  ┌──────────────────────────────────────────┐                          │
│  │           Report Queue (SQLite)           │                          │
│  │  Structured findings with confidence,     │                          │
│  │  supporting evidence, related entities    │                          │
│  └──────────────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                                     │
│                                                                         │
│  ┌────────────┐  ┌────────────────────┐  ┌──────────────────────────┐  │
│  │ CLI Chat   │  │ Financial Dashboard│  │ FalkorDB Browser UI      │  │
│  │ (ad-hoc    │  │ (ir web → FastAPI  │  │ (graph exploration)      │  │
│  │  queries)  │  │  + Chart.js)       │  │ localhost:3000            │  │
│  │            │  │ localhost:8000     │  │                          │  │
│  └────────────┘  └────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY (Cross-cutting)                         │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Langfuse                                  │  │
│  │  Traces all LLM calls, agent runs, tool invocations, costs        │  │
│  │  Integrated via OpenInference + OpenTelemetry bridge              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Graph database** | FalkorDB | Property graph with Cypher, vector indexing, high performance, Redis protocol. In-memory for fast traversals |
| **Orchestration layer** | OpenAI Agents SDK (outer) wrapping GraphRAG-SDK (inner tool) | OpenAI SDK gives fine-grained control over multi-agent handoffs, guardrails, tracing. GraphRAG-SDK's `chat_session()` exposed as a tool for NL→Cypher queries |
| **Document preprocessing** | MarkItDown → GraphRAG-SDK | MarkItDown handles formats GraphRAG-SDK doesn't natively support (PPTX, XLSX, audio). Unified markdown output for LLM consumption |
| **Observability** | Langfuse (self-hosted) | Open-source, captures full traces, cost tracking. Integrated with OpenAI Agents SDK via OpenInference bridge |
| **Report storage** | SQLite | Lightweight, no extra infrastructure, sufficient for local deployment. Agent writes structured JSON findings |
| **LLM strategy** | OpenAI API initially → Local LLM later | GPT-4.1 for KG construction quality. Migrate to Mac Studio cluster (2–4 × 512 GB) running exo/MLX with LiteLLM abstraction layer |
| **Ontology approach** | Hybrid: hand-crafted core + auto-extend | Structured financial data needs precise schema. Unstructured text benefits from auto-detection |
| **Deployment** | AMD Workstation + MacBook Pro | AMD Workstation (64GB DDR5, RTX 5090, 6TB NVMe: 2TB P41 + 4TB SN5000 RAID 0) runs all Docker containers and GPU inference. MacBook Pro M2 Pro is dev terminal only. NAS added at Phase 5 when total NVMe hits ~4.2TB (70%). Mac Studio cluster deferred to Phase 6+. See [06-deployment.md](06-deployment.md) |

## Data Flow Summary

### Ingestion Flow (Continuous)
```
Source → Fetch/Scrape → MarkItDown (if needed) → GraphRAG-SDK entity extraction
  → Entity Resolution (dedup) → FalkorDB (Cypher MERGE)

Sources include: SEC filings, financial APIs, news, web scraping,
Congressional disclosures, 13F institutional holdings, government
contract data, legislation/policy feeds, country economic data, and
manual uploads.
```

### Autonomous Agent Flow (24/7)
```
Scheduler triggers Data Monitor Agent
  → Detects new/changed data in graph
  → Hands off to specialist agent (Ripple Effect / Screener / Macro-Micro)
  → Specialist performs multi-hop graph analysis + LLM reasoning
  → Applies confidence decay across hops (0.9 per hop)
  → Hands off to Research Synthesizer
  → Synthesizer produces ranked opportunity report
  → Report includes: thesis, bear case, source citations, confidence score
  → Report written to SQLite queue with status = "needs_review"
  → Human reviews report before any action
```

### Interactive Query Flow (On-demand)
```
User types question in CLI
  → Triage Agent classifies intent
  → Handoff to appropriate specialist agent
  → Agent queries graph + reasons over results
  → Response returned to CLI
```

### Thesis-Driven Research Flow (On-demand)
```
User provides a directional thesis via CLI:
  "Bitcoin will crash because PQC breaks ECDSA. What are my best opportunities?"
  → Triage Agent identifies this as a thesis exploration (not a question)
  → Handoff to Thesis Explorer flow:
    1. Ripple Effect Analyzer: maps thesis to graph nodes, traverses outward
       — direct impacts, 2nd-order, 3rd-order, both long and short
    2. Fundamental Screener: filters for actionable opportunities
       — valuation, liquidity, institutional positioning
    3. Macro-Micro Linker: adds macro context and policy overlay
       — related legislation, country exposure, commodity impacts
    4. Research Synthesizer: produces ranked opportunity landscape
       — not a single trade idea, but a map of every way to capitalize
  → Output: structured report with ranked long/short candidates,
    confidence scores, bear cases, and source citations
  → Optionally written to report queue for paper trading
```

The thesis-driven flow is the system's most powerful mode. The user provides
*direction* (domain expertise), the system provides *breadth* (graph traversal
across 5,000+ entities). See [00-strategic-rationale.md](00-strategic-rationale.md)
§ Thesis-Driven Research.

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| **Graph size** | 5,000+ companies, ~800K+ nodes, ~3M+ relationships (at full build). Phase 1: ~50 companies (SEC-only). Future phases add ~600 legislators, ~1,000+ institutional holders |
| **News latency** | < 30 min from publication to graph |
| **Filing latency** | < 24 hours from EDGAR publication |
| **Agent response (CLI)** | < 30 seconds for typical queries |
| **Autonomous scan cycle** | Complete market scan every 4-6 hours |
| **RAM footprint** | 16-32 GB on workstation for FalkorDB graph + services. 512 GB per Mac Studio for LLM inference (Phase 6+) |
| **Human review** | All autonomous reports require human review before action. Reports are created with status `needs_review` |
| **Hypothesis framing** | All agent outputs framed as hypotheses, not conclusions. Bear case required in every report |
| **Source traceability** | Every factual claim in reports must cite a source (filing accession number, article URL, Cypher query, or data point) |
| **Thesis-driven research** | System accepts directional theses as input and maps full opportunity landscapes across the graph. Supports any domain — user expertise, external expert input, or speculative scenarios |
| **Confidence calibration** | Track prediction accuracy over time. Adjust confidence thresholds based on empirical results (Phase 7) |
| **Investment workflow** | Paper trading from Phase 4. Track hit rate, returns, and comparison against SPY baseline. Reports → investigation → paper-trade → decision pipeline (see [04-agent-system.md](04-agent-system.md) § Investment Decision Workflow) |
| **Uptime** | Best-effort (AMD workstation, not HA) |
