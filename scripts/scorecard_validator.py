#!/usr/bin/env python3
"""
Scorecard Validator: Validates Gate Scorecard table in research_workflow.md.
Checks that Evidence Loop Tracker has filled Gate Score and Decision columns.

Usage: python scorecard_validator.py <workspace_path>

Called by gate_check.py during stage_2 -> stage_3 transition.
"""
import os
import sys
import re


def validate_scorecards(workspace_path: str) -> tuple[bool, list[str]]:
    workflow_path = os.path.join(workspace_path, "research_workflow.md")
    if not os.path.exists(workflow_path):
        return False, ["research_workflow.md not found"]

    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find Evidence Loop Tracker section
    tracker_match = re.search(
        r"## Evidence Loop Tracker.*?(?=## |\Z)",
        content, re.DOTALL
    )
    if not tracker_match:
        return False, ["Evidence Loop Tracker section not found in research_workflow.md"]

    tracker_content = tracker_match.group(0)

    # Count data rows (exclude header and separator)
    lines = tracker_content.strip().split("\n")
    data_rows = []
    for line in lines:
        line = line.strip()
        if line.startswith("|") and not line.startswith("|---") and "Loop#" not in line:
            data_rows.append(line)

    if not data_rows:
        return False, ["Evidence Loop Tracker has no data rows - scorecards not filled"]

    # Check each row has Gate Score and Decision filled
    violations = []
    for i, row in enumerate(data_rows, 1):
        cells = [c.strip() for c in row.split("|")[1:-1]]
        # Expected 6 columns: Loop# | Frontier | Scout File | Challenge File | Gate Score | Decision
        if len(cells) < 6:
            violations.append(f"Row {i}: incomplete scorecard (only {len(cells)} cells, expected 6)")
            continue
        if cells[4] in ["", "-", " ", "None"]:
            violations.append(f"Loop row {i}: Gate Score is empty")
        if cells[5] in ["", "-", " ", "None"]:
            violations.append(f"Loop row {i}: Decision is empty")

    passed = len(violations) == 0
    return passed, violations


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so output containing non-ASCII (e.g.
    # bilingual section names) prints consistently on every platform. Without
    # this, Windows pipes default to cp1252 and the subprocess crashes with
    # UnicodeEncodeError mid-output (exit 1) even when validation itself passed.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python scorecard_validator.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = validate_scorecards(workspace)
    if passed:
        print("SCORECARD VALIDATOR PASSED: All scorecards filled")
        sys.exit(0)
    else:
        print("SCORECARD VALIDATOR FAILED")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
