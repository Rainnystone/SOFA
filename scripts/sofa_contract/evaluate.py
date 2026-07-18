from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
        registered_source_ids,
    )
    from source_cache.model import source_ids_in_text
except ImportError:
    from scripts.source_cache import (
        SOURCE_INDEX_FILENAME,
        SourceCacheEvaluation,
        evaluate_index,
        has_registered_source_id_reference,
        registered_source_ids,
    )
    from scripts.source_cache.model import source_ids_in_text

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
        render_report_metadata,
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
        render_report_metadata,
        sha256_bytes,
    )

try:
    from revisit_contract.model import derive_frontier_binding_legality_issue
except ImportError:
    from scripts.revisit_contract.model import (
        derive_frontier_binding_legality_issue,
    )

try:
    from revisit_contract.store import (
        _read_authority_generation,
        _require_authority_generation,
        verify_workspace_artifact,
    )
except ImportError:
    from scripts.revisit_contract.store import (
        _read_authority_generation,
        _require_authority_generation,
        verify_workspace_artifact,
    )

try:
    from frontier_lifecycle import (
        KNOWN_STAGES,
        LOOP_HEADER_RE,
        validate_registry,
    )
except ImportError:
    from scripts.frontier_lifecycle import (
        KNOWN_STAGES,
        LOOP_HEADER_RE,
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
REVISIT_REPORT_REQUIREMENTS = {
    "REVISIT_METADATA": ("revisit revision metadata",),
    "TRIGGER_DELTA": ("trigger delta",),
    "CLAIM_DELTA": ("claim delta",),
    "EVIDENCE_FRESHNESS_DELTA": ("evidence freshness delta",),
    "FRONTIER_DELTA": ("frontier delta",),
    "FINANCIAL_REDTEAM_DELTA": (
        "financial/red-team delta",
        "financial and red-team delta",
    ),
    "UNRESOLVED_BLOCKED_GAPS": ("unresolved or blocked gaps",),
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
    try:
        relative, payload, _text = read_specific_markdown_report(root, report_path)
    except (OSError, ValueError, RevisitContractError) as exc:
        result = ContractResult()
        result.fail(
            code="CURRENT_REPORT_INVALID",
            message=str(exc),
            path=str(report_path),
        )
        return result
    return _evaluate_specific_ticker_report_document(
        relative,
        payload,
        expected_sha256=expected_sha256,
        expected_metadata=expected_metadata,
    )


def _evaluate_specific_ticker_report_document(
    report_path: str,
    payload: bytes,
    *,
    expected_sha256: str | None = None,
    expected_metadata: str | None = None,
) -> ContractResult:
    """Pure document owner for ticker report validation.

    The thin filesystem adapter ``evaluate_specific_ticker_report`` reads the
    report and delegates here. Task 6.4's read-only seam passes preloaded bytes
    from an ``ObservedReadSession``.
    """
    result = ContractResult()
    if expected_sha256 is not None and sha256_bytes(payload) != expected_sha256:
        result.fail(
            code="CURRENT_REPORT_HASH_DRIFT",
            message="registered report bytes do not match report_sha256",
            path=report_path,
        )
        return result
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        result.fail(
            code="CURRENT_REPORT_INVALID",
            message=f"report is not valid UTF-8: {exc}",
            path=report_path,
        )
        return result
    if expected_metadata is not None and not _has_exact_single_metadata_block(
        text,
        expected_metadata,
    ):
        result.fail(
            code="REVISIT_REPORT_METADATA_MISMATCH",
            message="report does not contain the exact derived revisit metadata block",
            path=report_path,
        )
    profile = ContractProfile(mode="ticker", target="final_report")
    lower_text = text.lower()
    for label in _missing_final_report_requirements(lower_text, profile):
        result.fail(
            code=f"FINAL_REPORT_MISSING_{label}",
            message=f"final report is missing required area: {label.lower().replace('_', ' ')}",
            path=report_path,
            evidence=", ".join(TICKER_REPORT_REQUIREMENTS[label]),
        )
    if expected_metadata is not None:
        for label, markers in REVISIT_REPORT_REQUIREMENTS.items():
            if any(marker.lower() in lower_text for marker in markers):
                continue
            result.fail(
                code=f"FINAL_REPORT_MISSING_{label}",
                message=(
                    "revisit report is missing required area: "
                    f"{label.lower().replace('_', ' ')}"
                ),
                path=report_path,
                evidence=", ".join(markers),
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
) -> ContractResult:
    """Evaluate one named cycle through the public readiness seam."""
    from .revisit_readiness import evaluate_revisit_readiness

    return evaluate_revisit_readiness(workspace, cycle_id)


def _evaluate_revisit_report_impl(
    workspace: Path | str,
    cycle_id: str,
    *,
    readiness_result: ContractResult,
    selected_cycle: dict | None = None,
) -> tuple[ContractResult, tuple[Any, ...]]:
    result = readiness_result

    root = Path(workspace)
    if selected_cycle is None:
        try:
            cycle = load_cycle(root, cycle_id)
        except RevisitContractError as exc:
            result.fail(
                code="REVISIT_REPORT_CANDIDATE_MISSING",
                message=str(exc),
                path=f"revisit_cycles/{cycle_id}.json",
            )
            return result, ()
    else:
        cycle = selected_cycle
    candidate = cycle["report_candidate"]
    if candidate is None:
        result.fail(
            code="REVISIT_REPORT_CANDIDATE_MISSING",
            message="final revisit validation requires a registered report candidate",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return result, ()
    if cycle["status"] not in {"ready_for_report", "completed"}:
        result.fail(
            code="REVISIT_REPORT_CANDIDATE_MISSING",
            message="report candidate must belong to a ready or completed cycle",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return result, ()

    rerun_generations = _evaluate_revisit_rerun_matrix(root, cycle, result)
    authority_snapshots = [
        generation.snapshot
        for generation, _failure_code, _failure_path in rerun_generations
    ]

    candidate_path = candidate["report_path"]
    try:
        candidate_generation = _read_authority_generation(
            root, root / candidate_path
        )
    except RevisitContractError as exc:
        result.fail(
            code="REVISIT_REPORT_HASH_DRIFT",
            message=str(exc),
            path=candidate_path,
        )
        return result, tuple(authority_snapshots)
    authority_snapshots.append(candidate_generation.snapshot)
    if (
        candidate_generation.snapshot.expected_sha256
        != candidate["report_sha256"]
    ):
        result.fail(
            code="REVISIT_REPORT_HASH_DRIFT",
            message="registered report candidate bytes do not match report_sha256",
            path=candidate_path,
        )
        return result, tuple(authority_snapshots)
    expected_metadata = render_report_metadata(cycle)
    report_result = _evaluate_specific_ticker_report_document(
        candidate_path,
        candidate_generation.payload,
        expected_sha256=candidate["report_sha256"],
        expected_metadata=expected_metadata,
    )
    for issue in report_result.failures:
        if issue.code == "CURRENT_REPORT_HASH_DRIFT":
            result.fail(
                code="REVISIT_REPORT_HASH_DRIFT",
                message=issue.message,
                path=issue.path,
                evidence=issue.evidence,
            )
        else:
            result.fail(
                code=issue.code,
                message=issue.message,
                path=issue.path,
                evidence=issue.evidence,
            )
    result.warnings.extend(report_result.warnings)
    _evaluate_revisit_blocked_disclosure(
        cycle,
        candidate_generation.payload,
        candidate_path,
        result,
    )
    try:
        _require_authority_generation(
            candidate_generation,
            "after report candidate evaluation",
        )
    except RevisitContractError as exc:
        result.fail(
            code="REVISIT_REPORT_HASH_DRIFT",
            message=str(exc),
            path=candidate_path,
        )
    for generation, failure_code, failure_path in rerun_generations:
        try:
            _require_authority_generation(
                generation,
                "after final revisit evaluation",
            )
        except RevisitContractError as exc:
            result.fail(
                code=failure_code,
                message=str(exc),
                path=failure_path,
            )
    return result, tuple(authority_snapshots)


@dataclass(frozen=True)
class _PreparedRevisitReport:
    result: ContractResult
    cycle: dict | None
    generation_closure: Any | None
    authority_snapshots: tuple[Any, ...]


def _prepare_revisit_report_for_publication(
    workspace: Path | str,
    cycle_id: str,
) -> _PreparedRevisitReport:
    """Prepare one final verdict whose readiness closure can cross persistence."""
    from .revisit_readiness import _prepare_revisit_readiness

    try:
        from revisit_contract.generation import (
            AuthorityDriftError,
            ObservedReadSession,
        )
    except ImportError:
        from scripts.revisit_contract.generation import (
            AuthorityDriftError,
            ObservedReadSession,
        )

    lexical_workspace = Path(workspace)
    result = ContractResult()
    session = ObservedReadSession(lexical_workspace)
    try:
        prepared = _prepare_revisit_readiness(
            session,
            result,
            cycle_id,
            lexical_workspace,
        )
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
        return _PreparedRevisitReport(result, None, None, ())

    cycle = (
        prepared.selected_cycle.cycle
        if prepared.selected_cycle is not None
        else None
    )
    if cycle is None:
        result.fail(
            code="REVISIT_REPORT_CANDIDATE_MISSING",
            message="final revisit validation requires one globally eligible cycle",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        authority_snapshots: tuple[Any, ...] = ()
    else:
        result, authority_snapshots = _evaluate_revisit_report_impl(
            lexical_workspace,
            cycle_id,
            readiness_result=result,
            selected_cycle=cycle,
        )
    try:
        prepared.closure.require_unchanged()
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
    return _PreparedRevisitReport(
        result,
        cycle,
        prepared.closure,
        authority_snapshots,
    )


def _prepare_published_current_for_publication(
    workspace: Path | str,
    cycle: dict,
) -> _PreparedRevisitReport:
    """Strictly validate an already-current revisit report with a read closure."""
    from .revisit_readiness import _prepare_published_current_readiness

    try:
        from revisit_contract.generation import (
            AuthorityDriftError,
            ObservedReadSession,
        )
    except ImportError:
        from scripts.revisit_contract.generation import (
            AuthorityDriftError,
            ObservedReadSession,
        )

    lexical_workspace = Path(workspace)
    closure_result = ContractResult()
    session = ObservedReadSession(lexical_workspace)
    try:
        readiness = _prepare_published_current_readiness(
            session,
            closure_result,
            cycle["cycle_id"],
            lexical_workspace,
        )
    except AuthorityDriftError as exc:
        result = ContractResult()
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
        return _PreparedRevisitReport(result, None, None, ())

    result = evaluate_workspace(
        lexical_workspace,
        ContractProfile(mode="ticker", target="final_report"),
    )
    result.extend(closure_result)
    selected_cycle = (
        readiness.selected_cycle.cycle
        if readiness.selected_cycle is not None
        else cycle
    )
    result, authority_snapshots = _evaluate_revisit_report_impl(
        lexical_workspace,
        cycle["cycle_id"],
        readiness_result=result,
        selected_cycle=selected_cycle,
    )
    try:
        readiness.closure.require_unchanged()
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
    return _PreparedRevisitReport(
        result,
        cycle,
        readiness.closure,
        authority_snapshots,
    )


def _evaluate_revisit_blocked_disclosure(
    cycle: dict,
    report_payload: bytes,
    report_path: str,
    result: ContractResult,
) -> None:
    blocked_claim_ids = cycle["decision_assessment"]["blocked_claim_ids"]
    if not blocked_claim_ids:
        return
    try:
        report_text = report_payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    gap_section = _markdown_section(report_text, "Unresolved or Blocked Gaps")
    for claim_id in blocked_claim_ids:
        pattern = rf"(?<![A-Za-z0-9_-]){re.escape(claim_id)}(?![A-Za-z0-9_-])"
        if gap_section is not None and re.search(pattern, gap_section):
            continue
        result.fail(
            code="REVISIT_REPORT_BLOCKED_DISCLOSURE_MISSING",
            message=(
                "blocked claim must be disclosed in the report's "
                "Unresolved or Blocked Gaps section"
            ),
            path=report_path,
            evidence=claim_id,
        )


def _required_revisit_rerun_rows(cycle: dict) -> tuple[tuple[str, str | None, int | None, str | None, str], ...]:
    required = set(cycle["decision_assessment"]["required_reruns"])
    rows: list[tuple[str, str | None, int | None, str | None, str]] = []
    if "affected-financial-bridge" in required:
        rows.append(("bridge", "affected", None, "financial_bridge", "affected-financial-bridge"))
    if "full-financial-bridge" in required:
        rows.append(("bridge", "full", None, "financial_bridge", "full-financial-bridge"))
    for round_number in (1, 2):
        if f"redteam-round-{round_number}" in required:
            rows.append(("redteam_attack", None, round_number, "red_team", f"redteam-round-{round_number}"))
        if f"redteam-defense-{round_number}" in required:
            rows.append(("redteam_defense", None, round_number, None, f"redteam-defense-{round_number}"))
    if "thesis-revision" in required:
        rows.append(("thesis_revision", None, None, None, "thesis-revision"))
    return tuple(rows)


def _dispatch_records_from_payload(payload: bytes) -> tuple[dict, ...]:
    try:
        text = payload.decode("utf-8")
        records = []
        for line in text.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("dispatch row must be an object")
            records.append(value)
        return tuple(records)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RevisitContractError(
            "dispatch_log.jsonl must be valid UTF-8 JSONL"
        ) from exc


def _has_exact_rerun_dispatch(
    records: tuple[dict, ...], artifact_path: str, expected_role: str
) -> bool:
    for record in records:
        if not _dispatch_record_counts_as_delivery(record):
            continue
        if _normalize_delivery_path_from_facts(record.get("delivery_path", "")) != artifact_path:
            continue
        try:
            role_slug = normalize_role_slug(
                record.get("role"), delivery_path=artifact_path
            )
        except ValueError:
            continue
        if role_slug == expected_role:
            return True
    return False


def _evaluate_revisit_rerun_matrix(
    workspace: Path,
    cycle: dict,
    result: ContractResult,
) -> tuple[Any, ...]:
    artifacts = cycle["rerun_artifacts"]
    subject_tickers = cycle["intake"]["framing"]["snapshot"][
        "subject_resolution"
    ].get("tickers")
    allowed_bridge_paths = (
        {
            f"financials/{cycle['cycle_id']}_{ticker}_bridge.md"
            for ticker in subject_tickers
        }
        if isinstance(subject_tickers, list)
        else set()
    )
    generations = []
    artifact_facts: list[tuple[dict, bool]] = []
    for artifact in artifacts:
        artifact_path = artifact["path"]
        try:
            generation = _read_authority_generation(
                workspace, workspace / artifact_path
            )
        except RevisitContractError as exc:
            result.fail(
                code="REVISIT_RERUN_ARTIFACT_MISSING",
                message=str(exc),
                path=artifact_path,
            )
            artifact_facts.append((artifact, False))
            continue
        generations.append(
            (
                generation,
                "REVISIT_RERUN_ARTIFACT_MISSING",
                artifact_path,
            )
        )
        hash_matches = generation.snapshot.expected_sha256 == artifact["sha256"]
        if not hash_matches:
            result.fail(
                code="REVISIT_RERUN_ARTIFACT_MISSING",
                message="registered rerun artifact bytes do not match sha256",
                path=artifact_path,
            )
        ticker_matches = (
            artifact["kind"] != "bridge"
            or artifact_path in allowed_bridge_paths
        )
        if not ticker_matches:
            result.fail(
                code="REVISIT_RERUN_ARTIFACT_MISSING",
                message=(
                    "registered bridge rerun path must match one frozen "
                    "resolved ticker"
                ),
                path=artifact_path,
            )
        artifact_facts.append((artifact, hash_matches and ticker_matches))

    rows = _required_revisit_rerun_rows(cycle)
    dispatch_required: list[tuple[list[dict], str, str]] = []
    for kind, scope, round_number, role, requirement in rows:
        matches = [
            (artifact, valid)
            for artifact, valid in artifact_facts
            if artifact["kind"] == kind
            and artifact["scope"] == scope
            and artifact["round"] == round_number
        ]
        if not matches:
            result.fail(
                code="REVISIT_RERUN_ARTIFACT_MISSING",
                message=f"required cycle-specific rerun artifact is missing: {requirement}",
                path=f"revisit_cycles/{cycle['cycle_id']}.json",
                evidence=requirement,
            )
            continue
        valid_matches = [artifact for artifact, valid in matches if valid]
        if role is not None and valid_matches:
            dispatch_required.append((valid_matches, role, requirement))

    if dispatch_required:
        try:
            dispatch_generation = _read_authority_generation(
                workspace, workspace / "dispatch_log.jsonl"
            )
            dispatch_records = _dispatch_records_from_payload(
                dispatch_generation.payload
            )
            generations.append(
                (
                    dispatch_generation,
                    "REVISIT_RERUN_DISPATCH_MISSING",
                    "dispatch_log.jsonl",
                )
            )
        except RevisitContractError as exc:
            dispatch_records = ()
            dispatch_error = str(exc)
        else:
            dispatch_error = ""
        for matching_artifacts, role, requirement in dispatch_required:
            if not any(
                _has_exact_rerun_dispatch(
                    dispatch_records,
                    artifact["path"],
                    role,
                )
                for artifact in matching_artifacts
            ):
                artifact_path = matching_artifacts[0]["path"]
                result.fail(
                    code="REVISIT_RERUN_DISPATCH_MISSING",
                    message="required rerun artifact lacks an exact delivered role/path record",
                    path="dispatch_log.jsonl",
                    evidence=(
                        dispatch_error
                        or f"{role}: {artifact_path} ({requirement})"
                    ),
                )
    return tuple(generations)


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


def _has_exact_single_metadata_block(report_text: str, expected_metadata: str) -> bool:
    start_marker = "<!-- sofa:revisit-revision:start -->"
    end_marker = "<!-- sofa:revisit-revision:end -->"
    return (
        report_text.count(start_marker) == 1
        and report_text.count(end_marker) == 1
        and report_text.count(expected_metadata) == 1
    )


def evaluate_workspace(workspace_path: Path | str, profile: ContractProfile) -> ContractResult:
    workspace = Path(workspace_path)
    if profile.target == "revisit_report":
        from .revisit_readiness import evaluate_revisit_readiness

        return evaluate_revisit_readiness(workspace)
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
    _check_state_workflow_documents(state, workflow_text, result)


@dataclass(frozen=True)
class _RevisitStateFacts:
    mode: Literal["ticker", "sector"]
    loop_count: int
    stages_completed: frozenset[str]
    current_stage: str | None


@dataclass(frozen=True)
class _RevisitWorkflowFacts:
    text: str
    stage_statuses: tuple[tuple[str, str], ...]

    def status_for(self, stage: str) -> str | None:
        return dict(self.stage_statuses).get(stage)


@dataclass(frozen=True)
class _RevisitLedgerFacts:
    headers: tuple[tuple[int, str], ...]


_WORKFLOW_STATUSES = frozenset({"pending", "in_progress", "complete"})
_WORKFLOW_STAGE_CELL_RE = re.compile(
    r"^Stage (?P<number>[0-9]+): (?P<label>.+)$"
)


def _parse_revisit_state_facts(value: Any) -> _RevisitStateFacts:
    if not isinstance(value, dict):
        raise ValueError("state.json JSON authority must be an object")
    mode = value.get("mode")
    if mode not in {"ticker", "sector"}:
        raise ValueError("state.json mode must be ticker or sector")

    loop_count = value.get("loop_count", 0)
    if (
        not isinstance(loop_count, int)
        or isinstance(loop_count, bool)
        or loop_count < 0
    ):
        raise ValueError(
            "state.json loop_count must be a non-negative integer"
        )

    completed_value = value.get("stages_completed", [])
    if not isinstance(completed_value, list):
        raise ValueError("state.json stages_completed must be a list")
    completed: list[str] = []
    for stage in completed_value:
        if not isinstance(stage, str) or stage not in KNOWN_STAGES:
            raise ValueError(
                "state.json stages_completed contains an invalid stage"
            )
        if stage in completed:
            raise ValueError(
                "state.json stages_completed contains a duplicate stage"
            )
        completed.append(stage)

    current_stage = value.get("current_stage")
    if current_stage is not None and (
        not isinstance(current_stage, str)
        or current_stage not in KNOWN_STAGES
    ):
        raise ValueError("state.json current_stage is invalid")

    return _RevisitStateFacts(
        mode=mode,
        loop_count=loop_count,
        stages_completed=frozenset(completed),
        current_stage=current_stage,
    )


def _parse_revisit_workflow_facts(text: str) -> _RevisitWorkflowFacts:
    statuses: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] == "Stage":
            continue
        if not cells[0].startswith("Stage "):
            continue
        if len(cells) < 2:
            raise ValueError(
                f"workflow stage row {line_number} has no status"
            )
        match = _WORKFLOW_STAGE_CELL_RE.fullmatch(cells[0])
        if match is None:
            raise ValueError(
                f"workflow stage row {line_number} has an invalid identifier"
            )
        stage = f"stage_{int(match.group('number'))}"
        if stage not in KNOWN_STAGES:
            raise ValueError(
                f"workflow stage row {line_number} has an unknown identifier"
            )
        status = cells[1].lower()
        if status not in _WORKFLOW_STATUSES:
            raise ValueError(
                f"workflow stage row {line_number} has invalid status {status!r}"
            )
        if stage in statuses:
            raise ValueError(f"workflow contains duplicate row for {stage}")
        statuses[stage] = status
    return _RevisitWorkflowFacts(
        text=text,
        stage_statuses=tuple(sorted(statuses.items())),
    )


def _parse_revisit_ledger_facts(text: str) -> _RevisitLedgerFacts:
    headers: list[tuple[int, str]] = []
    seen_loop_numbers: set[int] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.startswith("## Loop"):
            continue
        match = LOOP_HEADER_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"malformed loop header at line {line_number}: {line}")
        loop_number = int(match.group("loop"))
        if loop_number in seen_loop_numbers:
            raise ValueError(
                f"duplicate loop number at line {line_number}: {loop_number}"
            )
        seen_loop_numbers.add(loop_number)
        headers.append((loop_number, match.group("frontier_id")))
    return _RevisitLedgerFacts(headers=tuple(headers))


def _check_state_workflow_facts(
    state: _RevisitStateFacts,
    workflow: _RevisitWorkflowFacts,
    result: ContractResult,
) -> None:
    for stage in sorted(state.stages_completed):
        status = workflow.status_for(stage)
        if status != "complete":
            rendered = status if status is not None else "missing"
            result.fail(
                code="STATE_WORKFLOW_STAGE_CONFLICT",
                message=(
                    f"{stage} is completed in state.json but {rendered} "
                    "in research_workflow.md"
                ),
                path="research_workflow.md",
                evidence=f"state.json stages_completed includes {stage}",
            )
    if (
        state.current_stage == "stage_6"
        and workflow.status_for("stage_5") != "complete"
    ):
        result.fail(
            code="STATE_WORKFLOW_STAGE_CONFLICT",
            message=(
                "state.json current_stage is stage_6 but workflow Stage 5 "
                "is not complete"
            ),
            path="research_workflow.md",
            evidence="current_stage=stage_6",
        )


def _check_state_workflow_documents(
    state: dict | None,
    workflow_text: str | None,
    result: ContractResult,
) -> None:
    """Pure document owner: state/workflow stage consistency.

    The filesystem adapter ``_check_state_workflow_consistency`` passes the
    already-loaded state and workflow text; Task 6.4's read-only seam passes
    facts preloaded by ``ObservedReadSession``.
    """
    if state is None or workflow_text is None:
        return
    statuses = parse_stage_progress(workflow_text)
    completed = set(state.get("stages_completed", []))
    for stage in sorted(completed):
        status = statuses.get(stage)
        if status in {"pending", "in_progress"}:
            result.fail(
                code="STATE_WORKFLOW_STAGE_CONFLICT",
                message=(
                    f"{stage} is completed in state.json but {status} "
                    "in research_workflow.md"
                ),
                path="research_workflow.md",
                evidence=f"state.json stages_completed includes {stage}",
            )
    current_stage = state.get("current_stage")
    if (
        current_stage == "stage_6"
        and statuses.get("stage_5") in {"pending", "in_progress"}
    ):
        result.fail(
            code="STATE_WORKFLOW_STAGE_CONFLICT",
            message=(
                "state.json current_stage is stage_6 but workflow Stage 5 "
                "is not complete"
            ),
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
    if not (workspace / "search_log.jsonl").exists():
        return set(), False
    try:
        records = tuple(
            record for _line_number, record in iter_jsonl_records(workspace / "search_log.jsonl")
        )
    except (json.JSONDecodeError, ValueError):
        return set(), False
    return _search_facts_from_records(records)


def _search_facts_from_records(
    records: tuple[dict, ...],
) -> tuple[set[str], bool]:
    """Pure fact owner: derive valid search loop coverage from parsed records."""
    loop_ids: set[str] = set()
    has_any_valid = False
    for record in records:
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
    return loop_ids, has_any_valid


_REVISIT_QUERY_VARIATION_DIMENSIONS = frozenset(
    {
        "source",
        "operator",
        "language",
        "time_window",
        "evidence_hypothesis",
    }
)
_SEARCH_LOOP_ID_RE = re.compile(r"^loop_([1-9][0-9]*)$")


def _derive_revisit_query_replay_issues(
    cycle: dict,
    search_records: tuple[dict, ...],
) -> tuple[RevisitIssue, ...]:
    """Derive exact post-boundary query-replay issues from preloaded facts."""
    boundary = cycle["intake"]["workspace_boundary"][
        "max_existing_loop_number"
    ]

    def is_post_boundary(record: dict) -> bool:
        loop_id = record.get("loop_id")
        match = _SEARCH_LOOP_ID_RE.fullmatch(loop_id) if isinstance(loop_id, str) else None
        return match is not None and int(match.group(1)) > boundary

    historical_queries: set[str] = set()
    historical_dead_ends: set[str] = set()
    for record in search_records:
        if is_post_boundary(record):
            continue
        query = record.get("query")
        if isinstance(query, str):
            historical_queries.add(query)
        dead_ends = record.get("dead_ends")
        if not isinstance(dead_ends, list):
            continue
        for dead_end in dead_ends:
            if not isinstance(dead_end, dict):
                continue
            dead_end_query = dead_end.get("query")
            if isinstance(dead_end_query, str):
                historical_dead_ends.add(dead_end_query)

    issues: list[RevisitIssue] = []
    for record in search_records:
        if not is_post_boundary(record):
            continue
        query = record.get("query")
        is_replay = isinstance(query, str) and (
            query in historical_queries or query in historical_dead_ends
        )
        has_dimension = "variation_dimension" in record
        has_reason = "variation_reason" in record
        dimension = record.get("variation_dimension")
        reason = record.get("variation_reason")
        valid_explanation = (
            is_replay
            and has_dimension
            and has_reason
            and isinstance(dimension, str)
            and dimension in _REVISIT_QUERY_VARIATION_DIMENSIONS
            and isinstance(reason, str)
            and bool(reason.strip())
        )
        if valid_explanation or (not is_replay and not has_dimension and not has_reason):
            continue

        loop_id = record.get("loop_id")
        if is_replay:
            message = (
                "exact prior-query or dead-end replay requires an allowed "
                "variation_dimension and non-empty variation_reason"
            )
        else:
            message = (
                "variation fields are allowed only on an exact prior-query "
                "or dead-end replay"
            )
        issues.append(
            RevisitIssue(
                "REVISIT_QUERY_REPLAY_UNEXPLAINED",
                "search_log.jsonl",
                message,
                f"loop_id={loop_id!r}; query={query!r}",
            )
        )
    return tuple(issues)


def _revisit_review_lifecycle_coherent(
    frontier: dict,
    review_decision: dict,
    *,
    bound_at: str,
) -> bool:
    lifecycle = frontier.get("lifecycle", [])
    if not lifecycle or not isinstance(lifecycle[-1], dict):
        return False
    final_transition = lifecycle[-1]
    return (
        frontier.get("status") == final_transition.get("to")
        and final_transition.get("to") == review_decision.get("decision")
        and isinstance(final_transition.get("ts"), str)
        and final_transition["ts"] > bound_at
        and final_transition.get("at_loop") == review_decision.get("at_loop")
    )


def _derive_revisit_frontier_floor_issues(
    workspace: Path,
    cycle: dict,
    registry: dict,
    ledger_text: str,
    dispatch_records: list[dict],
) -> tuple[RevisitIssue, ...]:
    """Filesystem adapter: derives search-coverage facts, then delegates.

    Task 6.4's read-only seam passes preloaded facts to
    ``_derive_revisit_frontier_floor_issues_from_facts``.
    """
    covered_search_loops, _ = _valid_search_coverage(workspace)
    return _derive_revisit_frontier_floor_issues_from_facts(
        cycle=cycle,
        registry=registry,
        ledger_text=ledger_text,
        dispatch_records=tuple(dispatch_records),
        covered_search_loops=frozenset(covered_search_loops),
    )


@dataclass(frozen=True)
class _RevisitFrontierBindingFacts:
    path: str
    binding_issue: RevisitIssue | None
    progress_available: bool
    loop_issue: RevisitIssue | None
    search_issue: RevisitIssue | None
    dispatch_issues: tuple[RevisitIssue, ...]
    review_issue: RevisitIssue | None


@dataclass(frozen=True)
class _RevisitFrontierFacts:
    preparation_issue: RevisitIssue | None
    bindings: tuple[_RevisitFrontierBindingFacts, ...]
    declared_binding_issues: tuple[RevisitIssue, ...]
    claim_floor_issues: tuple[RevisitIssue, ...]


def _prepare_revisit_frontier_facts(
    *,
    cycle: dict,
    registry: dict | None,
    ledger_facts: _RevisitLedgerFacts | None,
    dispatch_records: tuple[dict, ...] | None,
    covered_search_loops: frozenset[str] | None,
) -> _RevisitFrontierFacts:
    """Build one immutable frontier fact set for the four readiness owners."""
    declared_binding_issues = derive_frontier_requirements(cycle)
    if registry is None:
        return _RevisitFrontierFacts(
            preparation_issue=None,
            bindings=(),
            declared_binding_issues=declared_binding_issues,
            claim_floor_issues=(),
        )

    validate_registry(registry)
    frontiers = {
        frontier["id"]: frontier for frontier in registry["frontiers"]
    }
    registry_issue_by_path: dict[str, RevisitIssue] = {}
    for index, binding in enumerate(cycle["frontier_bindings"]):
        path = f"cycle.frontier_bindings[{index}]"
        frontier_id = binding["frontier_id"]
        frontier = frontiers.get(frontier_id)
        if frontier is None:
            registry_issue_by_path[path] = RevisitIssue(
                "REVISIT_FRONTIER_BINDING_INVALID",
                path,
                "bound frontier is absent from the validated registry",
                frontier_id,
            )
            continue
        legality_issue = derive_frontier_binding_legality_issue(
            cycle,
            binding,
            frontier,
            path=path,
        )
        if legality_issue is not None:
            registry_issue_by_path[path] = legality_issue

    preparation_issue = None
    progress_available = ledger_facts is not None
    live_loop_counts: dict[str, int] = {}
    headers = list(ledger_facts.headers) if ledger_facts is not None else []
    if ledger_facts is not None:
        known_frontier_ids = frozenset(frontiers)
        unknown_frontier_ids = tuple(
            sorted(
                {
                    frontier_id
                    for _loop_number, frontier_id in headers
                    if frontier_id not in known_frontier_ids
                }
            )
        )
        if unknown_frontier_ids:
            preparation_issue = RevisitIssue(
                "REVISIT_FRONTIER_BINDING_INVALID",
                "evidence_ledger.md",
                "ledger loop header references an unknown frontier",
                ", ".join(unknown_frontier_ids),
            )
            progress_available = False
        else:
            for _loop_number, frontier_id in headers:
                live_loop_counts[frontier_id] = (
                    live_loop_counts.get(frontier_id, 0) + 1
                )

    boundary = cycle["intake"]["workspace_boundary"][
        "max_existing_loop_number"
    ]
    binding_facts: list[_RevisitFrontierBindingFacts] = []
    failed_binding_paths: set[str] = set()
    for index, binding in enumerate(cycle["frontier_bindings"]):
        path = f"cycle.frontier_bindings[{index}]"
        frontier_id = binding["frontier_id"]
        frontier = frontiers.get(frontier_id)
        binding_issue = registry_issue_by_path.get(path)
        if binding_issue is not None:
            failed_binding_paths.add(path)
            binding_facts.append(
                _RevisitFrontierBindingFacts(
                    path=path,
                    binding_issue=binding_issue,
                    progress_available=False,
                    loop_issue=None,
                    search_issue=None,
                    dispatch_issues=(),
                    review_issue=None,
                )
            )
            continue

        if not progress_available:
            binding_facts.append(
                _RevisitFrontierBindingFacts(
                    path=path,
                    binding_issue=None,
                    progress_available=False,
                    loop_issue=None,
                    search_issue=None,
                    dispatch_issues=(),
                    review_issue=None,
                )
            )
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
        loop_issue = None
        if len(loop_ids) < 3 or live_loop_count < baseline_loop_count + 3:
            suffix = (
                "; retire this incomplete cycle through abort"
                if frontier.get("status") == "Retired"
                else ""
            )
            loop_issue = RevisitIssue(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                path,
                "bound frontier requires at least three distinct "
                "post-boundary ledger loops and a live loop count at least "
                f"baseline+3; found post-boundary={len(loop_ids)}, "
                f"baseline={baseline_loop_count}, live={live_loop_count}{suffix}",
                ", ".join(loop_ids),
            )

        missing_search = (
            tuple(
                loop_id
                for loop_id in loop_ids
                if loop_id not in covered_search_loops
            )
            if covered_search_loops is not None
            else ()
        )
        search_issue = (
            RevisitIssue(
                "REVISIT_SEARCH_FLOOR_MISSING",
                path,
                "every post-boundary frontier loop requires a valid search record",
                ", ".join(missing_search),
            )
            if missing_search
            else None
        )

        dispatch_issues: list[RevisitIssue] = []
        role_requirements = (
            ()
            if dispatch_records is None
            else (
                ("frontier_scout", "REVISIT_SCOUT_FLOOR_MISSING"),
                ("challenge_probe", "REVISIT_CHALLENGE_FLOOR_MISSING"),
            )
        )
        for role_slug, code in role_requirements:
            missing_role = tuple(
                loop_id
                for loop_id in loop_ids
                if not _has_exact_revisit_role_delivery_from_facts(
                    dispatch_records,
                    loop_id,
                    role_slug,
                )
            )
            if missing_role:
                dispatch_issues.append(
                    RevisitIssue(
                        code,
                        path,
                        "every post-boundary frontier loop requires delivered "
                        f"{role_slug} work",
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
            and _revisit_review_lifecycle_coherent(
                frontier,
                matching_reviews[-1],
                bound_at=binding["bound_at"],
            )
        )
        review_issue = (
            None
            if review_complete
            else RevisitIssue(
                "REVISIT_REVIEW_FLOOR_MISSING",
                path,
                "bound frontier requires a post-binding review that leaves Continued or review-based Retired",
                (
                    f"baseline={baseline_reviews}; "
                    f"current={frontier.get('review_count', 0)}"
                ),
            )
        )
        if (
            loop_issue is not None
            or search_issue is not None
            or dispatch_issues
            or review_issue is not None
        ):
            failed_binding_paths.add(path)
        binding_facts.append(
            _RevisitFrontierBindingFacts(
                path=path,
                binding_issue=None,
                progress_available=True,
                loop_issue=loop_issue,
                search_issue=search_issue,
                dispatch_issues=tuple(dispatch_issues),
                review_issue=review_issue,
            )
        )

    bound_claim_ids = {
        claim_id
        for binding in cycle["frontier_bindings"]
        for claim_id in binding["claim_ids"]
    }
    claim_floor_issues: list[RevisitIssue] = []
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
            claim_floor_issues.append(
                RevisitIssue(
                    "REVISIT_FRONTIER_BINDING_INVALID",
                    f"cycle.claim_resolutions[{claim_id}]",
                    "claim has no binding that independently passes every research floor",
                    claim_id,
                )
            )

    return _RevisitFrontierFacts(
        preparation_issue=preparation_issue,
        bindings=tuple(binding_facts),
        declared_binding_issues=declared_binding_issues,
        claim_floor_issues=tuple(claim_floor_issues),
    )


def _project_binding_registry_issue(
    binding: _RevisitFrontierBindingFacts,
) -> tuple[RevisitIssue, ...]:
    return (binding.binding_issue,) if binding.binding_issue is not None else ()


def _project_binding_loop_issue(
    binding: _RevisitFrontierBindingFacts,
) -> tuple[RevisitIssue, ...]:
    if not binding.progress_available or binding.loop_issue is None:
        return ()
    return (binding.loop_issue,)


def _project_binding_review_issue(
    binding: _RevisitFrontierBindingFacts,
) -> tuple[RevisitIssue, ...]:
    if not binding.progress_available or binding.review_issue is None:
        return ()
    return (binding.review_issue,)


def _project_binding_search_issue(
    binding: _RevisitFrontierBindingFacts,
) -> tuple[RevisitIssue, ...]:
    if not binding.progress_available or binding.search_issue is None:
        return ()
    return (binding.search_issue,)


def _project_binding_dispatch_issues(
    binding: _RevisitFrontierBindingFacts,
) -> tuple[RevisitIssue, ...]:
    if not binding.progress_available:
        return ()
    return binding.dispatch_issues


def _derive_revisit_registry_issues_from_facts(
    facts: _RevisitFrontierFacts,
) -> tuple[RevisitIssue, ...]:
    return tuple(
        issue
        for binding in facts.bindings
        for issue in _project_binding_registry_issue(binding)
    )


def _derive_revisit_frontier_progress_issues_from_facts(
    facts: _RevisitFrontierFacts,
) -> tuple[RevisitIssue, ...]:
    if facts.preparation_issue is not None:
        issues: list[RevisitIssue] = [facts.preparation_issue]
    else:
        issues = []
    for binding in facts.bindings:
        issues.extend(_project_binding_loop_issue(binding))
        issues.extend(_project_binding_review_issue(binding))
    issues.extend(facts.declared_binding_issues)
    issues.extend(facts.claim_floor_issues)
    return tuple(issues)


def _derive_revisit_search_floor_issues_from_facts(
    facts: _RevisitFrontierFacts,
) -> tuple[RevisitIssue, ...]:
    return tuple(
        issue
        for binding in facts.bindings
        for issue in _project_binding_search_issue(binding)
    )


def _derive_revisit_dispatch_floor_issues_from_facts(
    facts: _RevisitFrontierFacts,
) -> tuple[RevisitIssue, ...]:
    return tuple(
        issue
        for binding in facts.bindings
        for issue in _project_binding_dispatch_issues(binding)
    )


def _derive_revisit_frontier_floor_issues_from_facts(
    *,
    cycle: dict,
    registry: dict,
    ledger_text: str,
    dispatch_records: tuple[dict, ...],
    covered_search_loops: frozenset[str],
) -> tuple[RevisitIssue, ...]:
    """Compatibility adapter preserving the existing composite issue order."""
    try:
        ledger_facts = _parse_revisit_ledger_facts(ledger_text)
    except ValueError as exc:
        return (
            RevisitIssue(
                "REVISIT_FRONTIER_BINDING_INVALID",
                "evidence_ledger.md",
                str(exc),
            ),
        )
    facts = _prepare_revisit_frontier_facts(
        cycle=cycle,
        registry=registry,
        ledger_facts=ledger_facts,
        dispatch_records=dispatch_records,
        covered_search_loops=covered_search_loops,
    )
    if facts.preparation_issue is not None:
        return (facts.preparation_issue,)
    issues: list[RevisitIssue] = []
    for binding in facts.bindings:
        binding_issues = _project_binding_registry_issue(binding)
        issues.extend(binding_issues)
        if binding_issues:
            continue
        loop_issues = _project_binding_loop_issue(binding)
        issues.extend(loop_issues)
        if loop_issues:
            continue
        issues.extend(_project_binding_search_issue(binding))
        issues.extend(_project_binding_dispatch_issues(binding))
        issues.extend(_project_binding_review_issue(binding))
    issues.extend(facts.declared_binding_issues)
    issues.extend(facts.claim_floor_issues)
    return tuple(issues)


def _has_exact_revisit_role_delivery(
    workspace: Path,
    records: list[dict],
    loop_id: str,
    required_role_slug: str,
) -> bool:
    """Filesystem adapter retained for ordinary-target callers."""
    return _has_exact_revisit_role_delivery_from_facts(
        tuple(records), loop_id, required_role_slug
    )


def _has_exact_revisit_role_delivery_from_facts(
    records: tuple[dict, ...],
    loop_id: str,
    required_role_slug: str,
) -> bool:
    """Pure fact owner: does a delivered dispatch record match role+loop?"""
    for record in records:
        if str(record.get("loop_id", "")) != loop_id:
            continue
        if not _dispatch_record_counts_as_delivery(record):
            continue
        normalized_path = _normalize_delivery_path_from_facts(
            record.get("delivery_path", "")
        )
        if (
            normalized_path is None
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


def _normalize_delivery_path_from_facts(delivery_path) -> str | None:
    """Normalize a delivery_path without filesystem access.

    Mirrors ``_normalize_delivery_path`` for already-resolved relative POSIX
    paths. Rejects absolute paths and paths escaping the workspace.
    """
    raw = str(delivery_path)
    try:
        candidate = Path(raw)
    except (ValueError, TypeError):
        return None
    if candidate.is_absolute():
        return None
    parts = candidate.parts
    if ".." in parts:
        return None
    normalized = candidate.as_posix()
    if normalized in {"", "."}:
        return None
    return normalized


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
    """Filesystem adapter: loads dispatch records and worker-output facts.

    Task 6.4's read-only seam passes preloaded facts to
    ``_check_dispatch_documents``.
    """
    worker_output_paths = tuple(
        path.relative_to(workspace).as_posix()
        for path in find_worker_outputs(workspace)
    )
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        return list(
            _check_dispatch_documents(
                records=None,
                workflow_text=workflow_text,
                profile=profile,
                worker_output_paths=worker_output_paths,
                delivered_payloads=(),
                result=result,
            )
        )
    records = _read_dispatch_records(workspace, result)
    if records is None:
        return []
    delivered_payloads: list[tuple[str, bytes | None]] = []
    seen_delivered: set[str] = set()
    for record in records:
        if record.get("status") != "delivered":
            continue
        raw_path = record.get("delivery_path", "")
        if not raw_path:
            continue
        normalized = _normalize_delivery_path(workspace, raw_path)
        if normalized is None or normalized in seen_delivered:
            continue
        seen_delivered.add(normalized)
        try:
            payload = (workspace / normalized).read_bytes()
        except OSError:
            payload = None
        delivered_payloads.append((normalized, payload))
    return list(
        _check_dispatch_documents(
            records=tuple(records),
            workflow_text=workflow_text,
            profile=profile,
            worker_output_paths=worker_output_paths,
            delivered_payloads=tuple(delivered_payloads),
            result=result,
            workspace=workspace,
        )
    )


def _check_dispatch_documents(
    *,
    records: tuple[dict, ...] | None,
    workflow_text: str | None,
    profile: ContractProfile,
    worker_output_paths: tuple[str, ...],
    delivered_payloads: tuple[tuple[str, bytes | None], ...],
    result: ContractResult,
    workspace: Path | None = None,
    lexical_workspace: Path | None = None,
) -> tuple[dict, ...]:
    """Pure document owner: dispatch delivery semantics over preloaded facts.

    ``records`` is the parsed dispatch_log.jsonl content, or ``None`` if the
    log was missing or unparseable. ``delivered_payloads`` maps normalized
    delivery paths to their bytes (``None`` if the file is absent) and is used
    instead of filesystem existence checks.

    ``workspace`` is the canonical root used to read the preloaded facts.
    ``lexical_workspace`` preserves the caller's root for absolute delivery
    paths; when omitted it is the same as ``workspace``. When ``workspace`` is
    omitted, only already-relative POSIX paths are accepted.
    """
    _normalize = (
        (
            lambda delivery_path: _normalize_delivery_path(
                lexical_workspace or workspace,
                delivery_path,
                resolved_workspace=workspace,
            )
        )
        if workspace is not None
        else _normalize_delivery_path_from_facts
    )
    workflow_claims_delivery = _workflow_claims_subagent_delivery(workflow_text)
    if records is None:
        if not worker_output_paths and not workflow_claims_delivery:
            return ()
        result.fail(
            code="DISPATCH_PROOF_MISSING" if workflow_claims_delivery else "DISPATCH_LOG_MISSING",
            message="worker outputs and workflow dispatch claims require dispatch_log.jsonl or approved degraded-mode records",
            path="dispatch_log.jsonl",
            evidence=_dispatch_missing_evidence_from_facts(worker_output_paths, workflow_claims_delivery),
        )
        return ()
    if workflow_claims_delivery and not any(
        _dispatch_record_counts_as_delivery(record) for record in records
    ):
        result.fail(
            code="DISPATCH_PROOF_MISSING",
            message="workflow Subagent Dispatch Log claims delivered subagent work without machine delivery proof",
            path="dispatch_log.jsonl",
            evidence="no delivered host/native subagent record or approved degraded delivery record",
        )
    payload_by_path: dict[str, bytes | None] = dict(delivered_payloads)
    for duplicate_path, dispatch_ids in _duplicate_delivered_paths(
        records,
        workspace=workspace,
        lexical_workspace=lexical_workspace,
    ).items():
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
                normalized_delivery_path = _normalize(record.get("delivery_path", ""))
                payload = payload_by_path.get(normalized_delivery_path) if normalized_delivery_path else None
                if normalized_delivery_path is None or payload is None:
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
                    role_issue = _dispatch_role_delivery_issue(
                        record, normalized_delivery_path, profile.mode
                    )
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
        for normalized_path in [_normalize(record.get("delivery_path", ""))]
        if normalized_path is not None
    }
    for rel in worker_output_paths:
        if _is_revisit_main_thread_rerun(rel):
            continue
        if rel not in delivered_paths:
            result.fail(
                code="WORKER_OUTPUT_WITHOUT_DISPATCH",
                message="worker output has no delivered dispatch record",
                path=rel,
                evidence="dispatch_log.jsonl delivery_path mismatch",
            )
    return records


def _duplicate_delivered_paths(
    records: tuple[dict, ...],
    *,
    workspace: Path | None = None,
    lexical_workspace: Path | None = None,
) -> dict[str, list[str]]:
    _normalize = (
        (
            lambda delivery_path: _normalize_delivery_path(
                lexical_workspace or workspace,
                delivery_path,
                resolved_workspace=workspace,
            )
        )
        if workspace is not None
        else _normalize_delivery_path_from_facts
    )
    dispatch_ids_by_path: dict[str, list[str]] = {}
    for record in records:
        if record.get("status") != "delivered":
            continue
        if not record.get("delivery_path"):
            continue
        normalized_path = _normalize(record.get("delivery_path", ""))
        if normalized_path is None:
            continue
        dispatch_ids_by_path.setdefault(normalized_path, []).append(str(record.get("dispatch_id", "")))
    return {
        path: dispatch_ids
        for path, dispatch_ids in dispatch_ids_by_path.items()
        if len(dispatch_ids) > 1
    }


def _dispatch_missing_evidence(
    worker_outputs: list[Path], workflow_claims_delivery: bool
) -> str:
    evidence = []
    if worker_outputs:
        evidence.append(f"{len(worker_outputs)} worker output file(s)")
    if workflow_claims_delivery:
        evidence.append("research_workflow.md Subagent Dispatch Log delivered row")
    return "; ".join(evidence)


def _dispatch_missing_evidence_from_facts(
    worker_output_paths: tuple[str, ...], workflow_claims_delivery: bool
) -> str:
    evidence = []
    if worker_output_paths:
        evidence.append(f"{len(worker_output_paths)} worker output file(s)")
    if workflow_claims_delivery:
        evidence.append("research_workflow.md Subagent Dispatch Log delivered row")
    return "; ".join(evidence)


def _normalize_delivery_path(
    workspace: Path,
    delivery_path,
    *,
    resolved_workspace: Path | None = None,
) -> str | None:
    """Normalize a dispatch delivery_path to a workspace-relative posix string.

    Guides pass workers the same absolute ``{WORKSPACE}/...`` path they write
    to, so dispatch_log.jsonl often records absolute paths. Worker outputs are
    compared as workspace-relative paths. Relative paths may also include
    harmless ``./`` or ``..`` segments. Paths that escape the workspace are not
    accepted as delivered outputs. The returned identity stays lexical so an
    observed-read session can detect symbolic-link retargeting; resolution is
    used only to reject targets outside the workspace.
    """
    raw = str(delivery_path)
    try:
        lexical_workspace = Path(os.path.abspath(workspace))
        candidate = Path(raw)
        if candidate.is_absolute():
            lexical_candidate = Path(os.path.abspath(candidate))
        else:
            lexical_candidate = Path(
                os.path.abspath(lexical_workspace / candidate)
            )
        lexical_relative = lexical_candidate.relative_to(lexical_workspace)

        canonical_workspace = (resolved_workspace or lexical_workspace).resolve()
        resolved_candidate = (canonical_workspace / lexical_relative).resolve()
        resolved_candidate.relative_to(canonical_workspace)
        return lexical_relative.as_posix()
    except (TypeError, ValueError, OSError):
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


def _delivered_roles_by_path(workspace: Path, profile_mode: str) -> dict[str, str]:
    """Filesystem adapter retained for ordinary-target callers."""
    dispatch_path = workspace / "dispatch_log.jsonl"
    if not dispatch_path.exists():
        return {}
    try:
        records = tuple(
            record for _line_number, record in iter_jsonl_records(dispatch_path)
        )
    except (json.JSONDecodeError, ValueError):
        return {}
    return _delivered_roles_by_path_from_facts(records, profile_mode)


def _delivered_roles_by_path_from_facts(
    records: tuple[dict, ...], profile_mode: str
) -> dict[str, str]:
    """Pure fact owner: map delivered paths to normalized role slugs."""
    roles_by_path: dict[str, str] = {}
    seen_paths: set[str] = set()
    for record in records:
        if not _dispatch_record_counts_as_delivery(record):
            continue
        normalized_path = _normalize_delivery_path_from_facts(record.get("delivery_path", ""))
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
    """Filesystem adapter: loads worker-output texts and delivered roles.

    Task 6.4's read-only seam passes preloaded facts to
    ``_check_worker_output_documents``.
    """
    delivered_roles = _delivered_roles_by_path(workspace, profile.mode)
    outputs: list[tuple[str, str]] = []
    for path in find_worker_outputs(workspace):
        rel = path.relative_to(workspace).as_posix()
        text = path.read_text(encoding="utf-8")
        outputs.append((rel, text))
    _check_worker_output_documents(
        outputs=tuple(outputs),
        delivered_roles=tuple(delivered_roles.items()),
        registered_source_ids=registered_source_ids(workspace),
        profile=profile,
        result=result,
    )


def _check_worker_output_documents(
    *,
    outputs: tuple[tuple[str, str], ...],
    delivered_roles: tuple[tuple[str, str], ...] | None,
    registered_source_ids: frozenset[str] | None,
    profile: ContractProfile,
    result: ContractResult,
) -> None:
    """Pure document owner: worker-output semantics over preloaded facts."""
    delivered_roles_map = dict(delivered_roles or ())
    for rel, text in outputs:
        if _is_revisit_main_thread_rerun(rel):
            continue
        candidate_roles = _candidate_worker_roles_for_output(rel)
        role = _worker_role_for_output(rel, delivered_roles_map, candidate_roles)

        if not any(
            has_required_output_marker(text, marker)
            for marker in _required_output_markers_for_output(role, candidate_roles)
        ):
            result.fail(
                code="WORKER_METHOD_CARDS_MISSING",
                message="worker output must declare Method cards loaded",
                path=rel,
            )
        has_trace = has_source_trace(
            text, candidate_roles[0]
        ) or (
            registered_source_ids is not None
            and _has_registered_source_id_reference_from_facts(
                text, registered_source_ids
            )
        )
        if not has_trace and registered_source_ids is not None:
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


def _has_registered_source_id_reference_from_facts(
    text: str, registered_source_ids: frozenset[str]
) -> bool:
    """Pure fact owner: source-cache trace without filesystem access."""
    cited = set(source_ids_in_text(text))
    if not cited:
        return False
    return bool(cited & registered_source_ids)


def _candidate_worker_roles_for_output(rel: str):
    return tuple(role for role in all_worker_roles() if role.matches_delivery_path(rel))


def _is_revisit_main_thread_rerun(relative_path: str) -> bool:
    return bool(
        re.fullmatch(
            r"redteam/RC-[0-9]{4}_(?:round[1-9][0-9]*_defense|thesis_revision)\.md",
            relative_path,
        )
    )


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
        expected_metadata = None
        if revision["cycle_id"] is not None:
            cycle = _check_current_revision_cycle(workspace, revision, result)
            if cycle is None:
                return
            expected_metadata = render_report_metadata(cycle)
        result.extend(
            evaluate_specific_ticker_report(
                workspace,
                revision["report_path"],
                expected_sha256=revision["report_sha256"],
                expected_metadata=expected_metadata,
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
) -> dict | None:
    cycle_id = revision["cycle_id"]
    try:
        cycle = load_cycle(workspace, cycle_id)
    except (OSError, RevisitContractError) as exc:
        result.fail(
            code="CURRENT_REPORT_CYCLE_INVALID",
            message=str(exc),
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return None
    if cycle["status"] != "completed":
        result.fail(
            code="CURRENT_REPORT_CYCLE_INVALID",
            message="current report must originate from an immutable completed cycle",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return None

    if not _current_revision_matches_completed_cycle(revision, cycle):
        result.fail(
            code="CURRENT_REPORT_LINEAGE_MISMATCH",
            message="current revision does not exactly match its completed cycle candidate lineage",
            path=f"revisit_cycles/{cycle_id}.json",
        )
        return None
    return cycle


def _current_revision_matches_completed_cycle(
    revision: dict,
    cycle: dict,
) -> bool:
    """Return whether one current revision exactly projects its completed cycle."""
    candidate = cycle["report_candidate"]
    assessment = cycle["decision_assessment"]
    base_revision = cycle["intake"]["base_revision"]
    return bool(
        cycle["status"] == "completed"
        and cycle["cycle_id"] == revision["cycle_id"]
        and cycle["candidate_revision_id"] == revision["revision_id"]
        and isinstance(candidate, dict)
        and candidate["revision_id"] == revision["revision_id"]
        and candidate["revision_of"] == revision["revision_of"]
        and candidate["report_path"] == revision["report_path"]
        and candidate["report_sha256"] == revision["report_sha256"]
        and base_revision["revision_id"] == revision["revision_of"]
        and isinstance(assessment, dict)
        and assessment["new_action_class"] == revision["action_class"]
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
