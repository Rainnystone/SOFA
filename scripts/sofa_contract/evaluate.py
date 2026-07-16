from __future__ import annotations

import json
import re
from pathlib import Path

from workspace_contract import core_required_files, managed_block_for_name
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

try:
    from framing_contract import (
        FramingContractError,
        evaluate_contract,
        load_contract,
    )
    from framing_contract.model import normalize_contract
except ImportError:
    from scripts.framing_contract import (
        FramingContractError,
        evaluate_contract,
        load_contract,
    )
    from scripts.framing_contract.model import normalize_contract

try:
    from source_cache import (
        SOURCE_INDEX_FILENAME,
        SourceCacheEvaluation,
        evaluate_index,
        has_registered_source_id_reference,
    )
except ImportError:
    from scripts.source_cache import (
        SOURCE_INDEX_FILENAME,
        SourceCacheEvaluation,
        evaluate_index,
        has_registered_source_id_reference,
    )

try:
    from revisit_contract import (
        RevisitContractError,
        RevisitIssue,
        derive_claim_issues,
        derive_freshness_issues,
        derive_frontier_requirements,
        evaluate_history,
        list_cycle_ids,
        load_cycle,
        load_pointer,
        sha256_bytes,
    )
except ImportError:
    from scripts.revisit_contract import (
        RevisitContractError,
        RevisitIssue,
        derive_claim_issues,
        derive_freshness_issues,
        derive_frontier_requirements,
        evaluate_history,
        list_cycle_ids,
        load_cycle,
        load_pointer,
        sha256_bytes,
    )

try:
    from revisit_contract.model import derive_frontier_binding_legality_issue
except ImportError:
    from scripts.revisit_contract.model import (
        derive_frontier_binding_legality_issue,
    )

try:
    from revisit_contract.store import verify_workspace_artifact
except ImportError:
    from scripts.revisit_contract.store import verify_workspace_artifact

try:
    from frontier_lifecycle import (
        LOOP_HEADER_RE,
        derive_loop_counts,
        validate_registry,
    )
except ImportError:
    from scripts.frontier_lifecycle import (
        LOOP_HEADER_RE,
        derive_loop_counts,
        validate_registry,
    )

try:
    from frontier_review import read_registry_snapshot
except ImportError:
    from scripts.frontier_review import read_registry_snapshot

from .result import ContractProfile, ContractResult
from .workspace import (
    find_markdown_reports,
    find_worker_outputs,
    iter_jsonl_records,
    markdown_table_has_data_row,
    parse_stage_progress,
    read_json_file,
    read_specific_markdown_report,
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


def evaluate_specific_ticker_report(
    workspace: Path | str,
    report_path: str,
    *,
    expected_sha256: str | None = None,
    expected_metadata: str | None = None,
) -> ContractResult:
    root = Path(workspace)
    result = ContractResult()
    try:
        relative, payload, text = read_specific_markdown_report(root, report_path)
    except (OSError, ValueError, RevisitContractError) as exc:
        result.fail(
            code="CURRENT_REPORT_INVALID",
            message=str(exc),
            path=str(report_path),
        )
        return result
    if expected_sha256 is not None and sha256_bytes(payload) != expected_sha256:
        result.fail(
            code="CURRENT_REPORT_HASH_DRIFT",
            message="registered report bytes do not match report_sha256",
            path=relative,
        )
        return result
    if expected_metadata is not None and not _has_exact_single_metadata_block(
        payload.decode("utf-8"),
        expected_metadata,
    ):
        result.fail(
            code="REVISIT_REPORT_METADATA_MISMATCH",
            message="report does not contain the exact derived revisit metadata block",
            path=relative,
        )
    profile = ContractProfile(mode="ticker", target="final_report")
    for label in _missing_final_report_requirements(text, profile):
        result.fail(
            code=f"FINAL_REPORT_MISSING_{label}",
            message=f"final report is missing required area: {label.lower().replace('_', ' ')}",
            path=relative,
            evidence=", ".join(TICKER_REPORT_REQUIREMENTS[label]),
        )
    return result


def _check_revisit_ticker_mode(
    workspace: Path,
    result: ContractResult,
) -> bool:
    try:
        state = read_json_file(workspace / "state.json")
    except (OSError, ValueError) as exc:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=str(exc),
            path="state.json",
        )
        return False
    if isinstance(state, dict) and state.get("mode") == "sector":
        result.fail(
            code="REVISIT_UNSUPPORTED_MODE",
            message="revisit_report is unavailable for Sector workspaces",
            path="state.json",
        )
        return False
    if not isinstance(state, dict) or state.get("mode") != "ticker":
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="revisit_report requires state.json with mode=ticker",
            path="state.json",
        )
        return False
    return True


