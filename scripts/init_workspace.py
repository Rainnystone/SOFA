#!/usr/bin/env python3
"""
SOFA Workspace Initializer

Creates a SOFA workspace directory structure and initializes all required
state files. Must be called as the FIRST action in any SOFA research session.

Usage:
    python init_workspace.py <TICKER_OR_THEME> <WORKSPACE_PATH> [--mode ticker|sector]

Example:
    python init_workspace.py MXL /path/to/workspace --mode ticker
    python init_workspace.py "AI Optical Interconnect" /path/to/workspace --mode sector
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontier_lifecycle import make_registry


def create_workspace(ticker_or_theme: str, workspace_path: str, mode: str) -> None:
    # Normalize workspace path
    workspace_path = os.path.normpath(workspace_path)
    created = []
    skipped_existing = []

    # Create directory structure (common)
    dirs = [
        (workspace_path, "./"),
        (os.path.join(workspace_path, "scouts"), "scouts/"),
        (os.path.join(workspace_path, "challenges"), "challenges/"),
        (os.path.join(workspace_path, "maps"), "maps/"),
        (os.path.join(workspace_path, "financials"), "financials/"),
        (os.path.join(workspace_path, "redteam"), "redteam/"),
        (os.path.join(workspace_path, "reports"), "reports/"),
        (os.path.join(workspace_path, "dive_packets"), "dive_packets/"),
    ]

    # Sector mode adds coverage/ for Coverage Challenge files
    if mode == "sector":
        dirs.append((os.path.join(workspace_path, "coverage"), "coverage/"))

    for directory, label in dirs:
        if os.path.exists(directory):
            skipped_existing.append(label)
        else:
            os.makedirs(directory, exist_ok=True)
            created.append(label)

    # Create research_workflow.md
    workflow_path = os.path.join(workspace_path, "research_workflow.md")
    if not os.path.exists(workflow_path):
        with open(workflow_path, "w", encoding="utf-8") as f:
            f.write(f"""# Research Workflow: {ticker_or_theme}

## Basic Info
- Subject: {ticker_or_theme}
- Mode: {"Ticker Dive" if mode == "ticker" else "Sector Hunt"}
- Started: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
- Current Stage: Stage 0 (Intake + Framing)
- Workspace: {workspace_path}

## Stage Progress
| Stage | Status | Output Files | Notes |
|-------|--------|--------------|-------|
| Stage 0: Intake + Framing | in_progress | | |
| Stage 1: Provisional Frontier Plan | pending | | |
| Stage 2: {"Evidence Frontier Loops" if mode == "ticker" else "Mapping Loops"} | pending | {"evidence_ledger.md" if mode == "ticker" else "maps/dependency_ladder.md"} | |
| Stage 3: {"Thesis + Financial Bridge" if mode == "ticker" else "Chokepoint Scoring + Financial Screen"} | pending | financials/ | |
| Stage 4: {"Formal Red Team" if mode == "ticker" else "Mapping Integrity Review"} | pending | redteam/ | |
| Stage 5: {"Final Verdict" if mode == "ticker" else "Ranked Target Queue"} | pending | | |
| Stage 6: Watch Protocol | pending | | |

## Evidence Loop Tracker
| Loop# | Frontier | Scout File | Challenge File | Gate Score | Decision |
|-------|----------|------------|----------------|------------|----------|

## Subagent Dispatch Log
| Time | Loop# | Role | File Path | Status | Quality |
|------|-------|------|-----------|--------|---------|

## Decision Log
| Time | Decision | Reason | Based On |
|------|----------|--------|----------|

## Frontier Review Log
<!-- SOFA:frontier-review-log:start -->
<!-- SOFA:frontier-review-log:end -->

## Frontier Discovery Log
<!-- SOFA:frontier-discovery-log:start -->
<!-- SOFA:frontier-discovery-log:end -->

## Current Claim Ledger (summary)
(See evidence_ledger.md for full content)

## Synthesis Notes
> 主线程综合分析笔记区。记录跨 loop 推理、证据冲突解决、thesis 演进和最终判断的推理过程。
> 此区域由主线程独占写入，是持久化的分析推理记录（不是流程状态）。

""")
        created.append("research_workflow.md")
    else:
        skipped_existing.append("research_workflow.md")

    # Create evidence_ledger.md
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    if not os.path.exists(ledger_path):
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(f"""# Evidence Ledger: {ticker_or_theme}

> This file is the single source of truth for all evidence collected during research.
> Only the main thread writes to this file. Subagents deliver to scouts/challenges/etc.

---

""")
        created.append("evidence_ledger.md")
    else:
        skipped_existing.append("evidence_ledger.md")

    # Create claim_ledger.md
    claim_ledger_path = os.path.join(workspace_path, "claim_ledger.md")
    if not os.path.exists(claim_ledger_path):
        with open(claim_ledger_path, "w", encoding="utf-8") as f:
            f.write(f"""# Claim Ledger: {ticker_or_theme}

> Track every material claim before it enters a report or packet.

| Claim | Status | Evidence | Source | Owner | Next Check |
|-------|--------|----------|--------|-------|------------|

