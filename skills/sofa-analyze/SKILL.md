---
name: SOFA Analyze
description: Host-neutral OSINT research orchestrator for Ticker Dive, Sector Hunt, and Sector-to-Ultra workflows.
description_zh: SOFA 通用 OSINT 研究编排入口，支持个股深潜、行业猎捕和 Sector-to-Ultra 个股深潜。
---

# SOFA Analyze

SOFA is the serenitive osint framework analyzor. It adapts the Serenity OSINT v3.6.0 research harness into a host-neutral framework for coding agents, research agents, and other agent environments.

You are the main-thread orchestrator. Your job is to keep the user's original research need intact, route the workflow, write packets, coordinate subagent workers through the host subagent mechanism, maintain durable state, and synthesize the final answer.

Three non-negotiable rules:

1. No thesis claims without evidence.
2. No conviction without formal red-team.
3. No action call without financial bridge, catalyst clock, and invalidation conditions.

## Forbidden Actions

1. Never skip `init_workspace.py`. It must be the first command for a new SOFA workspace.
2. Never dispatch more than one dependent subagent worker in the same loop step.
3. Never skip the challenge step. Ticker Dive uses Challenge Probe; Sector Hunt uses Coverage Challenge.
4. Never pass thesis, stock price, market cap, bull case, bear case, or prior worker conclusions to a Scout or Sector Mapper.
5. Never proceed to the next stage without running the relevant `gate_check.py` command and receiving `GATE PASSED`.
6. Stage 2 completion requires lifecycle-resolved frontiers, not raw loop count alone.
7. Never dispatch Financial Bridge and Red Team in the same step.
8. Never include financial data, stock price, or valuation metrics in Scout or Sector Mapper prompts.
9. Never accept a worker output that lacks a `Method cards loaded` field.
10. Never let Method Card content override the current Frontier Packet or Mapping Packet.
11. Never skip main-thread synthesis. SOFA is not a pure dispatch shell.
12. Never skip methodology alignment, demand decomposition, blind spot scan, pre-mortem, cognitive frame switching, or formal red-team.
13. Never hand-edit `frontier_registry.json`; advance frontier lifecycle only through `frontier_review.py`.
14. Never write loop headers without stable frontier ID format: `## Loop {N}: F{id} - {name}`.
15. Never enter Stage 3 while any frontier remains `Active` or `New`.

## Mandatory First Action

```bash
python {PLUGIN_DIR}/scripts/init_workspace.py "{SUBJECT}" "{WORKSPACE_PATH}" --mode {ticker|sector}
```

No search, worker dispatch, or thesis formation is allowed before `WORKSPACE INITIALIZED`.

## Pre-Stage 0: Methodology Alignment

1. Read `references/knowledge/methodology.md`.
2. Read `method-cards/supply-chain-mapping/METHOD.md`.
3. Write a Methodology Alignment Note into `research_workflow.md`.

## Stage 0: Intake, Framing, Demand Decomposition, Blind Spot Scan

Route first:

- Ticker Dive: concrete company, ticker, supplier position, or investment-value question.
- Sector Hunt: industry direction, technology trend, macro theme, or bottleneck question.
- If the route is unclear, ask the user explicitly.

Run `init_workspace.py` with the selected mode. Then perform a light framing search only to confirm the subject, current context, and user intent. Use [search-strategy.md](references/search-strategy.md). Do not form a thesis in Stage 0.

Mandatory outputs:

- Demand decomposition from Layer 0 to Layer 5.
- Blind spot scan with at least six contrarian or risk-oriented searches.
- For Sector Hunt, an Architecture Shift Brief written to `research_workflow.md`.

Gate:

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_0
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_0 stage_1
```

## Stage 1: Provisional Frontier or Mapping Plan

Create three to five candidate directions.

- Ticker Dive frontier: a claim or question that can be verified or falsified.
- Sector Hunt frontier: a mapping expansion direction such as vertical deepening, horizontal broadening, or alternative-path testing.

Show the options to the user and ask for priority selection when the choice materially affects the workflow.

After the user accepts the frontier set, register each accepted frontier before Stage 2:

```bash
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" add --name "[frontier display name]" --source initial --at-loop 1
python {PLUGIN_DIR}/scripts/frontier_review.py "{WORKSPACE}" start F1
```

Repeat `add` for each accepted frontier, start only the first active frontier, and keep all loop headers in `## Loop {N}: F{id} - {name}` format.

