#!/usr/bin/env python3
"""Detect optional SOFA helper capabilities without changing user state."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capability_policy import FINANCE_CAPABILITIES, SEARCH_CHAIN

SKILL_ROOTS = [
    ".agents/skills",
    ".codex/skills",
    ".claude/skills",
]

WIND_SKILLS = [
    "wind-mcp-skill",
    "wind-find-finance-skill",
]

HOST_BUILTIN_EVIDENCE = [
    "Not externally detectable by SOFA; inspect the current host agent."
]


def scan_environment(
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return optional capability status without exposing secret values."""

    home_path = Path.home() if home is None else Path(home)
    env_data = dict(os.environ if env is None else env)

    evidence_by_id = {
        "anysearch": _existing_paths(
            home_path / root / "anysearch" for root in SKILL_ROOTS
        ),
        "exa": ["EXA_API_KEY present"] if env_data.get("EXA_API_KEY") else [],
        "tavily": _tavily_evidence(env_data, env_is_explicit=env is not None),
        "host_builtin": HOST_BUILTIN_EVIDENCE,
        "wind": _wind_evidence(home_path, env_data),
        "yfinance": (
            ["Python module yfinance importable"] if _module_present("yfinance") else []
        ),
    }

    search_chain = [
        {
            "id": provider.provider_id,
            "name": provider.display_label,
            "configured": (
                provider.provider_id != "host_builtin"
                and bool(evidence_by_id[provider.provider_id])
            ),
            "evidence": evidence_by_id[provider.provider_id],
            "recommendation": provider.recommendation,
        }
        for provider in SEARCH_CHAIN
    ]

    finance = {
        entry.provider_id: {
            "configured": bool(evidence_by_id[entry.provider_id]),
            "evidence": evidence_by_id[entry.provider_id],
            "recommendation": entry.recommendation,
        }
        for entry in FINANCE_CAPABILITIES
    }

    recommendations = []
    for entry in search_chain[:3]:
        if not entry["configured"]:
            recommendations.append(entry["recommendation"])
    for name in ("wind", "yfinance"):
        if not finance[name]["configured"]:
            recommendations.append(finance[name]["recommendation"])

    return {
        "schema_version": "1.1",
        "search_chain": search_chain,
        "finance": finance,
        "recommendations": recommendations,
    }


def _tavily_evidence(env_data: dict[str, str], *, env_is_explicit: bool) -> list[str]:
    evidence = []
    if env_data.get("TAVILY_API_KEY"):
        evidence.append("TAVILY_API_KEY present")
    if _command_present("tvly", env_data, env_is_explicit=env_is_explicit):
        evidence.append("tvly command present")
    return evidence


def _existing_paths(paths) -> list[str]:
    return [str(path) for path in paths if path.exists()]


def _command_present(
    command: str,
    env: dict[str, str],
    *,
    env_is_explicit: bool,
) -> bool:
    if env_is_explicit:
        return shutil.which(command, path=env.get("PATH", "")) is not None
    return shutil.which(command) is not None


def _module_present(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _wind_evidence(home: Path, env: dict[str, str]) -> list[str]:
    evidence = []
    if env.get("WIND_API_KEY"):
        evidence.append("WIND_API_KEY present")

    skill_paths = [
        home / root / skill_name
        for root in SKILL_ROOTS
        for skill_name in WIND_SKILLS
    ]
    evidence.extend(_existing_paths(skill_paths))

    config_paths = [home / ".wind-aifinmarket/config"]
    config_paths.extend(path / "config.json" for path in skill_paths)
    evidence.extend(_existing_paths(config_paths))
    return evidence


def _render_summary(report: dict[str, Any]) -> str:
    lines = [
        f"SOFA capability check schema {report['schema_version']}",
        "",
        "Search chain:",
    ]
    for entry in report["search_chain"]:
        status = "configured" if entry["configured"] else "not configured"
        lines.append(f"- {entry['name']}: {status}")
        for item in entry["evidence"]:
            lines.append(f"  evidence: {item}")

    lines.extend(["", "Finance:"])
    for name, entry in report["finance"].items():
        status = "configured" if entry["configured"] else "not configured"
        lines.append(f"- {name}: {status}")
        for item in entry["evidence"]:
            lines.append(f"  evidence: {item}")

    lines.extend(["", "Recommendations:"])
    for item in report["recommendations"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect optional SOFA helper capabilities without changing state."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a human summary.",
    )
    args = parser.parse_args(argv)

    report = scan_environment()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