def evaluate_revisit_report(
    workspace: Path | str,
    cycle_id: str,
    require_candidate: bool = False,
) -> ContractResult:
    del require_candidate
    root = Path(workspace)
    result = ContractResult()
    if not _check_revisit_ticker_mode(root, result):
        return result
    try:
        pointer = load_pointer(root)
        cycle = load_cycle(root, cycle_id)
        registry, _ = read_registry_snapshot(root)
        ledger_text = (root / "evidence_ledger.md").read_text(encoding="utf-8")
    except (OSError, ValueError, RevisitContractError) as exc:
        message = str(exc)
        code = (
            "REVISIT_CLAIM_SUPPORT_FORBIDDEN"
            if "cannot be used as positive support" in message
            else "REVISIT_CYCLE_MALFORMED"
        )
        result.fail(
            code=code,
            message=message,
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return result

    _check_revisit_intake_authorities(root, cycle, result)

    current = pointer["current_revision"]
    base = cycle["intake"]["base_revision"]
    expected_base = (
        {
            "revision_id": current["revision_id"],
            "report_path": current["report_path"],
            "report_sha256": current["report_sha256"],
            "action_class": current["action_class"],
        }
        if current is not None
        else None
    )
    base_drift = base != expected_base
    if current is not None:
        try:
            relative, payload, _ = read_specific_markdown_report(
                root, current["report_path"]
            )
            base_drift = base_drift or (
                relative != current["report_path"]
                or sha256_bytes(payload) != current["report_sha256"]
            )
        except (OSError, ValueError, RevisitContractError):
            base_drift = True
    if base_drift:
        result.fail(
            code="REVISIT_BASE_REPORT_DRIFT",
            message="cycle base revision or current report bytes differ from the registered pointer",
            path="cycle.intake.base_revision",
        )

    source_evaluation = evaluate_index(root)
    if (root / SOURCE_INDEX_FILENAME).exists():
        _append_source_cache_evaluation(result, source_evaluation)
    source_ids = {str(record["source_id"]) for record in source_evaluation.records}
    source_context_valid = not source_evaluation.issues
    for trigger_index, trigger in enumerate(cycle["intake"]["triggers"]):
        if not any(
            _revisit_evidence_ref_valid(
                root,
                reference,
                source_ids=source_ids,
                source_context_valid=source_context_valid,
            )
            for reference in trigger["evidence_refs"]
        ):
            result.fail(
                code="REVISIT_TRIGGER_EVIDENCE_MISSING",
                message="fired trigger has no currently valid registered evidence reference",
                path=f"cycle.intake.triggers[{trigger_index}].evidence_refs",
                evidence=trigger["trigger_id"],
            )

    for issue in derive_claim_issues(cycle):
        result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )
    if cycle["decision_assessment"] is None and not any(
        issue.code == "REVISIT_CLAIM_UNRESOLVED" for issue in result.failures
    ):
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="pre-report readiness requires a decision assessment",
            path="cycle.decision_assessment",
        )

    dispatch_records = _check_dispatch_log(
        root,
        read_text_file(root / "research_workflow.md"),
        ContractProfile(mode="ticker", target="revisit_report"),
        result,
    )
    for issue in _derive_revisit_frontier_floor_issues(
        root,
        cycle,
        registry,
        ledger_text,
        dispatch_records,
    ):
        result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )
    for issue in derive_freshness_issues(cycle):
        result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )
    for resolution_index, resolution in enumerate(cycle["claim_resolutions"]):
        if resolution["status"] not in {"confirmed", "weakened"}:
            continue
        if any(
            _revisit_evidence_ref_valid(
                root,
                reference,
                source_ids=source_ids,
                source_context_valid=source_context_valid,
            )
            for reference in resolution["current_evidence_refs"]
        ):
            continue
        result.fail(
            code="REVISIT_FRESHNESS_SUPPORT_INVALID",
            message="positive claim support has no currently valid exact evidence reference",
            path=(
                f"cycle.claim_resolutions[{resolution_index}].current_evidence_refs"
            ),
            evidence=resolution["claim_id"],
        )
    return result


