#!/usr/bin/env python3
"""
SOFA Dossier Validator

Validates that all required deliverables exist before generating the Final Dossier.
Mode-aware: applies correct checks for Ticker Dive vs Sector Hunt workflows.
Must be called before Stage 5 (Final Verdict).

Usage:
    python validate_dossier.py <WORKSPACE_PATH>

Example:
    python validate_dossier.py /path/to/sofa_workspace
"""

import json
import os
import sys
import re

# Import Socratic debate validator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from redteam_debate_validator import validate_debate
from sofa_contract import ContractProfile, evaluate_workspace


def count_md_files(directory: str) -> int:
    if not os.path.exists(directory):
        return 0
    return len([f for f in os.listdir(directory) if f.endswith(".md")])


def list_md_files(directory: str) -> list[str]:
    if not os.path.exists(directory):
        return []
    return sorted([f for f in os.listdir(directory) if f.endswith(".md")])


def count_loop_entries(ledger_path: str) -> int:
    if not os.path.exists(ledger_path):
        return 0
    with open(ledger_path, "r", encoding="utf-8") as f:
        content = f.read()
    return len(re.findall(r"^## Loop \d+:", content, re.MULTILINE))


def check_gate_scorecards(workflow_path: str) -> tuple[int, int]:
    """Returns (filled_count, total_loops)"""
    if not os.path.exists(workflow_path):
        return 0, 0
    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Count rows in Evidence Loop Tracker table (excluding header)
    tracker_rows = len(re.findall(r"^\| \d+", content, re.MULTILINE))
    return tracker_rows, tracker_rows


