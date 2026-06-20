#!/usr/bin/env python3
"""
Timeliness Checker: Validates that evidence_ledger.md and research_workflow.md
contain records of timeliness-aware searches (Stage 0 framing, recent events).

Usage: python3 timeliness_checker.py <workspace_path>

Called by gate_check.py during stage_2 -> stage_3 transition.
"""
import os
import sys
import re


def check_timeliness(workspace_path: str) -> tuple[bool, list[str]]:
    """
    Check that the research has timeliness awareness: recent events, conferences,
    earnings, product launches, or other time-sensitive context.
    """
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    workflow_path = os.path.join(workspace_path, "research_workflow.md")

    violations = []

    # Check evidence_ledger for timeliness keywords
    if os.path.exists(ledger_path):
        with open(ledger_path, "r", encoding="utf-8") as f:
            content = f.read()

        timeliness_keywords = [
            "时效性", "recent", "news", "conference", "event",
            "computex", "ofc", "ecoc", "gtc", "keynote",
            "announcement", "launch", "product", "earnings",
            "press release", "filing", "quarterly", "annual report"
        ]
        has_timeliness = any(kw in content.lower() for kw in timeliness_keywords)
        if not has_timeliness:
            violations.append("No timeliness/recent events recorded in evidence_ledger.md")
    else:
        violations.append("evidence_ledger.md not found")

    # Check research_workflow for Stage 0 search records
    if os.path.exists(workflow_path):
        with open(workflow_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "Stage 0" in content or "Framing" in content or "framing" in content:
            has_search = ("search" in content.lower() or "websearch" in content.lower()
                          or "anysearch" in content.lower() or "搜索" in content)
            if not has_search:
                violations.append("research_workflow.md does not appear to have Stage 0 search records")
    else:
        violations.append("research_workflow.md not found")

    passed = len(violations) == 0
    return passed, violations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 timeliness_checker.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = check_timeliness(workspace)
    if passed:
        print("TIMELINESS CHECKER PASSED: Recent events tracked")
        sys.exit(0)
    else:
        print("TIMELINESS CHECKER FAILED")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