""")
        created.append("claim_ledger.md")
    else:
        skipped_existing.append("claim_ledger.md")

    # Create search_log.md
    search_log_path = os.path.join(workspace_path, "search_log.md")
    if not os.path.exists(search_log_path):
        with open(search_log_path, "w", encoding="utf-8") as f:
            f.write(f"""# Search Log: {ticker_or_theme}

> Record search attempts, tool tier, result quality, and unresolved gaps.

| Time | Query | Tool Tier | Result | Notes |
|------|-------|-----------|--------|-------|

""")
        created.append("search_log.md")
    else:
        skipped_existing.append("search_log.md")

    # Create capability_report.md
    capability_report_path = os.path.join(workspace_path, "capability_report.md")
    if not os.path.exists(capability_report_path):
        with open(capability_report_path, "w", encoding="utf-8") as f:
            f.write(f"""# Capability Report: {ticker_or_theme}

Run from the project root:

```bash
python SOFA/scripts/capability_check.py --json
```

| Capability | Mode | Status | Notes |
|------------|------|--------|-------|
| Search | AnySearch -> Exa -> Tavily -> host-agent built-ins | pending | |
| Financial data | Wind for Chinese data; yfinance for English/global public-market data | pending | |
| Degraded mode | Explicitly documented reduced capability | pending | |

""")
        created.append("capability_report.md")
    else:
        skipped_existing.append("capability_report.md")

    # Sector mode: create initial dependency_ladder.md
    if mode == "sector":
        ladder_path = os.path.join(workspace_path, "maps", "dependency_ladder.md")
        if not os.path.exists(ladder_path):
            with open(ladder_path, "w", encoding="utf-8") as f:
                f.write(f"""# Dependency Ladder: {ticker_or_theme}

> Sector Hunt 的核心产出。由主线程在每轮 Mapping Loop 后更新。
> 记录从终端需求到物理瓶颈的完整依赖层级。

---

## Layer 0: Terminal Demand
(待 Stage 0 Demand Decomposition + Stage 2 Mapping Loop 填充)

## Layer 1: System / Platform

## Layer 2: Component / Module

## Layer 3: Material / Process

## Layer 4: Raw Material / Equipment

## Layer 5: Geography / Regulation

---

## Node Registry
| Company | Ticker | Layer | Role | Market Cap Bucket | Evidence Grade | Chokepoint Pre-Score |
|---------|--------|-------|------|-------------------|----------------|---------------------|

## Double Bottleneck Candidates
| Company | Layers Present | Cross-Validation | Evidence Grade |
|---------|---------------|-----------------|----------------|

## Chokepoint Scoring Matrix (Stage 3)
(Stage 3 完整 12 维打分，由主线程在 Mapping 完成后填写)

""")
            created.append("maps/dependency_ladder.md")
        else:
            skipped_existing.append("maps/dependency_ladder.md")

    # Create state.json for machine-readable state tracking
    state_path = os.path.join(workspace_path, "state.json")
    if not os.path.exists(state_path):
        state = {
            "subject": ticker_or_theme,
            "mode": mode,
            "started": datetime.now(timezone.utc).isoformat(),
            "current_stage": "stage_0",
            "loop_count": 0,
            "stages_completed": [],
            "subagent_dispatches": [],
            "decisions": [],
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        created.append("state.json")
    else:
        skipped_existing.append("state.json")

    # Create frontier_registry.json for v4 frontier lifecycle state.
    registry_path = os.path.join(workspace_path, "frontier_registry.json")
    if not os.path.exists(registry_path):
        registry = make_registry(ticker_or_theme, mode)
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        created.append("frontier_registry.json")
    else:
        skipped_existing.append("frontier_registry.json")

    # Output success
    print(f"WORKSPACE INITIALIZED")
    print(f"  Path: {workspace_path}")
    print(f"  Subject: {ticker_or_theme}")
    print(f"  Mode: {'Ticker Dive' if mode == 'ticker' else 'Sector Hunt'}")
    print(f"  Created:")
    _print_items(created)
    print(f"  Skipped existing:")
    _print_items(skipped_existing)
    print(f"")

    print(f"  Capability check:")
    print(f"    Run python SOFA/scripts/capability_check.py --json from the project root.")
    print(f"    SOFA recommends AnySearch -> Exa -> Tavily -> host-agent built-ins for general search.")
    print(f"    SOFA recommends Wind for Chinese financial data and yfinance for English/global public-market data.")
    print(f"")
    print(f"Proceed to Stage 0: Intake + Framing.")


def _print_items(items):
    if not items:
        print(f"    - (none)")
        return
    for item in items:
        print(f"    - {item}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize SOFA workspace")
    parser.add_argument("subject", help="Ticker or theme to research")
    parser.add_argument("workspace_path", help="Path to create workspace")
    parser.add_argument("--mode", choices=["ticker", "sector"], default="ticker",
                        help="Research mode: ticker (Ticker Dive) or sector (Sector Hunt)")
    args = parser.parse_args()
    create_workspace(args.subject, args.workspace_path, args.mode)
