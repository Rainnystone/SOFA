## Sector Hunt（行业猎捕）域知识参考

本文档是 SOFA Analyze 在 Sector Hunt 模式下的域知识参考。完整的 Stage 2-5 执行流程见 `references/sector-hunt-guide.md`。

核心问题：

> 这个方向里的主流受益者是谁？市场已经看见了哪一层？继续沿技术架构、供应链和客户链下钻后，哪些节点可能是真正有错配的 bottleneck candidates？

加载 [方法论手册](../references/knowledge/methodology.md) 和 [映射原型库](../references/knowledge/mapping-archetypes.md) 作为参考。

---

## 与主流程的对应关系

| 本文件内容 | 对应主流程阶段 | 执行指南 |
|-----------|--------------|---------|
| 架构迁移判断标准 | Stage 0 Demand Decomposition（Architecture Shift Brief） | sector-hunt-guide.md Stage 0 |
| 分层方法（market cap bucket） | Stage 2 Mapping Loops | sector-hunt-guide.md Stage 2 |
| 12 维 Chokepoint Scoring | Stage 3 Chokepoint Scoring | sector-hunt-guide.md Stage 3 |
| 最终产出定义 | Stage 5 Ranked Target Queue | sector-hunt-guide.md Stage 5 |

---

## 架构迁移判断标准

Sector Hunt 的第一问不是"有哪些股票"，而是：

> **这个方向是否存在明确的 architecture shift 或 demand regime shift？**

### 识别标准（而非穷举列表）

- 是否存在"从 A 到 B"的不可逆趋势？（单向性）
- 迁移是否改变了物理层面的依赖关系？（物理约束 > 软件偏好）
- 新架构中是否出现了旧架构中不存在的瓶颈层？（新约束 = 新机会）
- 是否有 demand regime shift（需求量级的突变，而非线性增长）？

### 搜索策略

遵循 [search-strategy.md](../references/search-strategy.md)。

- `"[theme] architecture shift 2025 2026"`, `"[theme] bottleneck"`, `"[theme] supply shortage"`
- 检查 Goldman Sachs / McKinsey / Yole / IDTechEx 等机构的公开报告片段
- 不要只搜"主要公司"——搜"supply constraint"、"unexpected bottleneck"、"who is the constraint"

如果没有清楚的架构迁移，应向用户说明。

---

## 分层方法：Market Cap Bucket

按 market cap bucket 和风险层级组织候选节点：

| Bucket | 角色 | 用途 |
|--------|------|------|
| Mega-cap anchor | 方向确认锚点 | 验证 demand signal |
| Large-cap direct winner | 主流直接受益者 | 市场已看见 |
| Mid-cap execution winner | 执行确定性高但弹性小 | 稳健配置 |
| Small-cap convex bottleneck | 潜在高弹性瓶颈 | Serenity 式 alpha |
| Micro-cap speculative | 高风险线索 | 需强 red-team |
| Private / pre-IPO | 不可买但作为供应链证据 | 完善图谱 |

---

## 12 维 Chokepoint Scoring 体系

Stage 3 对完整 dependency ladder 中所有候选节点打分：

| 维度 | 问题 | 评分 1-5 |
|------|------|---------|
| Demand Certainty | 需求增长有多确定？ | |
| Supply Concentration | 供给有多集中？ | |
| Substitutability | 有多难替代？ | |
| Qualification Cycle | 客户认证周期多长？ | |
| CapEx Difficulty | 扩产有多难？ | |
| Pricing Power | 议价权有多强？ | |
| Customer Concentration | 客户是否集中（风险）？ | |
| Evidence Quality | 证据等级有多高？ | |
| Financial Translation | 能否传导为收入？ | |
| Valuation Mismatch | 市值 vs 战略价值错配多大？ | |
| Liquidity / Dilution Risk | 流动性和稀释风险？ | |
| Catalyst Visibility | 催化剂是否可见？ | |

### 排序后的 Tier 划分

- **Tier 1: Priority Ticker Dive Targets**（Score 高 + Evidence 高 + 值得深挖）
- **Tier 2: Watch / Basket Candidates**（方向对但单一风险过高）
- **Tier 3: Rejected / Deprioritized**（证据不足或不成立）

### 最终产出

**Bottleneck Map + Ranked Target Queue**，不是直接股票推荐。个别标的只有进入 Ticker Dive 后才形成完整投资动作判断。

---

*Sector Hunt Domain Reference v2.0 | SOFA, adapted from Serenity OSINT v3.6.0*
