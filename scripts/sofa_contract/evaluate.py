from __future__ import annotations

import json
import re
from pathlib import Path

from workspace_contract import core_required_files
from capability_policy import RESULT_STATUS_COMPLETED, RESULT_STATUS_DEGRADED
from worker_role_catalog import (
    SOURCE_TRACE_MARKERS,
    all_worker_roles,
    forbidden_output_violations,
    has_required_output_marker,
    has_source_trace,
    normalize_role_slug,
    role_for_slug,
)

from .result import ContractProfile, ContractResult
from .workspace import (
    find_markdown_reports,
    find_worker_outputs,
    iter_jsonl_records,
    markdown_table_has_data_row,
    parse_stage_progress,
    read_json_file,
    read_text_file,
)


TICKER_REPORT_REQUIREMENTS = {
    "CONCLUSION": ("conclusion", "action class", "research status", "结论"),
    "CONFIDENCE": ("confidence", "置信"),
    "TIME_HORIZON": ("time horizon", "时间"),
    "SUPPORTING_EVIDENCE": ("top supporting evidence", "supporting evidence", "支持证据"),
    "COUNTER_EVIDENCE": ("strongest counter", "counter evidence", "反证"),
    "EVIDENCE_MAP": ("evidence map", "audit trail", "evidence_ledger", "证据"),
    "FINANCIAL_BRIDGE": ("financial bridge", "revenue bridge", "财务桥"),
    "CATALYST_CLOCK": ("catalyst clock", "catalyst", "催化"),
    "RED_TEAM": ("red-team", "red team", "红队"),
    "INVALIDATION": ("invalidation", "invalidated", "失效"),
    "WATCH_PROTOCOL": ("watch protocol", "观察协议"),
}
# Sector Hunt final reports follow a different template (see
# skills/sofa-analyze/references/sector-hunt-guide.md): architecture shift,
# layered dependency map, chokepoint scoring, ranked candidate queue, red-team
# summary, next steps, dive readiness. They are explicitly NOT action-class
# verdicts, so the ticker-only areas (confidence, time horizon, financial
# bridge, catalyst clock, watch protocol, ...) must not be required of them.
SECTOR_REPORT_REQUIREMENTS = {
    "SECTOR_HEADING": ("sector hunt report", "板块报告"),
    "ARCHITECTURE_SHIFT": ("architecture shift", "架构迁移"),
    "DEPENDENCY_MAP": ("layered dependency map", "dependency ladder", "依赖图谱", "依赖"),
    "CHOKEPOINT_SCORING": ("chokepoint scoring", "扼点评分"),
    "RANKED_CANDIDATE": ("ranked candidate", "排序候选"),
    "RED_TEAM_SUMMARY": ("red team summary", "red-team summary", "红队"),
    "NEXT_STEPS": ("recommended next steps", "next steps", "下一步"),
    "DIVE_READINESS": ("dive readiness", "潜水就绪"),
}
DISPATCH_DELIVERY_REQUIRED_FIELDS = ("dispatch_id", "loop_id", "role", "mechanism", "delivery_path", "status")
SUPPORTED_DISPATCH_MECHANISMS = ("host_subagent", "native_subagent", "degraded_single_agent")
SUBAGENT_DISPATCH_MECHANISMS = ("host_subagent", "native_subagent")
SECTOR_FORBIDDEN_ACTION_PATTERN = re.compile(
    r"(?:"
    r"\baction\s+class\b|"
    r"\btarget\s+price\b|"
    r"(?<![\w-])(?:buy|sell|hold|long|short|accumulate|reduce)(?![\w-])|"
    r"强烈买入|买入|卖出|持有|增持|减持|目标价"
    r")",
    re.IGNORECASE,
)
CORE_WORKSPACE_FILE_FAILURES = {
    "state.json": (
        "STATE_JSON_MISSING",
        "state.json is required as the machine-readable workspace authority",
    ),
    "research_workflow.md": (
        "RESEARCH_WORKFLOW_MISSING",
        "research_workflow.md is required as the human-readable workflow mirror",
    ),
    "evidence_ledger.md": (
        "EVIDENCE_LEDGER_MISSING",
        "evidence_ledger.md is required for evidence-first research",
    ),
}


