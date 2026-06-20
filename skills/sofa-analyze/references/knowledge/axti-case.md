# AXTI 黄金案例：物理瓶颈 / 双重瓶颈 / 地缘许可

> 蒸馏自 Serenity 的 AXTI 研究，用于学习"从终端需求逐层下钻到物理瓶颈"的研究动作。不是投资建议。

## 一句话压缩

AI 集群扩张的瓶颈，正在从 GPU/ASIC 外溢到 optical interconnect/OCS/high-speed transceiver；继续下钻到 InP-based lasers、InP substrates 和 InP source material；AXT/Tongmei 在 InP substrate 与 InP source material 两个层级同时出现，成为"瓶颈的瓶颈"候选。

## 剥洋葱路径

```
Layer 0: AI cluster buildout (hyperscaler capex)
    ↓
Layer 1: Optical interconnect / OCS / 800G-1.6T transceivers
    ↓
Layer 2: EML / DFB / CW laser arrays / receivers
    ↓
Layer 3: InP substrate (AXTI ~30-35%, Sumitomo ~30%, JX ~10-15%)
    ↓
Layer 4: InP source material (Vital ~35%, AXT ~25%, Zhuzhou Keneng ~18%, Dowa ~12%)
    ↓
Layer 5: Tongmei / China export permits / raw material JVs / mines / refineries
```

## Double Bottleneck 发现

AXTI 在 Layer 3（substrate）和 Layer 4（source material）同时出现：
- Substrate: AXTI ~30-35% + Sumitomo ~30% = duopoly
- Source material: Vital ~35% + AXT ~25% = 高度集中

这是 thesis 的核心 convexity 来源：同一家公司在两个层级都有控制权。

## 关键研究动作

1. **从 end-demand 开始，不从 ticker 开始**：先问 AI buildout 的物理约束是什么，AXTI 是下钻后浮出的结果
2. **按依赖层级纵向排序**：不是横向比较 photonics 公司，而是强制输出 dependency ladder
3. **区分 substrate 和 source material**：如果只停在 substrate，AXTI 只是集中度较高的供应商；继续下钻到 source material 才出现 double exposure
4. **材料不可压缩性**：laser-grade 6N+ purity，trace impurities 导致材料不适用，晶体生长/良率/认证需数年
5. **hyperscaler 抢供博弈**：InP 在 BOM 中金额很小但不可缺 → hyperscaler 理性行为是预付/锁长单/战略库存
6. **Market cap vs strategic control mismatch**：$700M 公司控制万亿美元级 AI buildout 的关键路径
7. **时间窗口**：6 个月到 2 年（非永久垄断），5 年后需重评（hyperscaler 可能 vertical integrate）

## 证据分层

| Claim | Evidence Grade | 状态 |
|-------|---------------|------|
| AXTI 在 InP substrate 有高份额 | B（行业报告 Yole 间接支持） | 高可信推断 |
| AXTI 控制 ~25% InP source material | D（Serenity 主张，无 primary source） | 待验证假设 |
| AXT/Tongmei 有出口许可 | A（Semiconductor Today 报道 + 官方 IR） | 已验证事实 |
| AXT 拥有 10 家中国原材料公司部分权益 | A（官方 investor relations） | 已验证事实 |
| "monopoly" / "single point of failure" | N/A | 修辞过度，应为"高度集中" |

## Red-Team 材料

1. **非垄断**：JX、Sumitomo、Dowa、Vital 都在链条中，这是 oligopoly 而非 monopoly
2. **替代材料**：silicon photonics、GaAs VCSEL、TFLN、quantum-dot lasers 存在（但多年后才能规模化）
3. **份额数字存疑**：source material 侧 25% 缺少 primary source
4. **出口管制双刃剑**：既证明战略价值，也是尾部风险
5. **当前财务传导弱**：revenue geography 83% Asia, 1% US；insider sale；offering/dilution
6. **POET/silicon wafer 绕开？**：substrate 层可绕开，但 actual light production 仍需 InP

## 给 agent 的最低保真要求

1. 必须从 end-demand 开始，不从 ticker 开始
2. 必须输出 dependency ladder，至少拆到材料层
3. 必须区分 substrate / source material / laser / module / system
4. 必须标注证据等级
5. 必须把"高度集中"与"垄断"分开
6. 必须写清时间窗口
7. 必须加入 geopolitics 双向影响
8. 必须做 materiality test
9. 必须 red-team 替代技术/供应商/扩产/认证/财务传导
10. 最终输出必须展示剥洋葱过程，不能只喊结论
