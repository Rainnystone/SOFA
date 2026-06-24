# Sector Hunt Guide — Stage 2-5

> Sector Hunt 模式的 Stage 2-5 完整流程。由 SKILL.md 路由加载。
> 公共阶段（Pre-Stage 0 ~ Stage 1, Stage 6）见 workflow-guide.md。
> 域知识参考见 `domains/sector-hunt.md`。

---

## 核心差异（vs Ticker Dive）

Sector Hunt 的目的不是验证某个公司的 thesis，而是**对一个行业方向做详尽 mapping，浮出一张值得 Ticker Dive 的候选清单**。

- Ticker Dive 的 loop = 验证 claim（Scout → Challenge → Scorecard）
- Sector Hunt 的 loop = 扩展 mapping（Sector Mapper → Coverage Challenge → Mapping Scorecard）
- Ticker Dive 的最终产出 = Actionable Thesis（Act/Watch/Reject）
- Sector Hunt 的最终产出 = Bottleneck Map + Ranked Target Queue（推荐 Ticker Dive 清单）

---

## Stage 2: Mapping Loops（核心引擎）

### Loop 结构（每轮 6 步）

**Step 1 — Mapping Packet**（主线程写）

用 Edit 追加到 `{WORKSPACE}/evidence_ledger.md`：

```markdown
## Loop {N}: F{id} - {Mapping Direction}

### Mapping Packet
- Direction: [本轮要扩展的 mapping 方向，如 "Layer 3→5 vertical deepening"]
- Current Ladder Summary: [当前 dependency ladder 的简要状态]
- Target Layers: [本轮要覆盖的层级]
- Expected Node Types: [预期发现的节点类型：公司/技术/材料/监管]
- Depth Target: [目标深度：行业报告级 / 公司级 / 交叉验证级]
- Stop/Continue Criteria: [什么结果算继续/停止]
```

然后运行：`python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" loop`

**Step 2 — Sector Mapper**（派遣 subagent）

Read `{PLUGIN_DIR}/scripts/prompts/sector_mapper_prompt.md` → 填入 Mapping Packet + 当前 dependency ladder 摘要 + 交付路径 `{WORKSPACE}/maps/mapping_loop{N}_{direction_slug}.md` → 发送。

⛔ prompt 中禁止包含：thesis、投资建议、其他 subagent 输出。

**Step 3 — Dependency Ladder Update + Chokepoint Pre-Score**（主线程写）

1. Read mapper 文件 → 提取新节点追加到 `maps/dependency_ladder.md`
2. 对新发现的每个节点做 **Chokepoint Pre-Score**（快速 1-3 分制，不是完整 12 维打分）：

| 维度 | Pre-Score (1-3) | 快速判断依据 |
|------|-----------------|-------------|
| Supply Concentration | | 供应商数量 |
| Substitutability | | 替代难度 |
| CapEx Difficulty | | 扩产周期 |
| Evidence Quality | | 来源等级 |

3. **强制**：写 2-3 句分析性推理到 `research_workflow.md` 综合分析笔记（本轮 mapping 对整体图谱的影响、新发现的瓶颈候选、下一轮方向启示）

**Step 4 — Coverage Challenge**（派遣 subagent）

Read `{PLUGIN_DIR}/scripts/prompts/coverage_challenge_prompt.md` → 填入当前 dependency ladder 摘要 + 交付路径 `{WORKSPACE}/coverage/coverage_loop{N}.md` → 发送。

⛔ Coverage Challenge 不知道 thesis、不知道 Sector Mapper 完整输出。

**Step 5 — Mapping Scorecard**（主线程填）

Read mapper + coverage 文件，在 `research_workflow.md` Evidence Loop Tracker 填一行：

| 维度 | 评分选项 |
|------|---------|
| Map Breadth Delta | None / Minor / Material / Structural |
| Map Depth Delta | None / New Layer / New Nodes / New Bottleneck |
| New Nodes Found | 0 / 1-3 / 4-10 / 10+ |
| Chokepoint Candidates | None / Weak / Strong / Double Bottleneck |
| Next Yield | High / Medium / Low / Blocked |

**Step 6 — Continue/Stop Decision**（主线程决策）

- **Continue**: 发现新层级/新瓶颈节点 且 Next Yield ≥ Medium → 同方向继续
- **Review**: kept mapping direction 达到或超过一个未记录的 3-loop review boundary → 暂停下一轮，先记录 Frontier Review decision
- **Early retire**: barren direction 可在 1-2 loops 后用 standalone `retire --category barren` 提前结束；`blocked` 或 `invalidated` 也必须走 standalone `retire`

记录到 Decision Log。

