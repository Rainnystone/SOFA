# SOFA Method Cards Index

Method cards are subagent-private progressive disclosure resources. They are not user commands.

| Card | Path | Owner Agent | Use When |
|---|---|---|---|
| supply-chain-mapping | `method-cards/supply-chain-mapping/METHOD.md` | Supply Chain Mapper | Building dependency ladders, tracing ownership chains, identifying double bottlenecks |
| customer-graph-discovery | `method-cards/customer-graph-discovery/METHOD.md` | Customer Graph Mapper | Mapping hidden customer relationships and confidence tiers |
| financial-bridge | `method-cards/financial-bridge/METHOD.md` | Financial Bridge Analyst | Translating bottleneck claims into revenue, margin, cash flow, dilution, and valuation checks |
| red-team | `method-cards/red-team/METHOD.md` | Red Team Analyst | Stress-testing thesis claims through structured bear-case debate |

## Rules

1. The main-thread packet defines what to research.
2. A method card defines how to perform one bounded research technique.
3. Subagents load only the cards named in their packet.
4. Every subagent output must include `Method cards loaded: [...]`.
5. Users should invoke SOFA Analyze, not individual method cards.
