#!/usr/bin/env python3
"""
SOFA Workspace Initializer

Creates a SOFA workspace directory structure and initializes all required
state files. Must be called as the FIRST action in any SOFA research session.

Usage:
    python scripts/init_workspace.py <TICKER_OR_THEME> <WORKSPACE_PATH> [--mode ticker|sector]

Example:
    python scripts/init_workspace.py MXL ./workspace/mxl --mode ticker
    python scripts/init_workspace.py "AI Optical Interconnect" ./workspace/ai-optical-interconnect --mode sector
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capability_policy import (
    render_chain_arrow,
    render_finance_summary,
    render_setup_recommendation_lines,
)
from frontier_lifecycle import (
    CURRENT_REGISTRY_VERSION,
    make_registry,
    render_frontier_layer_coverage_md,
    validate_registry,
)
from frontier_review import write_atomic
from workspace_contract import (
    ArtifactSpec,
    artifact_contract_for_mode,
    upsert_managed_block_after,
)

try:
    from framing_contract import empty_contract, render_contract_markdown
except ImportError:
    from scripts.framing_contract import empty_contract, render_contract_markdown

try:
    from revisit_contract import empty_pointer, persist_pointer
except ImportError:
    from scripts.revisit_contract import empty_pointer, persist_pointer


def _artifact_path(workspace_path: str, artifact: ArtifactSpec) -> str:
    if artifact.path == ".":
        return workspace_path
    return os.path.join(workspace_path, artifact.path)


def _create_directories(
    workspace_path: str, artifacts, created: list[str], skipped_existing: list[str]
) -> None:
    for artifact in artifacts:
        directory = _artifact_path(workspace_path, artifact)
        if os.path.exists(directory):
            skipped_existing.append(artifact.label)
        else:
            os.makedirs(directory, exist_ok=True)
            created.append(artifact.label)


def _managed_block_markdown(contract, block_name: str, content: str = "") -> str:
    for block in contract.managed_blocks:
        if block.name == block_name:
            body = content.rstrip()
            if body:
                body = body + "\n"
            return f"## {block.heading}\n{block.start_marker}\n{body}{block.end_marker}"
    raise ValueError(f"Unknown SOFA managed block: {block_name}")


def create_workspace(ticker_or_theme: str, workspace_path: str, mode: str) -> None:
    # Normalize workspace path
    workspace_path = os.path.normpath(workspace_path)
    legacy_initialized = any(
        os.path.exists(os.path.join(workspace_path, filename))
        for filename in (
            "state.json",
            "research_workflow.md",
            "frontier_registry.json",
        )
    )
    created = []
    updated = []
    skipped_existing = []
    contract = artifact_contract_for_mode(mode)
    mode = contract.mode
    pointer_path = os.path.join(workspace_path, "revisit_contract.json")
    exclude_legacy_revisit_scaffold = (
        mode == "ticker"
        and legacy_initialized
        and not os.path.exists(pointer_path)
    )

    registry_path = os.path.join(workspace_path, "frontier_registry.json")
    workflow_path = os.path.join(workspace_path, "research_workflow.md")
    registry_exists = os.path.exists(registry_path)
    workflow_exists = os.path.exists(workflow_path)

    registry_document = None
    if not registry_exists:
        registry_document = make_registry(ticker_or_theme, mode)
    elif not workflow_exists:
        with open(registry_path, "r", encoding="utf-8") as handle:
            registry_document = json.load(handle)
        validate_registry(registry_document)

    # Compute the empty framing contract and its Markdown mirror once; both
    # the workflow scaffold and the machine-ledger write consume this.
    framing_contract_doc = empty_contract()
    framing_mirror = render_contract_markdown(framing_contract_doc)
    framing_block_md = _managed_block_markdown(contract, "framing-contract", framing_mirror)

    layer_block_md = ""
    if (
        not workflow_exists
        and registry_document["version"] == CURRENT_REGISTRY_VERSION
    ):
        layer_block_md = _managed_block_markdown(
            contract,
            "frontier-layer-coverage",
            render_frontier_layer_coverage_md(registry_document),
        )
    layer_block_section = f"{layer_block_md}\n\n" if layer_block_md else ""

    repaired_workflow = None
    if workflow_exists and not registry_exists:
        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow_text = handle.read()
        repaired_workflow = upsert_managed_block_after(
            workflow_text,
            "frontier-layer-coverage",
            render_frontier_layer_coverage_md(registry_document),
            after_block_name="frontier-discovery-log",
        )

    # Create directory structure (common)
    directory_specs = contract.directory_specs
    if exclude_legacy_revisit_scaffold:
        directory_specs = tuple(
            artifact
            for artifact in directory_specs
            if artifact.path != "revisit_cycles"
        )
    _create_directories(workspace_path, directory_specs, created, skipped_existing)

    # Create research_workflow.md
    if not workflow_exists:
        with open(workflow_path, "w", encoding="utf-8") as f:
            f.write(f"""# Research Workflow: {ticker_or_theme}

## Basic Info
- Subject: {ticker_or_theme}
- Mode: {"Ticker Dive" if mode == "ticker" else "Sector Hunt"}
- Started: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
- Current Stage: Stage 0 (Intake + Framing)
- Workspace: {workspace_path}