def evaluate_workspace(workspace_path: Path | str, profile: ContractProfile) -> ContractResult:
    workspace = Path(workspace_path)
    result = ContractResult()
    state = _check_core_workspace_files(workspace, result)
    workflow_text = read_text_file(workspace / "research_workflow.md")
    _check_state_workflow_consistency(workspace, state, workflow_text, result)
    _check_search_log(workspace, state, result)
    _check_dispatch_log(workspace, workflow_text, profile, result)
    _check_worker_outputs(workspace, profile, result)
    if _requires_final_report(profile):
        _check_final_report(workspace, profile, result)
    return result


def _requires_final_report(profile: ContractProfile) -> bool:
    if profile.target in {"final_report", "dossier"}:
        return True
    return (
        profile.target == "stage_transition"
        and profile.from_stage == "stage_5"
        and profile.to_stage == "stage_6"
    )


def _check_core_workspace_files(workspace: Path, result: ContractResult) -> dict | None:
    state = read_json_file(workspace / "state.json")
    for relative_path in core_required_files():
        missing = state is None if relative_path == "state.json" else not (workspace / relative_path).exists()
        if not missing:
            continue
        code, message = CORE_WORKSPACE_FILE_FAILURES[relative_path]
        result.fail(code=code, message=message, path=relative_path)
    return state


def _check_state_workflow_consistency(
    workspace: Path,
    state: dict | None,
    workflow_text: str | None,
    result: ContractResult,
) -> None:
    if state is None or workflow_text is None:
        return
    statuses = parse_stage_progress(workflow_text)
    completed = set(state.get("stages_completed", []))
    for stage in sorted(completed):
        status = statuses.get(stage)
        if status in {"pending", "in_progress"}:
            result.fail(
                code="STATE_WORKFLOW_STAGE_CONFLICT",
                message=f"{stage} is completed in state.json but {status} in research_workflow.md",
                path="research_workflow.md",
                evidence=f"state.json stages_completed includes {stage}",
            )
    current_stage = state.get("current_stage")
    if current_stage == "stage_6" and statuses.get("stage_5") in {"pending", "in_progress"}:
        result.fail(
            code="STATE_WORKFLOW_STAGE_CONFLICT",
            message="state.json current_stage is stage_6 but workflow Stage 5 is not complete",
            path="research_workflow.md",
            evidence="current_stage=stage_6",
        )


def _workspace_claims_completed_loops(state: dict | None) -> bool:
    if state is None:
        return False
    if state.get("loop_count", 0) > 0:
        return True
    completed = set(state.get("stages_completed", []))
    return bool({"stage_2", "stage_3", "stage_4", "stage_5"} & completed)


def _valid_search_coverage(workspace: Path) -> tuple[set[str], bool]:
    """Return (loop_ids with a valid search record, has_any_valid_record).

    A single valid record used to satisfy the whole workspace; now we collect
    per-loop coverage so a workspace with loop_count=3 and only a loop_1 record
    is rejected (SEARCH_LOG_LOOP_COVERAGE_MISSING).
    """
    loop_ids: set[str] = set()
    has_any_valid = False
    if not (workspace / "search_log.jsonl").exists():
        return loop_ids, has_any_valid
    try:
        for _line_number, record in iter_jsonl_records(workspace / "search_log.jsonl"):
            status = str(record.get("result_status", "")).strip().lower()
            valid = (
                status == RESULT_STATUS_COMPLETED
                and _has_completed_search_record_shape(record)
            ) or (
                status == RESULT_STATUS_DEGRADED
                and _has_degraded_search_record_shape(record)
            )
            if valid:
                has_any_valid = True
                loop_id = record.get("loop_id")
                if loop_id:
                    loop_ids.add(str(loop_id))
    except (json.JSONDecodeError, ValueError):
        return set(), False
    return loop_ids, has_any_valid


def _has_completed_search_record_shape(record: dict) -> bool:
    has_binding = bool(record.get("loop_id") or record.get("dispatch_id"))
    has_trace = bool(record.get("query") or record.get("evidence_refs"))
    return has_binding and has_trace


