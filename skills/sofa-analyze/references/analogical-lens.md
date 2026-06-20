# Analogical Lens: 历史 Bottleneck 模式库

> 按需加载。Stage 3 Cognitive Frame Switching 时 Read 此文件，用历史模式识别当前 case 的盲区。
> 不是"找相似"，而是"找模式匹配和关键差异"。
> 搜索工具遵循 [search-strategy.md](search-strategy.md)：英文 → AnySearch 优先，中文 → configured search tool 优先。

---

## 模式 1: 终端叙事超前于物理现实

**特征**：市场需求预测远超实际部署能力，导致供应链"假性短缺"。

**历史案例**：
- **2000 年光纤泡沫**：需求预测 10 倍于实际部署，数百家光纤公司破产
- **2021 年芯片短缺**：恐慌性囤货导致假性短缺，2022 年转为过剩
- **2023 年 AI 服务器**：NVIDIA 订单暴增，但下游云厂商 capex 实际增速低于预期

**触发问题**（当前 case 必须回答）：
- 当前叙事是否比物理约束超前 2-3 年？
- 需求预测是否基于"如果所有计划都实现"的乐观假设？
- 下游客户是否已经在消化库存或推迟订单？

**验证搜索**（AnySearch 英文优先）：
- `"[industry] inventory days 2026"`
- `"[company] order push out delay"`
- `"[end customer] capex guidance cut"`

**跨行业映射**：在任何行业中，只要存在"需求预测 → 物理部署"的时间差，此模式就可能成立。问自己：我的研究对象是否存在类似的叙事-现实时差？

---

## 模式 2: 多供应商体系中的"小份额大叙事"

**特征**：某公司在供应链中只占小份额，但叙事中像占主导地位。

**历史案例**：
- **某 GaN 公司**：声称"下一代充电器核心供应商"，实际份额 <5%，且面临 TI/Infineon 挤压
- **某光芯片公司**：叙事中"AI 光互连核心"，实际只通过间接渠道供货，收入占比 <3%

**触发问题**：
- 份额数据是 Nominal 还是 Qualified？
- 客户是否有多供应商策略？
- 叙事中的"核心地位"是否有收入/订单支撑？

**验证搜索**（AnySearch 英文优先）：
- `"[company] revenue breakdown by customer"`
- `"[company] market share actual vs claimed"`
- `"[customer] multi-sourcing strategy"`

**跨行业映射**：任何存在"关键供应商"叙事但实际为多供应商体系的行业都可能出现此模式。问自己：我的研究对象的"核心地位"是否有收入支撑，还是只有叙事支撑？

---

## 模式 3: Hyperscaler 抢供 → 价格暴涨 → 扩产 → 过剩

**特征**：大客户恐慌性锁定供应 → 价格飙升 → 资本涌入扩产 → 产能过剩 → 价格崩盘。

**历史案例**：
- **2022 年锂价**：从 5 万/吨涨到 60 万/吨，然后跌到 10 万/吨
- **2021 年集装箱**：疫情导致抢箱，价格涨 10 倍，然后暴跌
- **2023 年多晶硅**：光伏需求爆发 → 扩产 → 2024 年价格腰斩

**触发问题**：
- 当前 bottleneck 是 permanent 还是 time-window？
- 扩产周期多长？已有多少扩产计划 announced？
- 价格暴涨是否已触发替代技术/材料的研发加速？

**验证搜索**（AnySearch 英文优先）：
- `"[material] capacity expansion announced 2026"`
- `"[material] price forecast 2027"`
- `"[alternative material] development timeline"`

**跨行业映射**：任何供给弹性低 + 需求突增的市场都会经历此周期。问自己：我的研究对象的供给端是否存在类似的抢供-扩产-过剩循环风险？

---

## 模式 4: 技术路线替代（Leapfrog）

**特征**：市场聚焦当前技术路线，但下一代技术可能直接跳过当前代。

**历史案例**：
- **GaAs → GaN → SiC**：功率器件的三代迁移，每一代都"跳过"中间代
- **LCD → OLED → MicroLED**：显示技术路线，投资 LCD 产线的公司被 leapfrog
- **铜互连 → 光互连**：AI 集群推动光互连跳过传统铜缆升级

**触发问题**：
- 当前技术路线是否可能被跳过？
- 下一代技术的成熟度如何？（实验室/样品/量产）
- 客户是否有动力直接采用下一代技术？

**验证搜索**（AnySearch 英文优先）：
- `"[next gen technology] commercialization timeline"`
- `"[customer] next generation architecture"`
- `"[current technology] obsolescence risk"`

**跨行业映射**：任何技术驱动型行业都存在 leapfrog 风险。问自己：我的研究对象押注的技术路线是否可能被下一代直接跳过？（生物科技：自体→异体细胞疗法；国防：有人→无人跳过混合；能源：锂电→固态跳过增量化学改进）

---

## 模式 5: 监管/政策突变改变供需格局

**特征**：供应链瓶颈看似由市场驱动，实则由政策/监管人为制造。

**历史案例**：
- **稀土出口管制**：中国稀土政策改变全球供应链格局
- **芯片出口管制**：美国 BIS 规则改变 AI 芯片供应链
- **光伏反倾销**：欧盟/美国关税改变全球光伏产能分布

**触发问题**：
- 当前 bottleneck 是否依赖特定国家的政策？
- 政策变化的方向是什么？（收紧/放松/不确定）
- 下游客户是否已在构建"去风险"供应链？

**验证搜索**（AnySearch 英文优先；中文政策用 configured search tool）：
- `"[country] export control [product] 2026"`
- `"[industry] policy change impact"`
- `"[company] geographic diversification strategy"`

**跨行业映射**：任何受监管深度影响的行业都可能出现此模式。问自己：我的研究对象的供需格局是否依赖某个政策假设？如果政策突变，谁会受损？

---

## 模式 6: 买方垂直整合消灭 Bottleneck

**特征**：下游大客户决定自己解决 bottleneck，导致原供应商失去定价权。

**历史案例**：
- **Apple 自研芯片**：从依赖 Intel/Qualcomm 到自研 M 系列，消灭上游 bottleneck
- **Tesla 自研电池**：从依赖松下/CATL 到自研 4680，改变锂供应链格局
- **Amazon 自研服务器**：从依赖 Dell/HP 到自研 Graviton，改变芯片采购模式

**触发问题**：
- 下游大客户是否有垂直整合的动机和能力？
- 是否已有自研/投资的公开信号？
- 如果大客户垂直整合，原供应商的收入弹性还剩多少？

**验证搜索**（AnySearch 英文优先）：
- `"[customer] in-house [technology] development"`
- `"[customer] vertical integration strategy"`
- `"[customer] investment [supplier] JV"`

**跨行业映射**：任何依赖单一瓶颈供应商的客户都有垂直整合动机。问自己：我的研究对象的下游大客户是否已有自研/内化/投资的信号？

---

## 使用指南

1. **Read 此文件**（Stage 3 Cognitive Frame Switching 时）
2. **判断当前 case 匹配哪个模式**（可能匹配多个）
3. **回答该模式的触发问题**
4. **执行验证搜索**（按 search-strategy.md 三路分流：英文 → AnySearch，中文 → configured search tool）
5. **记录关键差异**：当前 case 与历史模式有什么不同？这个差异是机会还是风险？

**核心原则**：历史不会简单重复，但模式会。找到匹配的模式，然后找到关键差异——差异才是 alpha 的来源。

---

*Analogical Lens v3.6.0 | Serenity OSINT*
