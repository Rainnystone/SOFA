# 证据等级系统

## Evidence Grade（证据分级）

### A 级：Primary / Hard Evidence（一手硬证据）

- SEC filings: 10-K, 10-Q, 8-K, proxy statements
- 年度报告、earnings transcript、investor presentation
- 客户官网公开确认、供应商官网公开确认
- 正式 press release（公司官方发布）
- 政府合同/补贴/出口许可公告
- 标准组织成员名单（CW-WDM MSA, OIF, etc.）
- 官方招股书/prospectus

**使用规则**：A 级证据可以作为 final conclusion 的核心支撑。

### B 级：Operational OSINT（操作型开源情报）

- Wayback Machine diff（网页历史变更）
- HTML inspection（源码检查，如 alt text、meta tag、隐藏链接）
- 招聘 JD（job posting 分析技术路线和客户线索）
- 专利（patent filing 和引用网络）
- 技术白皮书、会议 slide
- 客户 logo 墙 / 供应商目录 / ecosystem partner page
- 进出口数据（海关/贸易数据库）
- 地域收入（geographic revenue breakdown）
- 采购/招标公告
- 认证名单（qualified vendor list）
- 融资轮金额匹配（funding round amount matching to infer NDA customers）

**使用规则**：B 级可以支撑 high-confidence inference，但必须明确标注为推断而非事实。需要交叉验证。

### C 级：Industry Interpretation（行业解读）

- 行业报告（Yole, LightCounting, McKinsey, GS, etc.）
- Sell-side 研报
- 专家访谈（expert network transcript）
- Podcast 访谈
- 技术博客（公司 CTO 或行业专家撰写）
- 专业媒体报道（Semiconductor Today, EE Times, etc.）

**使用规则**：C 级可以辅助形成 hypothesis 和交叉验证，但不能独立支撑 final conclusion。

### D 级：Narrative / Lead Sources（叙事/线索来源）

- KOL 帖子（X/Twitter, Substack, Reddit）
- 论坛讨论（WSB, StockTwits, 雪球）
- Discord/Telegram 群组
- AI 生成摘要

**使用规则**：D 级只能产生 hypothesis，不能独立支撑 final conclusion。如果 thesis 的关键 claim 只有 D 级证据，必须标注为 Needs Primary Evidence。

---

## Claim Ledger（命题台账）

每条核心 claim 必须作为原子命题记录。模板：

```
Claim ID: CL-001
Claim Statement: [具体命题，如 "AXTI 控制约 25% 全球 InP source material"]
Importance: [Critical / High / Medium / Low]
Supporting Evidence: [列出支撑证据及其 grade]
Counter-Evidence: [列出反向证据及其 grade]
Evidence Grade: [最高级支撑证据的 grade]
Current Confidence: [High / Medium / Low / Speculative]
Missing Proof: [需要什么证据才能升级]
Impact If False: [如果此 claim 被推翻，对 thesis 的影响]
```

**规则**：没有进入 Claim Ledger 的命题，不应进入 final thesis。

---

## 事实-推断-叙事区分

对每个重要结论，必须标注属于以下哪类：

| 类别 | 定义 | 允许的操作 |
|------|------|-----------|
| Verified Fact | A 级来源直接支撑 | 可用于 final conclusion |
| High-Confidence Inference | B 级来源 + 交叉验证 | 可用于 thesis，标注为推断 |
| Low-Confidence Lead | C/D 级来源 | 只能作为 hypothesis |
| Unverified Hypothesis | 逻辑推断，无直接证据 | 标注为需要验证 |
| Counter-Evidence | 任何级别的反向证据 | 必须正面回应 |
| Needs Primary Evidence | 关键证据缺失 | 阻止 Act 结论 |

---

## Frontier Gate Scorecard（前沿关卡评分卡）

每轮 Evidence Frontier Loop 结束后必须填写：

### 1. Map Delta（地图变化）
- **None**: 没有新增节点、边、层级
- **Minor**: 新增边缘节点，不影响主路径
- **Material**: 新增关键节点、关键边、隐藏客户、上游材料、替代供应商、产能/监管层
- **Structural**: 重画了原先地图（如发现原先客户链不成立，或发现更深层 bottleneck）

### 2. Evidence Delta（证据变化）
- **None**: 停留在同类来源
- **Upgrade**: D/C 级线索升级到 B/A 级证据
- **Downgrade**: 原本 strong claim 被发现只靠低级证据
- **Conflict**: 出现同等级或更高等级反向证据

### 3. Claim Delta（命题变化）
- **Unchanged**: 本轮没改变任何核心 claim
- **Confirmed**: 某条 claim 被足够证据支撑
- **Weakened**: 某条 claim 证据不足或被削弱
- **Refuted**: 某条 claim 基本被打掉
- **Split**: 原 claim 被拆成更精确的子命题

### 4. Decision Delta（决策影响）
- **None**: 不影响
- **Ranking**: 改变 Sector Hunt 的候选排序
- **Action Class**: 改变 Ticker Dive 的 Act/Watch/Reject 等判断
- **Risk Class**: 改变风险归类
- **Stop Signal**: 继续搜的边际价值很低

### 5. Next Yield（下一轮预期收益）
- **High**: 有明确路径，可能带来 A/B 级证据或关键地图变化
- **Medium**: 有路径，但收益不确定
- **Low**: 大概率只是重复低质量来源
- **Blocked**: 公开信息无法解决，需要用户/付费源/专家/IR

---

## Continue / Fork / Stop 决策规则

- **Continue**: 本轮 Material/Structural Map Delta 或 Evidence Upgrade，且 Next Yield Medium/High
- **Pivot**: 当前 frontier Next Yield 变 Low，但另一个 frontier Next Yield 更高
- **Fork / Ask User**: 两个以上 frontier 都是 Medium/High，且消耗不同搜索预算
- **Stop**: 连续两轮无 Map/Evidence/Claim/Decision Delta，或关键证据 Blocked
- **Escalate to Red Team**: 已有 coherent initial thesis，继续搜索信息增益低于压力测试价值
