# 映射原型库（Mapping Archetypes）

> 从 Serenity 案例蒸馏的 8 种 bottleneck archetype。用于供应链映射和行业猎捕时的类型识别。

## Archetype 1: Physical Dependency / Material Bottleneck

**识别特征**：
- 终端需求扩张 → 某个物理材料/原料成为硬约束
- 材料有纯度/良率/认证等不可压缩的工艺门槛
- 扩产周期长（年级别），不能用钱快速解决
- 供应商高度集中，有效合格产能少

**典型案例**：AXTI — InP substrate / source material for AI photonics

**关键问题**：
- 讨论的是哪个等级（如 6N laser-grade vs 4N industrial-grade）？
- 有效合格产能 vs 名义产能？
- 客户认证后的可交付产能？
- 可出口至目标客户的产能？

---

## Archetype 2: Hidden Supplier / Customer Graph

**识别特征**：
- 公司没有公开披露全部客户关系（NDA 保护）
- 但公开蛛丝马迹可以构建 confidence-tiered 客户图谱
- Wayback/HTML inspection 揭示供应商变更
- 融资额匹配推断 NDA 客户占位符
- 地域收入匹配推断隐藏客户

**典型案例**：SIVE — Sivers Photonics 的隐藏 hyperscaler 客户图谱

**关键问题**：
- 客户映射是 public confirmed / high-confidence inferred / likely / one-hop / two-hop？
- 推断链条是否可交叉验证？
- NDA 客户即使高置信度，也可能不到量产

---

## Archetype 3: Demand Anomaly

**识别特征**：
- 某个需求信号被市场忽视或错误定价
- 需求来自新应用场景，尚未被传统分析框架覆盖
- 公司收入尚未反映需求变化

**典型案例**：RPI — Raspberry Pi 被社交媒体驱动的需求异常

---

## Archetype 4: Regulatory Chokepoint

**识别特征**：
- 出口管制、许可证、环保法规等创造供给约束
- 管制同时证明供应链战略价值和尾部风险
- 需要区分"管制 = 利好"和"管制 = 供应连续性风险"

**关键问题**：
- 管制是单向利好还是双刃剑？
- 如果被管制方的收入依赖被管制市场，风险如何？

---

## Archetype 5: Capacity / Equipment Bottleneck

**识别特征**：
- 某个设备/工具的交付周期成为全行业约束
- 设备供应商少，扩产需要特定工艺积累
- 下游即使有资本也无法快速增加产能

**关键问题**：
- 设备交付周期是多少？
- 是否有替代设备可以绕开？
- 设备供应商自身的供应链约束？

---

## Archetype 6: Testing / Validation Bottleneck

**识别特征**：
- 产品需要通过特定认证/测试才能进入客户供应链
- 认证周期长，替换供应商成本高
- 一旦认证通过，形成 strong switching cost

---

## Archetype 7: Software / Ecosystem Migration Bottleneck

**识别特征**：
- 技术架构迁移（如 agent security, identity management）
- 新生态系统中关键组件供应商少
- 迁移窗口期内形成临时 bottleneck

---

## Archetype 8: Capital-Structure-Driven Mispricing

**识别特征**：
- 公司因资本结构（可转债、warrants、SBC、dilution）被市场错误定价
- 战略价值 vs 市值严重不匹配
- 需要区分"真实 mispricing"和"市场正确反映了稀释风险"

---

## Archetype 交叉规则

- 一个公司可能同时属于多个 archetype（如 AXTI = Physical Bottleneck + Regulatory + Capital Mispricing）
- 多个 archetype 叠加 = 更高 convexity，但也更高 complexity 和 risk
- 必须分别验证每个 archetype 的独立 claim，不能因为一个成立就假定另一个成立
