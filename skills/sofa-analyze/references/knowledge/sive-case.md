# SIVE 黄金案例：客户链映射 / 隐藏供应商图谱

> 蒸馏自 Serenity 的 Sivers Photonics 研究，用于学习"公开蛛丝马迹构建 confidence-tiered 客户图谱"。不是投资建议。

## 一句话压缩

Sivers Photonics（$SIVE）是 CPO/pluggable 领域中未被市场发现的关键 CW laser 供应商，通过 customer mapping 可将其链接到 Apple、AMD、Marvell/Celestial、Ayar Labs、Nokia 等隐藏客户图谱。

## 客户图谱分层

### Public Confirmed（公开确认）
- **Jabil (JBL)**：2026 年 4 月 Sivers-Jabil 合作 1.6T LRO transceiver module
- **POET (POET)**：2025 年 9 月 External Light Source 合作 for CPO
- **Ayar Labs**：Sivers 作为 laser supplier 列于 Ayar 官网
- **O-Net / Enablence**：三方联合公告 ELS for AI datacenters
- **LIGHTIUM AG**：2025 年报提及 CW lasers on TFLN wafers

### High-Confidence Inferred（高可信推断）
- **Apple (AAPL)**：Fortune 100 客户 + RFQ 50M units/year + Carnegie 135 wavelength architectures = Apple Watch volume signature
- **Aeva (AEVA)**：LiDAR 客户，其他分析师报告提及
- **Marvell/Celestial (MRVL)**：Sivers 年报投资额匹配 → Celestial AI $100M Series B = Customer C placeholder

### Likely（很可能）
- **Lightmatter**：投资额匹配 $154M Series C = Customer B placeholder
- **Lightelligence (HKG:1879)**：Sivers 早期 presentation 直接点名 + 投资额匹配
- **AMD**：GlobalFoundries CPO program slide 中 Sivers 作为 laser partner 出现
- **Nokia (NOK)**：2025 年报 Finland 地域收入 + tier-1 telecom 客户描述

### One-Hop / Two-Hop（一跳/两跳推断）
- Ayar → AlChip/GUC/Wiwynn → Amazon/AMD/hyperscalers
- Jabil → prior Intel SiPh customers → Meta/Amazon/Google/Nvidia/Cisco
- POET → Lumilens ($50M preproduction + $500M volume order) → POET 的激光来自 Sivers
- Lightelligence → Biren → 中国 CPO 供应链（Tencent/Baidu）

## 关键 OSINT 技术

### 1. Wayback Machine / Archive.org
- Ayar Labs 官网 partner page 历史变更
- Lumentum 和 MACOM 被 silent removal
- Sivers 成为唯一公开的 laser supplier
- **证据等级**：B 级（Operational OSINT）

### 2. HTML Inspection
- Ayar 网站源码中 Lumentum/MACOM 的 alt text 残留
- 揭示已删除的供应商关系
- **证据等级**：B 级

### 3. Funding Round Amount Matching
- Sivers 年报 investor presentation 用 placeholder graphics 标注 Customer B/C/D
- 文字提及"超过 SEK 70 亿投资于 Celestial AI, Lightelligence, Lightmatter 等新公司"
- 匹配融资额：Lightmatter $154M + Celestial $100M + Lightmatter $155M ≈ SEK 70 亿
- Lightelligence 在同期融资 $0，但早期 presentation 有直接点名
- **证据等级**：B 级（交叉验证后高可信推断）

### 4. Revenue Geography Matching
- Sivers 2025 年报：大部分收入来自 Finland
- Finland 的主要 tier-1 telecom = Nokia
- **证据等级**：B 级推断

### 5. Ecosystem Slide Mapping
- GlobalFoundries CPO announcement 的 ecosystem partner slide
- 仅列出 Sivers 和 Lumentum 作为 laser companies
- **证据等级**：B 级

### 6. Annual Report Language Analysis
- "US Fortune 100 customer" + RFQ 50M units/year
- 全球只有 Apple 年销 ~50M 可穿戴设备
- **证据等级**：B 级（强推断但非直接确认）

## 重要 Caveat

Serenity 本人在文章末尾的 disclaimer：
> "These are high confidence links to Sivers, customers are likely to remain unconfirmed as the supply chain BOM/customer relationships are heavily guarded and under NDA. It's also possible some of these high confidence relationships may not proceed to mass production."

## 给 agent 的启示

1. 客户链映射必须分层：public confirmed → high-confidence inferred → likely → one-hop → two-hop
2. 每个推断必须标注使用的 OSINT 技术和证据等级
3. 即使高置信度关系也可能不到量产
4. NDA 保护意味着永远无法 100% 确认
5. 必须区分"logo 出现在 partner page"和"revenue-generating customer"
6. Wayback/HTML inspection 是 powerful OSINT 但需要定期重新检查
7. 融资额匹配是一种创造性的推断方法，但需要排除巧合