def _has_degraded_search_record_shape(record: dict) -> bool:
    has_reason = bool(record.get("degraded_reason"))
    has_trace = bool(record.get("evidence_refs") or record.get("gaps"))
    return has_reason and has_trace


def _check_search_log(workspace: Path, state: dict | None, result: ContractResult) -> None:
    if not _workspace_claims_completed_loops(state):
        return
    covered_loop_ids, has_any_valid = _valid_search_coverage(workspace)
    if has_any_valid:
        # At least one valid search_log.jsonl record exists. Now confirm that
        # EVERY claimed loop (loop_count) is covered. A workspace with
        # loop_count=3 but only a loop_1 search record must still be rejected.
        loop_count = 0
        if isinstance(state, dict):
            try:
                loop_count = int(state.get("loop_count", 0) or 0)
            except (TypeError, ValueError):
                loop_count = 0
        expected_loop_ids = {f"loop_{i}" for i in range(1, loop_count + 1)}
        missing_loop_ids = sorted(expected_loop_ids - covered_loop_ids)
        if missing_loop_ids:
            result.fail(
                code="SEARCH_LOG_LOOP_COVERAGE_MISSING",
                message=(
                    "each completed loop requires its own valid search_log.jsonl record; "
                    f"loops without a valid search record: {', '.join(missing_loop_ids)}"
                ),
                path="search_log.jsonl",
                evidence=(
                    f"covered loops: {sorted(covered_loop_ids) or 'none'}; "
                    f"missing loops: {missing_loop_ids}"
                ),
            )
        return
    legacy_text = read_text_file(workspace / "search_log.md")
    if markdown_table_has_data_row(legacy_text):
        result.warn(
            code="LEGACY_SEARCH_LOG_USED",
            message="legacy search_log.md is present; search_log.jsonl is required as the machine authority",
            path="search_log.md",
            evidence="Markdown table contains at least one data row",
        )
    result.fail(
        code="SEARCH_LOG_MISSING",
        message="completed loops require valid search_log.jsonl records",
        path="search_log.jsonl",
        evidence="no valid search record found",
    )


def _read_dispatch_records(workspace: Path, result: ContractResult) -> list[dict] | None:
    try:
        return [record for _line_number, record in iter_jsonl_records(workspace / "dispatch_log.jsonl")]
    except (json.JSONDecodeError, ValueError) as exc:
        result.fail(
            code="DISPATCH_LOG_INVALID",
            message="dispatch_log.jsonl must be valid JSONL with one object per non-blank line",
            path="dispatch_log.jsonl",
            evidence=str(exc),
        )
        return None


