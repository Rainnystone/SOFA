#!/usr/bin/env python3
"""
Synthesis Checker: Validates that research_workflow.md Synthesis Notes section
has substantive analytical content (minimum 3 substantive lines).

Usage: python synthesis_checker.py <workspace_path>

Called by gate_check.py during stage_3 -> stage_4 transition.
"""
import os
import sys
import re


def check_synthesis(workspace_path: str) -> tuple[bool, list[str]]:
    workflow_path = os.path.join(workspace_path, "research_workflow.md")
    if not os.path.exists(workflow_path):
        return False, ["research_workflow.md not found"]

    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Support both English and Chinese section headers
    if "## Synthesis Notes" not in content and "## 综合分析笔记" not in content:
        return False, ["Missing '## Synthesis Notes' / '## 综合分析笔记' section in research_workflow.md"]

    # Extract Synthesis Notes content
    synthesis_match = re.search(
        r"## (Synthesis Notes|综合分析笔记).*?(?=## |\Z)",
        content, re.DOTALL
    )
    if not synthesis_match:
        return False, ["Synthesis Notes section is empty"]

    synthesis_content = synthesis_match.group(0)

    # Count substantive lines (exclude empty, quotes, headers, tables, list markers, short lines)
    substantive_lines = [
        l for l in synthesis_content.split("\n")
        if l.strip()
        and not l.strip().startswith(">")
        and not l.strip().startswith("#")
        and not l.strip().startswith("|")
        and not l.strip().startswith("-")
        and len(l.strip()) > 20  # At least 20 characters to count as substantive
    ]

    if len(substantive_lines) < 3:
        return False, [
            f"Synthesis Notes has only {len(substantive_lines)} substantive line(s) - minimum 3 required. "
            "Main thread must record cross-loop reasoning, not just dispatch subagents."
        ]

    return True, []


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so output containing non-ASCII (e.g.
    # bilingual section names like "## 综合分析笔记") prints consistently on
    # every platform. Without this, Windows pipes default to cp1252 and the
    # subprocess crashes with UnicodeEncodeError mid-output (exit 1) even when
    # validation itself passed.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python synthesis_checker.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = check_synthesis(workspace)
    if passed:
        print("SYNTHESIS CHECKER PASSED: Synthesis Notes has substantive content")
        sys.exit(0)
    else:
        print("SYNTHESIS CHECKER FAILED")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
