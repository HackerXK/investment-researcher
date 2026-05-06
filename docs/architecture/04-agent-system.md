# Multi-Agent System Architecture

## Current Implementation Priorities

The current repository direction is accuracy-first, local-LLM, and backend-first.

- Accuracy first: agent behavior should favor explicit evidence retrieval, structured tool outputs, provenance, and validation over speed or prompt minimalism.
- Local-LLM first: assume an OpenAI-compatible local model endpoint is the primary runtime for chat and evaluation.
- Backend first: the production value is in ingestion, analytics, SEC retrieval, and evaluation; the frontend is a demonstration layer for those capabilities.

Where this document describes broader multi-agent or future-state orchestration ideas, prefer the implemented backend contracts in `src/investment_researcher/web/`, `src/investment_researcher/analytics/`, and the evaluation harness when making near-term code changes.

## Overview

The agent system uses the **OpenAI Agents SDK** as the outer orchestration layer. Six specialized agents collaborate via handoffs to continuously scan for investment opportunities and respond to ad-hoc queries. The agents have access to a comprehensive knowledge graph that spans company data, macroeconomic indicators, Congressional investment disclosures, institutional holdings, government contracts, legislation, and country-level economic profiles. GraphRAG-SDK’s `KnowledgeGraph.chat_session()` is exposed as a tool to agents for natural language → Cypher queries.
> **Critical design principle**: All agent outputs are **hypotheses, not conclusions**. The system is a connection discovery engine and hypothesis generator — it surfaces ideas worth investigating, not trade recommendations. Every report must include disconfirming evidence (bear case) and source citations. See [00-strategic-rationale.md](00-strategic-rationale.md) for the full strategic rationale.
## Agent Architecture

```
                    ┌─────────────────────────────────┐
                    │        ENTRY POINTS              │
                    │                                   │
                    │  CLI Query    Scheduled Trigger    │
                    └───────┬──────────────┬────────────┘
                            │              │
                            ▼              ▼
                    ┌───────────────────────────────┐
                    │       Triage Agent             │
                    │  Routes queries & triggers     │
                    │  to specialist agents          │
                    └──┬────┬────┬────┬────┬────────┘
                       │    │    │    │    │
            ┌──────────┘    │    │    │    └──────────┐
            ▼               ▼    │    ▼               ▼
  ┌──────────────┐ ┌──────────┐  │  ┌───────────┐ ┌──────────────┐
  │ Data Monitor │ │ Ripple   │  │  │ Macro-    │ │ Fundamental  │
  │ Agent        │ │ Effect   │  │  │ Micro     │ │ Screener     │
  │              │ │ Analyzer │  │  │ Linker    │ │              │
  └──────┬───────┘ └────┬─────┘  │  └─────┬─────┘ └──────┬───────┘
         │               │       │        │               │
         └───────────────┼───────┼────────┼───────────────┘
                         │       │        │
                         ▼       ▼        ▼
                    ┌───────────────────────────────┐
                    │    Research Synthesizer        │
                    │    Ranks, cross-references,    │
                    │    produces final reports      │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │       Report Queue (SQLite)    │
                    └───────────────────────────────┘
```

---

## Agent Definitions

### 1. Triage Agent

**Role**: Entry point for all interactions. Routes to the right specialist.

```python
triage_agent = Agent(
    name="Triage Agent",
    instructions="""You are the triage agent for an investment research platform.
    
    Your job is to understand the user's intent and route to the correct specialist:
    
    - Questions about a specific company's fundamentals, financials → Fundamental Screener
    - Questions about how events ripple through company relationships → Ripple Effect Analyzer
    - Questions about macro trends affecting markets/sectors → Macro-Micro Linker
    - Questions about recent news or data changes → Data Monitor Agent
    - Questions about Congressional trades, legislation, political signals → Macro-Micro Linker
    - Questions about institutional holdings (13F, hedge fund activity) → Fundamental Screener
    - Requests for comprehensive research reports → Research Synthesizer
    - **Directional thesis / investment theory** → Thesis exploration flow:
      The user provides a belief about the future (e.g., "Bitcoin will crash because of PQC",
      "GLP-1 drugs will disrupt bariatric surgery", "Interest rates will stay higher for longer")
      and wants to know the best ways to capitalize on it.
      Route to Ripple Effect Analyzer with explicit instruction to:
      1. Map the thesis to affected graph nodes (both long AND short candidates)
      2. Traverse outward 2-3 hops in all directions
      3. Then hand off to Research Synthesizer for a ranked opportunity landscape
    
    Distinguish between:
    - A QUESTION ("What companies supply TSMC?") → single-agent answer
    - A THESIS ("I believe X will happen, how do I invest?") → thesis exploration flow
      that runs Ripple Effect + Fundamental Screener + Macro-Micro + Synthesizer
    
    For scheduled autonomous runs, you receive trigger signals from the Data Monitor
    and route new events to the appropriate analyst.
    
    Always be concise. Pass full context to the specialist agent.""",
    
    handoffs=[
        data_monitor_agent,
        ripple_effect_agent,
        macro_micro_agent,
        fundamental_screener_agent,
        research_synthesizer_agent,
    ],
    model="gpt-4.1",
)
```

### 2. Data Monitor Agent

