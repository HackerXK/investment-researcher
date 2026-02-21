# Knowledge Graph Schema — Ontology Design

## Design Philosophy

The schema uses a **hybrid approach**: a hand-crafted core ontology for structured financial data (where precision matters) combined with auto-extension via GraphRAG-SDK for unstructured text (where discovery matters). All relationships carry temporal properties for historical tracking.

The graph is intentionally broad — it captures not only company-level data but also country economic profiles, US Congressional investment disclosures, institutional holdings, government contracts, legislation, and any other data that contributes to an accurate picture of the global economic landscape. This breadth enables the agent system to find cross-domain ripple effects (e.g., a legislator’s committee assignment + their recent stock trades + upcoming regulation → affected companies).
### Confidence & Data Quality Principles

> See [00-strategic-rationale.md](00-strategic-rationale.md) for the full strategic analysis behind these principles.

1. **Ground-truth anchors**: Use stable identifiers wherever possible — CIK numbers, bioguide IDs, CUSIP codes, and ticker symbols. These are authoritative and prevent entity resolution errors from compounding across hops.

2. **Confidence decay across hops**: Multi-hop traversals compound uncertainty. If each hop has ~90% entity resolution accuracy, confidence decays exponentially:
   - Hop 1: 90% → Hop 2: 81% → Hop 3: 73% → Hop 4: 66% → Hop 5: 59%
   - Agent system applies a 0.9 per-hop discount factor when reasoning across hops.
   - Findings beyond 3 hops require corroboration from a second data source.

3. **Prefer structured over extracted**: For critical relationships (supply chain, financial ties), prefer data from structured sources (SEC filings, XBRL, Capitol Trades API) over LLM-extracted relationships. LLM-extracted relationships should carry lower confidence scores.

4. **Confidence scoring on all edges**: Every relationship carries a `confidence` property (0.0–1.0). Agent reasoning discounts low-confidence edges and flags them in reports.

5. **Staleness decay**: Relationship confidence degrades over time. A `SUPPLIES_TO` relationship extracted from a 2023 10-K filing is less reliable in 2026 than one confirmed in this quarter's filing. Apply a staleness discount based on `last_confirmed` date:
   - Confirmed within 90 days: no discount
   - 90–365 days since last confirmation: 0.9× multiplier
   - 1–2 years: 0.7× multiplier
   - 2+ years: 0.5× multiplier (flag as "stale — needs reconfirmation")
   - Combined confidence = `base_confidence × hop_decay × staleness_multiplier`
   - Staleness is especially dangerous for supply chain relationships, which change frequently without public disclosure
## Core Node Types

### Company
The central entity. Every other node connects to or through companies.

```
(:Company {
  ticker: STRING,          -- "AAPL" (primary identifier for listed companies)
  cik: STRING,             -- SEC CIK number "0000320193"
  name: STRING,            -- "Apple Inc."
  legal_name: STRING,      -- "Apple Inc." (from SEC filings)
  description: STRING,     -- Brief company description
  founded_year: INT,       -- 1976
  ipo_date: STRING,        -- "1980-12-12"
  market_cap: FLOAT,       -- Current market cap in USD
  employee_count: INT,     -- Approximate headcount
  website: STRING,         -- "https://apple.com"
  hq_city: STRING,         -- "Cupertino"
  hq_state: STRING,        -- "CA"
  status: STRING,          -- "active" | "acquired" | "delisted" | "bankrupt"
  -- Snapshot metrics (latest quarter, refreshed each ingestion cycle)
  revenue_ttm: FLOAT,            -- Trailing 12-month revenue (USD)
  revenue_growth_yoy: FLOAT,     -- Year-over-year revenue growth rate
  eps_ttm: FLOAT,                -- Trailing 12-month EPS
  pe_ratio: FLOAT,               -- Price-to-earnings ratio
  gross_margin: FLOAT,           -- Gross profit margin (0.0-1.0)
  debt_to_equity: FLOAT,         -- Total debt / total equity
  free_cash_flow_ttm: FLOAT,     -- Trailing 12-month free cash flow (USD)
  metrics_as_of: STRING,         -- Period end date for snapshot metrics
  embedding: VECTOR,       -- Embedding of company description for semantic search
  last_updated: STRING     -- ISO timestamp
})
```