{framing_block_md}
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

{_managed_block_markdown(contract, "frontier-review-log")}

{_managed_block_markdown(contract, "frontier-discovery-log")}

{layer_block_section}## Current Claim Ledger (summary)
(See evidence_ledger.md for full content)

## Synthesis Notes
> 主线程综合分析笔记区。记录跨 loop 推理、证据冲突解决、thesis 演进和最终判断的推理过程。
> 此区域由主线程独占写入，是持久化的分析推理记录（不是流程状态）。

""")
        created.append("research_workflow.md")
    else:
        if repaired_workflow is None:
            skipped_existing.append("research_workflow.md")

    # Create evidence_ledger.md
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    if not os.path.exists(ledger_path):
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(f"""# Evidence Ledger: {ticker_or_theme}

> This file is the single source of truth for all evidence collected during research.
> Only the main thread writes to this file. Subagents deliver to scouts/challenges/etc.
> Deep-read excerpts are archived append-only via scripts/archive_source.py;
> evidence entries reference archived sources by source id (src-NNN).

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

    for ledger_name in contract.machine_ledgers:
        if exclude_legacy_revisit_scaffold and ledger_name == "revisit_contract.json":
            continue
        if ledger_name in {"state.json", "frontier_registry.json"}:
            continue
        ledger_path = os.path.join(workspace_path, ledger_name)
        if os.path.exists(ledger_path):
            skipped_existing.append(ledger_name)
            continue
        if ledger_name == "framing_contract.json":
            with open(ledger_path, "w", encoding="utf-8") as f:
                json.dump(framing_contract_doc, f, indent=2, ensure_ascii=False)
                f.write("\n")
        elif ledger_name == "revisit_contract.json":
            persist_pointer(
                workspace_path,
                empty_pointer(),
                expected_sha256=None,
            )
        else:
            with open(ledger_path, "w", encoding="utf-8"):
                pass
        created.append(ledger_name)

    # Create capability_report.md
    capability_report_path = os.path.join(workspace_path, "capability_report.md")
    if not os.path.exists(capability_report_path):
        with open(capability_report_path, "w", encoding="utf-8") as f:
            f.write(f"""# Capability Report: {ticker_or_theme}

Run from the repository root:

```bash
python scripts/capability_check.py --json
```

| Capability | Mode | Status | Notes |
|------------|------|--------|-------|
| Search | {render_chain_arrow()} | pending | |
| Financial data | {render_finance_summary()} | pending | |
| Degraded mode | Explicitly documented reduced capability | pending | |

""")
        created.append("capability_report.md")
    else:
        skipped_existing.append("capability_report.md")

    # Sector mode: create initial dependency_ladder.md
    if "maps/dependency_ladder.md" in contract.mode_artifacts:
        ladder_path = os.path.join(workspace_path, "maps", "dependency_ladder.md")
        if not os.path.exists(ladder_path):
            with open(ladder_path, "w", encoding="utf-8") as f:
                f.write(f"""# Dependency Ladder: {ticker_or_theme}

> Sector Hunt 的核心产出。由主线程在每轮 Mapping Loop 后更新。
> 记录从终端需求到物理瓶颈的完整依赖层级。

---

## Layer 0: [Workspace label from Stage 0]
(待 Stage 0 Demand Decomposition + Stage 2 Mapping Loop 填充)

## Layer 1: [Workspace label from Stage 0]

## Layer 2: [Workspace label from Stage 0]

## Layer 3: [Workspace label from Stage 0]

## Layer 4: [Workspace label from Stage 0]

## Layer 5: [Workspace label from Stage 0]

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

    # Create frontier_registry.json for registry schema v3 state.
    if not registry_exists:
        if repaired_workflow is not None:
            write_atomic(workflow_path, repaired_workflow)
            updated.append("research_workflow.md")
            write_atomic(
                registry_path,
                json.dumps(registry_document, indent=2, ensure_ascii=False),
            )
        else:
            with open(registry_path, "w", encoding="utf-8") as f:
                json.dump(registry_document, f, indent=2, ensure_ascii=False)
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
    if updated:
        print(f"  Updated:")
        _print_items(updated)
    print(f"  Skipped existing:")
    _print_items(skipped_existing)
    print(f"")

    print(f"  Capability check:")
    print(f"    Run python scripts/capability_check.py --json from the repository root.")
    for line in render_setup_recommendation_lines():
        print(f"    {line}")
    print(f"")
    print(f"Proceed to Stage 0: Intake + Framing.")


def _print_items(items):
    if not items:
        print(f"    - (none)")
        return
    for item in items:
        print(f"    - {item}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Initialize SOFA workspace")
    parser.add_argument("subject", help="Ticker or theme to research")
    parser.add_argument("workspace_path", help="Path to create workspace")
    parser.add_argument("--mode", choices=["ticker", "sector"], default="ticker",
                        help="Research mode: ticker (Ticker Dive) or sector (Sector Hunt)")
    args = parser.parse_args()
    create_workspace(args.subject, args.workspace_path, args.mode)