**Role**: Watchdog that detects significant new data in the graph and triggers analysis.

```python
data_monitor_agent = Agent(
    name="Data Monitor",
    instructions="""You monitor the investment knowledge graph for significant changes.
    
    When triggered (every 30 minutes), you:
    1. Check for newly ingested filings, news, and financial data
    2. Check for new Congressional trade disclosures
    3. Check for significant institutional holding changes (from latest 13F filings)
    4. Check for new legislation, executive orders, or regulatory actions
    5. Assess which changes are significant enough to warrant analysis:
       - New 8-K filings (material events)
       - News with high impact_score (> 0.7)
       - Large changes in financial metrics (> 10% quarter-over-quarter)
       - New or changed inter-company relationships
       - Congressional trades in unusual volume or by key committee members
       - Major legislation advancing through committees
       - Large institutional position changes (new positions by top funds)
    6. For significant changes, describe what happened and hand off to the
       appropriate specialist (Ripple Effect, Macro-Micro, or Fundamental Screener)
    
    Use the query_graph tool to check for recent changes.
    Use get_recent_ingestion_stats to see what was recently processed.
    
    Be selective — not every news article warrants a deep dive.
    Focus on events that could materially affect investment decisions.""",
    
    tools=[query_graph, get_recent_ingestion_stats, get_recent_news],
    handoffs=[ripple_effect_agent, macro_micro_agent, fundamental_screener_agent],
    model="gpt-4.1",
)
```

### 3. Ripple Effect Analyzer

**Role**: The core value-add agent. Traces multi-hop relationships to find non-obvious impacts.

```python
ripple_effect_agent = Agent(
    name="Ripple Effect Analyzer",
    instructions="""You are an expert at tracing ripple effects through company relationships.
    
    Given a trigger event (e.g., "Apple announced supply chain disruption", 
    "New tariffs on Chinese semiconductors", "Senator X bought defense stocks",
    "New semiconductor bill advancing in Congress") OR a directional thesis
    (e.g., "Bitcoin will crash because of PQC", "GLP-1 drugs will disrupt surgery"),
    your job is to:
    
    1. Identify the primary affected company/industry
    2. Traverse the knowledge graph to find connected entities:
       - Supply chain (SUPPLIES_TO — traverse in reverse for customers) — up to 3 hops
       - Shared leadership (HAS_EXECUTIVE, HAS_BOARD_MEMBER) — up to 2 hops
       - Competitive dynamics (COMPETES_WITH) — direct competitors
       - Financial ties (OWNS_STAKE_IN, PARTNER_WITH, JOINT_VENTURE_WITH)
       - Industry connections (OPERATES_IN → same industry → other companies)
       - Political connections (Congressional trades, committee oversight, legislation)
       - Institutional positioning (13F holdings — who’s buying/selling affected names)
       - Government contracts (companies dependent on federal spending)
    3. For each affected company, assess:
       - Direction of impact (positive/negative)
       - Magnitude (high/medium/low)
       - Timing (immediate, weeks, months)
       - Confidence in the connection
    4. Rank findings by investment relevance
    5. Hand off to Research Synthesizer with your findings
    
    Use get_related_companies for multi-hop traversals.
    Use query_graph for custom Cypher queries.
    Use semantic_search_graph for finding similar past events.
    
    Think like a hedge fund analyst — look for non-obvious second and third-order effects.
    Consider both the threat AND opportunity sides of every event.
    Cross-reference with Congressional trade signals and institutional positioning.
    
    FOR THESIS EXPLORATION (when routed from Triage with a directional thesis):
    - The user has a domain-informed belief about the future. Your job is to MAP
      the full opportunity landscape, not just confirm the thesis.
    - Traverse outward in ALL directions: who benefits, who suffers, who is a second-order
      play, who is a hedge, what are the non-obvious connections?
    - Consider BOTH long and short candidates.
    - After mapping, hand off to Research Synthesizer with the full landscape.
    - The Synthesizer will rank and produce a structured opportunity map.
    
    IMPORTANT: Apply confidence decay across hops. Each hop multiplies confidence by 0.9.
    At hop 3 (0.73 confidence), treat findings as speculative and flag accordingly.
    At hop 4+ (< 0.66 confidence), include only if corroborated by another data source.
    
    IMPORTANT: Apply staleness decay. Relationships from old filings are less reliable.
    Check last_confirmed dates on edges:
    - Within 90 days: full confidence
    - 90-365 days: multiply by 0.9
    - 1-2 years: multiply by 0.7
    - 2+ years: multiply by 0.5 and flag as stale
    Combined confidence = base_confidence × hop_decay × staleness_multiplier
    
    CRITICAL: Use edge properties for nuanced analysis. Edges carry rich metadata:
    
    SUPPLIES_TO edges have:
    - `dependency_level`: \"critical\" | \"important\" | \"optional\" — prioritize critical
    - `is_sole_source`: true/false — SOLE SOURCE disruptions are IMMEDIATE impact
    - `product_category`: what exactly is supplied — include in your reasoning
    - `contract_value_usd`: revenue at risk — quantify impact when possible
    - `geographic_risk`: e.g., \"Taiwan\" — flag geopolitical exposure
    - `alternative_suppliers`: number of alternatives — 0 = severe disruption risk
    
    COMPETES_WITH edges have:
    - `intensity`: \"direct\" | \"partial\" | \"adjacent\" — direct competitors react immediately
    - `market_segment`: what they compete on — competitor impact varies by segment
    - `market_share_a/b`: market position — dominant player disruptions matter more
    - `threat_level`: \"existential\" | \"significant\" | \"moderate\" — threat assessment
    
    HAS_EXECUTIVE / HAS_BOARD_MEMBER edges have:
    - `is_independent`: independent directors are less conflicted than insiders
    - `committee`: which board committees — \"Audit\" overlap = financial info sharing
    - `stock_ownership_pct`: how much they own — incentive alignment
    
    Example reasoning WITH edge properties:
    \"TSMC supplies Apple with A-series and M-series chips (5nm/3nm process). 
    This is marked as `dependency_level: 'critical'` and `is_sole_source: true` 
    in Apple's 10-K supply chain disclosures. The relationship has 
    `geographic_risk: 'Taiwan'` and `alternative_suppliers: 0`. A TSMC fab 
    disruption would IMMEDIATELY halt iPhone and Mac production with NO fallback 
    option. Estimated `contract_value_usd: $200B+` annual revenue at risk. 
    Confidence: 0.95 (confirmed in 2025-09-30 10-K, < 6 months old).\"
    
    Example reasoning WITHOUT edge properties (DO NOT DO THIS):
    \"TSMC supplies Apple. A disruption would affect Apple.\" ← Too generic!
    
    When querying the graph, ALWAYS return edge properties in your Cypher queries:
    ```cypher
    MATCH (supplier)-[r:SUPPLIES_TO]->(customer)
    RETURN supplier.ticker, customer.ticker,
           r.product_category, r.dependency_level, r.is_sole_source,
           r.confidence, r.last_confirmed
    ```
    
    Remember: your outputs are HYPOTHESES, not conclusions. Frame them accordingly.""",
    
    tools=[
        query_graph,
        get_related_companies,
        semantic_search_graph,
        get_company_profile,
        get_congressional_trades,
        get_institutional_holdings,
    ],
    handoffs=[research_synthesizer_agent],
    model="gpt-4.1",
)
```