def _check_revisit_intake_authorities(
    workspace: Path,
    cycle: dict,
    result: ContractResult,
) -> None:
    framing = cycle["intake"]["framing"]
    try:
        relative, payload = verify_workspace_artifact(
            workspace,
            framing["path"],
            framing["sha256"],
        )
        if relative != framing["path"]:
            raise RevisitContractError(
                "framing contract path differs from the immutable intake path"
            )
        raw_contract = json.loads(payload.decode("utf-8"))
        contract = normalize_contract(raw_contract)
        evaluation = evaluate_contract(contract, state_mode="ticker")
        if not evaluation.complete:
            details = "; ".join(
                f"{issue.code} {issue.field}: {issue.message}"
                for issue in evaluation.issues
            )
            raise RevisitContractError(
                f"framing contract is invalid: {details}"
            )
        if contract["mode"] != "ticker":
            raise RevisitContractError("framing contract mode must be ticker")
        if contract["research_posture"] != "revisit":
            raise RevisitContractError(
                "framing contract research_posture must be revisit"
            )
        snapshot = {
            "subject_resolution": contract["subject_resolution"],
            "research_posture": contract["research_posture"],
            "time_horizon": contract["time_horizon"],
            "market_scope": contract["market_scope"],
            "risk_appetite": contract["risk_appetite"],
            "output_expectation": contract["output_expectation"],
            "report_language": contract["report_language"],
            "budget_appetite": contract["budget_appetite"],
        }
        if snapshot != framing["snapshot"]:
            raise RevisitContractError(
                "live framing contract snapshot differs from immutable intake"
            )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        FramingContractError,
        RevisitContractError,
    ) as exc:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=str(exc),
            path="cycle.intake.framing",
        )

    for claim_index, claim in enumerate(cycle["intake"]["selected_claims"]):
        source_ref = claim["source_ref"]
        try:
            relative, _ = verify_workspace_artifact(
                workspace,
                source_ref["path"],
                source_ref["sha256"],
            )
            if relative != source_ref["path"]:
                raise RevisitContractError(
                    "selected claim source path differs from immutable intake"
                )
        except (OSError, RevisitContractError) as exc:
            result.fail(
                code="REVISIT_CYCLE_MALFORMED",
                message=str(exc),
                path=(
                    f"cycle.intake.selected_claims[{claim_index}].source_ref"
                ),
                evidence=claim["claim_id"],
            )


def _revisit_evidence_ref_valid(
    workspace: Path,
    reference: dict,
    *,
    source_ids: set[str],
    source_context_valid: bool,
) -> bool:
    if reference.get("kind") == "source":
        return (
            source_context_valid
            and str(reference.get("source_id", "")) in source_ids
        )
    normalized = _normalize_delivery_path(workspace, reference.get("path", ""))
    if normalized is None:
        return False
    path = workspace / normalized
    try:
        payload = path.read_bytes()
    except OSError:
        return False
    return sha256_bytes(payload) == reference.get("sha256")


