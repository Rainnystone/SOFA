---
name: financial-bridge
description: "Verifies whether a bottleneck thesis translates into revenue, profit, and valuation impact. Performs Revenue Reality check, DuPont decomposition, Revenue Capture estimation, Capital Structure and dilution analysis, Valuation Mismatch assessment, and Catalyst Clock mapping. Use when a coherent bottleneck thesis needs financial translation verification. Do not use for supply chain or customer graph research."
visibility: subagent-private
owner_agent: financial-bridge-analyst
owner_agent_label: Financial Bridge Analyst
load_when: "Packet requests financial bridge, revenue reality, margin, cash flow, dilution, valuation, or catalyst checks."
inputs: "Thesis packet, target company, ticker if available, financial transmission paths, output path."
outputs: "Revenue reality checks, financial bridge status, valuation and dilution assessment, unresolved questions, Method cards loaded declaration."
forbidden_uses: "Do not validate supply chain or customer evidence alone; do not issue an Action Class; do not override the packet."
---

# Financial Bridge Analysis Method Card

> This method card is subagent-private. Users should invoke SOFA Analyze, not this card directly.

> This card is dispatched as a subagent by the research orchestrator. It is not user-invocable.
> Dispatch rules: see [Subagent Dispatch](../../references/subagent-dispatch.md) Role 5.

## Purpose

Even if a bottleneck thesis is technically valid at the supply-chain level, the company may fail to capture financial value. This method answers: **can the company translate its bottleneck position into revenue growth, margin expansion, and valuation re-rating -- or do structural financial barriers (dilution, capacity lag, pricing lockdown, geographic mismatch) break the bridge between thesis and P&L?**

## Inputs

| Parameter | Description | Example |
|-----------|-------------|---------|
| Company name | Full legal or common name | "GlobalWafers" |
| Ticker | yfinance-compatible ticker | `6488.TW` |
| Thesis summary | 1-3 sentence bottleneck thesis | "Only qualified supplier of 300mm epi-wafers for TSMC N2" |
| Financial transmission paths | Specific paths to verify | "revenue concentration, pricing power, capacity timeline" |

## Utility Script

Before analysis, pull a full financial snapshot via the bundled `fetch_financials.py` script:

```bash
# Full snapshot (recommended) -- quote + profile + income + balance + cashflow + valuation + holders + analyst recommendations + earnings + dividends
python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER

# Single module on demand
python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER valuation
python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER income
python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER balance
python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER cashflow
```

**Ticker format**:

| Market | Format | Example |
|--------|--------|---------|
| US | `SYMBOL` | `AAPL` |
| HK | `CODE.HK` | `0700.HK` |
| A-share Shanghai | `CODE.SS` | `600519.SS` |
| A-share Shenzhen | `CODE.SZ` | `000858.SZ` |
| Japan | `CODE.T` | `6501.T` |
| Korea | `CODE.KS` | `005930.KS` |
| Taiwan | `CODE.TW` | `2330.TW` |

**Data supplement**: yfinance data may be incomplete (especially A-share and HK). When needed, supplement with AnySearch/configured fetch/deep-read tool (英文 10-K, 10-Q, earnings releases, IR pages) or configured search tool/configured fetch/deep-read tool (中文 A 股公告、港股年报). See search-strategy.md.

## Procedure

### Module 1: Revenue Reality (收入现实检查)

Confirm whether current revenue can support the thesis narrative.

| Check item | Method | Data source |
|------------|--------|-------------|
| Total revenue & growth (YoY, QoQ) | Trend analysis | yfinance income module, 10-K, 10-Q, earnings release |
| Segment revenue split | Decompose by business line | 10-K segment reporting, yfinance profile |
| Geographic revenue split | Decompose by region | 10-K, annual report |
| Top customer concentration | Top-5 customer share | 10-K (if disclosed) |
| Narrative-reality gap | What % of revenue is the new business the thesis relies on? | Cross-validation |

**Key judgments**:
- If the thesis says "future major customer" but geographic revenue from that region is negligible --> **Gap Flag**
- If the narrative depends on a new business still in R&D or sample stage --> **Timeline Gap**
- If QoQ revenue is flat but the thesis claims demand > supply --> **Signal Mismatch**

### Module 2: Profitability & DuPont (盈利能力与杜邦分解)

Understand the structural drivers of the company's ability to generate returns.

**DuPont decomposition**:

```
ROE = Net Margin x Asset Turnover x Equity Multiplier
    = (Net Income / Revenue) x (Revenue / Total Assets) x (Total Assets / Equity)
```

| Dimension | Check items | Bridge significance |
|-----------|-------------|---------------------|
| Net margin | Gross margin trend, net margin trend, peer comparison | If supply tight --> gross margin should expand |
| Asset turnover | AR turnover, inventory turnover, cash conversion cycle | If demand strong --> turnover should accelerate |
| Equity multiplier | Leverage ratio, debt structure | If forced to lever up for expansion --> risk increases |

**Stage-specific analysis** (阶段适配分析):

