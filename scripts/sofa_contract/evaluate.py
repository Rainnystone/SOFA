from __future__ import annotations

import re
from pathlib import Path

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


REPORT_REQUIREMENTS = {
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
DISPATCH_DELIVERY_REQUIRED_FIELDS = ("dispatch_id", "loop_id", "role", "mechanism", "delivery_path", "status")
SUPPORTED_DISPATCH_MECHANISMS = ("host_subagent", "native_subagent", "degraded_single_agent")
SUBAGENT_DISPATCH_MECHANISMS = ("host_subagent", "native_subagent")
SOURCE_TRACE_MARKERS = (
    "Search Exhaustion Report",
    "Sources consulted",
    "Source Pack",
    "Evidence Sources",
    "检索",
    "来源",
)
SCOUT_FORBIDDEN_TERMS = (
    "Action Class",
    "BUY",
    "SELL",
    "Strong Buy",
    "强烈买入",
    "卖出",
)


def evaluate_workspace(workspace_path: Path | str, profile: ContractProfile) -> ContractResult:
    workspace = Path(workspace_path)
    result = ContractResult()
    state = _check_core_workspace_files(workspace, result)
    workflow_text = read_text_file(workspace / "research_workflow.md")
    _check_state_workflow_consistency(workspace, state, workflow_text, result)
    _check_search_log(workspace, state, result)
    _check_dispatch_log(workspace, result)
    _check_worker_outputs(workspace, result)
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
    if state is None:
        result.fail(
            code="STATE_JSON_MISSING",
            message="state.json is required as the machine-readable workspace authority",
            path="state.json",
        )
    if not (workspace / "research_workflow.md").exists():
        result.fail(
            code="RESEARCH_WORKFLOW_MISSING",
            message="research_workflow.md is required as the human-readable workflow mirror",
            path="research_workflow.md",
        )
    if not (workspace / "evidence_ledger.md").exists():
        result.fail(
            code="EVIDENCE_LEDGER_MISSING",
            message="evidence_ledger.md is required for evidence-first research",
            path="evidence_ledger.md",
        )
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


def _has_valid_search_record(workspace: Path) -> bool:
    import json

    has_valid_record = False
    try:
        for _line_number, record in iter_jsonl_records(workspace / "search_log.jsonl"):
            status = str(record.get("result_status", "")).strip().lower()
            if status == "completed" and _has_completed_search_record_shape(record):
                has_valid_record = True
            if status == "degraded_approved" and _has_degraded_search_record_shape(record):
                has_valid_record = True
    except (json.JSONDecodeError, ValueError):
        return False
    return has_valid_record


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
    search_jsonl = workspace / "search_log.jsonl"
    if search_jsonl.exists() and _has_valid_search_record(workspace):
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


def _read_dispatch_records(workspace: Path) -> list[dict]:
    return [record for _line_number, record in iter_jsonl_records(workspace / "dispatch_log.jsonl")]


def _check_dispatch_log(workspace: Path, result: ContractResult) -> None:
    worker_outputs = find_worker_outputs(workspace)
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        if not worker_outputs:
            return
        result.fail(
            code="DISPATCH_LOG_MISSING",
            message="worker outputs require dispatch_log.jsonl or approved degraded-mode records",
            path="dispatch_log.jsonl",
            evidence=f"{len(worker_outputs)} worker output file(s)",
        )
        return
    records = _read_dispatch_records(workspace)
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
            elif not (workspace / str(record.get("delivery_path"))).is_file():
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
        str(record.get("delivery_path", ""))
        for record in records
        if _dispatch_record_counts_as_delivery(record)
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


def _check_worker_outputs(workspace: Path, result: ContractResult) -> None:
    for path in find_worker_outputs(workspace):
        rel = path.relative_to(workspace).as_posix()
        text = path.read_text(encoding="utf-8")
        if "Method cards loaded" not in text and "Method Cards Loaded" not in text:
            result.fail(
                code="WORKER_METHOD_CARDS_MISSING",
                message="worker output must declare Method cards loaded",
                path=rel,
            )
        if not any(marker in text for marker in SOURCE_TRACE_MARKERS):
            result.fail(
                code="WORKER_SOURCE_TRACE_MISSING",
                message="worker output must include a source or search trace section",
                path=rel,
                evidence=", ".join(SOURCE_TRACE_MARKERS),
            )
        if rel.startswith("scouts/") and any(term in text for term in SCOUT_FORBIDDEN_TERMS):
            result.fail(
                code="SCOUT_FORBIDDEN_CONCLUSION",
                message="Scout output must not contain action-class style conclusion language",
                path=rel,
            )


def _check_final_report(workspace: Path, profile: ContractProfile, result: ContractResult) -> None:
    reports = find_markdown_reports(workspace)
    if not reports:
        result.fail(
            code="FINAL_REPORT_MISSING",
            message="reports/ must contain a Markdown final report artifact",
            path="reports/",
        )
        return
    combined = "\n\n".join(path.read_text(encoding="utf-8") for path in reports).lower()
    for label, markers in REPORT_REQUIREMENTS.items():
        if not any(marker.lower() in combined for marker in markers):
            result.fail(
                code=f"FINAL_REPORT_MISSING_{label}",
                message=f"final report is missing required area: {label.lower().replace('_', ' ')}",
                path="reports/",
                evidence=", ".join(markers),
            )
    if profile.mode == "sector" and _contains_sector_action_language(combined):
        result.fail(
            code="SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE",
            message="Sector Hunt output must not contain action-class style conclusions",
            path="reports/",
            evidence="found buy/sell/action class language",
        )


def _contains_sector_action_language(text: str) -> bool:
    return "action class" in text or re.search(r"\b(?:buy|sell)\b", text) is not None
