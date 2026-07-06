"""Deterministic SOFA capability policy facts.

Owns the search chain order, provider identity, finance capability
recommendations, search-record vocabulary, and missing-tool confidence
language. Detection mechanics live in capability_check.py; readiness
decisions live in sofa_contract. This module holds facts and renders
exact strings only.
"""

from __future__ import annotations

from dataclasses import dataclass


RESULT_STATUS_COMPLETED = "completed"
RESULT_STATUS_DEGRADED = "degraded_approved"
STAGE0_LOOP_ID = "stage_0"

DEAD_END_NO_RESULT = "no_result"
DEAD_END_TOOL_DEGRADED = "tool_degraded"
DEAD_END_BLOCKED_SOURCE = "blocked_source"
DEAD_END_CATEGORIES = (
    DEAD_END_NO_RESULT,
    DEAD_END_TOOL_DEGRADED,
    DEAD_END_BLOCKED_SOURCE,
)

_MISSING_TOOL_CONFIDENCE_LANGUAGE = (
    "Missing capabilities must be recorded in capability_report.md or the "
    "evidence ledger and must lower stated confidence; do not present a "
    "weaker fallback as equivalent to a purpose-built capability."
)


@dataclass(frozen=True)
class SearchProvider:
    provider_id: str
    display_label: str
    short_label: str
    chain_position: int
    recommendation: str
    detection_note: str


@dataclass(frozen=True)
class FinanceCapability:
    provider_id: str
    display_label: str
    short_label: str
    audience: str
    recommendation: str
    detection_note: str


SEARCH_CHAIN = (
    SearchProvider(
        provider_id="anysearch",
        display_label="AnySearch skill",
        short_label="AnySearch",
        chain_position=1,
        recommendation=(
            "Install AnySearch from https://github.com/anysearch-ai/anysearch-skill "
            "as the preferred general-search skill."
        ),
        detection_note="anysearch skill directory under a known skill root",
    ),
    SearchProvider(
        provider_id="exa",
        display_label="Exa MCP server",
        short_label="Exa",
        chain_position=2,
        recommendation=(
            "Configure Exa MCP from https://github.com/exa-labs/exa-mcp-server "
            "with EXA_API_KEY after AnySearch if MCP search is available."
        ),
        detection_note="EXA_API_KEY environment variable present",
    ),
    SearchProvider(
        provider_id="tavily",
        display_label="Tavily",
        short_label="Tavily",
        chain_position=3,
        recommendation=(
            "Install Tavily skills from https://github.com/tavily-ai/skills "
            "or use the Tavily CLI as a later JSON-friendly search fallback."
        ),
        detection_note="TAVILY_API_KEY environment variable or tvly command present",
    ),
    SearchProvider(
        provider_id="host_builtin",
        display_label="Host-agent built-ins",
        short_label="host-agent built-ins",
        chain_position=4,
        recommendation=(
            "Use host-agent built-in search only after AnySearch, Exa, and Tavily "
            "are unavailable or unsuitable."
        ),
        detection_note="Not externally detectable by SOFA; inspect the current host agent.",
    ),
)

FINANCE_CAPABILITIES = (
    FinanceCapability(
        provider_id="wind",
        display_label="Wind financial capability",
        short_label="Wind",
        audience="Chinese data",
        recommendation=(
            "Chinese financial-data users should read "
            "https://aifinmarket.wind.com.cn/skill.md, install Wind financial "
            "capability after choosing project or global scope, and configure "
            "credentials only after explicit confirmation."
        ),
        detection_note="WIND_API_KEY, Wind skill directories, or Wind config files present",
    ),
    FinanceCapability(
        provider_id="yfinance",
        display_label="yfinance",
        short_label="yfinance",
        audience="English/global public-market data",
        recommendation=(
            "English/global public-market users can install yfinance with "
            "python -m pip install yfinance and treat it as a research aid, "
            "not an authoritative filing source."
        ),
        detection_note="Python module yfinance importable",
    ),
)

_ALL_PROVIDERS = SEARCH_CHAIN + FINANCE_CAPABILITIES


def provider_for_id(provider_id: str):
    for provider in _ALL_PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    raise ValueError(f"Unknown SOFA capability provider id: {provider_id!r}")


def recommendation_for_missing(provider_id: str) -> str:
    return provider_for_id(provider_id).recommendation


def missing_tool_confidence_language() -> str:
    return _MISSING_TOOL_CONFIDENCE_LANGUAGE


def render_chain_arrow() -> str:
    ordered = sorted(SEARCH_CHAIN, key=lambda provider: provider.chain_position)
    return " -> ".join(provider.short_label for provider in ordered)


def render_finance_summary() -> str:
    return "; ".join(
        f"{entry.short_label} for {entry.audience}" for entry in FINANCE_CAPABILITIES
    )


def render_setup_recommendation_lines() -> tuple[str, str]:
    wind = provider_for_id("wind")
    yfinance = provider_for_id("yfinance")
    return (
        f"SOFA recommends {render_chain_arrow()} for general search.",
        f"SOFA recommends {wind.short_label} for Chinese financial data "
        f"and {yfinance.short_label} for English/global public-market data.",
    )


def validate_policy() -> list[str]:
    issues: list[str] = []
    seen_ids: set[str] = set()
    for provider in _ALL_PROVIDERS:
        if provider.provider_id in seen_ids:
            issues.append(f"duplicate provider id: {provider.provider_id}")
        seen_ids.add(provider.provider_id)
        if not provider.recommendation.strip():
            issues.append(f"{provider.provider_id} has an empty recommendation")
        if not provider.detection_note.strip():
            issues.append(f"{provider.provider_id} has an empty detection note")

    positions = [provider.chain_position for provider in SEARCH_CHAIN]
    if positions != list(range(1, len(SEARCH_CHAIN) + 1)):
        issues.append(f"search chain positions are not sequential: {positions}")

    if len(set(DEAD_END_CATEGORIES)) != len(DEAD_END_CATEGORIES):
        issues.append("dead-end categories contain duplicates")

    return issues