def _evaluate_discovered_revisit_report(workspace: Path) -> ContractResult:
    result = ContractResult()
    if not _check_revisit_ticker_mode(workspace, result):
        return result
    try:
        pointer = load_pointer(workspace)
        cycles = [
            load_cycle(workspace, cycle_id)
            for cycle_id in list_cycle_ids(workspace)
        ]
        history = evaluate_history(pointer, cycles)
    except (OSError, ValueError, RevisitContractError) as exc:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=str(exc),
            path="revisit_contract.json",
        )
        return result
    if history.issues:
        for issue in history.issues:
            result.fail(
                code="REVISIT_CYCLE_MALFORMED",
                message=issue.message,
                path=issue.path,
                evidence=issue.evidence,
            )
        return result
    eligible = (
        *history.nonterminal_cycle_ids,
        *history.completed_unpublished_cycle_ids,
    )
    if len(eligible) != 1:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="revisit_report requires exactly one active, ready, or completed-unpublished cycle",
            path="revisit_cycles",
            evidence=", ".join(eligible),
        )
        return result
    return evaluate_revisit_report(workspace, eligible[0])


def _has_exact_single_metadata_block(report_text: str, expected_metadata: str) -> bool:
    return report_text.count(expected_metadata) == 1


def evaluate_workspace(workspace_path: Path | str, profile: ContractProfile) -> ContractResult:
    workspace = Path(workspace_path)
    if profile.target == "revisit_report":
        return _evaluate_discovered_revisit_report(workspace)
    result = ContractResult()
    state = _check_core_workspace_files(workspace, result)
    workflow_text = read_text_file(workspace / "research_workflow.md")
    _check_state_workflow_consistency(workspace, state, workflow_text, result)
    if _requires_framing_contract(profile):
        _check_framing_contract(workspace, state, result)
    _check_search_log(workspace, state, result)
    _check_source_cache(workspace, result)
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


def _requires_framing_contract(profile: ContractProfile) -> bool:
    return (
        profile.target == "stage_transition"
        and profile.from_stage == "stage_0"
        and profile.to_stage in {None, "stage_1"}
    )


def _check_framing_contract(workspace: Path, state_payload: dict | None, result: ContractResult) -> None:
    # Note: ContractResult.fail signature is fail(code, message, path, evidence).
    # message comes before path. Tests assert (issue.code, issue.path) tuples,
    # so getting this order right is load-bearing.
    try:
        contract = load_contract(workspace)
    except FileNotFoundError:
        result.fail(
            code="FRAMING_CONTRACT_MISSING",
            message="framing_contract.json is required before completing Stage 0. Run scripts/framing_intake.py <workspace> init.",
            path="framing_contract.json",
        )
        return
    except json.JSONDecodeError as exc:
        result.fail(
            code="FRAMING_CONTRACT_MALFORMED",
            message=f"framing_contract.json is not valid JSON: {exc}",
            path="framing_contract.json",
        )
        return
    except FramingContractError as exc:
        result.fail(
            code="FRAMING_CONTRACT_MALFORMED",
            message=str(exc),
            path="framing_contract.json",
        )
        return

    state_mode = None
    if isinstance(state_payload, dict):
        state_mode = str(state_payload.get("mode", "")) or None
    evaluation = evaluate_contract(contract, state_mode=state_mode)
    for issue in evaluation.issues:
        result.fail(
            code=issue.code,
            message=issue.message,
            path=f"framing_contract.json:{issue.field}",
        )

    # The managed Markdown mirror is the post-compaction recovery anchor —
    # Phase 5's reason for existing. A complete JSON without the mirror in
    # research_workflow.md means intent is not recoverable across context
    # loss, so Stage 0 cannot be complete. Check marker presence only (not
    # content parity with the JSON); content consistency is the CLI's
    # discipline and the gate must not diff prose.
    _require_framing_mirror(workspace, result)


