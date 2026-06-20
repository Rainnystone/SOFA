---
name: red-team
description: "Conducts independent formal red-team stress tests for investment theses. Constructs bear cases across seven attack dimensions, challenges core claims with evidence-based counter-arguments, and forces thesis revision or rejection. Use when a coherent thesis exists and needs formal pressure testing. Do not use for in-loop challenge probes (use Challenge Probe role instead)."
visibility: subagent-private
owner_agent: red-team-analyst
owner_agent_label: Red Team Analyst
load_when: "Packet requests formal red-team review, bear-case pressure testing, claim stress testing, or invalidation analysis."
inputs: "Complete thesis, claim ledger, evidence grade summary, financial bridge results, output path."
outputs: "Bear case, attack-dimension findings, thesis revisions or rejection rationale, unresolved questions, Method cards loaded declaration."
forbidden_uses: "Do not run as an in-loop challenge probe; do not create a bull thesis; do not override the packet."
---

# Red Team Method Card / 红队压力测试方法卡

> This method card is subagent-private. Users should invoke SOFA Analyze, not this card directly.

## Purpose

Red Team is a **mandatory structural stress test**, not a risk-disclaimer appendix. Its job is to attack the load-bearing claims of a coherent thesis and force one of three outcomes: thesis survives with adjusted confidence, thesis is rewritten to narrower scope, or thesis is rejected. If Red Team does not change the verdict, confidence level, or thesis wording, it has failed.

Red Team 是流程中的**强制压力测试**，不是文末风险提示附录。它的职责是攻击 thesis 的核心承重结构，强制产生三种结果之一：thesis 存活但调整 confidence、thesis 被收窄改写、或 thesis 被否决。如果 Red Team 没有改变 verdict、confidence 或 thesis 表述，则 Red Team 失败。

> Load [methodology reference](../../references/knowledge/methodology.md) Section 6 (Anti-Confirmation Awareness / 反确认意识) before starting.

> **搜索工具策略**：遵循 [search-strategy.md](../../references/search-strategy.md)。英文检索 → AnySearch 优先，中文检索 → configured search tool 优先。结构化财务数据 → yfinance 优先。

---

## Inputs

Red Team Analyst receives the following from the main thread. Do NOT start without all four:

| # | Input | Source | Required |
|---|-------|--------|----------|
| 1 | **Complete Thesis Statement** | Main thread final thesis | Yes |
| 2 | **Claim Ledger** | `evidence_ledger.md` — all claims with confidence levels and supporting evidence IDs | Yes |
| 3 | **Evidence Grade Summary** | Gate Scorecards from completed Evidence Frontier Loops | Yes |
| 4 | **Financial Bridge Results** | Financial Bridge Analyst output (Bridge Status, broken conditions, dilution analysis, valuation assessment) | Yes |

> **Context isolation**: Red Team Analyst does NOT receive conversation history, user sentiment, KOL endorsements, or current stock price. It operates on the structural evidence only.

---

## Procedure

Up to 3 rounds. If 3 rounds do not produce a stable assessment, output **Needs Primary Evidence** or **Reject for now**.

最多 1-3 轮。如果 3 轮后仍无法形成稳定判断，输出 **Needs Primary Evidence** 或 **Reject for now**。

### Round 1: Bear Case Construction (独立反驳)

Role: **an independent analyst who has never seen the bull case**. Construct a bear case from scratch.

角色：**完全不知道 bull case 的独立分析师**。从零开始构建 bear case。

#### Seven Attack Dimensions (七个攻击维度)

**A. Bottleneck Authenticity / Bottleneck 真实性**

- 这个 bottleneck 是否被夸大？
- 供应商数量、份额、可用产能、laser-grade 有效产能、认证后产能、可出口产能分别是多少？
- 是否只是 oligopoly 而非 single chokepoint？
- 替代技术/材料/路线是否存在？时间线是多少？

**B. Customer Relationships / 客户关系**

- 合作公告是否不等于订单？MOU 不等于 revenue？
- 客户映射是否只是 one-hop / two-hop 弱推断？
- Logo 出现在 partner page 是否等于 revenue-generating relationship？
- 大客户是否已 multi-source，使单一供应商份额被稀释？

**C. Supply Elasticity / 供给弹性**

- 有效产能是否真的稀缺，还是扩产已经在路上？
- 竞争者是否在扩产？（搜索该层级的主要竞争者及其扩产计划）
- 扩产时间线是年级别还是月级别？
- 纯度/良率/认证门槛是否被夸大？

**D. Financial Transmission / 财务传导**

- 当前 revenue 是否足够证明 demand 已传导？
- 客户地理是否支持"大客户抢供"叙事？
- Offering / dilution / insider sale 是否吞噬 upside？
- 毛利率能否扩张？还是被长协锁价？

**E. Valuation & Market Behavior / 估值与市场行为**

- 当前估值是否已经 price-in？特别是 KOL 公开讨论后？
- 小市值标的是否已经被 social media reflexivity 推高？
- KOL 公开讨论是否制造了反身性价格行为？（即 thesis 传播本身推高了股价，创造了 false validation）

**F. Geopolitics & Regulation / 地缘与监管**

- 出口管制是利好还是风险？还是双刃剑？
- 如果被管制方的收入依赖被管制市场，风险如何？
- 地缘政治升级的尾部风险有多大？

**G. Time Window / 时间窗口**

- Thesis 是否依赖"永久不可替代"？还是有明确时间窗口？
- 如果 2 年后 major buyer vertical integrate，bottleneck 还在吗？
- 替代技术的 timeline 是否被低估？