def validate(workspace_path: str) -> tuple[bool, list[str], list[str]]:
    """
    Returns (valid, errors, warnings)
    """
    errors = []
    warnings = []

    # Load mode from state.json
    mode = "ticker"
    state_path = os.path.join(workspace_path, "state.json")
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        mode = state.get("mode", "ticker")

    # 1. Core state files
    if not os.path.exists(os.path.join(workspace_path, "research_workflow.md")):
        errors.append("research_workflow.md does not exist")
    if not os.path.exists(os.path.join(workspace_path, "evidence_ledger.md")):
        errors.append("evidence_ledger.md does not exist")
    if not os.path.exists(os.path.join(workspace_path, "state.json")):
        errors.append("state.json does not exist")

    # 2. Evidence loops: minimum 3 (common)
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    loop_entries = count_loop_entries(ledger_path)
    if loop_entries < 3:
        errors.append(f"evidence_ledger.md has {loop_entries} loop entries (need >= 3)")

    # 3-4. Mode-specific loop output checks
    if mode == "ticker":
        # Ticker Dive: Scout + Challenge files
        scout_dir = os.path.join(workspace_path, "scouts")
        scout_files = list_md_files(scout_dir)
        if len(scout_files) < 3:
            errors.append(f"Only {len(scout_files)} scout file(s) in scouts/ (need >= 3)")

        challenge_dir = os.path.join(workspace_path, "challenges")
        challenge_files = list_md_files(challenge_dir)
        if len(challenge_files) < 3:
            errors.append(f"Only {len(challenge_files)} challenge file(s) in challenges/ (need >= 3)")
        if len(scout_files) != len(challenge_files):
            errors.append(
                f"Scout count ({len(scout_files)}) != Challenge count ({len(challenge_files)}). "
                "Each loop must have both."
            )
    else:
        # Sector Hunt: Mapping files + Coverage files
        maps_dir = os.path.join(workspace_path, "maps")
        map_files = list_md_files(maps_dir)
        # Subtract dependency_ladder.md if present
        ladder_exists = os.path.exists(os.path.join(maps_dir, "dependency_ladder.md"))
        mapping_files = len(map_files) - (1 if ladder_exists else 0)
        if mapping_files < 3:
            errors.append(f"Only {mapping_files} mapping file(s) in maps/ (need >= 3, excluding dependency_ladder.md)")

        coverage_dir = os.path.join(workspace_path, "coverage")
        coverage_files = list_md_files(coverage_dir)
        if len(coverage_files) < 3:
            errors.append(f"Only {len(coverage_files)} coverage challenge file(s) in coverage/ (need >= 3)")

        if not ladder_exists:
            errors.append("maps/dependency_ladder.md not found (Sector Hunt core deliverable)")

    # 5. Financial checks (mode-aware)
    financials_dir = os.path.join(workspace_path, "financials")
    bridge_files = list_md_files(financials_dir)
    if mode == "ticker":
        if len(bridge_files) < 1:
            errors.append("No financial bridge report in financials/ (need >= 1)")
    else:
        if len(bridge_files) < 1:
            warnings.append("No financial screen report in financials/ (recommended for Tier 1 candidates)")

    # 6. Red team: Socratic debate / Mapping Integrity Review must be complete
    passed_debate, debate_violations = validate_debate(workspace_path)
    if not passed_debate:
        errors.extend(debate_violations)

    # Soft warning: recommend 3 rounds
    redteam_dir = os.path.join(workspace_path, "redteam")
    if os.path.exists(redteam_dir):
        redteam_files = [f for f in os.listdir(redteam_dir) if "redteam" in f.lower()]
        rounds_count = len(redteam_files)
        if rounds_count < 3:
            warnings.append(f"Red Team has {rounds_count} rounds. 3 rounds recommended for thorough stress testing.")

    # 7. Check state.json for completed stages
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        completed = state.get("stages_completed", [])
        required_before_verdict = ["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"]
        for stage in required_before_verdict:
            if stage not in completed:
                errors.append(f"Stage '{stage}' not marked as completed in state.json")

        loop_count = state.get("loop_count", 0)
        if loop_count < 3:
            errors.append(f"state.json loop_count = {loop_count} (need >= 3)")
    else:
        errors.append("state.json not found")

    # 8. Shared SOFA compliance contract checks.
    contract = evaluate_workspace(
        workspace_path,
        ContractProfile(mode=mode, target="workspace"),
    )
    errors.extend(issue.display() for issue in contract.failures)
    warnings.extend(issue.display() for issue in contract.warnings)

    # 8b. Workflow content checks (warnings)
    workflow_path = os.path.join(workspace_path, "research_workflow.md")
    if os.path.exists(workflow_path):
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_content = f.read()

        # Synthesis notes check
        has_synthesis = ("## Synthesis Notes" in workflow_content or
                         "## 综合分析笔记" in workflow_content)
        if has_synthesis:
            synthesis_match = re.search(
                r"## (Synthesis Notes|综合分析笔记).*?(?=## |\Z)",
                workflow_content, re.DOTALL
            )
            if synthesis_match:
                synthesis_content = synthesis_match.group(0)
                lines = [l.strip() for l in synthesis_content.split("\n")
                         if l.strip() and not l.strip().startswith(">")
                         and not l.strip().startswith("#")
                         and not l.strip().startswith("|")
                         and not l.strip().startswith("-")
                         and len(l.strip()) > 20]
                if len(lines) < 3:
                    warnings.append(
                        "Synthesis Notes has only "
                        f"{len(lines)} substantive line(s) (need >= 3) - "
                        "main thread must record cross-loop reasoning"
                    )
            else:
                warnings.append("Synthesis Notes section is empty")
        else:
            warnings.append("research_workflow.md missing '## Synthesis Notes' / '## 综合分析笔记' section")

        # Common content checks
        if "## Blind Spot Report" not in workflow_content and "## 盲区报告" not in workflow_content:
            warnings.append("research_workflow.md missing Blind Spot Report")

        if "## Methodology Alignment" not in workflow_content and "## 方法论对齐" not in workflow_content:
            warnings.append("research_workflow.md missing Methodology Alignment Note (Pre-Stage 0)")

        if "## Demand Decomposition" not in workflow_content and "## 需求拆解" not in workflow_content:
            warnings.append("research_workflow.md missing Demand Decomposition Sketch")

        if "Serendipity" not in workflow_content and "意外发现" not in workflow_content:
            warnings.append("research_workflow.md missing Serendipity Loop findings (Stage 2)")

        if "## Pre-Mortem" not in workflow_content and "## 事前验尸" not in workflow_content:
            warnings.append("research_workflow.md missing Pre-Mortem")

        if "## Cognitive Frame" not in workflow_content and "## 认知框架" not in workflow_content:
            warnings.append("research_workflow.md missing Cognitive Frame Analysis")

        # Sector mode specific content checks
        if mode == "sector":
            if "## Architecture Shift" not in workflow_content and "## 架构迁移" not in workflow_content:
                warnings.append("research_workflow.md missing Architecture Shift Brief (Sector Hunt)")
            if "## Chokepoint Scoring" not in workflow_content and "## 扼点评分" not in workflow_content:
                warnings.append("research_workflow.md missing Chokepoint Scoring Matrix (Sector Hunt)")
            if "## Ranked Candidate" not in workflow_content and "## 排序候选" not in workflow_content:
                warnings.append("research_workflow.md missing Ranked Candidate Queue (Sector Hunt)")

    # 9. Other warnings (non-blocking)
    maps_dir = os.path.join(workspace_path, "maps")
    map_files = list_md_files(maps_dir)
    if len(map_files) == 0:
        warnings.append("No supply chain / customer graph maps in maps/ (recommended)")

    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) < 500:
            warnings.append("evidence_ledger.md seems too short (< 500 chars) - check content quality")

    valid = len(errors) == 0
    return valid, errors, warnings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_dossier.py <workspace_path>")
        print("")
        print("Validates SOFA workspace completeness before generating Final Dossier.")
        print("Mode-aware: reads state.json to apply correct checks for")
        print("Ticker Dive vs Sector Hunt workflows.")
        sys.exit(1)

    workspace_path = os.path.normpath(sys.argv[1])
    valid, errors, warnings = validate(workspace_path)

    # Report mode
    state_path = os.path.join(workspace_path, "state.json")
    mode = "ticker"
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        mode = state.get("mode", "ticker")
    mode_label = "Ticker Dive" if mode == "ticker" else "Sector Hunt"

    if valid:
        print(f"DOSSIER VALID [{mode_label}]")
        print("All prerequisites met. You may generate the Final Dossier.")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(f"  [WARN] {w}")
        sys.exit(0)
    else:
        print(f"DOSSIER INVALID [{mode_label}]")
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  [FAIL] {e}")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(f"  [WARN] {w}")
        print("\nFix all errors before generating the Final Dossier.")
        sys.exit(1)