def _check_dispatch_log(
    workspace: Path,
    workflow_text: str | None,
    profile: ContractProfile,
    result: ContractResult,
) -> None:
    worker_outputs = find_worker_outputs(workspace)
    workflow_claims_delivery = _workflow_claims_subagent_delivery(workflow_text)
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        if not worker_outputs and not workflow_claims_delivery:
            return
        result.fail(
            code="DISPATCH_PROOF_MISSING" if workflow_claims_delivery else "DISPATCH_LOG_MISSING",
            message="worker outputs and workflow dispatch claims require dispatch_log.jsonl or approved degraded-mode records",
            path="dispatch_log.jsonl",
            evidence=_dispatch_missing_evidence(worker_outputs, workflow_claims_delivery),
        )
        return
    records = _read_dispatch_records(workspace, result)
    if records is None:
        return
    if workflow_claims_delivery and not any(_dispatch_record_counts_as_delivery(record) for record in records):
        result.fail(
            code="DISPATCH_PROOF_MISSING",
            message="workflow Subagent Dispatch Log claims delivered subagent work without machine delivery proof",
            path="dispatch_log.jsonl",
            evidence="no delivered host/native subagent record or approved degraded delivery record",
        )
    for duplicate_path, dispatch_ids in _duplicate_delivered_paths(workspace, records).items():
        result.fail(
            code="DISPATCH_DELIVERY_PATH_DUPLICATE",
            message="delivered dispatch records must not reuse the same delivery_path",
            path="dispatch_log.jsonl",
            evidence=f"{duplicate_path}: {', '.join(dispatch_ids)}",
        )
    for record in records:
        mechanism = str(record.get("mechanism", "")).lower()
        label = str(record.get("label", "")).lower()
        if record.get("status") == "delivered":
            missing_fields = _missing_dispatch_delivery_fields(record)
            if missing_fields:
                result.fail(
                    code="DISPATCH_RECORD_INCOMPLETE",
                    message="delivered dispatch records require dispatch_id, loop_id, role, mechanism, delivery_path, and status",
                    path="dispatch_log.jsonl",
                    evidence=", ".join(missing_fields),
                )
            else:
                normalized_delivery_path = _normalize_delivery_path(workspace, record.get("delivery_path", ""))
                if normalized_delivery_path is None or not (workspace / normalized_delivery_path).is_file():
                    result.fail(
                        code="DISPATCH_DELIVERY_MISSING",
                        message="delivered dispatch record points to a missing delivery_path",
                        path="dispatch_log.jsonl",
                        evidence=str(record.get("delivery_path")),
                    )
                elif mechanism not in SUPPORTED_DISPATCH_MECHANISMS:
                    result.fail(
                        code="DISPATCH_MECHANISM_UNSUPPORTED",
                        message="delivered dispatch record uses an unsupported mechanism",
                        path="dispatch_log.jsonl",
                        evidence=mechanism,
                    )
                else:
                    role_issue = _dispatch_role_delivery_issue(record, normalized_delivery_path, profile.mode)
                    if role_issue is not None:
                        code, message, evidence = role_issue
                        result.fail(
                            code=code,
                            message=message,
                            path="dispatch_log.jsonl",
                            evidence=evidence,
                        )
        if mechanism == "degraded_single_agent" and record.get("degraded_mode_approved") is not True:
            result.fail(
                code="DEGRADED_MODE_NOT_APPROVED",
                message="degraded single-agent delivery requires explicit approval",
                path="dispatch_log.jsonl",
                evidence=str(record.get("dispatch_id", "")),
            )
        if mechanism == "degraded_single_agent" and "subagent" in label:
            result.fail(
                code="DEGRADED_MODE_MISLABELED",
                message="degraded single-agent work must not be labeled as subagent dispatch",
                path="dispatch_log.jsonl",
                evidence=str(record.get("dispatch_id", "")),
            )
    delivered_paths = {
        normalized_path
        for record in records
        if _dispatch_record_counts_as_delivery(record)
        for normalized_path in [_normalize_delivery_path(workspace, record.get("delivery_path", ""))]
        if normalized_path is not None
    }
    for output in worker_outputs:
        rel = output.relative_to(workspace).as_posix()
        if rel not in delivered_paths:
            result.fail(
                code="WORKER_OUTPUT_WITHOUT_DISPATCH",
                message="worker output has no delivered dispatch record",
                path=rel,
                evidence="dispatch_log.jsonl delivery_path mismatch",
            )


def _normalize_delivery_path(workspace: Path, delivery_path) -> str | None:
    """Normalize a dispatch delivery_path to a workspace-relative posix string.

    Guides pass workers the same absolute ``{WORKSPACE}/...`` path they write
    to, so dispatch_log.jsonl often records absolute paths. Worker outputs are
    compared as workspace-relative paths. Relative paths may also include
    harmless ``./`` or ``..`` segments. Paths that escape the workspace are not
    accepted as delivered outputs.
    """
    raw = str(delivery_path)
    try:
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (workspace / candidate).resolve()
        return resolved.relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _dispatch_role_delivery_issue(
    record: dict,
    normalized_delivery_path: str,
    profile_mode: str,
) -> tuple[str, str, str] | None:
    try:
        role_slug = normalize_role_slug(record.get("role"), delivery_path=normalized_delivery_path)
        role = role_for_slug(role_slug)
    except ValueError as exc:
        return (
            "DISPATCH_ROLE_DELIVERY_MISMATCH",
            "delivered dispatch record role must match its delivery_path",
            str(exc),
        )
    if profile_mode not in role.modes:
        return (
            "DISPATCH_ROLE_MODE_MISMATCH",
            "delivered dispatch record role is not allowed for this workspace mode",
            f"{role.slug} supports modes: {', '.join(role.modes)}; workspace mode: {profile_mode}",
        )
    return None


