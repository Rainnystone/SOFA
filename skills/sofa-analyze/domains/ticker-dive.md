## Ticker Dive（个股深潜）域知识参考

本文档是 SOFA Analyze 在 Ticker Dive 模式下的域知识参考。

核心问题：

> 这家公司是否处在某个被市场低估的关键依赖节点？如果是，它的 bottleneck 到底是什么、证据等级多高、财务能否传导、反证是否足够强？

加载 [方法论手册](../references/knowledge/methodology.md) 和 [AXTI 黄金案例](../references/knowledge/axti-case.md) 作为参考。

---

## 阶段 1: Company Reality Check

**在任何 bull thesis 之前，先确认公司真实业务。** 许多中小盘科技公司有强叙事和弱收入。

### 必须收集的信息

1. **产品与 segment**：公司实际卖什么？有哪些业务线？
2. **收入结构**：总收入、segment revenue、geographic revenue、top customers
3. **客户结构**：谁在买？公开客户 vs 推断客户？客户集中度？
4. **财务状态**：毛利率、营业利润率、现金流、现金储备
5. **融资结构**：ATM、可转债、warrants、SBC、债务、稀释
6. **管理层表述**：最近 earnings call 中管理层怎么说？
7. **历史业务 vs 新业务**：当前叙事依赖的新业务占收入多少？

### 搜索策略

> 遵循 [search-strategy.md](../references/search-strategy.md)（三路分流：yfinance 结构化 / AnySearch 英文定性 / configured search tool 中文 OSINT）。AnySearch 不可用时自动降级到 configured search tool/configured fetch/deep-read tool，yfinance 数据不全时用 AnySearch/configured search tool + configured fetch/deep-read tool 补充。

- **yfinance**: `python3 {PLUGIN_DIR}/scripts/fetch_financials.py TICKER`（完整财务快照，结构化数据 PRIMARY）
- **AnySearch**（英文优先）/ **configured search tool**（中文）: `"[company] annual report 2025"`, `"[ticker] 10-K"`, `"[ticker] earnings transcript"`
- **configured fetch/deep-read tool**: 公司 IR 页面、SEC filing
- **中国公司工商信息**: configured search tool `"[公司名] 天眼查"` / configured fetch/deep-read tool 天眼查/企查查页面
- **Browser**: 需要交互的页面检查

### 输出：Company Reality Brief

```markdown
## Company Reality Brief: [Company] ([Ticker])

### 核心业务
- 主要产品/服务：
- 业务 segment：
- 收入来源：

### 财务快照
- Revenue / Gross Margin / Operating Margin / FCF：
- Cash & Equivalents：
- Debt / Dilution：

### 客户地理
- Geographic Revenue Breakdown：
- Top Customers（公开/推断）：

### 管理层近期信号
- 最近 earnings call 关键表述：

### 叙事-现实差距检查
- 当前市场叙事：
- 叙事依赖的新业务占收入比例：
```

---

## 阶段 2: 链条位置判断

公司现实确认后，判断它在哪个链条上。

### 剥洋葱流程

参考 [方法论手册](../references/knowledge/methodology.md) 第 3 节，回答：

1. **该公司位于哪条技术/供应/客户链？**
2. **它在链条的哪一层？**（系统层 / 器件层 / 材料层 / 原料层）
3. **它是核心瓶颈、可替代供应商、二供、客户试样对象，还是只是生态露出？**
4. **关键关系是公开确认、间接推断还是 KOL 叙事？**

### 输出：Chain Position Assessment

```markdown
## Chain Position Assessment

### 链条定位
- 所在链条：
- 所在层级：
- 角色定位：核心瓶颈 / 可替代供应商 / 二供 / 试样对象 / 生态露出

### Dependency Ladder
（从 Supply Chain Mapper 交付文件获取）

### Customer Graph
（从 Customer Graph Mapper 交付文件获取）

### 关键关系证据等级
| 关系 | 证据等级 | 来源 |
|------|---------|------|
| ... | A/B/C/D | ... |
```

---

## 阶段 3: Evidence Frontier Loops

派遣 Frontier Scout subagent 执行多轮定向 OSINT（按证据前沿循环的编排逻辑）。

### 初始 Frontier 建议

- Frontier 1: 验证公司是否为某大客户的关键供应商
- Frontier 2: 验证供应链瓶颈是否真实存在（供给约束证据）
- Frontier 3: 验证财务传导（收入是否开始反映叙事）

每轮结束后检查 Gate Scorecard，决定是否继续。

---

## 阶段 4: Financial Bridge

派遣 Financial Bridge Analyst subagent 检验瓶颈能否传导为收入和利润。

核心问题：即使技术和供应链 thesis 成立，公司能否捕获价值？

---

## 阶段 5: Red Team

派遣 Red Team subagent 对完整 thesis 进行独立压力测试。

---

## 阶段 6: Final Verdict

调用最终裁决与观察流程（见 [Final Verdict 参考](../references/final-report.md)），生成最终裁决和观察协议。

---

## 完成定义

个股深潜完成时，必须输出 **Actionable Thesis Dossier**：

```markdown
## Actionable Thesis Dossier: [Company] ([Ticker])

### 1. Company Reality
[阶段 1 输出摘要]

### 2. Thesis Statement
[一句话 thesis]

### 3. Dependency / Customer Map
[阶段 2 输出摘要]

### 4. Claim Ledger
[从 evidence_ledger.md 提取]

### 5. Evidence Grade Summary
[A/B/C/D 级证据分布]

### 6. Financial Bridge
[阶段 4 输出摘要]

### 7. Challenge Probe Notes
[从各轮 loop 的 challenge probe 汇总]

### 8. Formal Red Team Result
[阶段 5 输出摘要]

### 9. Verdict
- **Action Class**: Act / Watch with Trigger / Trade-only / Basket-only / Reject / Needs Primary Evidence
- **Confidence**: High / Medium / Low
- **Time Horizon**: 6 months / 1-2 years / 3-5 years

### 10. Invalidation Triggers
[什么数据会推翻 thesis]

### 11. Watch Protocol
[阶段 6 输出]
```

如果无法给出上述任何一项，必须明确说明原因：证据不足、财务桥断裂、关键 frontier blocked，还是研究范围过大。