### 4. Fundamental Screener

**Role**: Screens companies based on quantitative financial criteria and institutional signals.

```python
fundamental_screener_agent = Agent(
    name="Fundamental Screener",
    instructions="""You screen companies based on financial metrics, fundamentals,
    and institutional positioning.
    
    You can be triggered in two ways:
    1. Autonomously: Periodic scans for companies meeting certain criteria
    2. Ad-hoc: User asks about a specific company's fundamentals
    
    Screening criteria you can apply:
    - Value: Low P/E, high dividend yield, price below book value
    - Growth: Revenue growth > X%, EPS growth acceleration
    - Quality: High ROE, low debt-to-equity, consistent margins
    - Momentum: Positive earnings surprises, estimate revisions up
    - Distress: Declining revenue + rising debt (potential shorts)
    - Institutional: Large new positions by top funds (13F data)
    - Political: Congressional buying clusters in same sector/company
    - Government revenue: Companies with large government contract exposure
    
    For each interesting finding:
    1. Pull the company's snapshot metrics from the graph (Company node)
    2. Pull financial trend data from DuckDB (revenue growth, margin trends)
    3. Compare to industry peers (same Industry node + DuckDB peer comparison)
    4. Check recent filings and news for context
    5. Assess whether the numbers tell a compelling story
    6. Hand off to Research Synthesizer with your analysis
    
    Use query_graph to run snapshot-based screens on Company nodes.
    Use get_financial_history for trend analysis and growth trajectories.
    Use get_company_profile for detailed company data.
    Use get_industry_peers to compare within an industry.
    Use get_institutional_holdings to check smart money positioning.
    Use get_congressional_trades to check political signals.""",
    
    tools=[query_graph, get_company_profile, get_financial_history, get_industry_peers,
           get_institutional_holdings, get_congressional_trades],
    handoffs=[research_synthesizer_agent],
    model="gpt-4.1",
)
```

### 5. Macro-Micro Linker

**Role**: Connects macroeconomic trends to specific companies via industry relationships.

