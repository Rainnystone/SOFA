# SOFA Search Strategy

This file is the human-readable operational strategy guide for SOFA search, fetch, and financial-data routing. Guides, prompts, method cards, and reports should reference this file for operational search policy instead of redefining source handling or freshness rules. Deterministic capability facts such as chain order, provider ids, recommendation text, and search-record vocabulary belong to `../../../scripts/capability_policy/`.

## General Search Fallback Chain

The deterministic source for this order and its provider ids is `../../../scripts/capability_policy/`. The list below is the human-readable summary.

Use the strongest configured tool that fits the evidence need:

1. AnySearch skill: preferred general search and extraction layer when installed.
2. Exa MCP server: preferred MCP fallback for web search and page fetch when configured.
3. Tavily skills or CLI: preferred JSON-friendly fallback for search, extract, crawl, map, or research tasks.
4. Host-agent built-in search and fetch tools: acceptable final fallback when external capabilities are not configured.

If a tool is missing, rate-limited, or fails, record the limitation in `capability_report.md` or the evidence ledger, then continue with the next available tool. Do not silently pretend that a weaker fallback has the same confidence as a purpose-built capability.

## Financial Data Recommendations

SOFA separates market data from evidence.

- Chinese users and China-market public-company work: recommend Wind financial capability.
- English or global public-market users: recommend `yfinance` for quick structured snapshots.
- Filings, exchange announcements, annual reports, prospectuses, and company disclosures remain authoritative.
- Missing financial tools lower financial bridge confidence. They do not automatically stop OSINT mapping, but they can block action-class conclusions.

`fetch_financials.py` can use the local Python environment for structured public-market snapshots when dependencies are available. If it is incomplete for a market, supplement with configured search and fetch tools, then cite the source type and evidence grade.

## Routing By Evidence Type

| Evidence need | Preferred route | Notes |
|----------------|-----------------|-------|
| Real-time quote, market cap, basic public financials | `fetch_financials.py` with `yfinance` when available | Treat as research support, not a filing substitute. |
| English industry reports, earnings transcripts, filings, investor slides | AnySearch, then Exa, then Tavily, then configured search tool | Deep-read high-value pages with the configured fetch/deep-read tool. |
| Chinese company registry, announcements, prospectuses, and supply-chain context | AnySearch or Wind when suited, then Exa/Tavily, then configured search tool | Use official registries and exchange pages whenever possible. |
| Webpage or PDF deep reading | AnySearch extraction, Exa fetch, Tavily extract, then configured fetch/deep-read tool | Do not cite snippets you have not opened or extracted. |
| Private-company mapping | Search plus official registry, prospectus, supplier pages, archived pages, and customer evidence | Separate ownership evidence from revenue evidence. |
| Contrarian evidence | Same chain, but query for alternatives, substitution, delay, lawsuits, dilution, demand slowdown, and short/bear arguments | Red-team evidence must be actively searched, not inferred. |

## Mandatory Search Protocol

1. Decide the evidence type before choosing tools.
2. Start with the strongest configured capability for that type.
3. Use source-specific queries: `site:`, filetype, date range, exchange names, registry names, customer names, and product identifiers.
4. Deep-read high-value results before using them as evidence.
5. Record tool gaps and fallback steps.
6. Assign evidence grades in the evidence ledger.

## Prior Search Trace

Before dispatching a Scout or Challenge Probe, the main thread may render a prior-query digest and paste it into the dispatch after the packet:

```bash
python {PLUGIN_DIR}/scripts/search_intel.py digest "{WORKSPACE}"
python {PLUGIN_DIR}/scripts/search_intel.py stats "{WORKSPACE}"
```

The digest carries negative trace only: queries already attempted, dead ends with categories, and visited hosts. It never contains findings, grades, or thesis content, so it does not weaken worker isolation. Dead-end categories: `no_result` (do not retry verbatim), `tool_degraded` (retry once the capability recovers), `blocked_source` (needs an alternate route, not repetition).

The stats table is advisory input for the Gate Scorecard's Next Yield judgment. It never decides continue/stop.

`{PLUGIN_DIR}/scripts/assemble_dispatch.py` attaches this digest to assembled dispatches automatically when `search_log.jsonl` exists; pass `--no-digest` to bypass explicitly.

## Framing Search

Stage 0 framing search is intentionally light. It may confirm:

- subject identity and ticker ambiguity;
- current business description;
- major recent event that affects routing;
- whether the user's question is Ticker Dive, Sector Hunt, or Sector-to-Ultra.

Stage 0 must not turn into thesis formation.

Confirm the subject deterministically first when a ticker candidate exists — this costs zero search budget and resolves ticker→company mapping before any external search runs:

```bash
python scripts/fetch_financials.py COHR profile
```

The `profile` module returns `longName`, `exchange`, `sector`, and `industry`, which confirm the identity against user intent. Same-name tickers, multi-listing, ADR, renames, and parent/subsidiary ambiguity produce `framing_intake.py add-candidate` entries with exclusion rationale, and clarification questions are generated from the candidate table rather than improvised. Only then run framing search, and record `resolution_method` as `deterministic_quote`, `framing_search`, or `user_confirmed` honestly. Search is for unresolved identity, rename history, sector/theme framing, or evidence that deterministic quote/profile data cannot provide. When yfinance is unavailable (capability report), record `framing_search` or `user_confirmed` honestly.

Log framing searches to `search_log.jsonl` with `loop_id: "stage_0"` so they join the machine-readable search trail before Loop 1 exists.

## Role-Specific Use

| Role | Structured financial data | Search | Deep read |
|------|---------------------------|--------|-----------|
| Main thread | Quote and profile only during framing | Configured chain | Configured fetch/deep-read tool |
| Frontier Scout | Only when needed to verify basic company context | Configured chain | Required for high-value sources |
| Challenge Probe | Usually none | Configured chain with contrarian queries | Required for strong counter-evidence |
| Sector Mapper | Company profile only when needed | Configured chain | Required for map-changing sources |
| Coverage Challenge | Usually none | Configured chain with missing-path queries | Required for coverage claims |
| Financial Bridge | Full structured snapshot plus filings/disclosures | Configured chain for filings, transcripts, and IR | Required |
| Red Team | Valuation, holders, earnings where available | Configured chain for bear evidence | Required |

## Examples

English public-company search:

```text
"company name" "earnings transcript" "product line"
"ticker" 10-K "risk factors" "customer concentration"
"product" "supplier" "capacity expansion"
```

Chinese company and supply-chain search:

```text
"公司名" "招股说明书"
"公司名" "供应商" "客户"
site:cninfo.com.cn "证券代码" "年度报告"
site:gsxt.gov.cn "公司名"
```

Sector mapping search:

```text
"industry" "supply chain map" "tier 2"
"technology" "bottleneck" "capacity constraint"
"product" "raw material" "substrate" "qualified supplier"
```

Contrarian search:

```text
"company" "substitution risk"
"product" "alternative technology"
"industry" "overcapacity"
"company" "dilution" OR "convertible" OR "ATM offering"
```

## Anti-Patterns

- Do not search for market cap, price, or valuation ratios when a structured financial snapshot is available.
- Do not treat search snippets as evidence without deep reading.
- Do not treat customer logos, pilots, samples, or ecosystem membership as revenue.
- Do not use KOL claims as core evidence.
- Do not suppress missing-tool limitations. Missing capabilities must appear in capability reporting and confidence language.

## Capability Setup

See `SOFA/docs/capability-setup.md` for installation recommendations. SOFA detects optional tools and prints recommendations, but it does not silently install tools or write credentials.
