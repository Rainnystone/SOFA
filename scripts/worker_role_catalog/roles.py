from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


VALID_MODES = ("ticker", "sector", "ultra")
ACTION_CLASS_LANGUAGE = "action_class_language"
METHOD_CARDS_ROOT = "skills/sofa-analyze/method-cards"

SOURCE_TRACE_MARKERS = (
    "Search Exhaustion Report",
    "Sources consulted",
    "Source Pack",
    "Evidence Sources",
    "检索",
    "来源",
)

SOURCE_TRACE_LABEL_PATTERN = re.compile(
    r"^(?:#{1,6}\s*)?(?:Search Exhaustion Report|Sources consulted|Source Pack|Evidence Sources|检索|来源)\s*(?::|：|-|$)",
    re.IGNORECASE,
)

ACTION_CLASS_PATTERN = re.compile(
    r"(?:"
    r"\baction\s+class\b|"
    r"\btarget\s+price\b|"
    r"(?<![\w-])strong\s+buy(?![\w-])|"
    r"(?<![\w-])(?:buy|sell|hold|long|short|accumulate|reduce)(?![\w-])|"
    r"强烈买入|买入|卖出|持有|增持|减持|目标价"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ForbiddenOutputIssue:
    class_name: str
    issue_code: str
    message: str


@dataclass(frozen=True)
class ForbiddenOutputRule:
    class_name: str
    issue_code: str
    message: str
    pattern: re.Pattern[str]

    def evaluate(self, text: str) -> ForbiddenOutputIssue | None:
        if self.pattern.search(text):
            return ForbiddenOutputIssue(
                class_name=self.class_name,
                issue_code=self.issue_code,
                message=self.message,
            )
        return None


@dataclass(frozen=True)
class WorkerRole:
    slug: str
    display_label: str
    dispatch_aliases: tuple[str, ...]
    prompt_template: str
    modes: tuple[str, ...]
    delivery_folder: str
    required_method_cards: tuple[str, ...]
    allowed_method_cards: tuple[str, ...]
    requires_source_trace: bool
    required_output_markers: tuple[str, ...]
    forbidden_input_classes: tuple[str, ...]
    forbidden_output_classes: tuple[str, ...]
    forbidden_output_rules: tuple[ForbiddenOutputRule, ...] = ()
    source_trace_markers: tuple[str, ...] = SOURCE_TRACE_MARKERS

    def prompt_path(self, repo_root: str | Path) -> Path:
        return Path(repo_root) / self.prompt_template

    def method_card_paths(self, repo_root: str | Path) -> tuple[Path, ...]:
        root = Path(repo_root)
        return tuple(
            root / METHOD_CARDS_ROOT / card / "METHOD.md"
            for card in self.required_method_cards
        )

    def matches_delivery_path(self, relative_path: str | Path) -> bool:
        normalized = normalize_relative_path(relative_path)
        return normalized.startswith(f"{self.delivery_folder}/")


SCOUT_ACTION_RULE = ForbiddenOutputRule(
    class_name=ACTION_CLASS_LANGUAGE,
    issue_code="SCOUT_FORBIDDEN_CONCLUSION",
    message="Scout output must not contain action-class style conclusion language",
    pattern=ACTION_CLASS_PATTERN,
)

WORKER_ACTION_RULE = ForbiddenOutputRule(
    class_name=ACTION_CLASS_LANGUAGE,
    issue_code="WORKER_FORBIDDEN_CONCLUSION",
    message="Worker output must not contain action-class style conclusion language",
    pattern=ACTION_CLASS_PATTERN,
)

WORKER_ROLES = (
    WorkerRole(
        slug="frontier_scout",
        display_label="Frontier Scout",
        dispatch_aliases=("scout", "frontier scout", "frontier_scout", "scouts"),
        prompt_template="scripts/prompts/scout_prompt.md",
        modes=("ticker",),
        delivery_folder="scouts",
        required_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        allowed_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        requires_source_trace=True,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("thesis", "stock_price", "market_cap", "valuation", "prior_worker_output"),
        forbidden_output_classes=(ACTION_CLASS_LANGUAGE,),
        forbidden_output_rules=(SCOUT_ACTION_RULE,),
    ),
    WorkerRole(
        slug="challenge_probe",
        display_label="Challenge Probe",
        dispatch_aliases=("challenge", "challenge probe", "challenge_probe", "challenges"),
        prompt_template="scripts/prompts/challenge_prompt.md",
        modes=("ticker",),
        delivery_folder="challenges",
        required_method_cards=("red-team", "supply-chain-mapping", "customer-graph-discovery"),
        allowed_method_cards=("red-team", "supply-chain-mapping", "customer-graph-discovery"),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("full_thesis", "conversation_history", "bull_case"),
        forbidden_output_classes=(),
    ),
    WorkerRole(
        slug="sector_mapper",
        display_label="Sector Mapper",
        dispatch_aliases=("mapper", "sector mapper", "sector_mapper", "maps"),
        prompt_template="scripts/prompts/sector_mapper_prompt.md",
        modes=("sector",),
        delivery_folder="maps",
        required_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        allowed_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        requires_source_trace=True,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("thesis", "stock_price", "market_cap", "valuation", "investment_recommendation"),
        forbidden_output_classes=(ACTION_CLASS_LANGUAGE,),
        forbidden_output_rules=(WORKER_ACTION_RULE,),
    ),
    WorkerRole(
        slug="coverage_challenge",
        display_label="Coverage Challenge",
        dispatch_aliases=("coverage", "coverage challenge", "coverage_challenge"),
        prompt_template="scripts/prompts/coverage_challenge_prompt.md",
        modes=("sector",),
        delivery_folder="coverage",
        required_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        allowed_method_cards=("supply-chain-mapping", "customer-graph-discovery"),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("final_thesis", "investment_recommendation"),
        forbidden_output_classes=(),
    ),
    WorkerRole(
        slug="supply_chain_mapper",
        display_label="Supply Chain Mapper",
        dispatch_aliases=("supply chain", "supply chain mapper", "supply_chain_mapper"),
        prompt_template="scripts/prompts/supply_chain_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="maps",
        required_method_cards=("supply-chain-mapping",),
        allowed_method_cards=("supply-chain-mapping",),
        requires_source_trace=True,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("stock_price", "market_cap", "valuation", "investment_recommendation"),
        forbidden_output_classes=(),
    ),
    WorkerRole(
        slug="customer_graph_mapper",
        display_label="Customer Graph Mapper",
        dispatch_aliases=("customer graph", "customer graph mapper", "customer_graph_mapper"),
        prompt_template="scripts/prompts/customer_graph_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="maps",
        required_method_cards=("customer-graph-discovery",),
        allowed_method_cards=("customer-graph-discovery",),
        requires_source_trace=True,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("stock_price", "market_cap", "valuation", "investment_recommendation"),
        forbidden_output_classes=(),
    ),
    WorkerRole(
        slug="financial_bridge",
        display_label="Financial Bridge",
        dispatch_aliases=("financial", "financial bridge", "financial screen", "financial_bridge", "financials"),
        prompt_template="scripts/prompts/financial_bridge_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="financials",
        required_method_cards=("financial-bridge",),
        allowed_method_cards=("financial-bridge",),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("technical_thesis_judgment",),
        forbidden_output_classes=(),
    ),
    WorkerRole(
        slug="red_team",
        display_label="Red Team",
        dispatch_aliases=("redteam", "red team", "red_team", "redteam analyst", "thesis-revision", "thesis_revision"),
        prompt_template="scripts/prompts/red_team_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="redteam",
        required_method_cards=("red-team",),
        allowed_method_cards=("red-team",),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("conversation_history", "user_sentiment", "kol_endorsement"),
        forbidden_output_classes=(),
    ),
)


def all_worker_roles() -> tuple[WorkerRole, ...]:
    return WORKER_ROLES


def role_for_slug(slug: str) -> WorkerRole:
    normalized = _normalize_key(slug)
    for role in WORKER_ROLES:
        if role.slug == normalized:
            return role
    raise ValueError(f"Unknown SOFA worker role: {slug!r}")


def role_for_delivery_path(relative_path: str | Path) -> WorkerRole:
    normalized = normalize_relative_path(relative_path)
    folder = normalized.split("/", 1)[0]
    folder_defaults = {
        "scouts": "frontier_scout",
        "challenges": "challenge_probe",
        "maps": "sector_mapper",
        "coverage": "coverage_challenge",
        "financials": "financial_bridge",
        "redteam": "red_team",
    }
    try:
        return role_for_slug(folder_defaults[folder])
    except KeyError as exc:
        raise ValueError(f"No SOFA worker role matches delivery path: {relative_path!r}") from exc


def normalize_role_slug(role_alias: str | None, *, delivery_path: str | Path | None = None) -> str:
    if role_alias is None or str(role_alias).strip() == "":
        if delivery_path is None:
            raise ValueError("A worker role alias or delivery path is required")
        return role_for_delivery_path(delivery_path).slug

    normalized_alias = _normalize_key(role_alias)
    for role in WORKER_ROLES:
        aliases = {_normalize_key(alias) for alias in role.dispatch_aliases}
        aliases.add(role.slug)
        if normalized_alias in aliases:
            if delivery_path is not None and not role.matches_delivery_path(delivery_path):
                raise ValueError(
                    f"dispatch role {role_alias!r} does not match delivery path {delivery_path!r}"
                )
            return role.slug

    raise ValueError(f"Unknown SOFA worker role alias: {role_alias!r}")


def has_required_output_marker(text: str, marker: str) -> bool:
    return marker.lower() in text.lower()


def has_source_trace(text: str, role: WorkerRole) -> bool:
    if not role.requires_source_trace:
        return True
    return any(SOURCE_TRACE_LABEL_PATTERN.search(line.strip()) for line in text.splitlines())


def forbidden_output_violations(role: WorkerRole, text: str) -> list[ForbiddenOutputIssue]:
    issues: list[ForbiddenOutputIssue] = []
    for rule in role.forbidden_output_rules:
        issue = rule.evaluate(text)
        if issue is not None:
            issues.append(issue)
    return issues


def validate_catalog(repo_root: str | Path) -> list[str]:
    root = Path(repo_root)
    issues: list[str] = []
    slugs: set[str] = set()
    aliases: dict[str, str] = {}

    for role in WORKER_ROLES:
        if role.slug in slugs:
            issues.append(f"duplicate role slug: {role.slug}")
        slugs.add(role.slug)

        for mode in role.modes:
            if mode not in VALID_MODES:
                issues.append(f"{role.slug} has unsupported mode: {mode}")

        if not role.prompt_path(root).is_file():
            issues.append(f"{role.slug} prompt missing: {role.prompt_template}")

        for marker in role.required_output_markers:
            if not marker.strip():
                issues.append(f"{role.slug} has blank required output marker")

        for card_path in role.method_card_paths(root):
            if not card_path.is_file():
                issues.append(f"{role.slug} method card missing: {card_path.relative_to(root).as_posix()}")

        for alias in role.dispatch_aliases:
            normalized = _normalize_key(alias)
            existing = aliases.get(normalized)
            if existing is not None and existing != role.slug:
                issues.append(f"dispatch alias {alias!r} is used by both {existing} and {role.slug}")
            aliases[normalized] = role.slug

    return issues


def normalize_relative_path(relative_path: str | Path) -> str:
    raw_text = str(relative_path)
    raw_path = Path(raw_text)
    windows_path = PureWindowsPath(raw_text)
    if raw_path.is_absolute() or windows_path.drive or windows_path.root:
        raise ValueError(f"Expected workspace-relative path, got absolute path: {relative_path!r}")

    raw = raw_text.replace("\\", "/")
    normalized_parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not normalized_parts:
                raise ValueError(
                    "Expected workspace-relative path, "
                    f"got path outside workspace: {relative_path!r}"
                )
            normalized_parts.pop()
            continue
        normalized_parts.append(part)

    if not normalized_parts:
        return "."
    return "/".join(normalized_parts)


def _normalize_key(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")