#### Round 1 Output: Bear Case Brief

For each counter-argument, produce:

```markdown
## Bear Case: [Company/Thesis]

### Strongest Counter-Arguments (按攻击强度排序)

#### 1. [最致命的反论点]
- 论据：
- 证据等级：
- 对 thesis 的影响：如果成立，thesis 的哪个核心 claim 被打穿？

#### 2. [第二强反论点]
- ...

#### N. [第 N 个反论点]
- ...

### Bear Case Summary
- 最强反论点是否足以推翻 thesis？
- 还是需要更多证据才能判断？
```

### Round 2: Thesis Defense / Revision (主线程回应)

Main thread receives the Bear Case Brief and responds to each counter-argument. For each one, exactly one of the following seven operations must be chosen:

主线程收到 Bear Case Brief 后，逐条回应。对每个反论点，**只能选择以下操作之一**：

| Operation | Meaning / 含义 | When to Use / 何时使用 |
|-----------|---------------|----------------------|
| **Accept** | 接受反论点，降级或放弃 claim | 反论点有 A/B 级证据支撑 |
| **Rebut** | 反驳反论点，提供额外证据 | 有更强的支撑证据 |
| **Downgrade** | 不否认风险，但降级 confidence | 反论点有道理但证据不足 |
| **Add Evidence** | 标注需要额外搜索来验证 | 当前证据不足以回应 |
| **Rewrite Thesis** | 修改 thesis 的核心表述 | 反论点揭示了 thesis 需要更精确的界定 |
| **Change Verdict** | 改变 action class | 反论点严重到改变最终结论 |
| **Reject Thesis** | 完全放弃 thesis | 核心 claim 被打穿 |

> Main thread must respond to **every** counter-argument. Skipping is not allowed.

### Round 3: Adversarial Re-score (红队审查修订后 thesis)

Red Team reviews the revised thesis after Round 2 responses:

- 修订后的 thesis 是否仍然站得住？
- 降级后的 confidence 是否仍值得 Act/Watch？
- 是否有新的反论点（在 Round 2 的修订中引入的）？

---

## Output

### Red Team Result Schema

```markdown
## Red Team Result: [Company/Thesis]

### Bear Case Summary (Round 1)
[最强 3-5 个反论点]

### Thesis Response Summary (Round 2)
[对每个反论点的回应和操作]

### Adversarial Re-score (Round 3)
- 修订后 thesis 是否仍成立：Yes / Partially / No
- Confidence after red-team：High / Medium / Low / Reject
- Verdict impact：[Action Class 是否改变]

### Remaining Unresolved Risks
[Red Team 后仍未解决的风险]

### Red Team Verdict
- **Thesis Survival**: Intact / Weakened / Refuted
- **Recommended Action Class Adjustment**: [如有]
- **Mandatory Additional Evidence**: [如有]
```

---

## Red Lines / 反确认红线

The following five conditions **MUST** trigger a verdict of **Reject** or **Needs Primary Evidence**. No exceptions, no softening via "risk factors to monitor" language.

以下五条中任何一条触发 → Red Team **必须**建议 Reject 或 Needs Primary Evidence。不允许用"风险因素待观察"软化。

1. **Single-source collapse**: Thesis 的核心 claim 只有一个来源支撑，且该来源被发现不可靠。
2. **Counter-evidence at equal or higher grade**: 发现同等级或更高等级的直接反向证据。
3. **Financial Bridge fracture**: 财务桥断裂（参见 Financial Bridge Analyst 的 6 条断裂条件）。
4. **Readily available substitute**: Thesis 依赖的 bottleneck 被证明有 readily available 替代品。
5. **Undisclosed material risk**: 发现公司有重大未披露风险（fraud、accounting irregularity、regulatory action）。

---

## KOL Reflexivity Check / KOL 反身性检查

When the thesis originates from or is widely propagated by KOLs (e.g., Serenity's own posts, Twitter/X fintwit threads, Substack deep-dives), the following four-point check is **mandatory**:

当 thesis 来自或被 KOL 广泛传播时（如 Serenity 本人的帖子、Twitter/X fintwit、Substack 深度帖），必须执行以下四点检查：

1. **Propagation scope / 传播范围**: 这个 thesis 被多少 KOL/大V/论坛讨论过？
2. **Price impact / 价格影响**: thesis 传播后股价是否已经异动？
3. **Reflexivity risk / 反身性风险**: KOL 推荐 → 散户涌入 → 股价上涨 → "验证" thesis → 更多人推荐 → 直到流动性/基本面无法支撑。
4. **Information edge decay / 信息优势衰减**: 一旦 thesis 被广泛传播，原始的信息优势还存在吗？

> If reflexivity is detected, the Bear Case Brief must include it as a standalone counter-argument under Dimension E (Valuation & Market Behavior).

---

## Guardrails

1. **This card describes how to gather/analyze evidence. It does not define what the evidence means for the investment thesis.** The Red Team Analyst produces structural assessments; the main thread decides what they mean for the action class and conviction level.

2. **Red Team is not a risk appendix.** It must materially affect the verdict, confidence, or thesis wording. A Red Team that produces no changes is a failed Red Team.

3. **Red Team must not be confused with Challenge Probe.** Challenge Probe operates inside the Evidence Frontier Loop, attacking the current frontier's claims in isolation. Red Team attacks the complete, assembled thesis after all loops have concluded.

4. **Thesis survival assessment must be evidence-based, not narrative-based.** "The thesis feels robust" is not a valid output. Every survival/weakening/refutation must cite specific evidence entries from the Evidence Ledger or Financial Bridge results.