Step 6 后立即运行：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" check-review
```

如果有 due direction，下一轮 loop 必须阻塞，直到记录 3-loop Frontier Review。loop 4/5 仍可能 due：只要 loop 3 boundary 还没有 review record，就不能继续绕过：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Continued --rationale "[why this mapping direction should remain in the durable queue]"
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Retired --category answered_out --rationale "[why the 3-loop review retires this direction]"
```

3-loop review-based retirement 只允许 `answered_out`、`bad_pick`、`superseded`。如果使用 `bad_pick` 或 `superseded`，替换上例中的 category 值即可。

3-loop review 之外的提前结束使用 standalone `retire`：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" retire F{id} --category barren --reason "[why this mapping direction is barren]"
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" retire F{id} --category blocked --reason "[why this direction cannot be pursued before review]"
```

Sector Hunt early standalone retire 允许 `barren`、`blocked`、`invalidated`。如果使用 `invalidated`，替换上例中的 second command category 值即可。一旦 direction 已经 review-due，不要用 standalone `retire` 绕过 review；必须用 `record --decision Retired`（或 review 事务里的 `--retire`，由 CLI 给目标 frontier 留下 review decision）。

Do not use `barren`, `blocked`, or `invalidated` as `record --decision Retired` categories.

### Mapping 方向类型

每轮 Mapping Packet 应明确属于以下哪类方向：

| 方向类型 | 说明 | 示例 |
|---------|------|------|
| Vertical Deepening | 沿已有链条继续向下钻 | Layer 2→3→4→5 |
| Horizontal Broadening | 在同一层级发现更多竞争者/替代者 | 补充 Layer 3 的更多供应商 |
| Alternative Path | 搜索替代技术路线/平行供应链 | 绕开当前 bottleneck 的其他路径 |
| Cross-Chain | 搜索相邻行业的交叉供应链 | 军工和民用的共享材料 |
| Regulatory/Geo | 深入地理/监管/出口许可层 | Layer 5 的出口管制分析 |

### Lifecycle 数量要求

- Sector Hunt 使用 3-5 个 mapping 方向。
- Kept mapping direction 必须跑到 3-loop Frontier Review，并记录为 `Continued`。
- Barren direction 可在 1-2 loops 后用 standalone `retire --category barren` 提前结束。
- 必须覆盖至少 2 种方向类型（如 vertical + alternative）
- 进入 Stage 3 前必须没有 `Active` 或 `New` direction，至少一个 `Continued` direction，且每个 `Continued` direction 都有 >=3 derived loops。

### Serendipity Loop（每 3 个 mapping 方向后）

同 Ticker Dive：搜索相邻领域，发现可能改变 Layer 0 假设的意外信息。

### 禁止压缩

不得因任何理由压缩 loop。mapping 的广度是下限，不是目标。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_2
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_2 stage_3
```

---

## Stage 3: Chokepoint Scoring + Financial Screen

### 3a. Chokepoint Scoring（完整 12 维打分）

基于完整 dependency ladder（Stage 2 所有 mapping 的累积产出），对所有候选节点做完整 12 维 Chokepoint Scoring：

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

**产出**：写入 `research_workflow.md` 的 `## Chokepoint Scoring Matrix` 区 + `## Ranked Candidate Queue` 区。

排序后分为三个 Tier：
- **Tier 1: Priority Ticker Dive Targets**（Score 高 + Evidence 高 + 值得深挖）
- **Tier 2: Watch / Basket Candidates**（方向对但单一风险过高）
- **Tier 3: Rejected / Deprioritized**（证据不足或不成立）

### 3b. Mapping Integrity Pre-Mortem（强制）

假设最终推荐的 Tier 1 列表有重大遗漏：
- 最可能遗漏了什么层级？
- 最可能遗漏了什么替代路径？
- Chokepoint Scoring 是否有确认偏误（过度依赖已有信息）？
- 搜索验证每个潜在遗漏 → 写入 Pre-Mortem 区

⛔ 禁止跳过 Pre-Mortem。

### 3c. Cognitive Frame Switching（强制）

同 Ticker Dive：用至少 2 个框架重新分析（Porter / Christensen / Soros / 历史类比）。

### 3d. Financial Screen（Tier 1 候选轻量筛查）

对 Tier 1 候选（通常 3-5 个上市公司）做轻量财务筛查。复用 `financial_bridge_prompt.md`，dispatch 时指定 lightweight screen mode：

- Market cap vs strategic control mismatch
- Revenue geography 是否支持 bottleneck 叙事
- Recent insider activity
- Dilution risk（ATM / convert / warrants / SBC）
- Liquidity check

交付：`{WORKSPACE}/financials/{TICKER}_screen.md`