def _duplicate_delivered_paths(workspace: Path, records: list[dict]) -> dict[str, list[str]]:
    dispatch_ids_by_path: dict[str, list[str]] = {}
    for record in records:
        if record.get("status") != "delivered":
            continue
        if not record.get("delivery_path"):
            continue
        normalized_path = _normalize_delivery_path(workspace, record.get("delivery_path", ""))
        if normalized_path is None:
            continue
        dispatch_ids_by_path.setdefault(normalized_path, []).append(str(record.get("dispatch_id", "")))
    return {
        path: dispatch_ids
        for path, dispatch_ids in dispatch_ids_by_path.items()
        if len(dispatch_ids) > 1
    }


def _delivered_roles_by_path(workspace: Path, profile_mode: str) -> dict[str, str]:
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        return {}
    try:
        records = [record for _line_number, record in iter_jsonl_records(dispatch_path)]
    except (json.JSONDecodeError, ValueError):
        return {}

    roles_by_path: dict[str, str] = {}
    seen_paths: set[str] = set()
    for record in records:
        if not _dispatch_record_counts_as_delivery(record):
            continue
        normalized_path = _normalize_delivery_path(workspace, record.get("delivery_path", ""))
        if normalized_path is None:
            continue
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        try:
            role_slug = normalize_role_slug(
                record.get("role"),
                delivery_path=normalized_path,
            )
            role = role_for_slug(role_slug)
        except ValueError:
            continue
        if profile_mode not in role.modes:
            continue
        roles_by_path[normalized_path] = role.slug
    return roles_by_path


def _dispatch_missing_evidence(worker_outputs: list[Path], workflow_claims_delivery: bool) -> str:
    evidence = []
    if worker_outputs:
        evidence.append(f"{len(worker_outputs)} worker output file(s)")
    if workflow_claims_delivery:
        evidence.append("research_workflow.md Subagent Dispatch Log delivered row")
    return "; ".join(evidence)


def _workflow_claims_subagent_delivery(workflow_text: str | None) -> bool:
    section = _markdown_section(workflow_text, "Subagent Dispatch Log")
    if not section:
        return False
    after_separator = False
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            after_separator = False
            continue
        cells = [cell.strip().lower() for cell in stripped.strip("|").split("|")]
        if _is_markdown_table_separator(cells):
            after_separator = True
            continue
        if not after_separator:
            continue
        if any(cell == "delivered" for cell in cells):
            return True
    return False


def _markdown_section(markdown_text: str | None, heading: str) -> str | None:
    if not markdown_text:
        return None
    heading_level: int | None = None
    section_lines: list[str] = []
    for line in markdown_text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip().lower()
            if heading_level is not None and level <= heading_level:
                break
            if heading_level is None and title == heading.lower():
                heading_level = level
                continue
        if heading_level is not None:
            section_lines.append(line)
    if heading_level is None:
        return None
    return "\n".join(section_lines)


def _is_markdown_table_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":"} and "-" in cell for cell in cells)


def _dispatch_record_counts_as_delivery(record: dict) -> bool:
    if record.get("status") != "delivered":
        return False
    if _missing_dispatch_delivery_fields(record):
        return False
    mechanism = str(record.get("mechanism", "")).lower()
    if mechanism in SUBAGENT_DISPATCH_MECHANISMS:
        return True
    if mechanism == "degraded_single_agent":
        return record.get("degraded_mode_approved") is True
    return False


def _missing_dispatch_delivery_fields(record: dict) -> list[str]:
    return [field for field in DISPATCH_DELIVERY_REQUIRED_FIELDS if not record.get(field)]