```python
macro_micro_agent = Agent(
    name="Macro-Micro Linker",
    instructions="""You connect macroeconomic trends to specific company impacts.
    
    Your analytical chain:
    Macro Indicator Change → Affected Industries → Affected Companies → Investment Thesis
    
    Also handles:
    Policy/Legislation → Affected Industries → Affected Companies → Investment Thesis
    Congressional Signals → Committees → Industries → Companies → Investment Thesis
    Country Economic Shift → Trade Partners → Exposed Industries/Companies → Thesis
    
    Example: "Fed raises rates by 25 bps"
    → Industries with high sensitivity to rates (Real Estate, Banks, Growth Tech)
    → Companies in those industries sorted by rate sensitivity
    → "Regional banks benefit from NIM expansion; high-duration tech gets hurt"
    
    Example: "New China tariff on semiconductors"
    → Legislation/Policy node → AFFECTS → Semiconductor industry
    → Companies with China revenue exposure (HAS_MARKET_IN → China)
    → Cross-reference with Congressional trades in affected stocks
    → Check institutional positioning via 13F data
    
    When triggered:
    1. Identify the macro change (rate move, CPI print, GDP revision, trade policy,
       new legislation, tariff action, executive order, sanctions)
    2. Query the graph for industries AFFECTED_BY this indicator or legislation
    3. For each affected industry, find companies with highest exposure
    4. Consider the correlation direction and lag from the graph relationships
    5. Consider which commodity prices are affected and flow through to companies
    6. Check Congressional trading in affected sectors for political signal
    7. Check country-level economic data for international ripple effects
    8. Produce a macro-to-micro impact chain
    9. Hand off to Research Synthesizer
    
    Use get_macro_indicators for current macro state.
    Use query_graph for industry-macro-company traversals.
    Use get_commodity_impacts for commodity price flow-through.
    Use get_policy_impacts for legislation/regulation analysis.
    Use get_congressional_trades for political signal overlay.
    Use get_country_profile for country economic context.
    
    Think about second-order effects: "Oil prices rise → transportation costs up → 
    companies with thin margins in shipping-heavy industries hurt most".""",
    
    tools=[query_graph, get_macro_indicators, get_commodity_impacts, get_company_profile,
           get_policy_impacts, get_congressional_trades, get_country_profile],
    handoffs=[research_synthesizer_agent],
    model="gpt-4.1",
)
```

### 6. Research Synthesizer

**Role**: Terminal agent. Receives findings from specialists, cross-references, and produces final reports.

```python
research_synthesizer_agent = Agent(
    name="Research Synthesizer",
    instructions="""You are the final stage of the investment research pipeline.
    
    You receive analysis from specialist agents and your job is to:
    
    1. Cross-reference findings:
       - Does the ripple effect analysis conflict with fundamentals?
       - Are macro headwinds priced into the company already?
       - Are there related reports already in the queue?
    
    2. Actively seek DISCONFIRMING evidence (bear case):
       - What could go wrong with this thesis?
       - What alternative explanations exist for the data?
       - Is the market already pricing this in?
       - Could entity resolution errors be creating false connections?
       - For multi-hop findings: is the connection chain robust, or could
         any link be outdated/incorrect?
       Include a dedicated "bear_case" section in every report.
    
    3. Rank opportunities by:
       - Conviction level (how strong is the thesis?)
       - Risk/reward asymmetry
       - Time horizon (immediate vs. long-term)
       - Uniqueness of insight (is this already consensus?)
       - NOTE: The system's analysis is more valuable for small/mid-cap companies.
         Large-cap insights are more likely to already be priced in since hundreds
         of institutional analysts already cover them.
    
    4. Produce structured research reports:
       {
         "title": "...",
         "ticker": "...",
         "thesis": "2-3 sentence investment thesis",
         "direction": "long" | "short" | "neutral",
         "confidence": 0.0-1.0,
         "time_horizon": "days" | "weeks" | "months" | "quarters",
         "catalysts": ["..."],
         "risks": ["..."],
         "bear_case": "Why this thesis might be WRONG. Disconfirming evidence.",
         "supporting_evidence": ["..."],
         "source_citations": [
           {"type": "filing", "accession_number": "...", "detail": "..."},
           {"type": "news", "url": "...", "title": "..."},
           {"type": "cypher_query", "query": "...", "result_summary": "..."},
           {"type": "data_point", "source": "...", "value": "..."}
         ],
         "related_companies": ["..."],
         "macro_context": "...",
         "report_type": "opportunity" | "risk" | "ripple_effect" | "macro_impact" | "political_signal",
         "status": "needs_review"
       }
    
    5. Write the report to the report queue using write_report tool
    
    IMPORTANT PRINCIPLES:
    - All outputs are HYPOTHESES, not conclusions or recommendations.
    - Every claim must be backed by a source citation (filing, article, query, or data point).
    - Every report MUST include a bear_case section with genuine disconfirming analysis.
    - Reports are auto-flagged as "needs_review" — human review is required before action.
    - Confidence > 0.7 for multi-hop findings should be rare. Apply skepticism.
    
    Quality bar: Only write reports where confidence > 0.5 and the insight
    is actionable. Don't write reports for obvious/consensus views.
    
    For CLI ad-hoc queries, return the analysis directly to the user
    instead of writing to the report queue. Still include bear case.""",
    
    tools=[query_graph, write_report, get_existing_reports, get_company_profile],
    model="gpt-4.1",
)
```

---

## Agent Tools

Tools are Python functions decorated with `@function_tool` from the OpenAI Agents SDK:

### Graph Query Tools