def _require_framing_mirror(workspace: Path, result: ContractResult) -> None:
    block = managed_block_for_name("framing-contract")
    workflow_text = read_text_file(workspace / "research_workflow.md")
    if workflow_text is None:
        result.fail(
            code="FRAMING_MIRROR_MISSING",
            message="research_workflow.md is missing the framing-contract managed mirror required for Stage 0.",
            path="research_workflow.md",
        )
        return
    if block.start_marker not in workflow_text or block.end_marker not in workflow_text:
        result.fail(
            code="FRAMING_MIRROR_MISSING",
            message=(
                "research_workflow.md is missing the framing-contract managed block "
                f"({block.start_marker}/{block.end_marker}). Run scripts/framing_intake.py <workspace> render."
            ),
            path="research_workflow.md",
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


def _derive_revisit_frontier_floor_issues(
    workspace: Path,
    cycle: dict,
    registry: dict,
    ledger_text: str,
    dispatch_records: list[dict],
) -> tuple[RevisitIssue, ...]:
    validate_registry(registry)
    try:
        live_loop_counts = derive_loop_counts(ledger_text, registry)
    except ValueError as exc:
        return (
            RevisitIssue(
                "REVISIT_FRONTIER_BINDING_INVALID",
                "evidence_ledger.md",
                str(exc),
            ),
        )
    frontiers = {
        frontier["id"]: frontier for frontier in registry["frontiers"]
    }
    headers: list[tuple[int, str]] = []
    for raw_line in ledger_text.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("## Loop "):
            continue
        match = LOOP_HEADER_RE.fullmatch(line)
        if match is None:
            return (
                RevisitIssue(
                    "REVISIT_FRONTIER_BINDING_INVALID",
                    "evidence_ledger.md",
                    f"malformed loop header: {line}",
                ),
            )
        headers.append(
            (int(match.group("loop")), match.group("frontier_id"))
        )

    covered_search_loops, _ = _valid_search_coverage(workspace)
    boundary = cycle["intake"]["workspace_boundary"][
        "max_existing_loop_number"
    ]
    issues: list[RevisitIssue] = []
    for index, binding in enumerate(cycle["frontier_bindings"]):
        path = f"cycle.frontier_bindings[{index}]"
        frontier_id = binding["frontier_id"]
        frontier = frontiers.get(frontier_id)
        if frontier is None:
            issues.append(
                RevisitIssue(
                    "REVISIT_FRONTIER_BINDING_INVALID",
                    path,
                    "bound frontier is absent from the validated registry",
                    frontier_id,
                )
            )
            continue
        legality_issue = derive_frontier_binding_legality_issue(
            cycle,
            binding,
            frontier,
            path=path,
        )
        if legality_issue is not None:
            issues.append(legality_issue)
            continue
        new_loop_numbers = tuple(
            sorted(
                {
                    loop_number
                    for loop_number, header_frontier_id in headers
                    if header_frontier_id == frontier_id
                    and loop_number > boundary
                }
            )
        )
        loop_ids = tuple(f"loop_{number}" for number in new_loop_numbers)
        baseline_loop_count = binding["baseline_loop_count"]
        live_loop_count = live_loop_counts.get(frontier_id, 0)
        if (
            len(loop_ids) < 3
            or live_loop_count < baseline_loop_count + 3
        ):
            suffix = (
                "; retire this incomplete cycle through abort"
                if frontier.get("status") == "Retired"
                else ""
            )
            issues.append(
                RevisitIssue(
                    "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                    path,
                    "bound frontier requires at least three distinct "
                    "post-boundary ledger loops and a live loop count at least "
                    f"baseline+3; found post-boundary={len(loop_ids)}, "
                    f"baseline={baseline_loop_count}, live={live_loop_count}{suffix}",
                    ", ".join(loop_ids),
                )
            )
            continue

        missing_search = tuple(
            loop_id for loop_id in loop_ids if loop_id not in covered_search_loops
        )
        if missing_search:
            issues.append(
                RevisitIssue(
                    "REVISIT_SEARCH_FLOOR_MISSING",
                    path,
                    "every post-boundary frontier loop requires a valid search record",
                    ", ".join(missing_search),
                )
            )

        for role_slug, code in (
            ("frontier_scout", "REVISIT_SCOUT_FLOOR_MISSING"),
            ("challenge_probe", "REVISIT_CHALLENGE_FLOOR_MISSING"),
        ):
            missing_role = tuple(
                loop_id
                for loop_id in loop_ids
                if not _has_exact_revisit_role_delivery(
                    workspace,
                    dispatch_records,
                    loop_id,
                    role_slug,
                )
            )
            if missing_role:
                issues.append(
                    RevisitIssue(
                        code,
                        path,
                        f"every post-boundary frontier loop requires delivered {role_slug} work",
                        ", ".join(missing_role),
                    )
                )

        baseline_reviews = binding["baseline_review_count"]
        matching_reviews = [
            decision
            for decision in frontier.get("review_decisions", [])
            if isinstance(decision.get("review_number"), int)
            and not isinstance(decision.get("review_number"), bool)
            and decision["review_number"] > baseline_reviews
            and decision.get("at_loop") in new_loop_numbers
            and decision.get("decision") in {"Continued", "Retired"}
        ]
        review_complete = (
            int(frontier.get("review_count", 0)) >= baseline_reviews + 1
            and bool(matching_reviews)
            and frontier.get("status") == matching_reviews[-1]["decision"]
        )
        if not review_complete:
            issues.append(
                RevisitIssue(
                    "REVISIT_REVIEW_FLOOR_MISSING",
                    path,
                    "bound frontier requires a post-binding review that leaves Continued or review-based Retired",
                    (
                        f"baseline={baseline_reviews}; "
                        f"current={frontier.get('review_count', 0)}"
                    ),
                )
            )
    issues.extend(derive_frontier_requirements(cycle))
    failed_binding_paths = {
        issue.path
        for issue in issues
        if issue.path.startswith("cycle.frontier_bindings[")
    }
    bound_claim_ids = {
        claim_id
        for binding in cycle["frontier_bindings"]
        for claim_id in binding["claim_ids"]
    }
    for claim in (
        *cycle["intake"]["selected_claims"],
        *cycle["derived_claims"],
    ):
        claim_id = claim["claim_id"]
        binding_paths = {
            f"cycle.frontier_bindings[{index}]"
            for index, binding in enumerate(cycle["frontier_bindings"])
            if claim_id in binding["claim_ids"]
        }
        if (
            claim_id in bound_claim_ids
            and binding_paths
            and binding_paths.issubset(failed_binding_paths)
        ):
            issues.append(
                RevisitIssue(
                    "REVISIT_FRONTIER_BINDING_INVALID",
                    f"cycle.claim_resolutions[{claim_id}]",
                    "claim has no binding that independently passes every research floor",
                    claim_id,
                )
            )
    return tuple(issues)


def _has_exact_revisit_role_delivery(
    workspace: Path,
    records: list[dict],
    loop_id: str,
    required_role_slug: str,
) -> bool:
    for record in records:
        if str(record.get("loop_id", "")) != loop_id:
            continue
        if not _dispatch_record_counts_as_delivery(record):
            continue
        normalized_path = _normalize_delivery_path(
            workspace, record.get("delivery_path", "")
        )
        if (
            normalized_path is None
            or not (workspace / normalized_path).is_file()
            or _dispatch_role_delivery_issue(record, normalized_path, "ticker")
            is not None
        ):
            continue
        try:
            role_slug = normalize_role_slug(
                record.get("role"), delivery_path=normalized_path
            )
        except ValueError:
            continue
        if role_slug == required_role_slug:
            return True
    return False


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


def _check_source_cache(workspace: Path, result: ContractResult) -> None:
    # Stage-independent: a present index must be internally consistent at
    # every gate. An absent index passes because legacy or fresh workspaces
    # are not failed retroactively when no records exist yet.
    if not (workspace / SOURCE_INDEX_FILENAME).exists():
        return
    evaluation = evaluate_index(workspace)
    _append_source_cache_evaluation(result, evaluation)


def _append_source_cache_evaluation(
    result: ContractResult,
    evaluation: SourceCacheEvaluation,
) -> None:
    for issue in evaluation.issues:
        result.fail(code=issue.code, message=issue.message, path=issue.location)
    for warning in evaluation.warnings:
        result.warn(code=warning.code, message=warning.message, path=warning.location)


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
) -> list[dict]:
    worker_outputs = find_worker_outputs(workspace)
    workflow_claims_delivery = _workflow_claims_subagent_delivery(workflow_text)
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        if not worker_outputs and not workflow_claims_delivery:
            return []
        result.fail(
            code="DISPATCH_PROOF_MISSING" if workflow_claims_delivery else "DISPATCH_LOG_MISSING",
            message="worker outputs and workflow dispatch claims require dispatch_log.jsonl or approved degraded-mode records",
            path="dispatch_log.jsonl",
            evidence=_dispatch_missing_evidence(worker_outputs, workflow_claims_delivery),
        )
        return []
    records = _read_dispatch_records(workspace, result)
    if records is None:
        return []
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
    return records


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
        has_trace = has_source_trace(text, candidate_roles[0]) or has_registered_source_id_reference(
            workspace, text
        )
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
    if profile.mode == "ticker":
        try:
            pointer = load_pointer(workspace, allow_missing=True)
        except (OSError, RevisitContractError) as exc:
            result.fail(
                code="CURRENT_REPORT_INVALID",
                message=str(exc),
                path="revisit_contract.json",
            )
            return
        if pointer is None or pointer["current_revision"] is None:
            result.fail(
                code="FINAL_REPORT_MISSING",
                message="ticker final report authority has no registered current report",
                path="revisit_contract.json",
            )
            result.fail(
                code="CURRENT_REPORT_UNREGISTERED",
                message="ticker final-report readiness requires an explicitly registered current report",
                path="revisit_contract.json",
            )
            return
        revision = pointer["current_revision"]
        if revision["cycle_id"] is not None and not _check_current_revision_cycle(
            workspace,
            revision,
            result,
        ):
            return
        result.extend(
            evaluate_specific_ticker_report(
                workspace,
                revision["report_path"],
                expected_sha256=revision["report_sha256"],
            )
        )
        return

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


