from __future__ import annotations

import re
from pathlib import Path

from .result import ContractProfile, ContractResult
from .workspace import find_markdown_reports, parse_stage_progress, read_json_file, read_text_file


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


def evaluate_workspace(workspace_path: Path | str, profile: ContractProfile) -> ContractResult:
    workspace = Path(workspace_path)
    result = ContractResult()
    state = _check_core_workspace_files(workspace, result)
    workflow_text = read_text_file(workspace / "research_workflow.md")
    _check_state_workflow_consistency(workspace, state, workflow_text, result)
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
