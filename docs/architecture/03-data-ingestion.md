# Data Ingestion & Sources

## Overview

The data ingestion layer is responsible for continuously pulling data from multiple sources, converting it into a format suitable for knowledge graph population, and loading it into FalkorDB. The platform goes beyond company data — it ingests country-level economic data, Congressional investment disclosures, institutional holdings, government contracts, legislation, and any other data source that contributes to an accurate picture of the global economic landscape.

This document serves as both the **ingestion architecture** (pipeline design, entity resolution, state tracking) and the **comprehensive data source catalog** (URLs, pricing, rate limits, access methods). Each pipeline section includes detailed source reference tables alongside the processing steps.

---

## Data Quality Principles

> **Core principle**: Prefer structured data sources (CIK numbers, SEC Company Facts API, Capitol Trades API, CUSIP codes) over LLM extraction for critical relationships. LLM-extracted relationships carry lower confidence scores and compound errors across graph hops. See [00-strategic-rationale.md](00-strategic-rationale.md) § "Where This Platform Won't Have an Edge" → Data Quality at Scale.

1. **Ground-truth anchors > LLM extraction**: CIK, CUSIP, bioguide ID, SIC code, Company Facts API → always prefer structured identifiers
2. **Government sources > third-party aggregators**: EDGAR over sec-api, Congress.gov over Capitol Trades, USASpending over contractor databases
3. **Structured > unstructured**: SEC Company Facts API over 10-K text parsing, XML ownership reports over news articles
4. **Multiple source corroboration**: A supply chain relationship extracted from a 10-K is stronger if confirmed by ImportYeti trade data
5. **Staleness matters**: 13F data is 45 days old by definition. Macro data varies by indicator (GDP quarterly, employment monthly, fed funds rate daily). Tag data freshness on every node

See [02-graph-schema.md](02-graph-schema.md) § "Confidence & Data Quality Principles" for schema-level implementation.

> **Key insight**: The overwhelming majority of data this platform needs is **free**. The US government provides extraordinary amounts of public data via SEC, FRED, Congress.gov, USASpending, Federal Register, BLS, and BEA — all with well-documented APIs. The platform's value comes from *connecting* this free data in a knowledge graph, not from paying for proprietary data. See [00-strategic-rationale.md](00-strategic-rationale.md) § "Strategic Positioning."

---

## Tier Classification

Each data source is classified by priority tier, which maps to the [phased roadmap](07-phased-roadmap.md):

| Tier | Definition | When to Build |
|------|-----------|---------------|
| **Tier 0** | Foundation — the graph is useless without these | Phase 0 (Data Foundation) and Phase 1-2 |
| **Tier 1** | Core value — these enable multi-hop analysis and cross-domain connections that differentiate the platform | Phase 2-3 |
| **Tier 2** | Institutional parity — these close the gap with institutional investors | Phase 3-5 |
| **Tier 3** | Enhancement — adds depth but not critical path | Phase 5+ |
| **Tier 4** | Aspirational — expensive or difficult to access, consider only if earlier tiers prove value | Post-Phase 7 |

### Reference Aggregator — Quiver Quantitative

**URL**: https://www.quiverquant.com/ | **API**: https://api.quiverquant.com/ | **Pricing**: Free (website), ~$25/mo or $300/yr (Premium with API)

Quiver has already parsed, ticker-matched, and aggregated many of the same raw government sources this platform plans to ingest directly. They've solved the entity resolution problem for these datasets — matching messy disclosure text to tradeable tickers. **This platform builds on raw sources directly**, but Quiver is a useful reference for (1) cross-validating our entity resolution and ticker matching against theirs, and (2) understanding what a finished dataset looks like before building our own parsers.

**Quiver datasets vs. this platform's planned sources:**

| Quiver Dataset | Raw Source They Parse | Our Tier | Our Pipeline / Source | Our Raw Source |
|---------------|----------------------|----------|----------------------|----------------|
| **Congressional Trading** | House/Senate STOCK Act PDFs | **Tier 1** | Pipeline 6 | House Clerk, Senate EFDS, Capitol Trades |
| **Institutional Trading (13F)** | SEC EDGAR 13F-HR filings | **Tier 1** | Pipeline 7 | EDGAR 13F-HR XML + OpenFIGI |
| **Insider Trading** | SEC Forms 3, 4, 5 | **Tier 3** | Source 3.1 | EDGAR ownership XML reports |
| **Government Contracts** | USASpending.gov / FPDS | **Tier 2** | Pipeline 8 | USASpending.gov API |
| **Corporate Lobbying** | Senate LDA filings | **Tier 4** | Source 4.3 | Senate LDA API |
| **U.S. Patents** | USPTO PatentsView | **Tier 3** | Source 3.4 | USPTO PatentsView API |
| **Social Media Trends** | Reddit (WSB), Twitter | **Tier 4** | Source 4.2 | Reddit API, X API, StockTwits |
| **Dark Pool / Off-Exchange** | FINRA ATS data | **Tier 3** | Source 3.11 | FINRA ATS weekly reports |
| **Google Search Trends** | Google Trends | **Tier 4** | Source 4.7 | Google Trends API / pytrends |
| **CNBC Stock Picks** | CNBC mentions | **Tier 4** | Source 4.8 | CNBC scraping |
| **Corporate Flights** | FAA flight data | **Tier 4** | Source 4.9 | FAA ASDI / ADS-B Exchange |
| **Inflation Forecasts** | Various models | **Tier 2** | Pipeline 2 (FRED) | FRED series (T10YIE, CPI, etc.) |
| **App Store Ratings** | App Store / Play Store | **Tier 4** | Source 4.1 (alt data) | Apptopia etc. ($10K+/yr) |

**Premium-only features** (not datasets, but analytical tools Quiver built on top):
- Politician Stock Portfolio Leaderboard — net worth estimates, return tracking
- Congress Backtester — test strategies based on Congressional trades
- Institutional Backtester — test strategies based on 13F activity
- Stock Smart Score — composite scoring across their datasets
- Strategies & Copytrading — via Quantbase partnership

**Key takeaway**: All 13 of Quiver's datasets now have corresponding entries in this document. 7 overlap with core planned sources (Tiers 1-2), 2 are Tier 3 enhancements (insider trading, dark pool), and 4 are Tier 4 aspirational (lobbying, social media, Google Trends, CNBC picks, corporate flights). Quiver's value-add is the pre-computed ticker matching and clean API — exactly the entity resolution work that takes weeks to build.

---

## Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Ingestion Scheduler                        │
│                     (APScheduler)                             │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ SEC EDGAR│ │Financial │ │  News    │ │  Web Scraper   │  │
│  │ Pipeline │ │Data Pipe │ │ Pipeline │ │  Pipeline      │  │
│  │ (daily)  │ │(daily/hr)│ │(15-30min)│ │  (weekly)      │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬─────────┘  │
│       │             │            │               │            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │Congressional │ │13F Holdings │ │ Gov/Policy   │         │
│  │ Disclosures  │ │  Pipeline   │ │ Pipeline     │         │
│  │ (daily)      │ │ (quarterly) │ │ (daily)      │         │
│  └──────┬───────┘ └─────┬────────┘ └──────┬───────┘         │
│         │               │                 │                  │
│         ▼               ▼                 ▼                  │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              Document Preprocessor                       ││
│  │     MarkItDown (PDF, DOCX, HTML → Markdown)              ││
│  └──────────────────────┬───────────────────────────────────┘│
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              Entity Extraction                           ││
│  │     GraphRAG-SDK (Markdown → Entities + Relations)       ││
│  │     Company Facts API (JSON → Structured nodes)          ││
│  └──────────────────────┬───────────────────────────────────┘│
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              Entity Resolution                           ││
│  │     Dedup by CIK/Ticker + Fuzzy name matching            ││
│  │     MERGE operations (upsert, not duplicate)             ││
│  └──────────────────────┬───────────────────────────────────┘│
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐│
│  │              FalkorDB Loader                             ││
│  │     Cypher MERGE statements                              ││
│  │     Batch operations for bulk loads                      ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

> **Note**: Pipelines 1-5 are Tier 0 (foundation). Pipeline 6 and 7 are Tier 1 (core value). Pipeline 8 is Tier 2 (institutional parity). Tier 3 and Tier 4 sources (below) will get pipelines in later phases as warranted.

---

## Pipeline 1: SEC EDGAR (Tier 0)

### Sources

#### SEC EDGAR — Company Filings (10-K, 10-Q, 8-K, etc.)

| Field | Detail |
|-------|--------|
| **URL** | https://www.sec.gov/cgi-bin/browse-edgar |
| **API** | https://efts.sec.gov/LATEST/search-index (Full-Text Search), https://data.sec.gov/submissions/ (Company Submissions JSON), https://data.sec.gov/api/xbrl/companyfacts/ (Company Facts API) |
| **Pricing** | **Free** |
| **Rate Limit** | 10 requests/second. Must include `User-Agent` header with company name, contact email |
| **Auth** | None (public). User-Agent identification required |
| **Format** | HTML, JSON (submissions API, Company Facts API) |
| **Fetch Method** | REST API. Use `data.sec.gov/submissions/CIK{cik}.json` for filing metadata. Download individual filings via accession number. Use the Company Facts API (`data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`) for structured financials — returns all historical XBRL facts as JSON in one call, eliminating the need to parse XBRL from individual filings. Use Full-Text Search API for keyword search across filings |
| **Key Data** | 10-K (annual), 10-Q (quarterly), 8-K (material events), DEF 14A (proxy), S-1 (IPO), 13F (institutional holdings — see Pipeline 7) |
| **Graph Nodes** | `Company`, `Filing`, `Person` (executives from proxy) |
| **Relationships** | `FILED`, `HAS_EXECUTIVE`, `MENTIONED_IN` |
| **Update Frequency** | Filings posted within hours of submission. Daily index files available |
| **Python Libraries** | `sec-edgar-downloader`, `edgartools`, `sec-api` (paid wrapper) |
| **Notes** | The single most important data source. All public US company data flows from here. Use the submissions API to get all filings for a company by CIK. Bulk download daily index files for initial seeding |

