---
name: customer-graph-discovery
description: "Discovers hidden customer relationships using OSINT techniques including Wayback Machine, HTML inspection, funding matching, revenue geography, ecosystem mapping, annual report analysis, job posting analysis, and patent analysis. Use when a Frontier Packet requires mapping customer chains, inferring hidden relationships, or building confidence-tiered customer graphs. Do not use for supply chain mapping or financial analysis."
visibility: subagent-private
owner_agent: customer-graph-mapper
owner_agent_label: Customer Graph Mapper
load_when: "Packet requests hidden customer relationship mapping, customer graph discovery, confidence tiering, partner OSINT, or NDA placeholder analysis."
inputs: "Frontier Packet or Mapping Packet, target entity, known customers, candidate customers, output path."
outputs: "Confidence-tiered customer graph, evidence table, relationship status labels, unresolved questions, Method cards loaded declaration."
forbidden_uses: "Do not treat inferred customer links as revenue; do not issue an Action Class; do not override the packet."
---

# Customer Graph Discovery

> This method card is subagent-private. Users should invoke SOFA Analyze, not this card directly.

**搜索工具策略**：遵循 [search-strategy.md](../../references/search-strategy.md)。英文检索 → AnySearch 优先，中文检索 → configured search tool 优先。AnySearch 不可用时自动降级到 configured search tool/configured fetch/deep-read tool。

## Purpose

Transform publicly available traces into a confidence-tiered customer graph for the target company. This card provides eight OSINT techniques to uncover hidden customer relationships that companies obscure through NDA placeholders, silent removals, and vague language. The output is a structured graph with explicit confidence tiers, not an investment conclusion.

## Inputs

| Input | Description |
|-------|-------------|
| Frontier Packet | The research task defining what to investigate; takes priority over this card |
| Target Company | The company whose customer relationships are being mapped |
| Known Customers | Already-confirmed customer relationships (from prior research or public filings) |
| Candidate Customers | Companies to verify as potential hidden customers |

Load the [SIVE golden case](../../references/knowledge/sive-case.md) to study how Serenity applies these customer mapping techniques in practice.

> **行业适配说明**：以下 8 种 OSINT 技术适用于**任何行业**的隐藏客户关系映射——不限于半导体或光子学。SIVE 案例仅用于教学演示；在实际研究中，主线程应将这些技术适配到目标公司的行业语境（例如：生物科技公司关注 CRO/CDMO 合作伙伴页面变更；国防承包商关注项目竞标结果从团队页面的消失；SaaS 公司关注客户案例页面的增减）。

## Procedure

### 1. Wayback Machine / Archive.org

**Purpose**: Detect silent removal of partners/suppliers from company websites over time.

**Steps**:
1. Open `https://web.archive.org/web/*/company-partners-page-url` via Browser tool
2. Compare snapshots across different time points
3. Focus on: partner logos appearing/disappearing, customer list changes, ecosystem page modifications

**SIVE Case**: Ayar Labs partner page history showed Lumentum and MACOM were silently removed, leaving Sivers as the only publicly listed laser supplier.

**Evidence Grade**: B (Operational OSINT)

### 2. HTML Inspection

**Purpose**: Find residual metadata, alt text, and hidden links in page source code that reveal removed relationships.

**Steps**:
1. Open target page via Browser tool
2. Use `javascript_tool` for DOM inspection
3. Or use `get_page_text` to retrieve full text for analysis
4. Focus on: img alt text containing company names, meta tags, data attributes, comment blocks

**SIVE Case**: Ayar website source code retained Lumentum/MACOM alt text residues, revealing deleted supplier relationships.

**Evidence Grade**: B

### 3. Funding Round Amount Matching

**Purpose**: Infer the identity of placeholder customers (Customer B/C/D) in company presentations by matching disclosed investment figures to known funding rounds.

**Steps**:
1. Extract placeholder customer descriptions from annual reports / investor presentations
2. Note key figures (e.g., "total investment SEK 70 billion")
3. AnySearch (or configured search tool fallback) for industry funding events of matching amounts in the same period
4. Cross-validate: check whether the company named them elsewhere, whether technology roadmaps align

**SIVE Case**: Sivers presentation: Customer B ($154M) = Lightmatter Series C, Customer C ($100M) = Celestial AI Series B.

**Evidence Grade**: B (requires cross-validation to rule out coincidence)

### 4. Revenue Geography Matching

**Purpose**: Infer hidden customers through geographic revenue breakdowns.

**Steps**:
1. Obtain geographic revenue breakdown from annual report / 10-K
2. Identify major potential customers headquartered in those regions
3. Cross-validate: does the region have matching technology/industry demand?