def _check_worker_outputs(workspace: Path, profile: ContractProfile, result: ContractResult) -> None:
    delivered_roles = _delivered_roles_by_path(workspace, profile.mode)
    for path in find_worker_outputs(workspace):
        rel = path.relative_to(workspace).as_posix()
        text = path.read_text(encoding="utf-8")
        candidate_roles = _candidate_worker_roles_for_output(rel)
        role = _worker_role_for_output(rel, delivered_roles, candidate_roles)

        if not any(
            has_required_output_marker(text, marker)
            for marker in _required_output_markers_for_output(role, candidate_roles)
        ):
            result.fail(
                code="WORKER_METHOD_CARDS_MISSING",
                message="worker output must declare Method cards loaded",
                path=rel,
            )
        has_trace = has_source_trace(text, candidate_roles[0])
        if not has_trace:
            if _requires_source_trace(role, candidate_roles):
                result.fail(
                    code="WORKER_SOURCE_TRACE_MISSING",
                    message="search worker output must include a source or search trace section",
                    path=rel,
                    evidence=", ".join(SOURCE_TRACE_MARKERS),
                )
            elif role is not None:
                result.warn(
                    code="WORKER_SOURCE_TRACE_RECOMMENDED",
                    message="worker output is missing a source or search trace section (recommended for analysis roles)",
                    path=rel,
                    evidence=", ".join(SOURCE_TRACE_MARKERS),
                )

        if role is not None:
            for issue in forbidden_output_violations(role, text):
                result.fail(
                    code=issue.issue_code,
                    message=issue.message,
                    path=rel,
                )


def _candidate_worker_roles_for_output(rel: str):
    return tuple(role for role in all_worker_roles() if role.matches_delivery_path(rel))


def _required_output_markers_for_output(role, candidate_roles) -> tuple[str, ...]:
    if role is not None:
        return role.required_output_markers
    if not candidate_roles:
        return ()
    shared_markers = set(candidate_roles[0].required_output_markers)
    for candidate_role in candidate_roles[1:]:
        shared_markers &= set(candidate_role.required_output_markers)
    return tuple(marker for marker in candidate_roles[0].required_output_markers if marker in shared_markers)


def _requires_source_trace(role, candidate_roles) -> bool:
    if role is not None:
        return role.requires_source_trace
    return bool(candidate_roles) and all(candidate_role.requires_source_trace for candidate_role in candidate_roles)


def _worker_role_for_output(rel: str, delivered_roles: dict[str, str], candidate_roles):
    role_slug = delivered_roles.get(rel)
    if role_slug is not None:
        try:
            return role_for_slug(normalize_role_slug(role_slug, delivery_path=rel))
        except ValueError:
            return None
    if len(candidate_roles) == 1:
        return candidate_roles[0]
    return None


def _check_final_report(workspace: Path, profile: ContractProfile, result: ContractResult) -> None:
    reports = find_markdown_reports(workspace)
    if not reports:
        result.fail(
            code="FINAL_REPORT_MISSING",
            message="reports/ must contain a Markdown final report artifact",
            path="reports/",
        )
        return
    report_texts = [(path, path.read_text(encoding="utf-8").lower()) for path in reports]
    if profile.mode == "sector":
        for report_path, report_text in report_texts:
            if _contains_sector_action_language(report_text):
                result.fail(
                    code="SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE",
                    message="Sector Hunt output must not contain action-class style conclusions",
                    path=report_path.relative_to(workspace).as_posix(),
                    evidence="found buy/sell/hold/target-price/action-class language",
                )
    complete_reports = [
        (path, text)
        for path, text in report_texts
        if not _missing_final_report_requirements(text, profile)
    ]
    if complete_reports:
        return
    best_path, best_text = min(
        report_texts, key=lambda item: len(_missing_final_report_requirements(item[1], profile))
    )
    requirements = _report_requirements_for(profile)
    for label in _missing_final_report_requirements(best_text, profile):
        markers = requirements[label]
        result.fail(
            code=f"FINAL_REPORT_MISSING_{label}",
            message=f"final report is missing required area: {label.lower().replace('_', ' ')}",
            path=best_path.relative_to(workspace).as_posix(),
            evidence=", ".join(markers),
        )


def _report_requirements_for(profile: ContractProfile) -> dict:
    if profile.mode == "sector":
        return SECTOR_REPORT_REQUIREMENTS
    return TICKER_REPORT_REQUIREMENTS


def _missing_final_report_requirements(report_text: str, profile: ContractProfile) -> list[str]:
    missing = []
    for label, markers in _report_requirements_for(profile).items():
        if not any(marker.lower() in report_text for marker in markers):
            missing.append(label)
    return missing


def _contains_sector_action_language(text: str) -> bool:
    return SECTOR_FORBIDDEN_ACTION_PATTERN.search(text) is not None