⛔ Financial Screen 和 Red Team 不可在同一消息中派遣。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_3
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_3 stage_4
```

---

## Stage 4: Mapping Integrity Review

与 Ticker Dive 的 Red Team 结构相同（最少 2 轮，推荐 3 轮），但攻击目标不同：

**Sector Hunt Red Team 攻击的是 mapping 完整性**，而非单个 thesis：

- 是否遗漏了关键层级？
- 某个 bottleneck 是否被高估？（如：只是多供应商体系中的小份额？）
- 替代路径是否被系统性低估？
- Chokepoint Scoring 是否有确认偏误？
- Double bottleneck 判断是否基于充分证据？
- 非上市公司（Private/pre-IPO）是否被正确定位为"证据节点"而非"投资标的"？

### Round 结构

同 Ticker Dive：Round 1 Socratic Inquiry → Defense → Round 2 Deepening → Defense → Round 3 Adversarial Re-score → Thesis Revision。

文件命名：`redteam/round{N}_redteam.md` + `redteam/round{N}_defense.md` + `redteam/round3_thesis_revision.md`

Red Team prompt：复用 `red_team_prompt.md`，dispatch 时传入 Ranked Candidate Queue + Chokepoint Scoring Matrix + dependency ladder 摘要（替代 thesis）。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_4
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_4 stage_5
```

---

## Stage 5: Ranked Target Queue

**进入前强制校验**：`python {PLUGIN_DIR}/scripts/validate_dossier.py "{WORKSPACE}"`
> **注意**：validate_dossier.py 的 ERROR 级检查（maps/coverage/ 文件数、dependency_ladder.md 存在性）必须全部通过才能进入 Stage 5。Architecture Shift Brief、Chokepoint Scoring Matrix、Ranked Candidate Queue 缺失时为 WARNING 级（记录但不阻塞）——但建议确保这三项已填写，以保证报告完整性。

主线程综合全量上下文，产出最终的 Sector Hunt Report。

### 最终产出结构

```markdown
## Sector Hunt Report: [Theme]

### Architecture Shift
[Stage 0 Architecture Shift Brief 摘要]

### Layered Dependency Map
[Stage 2 累积的完整 dependency ladder 摘要]

### Chokepoint Scoring Matrix
[Stage 3 完整 12 维打分表]

### Ranked Candidate Queue
[Stage 3 排序结果 + Stage 4 Red Team 后的修订]

#### Tier 1: Priority Ticker Dive Targets
| Company | Ticker | Chokepoint Score | Key Thesis | Dive Readiness |
|---------|--------|-----------------|-----------|----------------|

#### Tier 2: Watch / Basket Candidates
| Company | Ticker | Chokepoint Score | Key Thesis | Risk Flag |
|---------|--------|-----------------|-----------|-----------|

#### Tier 3: Rejected / Deprioritized
| Company | Ticker | Score | Reason |
|---------|--------|-------|--------|

### Red Team Summary
[Stage 4 关键发现和修订]

### Recommended Next Steps
- Priority Ticker Dive targets: [列表 + 建议的 frontier 方向]
- Basket candidates: [列表]
- Watch-only: [列表]
- Rejected nodes: [列表]
- Unresolved high-value frontiers: [列表]

### Dive Readiness Score (per Tier 1 candidate)
- Evidence sufficiency: [是否已有足够证据启动 Ticker Dive]
- Key open questions: [Ticker Dive 需要优先回答的问题]
- Suggested first frontier: [Ticker Dive Stage 1 建议的 frontier]
```

**注意**：Sector Hunt 不产出 Action Class（Act/Watch/Reject）——个别标的只有进入 Ticker Dive 后才形成完整投资动作判断。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_5
```

---

## 搜索预算

- Sector Hunt: 3-5 个 mapping 方向；kept direction 跑到 3-loop Frontier Review，barren direction 可提前 `retire --category barren`
- 每轮 Sector Mapper: 10-20 个独立搜索（mapping 需要更广的搜索）
- 每轮 Coverage Challenge: 10-15 个广度扫描搜索
- Red Team: 1-3 轮，每轮 5-10 个搜索

---

## 与 sector-hunt.md 域知识的对应关系

| 域知识文件内容 | 对应本指南阶段 |
|-------------|--------------|
| 阶段 1: 确认架构迁移 | Stage 0 Architecture Shift Brief |
| 阶段 2: 构建分层供应链图谱 | Stage 2 Mapping Loops |
| 阶段 3: Chokepoint Scoring | Stage 3 Chokepoint Scoring |
| 阶段 4: 候选 Red Team | Stage 4 Mapping Integrity Review |
| 阶段 5: Final Output | Stage 5 Ranked Target Queue |

---

*Sector Hunt Guide v1.0 | Serenity OSINT v3.6.0*