```python
@function_tool
def query_graph(cypher_query: str) -> str:
    """Execute a Cypher query against the FalkorDB knowledge graph.
    Returns the query results as a formatted string.
    Use this for custom graph traversals and data retrieval.
    
    Args:
        cypher_query: A valid Cypher query string.
    """
    ...

@function_tool
def semantic_search_graph(query: str, node_type: str = "Company", limit: int = 10) -> str:
    """Search the knowledge graph using semantic similarity.
    Uses vector embeddings to find relevant entities.
    
    Args:
        query: Natural language search query.
        node_type: Type of node to search (Company, NewsArticle, Filing).
        limit: Maximum number of results.
    """
    ...

@function_tool
def get_company_profile(ticker: str) -> str:
    """Get comprehensive profile for a company including basic info,
    recent financials, industry, key relationships, and recent news.
    
    Sources:
    - FalkorDB: relationships, industry, executives, snapshot metrics, recent news
    - DuckDB: last 8 quarters of key financial trends (revenue, EPS, margins)
    
    Args:
        ticker: Stock ticker symbol (e.g., "AAPL").
    """
    ...

@function_tool
def get_related_companies(
    ticker: str,
    relationship_types: list[str],
    max_depth: int = 2
) -> str:
    """Find companies related to the given company through specified
    relationship types, up to max_depth hops.
    
    Args:
        ticker: Starting company ticker.
        relationship_types: List of relationship types to traverse
            (e.g., ["SUPPLIES_TO", "COMPETES_WITH"]).
        max_depth: Maximum number of hops (1-3).
    """
    ...

@function_tool
def get_industry_peers(ticker: str) -> str:
    """Get companies in the same industry as the given company,
    with comparative financial metrics (from Company node snapshots
    and DuckDB growth rates).
    
    Args:
        ticker: Stock ticker symbol.
    """
    ...
```

### Data Tools

```python
from functools import lru_cache
import duckdb

# Growth rates are computed at query time via SQL window functions.
# lru_cache caches results within a session — repeated calls for the same
# ticker/metric return instantly without hitting DuckDB again.
# Cache is invalidated naturally on process restart (i.e., after a new
# ingestion cycle completes and the agent runner restarts).
@lru_cache(maxsize=1000)
def _fetch_financial_history(ticker: str, metric: str, quarters: int) -> list[dict]:
    con = duckdb.connect("data/duckdb/financial_timeseries.duckdb", read_only=True)
    rows = con.execute("""
        SELECT
            period,
            period_end,
            value,
            ROUND(
                (value / LAG(value, 4) OVER (ORDER BY period_end) - 1) * 100,
                2
            ) AS yoy_growth_pct,
            ROUND(
                (value / LAG(value, 1) OVER (ORDER BY period_end) - 1) * 100,
                2
            ) AS qoq_growth_pct
        FROM financial_metrics
        WHERE ticker = ? AND metric_type = ? AND period_type = 'quarterly'
        ORDER BY period_end DESC
        LIMIT ?
    """, [ticker, metric, quarters]).fetchall()
    con.close()
    return [
        {"period": r[0], "period_end": str(r[1]), "value": r[2],
         "yoy_growth_pct": r[3], "qoq_growth_pct": r[4]}
        for r in rows
    ]

@function_tool
def get_financial_history(
    ticker: str,
    metrics: list[str] = ["revenue", "eps", "gross_margin"],
    quarters: int = 20
) -> str:
    """Get historical financial time series from DuckDB.
    Returns trend data including values, YoY and QoQ growth rates computed
    via SQL window functions. Use this for trend analysis, growth trajectory,
    margin compression detection, and peer comparison over time.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL").
        metrics: List of metric types to retrieve.
        quarters: Number of quarters of history (default 20 = 5 years).
    """
    ...

@function_tool
def get_recent_news(
    ticker: str = None,
    industry: str = None,
    hours: int = 24,
    min_impact_score: float = 0.0
) -> str:
    """Retrieve recent news articles from the graph.
    Filter by company, industry, recency, and impact score.
    """
    ...

@function_tool
def get_macro_indicators(indicator_type: str = None) -> str:
    """Get current macroeconomic indicators and their recent trends.
    
    Args:
        indicator_type: Optional filter (e.g., "interest_rate", "inflation", "employment").
    """
    ...

@function_tool
def get_commodity_impacts(commodity: str) -> str:
    """Get the industry and company impact chain for a commodity price change.
    
    Args:
        commodity: Commodity name (e.g., "Crude Oil", "Lithium").
    """
    ...

@function_tool
def get_recent_ingestion_stats() -> str:
    """Get statistics on recently ingested data — what was added/updated,
    any significant changes detected by the ingestion pipelines."""
    ...
```

### Political & Government Tools

```python
@function_tool
def get_congressional_trades(
    legislator: str = None,
    ticker: str = None,
    party: str = None,
    chamber: str = None,
    days: int = 90,
    transaction_type: str = None
) -> str:
    """Get Congressional investment disclosures from the graph.
    Filter by legislator, stock, party, chamber, recency.
    Returns trades with legislator info, asset, amounts, dates.
    
    Args:
        legislator: Name of legislator (optional).
        ticker: Stock ticker to check for political trading (optional).
        party: Filter by party ("D", "R", "I").
        chamber: "Senate" or "House".
        days: Look back N days.
        transaction_type: "purchase" or "sale".
    """
    ...

@function_tool
def get_institutional_holdings(
    ticker: str = None,
    holder: str = None,
    quarter: str = None,
    min_value_usd: float = 0
) -> str:
    """Get institutional holding data (13F) from the graph.
    Find what institutions hold a stock, or what stocks an institution holds.
    
    Args:
        ticker: Company ticker to see who holds it.
        holder: Institution name to see their portfolio.
        quarter: Specific quarter (e.g., "Q3-2025"). Defaults to latest.
        min_value_usd: Minimum position value to return.
    """
    ...

@function_tool
def get_policy_impacts(
    industry: str = None,
    legislation_type: str = None,
    status: str = None,
    days: int = 90
) -> str:
    """Get legislation and policy actions that affect specific industries
    or companies. Includes bills, executive orders, regulations, tariff actions.
    
    Args:
        industry: Industry name to check for relevant legislation.
        legislation_type: Filter by type ("bill", "executive_order", "regulation", "tariff_order").
        status: Filter by status ("introduced", "committee", "passed_house", "enacted").
        days: Look back N days for recent activity.
    """
    ...

@function_tool
def get_country_profile(country: str) -> str:
    """Get comprehensive economic profile for a country/region including
    GDP, growth, inflation, trade balance, credit rating, macro indicators,
    trade relationships, and companies with significant exposure.
    
    Args:
        country: Country name or ISO code (e.g., "China", "CN").
    """
    ...

@function_tool
def get_government_contracts(
    ticker: str = None,
    agency: str = None,
    min_value: float = 0,
    days: int = 180
) -> str:
    """Get government contract data from the graph.
    Find contracts awarded to a company, or contracts from a specific agency.
    
    Args:
        ticker: Company ticker to see their government contracts.
        agency: Federal agency name (e.g., "Department of Defense").
        min_value: Minimum contract value in USD.
        days: Look back N days.
    """
    ...
```