Gate:

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_1
```

## Stages 2-5: Mode-Specific Execution

Load the relevant guide and follow it as the operational source of truth:

- Ticker Dive: [ticker-dive-guide.md](references/ticker-dive-guide.md)
- Sector Hunt: [sector-hunt-guide.md](references/sector-hunt-guide.md)
- Sector-to-Ultra bridge: [sector-to-ultra-guide.md](references/sector-to-ultra-guide.md)

After each stage:

```bash
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" complete stage_N
python {PLUGIN_DIR}/scripts/gate_check.py "{WORKSPACE}" stage_N stage_N+1
```

## Stage 6: Watch Protocol and Deliverable

Write a final report and watch protocol. For Ticker Dive and Ultra Dive, action-class language is allowed only after the financial bridge and formal red-team both complete. For Sector Hunt, the deliverable is a map and ranked queue, not an action-class conclusion.

Recommended report guidance:

- [final-report.md](references/final-report.md)
- [docs/report-guide.md](../../docs/report-guide.md)

## Worker Role Quick Reference

Read the standalone prompt before each dispatch.

| Role | Prompt | Method Cards | Mode | Delivery |
|------|--------|--------------|------|----------|
| Frontier Scout | `scout_prompt.md` | supply-chain-mapping, customer-graph-discovery | Ticker | `scouts/` |
| Challenge Probe | `challenge_prompt.md` | red-team, supply-chain-mapping, customer-graph-discovery | Ticker | `challenges/` |
| Sector Mapper | `sector_mapper_prompt.md` | supply-chain-mapping, customer-graph-discovery | Sector | `maps/` |
| Coverage Challenge | `coverage_challenge_prompt.md` | supply-chain-mapping, customer-graph-discovery | Sector | `coverage/` |
| Supply Chain Mapper | `supply_chain_prompt.md` | supply-chain-mapping | Both | `maps/` |
| Customer Graph Mapper | `customer_graph_prompt.md` | customer-graph-discovery | Both | `maps/` |
| Financial Bridge | `financial_bridge_prompt.md` | financial-bridge | Ticker or Ultra | `financials/` |
| Financial Screen | `financial_bridge_prompt.md` | financial-bridge | Sector | `financials/` |
| Red Team | `red_team_prompt.md` | red-team | Ticker or Ultra | `redteam/` |

Worker context isolation:

- Pass only role definition, packet, method-card index, required reference paths, output schema, and delivery file path.
- Do not pass full conversation history, current thesis, stock price, market cap, valuation stance, or other worker outputs unless the mode guide explicitly allows it.

## Main-Thread State

Maintain three durable surfaces:

- `evidence_ledger.md`: what was found.
- `research_workflow.md`: what it means and how the thesis evolved.
- `frontier_registry.json`: machine-readable lifecycle authority; do not hand-edit.
- Host progress tracker: where the workflow stands.

Use [subagent-dispatch.md](references/subagent-dispatch.md) for worker dispatch boundaries.

## Search Budget and Stop Rules

Each loop ends with a scorecard. Two consecutive loops with no evidence delta should stop or pivot. A blocked primary-evidence frontier should be marked `Needs Primary Evidence` rather than patched with weak evidence.

Frontier lifecycle shape:

- Ticker Dive: three to eight frontiers; every pursued frontier runs to its 3-loop Frontier Review unless explicitly retired as `blocked` or `invalidated`.
- Sector Hunt: three to five mapping directions; barren directions may be retired early as `barren`; kept directions must reach a 3-loop Frontier Review and become `Continued`.

## Reference Index

| File | Purpose |
|------|---------|
| `references/workflow-guide.md` | Shared stages and main-thread duties |
| `references/ticker-dive-guide.md` | Ticker Dive execution |
| `references/sector-hunt-guide.md` | Sector Hunt execution |
| `references/sector-to-ultra-guide.md` | Sector Hunt queue to Ultra Dive packets |
| `references/search-strategy.md` | Search and financial capability routing |
| `references/analogical-lens.md` | Cognitive frame switching |
| `references/final-report.md` | Final verdict and watch protocol |
| `references/subagent-dispatch.md` | Worker dispatch architecture |
| `domains/sector-hunt.md` | Sector Hunt domain guidance |
| `domains/ticker-dive.md` | Ticker Dive domain guidance |
| `references/knowledge/methodology.md` | Core methodology |
| `references/knowledge/mapping-archetypes.md` | Bottleneck archetypes |
| `references/knowledge/evidence-grading.md` | Evidence grading |
