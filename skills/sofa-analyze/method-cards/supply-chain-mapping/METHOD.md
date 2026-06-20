---
name: supply-chain-mapping
description: "Builds multi-layer dependency ladders and supply chain maps to identify bottleneck positions, double exposures, and chokepoint candidates. Use when a Frontier Packet requires mapping supply chain layers, detecting double bottlenecks, distinguishing effective vs nominal capacity, or modeling buyer scramble game theory. Do not use for customer graph discovery or financial analysis."
visibility: subagent-private
owner_agent: supply-chain-mapper
owner_agent_label: Supply Chain Mapper
load_when: "Packet requests dependency ladder, supply chain, capacity, ownership chain, or double bottleneck analysis."
inputs: "Frontier Packet or Mapping Packet, target entity, current claim, output path."
outputs: "Dependency ladder, evidence table, confidence labels, unresolved questions, Method cards loaded declaration."
forbidden_uses: "Do not create a thesis alone; do not issue an Action Class; do not override the packet."
---

# Supply Chain Mapping

> This method card is subagent-private. Users should invoke SOFA Analyze, not this card directly.

## Purpose

构建多层 dependency ladder 并标注每层节点属性，识别 double bottleneck candidate 和 chokepoint。
核心关注点：**哪个节点如果被抢供、断供或提价，会让所有上层公司同时焦虑**——不是横向比较所有公司，而是按依赖层级纵向排序。

加载参考: [方法论手册](../../references/knowledge/methodology.md) 第 3 节 | [映射原型库](../../references/knowledge/mapping-archetypes.md)

---

## Inputs

| 输入项 | 来源 | 说明 |
|--------|------|------|
| Frontier Packet | 证据前沿循环 | 包含 target company/sector、claim being tested、当前 evidence ledger |
| Target company / sector | Packet 指定 | 映射起点——可以是单一公司或整个行业主题 |
| Claim being tested | Packet 假设 | 例如 "X 公司在 Layer N 拥有 chokepoint 控制力" |
| Terminal demand driver | Packet 或用户输入 | 驱动链条的终端需求方向 |

---

## Procedure

### 1. 确定终端需求 (Terminal Demand)

从 Frontier Packet 中提取终端需求驱动力。常见方向包括但不限于：

- AI cluster buildout / hyperscaler capex
- Robotics deployment
- EV / battery demand
- 5G/6G infrastructure
- Advanced packaging / chiplet
- Renewable energy transition
- Defense modernization
- Biotech manufacturing scale-up

**不要预设列表**——由 Packet 中的 claim 和 evidence 方向驱动。

### 2. 逐层下钻 (Layer-by-Layer Drill-Down)

从终端需求开始，每一层问 **"这一层依赖什么？"**：

```
Layer 0: Terminal Demand
    ↓ "这个需求扩张后，什么物理能力必须增加？"
Layer 1: System / Platform (OCS, transceiver, ASIC, battery cell...)
    ↓ "系统层依赖什么器件/模块？"
Layer 2: Component / Module (lasers, receivers, controllers, cathode material...)
    ↓ "器件层依赖什么材料/工艺？"
Layer 3: Material / Process (InP substrate, TFLN, LiFePO4, rare earth...)
    ↓ "材料层依赖什么原料/设备？"
Layer 4: Raw Material / Equipment (feedstock, purification, crystal growth, lithography...)
    ↓ "原料层依赖什么地理/许可/资源？"
Layer 5: Geography / Regulation (export permits, mines, refineries, JVs...)
```

每层至少识别 **2-3 个关键节点** 才继续下钻；如果某层只有单一供应商，该节点已经是 chokepoint candidate——记录并继续下钻以验证 double bottleneck。

### 3. 定向搜索策略 (Search Execution)

对每一层执行以下搜索组合。**搜索工具策略**：遵循 [search-strategy.md](../../references/search-strategy.md)。英文检索 → AnySearch 优先，中文检索 → configured search tool 优先。

#### 3.1 通用搜索模式（英文 → AnySearch 优先 / 中文 → configured search tool 优先）
- `"[layer N product] supplier"`
- `"[layer N product] market share"`
- `"[layer N] bottleneck shortage"`
- `"[company name] supply chain [layer N]"`