**SIVE Case**: Sivers annual report showed majority of revenue from Finland, pointing to Nokia (Finland's tier-1 telecom).

**Evidence Grade**: B inference (requires other evidence for cross-validation)

### 5. Ecosystem Slide Mapping

**Purpose**: Discover hidden relationships from ecosystem partner slides published by large platform companies (e.g., GlobalFoundries, TSMC, Broadcom).

**Steps**:
1. Search for investor day / analyst day presentations from major platform companies
2. Examine ecosystem partner slides
3. Note the distinction between listed and unlisted companies on each slide

**SIVE Case**: GlobalFoundries CPO ecosystem slide listed only Sivers and Lumentum as laser companies.

**Evidence Grade**: B

### 6. Annual Report Language Analysis

**Purpose**: Infer customer identity from descriptive language in annual reports.

**Steps**:
1. Read carefully the sections on "customers", "partners", "collaborations"
2. Identify descriptive clues: e.g., "US Fortune 100 customer", "tier-1 telecom customer"
3. Combine with RFQ volume, order magnitude to narrow down specific customers

**SIVE Case**: Sivers annual report mentioned "US Fortune 100 customer" + RFQ 50M units/year; only Apple Watch matches that volume profile.

**Evidence Grade**: B (strong inference, not direct confirmation)

### 7. Job Posting Analysis

**Purpose**: Infer technology roadmap and customer relationships from recruitment signals.

**Steps**:
1. AnySearch (or configured search tool fallback) `"[company] careers" OR "[company] jobs site:linkedin.com"`
2. Analyze JD technical keywords, location, team description
3. Identify customer-specific roles (e.g., "onsite at customer facility")

**Evidence Grade**: B/C

### 8. Patent Analysis

**Purpose**: Infer technology collaboration relationships through patent filings and citation networks.

**Steps**:
1. Search company patent portfolio
2. Examine co-assignees, cited patents, inventor affiliations
3. Map specific application scenarios mentioned in patents to customer domains

**Evidence Grade**: B

## Output

Produce a Customer Graph in the following schema:

```markdown
## Customer Graph: [Company]

### Public Confirmed Customers
| Customer | Evidence | Source | Date |
|----------|----------|--------|------|
| ... | Press release / official announcement | [URL] | ... |

### High-Confidence Inferred
| Customer | Inference Method | Evidence Grade | Cross-Validation |
|----------|-----------------|----------------|------------------|
| ... | Wayback + annual report language | B | ... |

### Likely Customers
| Customer | Inference Method | Confidence |
|----------|-----------------|------------|

### One-Hop / Two-Hop Inferred
| End Customer | Chain | Confidence |
|-------------|-------|------------|
| ... | Company -> Customer A -> End Customer | Low |

### NDA Placeholders
(Placeholder labels from company presentations, e.g. Customer A/B/C/D, with inferred real identities)

### Open Questions
(Relationships requiring additional OSINT to confirm)
```

### Confidence Tier Definitions

| Tier | Definition | Permitted Use |
|------|-----------|---------------|
| Public Confirmed | Company announcement / press release explicitly confirms | May cite as fact |
| High-Confidence Inferred | Multiple B-grade evidence sources cross-validated | May support thesis, label as inferred |
| Likely | 1-2 B-grade evidence points or strong logical inference | Use as hypothesis |
| One-Hop Inferred | Inferred via confirmed customer's downstream | Use as lead |
| Two-Hop Inferred | Two-hop inference | Very weak lead, must label explicitly |

## Quality Check

Before outputting the customer graph, verify all six items:

1. **Logo does not equal Revenue** -- appearing on a partner page does not imply a revenue-generating relationship.
2. **MOU does not equal Order** -- a memorandum of understanding is not a purchase order.
3. **Sample does not equal Qualification** -- sending samples is not the same as passing qualification.
4. **Inference chain length** -- one-hop is already weak, two-hop is weaker, three-hop must not be used.
5. **Time decay** -- a partner page snapshot from 6 months ago may have changed; note evidence freshness.
6. **NDA caveat** -- include the Serenity disclaimer: even high-confidence relationships may not have reached volume production; NDA protection means 100% confirmation is never possible.

## Guardrails

This card describes how to gather/analyze evidence. It does not define what the evidence means for the investment thesis.

- **Customer confidence tiers are strictly enforced.** Never promote a Two-Hop Inferred relationship to Public Confirmed. Every tier has explicit evidentiary requirements (see Confidence Tier Definitions above).
- **Logo does not equal Revenue.** A partner logo on a website is a marketing artifact, not a financial fact.
- **MOU does not equal Order.** Strategic collaboration agreements and memoranda of understanding are not purchase orders or revenue.
- **Sample does not equal Qualification.** Sending engineering samples is not the same as passing customer qualification or entering volume production.
- **Inference chain length limit.** One-hop inference is the practical maximum for usable leads. Two-hop is extremely weak. Three-hop inference must not be used under any circumstances.
- **Time decay.** Evidence degrades. A partner page snapshot older than 6 months may no longer reflect the current relationship. Always annotate evidence with dates.
- **NDA caveat.** Companies protect customer identities with NDAs. Even high-confidence inferred relationships may not have reached volume production. 100% confirmation is structurally impossible for NDA-protected relationships.