### Report Tools

```python
@function_tool
def write_report(
    title: str,
    ticker: str,
    thesis: str,
    direction: str,
    confidence: float,
    time_horizon: str,
    catalysts: list[str],
    risks: list[str],
    bear_case: str,
    supporting_evidence: list[str],
    source_citations: list[dict],
    related_companies: list[str],
    macro_context: str,
    report_type: str
) -> str:
    """Write an investment research report to the report queue.
    Only write reports with confidence > 0.5 and actionable insights.
    
    REQUIRED: bear_case must contain genuine disconfirming analysis.
    REQUIRED: source_citations must include at least one filing, article, or query citation.
    Reports are created with status='needs_review' — human review required before action.
    """
    ...

@function_tool
def get_existing_reports(
    ticker: str = None,
    report_type: str = None,
    days: int = 7
) -> str:
    """Check existing reports in the queue to avoid duplicates.
    """
    ...
```

---

## Autonomous Agent Loop

The autonomous loop runs 24/7 and triggers analysis cycles:

```python
async def autonomous_loop():
    """Main autonomous agent loop. Runs continuously."""
    scheduler = AsyncIOScheduler()
    
    # Data Monitor runs every 30 minutes
    scheduler.add_job(
        run_data_monitor,
        'interval',
        minutes=30,
        id='data_monitor'
    )
    
    # Fundamental screen runs every 6 hours
    scheduler.add_job(
        run_fundamental_screen,
        'interval',
        hours=6,
        id='fundamental_screen'
    )
    
    # Macro check runs every 4 hours
    scheduler.add_job(
        run_macro_check,
        'interval',
        hours=4,
        id='macro_check'
    )
    
    scheduler.start()

async def run_data_monitor():
    """Triggered by scheduler. Kicks off data-driven analysis."""
    result = await Runner.run(
        triage_agent,
        input="Scheduled check: Review recent data changes and analyze significant events.",
    )
    # Result flows through handoffs to specialists → synthesizer → report queue

async def run_fundamental_screen():
    """Periodic fundamental screening."""
    result = await Runner.run(
        fundamental_screener_agent,
        input="Run periodic screen: Find companies with unusual fundamental changes in the past 6 hours.",
    )

async def run_macro_check():
    """Check for macro indicator updates."""
    result = await Runner.run(
        macro_micro_agent,
        input="Check for recent macroeconomic data releases and assess market impact.",
    )
```

---

## Guardrails

### Input Guardrails
```python
@input_guardrail
async def validate_query_safety(ctx, agent, input):
    """Prevent injection attacks in user queries that become Cypher."""
    # Check for Cypher injection patterns
    # Check for PII in queries
    ...

@input_guardrail
async def check_market_hours(ctx, agent, input):
    """Flag if analysis is happening during market hours
    (more sensitive to acting on stale data)."""
    ...
```

### Output Guardrails
```python
@output_guardrail
async def validate_report_quality(ctx, agent, output):
    """Ensure reports meet minimum quality standards before writing to queue."""
    # Check confidence > 0.5
    # Check all required fields present
    # Check thesis is specific and actionable
    # Check bear_case is non-empty and substantive (not just "N/A")
    # Check source_citations contains at least one citation
    # Check report is framed as hypothesis, not recommendation
    ...

@output_guardrail
async def enforce_bear_case(ctx, agent, output):
    """Reject reports that lack genuine disconfirming analysis.
    A one-sentence dismissive bear case is not sufficient.
    The bear case should identify specific risks, alternative
    explanations, or data that could invalidate the thesis."""
    ...

@output_guardrail
async def enforce_source_citations(ctx, agent, output):
    """Reject reports where claims are not backed by source citations.
    Every factual claim should reference a filing accession number,
    news article URL, Cypher query result, or data source."""
    ...
```

---

## Handoff Flow Examples