#### 3.2 行业报告搜索
搜索 Yole / LightCounting / McKinsey / IDTechEx / Goldman Sachs 报告片段：
- AnySearch（或 fallback configured search tool）`"[product] market report Yole"` 或 `"[product] forecast LightCounting"`
- 提取份额数据时标注报告年份和覆盖范围

#### 3.3 公司 IR / Earnings Transcript
检查大公司的 earnings transcript 中对上游 supply 的提及：
- AnySearch（或 fallback configured search tool）`"[company] earnings transcript supply constraint"`
- AnySearch（或 fallback configured search tool）`"[company] investor day upstream dependency"`

#### 3.4 yfinance 快速查询
```bash
python3 {PLUGIN_DIR}/scripts/fetch_financials.py TICKER quote
```
获取市值、行情概览，用于 Market Materiality Test。

#### 3.5 中国公司工商信息 OSINT
- configured search tool `"[公司名] 天眼查"` 或 `"[公司名] 企查查"`
- configured fetch/deep-read tool 读取搜索结果页面获取 **股东、对外投资、经营范围**
- 国家企业信用信息公示系统: configured search tool `"site:gsxt.gov.cn [公司名]"`
- 如果是上市公司子公司：从母公司年报/10-K 中获取关联关系

### 4. 标注节点属性 (Node Annotation)

对 ladder 中的每个公司/节点标注以下属性：

| 属性 | 说明 |
|------|------|
| Market Cap | 当前市值 bucket (Mega / Large / Mid / Small / Micro) |
| Role | 核心瓶颈 / 多供应商之一 / 二供 / 试样 / 生态露出 |
| Market Share | 估计份额（标注来源和 evidence grade） |
| Effective Capacity | 有效合格产能 vs 名义产能 |
| Qualification Status | 已认证 / 送样中 / 未开始 |
| Geography | 制造基地、总部、客户地域 |
| Substitutability | 替代难度 (High / Medium / Low) |
| Expansion Timeline | 扩产时间估计 |

**Effective vs Nominal 是关键区分**——名义产能包含所有产品等级和所有地域出货；有效产能只计入满足特定客户要求的部分。

### 5. Supplier Share Map 精度校准

**必须区分四种份额，混淆会导致严重误判**：

| 份额类型 | 定义 | 示例 |
|----------|------|------|
| **Nominal Share** | 公司声称或行业报告的总市场份额 | "全球 InP substrate 30%" |
| **Grade-Effective Share** | 只计算特定等级的份额（如 laser-grade 6N vs industrial 4N） | 30% 中只有 60% 达到 laser-grade → 18% |
| **Export-Effective Share** | 只计算可出口至目标客户地域的份额 | 18% 中部分受出口管制限制 → 12% |
| **Qualified Share** | 只计算通过客户认证后的可交付份额 | 12% 中已通过 hyperscaler qual 的 → 8-10% |

一个"30% 份额"如果只看 laser-grade + export-qualified，可能只有 10-15%。
**输出时必须标注使用的是哪种份额定义**，否则下游分析（红队、财务桥）无法正确引用。

### 6. Double Bottleneck 检测

当同一家公司在多个层级同时出现时，标记为 **double bottleneck candidate**。

检测规则：

1. **Adjacent-layer**: 在 Layer N 和 Layer N+1 都出现 → double bottleneck
2. **Skip-layer**: 在 Layer N 和 Layer N+2 都出现 → triple bottleneck（罕见，高 convexity）
3. **Indirect**: 通过 JV / subsidiary / ownership 间接出现在多层级 → 也算

**验证方法**：
- 对每个 candidate 执行 3.5 节中的工商信息 OSINT，确认股权和 JV 关系
- 检查子公司/合资公司是否独立定价还是受母公司控制
- 标注 evidence grade：confirmed（年报/工商确认）vs claimed（行业传闻）vs unverified

### 7. 买方抢供博弈建模 (Buyer Scramble / Game Theory Modeling)

当 supply tightness 出现且买方是高 capex / 高战略动机的客户时，建模博弈：

#### 7.1 BOM 占比测试
这个材料/器件在下游 BOM 中金额占比多少？
- 占比极低但不可替代 → 高价格容忍度 → 抢供可能大
- 占比高 → 买方有动力垂直整合或扶持二供

#### 7.2 买方战略动机分析
- 大客户之间谁先锁定供应 = **prisoner's dilemma**
- 不仅限于 hyperscaler——OEM 巨头、汽车 Tier-1、国防承包商等都可能参与抢供
- 检查：是否有 LTA（长期供应协议）、预付款、战略库存安排