#### SEC EDGAR Company Facts API — Structured Financial Data

| Field | Detail |
|-------|--------|
| **URL** | https://data.sec.gov/api/xbrl/companyfacts/ |
| **API** | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` (all facts for a company), `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json` (specific concept) |
| **Pricing** | **Free** |
| **Rate Limit** | Same as EDGAR: 10 req/sec |
| **Format** | JSON |
| **Fetch Method** | REST API. Each company has a `companyfacts` endpoint returning all reported XBRL facts. Bulk download available at `https://efts.sec.gov/LATEST/bulk-data/companyfacts.zip` (~2GB) |
| **Key Data** | Revenue, net income, total assets, total liabilities, EPS, shares outstanding, operating cash flow — all directly from filings, no LLM extraction needed |
| **Graph Nodes** | `Company` (snapshot metric updates), `Filing` |
| **Relationships** | `FILED` (Company → Filing) |
| **Notes** | **This is the primary source for structured financial data.** The Company Facts API returns all XBRL facts ever filed by a company as a single JSON payload — machine-readable, audited, and authoritative. One API call per CIK replaces the need to download and parse XBRL from individual filings. The bulk download (`companyfacts.zip` ~2GB) is the fastest way to seed financial metrics for 5,000+ companies. This is the "ground-truth anchor" referenced in the schema design. Financial metrics are **written to DuckDB** (`financial_metrics` table, with `accession` column for provenance); latest snapshot values are recomputed onto the FalkorDB `Company` node properties. See [02-graph-schema.md](02-graph-schema.md) § Time Series Data Store |

#### SIC / NAICS Industry Classification (Tier 1)

| Field | Detail |
|-------|--------|
| **URL** | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany (SIC from EDGAR), https://www.census.gov/naics/ (NAICS) |
| **Pricing** | **Free** |
| **Fetch Method** | Extract SIC code from EDGAR company submissions (`data.sec.gov/submissions/CIK{cik}.json` → `sic` field). Map SIC to sector/industry using standard SIC tables. Alternatively, use FMP profiles for GICS classification |
| **Key Data** | SIC code, SIC description, sector, industry group |
| **Graph Nodes** | `Industry`, `Sector` |
| **Relationships** | `OPERATES_IN` (Company → Industry), `BELONGS_TO` (Industry → Sector) |
| **Notes** | SIC codes from EDGAR are the authoritative classification for SEC-registered companies. GICS (Global Industry Classification Standard) from FMP is more commonly used in investment analysis. Seed the graph with both |

### Cadence
- **Daily batch**: Check for new filings for all tracked companies
- **Backfill**: Initial load of historical filings (last 3-5 years)

### Pipeline Steps

```
1. Fetch filing index for each tracked CIK
   └── GET https://data.sec.gov/submissions/CIK{cik}.json
   └── Filter for form types: 10-K, 10-Q, 8-K, DEF 14A, SC 13D
   └── Skip already-processed accession numbers

2. Download filing documents
   └── Primary document (HTML/XML) from filing URL

3. Preprocess with MarkItDown
   └── Convert HTML filing → Markdown
   └── Preserve tables, headers, structure

4. Fetch structured financial data (SEC Company Facts API)
   └── GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
   └── Map US GAAP concepts (Revenues, NetIncomeLoss, EarningsPerShareDiluted, etc.) → metric_type names
   └── Filter to 10-K FY entries; de-duplicate by earliest filing per period
   └── Write full time series → DuckDB (financial_metrics table, accession column preserved)
   └── Recompute Company snapshot metrics (revenue_ttm, pe_ratio, etc.) → FalkorDB Company node
   └── Extract SIC code → map to Industry/Sector nodes

5. Extract entities & relationships (GraphRAG-SDK)
   └── Feed markdown to GraphRAG-SDK
   └── Auto-detect: mentioned companies, executives, products,
       supply chain references, risk factors, legal proceedings

6. Entity resolution
   └── Match extracted company names → existing Company nodes (by CIK/ticker)
   └── Match person names → existing Person nodes (fuzzy match)
   └── Create new nodes for unknown entities

7. Load into FalkorDB
   └── MERGE Filing node (keyed on accession_number)
   └── MERGE relationships: Company-[:FILED]->Filing
   └── MERGE extracted relationships (SUPPLIES_TO, etc.)
```

### Key Considerations
- **Rate limiting**: EDGAR requires `User-Agent` header with contact info. Max 10 requests/sec
- **XBRL concept mapping**: US GAAP concept names (e.g., `us-gaap:Revenues`) → metric_type names. The Company Facts API returns these as JSON keys — no XML parsing required
- **Bulk seeding**: Use the Company Facts API bulk download (`companyfacts.zip` ~2GB) for initial financial metric population — faster than per-company API calls. Load into DuckDB first, then recompute snapshots onto FalkorDB Company nodes

---

## Pipeline 2: Financial Data APIs (Tier 0–2)

This pipeline covers company-level financial data (Tier 0) and macro-economic indicators (Tier 2) from multiple structured data sources.

### Sources

#### Financial Modeling Prep — Prices, Profiles, Ratios (Tier 0)

| Field | Detail |
|-------|--------|
| **URL** | https://financialmodelingprep.com/ |
| **API** | https://financialmodelingprep.com/api/v3/ |
| **Pricing** | **Free tier**: 250 req/day. **Starter**: $14/mo (10K req/day). **Premium**: $29/mo (unlimited). Annual discounts available |
| **Auth** | API key (free registration) |
| **Format** | JSON |
| **Fetch Method** | REST API. `/profile/{ticker}` for company profile, `/quote/{ticker}` for price, `/ratios/{ticker}` for financial ratios, `/stock-screener` for screening, `/enterprise-values/{ticker}` for valuation |
| **Key Data** | Company profiles (sector, industry, market cap, description, CEO, employees), historical prices, financial ratios (P/E, P/B, ROE, debt/equity), income statement, balance sheet, cash flow, stock screener |
| **Graph Nodes** | `Company` (enrichment), `Industry`, `Sector` |
| **Relationships** | `OPERATES_IN` |
| **Alternatives** | Alpha Vantage (free, 25 req/day; premium $50/mo), Polygon.io ($29/mo starter), Yahoo Finance (unofficial, fragile) |
| **Notes** | Best value for price + fundamental data. The free tier is enough for Phase 0 (50 companies). Starter tier handles Phase 3 scale. Use for company profile seeding, industry/sector classification (GICS), and ongoing price snapshots for paper trading. Financial ratios and time series data written to DuckDB (full history); latest snapshot recomputed onto FalkorDB Company node properties |

#### FRED — Federal Reserve Economic Data (Tier 2)

