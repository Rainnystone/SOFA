#!/usr/bin/env python3
"""Ledger-to-frontier registry binding checks for SOFA.

Usage: python loop_enforcer.py <workspace_path>

Called by gate_check.py during stage_2 -> stage_3 transition.
"""
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frontier_lifecycle import LifecycleError, derive_loop_counts, validate_registry


def check_ledger_binding(
    ledger_text: str,
    registry: dict,
) -> tuple[bool, dict[str, int], list[str]]:
    """Check that ledger loop headers bind to known stable frontier IDs."""
    try:
        validate_registry(registry)
        counts = derive_loop_counts(ledger_text, registry)
    except LifecycleError as exc:
        return False, {}, [str(exc)]

    for frontier in registry.get("frontiers", []):
        counts.setdefault(frontier["id"], 0)

    return True, counts, []


def check_loop_depth_from_documents(
    ledger_text: str,
    registry: dict[str, Any],
) -> tuple[bool, dict[str, int], list[str]]:
    passed, counts, violations = check_ledger_binding(ledger_text, registry)
    if not passed:
        return False, counts, violations
    if registry.get("frontiers") and not any(counts.values()):
        return False, counts, [
            "No ledger loop entries found for registered frontiers"
        ]
    return True, counts, []


def check_loop_depth(workspace_path: str) -> tuple[bool, list[str]]:
    """Backward-compatible gate_check entrypoint for ledger binding checks."""
    ledger_path = os.path.join(workspace_path, "evidence_ledger.md")
    if not os.path.exists(ledger_path):
        return False, ["evidence_ledger.md not found"]

    registry_path = os.path.join(workspace_path, "frontier_registry.json")
    if not os.path.exists(registry_path):
        return False, ["frontier_registry.json not found"]

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger_text = f.read()

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        validate_registry(registry)
    except (OSError, UnicodeError, json.JSONDecodeError, LifecycleError) as exc:
        return False, [f"frontier registry invalid: {exc}"]

    passed, _, violations = check_loop_depth_from_documents(ledger_text, registry)
    if not passed:
        return False, violations

    return True, []


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so output containing non-ASCII (e.g.
    # bilingual section names) prints consistently on every platform. Without
    # this, Windows pipes default to cp1252 and the subprocess crashes with
    # UnicodeEncodeError mid-output (exit 1) even when validation itself passed.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Usage: python loop_enforcer.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]
    passed, violations = check_loop_depth(workspace)
    if passed:
        print("LOOP ENFORCER PASSED: Ledger loop headers bind to frontier_registry.json")
        sys.exit(0)
    else:
        print("LOOP ENFORCER FAILED: Ledger binding check failed")
        for v in violations:
            print(f"  [FAIL] {v}")
        sys.exit(1)
