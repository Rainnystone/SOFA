## Final Verdict & Watch Protocol（最终裁决与观察）流程参考

本文档是 SOFA Analyze 的最终裁决流程参考。Serenity OSINT v3.6.0 是方法来源，SOFA 是当前交付包名。

职责：将所有前序研究输出转化为明确的、可行动的、有失效条件的最终裁决。

**不允许以模糊话术结束。** 所谓"掷地有声"不是伪装成绝对确定，而是在当前证据等级下给出明确行动分类和失效条件。

---

## Action Class 定义

允许的结论档位：

### Act

**含义**：证据链和 red-team 后仍成立，可以形成投资动作。

**前提条件**：
- 核心 claim 有 B 级以上证据支撑
- Financial Bridge 完整（未断裂）
- Red Team 后 thesis 仍然 Intact
- 有明确的 catalyst clock

### Watch with Trigger

**含义**：进入观察池，但必须有具体升级触发条件。

**前提条件**：
- 方向对，但关键证据尚未到位
- 必须写清楚：哪个事件/数据会把 Watch 升级为 Act
- 不允许只写"建议继续关注"

### Trade-only

**含义**：只适合短期交易，不适合中长期 thesis。

**适用场景**：
- 有短期催化剂但长期 thesis 不确定
- 市场情绪/流动性驱动，而非基本面驱动
- 需要明确的 exit trigger

### Basket-only

**含义**：方向成立，但单一标的风险过高。

**适用场景**：
- Bottleneck 真实存在，但具体哪家公司胜出不确定
- 需要分散到多个标的
- 单一公司的稀释/地缘/技术风险过高

### Reject

**含义**：核心 claim 被打穿或财务桥断裂。

**适用场景**：
- Red Team 后 thesis 被 Refuted
- Financial Bridge 断裂
- 发现重大未披露风险

### Needs Primary Evidence

**含义**：线索有价值，但关键证据不足，暂不允许行动。

**适用场景**：
- 核心 claim 只有 C/D 级证据
- 关键 frontier Blocked（公开信息无法解决）
- 需要付费源、专家网络、公司 IR 或等待未来事件

---

## Final Verdict 输出格式

```markdown
## Final Verdict: [Company/Theme]

### Action Class
**[Act / Watch with Trigger / Trade-only / Basket-only / Reject / Needs Primary Evidence]**

### Confidence
**[High / Medium / Low]**
（基于证据等级、red-team 结果和 financial bridge 状态）

### Time Horizon
**[6 months / 1-2 years / 3-5 years]**
（明确 thesis 的时间窗口）

### Core Thesis（一句话）
[压缩成一句话的 thesis]

### Top Supporting Evidence（最多 3 条）
1. [证据 + grade + 来源]
2. ...
3. ...

### Top Counter-Evidence（最多 3 条）
1. [反证 + grade + 来源]
2. ...
3. ...

### Financial Bridge Summary
- **Status**: Intact / Partially Broken / Fully Broken
- **Key Metric**: [最关键的财务传导指标]
- **Revenue Timeline**: [何时能看到收入反映]

### Catalyst Clock
| 催化剂 | 预计时间 | 影响 | 类型 |
|--------|---------|------|------|
| [下一次 earnings] | YYYY-Q? | 收入验证 | 验证 |
| [关键客户公告] | YYYY-Q? | 关系确认 | 验证 |
| [产能扩建] | YYYY-Q? | 供给增加 | 双刃剑 |
| [替代技术 milestone] | YYYY+ | 替代可能 | 否定 |

### Invalidation Triggers（失效触发条件）

以下任何一个事件发生，thesis 需要被重新评估：

1. **[具体事件 1]**：[为什么这会推翻 thesis]
2. **[具体事件 2]**：[为什么这会推翻 thesis]
3. **[具体事件 3]**：[为什么这会推翻 thesis]

**不允许只写"建议继续关注后续订单/业绩"。** 必须写清楚：哪个订单、哪次业绩、哪个 revenue line、哪个客户确认、哪个技术 milestone、哪个融资事件会改变判断。

### Next Evidence to Monitor
（在 Watch Protocol 中详述）

### Question Answered（对照原始意图）
定稿前，对照 `framing_contract.json` 确认本报告回答了用户原始问题：读取契约的 `output_expectation`、`time_horizon`、`subject_resolution.confirmed_name`，逐项确认报告覆盖了请求的输出类型、时间框架与对象。`research_posture` 为 `verify-narrative` 时必须显式回应原叙事；`compare` 时必须给出对比结论。如有刻意偏离，必须在报告中说明原因。
```

---

## Watch Protocol（观察协议）

最终不应以"继续关注"结束，而应给出**可执行观察协议**。