| Stage | Characteristics | Bridge focus |
|-------|----------------|--------------|
| High growth (revenue > 30% YoY) | Market capture | Revenue growth sustainability, share gains, scale-inflection point |
| Stable growth (10-30%) | Profit release | Margin improvement, ROE uplift path, dividend capacity |
| Mature (< 10%) | Cash return | Cash flow yield, dividend policy, second growth curve |
| Turnaround | Profit decline / losses | Reversal catalysts, balance-sheet safety, burn rate |

### Module 3: Revenue Capture (收入捕获潜力)

If the thesis is correct, estimate revenue upside potential.

| Dimension | Estimation method |
|-----------|-------------------|
| Company-addressable TAM | Addressable market the company can actually reach (not total industry TAM) |
| Market share assumption | Current share + competitive landscape + bottleneck position |
| Pricing power | If supply tight, how much can the company raise prices? How much is locked by long-term agreements (LTAs)? |
| Revenue timeline | When does revenue reflect? Next quarter? Next year? |
| Capacity constraint | Utilization rate, expansion plan and timeline |

**Critical questions**:
- Even if demand > supply, does the company have **qualified capacity** to deliver?
- Where does expansion capex come from? Internal cash vs equity raise vs debt?
- How long is the expansion cycle? Can it complete within the thesis time window?

### Module 4: Capital Structure & Dilution (资本结构与稀释)

Check whether capital structure swallows the upside.

| Dilution source | How to check | Danger signal |
|-----------------|-------------|---------------|
| ATM (At-the-Market) | 10-Q, 8-K filing | Large unused ATM shelf |
| Convertible Notes | 10-K, 8-K | Recent issuance, low conversion price |
| Warrants | 10-K, proxy | Large unexercised warrant pool |
| SBC (Stock-Based Comp) | 10-K, proxy | SBC/Revenue > 20% |
| Debt | Balance sheet | High debt/cash ratio, recent large borrowings |
| Insider Sales | Form 4 filing | Large insider sells (distinguish 10b5-1 from panic) |
| Secondary Offering | 8-K, press release | Recent or upcoming offering |

**Quantification requirement**: Sum ATM + convertible + warrants and express as % of current diluted shares outstanding. Do not merely flag "dilution risk exists" -- provide the number.

### Module 5: Valuation Mismatch (估值错配检验)

Test whether the "strategic value vs market cap" mismatch exists and whether the market has already priced it in.

#### 5a. Valuation method selection (估值方法选择)

| Method | Applicable when | Not applicable when |
|--------|----------------|---------------------|
| PE (TTM / Forward) | Stable earnings, multiple comps available | Losses, volatile earnings, cyclical trough |
| PB-ROE | Financial / heavy-asset industries | Asset-light / high-growth |
| PS / EV/Revenue | Loss-making or thin-margin companies | Stable-earnings companies |
| EV/EBITDA | Heavy-asset / cross-border comparison | Use as supplement |
| PEG | High-growth companies | Low-growth or loss-making |
| P/FCF | Strong cash-flow generators | High-capex phase |
| SOTP (sum-of-parts) | Multi-segment with large variance | Single-segment |
| DCF | Stable, predictable cash flows | High-growth / unpredictable cash flows |

**Industry-specific metrics** (行业特殊指标):

| Industry | Special metrics |
|----------|----------------|
| Semiconductor / Materials | EV/capacity, P/wafer capacity |
| SaaS / Cloud | EV/ARR, Rule of 40 |
| Biotech (pre-revenue) | Pipeline NPV, P/pipeline |
| Resources / Cyclical | EV/reserves, EV/capacity |

#### 5b. Comparable company valuation matrix (可比公司估值矩阵)

Build a 3-5 company comparable matrix:

| Company | Market Cap | PE(TTM) | PE(Fwd) | PB | PS | EV/EBITDA | [Industry metric] |
|---------|-----------|---------|---------|----|----|-----------|-------------------|
| Target | | | | | | | |
| Comp A | | | | | | | |
| Comp B | | | | | | | |
| **Median** | | | | | | | |

Compute the implied valuation range (25th percentile - median - 75th percentile) and compare against current market cap.

#### 5c. Serenity-style Market Cap Mismatch (Serenity 式 Market Cap Mismatch 推理)

Beyond standard valuation, additionally answer:
- How large is the mismatch between current market cap and strategic control value?
- Compare: market cap of pre-revenue concept companies vs real-revenue bottleneck companies?
- **Must distinguish**: market may have already priced-in (especially after wide KOL discussion), market may be correctly reflecting dilution risk

#### 5d. KOL Reflexivity Check (KOL 反身性检查)

If the thesis has been widely circulated by KOLs:
- Did the stock price move materially after circulation?
- Does the current valuation already include a narrative premium?
- If the narrative recedes, what valuation level would it revert to?

### Module 6: Catalyst Clock (催化剂时钟)