| Field | Detail |
|-------|--------|
| **URL** | https://fred.stlouisfed.org/ |
| **API** | https://api.stlouisfed.org/fred/ |
| **Pricing** | **Free** (requires API key registration at https://fredaccount.stlouisfed.org/apikeys) |
| **Rate Limit** | 120 req/minute |
| **Format** | JSON, XML |
| **Fetch Method** | REST API. `/fred/series/observations?series_id={id}` for time series data |
| **Key Data** | 816,000+ time series. GDP, inflation, unemployment, interest rates, consumer confidence, housing, manufacturing, trade balance, credit spreads, money supply |
| **Graph Nodes** | `MacroIndicator`, `Region` |
| **Relationships** | `REPORTS_INDICATOR` (Region → MacroIndicator) |
| **Essential Series** | GDP, GDPC1, UNRATE, CPIAUCSL, CPILFESL, FEDFUNDS, DFF, T10YIE, T10Y2Y, DEXUSEU, DEXCHUS, HOUST, UMCSENT, PAYEMS, INDPRO, RSAFS, M2SL, BAMLH0A0HYM2, VIXCLS |
| **Notes** | The best macro data API available. Free, reliable, well-documented. Use as the primary source for all US macro indicators. Supplement with World Bank/IMF for international data |

#### World Bank / IMF — International Economic Data (Tier 2)

| Field | Detail |
|-------|--------|
| **URL** | https://data.worldbank.org/, https://www.imf.org/en/Data |
| **API** | World Bank: https://api.worldbank.org/v2/ (REST). IMF: https://datahelp.imf.org/knowledgebase/articles/667681 (SDMX REST API) |
| **Pricing** | **Free** |
| **Format** | JSON, XML |
| **Fetch Method** | REST API. World Bank: `/country/{iso}/indicator/{indicator}` for time series. IMF: SDMX format, more complex but comprehensive |
| **Key Data** | Country GDP, GDP growth, inflation, trade balance, debt/GDP, FDI, current account, population, exchange rates |
| **Key Indicators** | NY.GDP.MKTP.CD (GDP), NY.GDP.MKTP.KD.ZG (GDP growth), FP.CPI.TOTL.ZG (inflation), NE.TRD.GNFS.ZS (trade % GDP), GC.DOD.TOTL.GD.ZS (debt/GDP) |
| **Graph Nodes** | `Region`, `MacroIndicator` |
| **Relationships** | `REPORTS_INDICATOR`, `TRADES_WITH` |
| **Notes** | Essential for the Macro-Micro Linker agent. Country-level economic data enables "China GDP slows → US import-dependent companies affected" analysis. Start with top 20 trading partners. World Bank API is simpler; IMF has more detailed financial data |

#### BLS — Bureau of Labor Statistics (Tier 2)

| Field | Detail |
|-------|--------|
| **URL** | https://www.bls.gov/developers/ |
| **API** | https://api.bls.gov/publicAPI/v2/timeseries/data/ |
| **Pricing** | **Free** (unregistered: 25 req/day, 10yr history. Registered: 500 req/day, 20yr history) |
| **Auth** | API key (optional but recommended — register at https://data.bls.gov/registrationEngine/) |
| **Format** | JSON |
| **Fetch Method** | POST request with series IDs. Series IDs follow specific formats (e.g., `CES0000000001` for total nonfarm payrolls) |
| **Key Data** | Employment by industry, CPI components, PPI by commodity, import/export price indexes, productivity |
| **Graph Nodes** | `MacroIndicator` |
| **Notes** | Overlaps with FRED for headline numbers, but BLS has more granular industry-level data. Use for sector-specific employment trends |

#### BEA — Bureau of Economic Analysis (Tier 2)

| Field | Detail |
|-------|--------|
| **URL** | https://www.bea.gov/tools/ |
| **API** | https://apps.bea.gov/api/signup/ |
| **Pricing** | **Free** (requires API key) |
| **Format** | JSON, XML |
| **Fetch Method** | REST API. Datasets: NIPA (national accounts), International (trade), Regional (state/metro GDP) |
| **Key Data** | GDP by industry, personal consumption by category, international trade by country/commodity, state GDP |
| **Graph Nodes** | `MacroIndicator`, `Region` |
| **Notes** | Use BEA for trade data between countries (bilateral trade flows, trade deficits). This feeds the `TRADES_WITH` relationship between regions. FRED carries some BEA data, but BEA API has more detail |

### Cadence
- **Daily**: Fundamental data (market cap, P/E, revenue estimates)
- **Weekly**: Full financial statement refresh
- **Daily**: Macro indicators from FRED
- **Daily/Weekly**: Country-level economic data (World Bank, IMF updates as available)

### Pipeline Steps

```
1. Fetch company fundamentals (FMP — Tier 0)
   └── Market cap, P/E, EPS, dividend yield, 52-week range
   └── Write to DuckDB financial_metrics table; recompute Company snapshot properties

2. Fetch financial statements (FMP — Tier 0, quarterly)
   └── Income statement, balance sheet, cash flow
   └── Write each line item to DuckDB financial_metrics table

3. Fetch US macro indicators (FRED — Tier 2)
   └── Federal Funds Rate, CPI, GDP, Unemployment, Consumer Confidence
   └── Treasury yields, housing starts, manufacturing PMI, retail sales
   └── Map to MacroIndicator nodes, link to Region ("United States")

4. Fetch global macro indicators (World Bank, IMF, BLS, BEA — Tier 2)
   └── World Bank API: GDP, inflation, trade data per country
   └── IMF Data API: Economic outlook, country reports
   └── BLS: Detailed labor market data
   └── BEA: GDP components, international trade, personal income
   └── Map to MacroIndicator nodes linked to Region nodes
   └── Create MacroIndicator nodes linked to Region nodes (Region stays identifier-only — see 02-graph-schema.md)

5. Load into FalkorDB
   └── MERGE MacroIndicator nodes (keyed on name+date+region)
   └── MERGE Region nodes (keyed on iso_code)
   └── No LLM needed — structured data, direct Cypher inserts
```

### Key Considerations
- **No LLM cost**: This pipeline is pure structured data → Cypher. No GraphRAG-SDK needed
- **API rate limits**: Batch requests, implement exponential backoff
- **Data quality**: Cross-validate between sources when possible
- **Global data**: World Bank / IMF data is updated less frequently (quarterly/annually). Cache and refresh on schedule
- **Country coverage**: Start with US, expand to G20, then broader as needed
- **FRED as primary**: Use FRED as the single primary US macro source. BLS and BEA add granular detail

---

## Pipeline 3: News (Tier 0)

### Sources

#### News APIs — Marketaux / GNews / NewsAPI

| Field | Detail |
|-------|--------|
| **URL** | https://newsapi.org/, https://www.marketaux.com/, https://gnews.io/ |
| **Pricing** | **NewsAPI**: Free (100 req/day, 1 month history, dev only). Business: $449/mo. **Marketaux**: Free (100 req/day). Standard: $29/mo (10K req/day, 1yr history). **GNews**: Free (100 req/day). Basic: $14/mo |
| **Auth** | API key |
| **Format** | JSON |
| **Fetch Method** | REST API. Query by keyword, company name, ticker. Filter by date, language, source |
| **Key Data** | Headlines, article content (or summary), source, publish date, URL |
| **Graph Nodes** | `NewsArticle` |
| **Relationships** | `MENTIONED_IN` (Company → NewsArticle) |
| **Recommendation** | Start with **Marketaux** — best balance of financial focus, pricing, and historical depth for investment research. GNews as backup. NewsAPI is good but expensive at scale and prohibits commercial use on free tier |
| **Notes** | News is essential for the Data Monitor Agent to detect events and trigger ripple analysis. For Phase 0-1, the free tiers are sufficient |

### Cadence
- **Every 15-30 minutes**: Poll for new articles
- **Dedup**: Skip articles already in graph (by URL hash)

### Pipeline Steps

```
1. Fetch latest articles
   └── Query by company names/tickers for tracked companies
   └── Query by industry keywords
   └── Query for macro news ("fed rate", "gdp", "trade policy")
   └── Query for political/policy news ("congress", "legislation", "tariff", "executive order")

2. Dedup check
   └── Hash article URL → check if article_id exists in graph
   └── Skip if already processed

3. Preprocess with MarkItDown
   └── Convert HTML article → clean Markdown
   └── Strip ads, navigation, boilerplate

4. LLM Analysis (via GraphRAG-SDK or direct OpenAI call)
   └── Extract: mentioned companies, sentiment, impact assessment
   └── Generate: summary, categories, impact_score
   └── Generate: embedding for semantic search

5. Entity resolution
   └── Match company mentions → Company nodes
   └── Disambiguate ("Apple" = AAPL, not the fruit)

6. Load into FalkorDB
   └── CREATE NewsArticle node
   └── MERGE relationships: Company-[:MENTIONED_IN]->NewsArticle
   └── If article mentions supply chain disruption, M&A, etc:
       └── Create/update inter-company relationships
   └── If article mentions legislation, tariffs, sanctions:
       └── Link to Legislation nodes, update AFFECTS relationships
```

### Key Considerations
- **Noise filtering**: Many articles are low-value. Use LLM to score relevance before full processing
- **Duplicate content**: Same story from multiple outlets. Cluster by embedding similarity
- **Cost optimization**: Use GPT-4o-mini for initial classification, GPT-4.1 only for high-impact articles

---

## Pipeline 4: Web Scraping (Tier 1)

### Sources

#### Company Investor Relations Pages & Press Releases (Tier 1)

| Field | Detail |
|-------|--------|
| **URL pattern** | `https://{company}.com/investor-relations` (varies per company). Common subpaths: `/investors`, `/ir`, `/news`, `/press-releases` |
| **Aggregators (optional)** | https://www.prnewswire.com/, https://www.businesswire.com/, https://www.globenewswire.com/ — aggregate press releases across companies |
| **Pricing** | **Free** — all public |
| **Auth** | None |
| **Format** | HTML (scraped), PDF (investor presentations, via MarkItDown) |
| **Fetch Method** | Scrapy for static IR pages. Discover press release URLs from IR index pages (`/press-releases`, `/news-releases`). Use RSS feeds where available (many IR sites expose RSS). Parse PDFs (investor presentations, fact sheets) with MarkItDown |
| **Key Data** | Press releases (product launches, partnerships, executive changes, guidance updates, dividend announcements), investor presentations (strategic roadmaps, segment financials, forward guidance), earnings call dates, special events |
| **Graph Nodes** | `NewsArticle` (for press releases), `Filing` (for investor presentations), `Person` (executive changes), `Company` |
| **Relationships** | `ANNOUNCED` (Company → NewsArticle), `PARTNERS_WITH`, `HAS_EXECUTIVE`, `MENTIONED_IN` |
| **Update Frequency** | Check IR pages daily for new releases. Major companies post several times per week |
| **Python Libraries** | `scrapy`, `feedparser` (RSS), `playwright` (JS-heavy IR pages) |
| **Notes** | **Press releases frequently precede SEC 8-K filings by hours.** A company posts a press release the moment a deal closes or a product launches; the 8-K follows hours or days later. This pipeline captures those signals first. Also captures events that never require an 8-K at all: product announcements, minor partnerships, management commentary, capital markets day presentations. Confidence should be higher than news articles (this is the company speaking directly) but lower than SEC filings (not legally certified). Cross-reference: if a press release describes a partnership, link both companies in the graph. If it describes an executive departure, update `HAS_EXECUTIVE` accordingly |

> **Complementarity with SEC Pipeline**: SEC Pipeline 1 catches 8-K filings (material events that legally require disclosure). This pipeline catches everything else — the non-material-but-still-significant announcements, early signals before the 8-K arrives, and management narrative that provides context to the numbers.

> **Signal types by event category:**
> - **M&A signals**: "Company X and Company Y in strategic discussions" press releases (often weeks before a formal 8-K)
> - **Product launches**: New product lines, market expansion — affects competitive positioning in graph
> - **Executive changes**: CEO/CFO departures often posted as press releases before DEF 14A amendments
> - **Guidance updates**: Mid-quarter guidance revisions outside earnings calls
> - **Partnership/licensing**: SUPPLIES_TO, PARTNERS_WITH edges with higher confidence than 10-K extraction
> - **Capital allocation**: Buyback programs, dividend initiations, equity offerings

#### Company Supply Chain / Relationships

| Field | Detail |
|-------|--------|
| **URL (free)** | https://importyeti.com/ (import/export records), SEC 10-K risk factors + supplier mentions |
| **Pricing** | **ImportYeti**: Free (US customs import data). **FactSet Supply Chain**: Enterprise ($10K+/yr). **Bloomberg SPLC**: Terminal only ($24K/yr) |
| **Fetch Method** | **Primary**: Extract supply chain mentions from 10-K filings using LLM (GraphRAG-SDK entity extraction). Section "Risk Factors" and "MD&A" frequently mention key customers and suppliers. **Secondary**: ImportYeti scraping for import/export data. **Tertiary**: Wikipedia/company websites for major known relationships |
| **Key Data** | Customer-supplier relationships, revenue concentration, geographic supply chain dependencies |
| **Graph Nodes** | `Company` |
| **Relationships** | `SUPPLIES_TO`, `COMPETES_WITH`, `PARTNERS_WITH` |
| **Notes** | **This is the hardest data to get for free and the most valuable for multi-hop analysis.** Companies are legally required to disclose material customer concentrations (>10% of revenue). Supplement with ImportYeti for import/export relationships. The confidence on LLM-extracted relationships should be lower than on structured data. Manual curation of the top 100-200 most important supply chain relationships is worth the effort for Phase 0 (complementing SEC extraction) |

#### Edge Property Extraction Strategy

When creating relationships from 10-K filings, **populate edge properties** to enable nuanced ripple analysis. See [02-graph-schema.md](02-graph-schema.md) § Edge Property Best Practices for the full schema.

##### SUPPLIES_TO Edges

Extract from 10-K sections:
- **Item 1 (Business)** → "Principal Suppliers" or "Principal Customers"
- **Item 1A (Risk Factors)** → "We depend on a single supplier…", "Our largest customer represents X% of revenue"
- **Note 14/15 (Segment Reporting)** → Customer concentration disclosures

LLM extraction prompt:
```
Extract supply chain relationships with these properties:
- product_category: What does the supplier provide? (e.g., "EUV lithography machines")
- dependency_level: "critical" if SEC filing uses terms like "sole source", "single supplier", 
  "critical dependency", or "no alternative"; "important" if "significant supplier"; 
  "optional" otherwise
- is_sole_source: true if filing explicitly states "sole source" or "only supplier"
- revenue_pct: If filing states "X% of our revenue from Customer Y", extract X
- contract_value_usd: If annual contract value is disclosed, extract it
- geographic_risk: Country where supplier is headquartered (for geopolitical risk)

Source: 10-K accession number [accession], page [page]
Confidence: 0.85 (LLM extraction from filing text)
Last_confirmed: [filing date]
```

##### COMPETES_WITH Edges

Extract from 10-K **Item 1 (Business) → Competition** section:

LLM extraction prompt:
```
Extract competitive relationships with these properties:
- market_segment: What market do they compete in? (e.g., "high-end data center GPUs")
- intensity: "direct" if described as "primary competitor"; "partial" if competing 
  in some segments but not others; "emerging" if described as "emerging threat"
- market_share_a / market_share_b: If market shares are disclosed, extract them
- differentiation: How do they compete? ("price", "performance", "ecosystem", "brand")
- threat_level: "existential" if described as major threat, "significant" if serious 
  competitor, "moderate" if mentioned among many

Source: 10-K accession number [accession]
Confidence: 0.75 (LLM extraction - competition sections are more subjective)
Last_confirmed: [filing date]
```

##### HAS_EXECUTIVE / HAS_BOARD_MEMBER Edges

Extract from **DEF 14A (Proxy Statement)**:

- `compensation_usd`: From "Summary Compensation Table" (structured table - high confidence)
- `stock_ownership_pct`: From "Beneficial Ownership" section
- `is_independent`: From "Board of Directors" section (look for "independent" designation)
- `committee`: From committee membership tables

**Automation strategy**: DEF 14A has **tables** that can be parsed structurally (not LLM extraction). Use a table extraction library (e.g., `camelot-py`) for higher accuracy.

##### Confidence Scoring by Source

| Extraction Method | Base Confidence | Rationale |
|-------------------|-----------------|-----------|
| Company Facts API field | 0.95–1.0 | Machine-readable, authoritative |
| SEC table extraction | 0.90–0.95 | Structured but OCR errors possible |
| 10-K "Principal Suppliers" LLM extraction | 0.80–0.90 | Disclosed requirement, high signal |
| 10-K "Risk Factors" LLM extraction | 0.70–0.85 | Narrative, some interpretation needed |
| News article LLM extraction | 0.60–0.75 | Secondary source, less authoritative |
| Wikipedia / public databases | 0.50–0.70 | Crowd-sourced, needs verification |

**Corroboration boost**: If the same relationship appears in multiple sources (e.g., 10-K + news + ImportYeti), increase confidence by 0.05–0.10.

### Targets
- **Company IR pages + press releases**: Daily scan for new releases. RSS feeds preferred (fast, low bandwidth). Fall back to HTML scraping of press release index pages
- **Investor presentations**: Quarterly earnings presentations (PDFs), capital markets day decks, fact sheets. MarkItDown converts to Markdown for GraphRAG-SDK extraction
- **Supply chain databases**: Public data on supplier/customer relationships (ImportYeti)
- **Industry reports**: Publicly available market research
- **Wikipedia/Wikidata**: Board member info, company relationships

### Cadence
- **Daily**: IR page scan for new press releases, RSS feed polling
- **Weekly**: Re-check investor presentation pages for new PDFs
- **On-demand**: Add new scraping targets as needed

### Pipeline Steps

```
1. Discover new content
   └── Poll RSS feeds for tracked companies (fast path)
   └── Fall back: scrape /press-releases index page for new URLs
   └── Compare against already-processed URL hashes (ingestion.db)

2. Fetch and classify content
   └── Press release (HTML) → MarkItDown → Markdown
   └── Investor presentation (PDF) → MarkItDown → Markdown
   └── LLM classification: event type (product launch / M&A / exec change / guidance / partnership)

3. Extract via GraphRAG-SDK
   └── Entities and relationships from unstructured content
   └── Cross-reference: if partnership mentioned, look up both companies in graph
   └── If exec change: update HAS_EXECUTIVE relationship

4. Reconcile with SEC pipeline
   └── If press release → check if a matching 8-K exists (within 48 hrs)
   └── If yes: link NewsArticle to Filing (press release is the early signal, 8-K is the authoritative record)
   └── If no 8-K after 5 days: flag as non-material event (still valuable)

5. Entity resolution + Load into FalkorDB
```

---

## Pipeline 5: Manual Uploads (Tier 0)

### Interface
- CLI command: `python -m cli upload <file_path>`
- Supports: PDF, DOCX, PPTX, XLSX, TXT, HTML

### Pipeline Steps

```
1. User provides file path via CLI
2. MarkItDown converts to Markdown
3. User optionally specifies: related company ticker, document type
4. GraphRAG-SDK extracts entities and relationships
5. Entity resolution + Load into FalkorDB
6. Confirmation: "Processed <filename>: extracted N entities, M relationships"
```

---

## Pipeline 6: Congressional Investment Disclosures (Tier 1)

### Sources

#### Congressional Disclosures (STOCK Act)

| Field | Detail |
|-------|--------|
| **URL (raw)** | https://disclosures-clerk.house.gov/FinancialDisclosure (House), https://efdsearch.senate.gov/search/ (Senate) |
| **URL (aggregated)** | https://www.capitoltrades.com/, https://www.quiverquant.com/congresstrading |
| **API** | **Quiver Quant**: https://api.quiverquant.com/ (paid, ~$10-30/mo). **House/Senate**: No API — HTML scraping or PDF parsing |
| **Pricing** | **Raw data**: Free (public records). **Capitol Trades**: Free website, premium features behind paywall. **Quiver Quant API**: ~$10-30/mo |
| **Format** | PDF (Financial Disclosure Reports), HTML (search results) |
| **Fetch Method** | **Recommended**: Scrape raw data from House Clerk and Senate EFD portals. Use MarkItDown for PDF → markdown conversion. Alternatively, use Quiver Quant API for pre-parsed data (easier but adds dependency). Capitol Trades for manual validation |
| **Key Data** | Legislator name, transaction type (buy/sell/exchange), asset description, transaction date, notification date, amount range, filing URL |
| **Graph Nodes** | `Legislator`, `CongressionalTrade` |
| **Relationships** | `DISCLOSED_TRADE` (Legislator → CongressionalTrade), `INVOLVES` (CongressionalTrade → Company), `MEMBER_OF` (Legislator → Committee) |
| **Update Frequency** | Members must disclose within 45 days (often late). New disclosures daily |
| **Notes** | For early phases, use Quiver Quant API or scrape Capitol Trades. For production, build a parser for the raw disclosures to eliminate third-party dependency. Cross-referencing trades with committee assignments is where the real value lies |

#### Congressional Committee Assignments (Tier 1)

| Field | Detail |
|-------|--------|
| **URL** | https://www.congress.gov/, https://clerk.house.gov/committee-reports, https://www.senate.gov/committees/ |
| **API** | https://api.congress.gov/v3/ (Congress.gov API, free, requires API key registration at https://api.congress.gov/sign-up/) |
| **Rate Limit** | 5,000 req/hour |
| **Format** | JSON, XML |
| **Fetch Method** | REST API. `/member` for legislator info, `/committee` for committee data. Also available via `unitedstates/congress-legislators` GitHub repo (YAML, updated regularly) |
| **Key Data** | Legislator bio, party, state, committee memberships, subcommittee assignments |
| **Graph Nodes** | `Legislator` (enrichment), `Committee` (new node type or property) |
| **Relationships** | `MEMBER_OF` (Legislator → Committee) |
| **Alternative** | https://github.com/unitedstates/congress-legislators — static YAML files, includes historical data back to 1789 |
| **Notes** | Essential for connecting Congressional trades to their committee oversight areas. A trade by an Armed Services Committee member in a defense contractor is far more significant than a random buy. The GitHub repo is the easiest starting point |

### Cadence
- **Daily**: Check for new disclosures (filings are due within 30-45 days of trade)
- **Backfill**: Historical data load (available from 2012 under STOCK Act)

### Pipeline Steps

```
1. Fetch new disclosures
   └── Scrape or API-fetch from Senate EFDS / House clerk / Capitol Trades
   └── Parse PDF disclosures (MarkItDown for PDF → markdown if needed)
   └── Extract structured fields: legislator, transaction date, asset, amount range, type

2. Entity resolution
   └── Match legislator name → Legislator node (by bioguide_id or name match)
   └── Match asset description → Company node (ticker extraction from asset name)
   └── Handle non-stock assets: options, bonds, crypto (store but may not link to Company)

3. Load into FalkorDB
   └── MERGE Legislator node (keyed on bioguide_id)
   └── CREATE CongressionalTrade node (keyed on disclosure_id)
   └── CREATE relationships: Legislator-[:DISCLOSED_TRADE]->CongressionalTrade
   └── CREATE relationships: CongressionalTrade-[:INVOLVES]->Company
   └── Update Legislator committee assignments (from congress.gov API)
```

### Key Considerations
- **Disclosure delay**: Trades are disclosed 30-45 days after execution. Factor this into analysis
- **Asset matching**: Description text like "Apple Inc (AAPL)" is usually clear, but some filings use generic descriptions
- **Spousal trades**: Track `owner` field ("self" vs "spouse" vs "dependent")
- **Committee overlap detection**: Cross-reference `SERVES_ON_COMMITTEE` with traded companies' industries — this is where the agents find alpha
- **No LLM cost for structured aggregator data**: Capitol Trades / Quiver provide pre-parsed data

---

## Pipeline 7: Institutional Holdings — 13F (Tier 1)

### Sources

#### SEC EDGAR 13F — Institutional Holdings

| Field | Detail |
|-------|--------|
| **URL** | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=13F |
| **API** | Same EDGAR API: `data.sec.gov/submissions/CIK{cik}.json` filtered for form type `13F-HR`. Also: https://efts.sec.gov/LATEST/search-index?q=&forms=13F-HR |
| **Pricing** | **Free** |
| **Format** | XML (information table), HTML |
| **Fetch Method** | Download 13F-HR filings. Parse the XML information table for holdings (CUSIP, shares, value). Map CUSIP to ticker using OpenFIGI (below) |
| **Key Data** | Institutional holder (fund name, CIK), positions (CUSIP, shares, value, put/call), filing date, quarter |
| **Graph Nodes** | `InstitutionalHolder`, `Company` |
| **Relationships** | `HOLDS_POSITION` (InstitutionalHolder → Company via CUSIP) |
| **Update Frequency** | Quarterly (45 days after quarter end). ~5,000 institutions file |
| **Python Libraries** | `sec-edgar-downloader`, custom XML parser |
| **Notes** | Critical for "following smart money." 13F data is 45 days stale but shows positioning trends. Cross-reference with Congressional trades for confirmation patterns. Parse the XML information table, not the HTML cover page |

#### OpenFIGI — CUSIP / ISIN / Ticker Mapping (Tier 2)

| Field | Detail |
|-------|--------|
| **URL** | https://www.openfigi.com/ |
| **API** | https://api.openfigi.com/v3/mapping |
| **Pricing** | **Free** (unauthenticated: 5 req/min, 10 jobs/req. Authenticated: 20 req/min, 100 jobs/req) |
| **Auth** | API key (free registration) |
| **Format** | JSON |
| **Fetch Method** | POST with identifier type and value. Map CUSIP → ticker, ISIN → ticker, etc. |
| **Key Data** | CUSIP, ISIN, ticker, exchange, security type, company name |
| **Notes** | **Essential for 13F parsing.** 13F filings report holdings by CUSIP, not ticker. OpenFIGI maps CUSIP to ticker/company. Without this, you can't link 13F data to companies in the graph. Cache the mapping table locally |

#### WhaleWisdom (Alternative)

| Field | Detail |
|-------|--------|
| **URL** | https://whalewisdom.com/ |
| **Notes** | Third-party pre-parsed 13F data with quarter-over-quarter diffs. Useful for validation and spot-checking, but the raw EDGAR data is authoritative |

### Cadence
- **Quarterly**: 13F filings are due 45 days after quarter end
- **Backfill**: Load 2-3 years of historical 13F data for trend analysis

### Pipeline Steps

```
1. Fetch 13F filing index
   └── GET https://data.sec.gov/submissions/CIK{cik}.json for tracked institutions
   └── Filter for form type "13F-HR"
   └── Skip already-processed accession numbers

2. Parse 13F holdings table (XML/HTML)
   └── Extract: company name, CUSIP, ticker, shares, value, put/call indicator
   └── Map CUSIP → ticker using OpenFIGI API (cache results locally)

3. Compute quarter-over-quarter changes
   └── Compare against previous quarter's holdings
   └── Flag: new positions, sold-out positions, significant increases/decreases
   └── Calculate change_pct for each position

4. Entity resolution
   └── Match holding company name → Company node (by ticker or CUSIP)
   └── Match institutional holder → InstitutionalHolder node (by CIK)

5. Load into FalkorDB
   └── MERGE InstitutionalHolder node (keyed on CIK)
   └── MERGE HOLDS_POSITION relationship (keyed on holder+company+quarter)
   └── MERGE Filing node for the 13F filing itself
   └── CREATE InstitutionalHolder-[:FILED_13F]->Filing relationship
```

### Key Considerations
- **Scale**: ~5,000 institutional filers with ~3,000 holdings each = ~15M position records per quarter
- **No LLM cost**: Purely structured data → direct Cypher inserts
- **Delay**: 13F data is 45-days old by the time it's filed. Still valuable for trend analysis
- **Top holders**: Prioritize the largest 500 filers (Berkshire, Bridgewater, etc.) for initial load
- **Aggregation**: Consider aggregating to answer "what % of a company is held by institutions?"

---

## Pipeline 8: Government & Policy Data (Tier 2)

### Sources

#### Legislation & Bill Tracking — Congress.gov / GovTrack / ProPublica

| Field | Detail |
|-------|--------|
| **URL** | https://www.congress.gov/, https://www.govtrack.us/, https://projects.propublica.org/api-docs/congress-api/ |
| **API** | **Congress.gov**: https://api.congress.gov/v3/bill (official). **GovTrack**: https://www.govtrack.us/developers/api. **ProPublica**: https://api.propublica.org/congress/v1/ |
| **Pricing** | **All free**. Congress.gov requires API key. ProPublica requires API key |
| **Rate Limit** | Congress.gov: 5,000 req/hr. ProPublica: 5,000 req/day |
| **Format** | JSON, XML |
| **Fetch Method** | REST API. Query bills by keyword, committee, sponsor, status. Get bill full text, actions, votes, cosponsors |
| **Key Data** | Bill number, title, summary, full text, status (introduced → committee → passed), sponsors, cosponsors, committee referral, related bills |
| **Graph Nodes** | `Legislation` |
| **Relationships** | `SPONSORED_BY` (Legislator → Legislation), `AFFECTS` (Legislation → Industry/Company) |
| **Notes** | Critical for the "Legislation → Industry → Company" impact chain. LLM maps bill content to affected industries. Congress.gov is authoritative. GovTrack adds prognosis. ProPublica adds vote data. Use keywords to monitor for bills affecting industries in the graph |

#### Federal Government Contracts — USASpending.gov

| Field | Detail |
|-------|--------|
| **URL** | https://www.usaspending.gov/, https://www.fpds.gov/ |
| **API** | https://api.usaspending.gov/ (comprehensive REST API) |
| **Pricing** | **Free** |
| **Format** | JSON |
| **Fetch Method** | REST API. `/api/v2/search/spending_by_award/` for contract search. `/api/v2/recipient/` for company lookup. Filter by agency, NAICS code, date range, award amount. Bulk download available |
| **Key Data** | Contract recipient (company name, DUNS/UEI), awarding agency, contract value, period of performance, NAICS code, description |
| **Graph Nodes** | `GovernmentContract`, `Company` |
| **Relationships** | `AWARDED_CONTRACT` (Company ← GovernmentContract) |
| **Notes** | Defense contractors, IT services companies, and healthcare companies derive significant revenue from government contracts. A new $500M contract award is a material event. Entity resolution between USASpending company names and EDGAR names is non-trivial — use DUNS/UEI numbers where available |

### Cadence
- **Daily**: Congress.gov for bill status changes
- **Weekly**: USAspending.gov for new contract awards
- **On-demand**: Major tariff or trade policy announcements

### Pipeline Steps

```
1. Legislation pipeline
   └── Fetch active bills from Congress.gov API (filter by committees relevant to markets)
   └── Track status changes (introduced → committee → passed → signed)
   └── LLM analysis: summarize market impact, identify affected industries
   └── MERGE Legislation node, CREATE AFFECTS relationships to Industries
   └── Link sponsors: Legislator-[:SPONSORED]->Legislation

2. Government contract pipeline
   └── Fetch new awards from USAspending.gov API
   └── Filter for contracts > $1M value
   └── Match recipient company → Company node (by DUNS/CAGE code or name)
   └── MERGE GovernmentContract node, CREATE Company-[:AWARDED_CONTRACT]->GovernmentContract

3. Trade policy pipeline
   └── Monitor USTR announcements, tariff notices
   └── LLM analysis: identify affected countries, industries, and specific companies
   └── CREATE/update Region-[:HAS_POLICY]->Legislation
   └── CREATE Legislation-[:AFFECTS]->Region for tariffs targeting specific countries
```

### Key Considerations
- **Volume management**: Congress introduces ~10,000 bills per session; filter to finance/market-relevant bills using committee + keyword heuristics
- **LLM usage**: Medium — needed for impact analysis of legislation, not for structured contract data
- **Entity resolution**: Company names in USAspending often differ from SEC names ("LOCKHEED MARTIN CORP" vs "Lockheed Martin Corporation"). Fuzzy match required
- **Lobbying data**: Future addition (Tier 4) — connects companies to their lobbying spend on specific bills

---

## Tier 3 — Enhancement Sources (Future Pipelines)

These add depth and breadth to the graph. Build only after Tiers 0-2 are working. Each source below would get its own pipeline when prioritized for implementation (Phase 5+).

---

### 3.1 SEC Insider Trading (Forms 3, 4, 5)

| Field | Detail |
|-------|--------|
| **URL** | https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4 |
| **API** | EDGAR API, filter for forms 3, 4, 5. Also: https://efts.sec.gov/LATEST/search-index?forms=4 |
| **Pricing** | **Free** |
| **Format** | XML (structured ownership report) |
| **Fetch Method** | Parse XML ownership reports. Each filing has reporting owner (insider), issuer (company), transaction details (buy/sell, shares, price, date) |
| **Key Data** | Insider name, title (CEO, CFO, Director), transaction type, shares, price, ownership after transaction |
| **Graph Nodes** | `Person`, `Company` |
| **Relationships** | `HAS_EXECUTIVE` (enrichment), insider trade as edge property or separate node |
| **Notes** | Insider buying is a stronger signal than insider selling (insiders sell for many reasons, but they buy for one reason). Cross-reference with 13F and Congressional data for multi-signal confirmation. The XML is well-structured — no LLM extraction needed |

---

### 3.2 SEC Schedule 13D/G — Activist / Large Ownership Positions

| Field | Detail |
|-------|--------|
| **URL** | EDGAR, filter for forms SC 13D, SC 13G |
| **Pricing** | **Free** |
| **Format** | HTML/text (less structured than Form 4) |
| **Fetch Method** | Download filings, parse for ownership percentage, filer identity, stated purpose |
| **Key Data** | Holder name, ownership percentage (>5%), stated purpose (passive vs. activist), company |
| **Graph Nodes** | `InstitutionalHolder` or `Person`, `Company` |
| **Relationships** | `OWNS_STAKE_IN` (with purpose property) |
| **Notes** | Activist positions (13D) are significant events — someone is buying 5%+ and plans to influence company direction. 13G is passive but still shows large concentrated positions |

---

### 3.3 SEC Proxy Statements (DEF 14A) — Executive Compensation & Governance

| Field | Detail |
|-------|--------|
| **URL** | EDGAR, filter for form DEF 14A |
| **Pricing** | **Free** |
| **Format** | HTML |
| **Fetch Method** | Download and parse proxy statements. LLM extraction for executive names, compensation, board members, shareholder proposals |
| **Key Data** | Named executive officers, compensation breakdown, board of directors, shareholder proposals, voting results |
| **Graph Nodes** | `Person` (executives, directors), `Company` |
| **Relationships** | `HAS_EXECUTIVE`, `HAS_BOARD_MEMBER` |
| **Notes** | Useful for mapping the executive/board network. Directors who sit on multiple boards create relationship edges between companies. Executive compensation outliers can signal governance issues |

---

### 3.4 Patent Data — USPTO / Google Patents

| Field | Detail |
|-------|--------|
| **URL** | https://developer.uspto.gov/, https://patents.google.com/ |
| **API** | USPTO: https://developer.uspto.gov/api-catalog (PatentsView API). Google Patents: No official API (Public Datasets on BigQuery) |
| **Pricing** | **Free** |
| **Format** | JSON (PatentsView), BigQuery (Google) |
| **Fetch Method** | PatentsView API: query by assignee (company), CPC classification, date range. `/patents/query` endpoint |
| **Key Data** | Patent title, abstract, classification, assignee, filing date, grant date, citations |
| **Graph Nodes** | `Patent` (new node type) |
| **Relationships** | `HOLDS_PATENT` (Company → Patent), `CITES_PATENT` (Patent → Patent) |
| **Notes** | Patent activity signals R&D direction. Cross-reference with industry trends. A company filing many patents in "quantum-resistant cryptography" supports a thesis about PQC readiness. Volume is high — focus on specific technology areas relevant to active theses |

---

### 3.5 Commodity Prices — FRED / EIA / World Bank

| Field | Detail |
|-------|--------|
| **URL** | https://www.eia.gov/opendata/ (Energy), FRED (metals, agriculture via series), https://www.worldbank.org/en/research/commodity-markets |
| **API** | EIA: https://api.eia.gov/v2/ (API key required, free). FRED: covered in Pipeline 2. World Bank: CSV download |
| **Pricing** | **All free** |
| **Key Data** | WTI crude, Brent, natural gas, gold, silver, copper, lithium, rare earths, agricultural commodities |
| **Graph Nodes** | `Commodity` |
| **Relationships** | `DEPENDS_ON` (Company/Industry → Commodity) |
| **Notes** | Commodity price movements ripple through supply chains. An airline depends on jet fuel (oil). A battery maker depends on lithium. Map these dependencies in the graph for thesis-driven research |

---

### 3.6 Federal Register — Regulations & Executive Orders

| Field | Detail |
|-------|--------|
| **URL** | https://www.federalregister.gov/ |
| **API** | https://www.federalregister.gov/developers/documentation/api/v1 |
| **Pricing** | **Free** |
| **Format** | JSON |
| **Fetch Method** | REST API. Search by keyword, agency, document type, date. `/documents.json?conditions[term]=semiconductor` |
| **Key Data** | Document title, abstract, agency, type (rule, proposed rule, notice, executive order), effective date, full text URL |
| **Graph Nodes** | `Legislation` (regulations overlap with legislation in function) |
| **Relationships** | `AFFECTS` (Regulation → Industry) |
| **Notes** | Regulations often have bigger market impact than legislation. EPA rules affect energy. FDA rules affect pharma. FCC rules affect telecom. The API is excellent — well-documented and reliable. Monitor for final rules and executive orders affecting portfolio sectors |

---

### 3.7 Earnings Call Transcripts

| Field | Detail |
|-------|--------|
| **URL** | https://seekingalpha.com/earnings/earnings-call-transcripts, https://www.fool.com/earnings-call-transcripts/ |
| **API** | No free API for full transcripts. **FMP** has transcripts endpoint (premium tier, $29/mo) |
| **Pricing** | **Free** (scraping, Terms of Service limitations). **FMP Premium**: $29/mo includes transcripts |
| **Fetch Method** | FMP API: `/earning_call_transcript/{ticker}`. Alternatively, SEC 8-K filings sometimes include transcripts as exhibits |
| **Key Data** | Full earnings call text with management commentary, analyst Q&A, forward guidance language |
| **Graph Nodes** | `Filing` or `Transcript` (as property of a Filing) |
| **Notes** | Earnings calls contain forward-looking statements that reveal management's view of supply chain, competition, and market conditions. LLM extraction can identify sentiment shifts, guidance changes, and competitor mentions. FMP premium is the cleanest source |

---

### 3.8 Short Interest Data — FINRA / Nasdaq

| Field | Detail |
|-------|--------|
| **URL** | https://www.nasdaqtrader.com/trader.aspx?id=shortintpubsch, https://www.finra.org/finra-data/browse-catalog/short-interest/data |
| **Pricing** | **Free** (delayed). Real-time short interest from vendors costs $100+/mo |
| **Fetch Method** | Download FINRA short interest files. FMP includes short interest in their API (premium) |
| **Key Data** | Ticker, short interest (share count), settlement date, days to cover |
| **Graph Nodes** | `Company` (short interest as snapshot metric) |
| **Notes** | High short interest + positive thesis = short squeeze potential. High short interest confirms bearish sentiment. Bi-monthly is sufficient for the system's time horizon (weeks to months) |

---

### 3.9 ETF Holdings Data — ETF.com / SEC N-PORT

| Field | Detail |
|-------|--------|
| **URL** | https://www.etf.com/, SEC N-PORT filings |
| **Pricing** | **Free** (N-PORT). ETF providers publish daily holdings on their websites |
| **Fetch Method** | Parse N-PORT filings (XML) from EDGAR for complete quarterly holdings. Scrape daily holdings from ETF provider websites (iShares, Vanguard, SPDR) for key ETFs |
| **Key Data** | ETF name, holdings (ticker, weight, shares), AUM, expense ratio |
| **Graph Nodes** | `InstitutionalHolder` (ETFs are holders), `Company` |
| **Relationships** | `HOLDS_POSITION` |
| **Notes** | ETF flows indicate sector rotation. If thesis predicts "cybersecurity demand increases," check if cybersecurity ETFs (HACK, CIBR, BUG) are seeing inflows. Also useful for identifying basket effects — when an ETF rebalances, all holdings move |

---

### 3.10 Options Flow / Unusual Activity

| Field | Detail |
|-------|--------|
| **URL** | https://unusualwhales.com/, https://www.barchart.com/options/unusual-activity |
| **Pricing** | **Unusual Whales**: ~$57/mo (Congressional + options data). **Barchart**: $50/mo+ |
| **Key Data** | Large options trades, unusual volume, open interest changes, Congressional trades (Unusual Whales includes this) |
| **Notes** | Tier 3 because options flow is noisy and requires significant expertise to interpret. However, very large unusual options activity (10x+ normal volume) can signal informed trading. Unusual Whales also bundles Congressional trading data, making it a potential 2-for-1 source |

---

### 3.11 Dark Pool / Off-Exchange Volume — FINRA ATS

| Field | Detail |
|-------|--------|
| **URL** | https://otctransparency.finra.org/otctransparency/AtsIssueData |
| **API** | FINRA ATS Transparency Data: https://otctransparency.finra.org/ (downloadable reports). No REST API — weekly file downloads |
| **Pricing** | **Free** |
| **Format** | CSV (weekly reports) |
| **Fetch Method** | Download weekly ATS (Alternative Trading System) issue-level data from FINRA. Each report shows shares traded per ticker, per ATS venue, with a 2-4 week delay. Parse CSV, aggregate by ticker |
| **Key Data** | Ticker, ATS venue (e.g., Citadel Connect, Virtu, UBS), shares traded, trade count, reported week |
| **Graph Nodes** | `Company` (dark pool volume as DuckDB metric) |
| **Notes** | Unusually high dark pool volume relative to lit exchange volume can signal institutional accumulation or distribution before it shows up in 13F filings (which are 45 days delayed). Quiver tracks this — useful for cross-validation. The data is free but delayed 2-4 weeks, which is acceptable for this platform's time horizon. Compare dark pool % against historical baseline for each ticker to detect anomalies |

---

## Tier 4 — Aspirational Sources

Don't build these until the system proves its value through Phase 7 feedback.

> **Contrarian-at-extremes principle**: Several Tier 4 sources (social media, Google Trends, CNBC picks) are individually noisy and low-signal. Their value lies in **contrarian signals at extremes** — when public attention on a stock hits an extreme, the easy money has already been made:
>
> - **Extreme bullish attention** (all-time-high search volume, wall-to-wall CNBC coverage, trending on Reddit) → everyone who's going to buy has already bought → the marginal buyer is exhausted → often coincides with a local top
> - **Extreme bearish attention** (panic selling, "is X going to zero?" headlines) → oversold conditions → often coincides with a local bottom
>
> These signals become powerful when **cross-referenced with the graph's structured data**:
> ```
> Google Trends for "Bitcoin" hits all-time high
>   + Congressional trades show senators SELLING crypto positions
>   + 13F data shows institutions reducing MSTR/COIN exposure
>   + Dark pool volume shows heavy off-exchange selling
>   = Multi-signal confirmation: "smart money exiting while retail piles in"
>   = High-confidence contrarian bearish signal
> ```
> On their own, these are coin-flip indicators. Combined with the graph, they add a sentiment layer that confirms or contradicts a thesis. That's why they're Tier 4 — build them only after the graph has enough structured data to give them context.

---

### 4.1 Alternative Data — Satellite, Credit Cards, App Analytics

| Field | Detail |
|-------|--------|
| **Sources** | Orbital Insight (satellite), Earnest Research (credit cards), Apptopia (app downloads), SimilarWeb (web traffic) |
| **Pricing** | **$10K–$200K/year per dataset** |
| **Notes** | This is what hedge funds pay for. Satellite imagery of parking lots predicts retail earnings. Credit card data predicts consumer spending. The pricing is prohibitive for a solo investor. Only consider after the system demonstrates clear value from public data sources |

---

### 4.2 Social Media Sentiment — Reddit / Twitter (X) / StockTwits

| Field | Detail |
|-------|--------|
| **URL** | https://www.reddit.com/dev/api/, X API (https://developer.x.com/), https://api.stocktwits.com/ |
| **Pricing** | **Reddit**: Free (OAuth, 60 req/min). **X**: Free tier severely limited (2023+); Basic: $100/mo. **StockTwits**: Free (limited) |
| **Fetch Method** | Reddit: PRAW library. X: official API or academic access. StockTwits: REST API |
| **Key Data** | Mentions, sentiment, volume of discussion, trending tickers |
| **Notes** | Social sentiment is noisy and mostly useful as a contrarian indicator or for detecting retail-driven momentum (meme stocks). Low priority because the system is designed for fundamental/structural analysis, not sentiment trading |

---

### 4.3 Lobbying Disclosures — Senate LDA

| Field | Detail |
|-------|--------|
| **URL** | https://lda.senate.gov/system/public/ |
| **API** | https://lda.senate.gov/api/ (REST API) |
| **Pricing** | **Free** |
| **Format** | JSON |
| **Fetch Method** | REST API. Query by registrant (lobbyist firm), client (company), issue area, date |
| **Key Data** | Client (who's lobbying), registrant (lobbying firm), issue area, specific bills lobbied on, amount spent |
| **Graph Nodes** | `Company` (client), `Legislation` (bills lobbied on) |
| **Relationships** | `LOBBIES_FOR` (Company → Legislation) |
| **Notes** | If a company is spending millions lobbying on a specific bill, they expect it to materially affect their business. Cross-reference with Congressional committee assignments and trades for powerful correlation. Free and well-structured API, but parsing company names requires entity resolution |

---

### 4.4 International Trade Data — Census / UN Comtrade

| Field | Detail |
|-------|--------|
| **URL** | https://www.census.gov/foreign-trade/data/ (US Census), https://comtradeplus.un.org/ (UN Comtrade) |
| **API** | Census: https://api.census.gov/data/timeseries/intltrade/. Comtrade: https://comtradeapi.un.org/ |
| **Pricing** | **Free** (Census). Comtrade: Free (limited), Premium $600/yr |
| **Key Data** | Bilateral trade flows by commodity (HS code), country, value, quantity |
| **Notes** | Useful for thesis-driven research involving trade policy. "What happens if US tariffs on Chinese goods increase?" — the trade data shows exactly which commodities and which dollar amounts are at stake |

---

### 4.5 Corporate Bond / Credit Data — FRED / TRACE

| Field | Detail |
|-------|--------|
| **URL** | FRED (credit spreads), FINRA TRACE (bond transactions) |
| **Pricing** | FRED: **Free**. TRACE: complex access |
| **Key Data** | Credit spreads (investment grade, high yield), individual bond prices, CDS spreads |
| **Notes** | Credit markets often lead equity markets. Widening credit spreads signal stress before stock prices react. FRED has the key aggregate series (BAMLH0A0HYM2 for high yield spread, BAMLC0A0CM for investment grade). Individual company bond data is harder to access |

---

### 4.6 Crypto / Digital Asset Data — CoinGecko / CoinMarketCap

| Field | Detail |
|-------|--------|
| **URL** | https://www.coingecko.com/api/documentation, https://coinmarketcap.com/api/ |
| **Pricing** | **CoinGecko**: Free (30 req/min). Pro: $129/mo. **CoinMarketCap**: Free (333 req/day). Hobbyist: $29/mo |
| **Key Data** | Crypto prices, market cap, volume, exchange data, DeFi metrics |
| **Notes** | Only relevant for crypto-related theses (e.g., "Bitcoin crashes, what stocks are affected?"). Not core to the platform, but valuable for thesis-driven research involving crypto-exposed companies (MSTR, COIN, MARA, etc.). Free tiers are sufficient |

---

### 4.7 Google Search Trends

| Field | Detail |
|-------|--------|
| **URL** | https://trends.google.com/ |
| **API** | No official API. Use `pytrends` library (unofficial Python wrapper) |
| **Pricing** | **Free** |
| **Format** | JSON (via pytrends) |
| **Fetch Method** | `pytrends` library: query interest over time by keyword/ticker, geographic breakdown, related queries, rising queries. Rate-limited — use delays between requests |
| **Key Data** | Relative search interest (0-100 scale) over time for company names, tickers, industry terms. Geographic distribution of interest. Related and rising queries |
| **Graph Nodes** | `Company` (search interest stored in DuckDB, not FalkorDB) |
| **Notes** | Retail attention indicator. A spike in Google searches for a company often precedes retail buying pressure. Most useful as a contrarian indicator — extreme search volume on a stock often coincides with a local top. Low signal-to-noise ratio; useful only when combined with other signals. Quiver tracks this — useful for cross-validation |

---

### 4.8 CNBC / Financial Media Stock Picks

| Field | Detail |
|-------|--------|
| **URL** | https://www.cnbc.com/, https://madmoney.thestreet.com/ |
| **API** | No official API. Scrape or use RSS feeds |
| **Pricing** | **Free** (scraping) |
| **Fetch Method** | Scrape CNBC "Mad Money" stock picks, analyst upgrades/downgrades mentioned on air, "Fast Money" final trades. RSS feeds for CNBC markets section |
| **Key Data** | Stock ticker mentioned, show/segment, analyst or host, buy/sell/hold recommendation, date |
| **Graph Nodes** | `NewsArticle` (media mention as a news event) |
| **Notes** | Financial media mentions create short-term retail trading pressure. Historically a contrarian indicator at extremes — heavy CNBC coverage of a stock often signals it's already priced in. Low priority because the system focuses on structural/fundamental analysis, not media-driven momentum. Quiver tracks this — useful for cross-validation |

---

### 4.9 Corporate Flight Tracking — FAA / ADS-B

| Field | Detail |
|-------|--------|
| **URL** | https://www.adsbexchange.com/, https://opensky-network.org/ |
| **API** | **ADS-B Exchange**: API available (paid, ~$10/mo+). **OpenSky Network**: Free API (academic/research use) — https://openskynetwork.github.io/opensky-api/ |
| **Pricing** | **OpenSky**: Free (non-commercial). **ADS-B Exchange**: ~$10/mo. **FlightAware Firehose**: Enterprise pricing |
| **Fetch Method** | Track tail numbers of corporate jets registered to public companies or their executives. Monitor flight patterns: unusual C-suite visits to other company HQs (M&A signal), trips to Washington DC (regulatory signal), trips to Omaha (Buffett meeting) |
| **Key Data** | Aircraft tail number, owner (company/executive), origin, destination, flight time, frequency |
| **Graph Nodes** | No direct graph node — signals would enrich `Company` or `Person` nodes |
| **Notes** | Deep alternative data. Tracking corporate jets has historically predicted M&A announcements (CEO of acquirer flying to target company HQ). Requires mapping tail numbers to companies (FAA N-number registry is public). High effort for occasional signal. Quiver tracks this — useful for cross-validation. Only consider if the system is producing value from all other tiers first |

---

## Entity Resolution Strategy

Entity resolution is critical for a graph with 5,000+ companies, 600+ legislators, and 1,000+ institutional holders. Without it, "Apple Inc.", "Apple", "AAPL", and "Apple Inc" would create 4 separate nodes.

> **Why this matters for investment insights**: Entity resolution errors compound across graph hops. If hop 1 has 90% accuracy, by hop 3 you're at 73% confidence. Poor entity resolution means the ripple effect analyzer produces false connections. Use ground-truth identifiers (CIK, bioguide_id, CUSIP, ticker) as anchors wherever possible. See [02-graph-schema.md](02-graph-schema.md) § "Confidence & Data Quality Principles".

### Resolution Rules

```python
class EntityResolver:
    """
    Resolution priority:
    1. Exact CIK match (for SEC filings)
    2. Exact ticker match (for financial data)
    3. Exact legal name match
    4. Fuzzy name match (Levenshtein distance < threshold)
    5. LLM disambiguation (last resort, for ambiguous cases)
    """
    
    def resolve_company(self, extracted_name: str) -> Optional[str]:
        # Step 1: Check ticker lookup table
        # Step 2: Check CIK lookup table  
        # Step 3: Full-text search in FalkorDB
        # Step 4: Fuzzy match against known names
        # Step 5: LLM call with context for disambiguation
        pass
    
    def resolve_legislator(self, name: str) -> Optional[str]:
        # Step 1: Check bioguide_id lookup table
        # Step 2: Fuzzy name match against known legislators
        # Step 3: Disambiguate by state/party if multiple matches
        pass
    
    def resolve_institution(self, name: str) -> Optional[str]:
        # Step 1: Check CIK lookup table (institutions also have CIKs)
        # Step 2: Fuzzy name match
        pass
```

### Company Master List
- Initialize from SEC EDGAR company index (~10K+ companies)
- Each company gets a canonical `ticker` as primary key
- Alias table maps alternative names → canonical ticker

### Legislator Master List
- Initialize from Congress.gov API (all current members)
- Keyed on `bioguide_id` (unique, stable identifier)
- Include historical members (last 10+ years) for trade history

### Institutional Holder Master List
- Initialize from SEC EDGAR 13F filer index
- Keyed on CIK
- Prioritize top 500 filers by AUM for initial load

---

## Ingestion State Tracking

Track what's been ingested to enable incremental processing:

```python
# SQLite table for ingestion state
CREATE TABLE ingestion_state (
    source TEXT,           -- "edgar", "news", "financial_api", "scraper"
    entity_key TEXT,       -- Company ticker or source-specific ID
    last_processed TEXT,   -- ISO timestamp or accession number
    last_success TEXT,     -- ISO timestamp
    error_count INT,       -- Consecutive errors
    PRIMARY KEY (source, entity_key)
);

CREATE TABLE ingestion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    entity_key TEXT,
    timestamp TEXT,
    status TEXT,           -- "success", "error", "skipped"
    items_processed INT,
    error_message TEXT
);
```

### Why the Current Design Is Sufficient

All pipelines are **pull-based (polling)**. EDGAR, FRED, News APIs, and every other source retain data on their servers — they don't push events to you. If the machine is down for maintenance, nothing is lost: the external source still holds the data, and the next polling run catches up automatically. Combined with APScheduler's missed-run detection and the idempotent `ingestion_state` table (all pipelines skip already-processed items), the system is inherently resilient to downtime without a dedicated message queue.

### Future Consideration: Message Queue for Real-Time Feeds

If the platform evolves to consume **push-based / webhook feeds** (e.g., EDGAR's real-time filing push, Polygon.io WebSocket tick data, exchange-level news wire hooks), the polling model can no longer guarantee durability — an event pushed while the worker is down would be silently dropped. At that point, introducing a message queue becomes the right call:

- **What**: Redis Streams (preferred — Redis is already running via FalkorDB) or a lightweight broker like RabbitMQ
- **Pattern**: Separate *fetcher* workers write raw events to the queue; *processor* workers consume them independently. Each stage can fail, restart, or scale without affecting the other
- **Why not now**: Adds operational complexity (consumer groups, DLQ management, at-least-once delivery semantics) that is pure overhead when every source already provides durable historical access via API

**Trigger for adoption**: Add a message queue when the first webhook/push-based source is integrated, or when concurrent multi-worker ingestion creates a need for work distribution. At that point, enabling Redis Streams on the existing FalkorDB Redis instance costs almost nothing.

---

## Data Source Summary by Graph Node Type

| Graph Node | Primary Sources (Tier) | Secondary Sources (Tier) |
|------------|----------------------|------------------------|
| **Company** | EDGAR (T0), FMP (T0) | ImportYeti (T1), Company websites |
| **Filing** | EDGAR (T0) | Investor presentations / IR PDFs (T1) |
| **DuckDB (financial_metrics)** | EDGAR Company Facts API (T0), FMP (T0) — full time series + provenance via `accession` column | BLS (T2), Short interest (T3), Dark pool volume (T3), Google Trends (T4) |
| **NewsArticle** | Marketaux (T0), GNews (T0) | IR press releases (T1), NewsAPI (T0), CNBC picks (T4) |
| **Industry / Sector** | EDGAR SIC (T1), FMP GICS (T0) | — |
| **Person** | EDGAR proxy (T0), Form 4 (T3) | LinkedIn (manual) |
| **Legislator** | Congress.gov (T1), congress-legislators repo (T1) | Capitol Trades (T1) |
| **CongressionalTrade** | House/Senate disclosures (T1), Quiver Quant (T1) | Capitol Trades (T1), Unusual Whales (T3) |
| **Legislation** | Congress.gov (T2), GovTrack (T2) | Federal Register (T3), ProPublica (T2) |
| **InstitutionalHolder** | 13F via EDGAR (T1) | ETF holdings (T3) |
| **GovernmentContract** | USASpending.gov (T2) | FPDS (T2) |
| **MacroIndicator** | FRED (T2), World Bank (T2) | BLS (T2), BEA (T2), IMF (T2) |
| **Region** | World Bank (T2), FRED (T2) | Census (T4), BEA (T2) |
| **Commodity** | FRED (T3), EIA (T3) | World Bank Commodities (T3) |

---

## Cost Summary

| Category | Sources | Annual Cost |
|----------|---------|-------------|
| **Completely Free** | EDGAR, EDGAR Company Facts API, FRED, Congress.gov, USASpending, BLS, BEA, World Bank, IMF, OpenFIGI, Federal Register, PatentsView, LDA (lobbying) | **$0** |
| **Freemium (free tier sufficient for Phase 0-1)** | FMP, Marketaux, GNews, CoinGecko, BLS registered | **$0** for Phase 0-1 |
| **Recommended paid (production)** | FMP Starter ($14/mo), Marketaux Standard ($29/mo) | **~$516/yr** |
| **Optional paid** | Quiver Quant ($10-30/mo), Unusual Whales ($57/mo) | **~$500-1,000/yr** |
| **Total for full production** | All recommended | **~$500-1,500/yr** |
| **Enterprise tier (Tier 4)** | Alternative data, premium terminals | **$10K-200K/yr** |

### LLM Usage by Pipeline

| Pipeline | LLM Usage | Optimization |
|----------|-----------|-------------|
| SEC EDGAR | High (entity extraction from long docs) | Summarize first, then extract. Use GPT-4o-mini for summarization |
| Financial APIs | None (structured data) | Direct Cypher inserts |
| News | Medium (classification + extraction) | Two-tier: cheap model for filtering, expensive model for extraction |
| Web Scraping | Medium | Batch processing, cache extracted relationships |
| Manual Uploads | Low (on-demand) | N/A |
| Congressional Disclosures | None/Low | Structured data from aggregators. LLM only if parsing raw PDFs |
| 13F Institutional Holdings | None | Pure structured data → Cypher |
| Government & Policy | Medium | LLM for legislation impact analysis. Structured for contracts |

### Cost Optimization Strategies

- **Batch processing**: Accumulate documents and process in batches to reduce API overhead
- **Async HTTP**: Use async HTTP clients for parallel fetching (separate from LLM calls)
- **Embedding cost**: Use `text-embedding-3-small` ($0.02/1M tokens) for embeddings — only embed summaries, not full documents. Cache embeddings, recompute only on content change
- **Two-tier LLM**: Use GPT-4o-mini for classification/filtering, GPT-4.1 only for high-value analysis

---

## Recommended Build Order

### Phase 0 (Data Foundation — 50 companies, 2-3 weeks)
1. **EDGAR** — 10-K, 10-Q for 50 semiconductor companies (fetch, parse, LLM-extract entities/relationships)
2. **EDGAR Company Facts API** — Financial metrics for those 50 companies → written to DuckDB `financial_metrics` table (via `timeseries.py`); latest snapshot recomputed onto FalkorDB Company nodes
3. **DuckDB initialization** — `financial_timeseries.duckdb` created with full schema (`financial_metrics` + `macro_timeseries`) during Phase 0 infrastructure setup. Phase 2 pipelines (FMP, FRED) write to this same store without schema changes
4. **FMP (free tier)** — Company profiles, prices, sector/industry (optional, lower priority than SEC extraction)

### Phase 1-2 (Core graph — 500 companies)
5. **EDGAR Company Facts API bulk download** — All company financials
6. **EDGAR 13F** — Top 50 institutional holders
7. **OpenFIGI** — CUSIP mapping for 13F parsing
8. **SIC/NAICS** — Industry classification from EDGAR
9. **Congressional disclosures** — House/Senate or Quiver Quant
10. **Congress.gov** — Committee assignments, legislator data

### Phase 3 (Scale — 5,000+ companies)
11. **FMP (paid)** — Scale company profiles and prices
12. **News API (paid)** — Scale news ingestion (Marketaux Standard)
13. **Congress.gov (legislation)** — Bill tracking
14. **USASpending.gov** — Government contracts
15. **FRED** — Full macro indicator suite
16. **World Bank / IMF** — International economic data
17. **IR pages + press releases** — RSS feed + scraper for tracked companies. Captures announcements before 8-K filing
18. **Supply chain extraction** — LLM extraction from 10-K filings

### Phase 5+ (Enhancement)
19. **Form 3/4/5** — Insider trading
20. **13D/G** — Activist positions
21. **Federal Register** — Regulations
22. **EIA / Commodity data** — Commodity prices
23. **Earnings transcripts** — FMP premium
24. **BLS / BEA** — Granular macro data
25. **Patent data** — USPTO PatentsView
26. **Short interest** — FINRA data
27. **Dark pool volume** — FINRA ATS weekly reports

### Post-Phase 7 (Only if system proves value)
28. Lobbying data (LDA)
29. International trade data (Census/Comtrade)
30. Social sentiment (Reddit/X)
31. Crypto data (CoinGecko)
32. Google Search Trends (pytrends)
33. CNBC / financial media stock picks
34. Corporate flight tracking (ADS-B / OpenSky)
35. Alternative data (satellite, credit cards — if ROI justifies $10K+/yr)
