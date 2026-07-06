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

ENGLISH_ACTION_TERMS = r"(?:strong\s+buy|buy|sell|hold|long|short|accumulate|reduce)"
CHINESE_ACTION_TERMS = r"(?:强烈买入|买入|卖出|持有|增持|减持)"
ACTION_CLASS_PATTERN = re.compile(
    rf"(?:"
    rf"\baction\s+class\b|"
    rf"\btarget\s+price\b|"
    rf"\b(?:recommendation|rating|conclusion)\b\s*(?::|：|-)\s*{ENGLISH_ACTION_TERMS}(?![\w-])|"
    rf"(?<![\w-]){ENGLISH_ACTION_TERMS}(?![\w-])\s+(?:rating|recommendation)|"
    rf"(?<![\w-])strong\s+buy(?![\w-])|"
    rf"(?:投资建议|操作建议|评级|结论)\s*(?::|：|-)?\s*{CHINESE_ACTION_TERMS}|"
    rf"建议\s*{CHINESE_ACTION_TERMS}|"
    rf"{CHINESE_ACTION_TERMS}\s*(?:评级|建议)|"
    rf"目标价"
    rf")",
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
class ForbiddenInputIssue:
    class_name: str
    issue_code: str
    message: str


@dataclass(frozen=True)
class ForbiddenInputRule:
    class_name: str
    issue_code: str
    message: str
    pattern: re.Pattern[str]

    def evaluate(self, text: str) -> ForbiddenInputIssue | None:
        if self.pattern.search(text):
            return ForbiddenInputIssue(
                class_name=self.class_name,
                issue_code=self.issue_code,
                message=self.message,
            )
        return None


@dataclass(frozen=True)
class DispatchSlot:
    name: str
    style: str  # "replace" or "append"
    literal: str = ""
    heading: str = ""
    required: bool = True


FILENAME_FIELD_VOCABULARY = {"loop", "frontier_slug", "round", "ticker", "version"}
FILENAME_FIELD_PATTERN = re.compile(r"\{([a-z_]+)\}")

MARKET_DATA_PATTERN = re.compile(
    r"(?:\btarget\s+price\b|\bmarket\s+cap(?:italization)?\b|\bP/E\b|\bPE\s+ratio\b"
    r"|\bstock\s+prices?\b|\bshare\s+prices?\b"
    r"|市值|股价|目标价|市盈率)",
    re.IGNORECASE,
)

ACTION_INPUT_RULE = ForbiddenInputRule(
    class_name="action_class_language",
    issue_code="DISPATCH_INPUT_ACTION_LANGUAGE",
    message="dispatch input must not contain action-class or conclusion language for this role",
    pattern=ACTION_CLASS_PATTERN,
)

MARKET_DATA_INPUT_RULE = ForbiddenInputRule(
    class_name="market_data",
    issue_code="DISPATCH_INPUT_MARKET_DATA",
    message="dispatch input must not contain price, market-cap, or valuation data for this role",
    pattern=MARKET_DATA_PATTERN,
)


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
    dispatch_slots: tuple[DispatchSlot, ...] = ()
    delivery_filename_template: str = ""
    forbidden_input_rules: tuple[ForbiddenInputRule, ...] = ()

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
        return normalized == self.delivery_folder or normalized.startswith(f"{self.delivery_folder}/")


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
        dispatch_slots=(
            DispatchSlot(name="frontier_packet", style="replace", literal="[主线程粘贴完整 Frontier Packet]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/scouts/loop1_customer_relationship.md]"),
        ),
        delivery_filename_template="loop{loop}_{frontier_slug}.md",
        forbidden_input_rules=(ACTION_INPUT_RULE, MARKET_DATA_INPUT_RULE),
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
        dispatch_slots=(
            DispatchSlot(name="claim_summary", style="replace", literal="[主线程粘贴：只包含本轮 frontier 的 claim 摘要 + 支撑证据列表 + 证据等级]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/challenges/loop1_challenge.md]"),
        ),
        delivery_filename_template="loop{loop}_challenge.md",
        forbidden_input_rules=(ACTION_INPUT_RULE,),
    ),
    WorkerRole(
        slug="sector_mapper",
        display_label="Sector Mapper",
        dispatch_aliases=("mapper", "sector mapper", "sector_mapper"),
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
        dispatch_slots=(
            DispatchSlot(name="mapping_packet", style="replace", literal="[主线程粘贴：当前已知的 dependency ladder 摘要 + 需要扩展的具体层级/方向 + 目标深度]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/maps/mapping_loop1_layer2_3.md]"),
        ),
        delivery_filename_template="mapping_loop{loop}_{frontier_slug}.md",
        forbidden_input_rules=(ACTION_INPUT_RULE, MARKET_DATA_INPUT_RULE),
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
        dispatch_slots=(
            DispatchSlot(name="coverage_packet", style="replace", literal="[主线程粘贴：当前 dependency ladder 摘要 + 已完成的 mapping loop 数量 + 已发现的节点列表]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/coverage/coverage_loop1.md]"),
        ),
        delivery_filename_template="coverage_loop{loop}.md",
        forbidden_input_rules=(ACTION_INPUT_RULE,),
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
        dispatch_slots=(
            DispatchSlot(name="ladder_packet", style="replace", literal="[主线程粘贴：当前已知的 dependency ladder + 需要扩展的层级/方向]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/maps/supply_chain_v1.md]"),
        ),
        delivery_filename_template="supply_chain_v{version}.md",
        forbidden_input_rules=(ACTION_INPUT_RULE, MARKET_DATA_INPUT_RULE),
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
        dispatch_slots=(
            DispatchSlot(name="customer_packet", style="replace", literal="[主线程粘贴：目标公司 + 当前已知客户 + 需要验证的候选客户]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/maps/customer_graph_v1.md]"),
        ),
        delivery_filename_template="customer_graph_v{version}.md",
        forbidden_input_rules=(ACTION_INPUT_RULE, MARKET_DATA_INPUT_RULE),
    ),
    WorkerRole(
        slug="financial_bridge",
        display_label="Financial Bridge",
        dispatch_aliases=(
            "financial",
            "financial bridge",
            "financial bridge analyst",
            "financial screen",
            "financial_bridge",
            "financials",
        ),
        prompt_template="scripts/prompts/financial_bridge_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="financials",
        required_method_cards=("financial-bridge",),
        allowed_method_cards=("financial-bridge",),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("technical_thesis_judgment",),
        forbidden_output_classes=(),
        dispatch_slots=(
            DispatchSlot(name="bridge_input", style="replace", literal="[主线程粘贴：公司名 + ticker + thesis 摘要 + 需要验证的财务传导路径 + 当前已知的财务数据（如有）]"),
            DispatchSlot(name="delivery_path", style="replace", literal="[主线程指定，如：完成后用 Write 工具将完整输出写入 {WORKSPACE}/financials/TICKER_bridge.md]"),
        ),
        delivery_filename_template="{ticker}_bridge.md",
    ),
    WorkerRole(
        slug="red_team",
        display_label="Red Team",
        dispatch_aliases=(
            "redteam",
            "red team",
            "red team analyst",
            "red_team",
            "redteam analyst",
            "thesis-revision",
            "thesis_revision",
        ),
        prompt_template="scripts/prompts/red_team_prompt.md",
        modes=("ticker", "sector", "ultra"),
        delivery_folder="redteam",
        required_method_cards=("red-team",),
        allowed_method_cards=("red-team",),
        requires_source_trace=False,
        required_output_markers=("Method cards loaded",),
        forbidden_input_classes=("conversation_history", "user_sentiment", "kol_endorsement"),
        forbidden_output_classes=(),
        dispatch_slots=(
            DispatchSlot(name="round_input", style="append", heading="## 本轮输入（主线程提供）"),
            DispatchSlot(name="delivery_path", style="append", heading="## 交付文件路径"),
        ),
        delivery_filename_template="round{round}_redteam.md",
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
    matches = tuple(role for role in WORKER_ROLES if role.matches_delivery_path(normalized))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        role_list = ", ".join(role.slug for role in matches)
        raise ValueError(
            f"ambiguous SOFA worker role for delivery path {relative_path!r}; "
            f"no unambiguous role matches among: {role_list}"
        )
    raise ValueError(f"No SOFA worker role matches delivery path: {relative_path!r}")


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
    return any(SOURCE_TRACE_LABEL_PATTERN.search(line.strip()) for line in text.splitlines())


def forbidden_output_violations(role: WorkerRole, text: str) -> list[ForbiddenOutputIssue]:
    issues: list[ForbiddenOutputIssue] = []
    for rule in role.forbidden_output_rules:
        issue = rule.evaluate(text)
        if issue is not None:
            issues.append(issue)
    return issues


def forbidden_input_violations(role: WorkerRole, text: str) -> list[ForbiddenInputIssue]:
    issues: list[ForbiddenInputIssue] = []
    for rule in role.forbidden_input_rules:
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

        slot_names = [slot.name for slot in role.dispatch_slots]
        if len(slot_names) != len(set(slot_names)):
            issues.append(f"{role.slug} has duplicate dispatch slot names")
        if slot_names.count("delivery_path") != 1:
            issues.append(f"{role.slug} must declare exactly one delivery_path slot")

        template_body = ""
        template_declarations = ""
        if role.prompt_path(root).is_file():
            template_text = role.prompt_path(root).read_text(encoding="utf-8")
            template_parts = template_text.split("\n## Placeholders", 1)
            template_body = template_parts[0]
            template_declarations = template_parts[1] if len(template_parts) > 1 else ""

        for slot in role.dispatch_slots:
            if slot.style == "replace":
                if not slot.literal:
                    issues.append(f"{role.slug} slot {slot.name} is replace-style but has no literal")
                elif template_body.count(slot.literal) != 1:
                    issues.append(
                        f"{role.slug} slot {slot.name} literal must appear exactly once in the template body"
                    )
                elif slot.literal not in template_declarations:
                    issues.append(
                        f"{role.slug} slot {slot.name} literal is not declared in the template Placeholders section"
                    )
            elif slot.style == "append":
                if not slot.heading:
                    issues.append(f"{role.slug} slot {slot.name} is append-style but has no heading")
            else:
                issues.append(f"{role.slug} slot {slot.name} has unknown style: {slot.style}")

        if not role.delivery_filename_template:
            issues.append(f"{role.slug} has no delivery filename template")
        else:
            unknown_fields = (
                set(FILENAME_FIELD_PATTERN.findall(role.delivery_filename_template))
                - FILENAME_FIELD_VOCABULARY
            )
            if unknown_fields:
                issues.append(
                    f"{role.slug} filename template uses unknown fields: {sorted(unknown_fields)}"
                )

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