| Catalyst | Expected timeline | Direction | Type |
|----------|-------------------|-----------|------|
| Next earnings | YYYY-Q? | Revenue validation | Confirm / Deny |
| Key customer announcement | Event-driven | Relationship confirmed | Confirm |
| Capacity expansion complete | YYYY-Q? | Supply increase | Double-edged |
| Export license review | Event-driven | Geographic constraint | Double-edged |
| Substitute technology milestone | YYYY+ | Long-term substitution | Deny |
| Offering / financing | Any time | Dilution | Deny |
| Industry conference / trade show | Periodic | New signals | Neutral |

## Bridge Break Conditions (Bridge 断裂条件 -- 硬性规则)

Any one of the following triggers --> Bridge Status = **Fully Broken**. No Act conclusion is permitted when any condition fires.

1. **Revenue cannot support narrative**: New business < 5% of revenue AND no growth in last 2 quarters.
2. **Dilution swallows upside**: ATM + convertible + warrants total potential dilution > 30%.
3. **Cash runway insufficient**: Cash runway < 12 months, forced financing probability high.
4. **No pricing power**: LTA-locked pricing + multi-supplier system --> cannot raise prices even when supply tight.
5. **Geographic revenue fully mismatched**: Thesis says US hyperscaler but revenue 99% from unrelated geographies.
6. **Capacity expansion nowhere in sight**: Has raw materials but no qualified capacity; expansion requires 3+ years.

## Output

The Financial Bridge Report follows this schema:

```markdown
## Financial Bridge Report: [Company] ([Ticker])

### Analysis date: YYYY-MM-DD
### Data currency: Based on [most recent filing] data

---

### 1. Revenue Reality
| Metric | Last Annual | Last Quarter | YoY | QoQ |
|--------|-----------|--------------|-----|-----|
| Total Revenue | | | | |
| Gross Margin | | | | |
| [Segment A] | | | | |
| [Geographic A] | | | | |

**Narrative-Reality Gap**: [specific findings]

### 2. Profitability (DuPont)
| Dimension | Value | Trend | Peer Median | vs Peer |
|-----------|-------|-------|-------------|---------|
| ROE | | | | |
| Net Margin | | | | |
| Asset Turnover | | | | |
| Equity Multiplier | | | | |

**Stage**: [High growth / Stable / Mature / Turnaround]
**Stage-Specific Focus**: [corresponding analysis focus]

### 3. Revenue Capture Potential
- Company-addressable TAM:
- Market Share Assumption:
- Pricing Power Assessment:
- Revenue Timeline:
- Capacity Readiness:

### 4. Capital Structure & Dilution
| Source | Amount / Rate | Risk Level | Impact on EPS |
|--------|--------------|------------|---------------|
| ATM | | | |
| Convertible | | | |
| Warrants | | | |
| SBC | | | |
| **Total Potential Dilution** | | | |

### 5. Valuation Assessment

#### Comparable Matrix
| Company | MCap | PE(TTM) | PE(Fwd) | PB | PS | [Industry metric] |
|---------|------|---------|---------|----|----|-------------------|
| Target | | | | | | |
| Comp A | | | | | | |
| Comp B | | | | | | |
| Median | | | | | | |

#### Implied Valuation Range
- 25th percentile: [X]
- Median: [X]
- 75th percentile: [X]
- Current market cap: [X]
- Position: [Below / Fair / Above]

#### Market Cap Mismatch (Serenity-style)
- Strategic control vs market cap: [analysis]
- Already priced-in?: [analysis]
- KOL reflexivity risk: [Yes / No]

### 6. Catalyst Clock
| Catalyst | Timeline | Direction | Type |
|----------|----------|-----------|------|
| ... | ... | ... | ... |

### 7. Financial Bridge Verdict
- **Bridge Status**: Intact / Partially Broken / Fully Broken
- **Broken conditions triggered**: [list triggered conditions, or "none"]
- **Key Risk**: [largest financial transmission risk]
- **Missing Evidence**: [what data would confirm or deny]
- **Valuation Conclusion**: [current market cap vs fair range]
```

## Quality Standards (质量标准)

1. Financial data must cite source and date.
2. Valuation must use at least 2 methods for cross-validation.
3. Loss-making companies must NOT use PE -- switch to PS or EV/Revenue.
4. If fewer than 3 comparable companies, must disclose limitation explicitly.
5. DuPont decomposition must be complete (all three factors).
6. Stage-specific analysis must not be skipped.
7. Dilution analysis must be quantified (not merely "dilution risk exists" -- provide the number).
8. Must not give buy/sell recommendations; output is financial transmission analysis only.

## Guardrails (防护栏)

> **This card describes how to gather and analyze evidence. It does not define what the evidence means for the investment thesis.**

- **No investment recommendations**: Must not output buy, sell, hold, or any directional investment advice. Output is limited to financial transmission analysis.
- **Quantify dilution**: When flagging dilution risk, must provide the quantified impact (shares, %, EPS effect). Merely stating "dilution risk exists" is insufficient.
- **Loss-making companies must not use PE**: For companies with negative earnings, PE is invalid. Must switch to PS, EV/Revenue, or other applicable methods. Using PE for loss-making companies is a hard error.
