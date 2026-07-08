# Ticker Dive Guide — Stage 2-5

> Ticker Dive 模式的 Stage 2-5 完整流程。由 SKILL.md 路由加载。
> 公共阶段（Pre-Stage 0 ~ Stage 1, Stage 6）见 workflow-guide.md。
> 进入本 guide 各 stage 前，Stage 0 的 Framing Intent Contract 必须已完备并通过 stage_0 gate（`python {PLUGIN_DIR}/scripts/framing_intake.py "{WORKSPACE}" status` 检查字段状态；契约与 CLI 详见 workflow-guide.md Stage 0）。
> 域知识参考见 `domains/ticker-dive.md`。

---

## Stage 2: Evidence Frontier Loops（核心引擎）

### Loop 结构（每轮 6 步，严格顺序）

**Step 1 — Frontier Packet**（主线程写）

用 Edit 追加到 `{WORKSPACE}/evidence_ledger.md`：

```markdown
## Loop {N}: F{id} - {Frontier Name}

### Frontier Packet
- Frontier: [本轮要推进的具体边界]
- Key Claims: [1-3 条要验证的原子命题]
- Expected Evidence: [优先寻找的来源类型]
- Challenge Focus: [Challenge Probe 重点质疑什么]
- Stop/Continue Criteria: [什么结果算继续/停止]
```

然后运行：`python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" loop`

**Step 2 — Frontier Scout**（派遣 subagent）

Read `{PLUGIN_DIR}/scripts/prompts/scout_prompt.md` → 填入 Frontier Packet + 交付路径 `{WORKSPACE}/scouts/loop{N}_{frontier_slug}.md` → 发送。

推荐组装命令：`python {PLUGIN_DIR}/scripts/assemble_dispatch.py --workspace "{WORKSPACE}" --role scout --packet-file <packet.md> --loop {N} --frontier-slug <frontier_slug>`（手工填充为 degraded fallback）。

⛔ prompt 中禁止包含：thesis、股价、市值、其他 subagent 输出、完整 evidence_ledger。

**Step 3 — Evidence Ledger Update + 逐 Loop 推理笔记**（主线程写）

Read scout 文件 → 提取关键发现追加到 `evidence_ledger.md` → **强制**用 Edit 追加 2-3 句分析性推理到 `research_workflow.md` 综合分析笔记区。

**Step 4 — Challenge Probe**（派遣 subagent）

从 evidence_ledger.md 提取本轮 claim 摘要（≤200 字）。Read `{PLUGIN_DIR}/scripts/prompts/challenge_prompt.md` → 填入 + 交付路径 `{WORKSPACE}/challenges/loop{N}_challenge.md` → 发送。

推荐组装命令：`python {PLUGIN_DIR}/scripts/assemble_dispatch.py --workspace "{WORKSPACE}" --role challenge --packet-file <claim_summary.md> --loop {N}`。

⛔ Challenge Probe 不知道 thesis、Scout 完整输出、bull case。

**Step 5 — Gate Scorecard**（主线程填）

Read scout + challenge 文件，在 `research_workflow.md` Evidence Loop Tracker 填一行：

| 维度 | 评分选项 |
|------|---------|
| Map Delta | None / Minor / Material / Structural |
| Evidence Delta | None / Upgrade / Downgrade / Conflict |
| Claim Delta | Unchanged / Confirmed / Weakened / Refuted / Split |
| Decision Delta | None / Ranking / Action Class / Risk Class / Stop |
| Next Yield | High / Medium / Low / Blocked |

**Step 6 — Continue/Stop Decision**（主线程决策）

- **Continue**: Map Delta ≥ Material 且 Next Yield ≥ Medium → 同一 frontier 下一轮
- **Review**: frontier 达到或超过一个未记录的 3-loop review boundary → 暂停下一轮，先记录 Frontier Review decision
- **Early retire**: 3 loops 前只有 `blocked` 或 `invalidated` 可用 standalone `retire` 提前结束
- **Escalate to Red Team**: 没有 `Active` 或 `New` frontier，至少一个 `Continued` frontier，且每个 `Continued` frontier 都有 >=3 derived loops → Stage 3

记录到 Decision Log。

Step 6 后立即运行：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" check-review
```

如果有 due frontier，下一轮 loop 必须阻塞，直到记录 3-loop Frontier Review。loop 4/5 仍可能 due：只要 loop 3 boundary 还没有 review record，就不能继续绕过：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Continued --rationale "[why this frontier should stay in the durable queue]"
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" record F{id} --decision Retired --category answered_out --rationale "[why the 3-loop review retires this frontier]"
```

3-loop review-based retirement 只允许 `answered_out`、`bad_pick`、`superseded`。如果使用 `bad_pick` 或 `superseded`，替换上例中的 category 值即可。

3-loop review 之外的提前结束使用 standalone `retire`：

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" retire F{id} --category blocked --reason "[why this frontier cannot be pursued before review]"
```

Ticker Dive early standalone retire 只允许 `blocked`、`invalidated`。如果使用 `invalidated`，替换上例中的 category 值即可。一旦 frontier 已经 review-due，不要用 standalone `retire` 绕过 review；必须用 `record --decision Retired`（或 review 事务里的 `--retire`，由 CLI 给目标 frontier 留下 review decision）。

Do not use `blocked` or `invalidated` as `record --decision Retired` categories.

### Lifecycle 数量要求

- Ticker Dive 使用 3-8 个 frontier。
- 每个 pursued frontier 必须跑到 3-loop Frontier Review，然后记录为 `Continued` 或 review-based `Retired`。
- 3 loops 前只能用 standalone `retire` 提前结束，category 只允许 `blocked` 或 `invalidated`。
- 进入 Stage 3 前必须没有 `Active` 或 `New` frontier，至少一个 `Continued` frontier，且每个 `Continued` frontier 都有 >=3 derived loops。

### Serendipity Loop（每 3 个 frontier 后）

搜索相邻领域（上游的上游、下游的下游、平行技术、监管动态、宏观经济），至少 3 个搜索方向。结果写入 Synthesis Notes。

### 禁止压缩循环

不得因任何理由压缩 loop 或跳过 frontier。循环次数是下限，不是目标。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_2
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_2 stage_3
```

