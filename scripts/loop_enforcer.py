#!/usr/bin/env python3
"""
Loop Enforcer: Validates each frontier has at least 2 completed loops.
Parses evidence_ledger.md "## Loop N: Frontier Name" entries and groups by frontier.

Usage: python3 loop_enforcer.py <workspace_path>

Called by gate_check.py during stage_2 -> stage_3 transition.
"""
import os
import sys
import re


def check_loop_depth(workspace_path: str) -> tuple[bool, list[str]]:
    """
    Check that each frontier in evidence_ledger.md has at least 2 loops.
    Returns: (passed, violations)
    """
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    if not os.path.exists(ledger_path):
        return False, ["evidence_ledger.md not found"]

    with open(ledger_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse "## Loop N: Frontier Name" format
    loop_pattern = re.compile(r"^## Loop \d+:\s*(.+)$", re.MULTILINE)
    loops = loop_pattern.findall(content)

    if not loops:
        return False, ["No loop entries found in evidence_ledger.md"]

    # Group by frontier name
    frontier_loops: dict[str, int] = {}
    for frontier_name in loops:
        frontier = frontier_name.strip()
        if frontier not in frontier_loops:
            frontier_loops[frontier] = 0
        frontier_loops[frontier] += 1

    violations = []
    for frontier, count in frontier_loops.items():
        if count < 2:
            violations.append(
                f"Frontier '{frontier}' only has {count} loop(s) - minimum 2 required per frontier"
            )

    passed = len(violations) == 0
    return passed, violations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 loop_enforcer.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = check_loop_depth(workspace)
    if passed:
        print("LOOP ENFORCER PASSED: All frontiers have >= 2 loops")
        sys.exit(0)
    else:
        print("LOOP ENFORCER FAILED")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