```markdown
## Watch Protocol: [Company/Theme]

### 定期检查项
| 信号 | 来源 | 频率 | 升级条件 | 降级条件 |
|------|------|------|---------|---------|
| Earnings revenue | SEC filing | Quarterly | Revenue QoQ > X% | Revenue flat/declining |
| 客户公告 | Press release | Event-driven | Named supplier for Y | Removed from partner page |
| 产能更新 | Earnings call | Quarterly | Capacity expansion on track | Delays announced |
| 价格信号 | Industry report | Monthly | Price increase > X% | Price stable/declining |
| 竞争者扩产 | News / filings | Event-driven | Competitor delays | Competitor ahead of schedule |
| 融资/稀释 | SEC 8-K / Form 4 | Event-driven | No dilution | Offering / ATM / convert announced |
| 技术路线变化 | Patent / conference | Quarterly | No alternative progress | Alternative tech milestone |
| 地缘/监管 | Government notice | Event-driven | Permit renewed | Export restriction tightened |

### 升级触发（Watch → Act）
1. [具体事件 + 为什么这会升级]
2. ...

### 降级触发（Act → Watch / Watch → Reject）
1. [具体事件 + 为什么这会降级]
2. ...

### 复盘日期
- **第一次复盘**: [日期] — 检查 catalyst clock 是否按预期推进
- **第二次复盘**: [日期] — 检查 revenue 是否开始反映
- **Thesis 过期日**: [日期] — 如果到这个日期仍无验证，自动降级为 Reject

### 复盘标准
- 哪些信号已出现？
- 哪些信号未出现？
- 未出现的信号是否仍然预期会出现？
- 是否需要对 thesis 进行修订？
```

---

## 复盘约束

Watch Protocol 的目标是让未来复盘有标准，而不是让 thesis 无限延期。

- 每个 Watch with Trigger 必须有**明确的升级条件**
- 每个 Act 必须有**明确的失效条件**
- 每个 thesis 必须有**过期日**——到了这个日期如果关键验证没出现，自动降级
- 不允许写"长期看好"——必须有 time horizon 和对应的时间节点

---

## 正式研究报告结构

最终裁决不是对话中的一段总结，而是一份可交付的研究报告。报告必须掷地有声——给出明确结论、证据支撑、风险因素和后续行动，不允许模棱两可。

### 报告生成流程

1. 汇总所有前序阶段的输出：
   - `research_workflow.md`（Pre-Stage 0 ~ Stage 5 全流程记录）
   - `frontier_registry.json` 及其 registry-derived `frontier-layer-coverage` managed narration
   - `evidence_ledger.md`（Stage 2 证据台账）
   - `scouts/` 目录下各轮 scout 交付文件
   - `challenges/` 目录下各轮 challenge 交付文件
   - `financials/` 目录下 Financial Bridge 报告
   - `redteam/` 目录下 Red Team 辩论文件（round{N}_redteam.md + round{N}_defense.md + thesis_revision.md）
   - `maps/` 目录下供应链/客户链映射文件（如有）

2. 调用 **docx 技能**（如可用）生成 Word 文档，否则生成 Markdown 文件

3. 文件命名规则：
   - `[SUBJECT]_SOFA_Report_[YYYY-MM-DD].md`（如可用 docx 技能，优先生成 `.docx`）

### Frontier Layer Snapshot 边界

Audit Appendix 必须包含 registry-derived Frontier Layer Snapshot，并明确列出 unrepresented layers、blocked-only layers、retired-only layers、unbound frontiers，以及存在时的 structural lineage facts。报告正文可以说明这些 gap 如何限制 confidence，但 snapshot 只表达 frontier presence/status，不能证明研究充分性。

完整的 company/technology/evidence/double-bottleneck dependency ladder 始终由主线程撰写；frontier structural parent 是研究方向的谱系，不是经济 dependency edge。Snapshot 不得生成或升级 evidence grade、confidence、action class、Ticker conclusion 或 Sector ranked queue。Sector Hunt 仍以 map 和 ranked queue 结束；只有完成 Ticker Dive 或 Ultra Dive，才能使用 action-class language。

### 报告结构模板