> **Snapshot metrics**: These are the most-used financial screening values, promoted directly onto the Company node to enable fast Cypher-based screening across 5,000+ companies without joining to a separate metrics store. Full time series history lives in DuckDB (see [Time Series Data Store](#time-series-data-store-duckdb) below). Snapshot values are recomputed each time new financial data is ingested.

### Person
Executives, board members, key insiders.

```
(:Person {
  name: STRING,            -- "Tim Cook"
  title: STRING,           -- Most recent known title
  bio: STRING,             -- Brief biography
  linkedin_url: STRING,    -- Optional
  last_updated: STRING
})
```

### Filing
SEC filings (10-K, 10-Q, 8-K, proxy statements, etc.)

```
(:Filing {
  accession_number: STRING,  -- SEC accession number (unique ID)
  form_type: STRING,         -- "10-K", "10-Q", "8-K", "DEF 14A"
  filed_date: STRING,        -- "2025-10-30"
  period_of_report: STRING,  -- "2025-09-30"
  filing_url: STRING,        -- EDGAR URL
  summary: STRING,           -- LLM-generated summary
  key_topics: [STRING],      -- Extracted key topics
  sentiment: FLOAT,          -- -1.0 to 1.0
  summary_embedding: VECTOR, -- For semantic search across filings
  processed: BOOL            -- Whether entity extraction is complete
})
```

### Industry
Industry classifications (GICS-aligned).

```
(:Industry {
  name: STRING,            -- "Consumer Electronics"
  gics_code: STRING,       -- GICS industry code
  description: STRING,
  last_updated: STRING
})
```

### Sector
Higher-level grouping of industries (GICS sectors).

```
(:Sector {
  name: STRING,            -- "Information Technology"
  gics_code: STRING,       -- GICS sector code
  description: STRING
})
```

### Region
Geographic anchor for company HQ, operations, and market presence. Populated from 10-K cover page and segment reporting. **Economic data (GDP, credit rating, trade balance, etc.) is a future-phase addition** — do not store it here until a dedicated macro data source is integrated.

```
(:Region {
  name: STRING,            -- "United States", "China", "European Union"
  region_type: STRING,     -- "country", "economic_bloc", "state", "city"
  iso_code: STRING,        -- "US", "CN", "EU" (ISO 3166-1 alpha-2 for countries)
  last_updated: STRING
})
```

---

## Future Data Sources

The nodes and relationships below are **intentionally not schema'd yet**. They represent data categories we want to incorporate in later phases. Schema detail will be added when the ingestion pipeline for each source is being built.

### Phase 2 — Market & Alternative Data
- **NewsArticle** — news from Reuters, Bloomberg, FMP news feed; key fields: `article_id`, `title`, `source`, `url`, `published_date`, `summary` (LLM-generated), `sentiment`, `impact_score`, `embedding`; linked to companies via `MENTIONED_IN`
- **Commodity** — crude oil, lithium, semiconductor wafers, etc.; linked to companies via `DEPENDS_ON` / `PRODUCES` and to industries via `AFFECTS_INDUSTRY`
- **MacroIndicator** — Fed Funds Rate, CPI, GDP Growth (FRED/BLS/BEA); linked to industries via `AFFECTED_BY`; all time series in DuckDB `macro_timeseries`; graph node is reference anchor only (`indicator_id`, `name`, `unit`, `source`)
- **ResearchReport** — agent-generated investment theses; linked to companies, filings, news

### Phase 3 — Political & Government Data
- **Legislator** — Congress members; source: bioguide.congress.gov, Capitol Trades API
- **CongressionalTrade** — STOCK Act disclosures; source: Capitol Trades API / house.gov / senate.gov
- **Legislation** — bills, executive orders, regulations, tariffs; source: congress.gov, Federal Register
- **GovernmentContract** — federal contract awards; source: USAspending.gov

### Phase 4 — Institutional Holdings
- **InstitutionalHolder** — 13F filers (hedge funds, mutual funds, pension funds); source: SEC EDGAR 13F filings
  - Key relationship: `HOLDS_POSITION` → Company, with shares, value, quarter, position change

---

## Core Relationships

### Company ↔ Company (The Ripple Effect Relationships)

```cypher
// Supply Chain
(:Company)-[:SUPPLIES_TO {
  // ── Core metadata ────────────────────────────────────────────────────────
  confidence: FLOAT,           -- 0.0-1.0 (decays with staleness + hop distance)
  source: STRING,              -- "AAPL 10-K 2024 p.12", "TSMC earnings call"
  last_confirmed: STRING,      -- ISO date when relationship was last verified
  created_at: STRING,          -- ISO date when edge was first added to graph
  
  // ── Supply chain specifics ──────────────────────────────────────────────
  product_category: STRING,    -- "EUV lithography machines", "5nm GPU chips"
  dependency_level: STRING,    -- "critical" | "important" | "optional"
  is_sole_source: BOOL,        -- Whether supplier is the ONLY source
  contract_value_usd: FLOAT,   -- Estimated annual spend (if disclosed)
  revenue_pct: FLOAT,          -- % of supplier's revenue from this customer
  volume_estimate: STRING,     -- "100M+ units/year", "50% of wafer capacity"
  
  // ── Temporal validity ───────────────────────────────────────────────────
  valid_from: STRING,          -- Start of supply relationship
  valid_to: STRING,            -- Null if ongoing, date if terminated
  
  // ── Risk indicators ─────────────────────────────────────────────────────
  geographic_risk: STRING,     -- "Taiwan", "China", "Multi-region" (supply chain risk)
  alternative_suppliers: INT,  -- Number of known alternatives (0 = sole source)
  lead_time_weeks: INT,        -- Typical order-to-delivery time

  // ── LLM narrative ───────────────────────────────────────────────────────
  description: STRING          -- LLM-generated plain-English summary of this specific
                               --  supply relationship, e.g. "TSMC is Apple's sole-source
                               --  manufacturer for A-series and M-series SoCs using 3nm/5nm
                               --  processes. No qualified alternative exists. Estimated
                               --  $20B+ annual spend per analyst estimates."
}]->(:Company)

// Note: to find customers of a company, traverse SUPPLIES_TO in reverse:
// MATCH (supplier:Company {ticker: "TSM"})<-[:SUPPLIES_TO]-(customer:Company)
// CUSTOMER_OF is not stored — it's redundant and doubles edge count.

// Competition
(:Company)-[:COMPETES_WITH {
  // ── Core metadata ────────────────────────────────────────────────────────
  confidence: FLOAT,           -- 0.0-1.0
  source: STRING,              -- "Industry analysis", "10-K competitive section"
  last_confirmed: STRING,
  created_at: STRING,
  
  // ── Competitive dynamics ────────────────────────────────────────────────
  market_segment: STRING,      -- "high-end data center GPUs", "smartphone SoCs"
  intensity: STRING,           -- "direct" | "partial" | "adjacent" | "emerging"
  geographic_overlap: [STRING],-- ["North America", "Europe", "Asia"]
  market_share_a: FLOAT,       -- Company A's market share in segment (0.0-1.0)
  market_share_b: FLOAT,       -- Company B's market share in segment
  
  // ── Strategy indicators ─────────────────────────────────────────────────
  differentiation: STRING,     -- "price", "performance", "ecosystem", "integration"
  competitive_moat: STRING,    -- "patent portfolio", "brand", "network effects"
  threat_level: STRING,        -- "existential" | "significant" | "moderate" | "low"

  // ── LLM narrative ───────────────────────────────────────────────────────
  description: STRING,         -- LLM-generated summary of competitive dynamics between
                               --  this specific pair, e.g. "AMD directly competes with
                               --  NVIDIA in data center GPUs (H100 vs MI300X) but does
                               --  not compete in networking or robotics. AMD has ~15%
                               --  share vs NVIDIA's ~80% in AI accelerators as of 2025."

  valid_from: STRING
}]->(:Company)

// Financial / Ownership
(:Company)-[:OWNS_STAKE_IN {
  stake_pct: FLOAT,           -- Ownership percentage
  stake_type: STRING,          -- "majority", "minority", "activist"
  value_usd: FLOAT,
  source: STRING,
  valid_from: STRING,
  valid_to: STRING,
  description: STRING          -- LLM-generated context, e.g. "Berkshire acquired a ~6%
                               --  stake in TSMC in Q3 2022 then exited in Q1 2023, citing
                               --  geopolitical concerns around Taiwan."
}]->(:Company)

(:Company)-[:ACQUIRED {
  acquisition_date: STRING,
  deal_value_usd: FLOAT,
  deal_type: STRING,           -- "cash", "stock", "mixed"
  status: STRING,              -- "completed", "pending", "failed"
  description: STRING          -- LLM-generated context, e.g. "Microsoft acquired Activision
                               --  Blizzard for $68.7B in cash (Jan 2023) after an 18-month
                               --  FTC battle. Rationale: gaming content for Xbox Game Pass
                               --  and access to mobile gaming via King."
}]->(:Company)

// Direction convention: (absorbed)-[:MERGED_WITH]->(survivor)
// The arrow points TO the surviving entity — no need for a surviving_entity string property.
(:Company)-[:MERGED_WITH {
  merge_date: STRING,
  deal_value_usd: FLOAT,
  deal_type: STRING,           -- "cash", "stock", "mixed"
  source: STRING,
  description: STRING          -- LLM-generated context: rationale, regulatory hurdles,
                               --  what was absorbed, what survived, market reaction
}]->(:Company)                 -- target node IS the surviving entity

(:Company)-[:JOINT_VENTURE_WITH {
  jv_name: STRING,
  purpose: STRING,
  valid_from: STRING,
  valid_to: STRING,
  description: STRING          -- LLM-generated context beyond the purpose field, e.g.
                               --  revenue share terms, strategic rationale, known tensions
}]->(:Company)

(:Company)-[:PARTNER_WITH {
  partnership_type: STRING,    -- "technology", "distribution", "licensing"
  description: STRING,
  valid_from: STRING,
  valid_to: STRING
}]->(:Company)
```

### Company ↔ People

```cypher
(:Company)-[:HAS_EXECUTIVE {
  title: STRING,              -- "CEO", "CFO", "CTO", "Chief Scientist"
  start_date: STRING,
  end_date: STRING,           -- null if currently serving
  compensation_usd: FLOAT,    -- Most recent disclosed compensation
  stock_ownership_pct: FLOAT, -- % of company owned by this executive
  source: STRING,             -- "DEF 14A 2024", "Press release"
  last_confirmed: STRING,
  description: STRING         -- LLM-generated context, e.g. "Tim Cook has served as Apple
                              --  CEO since August 2011, succeeding Steve Jobs. Known for
                              --  supply chain expertise and expanding Apple's services
                              --  revenue from ~$20B to $85B+."
}]->(:Person)

(:Company)-[:HAS_BOARD_MEMBER {
  role: STRING,               -- "Chairman", "Independent Director", "Lead Director"
  committee: [STRING],        -- ["Audit", "Compensation", "Governance"]
  is_independent: BOOL,       -- Independent director vs. insider
  start_date: STRING,
  end_date: STRING,           -- null if currently serving
  stock_ownership_shares: INT,-- Shares owned
  source: STRING,             -- "DEF 14A 2024"
  last_confirmed: STRING,
  description: STRING         -- LLM-generated context, e.g. notable background, why they
                              --  were appointed, any known conflicts or activist pressure
}]->(:Person)
```

### Company ↔ Industry / Sector

```cypher
(:Company)-[:OPERATES_IN {
  revenue_pct: FLOAT,         -- % of revenue from this industry
  is_primary: BOOL
}]->(:Industry)

(:Industry)-[:BELONGS_TO]->(:Sector)
```

### Company ↔ Geography

```cypher
(:Company)-[:HEADQUARTERED_IN]->(:Region)

(:Company)-[:HAS_MARKET_IN {
  revenue_pct: FLOAT,         -- % of revenue from this market
  is_primary: BOOL
}]->(:Region)

(:Company)-[:HAS_OPERATIONS_IN {
  operation_type: STRING       -- "manufacturing", "R&D", "sales"
}]->(:Region)
```

### Company ↔ Filings

```cypher
(:Company)-[:FILED]->(:Filing)
```

> **Screening queries** use snapshot metrics on the Company node directly (no join needed):
> ```cypher
> MATCH (c:Company)-[:OPERATES_IN]->(ind:Industry)
> WHERE c.pe_ratio < 20 AND c.revenue_growth_yoy > 0.10
> RETURN c.ticker, c.pe_ratio, c.revenue_growth_yoy
> ```
> **Trend/time series queries** hit DuckDB, not FalkorDB. See [Time Series Data Store](#time-series-data-store-duckdb).

### Company ↔ News

> **Future Phase 2.** Schema TBD when news ingestion is built. Intended relationship: `MENTIONED_IN` (Company → NewsArticle) with mention_type and sentiment. Source: FMP news feed, Reuters, Bloomberg.

### Company ↔ Commodities

> **Future Phase 2.** Schema TBD when commodity data ingestion is built. Intended relationships: `DEPENDS_ON` (raw material / energy / component input) and `PRODUCES` (for commodity-producing companies). Source: 10-K risk factors and business description.

### Industry / Macro Connections

> **Future Phase 2.** Schema TBD. Intended relationships: `AFFECTED_BY` (Industry → MacroIndicator, with correlation and lag), `AFFECTS_INDUSTRY` (Commodity → Industry). Source: academic studies, historical regressions against FRED data.

### Research Report Connections

> **Future Phase 2.** Schema TBD. Agent-generated reports will link to Company, NewsArticle, Filing, MacroIndicator, Legislation, CongressionalTrade nodes as evidence anchors.

### Legislator ↔ Congressional Trades & Committees

> **Future Phase 3.** Schema TBD. Intended relationships: `DISCLOSED_TRADE` (Legislator → CongressionalTrade → Company), `SPONSORED` (Legislator → Legislation), `SERVES_ON_COMMITTEE` (Legislator → Industry). Source: Capitol Trades API, bioguide.congress.gov.

### Legislation ↔ Industries & Companies

> **Future Phase 3.** Schema TBD. Intended relationships: `AFFECTS` (Legislation → Industry, Company, Region) with impact_type, direction, confidence. Source: congress.gov, LLM analysis of bill text.

### Institutional Holdings (13F)

> **Future Phase 4.** Schema TBD. Intended relationship: `HOLDS_POSITION` (InstitutionalHolder → Company) with shares, value, quarter, position change type. Source: SEC EDGAR 13F filings.

### Government Contracts

> **Future Phase 3.** Schema TBD. Intended relationships: `AWARDED_CONTRACT` (Company → GovernmentContract). Source: USAspending.gov.

### Country ↔ Trade & Policy

> **Future Phase 3.** Schema TBD. Intended relationships: `TRADES_WITH` (Region → Region) and `HAS_POLICY` (Region → Legislation). Source: WTO, World Bank, US Census Bureau.

### Auto-Extended Relationships

GraphRAG-SDK may discover relationships not in the core schema from SEC filing text. These are stored as:

```cypher
(:Company)-[:RELATED_TO {
  relationship_detail: STRING,  -- LLM-extracted description
  source_document: STRING,      -- Accession number or document identifier
  confidence: FLOAT,
  auto_detected: BOOL,         -- true (flag for review)
  detected_date: STRING
}]->(:Company)
```

Periodically review `RELATED_TO` edges and promote to named relationship types. See Phase 7 (Feedback Loop) in [07-phased-roadmap.md](07-phased-roadmap.md) for the ontology refinement process.

> **Graph noise warning**: Auto-detected relationships can create false patterns. Implement confidence thresholds and require multi-source corroboration before agents use them in analysis. See [00-strategic-rationale.md](00-strategic-rationale.md) § "Honest Risk Assessment" for details.

---

## Edge Property Best Practices

### Why Rich Edge Properties Matter

The difference between basic and enriched edges is the difference between **generic analysis** and **actionable intelligence**:

**Before** (basic `SUPPLIES_TO` with no properties):
> "TSMC supplies Apple. A TSMC disruption would affect Apple."

**After** (enriched with `dependency_level`, `is_sole_source`, `product_category`):
> "TSMC is Apple's **sole-source supplier** for A-series and M-series chips (5nm/3nm process), representing **critical dependency** per Apple's 10-K risk factors. A TSMC fab disruption would **immediately halt** iPhone and Mac production with **no alternative supplier** available. Estimated impact: $200B+ annual revenue at risk. Confidence: 0.95."

This is what separates institutional-grade research from surface-level analysis.

### Property Population Strategy

| Property | Phase 0 (Manual) | Phase 2+ (Automated) | Data Source |
|----------|------------------|----------------------|-------------|
| `confidence` | ✓ Manual estimate | LLM multi-source scoring | Filing text + news corroboration |
| `source` | ✓ "10-K 2024" | Full citation with page | XBRL metadata + document parser |
| `description` | ✓ Hand-written for seed edges | LLM-generated at ingestion time | Source paragraph(s) the relationship was extracted from — passed as context to the LLM |
| `product_category` | ✓ Hand-coded | LLM extraction | "Principal Suppliers" section |
| `dependency_level` | ✓ Domain knowledge | LLM + keyword detection | "Risk Factors" mentions of "sole source", "critical" |
| `is_sole_source` | ✓ Known facts | Regex + LLM confirmation | "Sole source", "single supplier" in 10-K |
| `contract_value_usd` | Manual (if public) | Scrape from earnings calls | Transcript parsing + UMM disambiguation |
| `market_segment` | ✓ Industry taxonomy | LLM extraction | 10-K "Competition" section |
| `geographic_overlap` | Industry knowledge | Company "Geographic Revenue" sections | 10-K Item 1, segment reporting |
| `correlation` (AFFECTED_BY) | Domain knowledge / literature | Historical regression vs. DuckDB macro_timeseries | Academic studies + FRED data |

> **`description` generation rule**: At ingestion time, pass the **source passage** (the paragraph from the 10-K, earnings call excerpt, or news article) directly to the LLM and ask it to write a 2–4 sentence synthesis specific to this entity pair. Do **not** generate from structured fields alone — the description should add information beyond what the structured properties already capture. Store the source passage in the `source` field for provenance.

> **What NOT to store on nodes**: Commodity prices, macro indicator values, region economic snapshots — anything that changes faster than your ingestion cycle will be stale by the time an agent reads it. These belong in DuckDB or a live price feed, with the graph node serving only as the reference anchor (`name`, `indicator_id`, `unit`).

### Edge Property Validation Rules

1. **Confidence decay**: All edges have a base confidence that decays with:
   - **Staleness**: Multiply by 0.9 if 90-365 days since `last_confirmed`, 0.7 if 1-2 years, 0.5 if 2+ years
   - **Hop distance**: See "Confidence & Data Quality Principles" above — 0.9 per hop
   - Combined: `effective_confidence = base_confidence × staleness_multiplier × hop_decay`

2. **Source citation mandatory**: Every edge MUST have a `source` property. No exceptions. If source is unknown, mark as `"source": "unverified"` and flag for review.

3. **Temporal validity**: For time-sensitive relationships (SUPPLIES_TO, HOLDS_POSITION), always populate `last_confirmed`. If > 1 year old, flag for re-verification.

4. **Mutual exclusivity checks**:
   - `is_sole_source = true` → `alternative_suppliers = 0`
   - `dependency_level = "critical"` → `is_sole_source = true OR alternative_suppliers ≤ 2`

5. **Numeric range validation**:
   - `confidence`: 0.0–1.0
   - `revenue_pct`: 0.0–1.0 (can exceed 1.0 if supplier has multiple revenue streams)
   - `market_share_a/b`: 0.0–1.0

6. **No volatile data on nodes**: Never store time-varying values (prices, indicator readings, trends) directly on nodes. These become stale silently and agents will use them as if current. Always query DuckDB for current values.

7. **Relationship direction encodes meaning**: `MERGED_WITH` arrow points TO the surviving entity. `ACQUIRED` arrow points TO the acquired target. Never use a STRING property to encode what the graph structure already expresses.

### Query Pattern: Using Edge Properties for Precision

```cypher
// Find CRITICAL supply chain dependencies (highest disruption risk)
MATCH (supplier:Company)-[r:SUPPLIES_TO]->(customer:Company)
WHERE r.dependency_level = 'critical'
  AND r.is_sole_source = true
  AND r.confidence > 0.8
  AND date(r.last_confirmed) > date('2025-01-01')  // Recent confirmation
RETURN supplier.ticker,
       customer.ticker,
       r.product_category,
       r.contract_value_usd,
       r.geographic_risk,
       r.last_confirmed
ORDER BY r.contract_value_usd DESC
```

```cypher
// Find direct competitors in a specific market with significant overlap
MATCH (c:Company {ticker: 'NVDA'})-[r:COMPETES_WITH]-(competitor:Company)
WHERE r.intensity = 'direct'
  AND r.market_segment CONTAINS 'GPU'
  AND r.confidence > 0.85
RETURN competitor.ticker,
       r.market_segment,
       r.market_share_a AS nvda_share,
       r.market_share_b AS competitor_share,
       r.differentiation,
       r.threat_level
ORDER BY r.market_share_b DESC
```

---

## Example Graph Traversals (Ripple Effect Queries)

### "Which companies are affected if TSMC has production issues?"

```cypher
// 1-hop: Direct customers with CRITICAL dependencies
MATCH (tsmc:Company {ticker: "TSM"})-[r:SUPPLIES_TO]->(customer:Company)
WHERE r.dependency_level IN ['critical', 'important']
  AND r.confidence > 0.8
RETURN customer.ticker,
       customer.name,
       r.product_category,
       r.dependency_level,
       r.is_sole_source,
       r.contract_value_usd,
       r.confidence
ORDER BY r.contract_value_usd DESC

// 2-hop: Ripple effects with confidence decay
MATCH path = (tsmc:Company {ticker: "TSM"})-[r1:SUPPLIES_TO]->(c1:Company)-[r2:SUPPLIES_TO]->(c2:Company)
WHERE r1.confidence > 0.8 AND r2.confidence > 0.7
WITH c1, c2, r1, r2,
     (r1.confidence * 0.9) AS hop1_confidence,                    // 1st hop decay
     (r1.confidence * 0.9 * r2.confidence * 0.9) AS hop2_confidence  // 2nd hop decay
RETURN c1.ticker AS direct_customer,
       c1.name AS direct_name,
       r1.product_category AS tsmc_supplies,
       c2.ticker AS ripple_customer,
       c2.name AS ripple_name,
       r2.product_category AS c1_supplies,
       round(hop1_confidence, 3) AS c1_confidence,
       round(hop2_confidence, 3) AS c2_confidence,
       CASE
         WHEN hop2_confidence < 0.7 THEN 'speculative - needs corroboration'
         ELSE 'reliable'
       END AS confidence_assessment
ORDER BY hop2_confidence DESC
LIMIT 20

// Geographic concentration risk: Find customers dependent on Taiwan-based supply
MATCH (tsmc:Company {ticker: "TSM"})-[r:SUPPLIES_TO]->(customer:Company)
WHERE r.geographic_risk = 'Taiwan'
  AND r.dependency_level = 'critical'
WITH customer, 
     COUNT{(customer)-[r2:SUPPLIES_TO]->(other) WHERE r2.geographic_risk = 'Taiwan'} AS taiwan_suppliers
WHERE taiwan_suppliers > 0
RETURN customer.ticker,
       customer.name,
       taiwan_suppliers AS total_taiwan_dependencies,
       'Taiwan blockade scenario: severe impact' AS risk_assessment
ORDER BY taiwan_suppliers DESC

// Multi-hop with industry context and edge property filtering
MATCH path = (tsmc:Company {ticker: "TSM"})-[rels:SUPPLIES_TO|COMPETES_WITH|PARTNER_WITH*1..3]-(affected:Company)
WHERE ALL(r IN rels WHERE r.confidence > 0.75)  // Filter low-confidence edges
MATCH (affected)-[:OPERATES_IN]->(ind:Industry)
WITH affected, ind, 
     length(path) AS hops,
     [r IN relationships(path) | {type: type(r), confidence: r.confidence}] AS rel_details,
     reduce(conf = 1.0, r IN relationships(path) | conf * r.confidence * 0.9) AS path_confidence
RETURN affected.ticker,
       affected.name,
       ind.name AS industry,
       hops,
       round(path_confidence, 3) AS overall_confidence,
       rel_details AS relationship_chain
ORDER BY hops ASC, path_confidence DESC
LIMIT 50
```

### "How might rising interest rates affect the tech sector?"

> Requires Phase 2 MacroIndicator + AFFECTED\_BY data. Query pattern TBD.

### "Which Congress members recently bought defense stocks?"

> Requires Phase 3 Legislator + CongressionalTrade data. Query pattern TBD.

### "What legislation could affect the semiconductor industry?"

> Requires Phase 3 Legislation + AFFECTS data. Query pattern TBD.

### "What are the top institutional holders buying this quarter?"

> Requires Phase 4 InstitutionalHolder + HOLDS\_POSITION data. Query pattern TBD.

### "Multi-domain ripple: Congress trades + legislation + supply chain + institutional positioning"

> Requires Phase 3+4 data. Query pattern TBD. See the full example in git history for the intended structure once those phases are implemented.

### "Find companies with shared board members (interlock analysis)"

```cypher
// Board interlocks can signal information flow or strategic alignment
MATCH (c1:Company)-[r1:HAS_BOARD_MEMBER]->(p:Person)<-[r2:HAS_BOARD_MEMBER]-(c2:Company)
WHERE c1.ticker < c2.ticker  // Avoid duplicates
  AND r1.is_independent = true
  AND r2.is_independent = true  // Focus on independent directors (reduce noise)
WITH c1, c2, p, r1, r2
WHERE date(r1.end_date) IS NULL AND date(r2.end_date) IS NULL  // Currently serving
RETURN c1.ticker AS company_a,
       c1.name AS name_a,
       c2.ticker AS company_b,
       c2.name AS name_b,
       p.name AS shared_director,
       r1.role AS role_at_a,
       r2.role AS role_at_b,
       r1.committee AS committees_at_a,
       r2.committee AS committees_at_b,
       // Does this create strategic information flow?
       CASE
         WHEN 'Audit' IN r1.committee AND 'Audit' IN r2.committee
           THEN 'Financial oversight interlock'
         WHEN r1.role CONTAINS 'Chairman' OR r2.role CONTAINS 'Chairman'
           THEN 'Executive-level interlock'
         ELSE 'Board-level connection'
       END AS interlock_significance
ORDER BY company_a, company_b
```

---

## Indexes

```cypher
// Phase 1 unique constraints (SEC-sourced nodes)
CREATE CONSTRAINT ON (c:Company) ASSERT c.ticker IS UNIQUE
CREATE CONSTRAINT ON (c:Company) ASSERT c.cik IS UNIQUE
CREATE CONSTRAINT ON (f:Filing) ASSERT f.accession_number IS UNIQUE

// Full-text search indexes
CALL db.idx.fulltext.createNodeIndex('company_search', 'Company', 'name', 'description')
CALL db.idx.fulltext.createNodeIndex('filing_search', 'Filing', 'summary')

// Vector indexes (for semantic search)
CREATE VECTOR INDEX FOR (c:Company) ON (c.embedding)
CREATE VECTOR INDEX FOR (f:Filing) ON (f.summary_embedding)

// Range indexes for time-based queries
CREATE INDEX FOR (f:Filing) ON (f.filed_date)

// Future phases will add constraints for:
// NewsArticle, Legislator, CongressionalTrade, Legislation,
// GovernmentContract, InstitutionalHolder, MacroIndicator
```

---

## Time Series Data Store (DuckDB)

Financial time series data lives in **DuckDB** — an embedded columnar analytical database — rather than in FalkorDB. This is a deliberate architectural split:

| Concern | FalkorDB (Graph) | DuckDB (Analytical) |
|---------|-------------------|---------------------|
| **Data** | Relationships, entities, latest snapshot metrics | Full historical time series (40+ quarters) |
| **Query pattern** | Multi-hop traversal, entity discovery, screening | Trend analysis, growth rates, peer comparison, window functions |
| **Scale** | 800K+ nodes, 3M+ edges, ~16 GB in-memory budget | 4M+ rows on disk, columnar compression |
| **Storage** | In-memory (Redis protocol) | On-disk file (`data/duckdb/financial_timeseries.duckdb`) |
| **Why** | Graph traversals and relationship queries | Analytical aggregations, YoY/QoQ growth, moving averages, CAGR |

### Why not keep everything in FalkorDB?

5,000 companies × 20+ metrics × 40 quarters = **4,000,000+ data points** at ~200–500 bytes each = **~1–2 GB** of FalkorDB's 16 GB memory budget, competing with the relationship data the graph is actually good at. And Cypher is awkward for window functions, growth rate calculations, and peer-group rankings — these are columnar analytical workloads.

### Why DuckDB over SQLite?

Both are embedded (single file, no server). DuckDB is purpose-built for analytical queries — columnar storage, vectorized execution, native window functions. At 4M rows the performance difference is small, but DuckDB's SQL ergonomics for analytical workloads (QUALIFY, WINDOW, SAMPLE, Parquet import) make the time series queries significantly more natural than SQLite.

### Growth Rate Strategy: Compute, Don't Precompute

Growth rates (YoY, QoQ, CAGR) are **computed at query time** using SQL window functions — not stored in a separate precomputed table. Reasons:

- **DuckDB is fast enough**: a window function over 4M rows runs in < 10ms. There is no performance problem to solve.
- **No sync bugs**: a precomputed table requires a separate recompute step on every ingestion. If a company restates earnings and `financial_metrics` is updated, a stale precomputed table silently serves wrong growth numbers.
- **Restatements are common**: earnings restatements, segment reclassifications, and acquisition adjustments are frequent. Derived tables compound this risk.

Instead, growth rates are computed inside the `get_financial_history` agent tool (see [04-agent-system.md](04-agent-system.md)) and cached at the tool layer via `lru_cache` for performance within a session.

### DuckDB Schema

```sql
-- Full time series store: every metric for every company for every period
CREATE TABLE financial_metrics (
    ticker       VARCHAR NOT NULL,
    cik          VARCHAR,
    metric_type  VARCHAR NOT NULL,   -- 'revenue', 'net_income', 'eps', 'gross_margin', ...
    value        DOUBLE NOT NULL,
    currency     VARCHAR DEFAULT 'USD',
    period       VARCHAR NOT NULL,   -- 'Q3-2025', 'FY-2025'
    period_type  VARCHAR NOT NULL,   -- 'quarterly', 'annual', 'ttm'
    period_end   DATE NOT NULL,      -- 2025-09-30
    source       VARCHAR,            -- '10-K', '10-Q', 'fmp', 'polygon'
    accession    VARCHAR,            -- SEC filing accession number (if from filing)
    ingested_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (ticker, metric_type, period_type, period_end)
);

-- Macro time series (FRED, World Bank, BLS, BEA)
CREATE TABLE macro_timeseries (
    indicator_id  VARCHAR NOT NULL,   -- 'FEDFUNDS', 'CPIAUCSL', 'GDP'
    name          VARCHAR NOT NULL,
    value         DOUBLE NOT NULL,
    unit          VARCHAR,            -- 'percent', 'index', 'billions_usd'
    date          DATE NOT NULL,
    source        VARCHAR,            -- 'FRED', 'WorldBank', 'BLS', 'BEA'
    ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (indicator_id, date)
);
```

### Example DuckDB Queries

```sql
-- Revenue growth trend for Apple over 5 years
SELECT period, value,
       value / LAG(value, 4) OVER (ORDER BY period_end) - 1 AS yoy_growth
FROM financial_metrics
WHERE ticker = 'AAPL' AND metric_type = 'revenue' AND period_type = 'quarterly'
ORDER BY period_end DESC
LIMIT 20;

-- Peer comparison: tech companies ranked by revenue growth
SELECT ticker,
       LAST(value ORDER BY period_end) AS latest_revenue,
       LAST(value ORDER BY period_end) / 
         NTH_VALUE(value, 1) OVER (PARTITION BY ticker ORDER BY period_end 
           ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) - 1 AS yoy_growth
FROM financial_metrics
WHERE metric_type = 'revenue' AND period_type = 'quarterly'
  AND ticker IN ('AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META')
GROUP BY ticker
ORDER BY yoy_growth DESC;

-- Margin compression detection: companies where gross margin
-- dropped 5%+ below their recent 4-quarter average
WITH margins AS (
    SELECT ticker, period, value AS gross_margin,
           AVG(value) OVER (PARTITION BY ticker
             ORDER BY period_end ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS margin_4q_avg
    FROM financial_metrics
    WHERE metric_type = 'gross_margin' AND period_type = 'quarterly'
)
SELECT * FROM margins
WHERE gross_margin < margin_4q_avg * 0.95
ORDER BY ticker, period_end DESC;

-- Fed Funds Rate over time
SELECT date, value FROM macro_timeseries
WHERE indicator_id = 'FEDFUNDS'
ORDER BY date DESC LIMIT 60;
```

### Data Flow: Ingestion → DuckDB → FalkorDB Snapshot

```
           ┌──────────────┐
           │ Data Sources  │  (EDGAR XBRL, FMP, Polygon, FRED, BLS, ...)
           └──────┬───────┘
                  │
                  ▼
           ┌──────────────┐
           │ Ingestion     │  Parse → validate → normalize
           │ Pipeline       │
           └──────┬───────┘
                  │
          ┌───────┼────────┐
          ▼                ▼
   ┌────────────┐   ┌────────────┐
   │  DuckDB    │   │  FalkorDB  │
   │            │   │            │
   │ Full time  │   │ Filing     │  (:Company)-[:FILED]->(:Filing)
   │ series     │   │ nodes +    │  Graph traversal, entity relationships
   │ (4M+ rows) │   │ relations  │
   │            │   │            │
   │ Growth     │──►│ Snapshot   │  Recompute Company snapshot metrics
   │ calcs      │   │ on Company │  (revenue_ttm, pe_ratio, etc.)
   └────────────┘   └────────────┘
```

Agent tools query both stores:
- **Screening / discovery** → FalkorDB snapshot metrics (fast Cypher)
- **Trend analysis / growth rates** → DuckDB (`get_financial_history` tool)
- **Provenance ("which filing reported metric X?")** → DuckDB `financial_metrics` table (`accession` column links each row to its source filing)

---

## Temporal Modeling

All relationships that change over time carry `valid_from`, `valid_to`, and `last_confirmed` properties:

- `valid_from`: When the relationship became active (ISO date string)
- `valid_to`: When the relationship ended (`null` if still active)
- `last_confirmed`: When this relationship was last corroborated by a data source (ISO date string). Used for staleness decay calculations (see Confidence & Data Quality Principles above)

This enables:
- **Point-in-time queries**: "Who supplied Apple in 2023?"
- **Change detection**: "Which supply chain relationships changed this quarter?"
- **Historical analysis**: "How has this company's competitive landscape evolved?"

```cypher
// Current suppliers only
MATCH (c:Company {ticker: "AAPL"})-[r:SUPPLIES_TO]->(supplier)
WHERE r.valid_to IS NULL
RETURN supplier.name

// Suppliers as of a specific date
MATCH (c:Company {ticker: "AAPL"})-[r:SUPPLIES_TO]->(supplier)
WHERE r.valid_from <= "2024-01-01" AND (r.valid_to IS NULL OR r.valid_to > "2024-01-01")
RETURN supplier.name
```