#### 7.3 可能的买方行为预测
- 预付款 / 长期供应协议 / 战略库存 / 垂直整合 / 投资供应商
- 对每种行为评估：如果发生，对瓶颈公司的 revenue / margin / valuation 影响

#### 7.4 Market Materiality Test（不限市值）

| 市值级别 | 关注点 |
|----------|--------|
| **Mega-cap** (TSMC, ASML) | bottleneck 可能已被市场认知，验证定价权是否被低估 |
| **Large-cap** (LITE, COHR) | bottleneck 是否是增量收入的主要驱动力 |
| **Mid-cap** | bottleneck 对公司整体收入的弹性更高 |
| **Small-cap / Micro-cap** | Revenue/market cap 足够小 → 价格或订单变化产生巨大估值弹性；但 offering/dilution/insider sale 更容易发生 |

**关键判断**：不是"找小票"，而是"找错配"——任何市值级别的公司，只要战略控制力 vs 当前市值存在显著错配，都值得研究。

---

## Output

```markdown
## Supply Chain Map: [Theme / Company]

**Method cards loaded**: supply-chain-mapping
**Frontier Packet ref**: [packet ID / claim being tested]

### Dependency Ladder

| Layer | Category | Key Nodes | Evidence Grade |
|-------|----------|-----------|----------------|
| 0 | Terminal Demand | [demand driver] | — |
| 1 | System / Platform | [公司列表 + role] | [grade] |
| 2 | Component / Module | [公司列表 + role] | [grade] |
| 3 | Material / Process | [公司列表 + role] | [grade] |
| 4 | Raw Material / Equipment | [公司列表 + role] | [grade] |
| 5 | Geography / Regulation | [关键节点] | [grade] |

### Node Detail Table

| Company | Layer | Role | Market Cap | Mkt Share (type) | Eff. Capacity | Qual Status | Geography | Substitutability | Expansion Timeline |
|---------|-------|------|------------|-------------------|---------------|-------------|-----------|------------------|--------------------|

### Double Bottleneck Candidates

| Company | Layers Present | Direct/Indirect | Evidence Grade |
|---------|---------------|-----------------|----------------|

### Supplier Share Map

| Company | Nominal | Grade-Effective | Export-Effective | Qualified | Source |
|---------|---------|----------------|-----------------|-----------|--------|

### Buyer Scramble Game Theory (if applicable)

- **BOM share**: [占比及价格容忍度判断]
- **Prisoner's dilemma dynamics**: [买方锁定供应的竞争态势]
- **Predicted buyer behaviors**: [LTA / 预付款 / 垂直整合 / etc.]

### Market Materiality

| Company | Market Cap Bucket | Bottleneck Elasticity | Dilution / Offering Risk |
|---------|-------------------|-----------------------|--------------------------|

### Open Questions

- [需要进一步验证的链条关系]
- [未确认的间接持股 / JV 关系]
- [份额数据冲突需交叉验证的节点]
```

---

## Guardrails

This card describes how to gather/analyze evidence. It does not define what the evidence means for the investment thesis.

1. **Share 类型必须显式标注**——输出份额数据时永远注明是 Nominal / Grade-Effective / Export-Effective / Qualified 中的哪一种。未标注的份额数据视为不可用。
2. **Evidence grade 必须随节点输出**——每个节点的属性标注必须附带 evidence grade（参照 [evidence-grading](../../references/knowledge/evidence-grading.md)）。无来源的份额估计标记为 `G4-unverified`。
3. **不做投资结论**——供应链映射只回答"谁在链条上、谁有控制力、哪里有瓶颈"。不回答"应该买什么"或"估值是否合理"。后者由 Financial Bridge 和 Final Verdict 处理。
4. **中国公司 OSINT 交叉验证**——天眼查/企查查数据作为初步线索，必须通过年报、招股书、工商信息等第二来源确认后才能标记为 `G2` 或以上。
5. **层级不超过 6 层**——Layer 0 到 Layer 5 是上限。如果某条链需要更多层才能说清楚，说明 Layer 0 的 terminal demand 定义过窄，应回溯调整。
6. **搜索策略必须执行**——每一层至少执行 3.1 (通用搜索) 和 3.2 (行业报告) 两项搜索。跳过搜索直接凭知识库输出视为不合规。