```markdown
# [Company/Theme] — SOFA OSINT Research Report

**研究日期**: YYYY-MM-DD
**研究模式**: [Ticker Dive / Ultra Dive / Sector Hunt]
[以下两行只保留当前研究模式对应的一行]
**最终 Action Class（Ticker Dive / Ultra Dive only）**: [Act / Watch / Trade-only / Basket-only / Reject / Needs Primary Evidence]
**最终输出（Sector Hunt only）**: Map + Ranked Candidate Queue
**Confidence**: [High / Medium / Low]
**Time Horizon**: [6 months / 1-2 years / 3-5 years]

---

## 一句话结论

[只保留当前研究模式对应的写法：
- Ticker Dive / Ultra Dive：用一段话给出 action class、核心 thesis、confidence 和 time horizon。
- Sector Hunt：用一段话概括 architecture shift、map 的关键 bottleneck、ranked queue 首选项、confidence 和 time horizon，并给出下一步 dive 方向。
两种模式都不允许用"建议继续关注"式的模糊结尾。]

## 核心 Thesis

[2-3 段阐述核心 thesis，包含 dependency chain 和 bottleneck 论证]

## 证据基础

### 支撑证据（Top 5）
| # | Claim | 证据等级 | 来源 | 关键数据 |
|---|-------|---------|------|---------|
| 1 | | A/B | [来源] | [数据] |

### 反向证据（Top 5）
| # | Counter-Claim | 证据等级 | 来源 | 关键数据 |
|---|--------------|---------|------|---------|
| 1 | | A/B | [来源] | [数据] |

### 证据分布
- A 级（一手硬证据）: X 条
- B 级（操作型 OSINT）: X 条
- C 级（行业解读）: X 条
- D 级（叙事/线索）: X 条

## 供应链/客户链图谱

[Dependency ladder 或 layered map 的可视化描述]

### 关键节点
| 节点 | 层级 | 角色 | 市值 | 证据等级 |
|------|------|------|------|---------|

## 财务桥

### 传导状态
- **Bridge Status**: Intact / Partially Broken / Fully Broken
- Revenue Reality: [当前收入 vs thesis 预期的差距]
- Dilution Risk: [关键稀释风险]
- Valuation Mismatch: [市值 vs 战略价值]

### 催化剂时钟
| 催化剂 | 时间 | 影响方向 |
|--------|------|---------|

## 红队压力测试结果

### 最强反论点
1. [反论点 + 证据 + thesis 回应]
2. ...

### Red Team 后 Thesis 状态
- **Survival**: Intact / Weakened / Refuted
- **Confidence 调整**: [是否降级]

[以下两个最终输出分支只保留当前研究模式对应的一个]

## 最终裁决（Ticker Dive / Ultra Dive）

### Action Class: [具体档位]

**理由**: [为什么是这个档位而不是更高或更低]

### 失效触发条件（Invalidation Triggers）
1. [具体事件] → [为什么推翻 thesis]
2. ...

## Sector Hunt Map + Ranked Queue

### Map Artifact
[主线程撰写的完整 dependency map / layered map，包括关键 bottleneck 与 double-bottleneck facts。]

### Ranked Candidate Queue
[按证据与 mapping rationale 排序的候选队列；列明 tier、排序理由、关键 gap 和建议的下一步 Ticker Dive / Ultra Dive。]

[以下两个 follow-up 分支只保留当前研究模式对应的一个]

## 观察协议（Ticker Dive / Ultra Dive Watch Protocol）

### 升级触发
1. [事件] → [Watch 升级为 Act]

### 降级触发
1. [事件] → [降级为 Reject]

### 复盘日期
- 第一次复盘: [日期]
- Thesis 过期日: [日期]

## Mapping and Queue Review Protocol（Sector Hunt）

### Queue Promotion Triggers
1. [可观测证据] → [候选上调到更高 queue tier，或进入下一步 Ticker Dive / Ultra Dive]

### Queue Downgrade / Deprioritization Triggers
1. [可观测证据] → [候选降低排序、移出 queue 或重开 mapping]

### Map Refresh Triggers
1. [新技术路线、监管变化、供给变化或关键反证] → [需要重绘的节点、层级或 dependency edge]

### 复盘日期
- 第一次 map 复盘: [日期]
- Ranked queue 刷新日: [日期]
- Evidence stale date: [日期]

## Audit Appendix（审计附录）

### Frontier Layer Snapshot
[从 frontier registry 的确定性派生 narration 提取：列明 unrepresented layers、blocked-only layers、retired-only layers、unbound frontiers，以及存在时的 structural lineage facts。仅表达 presence/status，不把它解释为研究充分性。]

### 完整 Claim Ledger
[从 evidence_ledger.md 提取]

### 完整来源列表
[所有 URL 和文件引用]

### 研究过程日志
[各轮 Loop 的 Frontier Packet 和 Gate Scorecard 摘要]
```

### 报告质量检查

报告生成前必须通过以下检查：

1. **按模式结论明确性**: Ticker Dive / Ultra Dive 第一页必须能看到 Action Class 和一句话结论；Sector Hunt 第一页必须能看到 Map Artifact、Ranked Candidate Queue 和一句话结论，且不得包含 Action Class
2. **证据可追溯**: 每个关键 claim 都有来源 URL 或文件引用
3. **反向证据正面呈现**: 不藏在附录或 footnote，而是在正文中有独立章节
4. **触发条件具体**: Ticker Dive / Ultra Dive 的失效条件和 Sector Hunt 的 map/queue 修订条件都必须是具体可观测事件；不允许"如果基本面恶化"这种废话
5. **无模棱两可话术**: 检查并删除以下表达：
   - "建议继续关注"（改为具体观察什么、什么条件下升级/降级）
   - "存在不确定性"（改为具体是什么不确定性、需要什么证据才能消除）
   - "值得深入研究"（改为具体研究什么、用什么方法、什么结果会改变判断）
   - "可能有机会也可能有风险"（改为在什么条件下有机会、什么条件下有风险）