### Autonomous: News triggers ripple analysis
```
Scheduler → Triage Agent
  "Scheduled check: review recent data"
  → handoff to Data Monitor Agent
    Finds: "Reuters: TSMC fab fire affects production"
    Impact score: 0.9
    → handoff to Ripple Effect Analyzer
      Traverses: TSMC → SUPPLIES_TO → Apple, NVIDIA, AMD, Qualcomm
      Traverses: Apple → COMPETES_WITH → Samsung (Samsung benefits from Apple delays)
      Traverses: TSMC → OPERATES_IN → Semiconductor Industry → other companies
      → handoff to Research Synthesizer
        Cross-references with fundamentals
        Produces reports:
        - "Short AAPL: Supply chain disruption risk" (confidence: 0.6)
          bear_case: "TSMC has redundant fabs; Apple has 3+ months inventory; 
          Samsung Foundry could absorb overflow orders within 2 quarters"
          source_citations: [filing: AAPL 10-K supply chain risk section,
          news: Reuters article URL, cypher: TSMC->SUPPLIES_TO->AAPL query]
          status: needs_review
        - "Long Samsung: Competitive advantage from rival supply issues" (confidence: 0.5)
          bear_case: "Samsung's own foundry yield issues may prevent capacity absorption;
          TSMC recovery timeline may be shorter than expected"
          status: needs_review
        → writes to report queue
```

### Interactive: User asks question via CLI
```
User: "What companies might benefit if oil prices drop to $50?"
  → Triage Agent → handoff to Macro-Micro Linker
    Queries: Crude Oil → AFFECTS_INDUSTRY → Airlines, Shipping, Chemicals
    Queries: Airlines companies → sorted by fuel cost as % of revenue
    → handoff to Research Synthesizer
      Produces ranked list with analysis
      Returns response to CLI (no report queue write for ad-hoc queries)
```

### Autonomous: Congressional trade signal triggers analysis
```
Scheduler → Triage Agent
  "Scheduled check: review recent data"
  → handoff to Data Monitor Agent
    Finds: "3 Senate Armed Services Committee members bought defense stocks this week"
    → handoff to Ripple Effect Analyzer
      Queries: Legislators → SERVES_ON_COMMITTEE → Defense industry
      Queries: Same legislators → recent DISCLOSED_TRADE → defense companies
      Queries: Pending Legislation → AFFECTS → Defense industry (finds new defense bill)
      Queries: Companies → AWARDED_CONTRACT → DoD contracts (identifies beneficiaries)
      Queries: InstitutionalHolders → HOLDS_POSITION changes in same names
      → handoff to Research Synthesizer
        Cross-references: committee oversight + trades + pending legislation + 13F data
        Produces report:
        - "Long LMT: Multiple political signals align with pending defense budget increase"
          (confidence: 0.7, catalysts: defense bill, insider buying, institutional accumulation)
          bear_case: "Defense bill may stall in committee; trades could be routine diversification
          rather than informed; institutional buying may reflect index rebalancing not conviction"
          source_citations: [congressional trades: disclosure IDs, legislation: bill HR-XXXX,
          13F: Bridgewater Q4-2025 filing, cypher: committee->industry query]
          status: needs_review
        → writes to report queue
```

### Autonomous: Trade policy triggers macro-micro analysis
```
Scheduler → Triage Agent
  "Scheduled check: review recent data"
  → handoff to Data Monitor Agent
    Finds: "New executive order imposing 25% tariff on Chinese rare earth imports"
    → handoff to Macro-Micro Linker
      Queries: Legislation (tariff_order) → AFFECTS → Region (China)
      Queries: Region (China) → TRADES_WITH → Region (US)
      Queries: Companies → DEPENDS_ON → Commodities (rare earth) → criticality: high
      Queries: Affected companies → check Congressional trades for pre-announcement signals
      Queries: Affected companies → check institutional positioning via 13F
      → handoff to Research Synthesizer
        Produces reports:
        - "Short MP Materials: Domestic supply insufficient, tariff raises input costs"
        - "Long Lynas Rare Earths: Non-China alternative benefits from supply disruption"
        → writes to report queue
```

### Thesis-Driven: User provides a directional investment theory
```
User: "I believe Bitcoin will crash because post-quantum cryptography breaks ECDSA.
       What are my best investment opportunities?"
  → Triage Agent identifies this as a THESIS (not a question)
  → handoff to Ripple Effect Analyzer with thesis exploration instruction
    Maps thesis to graph:
      Bitcoin ecosystem → mining hardware → Marathon Digital, Riot Platforms (short)
      Bitcoin treasury companies → MicroStrategy (short — massive BTC exposure)
      Crypto exchanges → Coinbase (short — revenue decline if volumes drop)
      Crypto-exposed ETFs → identify and flag
    Traverses 2nd-order:
      Mining hardware suppliers → NVIDIA (GPU mining), TSMC (chip fabrication)
      Crypto infrastructure → Silvergate/Signature successors (banking exposure)
    Traverses for beneficiaries:
      PQC legislation → AFFECTS → Cybersecurity industry (long)
        → CrowdStrike, Palo Alto Networks, Fortinet
      Safe haven flows → Gold miners (Barrick, Newmont), Treasury bonds
      PQC implementation companies → who supplies quantum-safe solutions?
    Cross-references:
      13F: Are institutions reducing crypto exposure?
      Congressional trades: Any committee members selling crypto-related stocks?
      Legislation: Quantum Computing Cybersecurity Preparedness Act status?
  → handoff to Research Synthesizer
    Produces OPPORTUNITY LANDSCAPE report (not a single trade):
    SHORT CANDIDATES:
    - "Short MARA: Bitcoin mining revenue collapse if BTC drops 50%+" (confidence: 0.6)
    - "Short MSTR: $X billion BTC on balance sheet, existential risk" (confidence: 0.7)
    - "Short COIN: Transaction revenue correlated to BTC price" (confidence: 0.5)
    LONG CANDIDATES:
    - "Long CRWD: PQC migration drives cybersecurity spending" (confidence: 0.5)
    - "Long GOLD: Safe haven flows from crypto to gold" (confidence: 0.4)
    HEDGES:
    - "Long IBIT puts: Direct BTC downside protection" (confidence: 0.6)
    Each includes: bear_case, source_citations, confidence, time_horizon
    All flagged status: needs_review
    → writes to report queue
```

