#!/usr/bin/env python3
"""
Red Team Debate Validator: Validates Socratic Debate completeness in Stage 4.
Checks: round files, defense files, round pairing, minimum 2 rounds, thesis revision.

Usage: python redteam_debate_validator.py <workspace_path>

Called by gate_check.py during stage_4 -> stage_5 transition.
"""
import os
import sys
import re


def list_md_files(directory: str) -> list[str]:
    if not os.path.exists(directory):
        return []
    return sorted([f for f in os.listdir(directory) if f.endswith(".md")])


def validate_debate(workspace_path: str) -> tuple[bool, list[str]]:
    redteam_dir = os.path.join(workspace_path, "redteam")
    if not os.path.exists(redteam_dir):
        return False, ["redteam/ directory not found"]

    files = list_md_files(redteam_dir)

    violations = []

    # Check for redteam files (round{N}_redteam.md)
    redteam_files = [f for f in files if "redteam" in f.lower()]
    if not redteam_files:
        violations.append("No redteam/round{N}_redteam.md files found")

    # Check for defense files (round{N}_defense.md)
    defense_files = [f for f in files if "defense" in f.lower()]
    if not defense_files:
        violations.append(
            "No redteam/round{N}_defense.md files found - "
            "main thread must respond to each Red Team round"
        )

    # Check round pairing: every redteam round (except possibly the last) should have a defense
    redteam_round_nums = set()
    defense_round_nums = set()

    for f in redteam_files:
        match = re.search(r'round(\d+)', f.lower())
        if match:
            redteam_round_nums.add(int(match.group(1)))

    for f in defense_files:
        match = re.search(r'round(\d+)', f.lower())
        if match:
            defense_round_nums.add(int(match.group(1)))

    for round_num in sorted(redteam_round_nums):
        if round_num not in defense_round_nums and round_num < max(redteam_round_nums, default=0):
            violations.append(f"Round {round_num} Red Team has no corresponding defense file")

    # Minimum 2 rounds of Socratic debate
    if len(redteam_round_nums) < 2:
        violations.append(
            f"Only {len(redteam_round_nums)} Red Team round(s) - "
            "minimum 2 required for Socratic debate"
        )

    # Check for thesis revision file
    revision_files = [f for f in files if "revision" in f.lower() or "thesis" in f.lower()]
    if not revision_files:
        violations.append("No thesis revision file found in redteam/ - Stage 4 incomplete")

    passed = len(violations) == 0
    return passed, violations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python redteam_debate_validator.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = validate_debate(workspace)
    if passed:
        print("RED TEAM DEBATE VALIDATOR PASSED: Socratic debate is complete")
        sys.exit(0)
    else:
        print("RED TEAM DEBATE VALIDATOR FAILED")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
