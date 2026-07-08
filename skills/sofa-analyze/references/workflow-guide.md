# SOFA OSINT Workflow Guide

> 详细流程文档。SKILL.md 只保留核心骨架；所有详细阶段流程、模式要点和主线程指南在此。
> 按需 Read，不必一开始就加载。

---

## 目录

1. [Pre-Stage 0: Methodology Alignment](#pre-stage-0)
2. [Stage 0: Intake + Framing](#stage-0)
3. [Stage 1: Provisional Frontier Plan](#stage-1)
4. [Stage 2: Evidence Frontier Loop（核心引擎）](#stage-2)
5. [Stage 3: Thesis + Financial Bridge](#stage-3)
6. [Stage 4: Formal Red Team](#stage-4)
7. [Stage 5: Final Verdict](#stage-5)
8. [Stage 6: Watch Protocol](#stage-6)
9. [Ticker Dive 模式要点](#ticker-dive)（简要，详见 `references/ticker-dive-guide.md`）
10. [Sector Hunt 模式要点](#sector-hunt)（简要，详见 `references/sector-hunt-guide.md`）
11. [主线程指南](#main-thread-guide)
12. [搜索预算与停止规则](#search-budget)

---

## Pre-Stage 0: Methodology Alignment {#pre-stage-0}

**目的**：确保主线程在设计 frontier 之前已内化 Serenity 方法论。

### 强制动作（必须按顺序执行）

1. **Read `methodology.md`** — 完整阅读，理解 Serenity 的核心哲学（供应链分层、瓶颈识别、证据分级）
2. **Read supply-chain-mapping method card** — 理解供应链映射的具体方法论
3. **撰写 Methodology Alignment Note** — 写入 `research_workflow.md`，记录：
   - 本次研究主题与 Serenity 方法论的对应关系
   - 需要特别注意的方法论要点
   - 预期的供应链层级结构假设

### 禁止事项

- ⛔ **不得跳过 Pre-Stage 0** — 即使对研究对象非常熟悉
- ⛔ **不得在未阅读 methodology.md 的情况下设计 frontier** — 方法论是 frontier 设计的基础，不是参考
- ⛔ **不得将 Pre-Stage 0 与 Stage 0 合并** — 这是独立的认知校准步骤

---

## Stage 0: Intake + Framing {#stage-0}

### 路由判断

**→ Ticker Dive 信号**：具体公司名、ticker、供应链地位、投资价值
**→ Sector Hunt 信号**：行业方向、技术趋势、宏观主题、瓶颈在哪

⛔ 不确定时必须询问用户，禁止猜测。

### Light Framing Search（轻量搜索）

**目的**：
1. 确认对象
2. **校准时效性**（最近是否有财报/公告/KOL传播/价格异动/**行业会议**）
3. 理解用户意图

**强制搜索项**（至少 3 个）：
1. `"[ticker/company] news last 7 days"`
2. `"[industry] news last 30 days"`
3. `"[ticker] earnings conference product launch 2026"`
4. `"[industry] trade show conference 2026"`（如 Computex, OFC, GTC, ECOC）

**工具**：AnySearch 优先（英文目标）/ configured search tool 优先（中文目标），详见 [search-strategy.md](search-strategy.md)

**禁止**：深度检索供应链、形成 bull/bear thesis、引用 KOL 作为核心证据、给出投资结论。

### Step 3 — Demand Decomposition（需求拆解，强制）

**目的**：将研究对象的需求从终端应用逐层拆解到原材料，防止 frontier 设计遗漏关键层级。

**Layer 0→5 "剥洋葱"框架**：

| Layer | 内容 | 示例 |
|-------|------|------|
| Layer 0 | 终端应用/市场需求 | AI训练、数据中心、EV |
| Layer 1 | 系统级需求 | GPU服务器、电池包 |
| Layer 2 | 子系统/模块 | 光模块、散热模组、电芯 |
| Layer 3 | 器件/组件 | 激光器、热管、正极材料 |
| Layer 4 | 材料/工艺 | InP晶圆、石墨、锂矿 |
| Layer 5 | 原材料/设备 | 稀有气体、CVD设备 |

**行业适配原则**：上表示例来自硬件/制造供应链。Layer 0→5 是一个**结构框架**，不是行业模板。对非制造业研究对象，主线程必须自行映射每层含义：
- **生物科技**：治疗需求 → 药物形态（小分子/大分子/CGT）→ CDMO/CRO 产能 → 关键起始物料/色谱树脂 → 发酵/纯化产能 → 监管审批/专利独占期
- **国防科技**：作战需求 → 武器平台 → 子系统/传感器 → 核心元器件（FPA/RF）→ 特种材料/军用级芯片 → 出口管制/ITAR/安全审查
- **SaaS/平台**：用户需求 → 应用层 → 中间件/API → 基础设施/数据中心 → 芯片/网络 → 数据主权/合规

**每层需要识别**：
- 2-3 个关键节点（公司/技术/产品）
- 瓶颈候选（供给集中度高、认证周期长、扩产困难的节点）
- 份额类型关注（独占/寡占/多供应商体系）

**输出**：Demand Decomposition Sketch，写入 `research_workflow.md`

**为什么强制**：frontier 设计如果遗漏了某个关键层级，后续所有 loop 都无法弥补。需求拆解是 frontier 规划的地基。

### Step 4 — Blind Spot Scan（盲区扫描，强制）

**目的**：在 frontier 设计之前，主动搜索对立观点和被忽视的风险。

**6 类强制搜索查询**：

1. **Bear case**: `"[company/industry] bear case risks 2026"`
2. **Short thesis**: `"[company] short thesis overvalued"`
3. **Overhyped**: `"[technology/trend] overhyped bubble concerns"`
4. **Overlooked risks**: `"[company/industry] overlooked risks underappreciated"`
5. **Alternatives**: `"[technology/approach] alternatives replacement threat"`
6. **Demand slowdown**: `"[industry] demand slowdown deceleration risk"`

**搜索工具**：英文 → AnySearch 优先，中文 → configured search tool 优先。详见 [search-strategy.md](search-strategy.md)。

**输出**：Blind Spot Report，写入 `research_workflow.md`

**为什么强制**：主动的对立搜索比被动等待 Red Team 更有效——在 frontier 设计阶段就纳入 contrarian 视角，可以避免 confirmation bias。

⛔ **禁止跳过 Blind Spot Scan 直接进入 Stage 1。**

### 输出：Framing Intent Contract + Decomposition Sketch + Blind Spot Report

Stage 0 is complete only when `framing_contract.json` is complete and its managed mirror is rendered inside `research_workflow.md` (the `<!-- SOFA:framing-contract:start/end -->` block). The Framing Intent Contract is the machine-readable authority for user intent; the rendered mirror is narration. Record intent through the mutation CLI (the only supported mutation path):

```bash
python scripts/framing_intake.py "<workspace>" init
python scripts/framing_intake.py "<workspace>" set --field mode --value ticker
python scripts/framing_intake.py "<workspace>" set --field research_posture --value fresh
python scripts/framing_intake.py "<workspace>" set --field time_horizon --value "6-12 months"
python scripts/framing_intake.py "<workspace>" set --field market_scope --value "US public market"
python scripts/framing_intake.py "<workspace>" set --field risk_appetite --unknown-accepted
python scripts/framing_intake.py "<workspace>" set --field output_expectation --value "decision memo"
python scripts/framing_intake.py "<workspace>" set --field report_language --value zh
python scripts/framing_intake.py "<workspace>" set --field budget_appetite --unknown-accepted
python scripts/framing_intake.py "<workspace>" resolve-subject --name "Coherent Corp" --ticker COHR --exchange NYSE --method deterministic_quote
python scripts/framing_intake.py "<workspace>" status
```

Field rules: `mode` (`ticker`/`sector`), `research_posture` (`fresh`/`verify-narrative`/`revisit`/`compare`), and subject resolution (`confirmed_name`, at least one `ticker` + `exchange` in ticker mode, `resolution_method`) are required and may **not** use the `unknown-accepted-by-user` sentinel. The preference fields (`time_horizon`, `market_scope`, `risk_appetite`, `output_expectation`, `report_language`, `budget_appetite`) accept the sentinel so the contract never blocks a user who declines to state a preference, but silent omission is not valid. Posture changes frontier design templates only; it never changes loop, challenge, or red-team floors. Record disambiguation candidates with `add-candidate` (all four of `--name`/`--ticker`/`--exchange`/`--reason` required) and clarification outcomes with `add-clarification`.

近期语境校准（最近关键事件，包括行业会议、产品发布、财报）仍以 prose 写在 Framing Intent Contract 之上，作为人读补充；契约字段是 authority。

```markdown
【Demand Decomposition Sketch】
Layer 0: [终端应用] → 关键节点: [...], 瓶颈候选: [...]
Layer 1: [系统级] → 关键节点: [...], 瓶颈候选: [...]
Layer 2: [子系统] → 关键节点: [...], 瓶颈候选: [...]
Layer 3: [器件] → 关键节点: [...], 瓶颈候选: [...]
Layer 4: [材料] → 关键节点: [...], 瓶颈候选: [...]
Layer 5: [原材料] → 关键节点: [...], 瓶颈候选: [...]

【Blind Spot Report】
Bear case: [主要看空论点]
Short thesis: [做空论点]
Overhyped concerns: [过度炒作风险]
Overlooked risks: [被忽视的风险]
Alternatives threat: [替代技术/方案]
Demand slowdown risk: [需求放缓风险]
```

---

## Stage 1: Provisional Frontier Plan {#stage-1}

列出 3-5 个候选 frontier（每个是一个待验证的具体 claim 或问题）。向用户展示，让用户选择优先方向。

每个 frontier 包含：
- 核心问题
- 1-3 条 Key Claims
- 优先来源类型
- 初始证据等级预期
- Stop/Continue 条件

用户接受初始 frontier set 后，立即为每个方向注册 lifecycle ID，并启动第一个要执行的 frontier：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" add --name "[frontier display name]" --source initial --at-loop 1
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" start F1
```

对每个 accepted frontier 重复 `add`；只对当前要执行的第一个 frontier 运行 `start`。Registry ID（如 `F1`, `F2`, `F3`）是机器绑定 key。Display name 可以随着研究理解变清晰而调整，但 `evidence_ledger.md` 的 loop header 必须保留稳定 ID。

---

### Research Posture 对 frontier 设计的影响

frontier 设计前读取 `framing_contract.json` 的 `research_posture`（Stage 0 已记录，禁哨兵）：

- `fresh`：默认流程，无额外要求。
- `verify-narrative`：第一个 frontier 必须对传入叙事取 contrarian 方向——传入叙事按 D 级线索处理，该 frontier 的 Key Claims 直接检验叙事最脆弱的前提。
- `compare`：对比对象各自独立走完整 dive（两个 workspace 或先后两轮），最后做对比 synthesis；不新增研究模式。
- `revisit`：本阶段仅记录；revisit 工作流属 Phase 8，落地前按 `fresh` 执行并在 workflow 中注明。

## Stage 2: Evidence Frontier Loop（核心引擎）{#stage-2}

### 核心原则

**每个 pursued frontier 必须跑到 3-loop Frontier Review**，然后通过 `frontier_review.py` 记录为 `Continued` 或 review-based `Retired`。

**禁止**：未通过 lifecycle command 记录状态前切换或进入 Stage 3。Ticker Dive 在 3 loops 前只能用 standalone `retire` 提前结束 `blocked` 或 `invalidated` frontier；Sector Hunt 还允许 barren mapping direction 用 `barren` 提前结束。

### 每轮 Loop 的 6 步

**Step 1 — Frontier Packet**（主线程写）

追加到 `evidence_ledger.md`：
```markdown
## Loop {N}: F{id} - {Frontier Name}

### Frontier Packet
- Frontier: [本轮要推进的具体边界]
- Key Claims: [1-3 条要验证的原子命题]
- Expected Evidence: [优先寻找的来源类型]
- Challenge Focus: [Challenge Probe 重点质疑什么]
- Stop/Continue Criteria: [什么结果算继续/停止]
```

**Step 2 — Frontier Scout**（派遣 subagent worker）

读取 `prompts/scout_prompt.md` 获取角色模板，填入 Frontier Packet，派遣 subagent。

⛔ prompt 中禁止包含：thesis、股价、市值、其他 subagent 输出、完整 evidence_ledger。

**Step 3 — Evidence Ledger Update + Synthesis Notes**（主线程写）

1. Read scout 文件，提取关键发现，追加到 `evidence_ledger.md`
2. **强制**：写 2-3 句话到 `research_workflow.md` 的"综合分析笔记"区——记录本轮发现对 thesis 的影响、与其他 loop 的关联或矛盾、对下一轮 frontier 优先级的启示

**Step 4 — Challenge Probe**（派遣 subagent worker）

从 evidence_ledger 提取本轮 1-3 条 claim 摘要（不超过 200 字）。读取 `prompts/challenge_prompt.md`，派遣 subagent。

⛔ Challenge Probe 不知道 thesis、不知道 Scout 完整输出、不知道 bull case。

**Step 5 — Gate Scorecard**（主线程填）

在 `research_workflow.md` 的 Evidence Loop Tracker 表中填写：

| 维度 | 评分选项 |
|------|---------|
| Map Delta | None / Minor / Material / Structural |
| Evidence Delta | None / Upgrade / Downgrade / Conflict |
| Claim Delta | Unchanged / Confirmed / Weakened / Refuted / Split |
| Decision Delta | None / Ranking / Action Class / Risk Class / Stop |
| Next Yield | High / Medium / Low / Blocked |

评分标准详见 `{PLUGIN_DIR}/skills/sofa-analyze/references/knowledge/evidence-grading.md`。

**Step 6 — Continue/Stop Decision**（主线程决策）

- **Continue current frontier**: 如果 Frontier Review 不 due，且 Map Delta ≥ Material 或 Evidence Upgrade，且 Next Yield ≥ Medium，可以回到 Step 1 写同一 frontier 的下一轮。
- **Review gate**: 如果当前 frontier 已达到或超过一个未记录的 3-loop review boundary，必须先记录 `Continued` 或 review-based `Retired`，不得直接切换、开启下一轮或进入 Stage 3。
- **Switch frontier**: 只有当前 frontier 已有 lifecycle resolution（`Continued`、`Retired`，或允许的 early standalone `retire`）时，才可以启动另一个 `New` frontier 或 `reactivate` 一个 `Continued` frontier。
- **Early out-of-band retire**: 3 loops 前只能用 standalone `retire` 处理允许的 early categories；Ticker Dive 允许 `blocked`、`invalidated`，Sector Hunt 还允许 `barren`。
- **Escalate to Stage 3**: 只有 `gate_check.py "{WORKSPACE}" stage_2 stage_3` lifecycle gate 通过后才能进入 Stage 3；这要求没有 `Active` 或 `New` frontier，至少一个 `Continued` frontier，且每个 `Continued` frontier 都有 >=3 derived loops。

Step 6 后立即运行 Frontier Review 检查：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" check-review
```

如果 `check-review` 显示某个 frontier due，下一轮 loop 必须暂停，直到记录 review decision。即使 ledger 已经写到 loop 4/5，只要对应 3-loop boundary 尚未记录 review，它仍然 due：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Continued --rationale "[why this frontier still creates material evidence yield]"
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Retired --category answered_out --rationale "[why the 3-loop review retires it]"
```

3-loop review-based retirement 只允许 `answered_out`、`bad_pick`、`superseded`。如果使用 `bad_pick` 或 `superseded`，替换上例中的 category 值即可。

3-loop review 之外的提前结束使用 standalone `retire`：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" retire F{id} --category blocked --reason "[why this frontier cannot be pursued before review]"
```

Ticker Dive early standalone retire 允许 `blocked`、`invalidated`。Sector Hunt early standalone retire 允许 `blocked`、`invalidated`、`barren`。一旦 frontier 已经 review-due，不要用 standalone `retire` 绕过 review；必须用 `record --decision Retired`（或 review 事务里的 `--retire`，由 CLI 给目标 frontier 留下 review decision）。`Continued` 是 durable 状态；之后如果要继续推进这个 frontier，必须显式运行 `reactivate F{id}`。不要把 early categories 写成 review-based `record --decision Retired` category。

### Serendipity Loop（每 3 个 frontier 后执行）

**触发条件**：每完成 3 个 frontier 的 evidence loop 后执行一次。

**目的**：搜索相邻但非直接相关的领域，发现可能改变核心假设的意外信息。

**搜索方向**（每个方向至少 1-2 个查询）：
- **Upstream-of-upstream**: 供应商的供应商，原材料的原材料
- **Downstream-of-downstream**: 客户的客户，终端应用的终端
- **Parallel tech**: 平行技术路线，可能替代或增强当前技术
- **Regulatory**: 监管政策变化、贸易限制、环保法规
- **Macro**: 宏观经济因素、利率、汇率、地缘政治

**搜索工具**：英文 → AnySearch 优先，中文 → configured search tool 优先。详见 [search-strategy.md](search-strategy.md)。

**输出**：Serendipity Findings，写入 `research_workflow.md` 的 Synthesis Notes 区。

**评估要求**：
- Serendipity 发现是否改变了 Layer 0 的需求假设？
- 是否产生了新的 frontier 候选？
- 是否需要重新设计后续 frontier 的优先级？

### ⛔ 禁止压缩循环

主线程**不得**因为以下原因压缩 loop 数量或跳过 frontier：
- "时间不够" / "已经搜了很多" / "看起来方向很清楚" / "用户可能等不及" / "这个 frontier 不太重要"

**循环次数是下限，不是目标。** 证据薄弱时主动延长。Gate Scorecard 的 "Stop" 必须基于连续两轮无实质 delta。

### Lifecycle 数量要求

- **Ticker Dive**: 3-8 个 frontier；每个 pursued frontier 必须跑到 3-loop Frontier Review，然后 `Continued` 或 `Retired`。3 loops 前只能用 standalone `retire` 提前结束，category 允许 `blocked` 或 `invalidated`。
- **Sector Hunt**: 3-5 个 mapping direction；kept direction 必须跑到 3-loop Frontier Review 并成为 `Continued`。Barren direction 可在 1-2 loops 后用 standalone `retire --category barren` 提前结束。
- 进入 Stage 3 前必须没有 `Active` 或 `New` frontier，至少有一个 `Continued` frontier，且每个 `Continued` frontier 都有不少于 3 个 derived loops。

---

## Stage 3: Thesis + Financial Bridge {#stage-3}

### 3a. Initial Thesis（主线程综合分析）

主线程是唯一拥有全量上下文的组件。综合所有 loop 的 evidence_ledger、scout/challenge 返回、Gate Scorecard 形成 thesis。

**要求**：
- 不是简单拼接，而是跨 loop 关联推理
- 识别证据之间的交叉验证或矛盾
- 标注认知演进（如果某 loop 发现改变了之前 loop 的理解）

**Ticker Dive thesis 格式**：
> "[公司] 在 [层级] 是 [角色]，因为 [核心 claim]，证据等级 [grade]，财务传导 [状态]。"

**Sector Hunt**：按 12 维 Chokepoint Scoring 排序（详见 [Sector Hunt 模式要点](#sector-hunt)）。

### 3b. Pre-Mortem（事前验尸，强制）

**目的**：假设 thesis 在 6 个月后失败，识别最可能的失败原因并搜索验证。

**执行步骤**：

1. **假设 thesis 已死** — 设定场景："6 个月后，这个投资 thesis 被证明是错误的"
2. **列出 3 个最可能的"死因"** — 基于当前证据和已知风险
3. **搜索验证每个死因** — 英文 → AnySearch 优先，中文 → configured search tool 优先。详见 [search-strategy.md](search-strategy.md)
4. **评估每个死因的概率和影响** — High/Medium/Low
5. **撰写 Pre-Mortem 分析** — 写入 `research_workflow.md` 的 Pre-Mortem 区

**Pre-Mortem 输出格式**：

```markdown
【Pre-Mortem Analysis】
假设：[Thesis] 在 6 个月内失败

死因 1: [描述]
- 概率: [High/Medium/Low]
- 影响: [描述]
- 搜索验证结果: [发现]

死因 2: [描述]
- 概率: [High/Medium/Low]
- 影响: [描述]
- 搜索验证结果: [发现]

死因 3: [描述]
- 概率: [High/Medium/Low]
- 影响: [描述]
- 搜索验证结果: [发现]

对 Thesis 的修正建议: [如有]
```

⛔ **禁止跳过 Pre-Mortem 直接进入 Financial Bridge。**

### 3c. Cognitive Frame Switching（认知框架切换，强制）

**目的**：通过多个分析框架审视 thesis，避免单一视角盲区。

**4 个强制分析框架**：

1. **Porter's Five Forces** — 分析行业竞争结构：供应商议价力、买方议价力、新进入者威胁、替代品威胁、现有竞争者强度
2. **Christensen Disruptive Innovation** — 分析颠覆性创新风险：当前技术是否面临低端颠覆或新市场颠覆？
3. **Soros Reflexivity** — 分析反身性：市场预期是否正在改变基本面？价格行为是否在创造自我实现的预言？
4. **Historical Analogy** — Read `analogical-lens.md` 获取方法论，寻找历史类比案例并评估适用性

**每个框架需要回答**：
- 该框架揭示了什么 Serenity 供应链分析未揭示的风险或机会？
- 该框架是否改变了 thesis 的核心 claim？
- 是否需要增加新的 frontier 来验证该框架提出的问题？

**输出**：Cognitive Frame Analysis，写入 `research_workflow.md`

⛔ **禁止仅使用 Serenity 供应链框架** — 至少完成上述 4 个框架的分析。

### 3d. Financial Bridge

派遣 Financial Bridge Analyst subagent worker（读取 `prompts/financial_bridge_prompt.md`）。

⛔ Financial Bridge 和 Red Team 不可在同一消息中派遣。

**财务数据获取（三路分流）**：结构化数据 → `python {PLUGIN_DIR}/scripts/fetch_financials.py TICKER`（yfinance，10 模块：quote/profile/income/balance/cashflow/valuation/holders/recommendations/earnings/dividends）；英文定性信息 → AnySearch + configured fetch/deep-read tool 获取 filings、transcripts、IR slides；中文定性信息 → configured search tool + configured fetch/deep-read tool 获取 A 股公告、港股年报。详见 [search-strategy.md](search-strategy.md)。

---

## Stage 4: Formal Red Team (Socratic Debate) {#stage-4}

### 核心原则

Red Team 不是"风险提示"，而是**强制压力测试**。它必须攻击 thesis 的核心承重结构。

**辩论循环**：主线程 ↔ Red Team 至少 2-3 轮。主线程不是机械接受 Red Team 的反馈，而是**自主拆解、自主搜索补充证据、逐条回应**。

### 无状态适配

Host subagent workers are treated as **stateless** unless the adapter explicitly guarantees persistent worker memory.

因此，辩论必须通过**文件系统**持久化：
- `redteam/round1_redteam.md` — Red Team Round 1 提问
- `redteam/round1_defense.md` — 主线程 Round 1 回应
- `redteam/round2_redteam.md` — Red Team Round 2 追问（基于 Round 1 defense）
- `redteam/round2_defense.md` — 主线程 Round 2 回应
- `redteam/round3_redteam.md` — Red Team Round 3 最终评估
- `redteam/round3_thesis_revision.md` — 主线程最终修订

### Round 1: Socratic Inquiry

**Step 1 — 派遣 Red Team subagent worker（苏格拉底式提问）**

输入：完整 thesis + claim ledger + evidence grade summary
输出：`redteam/round1_redteam.md`

Red Team 通过苏格拉底式追问暴露隐含假设，不直接给结论。

**Step 2 — 主线程 Defense（自主搜索 + 逐条回应）**

主线程必须：
1. **阅读** `redteam/round1_redteam.md`
2. **自主搜索补充证据**：对 Red Team 质疑的 claim，按搜索策略搜索新材料（英文 → AnySearch 优先，中文 → configured search tool 优先）
3. **逐条回应**：对每个追问，明确立场（接受/反驳/补证据/承认不确定）
4. **修订 thesis**：标注哪些 claim 被保留/降级/放弃
5. **写入**：`redteam/round1_defense.md`

⛔ 禁止机械接受 Red Team 结论。主线程必须自主判断。

**主线程 Defense 文件格式**：

```markdown
# Round {N} Defense: Main Thread Response to Red Team

## 自主搜索补充
| 搜索目的 | 搜索关键词 | 发现 | 证据等级 |
|---------|-----------|------|---------|
| ... | ... | ... | ... |

## 逐条回应

### 追问 1: [Red Team 的问题]
**Red Team 原问题**: ...
**主线程立场**: [接受 / 反驳 / 补证据 / 承认不确定]
**回应**: ...
**对 Thesis 的影响**: [无 / 降级 / 放弃 / 需修订]

## Thesis 修订
| Claim ID | 原 Grade | 新 Grade | 修订原因 |
|----------|---------|---------|---------|
| ... | ... | ... | ... |

## 新发现
- ...
```

### Round 2: Deepening Inquiry

**Step 3 — 派遣 Red Team subagent worker（基于 defense 的更深追问）**

输入：`round1_redteam.md` + `round1_defense.md`（完整对话历史）
输出：`redteam/round2_redteam.md`

Red Team 基于主线程的 defense：
- 如果主线程补足了证据 → 承认并转向其他弱点
- 如果主线程回避了问题 → 直接指出
- 如果主线程的 defense 暴露了新的隐含假设 → 继续追问

**Step 4 — 主线程 Defense（再次自主搜索 + 回应）**

同 Round 1 Step 2，写入 `redteam/round2_defense.md`

### Round 3: Adversarial Re-score

**Step 5 — 派遣 Red Team subagent worker（最终评估）**

输入：前两轮完整对话历史
输出：`redteam/round3_redteam.md`

Red Team 给出：
- 最终评估：Intact / Weakened / Refuted
- 哪些 core claims 存活
- 哪些被损坏
- 推荐的 verdict 调整

**Step 6 — 主线程最终修订**

主线程：
1. 综合三轮对话，修订 thesis
2. 明确标注每个 claim 的最终状态
3. 写入 `redteam/round3_thesis_revision.md`

### Round 4+: Extended Inquiry（主线程裁量）

当 Round 3 后仍存在重大未决问题，主线程可决定继续辩论。

**文件命名规则**：
- `redteam/round{N}_redteam.md` — Red Team 第 N 轮提问
- `redteam/round{N}_defense.md` — 主线程第 N 轮回应

**Round 4+ 的执行规则**：
- Red Team 基于所有前轮对话历史继续追问
- 主线程必须自主搜索补充证据（英文 → AnySearch 优先，中文 → configured search tool 优先）
- 每轮遵循与 Round 1-3 相同的 Defense 格式

**Round 结构总览**：

| Round | 状态 | 说明 |
|-------|------|------|
| Round 1 | 强制 | Socratic Inquiry — 苏格拉底式提问 |
| Round 2 | 强制 | Deepening Inquiry — 基于 defense 的更深追问 |
| Round 3 | 标准/推荐 | Adversarial Re-score — 最终评估 |
| Round 4+ | 主线程裁量 | Extended Inquiry — 仅在核心问题未解决时继续 |

### 辩论停止条件

- **最少 2 轮**（Round 1 + Round 2）
- **标准 3 轮**
- **主线程可延长**：如果 Round 3 后仍有重大未决问题，主线程可决定 Round 4+
- **停止信号**：连续两轮 Red Team 没有提出新的有效追问，或主线程 defense 完全补足所有质疑

### 典型 Red Team 追问维度

- 这个 bottleneck 是否被夸大？
- 这家公司是否只是多供应商体系中的小份额？
- 合作公告是否不等于订单？
- 客户映射是否只是 one-hop / two-hop 弱推断？
- 该技术路线是否可能推迟或被替代？
- 有效产能是否真的稀缺，还是扩产已经在路上？
- 当前估值是否已经 price-in？
- 资本结构是否会吞掉 upside？
- KOL 公开讨论是否制造了反身性价格行为？
- thesis 是否依赖单一未验证 claim？

---

## Stage 5: Final Verdict {#stage-5}

**进入前强制校验**：运行 `scripts/validate_dossier.py`。如果 `DOSSIER INVALID`，禁止生成 Final Dossier。

主线程综合所有 workspace 文件生成 Final Verdict。

**输出必须包含**：
- Action Class: Act / Watch with Trigger / Trade-only / Basket-only / Reject / Needs Primary Evidence
- Confidence: High / Medium / Low
- Time Horizon: 6 months / 1-2 years / 3-5 years
- Invalidation Triggers（具体可观测事件）
- Watch Protocol（升级/降级触发 + 复盘日期）

**Action Class 前提条件**：
- **Act**: 核心 claim B 级以上 + Financial Bridge Intact + Red Team Intact + 有 catalyst clock
- **Watch with Trigger**: 方向对但关键证据未到位
- **Reject**: Red Team Refuted 或 Financial Bridge 断裂
- **Needs Primary Evidence**: 核心 claim 只有 C/D 级证据

---

## Stage 6: Watch Protocol {#stage-6}

1. 生成 Watch Protocol（基于 Stage 5 综合分析推理）
2. 将最终报告写入文件：`{SUBJECT}_SOFA_Report_{YYYY-MM-DD}.md`
3. 写入或复制到 `{WORKSPACE}/reports/` 目录

---

## Ticker Dive 模式要点 {#ticker-dive}

> **完整 Stage 2-5 流程见 `references/ticker-dive-guide.md`。** 此处仅保留快速参考。

### 核心问题

> 这家公司是否处在某个被市场低估的关键依赖节点？如果是，它的 bottleneck 到底是什么、证据等级多高、财务能否传导、反证是否足够强？

### 阶段 1: Company Reality Check

**在任何 bull thesis 之前，先确认公司真实业务。**

必须收集：
1. 产品与 segment
2. 收入结构（segment / geographic / top customers）
3. 客户结构（公开 vs 推断 / 集中度）
4. 财务状态（GM / OM / FCF / cash）
5. 融资结构（ATM / convert / warrants / SBC / debt）
6. 管理层表述（最近 earnings call）
7. 历史业务 vs 新业务（叙事依赖的新业务占收入多少？）

### 阶段 2: 链条位置判断

回答：
1. 该公司位于哪条技术/供应/客户链？
2. 它在链条的哪一层？（系统 / 器件 / 材料 / 原料）
3. 它是核心瓶颈、可替代供应商、二供、试样对象，还是生态露出？
4. 关键关系是公开确认、间接推断还是 KOL 叙事？
5. 该关系是否已进入量产、订单、收入或毛利？
6. 若 thesis 正确，收入弹性有多大？
7. 若 thesis 错误，哪个 claim 最先被证伪？
8. 当前价格是否已经 price-in？

### 完成定义

必须输出 **Actionable Thesis Dossier**：
1. Company Reality
2. Thesis Statement
3. Dependency / Customer Map
4. Claim Ledger
5. Evidence Grade Summary
6. Financial Bridge
7. Challenge Probe Notes
8. Formal Red Team Result
9. Verdict（Action Class + Confidence + Time Horizon）
10. Invalidation Triggers
11. Watch Protocol

---

## Sector Hunt 模式要点 {#sector-hunt}

> **完整 Stage 2-5 流程见 `references/sector-hunt-guide.md`。** 此处仅保留快速参考。
> **域知识参考见 `domains/sector-hunt.md`。**

### 核心问题

> 这个方向里的主流受益者是谁？市场已经看见了哪一层？继续沿技术架构、供应链和客户链下钻后，哪些节点可能是真正有错配的 bottleneck candidates？

### 阶段 1: 确认架构迁移

第一问不是"有哪些股票"，而是：

> **这个方向是否存在明确的 architecture shift 或 demand regime shift？**

判断标准：
- 是否存在"从 A 到 B"的不可逆趋势？
- 迁移是否改变了物理层面的依赖关系？
- 新架构中是否出现了旧架构中不存在的瓶颈层？
- 是否有 demand regime shift（需求量级的突变）？

### 阶段 2: 构建分层供应链图谱

按 market cap bucket 组织：

| Bucket | 角色 |
|--------|------|
| Mega-cap anchor | 方向确认锚点 |
| Large-cap direct winner | 主流直接受益者 |
| Mid-cap execution winner | 执行确定性高但弹性小 |
| Small-cap convex bottleneck | 潜在高弹性瓶颈 |
| Micro-cap speculative | 高风险线索 |
| Private / pre-IPO | 不可买但作为供应链证据 |

### 阶段 3: Chokepoint Scoring（12 维）

| 维度 | 问题 |
|------|------|
| Demand Certainty | 需求增长有多确定？ |
| Supply Concentration | 供给有多集中？ |
| Substitutability | 有多难替代？ |
| Qualification Cycle | 客户认证周期多长？ |
| CapEx Difficulty | 扩产有多难？ |
| Pricing Power | 议价权有多强？ |
| Customer Concentration | 客户是否集中？ |
| Evidence Quality | 证据等级有多高？ |
| Financial Translation | 能否传导为收入？ |
| Valuation Mismatch | 市值 vs 战略价值错配多大？ |
| Liquidity / Dilution Risk | 流动性和稀释风险？ |
| Catalyst Visibility | 催化剂是否可见？ |

### 完成定义

输出 **Bottleneck Map + Ranked Target Queue**：
- Architecture Shift
- Layered Supply Chain Map
- Chokepoint Scoring Matrix
- Ranked Candidate Queue（Tier 1/2/3）
- Red Team Summary
- Recommended Next Steps

---

## 主线程指南 {#main-thread-guide}

### 你是分析师，不是调度器

主线程是整个研究流程中唯一拥有全量上下文的角色。价值不只是"派遣 subagent 然后拼接返回结果"，而是：

- **跨 loop 关联推理**：Loop 3 的发现可能改变 Loop 1 证据的含义
- **证据冲突解决**：两个 scout 结论矛盾时，判断哪个更可信
- **Thesis 演进追踪**：维护 provisional → initial → post-red-team → final 的一致性
- **最终综合判断**：所有证据 + 所有 subagent 分析 → 一个可行动的 verdict

### 持久记录（强制三层体系）

上下文窗口 = 易失内存，文件系统 = 持久磁盘。

| 文件 | 用途 | 写入时机 |
|------|------|---------|
| `evidence_ledger.md` | 证据台账（What was found） | 每轮 Step 3 |
| `research_workflow.md` 综合分析笔记 | 推理过程（What it means） | 每轮 Step 3、Stage 3/4/5 |
| `frontier_registry.json` | Machine-readable lifecycle authority；不要手工编辑 | 由 `frontier_review.py` 管理 |
| `research_workflow.md` Frontier Review / Discovery managed blocks | Human-readable lifecycle narration；由 `frontier_review.py` 在 `record` review flows 和 portfolio discovery actions 中渲染 | Standalone `retire` 更新 registry；之后的 managed block render 可能反映该状态 |
| Host progress tracker | 进度跟踪（Where we are） | 每个 Stage 开始/结束、每次决策 |

**为什么强制**：长研究会话可能跨越多次上下文压缩。如果分析推理只存在于上下文中而不落盘，压缩后将无法理解"为什么得出了这个 thesis"。

### 综合分析笔记写入时机

- **每轮 Loop Step 3 后（强制）**：读完 scout 返回、提取证据到 ledger 之后，立即写 2-3 句话
- Stage 3a 形成 thesis 时：跨 loop 推理过程
- Stage 4 Red Team 返回后：逐条回应和 thesis 修订推理
- Stage 5 Final Verdict 时：从全部证据到 verdict 的完整推理链

### 三大核心义务（Three Core Obligations）

主线程的价值不仅在于协调 subagent，更在于履行以下三项不可替代的义务：

**义务一：Demand Decomposition（Stage 0 强制）**

主线程必须在 Stage 0 完成 Layer 0→5 的需求拆解。这是 frontier 设计的地基，不得委托给 subagent，不得简化为"大致了解"。

- 执行时机：Stage 0 Step 3
- 输出：Demand Decomposition Sketch in research_workflow.md
- 验证标准：每层至少识别 2-3 个关键节点和瓶颈候选

**义务二：自主搜索补充证据（Stage 4 强制，Stage 2/3 推荐）**

主线程必须主动搜索补充证据，而非仅依赖 subagent 返回的结果。尤其在 Red Team 质疑后，主线程必须自主发起搜索来验证或反驳。

- Stage 4（强制）：每轮 Red Team Defense 必须包含自主搜索补充（见 Defense 文件格式）
- Stage 2（推荐）：在综合分析笔记写入时，如发现证据缺口，主动搜索填补
- Stage 3（推荐）：Pre-Mortem 和 Cognitive Frame Switching 中主动搜索验证

**义务三：禁止压缩（Stage 2 + Stage 4 强制）**

主线程不得以任何理由压缩 loop 数量、跳过 frontier 或减少 Red Team 轮次至最低要求以下。

- Stage 2：循环次数是下限，不是目标。证据薄弱时主动延长
- Stage 4：最少 2 轮辩论，标准 3 轮。不得在最低轮次前停止
- 搜索预算：不得低于最低要求（见[搜索预算与停止规则](#search-budget)）
- 违反后果：如果压缩了循环，研究结论的可信度自动降级

---

## 搜索预算与停止规则 {#search-budget}

### 停止规则

- 每轮 Loop 后检查 Gate Scorecard
- **连续两轮无 Map/Evidence/Claim/Decision Delta → Stop**
- 关键证据 Blocked → Needs Primary Evidence + Stop
- 已有 coherent thesis 且搜索增益 < 压力测试价值 → Escalate to Red Team
- 用户可随时停止、转向或加预算

### 搜索预算最低要求

⛔ 以下为**最低要求，不是建议**。主线程不得低于以下预算。

- Ticker Dive: 3-8 个 frontier；每个 pursued frontier 跑到 3-loop Frontier Review，除非提前 standalone `retire` 为 `blocked` 或 `invalidated`
- Sector Hunt: 3-5 个 mapping direction；kept direction 跑到 3-loop Frontier Review，barren direction 可提前 `retire --category barren`
- 每轮 Scout: 5-15 个独立搜索
- 每轮 Challenge Probe: 不超过 5 个验证性搜索
- Red Team: 1-3 轮，每轮 5-10 个搜索

⛔ **禁止**：以"时间不够"、"已经搜够了"或任何理由将搜索次数降至最低要求以下。低于最低要求的研究不得进入下一阶段。

---

*Workflow Guide v4.2 | SOFA, adapted from Serenity OSINT v3.6.0*
