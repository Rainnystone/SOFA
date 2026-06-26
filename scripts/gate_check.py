#!/usr/bin/env python3
"""
Serenity OSINT Gate Check — Enhanced v3.6

Validates that all prerequisites for a stage transition are met.
Mode-aware: reads state.json mode field to apply correct checks for
Ticker Dive vs Sector Hunt workflows.

Integrates loop_enforcer, scorecard_validator, timeliness_checker,
synthesis_checker, and redteam_debate_validator.

Usage:
    python gate_check.py <WORKSPACE_PATH> <FROM_STAGE> <TO_STAGE>
    python gate_check.py <WORKSPACE_PATH> complete <STAGE>
    python gate_check.py <WORKSPACE_PATH> loop

Stage names: stage_0, stage_1, stage_2, stage_3, stage_4, stage_5, stage_6
"""

import json
import os
import re
import sys

# Import enhanced enforcers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loop_enforcer import check_loop_depth
from scorecard_validator import validate_scorecards
from timeliness_checker import check_timeliness
from synthesis_checker import check_synthesis
from redteam_debate_validator import validate_debate
from frontier_lifecycle import LifecycleError, derive_loop_counts, validate_for_stage_transition
from sofa_contract import ContractProfile, evaluate_workspace


def load_state(workspace_path: str) -> dict:
    state_path = os.path.join(workspace_path, "state.json")
    if not os.path.exists(state_path):
        return None
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_frontier_registry(workspace_path: str) -> dict | None:
    registry_path = os.path.join(workspace_path, "frontier_registry.json")
    if not os.path.exists(registry_path):
        return None
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(workspace_path: str, state: dict) -> None:
    state_path = os.path.join(workspace_path, "state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def file_exists(workspace_path: str, relative_path: str) -> bool:
    return os.path.exists(os.path.join(workspace_path, relative_path))


def count_files(workspace_path: str, subdir: str) -> int:
    dir_path = os.path.join(workspace_path, subdir)
    if not os.path.exists(dir_path):
        return 0
    return len([f for f in os.listdir(dir_path) if f.endswith(".md")])


def dedupe_stage_2_missing_items(items: list[str]) -> list[str]:
    normalized_items = {
        "evidence_ledger.md does not exist": "evidence_ledger.md not found",
        "frontier_registry.json not found": "frontier_registry.json not found - run init_workspace.py first",
    }
    deduped = []
    seen = set()
    for item in items:
        normalized = normalized_items.get(item, item)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def check_gate(workspace_path: str, from_stage: str, to_stage: str) -> tuple[bool, list[str]]:
    """
    Returns (passed, missing_items)
    """
    missing = []
    state = load_state(workspace_path)

    if state is None:
        return False, ["state.json not found - run init_workspace.py first"]

    mode = state.get("mode", "ticker")

    # Common checks
    if not file_exists(workspace_path, "research_workflow.md"):
        missing.append("research_workflow.md does not exist")
    if not file_exists(workspace_path, "evidence_ledger.md"):
        missing.append("evidence_ledger.md does not exist")

    # Stage-specific checks
    if from_stage == "stage_0":
        if "stage_0" not in state.get("stages_completed", []):
            missing.append("Stage 0 not marked as completed in state.json")

        # Check for Methodology Alignment Note, Demand Decomposition, and Blind Spot
        wf_path = os.path.join(workspace_path, "research_workflow.md")
        if os.path.exists(wf_path):
            with open(wf_path, "r", encoding="utf-8") as f:
                wf_content = f.read()
            if "## Methodology Alignment" not in wf_content and "## 方法论对齐" not in wf_content:
                missing.append("research_workflow.md missing Methodology Alignment Note (Pre-Stage 0 requirement)")
            if "## Demand Decomposition" not in wf_content and "## 需求拆解" not in wf_content:
                missing.append("research_workflow.md missing Demand Decomposition Sketch (Stage 0 requirement)")
            if "## Blind Spot Report" not in wf_content and "## 盲区报告" not in wf_content:
                missing.append("research_workflow.md missing Blind Spot Report (Stage 0 requirement)")

            # Sector mode: also check Architecture Shift Brief
            if mode == "sector":
                if "## Architecture Shift" not in wf_content and "## 架构迁移" not in wf_content:
                    missing.append("research_workflow.md missing Architecture Shift Brief (Sector Hunt Stage 0 requirement)")

    elif from_stage == "stage_1":
        if "stage_1" not in state.get("stages_completed", []):
            missing.append("Stage 1 not marked as completed in state.json")

    elif from_stage == "stage_2":
        # Stage 2 -> Stage 3: mode-aware evidence loop checks
        loop_count = state.get("loop_count", 0)
        if loop_count < 3:
            missing.append(f"Only {loop_count} loop(s) completed - minimum 3 required")

        if mode == "ticker":
            # Ticker Dive: Scout + Challenge files
            scout_count = count_files(workspace_path, "scouts")
            challenge_count = count_files(workspace_path, "challenges")

            if scout_count < 3:
                missing.append(f"Only {scout_count} scout file(s) - minimum 3 required")
            if challenge_count < 3:
                missing.append(f"Only {challenge_count} challenge file(s) - minimum 3 required")
            if scout_count != challenge_count:
                missing.append(f"Scout count ({scout_count}) != Challenge count ({challenge_count})")

        elif mode == "sector":
            # Sector Hunt: Mapping files + Coverage files
            maps_count = count_files(workspace_path, "maps")
            # dependency_ladder.md is not a loop output, so subtract 1 if it exists
            ladder_path = os.path.join(workspace_path, "maps", "dependency_ladder.md")
            if os.path.exists(ladder_path):
                maps_count -= 1
            if maps_count < 3:
                missing.append(f"Only {maps_count} mapping file(s) in maps/ - minimum 3 required")

            coverage_count = count_files(workspace_path, "coverage")
            if coverage_count < 3:
                missing.append(f"Only {coverage_count} coverage challenge file(s) in coverage/ - minimum 3 required")

            # Check dependency ladder exists
            if not os.path.exists(ladder_path):
                missing.append("maps/dependency_ladder.md not found (Sector Hunt core deliverable)")

        # === ENHANCED ENFORCERS (v3.3) ===
        # 1. Loop Enforcer: ledger loop headers must bind to stable frontier IDs
        passed_loop, loop_violations = check_loop_depth(workspace_path)
        if not passed_loop:
            missing.extend(loop_violations)

        registry = load_frontier_registry(workspace_path)
        if registry is None:
            missing.append("frontier_registry.json not found - run init_workspace.py first")
        elif passed_loop:
            ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
            try:
                with open(ledger_path, "r", encoding="utf-8") as f:
                    ledger_content = f.read()
                loop_counts = derive_loop_counts(ledger_content, registry)
                passed_lifecycle, lifecycle_violations = validate_for_stage_transition(
                    registry,
                    loop_counts,
                    mode,
                    to_stage,
                )
                if not passed_lifecycle:
                    missing.extend(lifecycle_violations)
            except FileNotFoundError:
                missing.append("evidence_ledger.md not found")
            except LifecycleError as exc:
                missing.append(str(exc))

        # 2. Scorecard Validator: Gate Scorecards must be filled
        passed_sc, sc_violations = validate_scorecards(workspace_path)
        if not passed_sc:
            missing.extend(sc_violations)

        # 3. Timeliness Checker: recent events must be tracked
        passed_time, time_violations = check_timeliness(workspace_path)
        if not passed_time:
            missing.extend(time_violations)

        # Check for Serendipity Loop findings (required after 3 frontiers)
        wf_path = os.path.join(workspace_path, "research_workflow.md")
        if os.path.exists(wf_path):
            with open(wf_path, "r", encoding="utf-8") as f:
                wf_content = f.read()
            if "Serendipity" not in wf_content and "意外发现" not in wf_content:
                missing.append("research_workflow.md missing Serendipity Loop findings (required after 3 frontiers in Stage 2)")

        if "stage_2" not in state.get("stages_completed", []):
            missing.append("Stage 2 not marked as completed in state.json")

        missing = dedupe_stage_2_missing_items(missing)

    elif from_stage == "stage_3":
        # Stage 3 -> Stage 4: mode-aware financial checks
        if mode == "ticker":
            # Ticker Dive: full Financial Bridge required
            bridge_count = count_files(workspace_path, "financials")
            if bridge_count < 1:
                missing.append("No financial bridge report found in financials/")
        # Sector mode: Financial Screen is recommended but not gate-blocking

        # 4. Synthesis Checker: Synthesis Notes must have substantive content
        passed_syn, syn_violations = check_synthesis(workspace_path)
        if not passed_syn:
            missing.extend(syn_violations)

        # Check for Pre-Mortem and Cognitive Frame Analysis (common)
        wf_path = os.path.join(workspace_path, "research_workflow.md")
        if os.path.exists(wf_path):
            with open(wf_path, "r", encoding="utf-8") as f:
                wf_content = f.read()
            if "## Pre-Mortem" not in wf_content and "## 事前验尸" not in wf_content:
                missing.append("research_workflow.md missing Pre-Mortem (Stage 3 requirement)")
            if "## Cognitive Frame" not in wf_content and "## 认知框架" not in wf_content:
                missing.append("research_workflow.md missing Cognitive Frame Analysis (Stage 3 requirement)")

            # Sector mode: also check Chokepoint Scoring
            if mode == "sector":
                if "## Chokepoint Scoring" not in wf_content and "## 扼点评分" not in wf_content:
                    missing.append("research_workflow.md missing Chokepoint Scoring Matrix (Sector Hunt Stage 3 requirement)")
                if "## Ranked Candidate" not in wf_content and "## 排序候选" not in wf_content:
                    missing.append("research_workflow.md missing Ranked Candidate Queue (Sector Hunt Stage 3 requirement)")

        if "stage_3" not in state.get("stages_completed", []):
            missing.append("Stage 3 not marked as completed in state.json")

    elif from_stage == "stage_4":
        # Stage 4 -> Stage 5: Red Team / Mapping Integrity Review
        # 5. Red Team Debate Validator: rounds, defense files, thesis revision
        passed_debate, debate_violations = validate_debate(workspace_path)
        if not passed_debate:
            missing.extend(debate_violations)

        # Soft warning: recommend 3 rounds
        redteam_dir = os.path.join(workspace_path, "redteam")
        if os.path.exists(redteam_dir):
            redteam_files = [f for f in os.listdir(redteam_dir) if "redteam" in f.lower()]
            rounds_count = len(redteam_files)
            if rounds_count < 3:
                # Non-blocking warning
                print(f"[WARN] Red Team has {rounds_count} rounds. 3 rounds recommended for thorough stress testing.")

            # Check Round 4+ defense pairing
            for f in redteam_files:
                match = re.match(r"round(\d+)_redteam", f, re.IGNORECASE)
                if match and int(match.group(1)) >= 4:
                    round_num = match.group(1)
                    defense_file = f"round{round_num}_defense.md"
                    if not os.path.exists(os.path.join(redteam_dir, defense_file)):
                        missing.append(f"Red Team Round {round_num} has no corresponding defense file ({defense_file})")

        if "stage_4" not in state.get("stages_completed", []):
            missing.append("Stage 4 not marked as completed in state.json")

    elif from_stage == "stage_5":
        if "stage_5" not in state.get("stages_completed", []):
            missing.append("Stage 5 not marked as completed in state.json")

        contract = evaluate_workspace(
            workspace_path,
            ContractProfile(
                mode=mode,
                target="stage_transition",
                from_stage=from_stage,
                to_stage=to_stage,
            ),
        )
        missing.extend(issue.display() for issue in contract.failures)
        for warning in contract.warnings:
            print(f"[WARN] {warning.display()}")

    passed = len(missing) == 0
    return passed, missing


def complete_stage(workspace_path: str, stage: str) -> None:
    """Mark a stage as completed in state.json"""
    state = load_state(workspace_path)
    if state is None:
        print("ERROR: state.json not found - run init_workspace.py first")
        sys.exit(1)

    if "stages_completed" not in state:
        state["stages_completed"] = []

    if stage not in state["stages_completed"]:
        state["stages_completed"].append(stage)

    # Update current_stage to next
    stage_order = ["stage_0", "stage_1", "stage_2", "stage_3", "stage_4", "stage_5", "stage_6"]
    idx = stage_order.index(stage)
    if idx + 1 < len(stage_order):
        state["current_stage"] = stage_order[idx + 1]

    save_state(workspace_path, state)
    # Keep the human-readable Stage Progress mirror in sync; otherwise the
    # dossier contract's STATE_WORKFLOW_STAGE_CONFLICT check rejects any
    # workspace advanced purely via this CLI (init_workspace.py starts every
    # row as pending).
    _set_workflow_stage_status(workspace_path, stage, "complete")
    print(f"STAGE COMPLETED: {stage}")


def _set_workflow_stage_status(workspace_path: str, stage: str, status: str) -> None:
    """Flip one Stage Progress row's status cell in research_workflow.md.

    Mirrors parse_stage_progress: matches '| Stage N: ... | <status> | ...'.
    Only the status cell is rewritten; the rest of the row is preserved.
    Silently no-ops if the workflow file or the row is absent.
    """
    wf_path = os.path.join(workspace_path, "research_workflow.md")
    if not os.path.exists(wf_path):
        return
    try:
        stage_num = stage.split("_", 1)[1]
    except IndexError:
        return
    with open(wf_path, "r", encoding="utf-8") as handle:
        content = handle.read()
    pattern = re.compile(
        r"^(\|\s*Stage\s+" + re.escape(stage_num) + r"\b[^\n|]*\|\s*)([^\n|]+?)(\s*\|[^\n]*)$",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return
    if match.group(2).strip().lower() == status.lower():
        return
    new_row = match.group(1) + status + match.group(3)
    with open(wf_path, "w", encoding="utf-8") as handle:
        handle.write(content[: match.start()] + new_row + content[match.end():])


def increment_loop(workspace_path: str) -> int:
    """Increment loop counter and return new count"""
    state = load_state(workspace_path)
    if state is None:
        print("ERROR: state.json not found - run init_workspace.py first")
        sys.exit(1)

    state["loop_count"] = state.get("loop_count", 0) + 1
    save_state(workspace_path, state)
    print(f"LOOP STARTED: #{state['loop_count']}")
    return state["loop_count"]


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so output containing non-ASCII (e.g.
    # bilingual section names like "## 综合分析笔记" carried through from the
    # synthesis/gate checks) prints consistently on every platform. Without
    # this, Windows pipes default to cp1252 and the subprocess crashes with
    # UnicodeEncodeError mid-output (exit 1) even when the gate itself passed.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python gate_check.py <workspace> <from_stage> <to_stage>")
        print("  python gate_check.py <workspace> complete <stage>")
        print("  python gate_check.py <workspace> loop")
        print("")
        print("Stage names: stage_0, stage_1, stage_2, stage_3, stage_4, stage_5, stage_6")
        sys.exit(1)

    workspace_path = os.path.normpath(sys.argv[1])

    if len(sys.argv) == 3 and sys.argv[2] == "loop":
        increment_loop(workspace_path)
        sys.exit(0)

    if len(sys.argv) == 4 and sys.argv[2] == "complete":
        complete_stage(workspace_path, sys.argv[3])
        sys.exit(0)

    if len(sys.argv) == 4:
        from_stage = sys.argv[2]
        to_stage = sys.argv[3]

        passed, missing = check_gate(workspace_path, from_stage, to_stage)

        if passed:
            print(f"GATE PASSED: {from_stage} -> {to_stage}")
            print("All prerequisites met. Proceed to next stage.")
            sys.exit(0)
        else:
            print(f"GATE FAILED: {from_stage} -> {to_stage}")
            print(f"Missing {len(missing)} prerequisite(s):")
            for i, item in enumerate(missing, 1):
                print(f"  {i}. {item}")
            print("")
            print("Fix the above issues before proceeding.")
            sys.exit(1)
    else:
        print("Invalid arguments. Run without arguments for usage.")
        sys.exit(1)