def _check_current_revision_cycle(
    workspace: Path,
    revision: dict,
    result: ContractResult,
) -> bool:
    cycle_id = revision["cycle_id"]
    try:
        cycle = load_cycle(workspace, cycle_id)
    except (OSError, RevisitContractError) as exc:
        result.fail(
            code="CURRENT_REPORT_CYCLE_INVALID",
            message=str(exc),
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return False
    if cycle["status"] != "completed":
        result.fail(
            code="CURRENT_REPORT_CYCLE_INVALID",
            message="current report must originate from an immutable completed cycle",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return False

    candidate = cycle["report_candidate"]
    assessment = cycle["decision_assessment"]
    base_revision = cycle["intake"]["base_revision"]
    candidate_matches = (
        cycle["candidate_revision_id"] == revision["revision_id"]
        and isinstance(candidate, dict)
        and candidate["revision_id"] == revision["revision_id"]
        and candidate["revision_of"] == revision["revision_of"]
        and candidate["report_path"] == revision["report_path"]
        and candidate["report_sha256"] == revision["report_sha256"]
        and base_revision["revision_id"] == revision["revision_of"]
        and isinstance(assessment, dict)
        and assessment["new_action_class"] == revision["action_class"]
    )
    if not candidate_matches:
        result.fail(
            code="CURRENT_REPORT_LINEAGE_MISMATCH",
            message="current revision does not exactly match its completed cycle candidate lineage",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return False
    return True


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
