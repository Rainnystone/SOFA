#!/usr/bin/env python3
"""Detect optional SOFA helper capabilities without changing user state."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any


SEARCH_CHAIN_NAMES = [
    "AnySearch skill",
    "Exa MCP server",
    "Tavily",
    "Host-agent built-ins",
]

SKILL_ROOTS = [
    ".agents/skills",
    ".codex/skills",
    ".claude/skills",
]

WIND_SKILLS = [
    "wind-mcp-skill",
    "wind-find-finance-skill",
]


def scan_environment(
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return optional capability status without exposing secret values."""

    home_path = Path.home() if home is None else Path(home)
    env_data = dict(os.environ if env is None else env)

    anysearch_evidence = _existing_paths(
        home_path / root / "anysearch" for root in SKILL_ROOTS
    )
    exa_evidence = ["EXA_API_KEY present"] if env_data.get("EXA_API_KEY") else []

    tavily_evidence = []
    if env_data.get("TAVILY_API_KEY"):
        tavily_evidence.append("TAVILY_API_KEY present")
    if _command_present("tvly", env_data, env_is_explicit=env is not None):
        tavily_evidence.append("tvly command present")

    wind_evidence = _wind_evidence(home_path, env_data)
    yfinance_evidence = (
        ["Python module yfinance importable"] if _module_present("yfinance") else []
    )

    search_chain = [
        {
            "name": "AnySearch skill",
            "configured": bool(anysearch_evidence),
            "evidence": anysearch_evidence,
            "recommendation": (
                "Install AnySearch from https://github.com/anysearch-ai/anysearch-skill "
                "as the preferred general-search skill."
            ),
        },
        {
            "name": "Exa MCP server",
            "configured": bool(exa_evidence),
            "evidence": exa_evidence,
            "recommendation": (
                "Configure Exa MCP from https://github.com/exa-labs/exa-mcp-server "
                "with EXA_API_KEY after AnySearch if MCP search is available."
            ),
        },
        {
            "name": "Tavily",
            "configured": bool(tavily_evidence),
            "evidence": tavily_evidence,
            "recommendation": (
                "Install Tavily skills from https://github.com/tavily-ai/skills "
                "or use the Tavily CLI as a later JSON-friendly search fallback."
            ),
        },
        {
            "name": "Host-agent built-ins",
            "configured": False,
            "evidence": [
                "Not externally detectable by SOFA; inspect the current host agent."
            ],
            "recommendation": (
                "Use host-agent built-in search only after AnySearch, Exa, and Tavily "
                "are unavailable or unsuitable."
            ),
        },
    ]

    finance = {
        "wind": {
            "configured": bool(wind_evidence),
            "evidence": wind_evidence,
            "recommendation": (
                "Chinese financial-data users should read "
                "https://aifinmarket.wind.com.cn/skill.md, install Wind financial "
                "capability after choosing project or global scope, and configure "
                "credentials only after explicit confirmation."
            ),
        },
        "yfinance": {
            "configured": bool(yfinance_evidence),
            "evidence": yfinance_evidence,
            "recommendation": (
                "English/global public-market users can install yfinance with "
                "python3 -m pip install yfinance and treat it as a research aid, "
                "not an authoritative filing source."
            ),
        },
    }

    recommendations = []
    for entry in search_chain[:3]:
        if not entry["configured"]:
            recommendations.append(entry["recommendation"])
    for entry in (finance["wind"], finance["yfinance"]):
        if not entry["configured"]:
            recommendations.append(entry["recommendation"])

    return {
        "schema_version": "1.0",
        "search_chain": search_chain,
        "finance": finance,
        "recommendations": recommendations,
    }


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