---

## Stage 3: Thesis + Financial Bridge

### 3a. Initial Thesis（主线程综合分析）

综合全量上下文形成 thesis statement。要求：跨 loop 关联推理、识别证据交叉验证或矛盾、标注认知演进。

Thesis 格式：`"[公司] 在 [层级] 是 [角色]，因为 [核心 claim]，证据等级 [grade]，财务传导 [状态]。"`

### 3b. Pre-Mortem（强制）

假设 thesis 在 6 个月后失败 → 列 ≥3 个最可能死因 → 搜索验证每个死因 → 写入 Pre-Mortem 区。

⛔ 禁止跳过 Pre-Mortem。

### 3c. Cognitive Frame Switching（强制）

用至少 2 个框架重新分析 thesis：Porter 五力、Christensen 颠覆性创新、Soros 反身性、历史类比（Read `references/analogical-lens.md`）。输出写入 Cognitive Frame Analysis 区。

⛔ 禁止仅使用 Serenity 供应链框架。

### 3d. Financial Bridge

派遣 Financial Bridge Analyst：Read `{PLUGIN_DIR}/scripts/prompts/financial_bridge_prompt.md` → 填入 thesis + 财务数据 → 交付 `{WORKSPACE}/financials/{TICKER}_bridge.md`。

推荐组装命令：`python {PLUGIN_DIR}/scripts/assemble_dispatch.py --workspace "{WORKSPACE}" --role financial --packet-file <bridge_input.md> --ticker {TICKER}`。

⛔ Financial Bridge 和 Red Team 不可在同一消息中派遣。

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_3
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_3 stage_4
```

---

## Stage 4: Formal Red Team (Socratic Debate)

最少 2 轮，推荐 3 轮。

### Round 1: Socratic Inquiry

**Step 1**：Read `{PLUGIN_DIR}/scripts/prompts/red_team_prompt.md` → 填入 thesis + claim ledger + evidence + Financial Bridge → 交付 `redteam/round1_redteam.md`

推荐组装命令：`python {PLUGIN_DIR}/scripts/assemble_dispatch.py --workspace "{WORKSPACE}" --role redteam --packet-file <round_input.md> --round 1`。

**Step 2**：主线程 Defense——阅读 Red Team → **自主搜索补充证据** → 逐条回应（Accept / Rebut / Downgrade / Add Evidence / Rewrite / Reject）→ 修订 thesis → 写入 `redteam/round1_defense.md`

⛔ 禁止机械接受 Red Team 结论。

### Round 2: Deepening Inquiry

**Step 3**：派遣 Red Team（基于 Round 1 完整历史）→ `redteam/round2_redteam.md`
**Step 4**：主线程 Defense → `redteam/round2_defense.md`

### Round 3（推荐）: Adversarial Re-score

**Step 5**：派遣 Red Team（最终评估：Intact / Weakened / Refuted）→ `redteam/round3_redteam.md`
**Step 6**：主线程最终修订 → `redteam/round3_thesis_revision.md`

### Round 4+（主线程裁量）

重大未决问题时继续。文件命名：`round{N}_redteam.md` + `round{N}_defense.md`

### Defense 文件格式

```markdown
# Round {N} Defense

## 自主搜索补充
| 搜索目的 | 搜索关键词 | 发现 | 证据等级 |

## 逐条回应
### 追问 1: [Red Team 的问题]
**立场**: [接受 / 反驳 / 补证据 / 承认不确定]
**回应**: ...
**对 Thesis 的影响**: [无 / 降级 / 放弃 / 需修订]

## Thesis 修订
| Claim ID | 原 Grade | 新 Grade | 修订原因 |
```

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_4
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_4 stage_5
```

---

## Stage 5: Final Verdict

**进入前强制校验**：`python {PLUGIN_DIR}/scripts/validate_dossier.py "{WORKSPACE}"`

主线程综合全量上下文生成 Final Verdict。详细格式见 `references/final-report.md`。

**输出必须包含**：
- Action Class: Act / Watch with Trigger / Trade-only / Basket-only / Reject / Needs Primary Evidence
- Confidence: High / Medium / Low
- Time Horizon: 6 months / 1-2 years / 3-5 years
- Invalidation Triggers（具体可观测事件）
- Watch Protocol

**Action Class 前提条件**：
- **Act**: 核心 claim B 级以上 + Financial Bridge Intact + Red Team Intact + catalyst clock
- **Watch with Trigger**: 方向对但关键证据未到位
- **Reject**: Red Team Refuted 或 Financial Bridge 断裂
- **Needs Primary Evidence**: 核心 claim 只有 C/D 级证据

### 完成条件

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_5
```

---

## 搜索预算

- Ticker Dive: 3-8 个 frontier；每个 pursued frontier 跑到 3-loop Frontier Review，除非提前 standalone `retire` 为 `blocked` 或 `invalidated`
- 每轮 Scout: 5-15 个独立搜索
- 每轮 Challenge Probe: ≤5 个验证性搜索
- Red Team: 1-3 轮，每轮 5-10 个搜索

---

*Ticker Dive Guide v1.0 | SOFA, adapted from Serenity OSINT v3.6.0*