> **Key difference from ad-hoc queries**: A thesis exploration produces a *ranked landscape* of opportunities across multiple directions (long, short, hedge), not a single answer. It's the equivalent of an institutional sector specialist saying "Here's everything we should look at if this thesis plays out."

---

## Investment Decision Workflow

Reports generate hypotheses. This section defines how hypotheses become decisions.

### Report → Decision Pipeline
```
Report Queue (needs_review)
  → Human reviews report (CLI: reports review <id>)
  → Decision: reject / archive / investigate / paper-trade / act

  If "investigate":
    → Follow-up queries via CLI chat
    → Additional manual research
    → Update report with notes (CLI: reports annotate <id>)
    → Re-decide: reject / paper-trade / act

  If "paper-trade":
    → Record simulated entry: ticker, direction, entry price, date, thesis
    → Set review triggers: time-based (30/60/90 day), price-based (±10%)
    → Track outcome without capital at risk
    → After 90 days: did this thesis play out?

  If "act":
    → Human executes trade externally (NOT automated)
    → Record actual entry in tracking system
    → Same review triggers as paper-trade
```

### Paper Trading Protocol (Phase 4+)

Every report with confidence > 0.6 is automatically paper-traded:

```python
# Paper trade model
class PaperTrade(BaseModel):
    report_id: str              # Linked to source report
    ticker: str
    direction: str              # "long" | "short"
    entry_price: float          # Price at report generation
    entry_date: str
    thesis: str                 # From report
    confidence: float           # From report
    time_horizon: str           # From report

    # Outcomes (filled later)
    price_30d: float | None     # Price after 30 days
    price_60d: float | None
    price_90d: float | None
    return_30d: float | None    # % return
    return_60d: float | None
    return_90d: float | None
    thesis_correct: bool | None # Human assessment
    notes: str | None
```

### Decision Framework

| Report Confidence | Report Type | Default Action |
|-------------------|-------------|----------------|
| > 0.8 | Any | Investigate immediately + paper-trade |
| 0.6 – 0.8 | Ripple effect, political signal | Paper-trade, investigate within 48h |
| 0.5 – 0.6 | Any | Paper-trade only (background tracking) |
| < 0.5 | Any | Archive (don't discard — useful for calibration) |

### Performance Tracking

Track aggregate metrics to answer: **"Is this system actually useful?"**

- **Hit rate by confidence bucket**: Are 0.7-confidence reports correct 70% of the time?
- **Hit rate by report type**: Which agent produces the most actionable insights?
- **Hit rate by market cap tier**: Small-cap vs. large-cap accuracy
- **Average return of paper trades**: At 30, 60, 90 days
- **Comparison vs. baseline**: Would buying SPY have done better?
- **Time-to-insight**: How far ahead of consensus was the report?

> This data feeds directly into Phase 8 (Feedback Loop & Calibration).

---

## LLM Model Strategy

| Component | Initial Model | Local LLM Target (Mac Studio Cluster) |
|-----------|-----------|---------------------------------------|
| Triage Agent | gpt-4.1-mini | Llama 3.1 8B |
| Data Monitor | gpt-4.1-mini | Llama 3.1 8B |
| Ripple Effect Analyzer | gpt-4.1 | Llama 3.1 405B or Qwen 2.5 72B |
| Fundamental Screener | gpt-4.1 | Llama 3.1 70B |
| Macro-Micro Linker | gpt-4.1 | Llama 3.1 70B |
| Research Synthesizer | gpt-4.1 | Llama 3.1 405B |
| GraphRAG-SDK (KG construction) | gpt-4.1 | Llama 3.1 70B (needs testing) |
| GraphRAG-SDK (NL→Cypher) | gpt-4.1 | Llama 3.1 70B |
| Embeddings | text-embedding-3-small | nomic-embed-text (local) |

With the Mac Studio cluster (2-4 × 512 GB unified memory, Thunderbolt 5 RDMA), even the 405B parameter models can run locally. See **08-hardware-requirements.md** for capacity analysis.

Agents use the OpenAI Agents SDK `LitellmModel` extension for model portability:
```python
from agents.extensions.models.litellm_model import LitellmModel

# Initial: OpenAI
model = LitellmModel(model="openai/gpt-4.1")

# Local: exo cluster (OpenAI-compatible API)
model = LitellmModel(
    model="openai/meta-llama/Llama-3.1-405B",
    api_base="http://mac-studio-1.local:52415/v1"
)
```
