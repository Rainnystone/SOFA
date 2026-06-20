# Serenity 方法论手册

> 蒸馏自 Serenity（@aleabitoreddit）公开研究动作，不是投资建议。

## 1. 核心研究动作序列

Serenity 的可蒸馏价值不在于某个持仓或小票偏好，而在于他的研究动作序列：

> 从主流市场已经看见的主题出发，沿着物理依赖、客户关系、供应约束、财务传导和反证路径逐层下钻，直到找到一个能被证据支撑、能被 red-team 压力测试、并能转化成明确投资动作的 bottleneck thesis。

### 第一性原则

- **No thesis claims without evidence.** 没有可引用证据，不得声称 thesis 成立。
- **No conviction without formal red-team.** 没有经过独立红队压力测试，不得给出高 conviction。
- **No action call without financial bridge, catalyst clock, and invalidation conditions.** 没有财务桥、催化剂时钟和失效条件，不得给出投资动作建议。

### 研究动作序列（从 AXTI 和 SIVE 案例蒸馏，适用于科技/硬科技全领域）

1. **确认终端需求迁移**：不问"哪只股票热门"，而问"这个行业扩张的物理约束/技术约束是什么"
2. **从系统层下钻到器件/模块层**：把终端系统拆到关键器件/模块/子系统
3. **从器件层下钻到材料/工艺/设备层**：识别对特殊材料、工艺、设备、EDA 工具等的依赖
4. **建立 supplier share map**：区分全部份额 / 特定等级有效份额 / 可出口份额 / 认证后份额
5. **寻找 double exposure**：同一家公司在多个层级同时出现 = double bottleneck candidate
6. **加入地理和许可层**：制造基地、子公司、JV、出口许可、标准认证、客户地理收入
7. **建模买方行为**：下游客户的抢供博弈、prepayment、长协、战略库存、垂直整合
8. **做 market materiality test**：哪个公司的战略控制力 vs 市值错配最大（不限市值大小）
9. **设置时间窗口**：6 个月 / 2 年 / 5 年分别代表什么
10. **强制 red-team**：替代技术、替代供应商、扩产、客户认证、财务传导

**适用范围**：AI 基础设施、半导体、光通信、电力/新能源、机器人、工业软件、数据基础设施、网络安全、先进制造、材料、设备、特殊工艺、EDA/IP、航空航天、国防科技、生物科技上游工具等。不限于 AI 或任何单一方向。

## 2. Chokepoint Theory（供应链瓶颈理论）

Serenity 将其方法概括为"供应链瓶颈套利"。核心思想：

- 当市场聚焦在终端叙事（如 AI buildout、EV transition、robotics adoption）时，真正的 alpha 可能在第三层、第四层——衬底材料、特殊化学品、精密设备、核心 IP
- 不是"找小票"，而是"找错配"——在任何市值级别的公司中，寻找战略控制力 vs 市场认知的差距
- 关键问题不是"谁在链条上"，而是"哪个节点如果被抢供、断供或提价，会让所有上层公司同时焦虑"

### Bottleneck 识别的核心问题

对于任何候选 bottleneck 节点，必须回答：

1. 这个节点是否真的不可替代？有多少合格替代供应商？
2. 替代供应商的有效产能（不是名义产能）是多少？
3. 扩产需要多长时间？需要什么条件（认证、许可、纯度达标）？
4. 这个节点在下游 BOM 中占比多少？如果占比低但不可缺，下游是否容忍价格大幅上升？
5. 买方是否是少数高 capex、强战略动机的 hyperscaler？
6. 买方之间是否会互相抢供，形成 prisoner's dilemma？
7. 小公司 revenue / market cap 是否足够小，使一点价格或订单变化就产生巨大估值弹性？

## 3. 剥洋葱流程：从终端需求到物理/技术瓶颈

```
终端需求（AI cluster / EV fleet / robotics deployment / 5G buildout / space launch / ...）
    ↓
系统层（整机/平台/基础设施，如 OCS / battery pack / robot controller / base station）
    ↓
子系统/模块层（如 transceiver / BMS / servo / RF front-end）
    ↓
器件层（如 laser diode / IGBT / encoder / GaN HEMT）
    ↓
材料/工艺/设备层（如 InP substrate / SiC wafer / 稀土永磁 / EUV photoresist / 精密轴承）
    ↓
原料/工具/IP层（如 feedstock / 矿产 / EDA license / 核心 IP block / 校准设备）
    ↓
地理/许可/标准层（export permits / 出口管制 / 行业标准认证 / 矿权 / JV 结构）
```

每一层下钻时必须问：
- 为什么供给弹性低？（不是"供不应求"，而是为什么不能用钱解决）
- 纯度/良率/认证/扩产周期/替代材料时间线？
- 是 permanent monopoly 还是 time-window thesis？
- **不限市值**：瓶颈可能在 mega-cap（如 TSMC 在先进制程），也可能在 micro-cap（如某种特殊材料的唯一供应商）。关注的是战略控制力 vs 市值的错配，而不是绝对市值大小。

## 4. 两条主线

### Ticker Dive（个股深潜）

输入：一个具体标的
核心问题：这家公司是否处在某个被市场低估的关键依赖节点？

流程：
1. Company Reality Check — 先确认公司真实业务（产品/segment/收入来源/客户结构/地域/融资）
2. 链条位置判断 — 它在哪个层级？核心瓶颈还是可替代供应商？
3. 证据分层 — 关系是公开确认、间接推断还是 KOL 叙事？
4. 财务传导 — 关系是否已进入量产/订单/收入/毛利？
5. Red-team — 哪个 claim 最先被证伪？
6. Action Class — Act / Watch / Trade-only / Basket-only / Reject / Needs Primary Evidence

### Sector Hunt（行业猎捕）

输入：一个行业/技术方向/宏观主题
核心问题：哪些节点可能是真正有错配的 bottleneck candidates？

流程：
1. 确认 architecture shift — 是否存在明确的技术架构迁移或需求体制转换
2. 分层候选池 — 按 market cap bucket 和风险层级组织（mega-cap anchor → micro-cap speculative）
3. Chokepoint Scoring — 12 维度打分排序
4. 输出 Bottleneck Map + Ranked Target Queue
5. 个别标的只有进入 Ticker Dive 后才形成完整投资动作判断

## 5. 情报循环（非直线流程）

Serenity-style OSINT 不是一次性计划→搜索→报告。核心是情报循环：

> Provisional Frontier Plan → Evidence Frontier Loop → Frontier Gate Evaluation → Revised Plan → Next Evidence Frontier Loop

每轮搜索都应推进一个具体证据前沿。每轮结束评估是否产生真实增量。没有增量就停止、转向、分叉询问用户，或进入 red-team。

## 6. 反确认意识

- **Challenge Probe**（in-loop 局部挑战）：防止当前 frontier 过度解读
- **Formal Red Team**（独立阶段）：攻击完整 thesis，决定最终 conviction

二者必须区分。前者只针对当前 frontier；后者攻击完整 thesis。

## 7. 强制区分事实、推断和叙事

每个重要结论必须区分：
- 已验证事实（A 级一手来源）
- 高可信推断（B 级操作型 OSINT）
- 中低可信线索（C 级行业解读）
- 未验证假设（D 级叙事/线索来源）
- 反方证据
- 仍需 primary evidence 的部分

不分层会导致把所有材料压平成"看起来合理的故事"。
