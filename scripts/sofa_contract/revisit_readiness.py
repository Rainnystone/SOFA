"""Single read-only revisit readiness seam (Task 6.4).

``evaluate_revisit_readiness`` is the ONLY thirteen-row readiness surface: the
named-selection (``evaluate_revisit_report``), profile-target
(``evaluate_workspace`` with ``target="revisit_report"``) and CLI ``check``
routes all delegate to it. All semantic filesystem access in the readiness call
graph flows through one ``ObservedReadSession`` so that ``freeze()`` captures
every authority actually consumed by the semantic owners, and a single
``require_unchanged()`` boundary recheck translates any drift to
``REVISIT_AUTHORITY_DRIFT``.

The thirteen-row plan is a CLOSED, ordered list (NOT a plugin registry). The
``_REQUIREMENT_OWNERS`` mapping and the explicit ``_evaluate_*`` dispatch in
``_run_readiness_plan`` must stay in lock-step with ``REVISIT_REQUIREMENT_IDS``;
``_verify_plan_shape`` fails loudly if a requirement id is missing, duplicated,
or owned by zero/multiple rows.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from workspace_contract import all_worker_output_directories, is_main_thread_artifact

from .result import ContractProfile, ContractResult

from .workspace import (
    iter_jsonl_records,
    parse_stage_progress,
)

try:
    from framing_contract import FramingContractError, evaluate_contract
    from framing_contract.model import normalize_contract
except ImportError:
    from scripts.framing_contract import FramingContractError, evaluate_contract
    from scripts.framing_contract.model import normalize_contract

try:
    from frontier_lifecycle import LifecycleError, validate_registry
except ImportError:
    from scripts.frontier_lifecycle import LifecycleError, validate_registry

try:
    from revisit_contract import (
        RevisitContractError,
        derive_claim_issues,
        derive_freshness_issues,
        evaluate_history,
        list_cycle_ids,
        mark_ready_for_report,
        persist_cycle,
        sha256_bytes,
        workspace_transaction,
    )
    from revisit_contract.model import validate_cycle, validate_pointer, with_audit
    from revisit_contract.store import RevisitPersistenceRollbackError
except ImportError:
    from scripts.revisit_contract import (
        RevisitContractError,
        derive_claim_issues,
        derive_freshness_issues,
        evaluate_history,
        list_cycle_ids,
        mark_ready_for_report,
        persist_cycle,
        sha256_bytes,
        workspace_transaction,
    )
    from scripts.revisit_contract.model import (
        validate_cycle,
        validate_pointer,
        with_audit,
    )
    from scripts.revisit_contract.store import RevisitPersistenceRollbackError

try:
    from revisit_contract.generation import (
        AuthorityDriftError,
        GenerationClosure,
        ObservedReadSession,
    )
except ImportError:
    from scripts.revisit_contract.generation import (
        AuthorityDriftError,
        GenerationClosure,
        ObservedReadSession,
    )

try:
    from source_cache import SOURCE_INDEX_FILENAME
    from source_cache.store import evaluate_index_documents, plan_index_document
except ImportError:
    from scripts.source_cache import SOURCE_INDEX_FILENAME
    from scripts.source_cache.store import evaluate_index_documents, plan_index_document

from .evaluate import (  # noqa: E402
    TICKER_REPORT_REQUIREMENTS,
    _check_dispatch_documents,
    _check_state_workflow_documents,
    _check_worker_output_documents,
    _derive_revisit_frontier_floor_issues_from_facts,
    _dispatch_record_counts_as_delivery,
    _evaluate_specific_ticker_report_document,
    _has_exact_single_metadata_block,
    _missing_dispatch_delivery_fields,
    _missing_final_report_requirements,
    _normalize_delivery_path,
    _normalize_delivery_path_from_facts,
    _search_facts_from_records,
)

REVISIT_REQUIREMENT_IDS = (
    "core_state_workflow",
    "global_cycle_history",
    "intake_provenance",
    "trigger_evidence",
    "claim_freshness",
    "frontier_registry",
    "frontier_research_floor",
    "search_coverage",
    "dispatch_delivery",
    "worker_outputs",
    "source_cache",
    "generation_closure",
    "route_and_effect_parity",
)


class ReadinessPlanError(ValueError):
    """Raised when the thirteen-row plan is not exactly complete and ordered."""


@dataclass(frozen=True)
class _PreparedRevisitReadiness:
    """Module-private prepared-facts container.

    Task 6.5 will reuse the preparation flow for the check path; for Task 6.4
    this stays internal to ``revisit_readiness`` but is structured so 6.5 can
    call the same ``_prepare_revisit_readiness`` helper.
    """

    result: ContractResult
    cycle_id: str | None
    cycle: dict | None
    cycle_sha256: str | None
    closure: GenerationClosure


class RevisitCheckEffect(str, Enum):
    """The three atomic effects of ``check_revisit_readiness``.

    * ``BLOCKED`` -- semantic or drift failure; zero writes.
    * ``TRANSITIONED`` -- active->ready; exactly one ``check`` audit entry.
    * ``UNCHANGED_READY`` -- already ready; byte-preserving no-op (no audit).
    """

    BLOCKED = "blocked"
    TRANSITIONED = "transitioned"
    UNCHANGED_READY = "unchanged_ready"


@dataclass(frozen=True)
class RevisitCheckOutcome:
    """Result of ``check_revisit_readiness``.

    ``cycle_id`` is the globally selected eligible id, or ``None`` when
    malformed history prevents selection.
    """

    result: ContractResult
    cycle_id: str | None
    effect: RevisitCheckEffect


# Canonical UTC seconds: ``YYYY-MM-DDTHH:MM:SSZ``. Invalid caller timestamps
# are programming/API errors (raised, never translated to a ContractResult).
_CANONICAL_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)


def _validate_canonical_timestamp(timestamp: str) -> str:
    if not isinstance(timestamp, str) or _CANONICAL_TIMESTAMP_RE.fullmatch(
        timestamp
    ) is None:
        raise ValueError(
            "timestamp must be canonical UTC seconds (YYYY-MM-DDTHH:MM:SSZ): "
            f"{timestamp!r}"
        )
    return timestamp


def _json_from_bytes(payload: bytes | None, path: str) -> Any:
    if payload is None:
        raise RevisitContractError(f"required authority is missing: {path}")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError(f"malformed JSON authority: {path}") from exc


def _iter_jsonl_bytes(payload: bytes | None) -> tuple[tuple[int, dict[str, Any]], ...]:
    if payload is None:
        return ()
    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} JSONL record must be an object")
        records.append((line_number, value))
    return tuple(records)


def _check_intake_authorities_from_facts(
    cycle: dict,
    payload_by_path: dict[str, bytes],
    result: ContractResult,
) -> None:
    """Validate framing contract and selected-claim source artifacts from bytes."""
    framing = cycle["intake"]["framing"]
    framing_path = framing["path"]
    framing_payload = payload_by_path.get(framing_path)
    try:
        if framing_payload is None:
            raise RevisitContractError(
                f"required authority is missing: {framing_path}"
            )
        if sha256_bytes(framing_payload) != framing["sha256"]:
            raise RevisitContractError(
                "framing contract bytes do not match registered sha256"
            )
        raw_contract = json.loads(framing_payload.decode("utf-8"))
        contract = normalize_contract(raw_contract)
        evaluation = evaluate_contract(contract, state_mode="ticker")
        if not evaluation.complete:
            details = "; ".join(
                f"{issue.code} {issue.field}: {issue.message}"
                for issue in evaluation.issues
            )
            raise RevisitContractError(f"framing contract is invalid: {details}")
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
        source_path = source_ref["path"]
        source_payload = payload_by_path.get(source_path)
        try:
            if source_payload is None:
                raise RevisitContractError(
                    f"required authority is missing: {source_path}"
                )
            if sha256_bytes(source_payload) != source_ref["sha256"]:
                raise RevisitContractError(
                    "selected claim source bytes do not match registered sha256"
                )
        except RevisitContractError as exc:
            result.fail(
                code="REVISIT_CYCLE_MALFORMED",
                message=str(exc),
                path=(
                    f"cycle.intake.selected_claims[{claim_index}].source_ref"
                ),
                evidence=claim["claim_id"],
            )


def _evidence_ref_valid_from_facts(
    reference: dict,
    workspace: Path,
    *,
    source_ids: frozenset[str],
    source_context_valid: bool,
    payload_by_path: dict[str, bytes],
) -> bool:
    if reference.get("kind") == "source":
        return (
            source_context_valid
            and str(reference.get("source_id", "")) in source_ids
        )
    normalized = _normalize_delivery_path(workspace, reference.get("path", ""))
    if normalized is None:
        return False
    payload = payload_by_path.get(normalized)
    if payload is None:
        return False
    return sha256_bytes(payload) == reference.get("sha256")


def _derive_current_report_sha256(pointer: dict) -> str | None:
    current = pointer["current_revision"]
    if current is None:
        return None
    return current.get("report_sha256")


def _check_current_report_from_facts(
    pointer: dict,
    cycle: dict,
    payload_by_path: dict[str, bytes],
    result: ContractResult,
) -> None:
    """Validate that the current report matches the cycle base revision."""
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
        report_path = current["report_path"]
        report_payload = payload_by_path.get(report_path)
        if report_payload is None:
            base_drift = True
        else:
            base_drift = base_drift or (
                sha256_bytes(report_payload) != current["report_sha256"]
            )
    if base_drift:
        result.fail(
            code="REVISIT_BASE_REPORT_DRIFT",
            message="cycle base revision or current report bytes differ from the registered pointer",
            path="cycle.intake.base_revision",
        )


def _evaluate_source_cache_from_session(
    session: ObservedReadSession,
) -> tuple:
    """Plan, read, and evaluate the source cache using the observed session.

    Returns ``(evaluation, source_ids, source_context_valid)``.
    """
    index_payload = session.read_optional(SOURCE_INDEX_FILENAME)
    plan = plan_index_document(index_payload)
    excerpt_payloads: list[tuple[str, bytes | None]] = []
    for excerpt_path in plan.excerpt_paths:
        excerpt_payloads.append(
            (excerpt_path, session.read_optional(excerpt_path))
        )
    source_entries = session.list_directory("sources", recursive=True, optional=True)
    source_files = tuple(
        entry.relative_path
        for entry in source_entries
        if entry.kind == "file"
    )
    evaluation = evaluate_index_documents(
        plan, tuple(excerpt_payloads), source_files
    )
    source_ids = frozenset(
        str(record["source_id"]) for record in evaluation.records
    )
    source_context_valid = not evaluation.issues
    return evaluation, source_ids, source_context_valid


def _load_worker_output_facts(
    session: ObservedReadSession,
) -> tuple[tuple[str, str], ...]:
    """Read every known worker-output directory member through the session."""
    outputs: list[tuple[str, str]] = []
    for dirname in all_worker_output_directories():
        entries = session.list_directory(dirname, recursive=False, optional=True)
        for entry in entries:
            if entry.kind != "file" or not entry.relative_path.endswith(".md"):
                continue
            if is_main_thread_artifact(entry.relative_path):
                continue
            payload = session.read_optional(entry.relative_path)
            if payload is None:
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            outputs.append((entry.relative_path, text))
    return tuple(outputs)


def _load_dispatch_facts(
    session: ObservedReadSession,
    workspace: Path,
    result: ContractResult,
) -> tuple[tuple[dict, ...] | None, tuple[tuple[str, bytes | None], ...]]:
    """Parse dispatch_log.jsonl and preload delivered payloads.

    Returns ``(records, delivered_payloads)``. A parse failure records
    ``DISPATCH_LOG_INVALID`` and returns ``(None, ())``.
    """
    payload = session.read_optional("dispatch_log.jsonl")
    if payload is None:
        return (), ()
    try:
        records = _iter_jsonl_bytes(payload)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        result.fail(
            code="DISPATCH_LOG_INVALID",
            message="dispatch_log.jsonl must be valid JSONL with one object per non-blank line",
            path="dispatch_log.jsonl",
            evidence=str(exc),
        )
        return None, ()
    record_tuple = tuple(record for _line_number, record in records)
    delivered_payloads: list[tuple[str, bytes | None]] = []
    seen: set[str] = set()
    for record in record_tuple:
        if record.get("status") != "delivered":
            continue
        raw_path = record.get("delivery_path", "")
        if not raw_path:
            continue
        normalized = _normalize_delivery_path(workspace, raw_path)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        delivered_payloads.append(
            (normalized, session.read_optional(normalized))
        )
    return record_tuple, tuple(delivered_payloads)


def _load_search_facts(
    session: ObservedReadSession,
) -> tuple[dict, ...]:
    payload = session.read_optional("search_log.jsonl")
    if payload is None:
        return ()
    try:
        return tuple(record for _line_number, record in _iter_jsonl_bytes(payload))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return ()


def _discover_eligible_cycle_id(
    history,
    result: ContractResult,
) -> str | None:
    """Return the sole eligible cycle id, or record a failure and return None."""
    if history.issues:
        for issue in history.issues:
            result.fail(
                code="REVISIT_CYCLE_MALFORMED",
                message=issue.message,
                path=issue.path,
                evidence=issue.evidence,
            )
        return None
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
        return None
    return eligible[0]


def _map_cycle_load_error(exc: RevisitContractError) -> str:
    """Preserve the historical special-case code for forbidden positive support."""
    message = str(exc)
    if "cannot be used as positive support" in message:
        return "REVISIT_CLAIM_SUPPORT_FORBIDDEN"
    return "REVISIT_CYCLE_MALFORMED"


def _prepare_revisit_readiness(
    session: ObservedReadSession,
    result: ContractResult,
    named_cycle_id: str | None,
) -> _PreparedRevisitReadiness:
    """Run the thirteen-row readiness plan and freeze the observed closure."""
    workspace = session._workspace

    # ------------------------------------------------------------------
    # Fact loading: core workspace authorities
    # ------------------------------------------------------------------
    state_payload = session.read_optional("state.json")
    workflow_payload = session.read_optional("research_workflow.md")
    state: dict | None = None
    workflow_text: str | None = None
    if state_payload is not None:
        try:
            state_value = json.loads(state_payload.decode("utf-8"))
            if isinstance(state_value, dict):
                state = state_value
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            result.fail(
                code="STATE_JSON_INVALID",
                message=f"state.json is not valid JSON: {exc}",
                path="state.json",
            )
    if workflow_payload is not None:
        try:
            workflow_text = workflow_payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            result.fail(
                code="RESEARCH_WORKFLOW_INVALID",
                message=f"research_workflow.md is not valid UTF-8: {exc}",
                path="research_workflow.md",
            )

    # Row 1: core_state_workflow
    # Preserve the historical revisit-ready state-gate codes:
    # missing/invalid/non-ticker state is a cycle malformed issue, Sector has its
    # own code, and state/workflow stage conflicts are reported when both docs are
    # present and valid.
    if state is None:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="revisit_report requires state.json with mode=ticker",
            path="state.json",
        )
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=None,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )

    mode = state.get("mode")
    if mode == "sector":
        result.fail(
            code="REVISIT_UNSUPPORTED_MODE",
            message="revisit_report is unavailable for Sector workspaces",
            path="state.json",
        )
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=None,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )

    if mode != "ticker":
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="revisit_report requires state.json with mode=ticker",
            path="state.json",
        )
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=None,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )

    if workflow_text is not None:
        _check_state_workflow_documents(state, workflow_text, result)

    # ------------------------------------------------------------------
    # Fact loading: global cycle history
    # ------------------------------------------------------------------
    pointer_payload = session.read_required("revisit_contract.json")
    pointer = validate_pointer(_json_from_bytes(pointer_payload, "revisit_contract.json"))
    cycle_entries = session.list_directory("revisit_cycles", recursive=False)
    cycle_payloads: list[tuple[str, bytes]] = []
    for entry in cycle_entries:
        if entry.kind != "file" or not entry.relative_path.endswith(".json"):
            continue
        cycle_id_from_name = Path(entry.relative_path).stem
        if not cycle_id_from_name:
            continue
        payload = session.read_optional(entry.relative_path)
        if payload is not None:
            cycle_payloads.append((cycle_id_from_name, payload))
    cycles: list[dict] = []
    for cycle_id_from_name, payload in sorted(cycle_payloads):
        try:
            cycle_value = _json_from_bytes(payload, f"revisit_cycles/{cycle_id_from_name}.json")
            cycle_value = validate_cycle(cycle_value)
            if cycle_value["cycle_id"] != cycle_id_from_name:
                raise RevisitContractError(
                    f"filename {cycle_id_from_name} does not match internal cycle_id {cycle_value['cycle_id']}"
                )
            cycles.append(cycle_value)
        except RevisitContractError as exc:
            result.fail(
                code=_map_cycle_load_error(exc),
                message=str(exc),
                path=f"revisit_cycles/{cycle_id_from_name}.json",
            )

    history = evaluate_history(pointer, cycles)

    # Row 2: global_cycle_history
    eligible_cycle_id = _discover_eligible_cycle_id(history, result)
    if eligible_cycle_id is None:
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=None,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )

    if named_cycle_id is not None and named_cycle_id != eligible_cycle_id:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=(
                f"named cycle {named_cycle_id} is not the sole globally eligible cycle "
                f"({eligible_cycle_id})"
            ),
            path="revisit_cycles",
            evidence=f"named={named_cycle_id}; eligible={eligible_cycle_id}",
        )
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=named_cycle_id,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )

    cycle_id = named_cycle_id or eligible_cycle_id
    cycle_payload = session.read_required(f"revisit_cycles/{cycle_id}.json")
    try:
        cycle_value = _json_from_bytes(cycle_payload, f"revisit_cycles/{cycle_id}.json")
        cycle = validate_cycle(cycle_value)
        if cycle["cycle_id"] != cycle_id:
            raise RevisitContractError(
                f"filename {cycle_id} does not match internal cycle_id {cycle['cycle_id']}"
            )
    except RevisitContractError as exc:
        result.fail(
            code=_map_cycle_load_error(exc),
            message=str(exc),
            path=f"revisit_cycles/{cycle_id}.json",
        )
        closure = session.freeze()
        return _PreparedRevisitReadiness(
            result=result,
            cycle_id=cycle_id,
            cycle=None,
            cycle_sha256=None,
            closure=closure,
        )
    cycle_sha256 = sha256_bytes(cycle_payload)

    # ------------------------------------------------------------------
    # Fact loading: source cache (consumed by trigger, claim, worker rows)
    # ------------------------------------------------------------------
    source_evaluation, source_ids, source_context_valid = (
        _evaluate_source_cache_from_session(session)
    )

    # Build a lookup of every artifact path referenced by the cycle.
    payload_by_path: dict[str, bytes] = {}
    current = pointer.get("current_revision")
    if current is not None:
        report_path = current["report_path"]
        report_payload = session.read_optional(report_path)
        if report_payload is not None:
            payload_by_path[report_path] = report_payload
    framing_path = cycle["intake"]["framing"]["path"]
    framing_payload = session.read_optional(framing_path)
    if framing_payload is not None:
        payload_by_path[framing_path] = framing_payload
    for claim in cycle["intake"]["selected_claims"]:
        path = claim["source_ref"]["path"]
        payload = session.read_optional(path)
        if payload is not None:
            payload_by_path[path] = payload
    for trigger in cycle["intake"]["triggers"]:
        for reference in trigger["evidence_refs"]:
            if reference.get("kind") != "artifact":
                continue
            path = reference.get("path", "")
            if not path:
                continue
            normalized = _normalize_delivery_path(workspace, path)
            if normalized is None:
                continue
            payload = session.read_optional(normalized)
            if payload is not None:
                payload_by_path[normalized] = payload
    for resolution in cycle["claim_resolutions"]:
        for field in ("current_evidence_refs", "counter_evidence_refs"):
            for reference in resolution[field]:
                if reference.get("kind") != "artifact":
                    continue
                path = reference.get("path", "")
                if not path:
                    continue
                normalized = _normalize_delivery_path(workspace, path)
                if normalized is None:
                    continue
                payload = session.read_optional(normalized)
                if payload is not None:
                    payload_by_path[normalized] = payload

    # Row 3: intake_provenance
    _check_intake_authorities_from_facts(cycle, payload_by_path, result)

    # Row 3b: current report base drift
    _check_current_report_from_facts(pointer, cycle, payload_by_path, result)

    # Row 4: trigger_evidence
    for trigger_index, trigger in enumerate(cycle["intake"]["triggers"]):
        for reference_index, reference in enumerate(trigger["evidence_refs"]):
            if _evidence_ref_valid_from_facts(
                reference,
                workspace,
                source_ids=source_ids,
                source_context_valid=source_context_valid,
                payload_by_path=payload_by_path,
            ):
                continue
            result.fail(
                code="REVISIT_TRIGGER_EVIDENCE_MISSING",
                message="fired trigger evidence reference is not currently valid",
                path=(
                    f"cycle.intake.triggers[{trigger_index}]"
                    f".evidence_refs[{reference_index}]"
                ),
                evidence=trigger["trigger_id"],
            )

    # Row 5: claim_freshness
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
    for issue in derive_freshness_issues(cycle):
        result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )
    for resolution_index, resolution in enumerate(cycle["claim_resolutions"]):
        status = resolution["status"]
        if status in {"confirmed", "weakened"}:
            for reference_index, reference in enumerate(
                resolution["current_evidence_refs"]
            ):
                if _evidence_ref_valid_from_facts(
                    reference,
                    workspace,
                    source_ids=source_ids,
                    source_context_valid=source_context_valid,
                    payload_by_path=payload_by_path,
                ):
                    continue
                result.fail(
                    code="REVISIT_FRESHNESS_SUPPORT_INVALID",
                    message=(
                        "positive claim support evidence reference is not "
                        "currently valid"
                    ),
                    path=(
                        f"cycle.claim_resolutions[{resolution_index}]"
                        f".current_evidence_refs[{reference_index}]"
                    ),
                    evidence=resolution["claim_id"],
                )
        if status in {"weakened", "refuted"}:
            for reference_index, reference in enumerate(
                resolution["counter_evidence_refs"]
            ):
                if _evidence_ref_valid_from_facts(
                    reference,
                    workspace,
                    source_ids=source_ids,
                    source_context_valid=source_context_valid,
                    payload_by_path=payload_by_path,
                ):
                    continue
                result.fail(
                    code="REVISIT_COUNTER_EVIDENCE_INVALID",
                    message=(
                        "claim counter-evidence reference is not currently valid"
                    ),
                    path=(
                        f"cycle.claim_resolutions[{resolution_index}]"
                        f".counter_evidence_refs[{reference_index}]"
                    ),
                    evidence=resolution["claim_id"],
                )

    # ------------------------------------------------------------------
    # Fact loading: frontier registry
    # ------------------------------------------------------------------
    registry_payload = session.read_optional("frontier_registry.json")
    registry: dict | None = None
    registry_valid = False
    if registry_payload is None:
        result.fail(
            code="FRONTIER_REGISTRY_MISSING",
            message="frontier_registry.json is required for revisit readiness",
            path="frontier_registry.json",
        )
    else:
        try:
            registry_value = _json_from_bytes(registry_payload, "frontier_registry.json")
            validate_registry(registry_value)
            registry = registry_value
            registry_valid = True
        except LifecycleError as exc:
            result.fail(
                code="REVISIT_FRONTIER_REGISTRY_MALFORMED",
                message=str(exc),
                path="frontier_registry.json",
            )

    # Row 6: frontier_registry
    # The validation failure is emitted above; this row records the identifier.
    # No additional work is required because validation is the row's semantic.

    # ------------------------------------------------------------------
    # Fact loading: ledger, search, dispatch, worker outputs
    # ------------------------------------------------------------------
    ledger_payload = session.read_optional("evidence_ledger.md")
    ledger_text = (
        ledger_payload.decode("utf-8")
        if ledger_payload is not None
        else ""
    )
    search_records = _load_search_facts(session)
    dispatch_records, delivered_payloads = _load_dispatch_facts(session, workspace, result)
    worker_outputs = _load_worker_output_facts(session)

    # Row 7: frontier_research_floor
    if registry is not None and registry_valid:
        covered_search_loops, _ = _search_facts_from_records(search_records)
        for issue in _derive_revisit_frontier_floor_issues_from_facts(
            cycle=cycle,
            registry=registry,
            ledger_text=ledger_text,
            dispatch_records=dispatch_records or (),
            covered_search_loops=frozenset(covered_search_loops),
        ):
            result.fail(
                code=issue.code,
                message=issue.message,
                path=issue.path,
                evidence=issue.evidence,
            )

    # Row 8: search_coverage
    state_loop_count = int(state.get("loop_count", 0) or 0) if isinstance(state, dict) else 0
    if state_loop_count > 0:
        covered_loop_ids, has_any_valid = _search_facts_from_records(search_records)
        if has_any_valid:
            expected_loop_ids = {f"loop_{i}" for i in range(1, state_loop_count + 1)}
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
        else:
            result.fail(
                code="SEARCH_LOG_MISSING",
                message="completed loops require valid search_log.jsonl records",
                path="search_log.jsonl",
                evidence="no valid search record found",
            )

    # Row 9: dispatch_delivery
    worker_output_paths = tuple(rel for rel, _text in worker_outputs)
    if dispatch_records is not None:
        _check_dispatch_documents(
            records=dispatch_records,
            workflow_text=workflow_text,
            profile=ContractProfile(mode="ticker", target="revisit_report"),
            worker_output_paths=worker_output_paths,
            delivered_payloads=delivered_payloads,
            result=result,
            workspace=workspace,
        )

    # Row 10: worker_outputs
    if dispatch_records is not None:
        delivered_roles = _delivered_roles_from_records(dispatch_records)
        _check_worker_output_documents(
            outputs=worker_outputs,
            delivered_roles=delivered_roles,
            registered_source_ids=source_ids,
            profile=ContractProfile(mode="ticker", target="revisit_report"),
            result=result,
        )

    # Row 11: source_cache
    if source_evaluation.issues or source_evaluation.warnings:
        for issue in source_evaluation.issues:
            result.fail(
                code=issue.code,
                message=issue.message,
                path=issue.location,
            )
        for warning in source_evaluation.warnings:
            result.warn(
                code=warning.code,
                message=warning.message,
                path=warning.location,
            )

    # Row 12: generation_closure
    closure = session.freeze()

    # Row 13: route_and_effect_parity
    # Satisfied by construction: every route shares this same preparation plan.

    return _PreparedRevisitReadiness(
        result=result,
        cycle_id=cycle_id,
        cycle=cycle,
        cycle_sha256=cycle_sha256,
        closure=closure,
    )


def _delivered_roles_from_records(
    records: tuple[dict, ...],
) -> tuple[tuple[str, str], ...]:
    """Derive normalized (relative_path, role_slug) pairs from dispatch records."""
    roles_by_path: dict[str, str] = {}
    seen_paths: set[str] = set()
    for record in records:
        if not _dispatch_record_counts_as_delivery(record):
            continue
        normalized = _normalize_delivery_path_from_facts(record.get("delivery_path", ""))
        if normalized is None:
            continue
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        try:
            from worker_role_catalog import normalize_role_slug, role_for_slug

            role_slug = normalize_role_slug(record.get("role"), delivery_path=normalized)
            role = role_for_slug(role_slug)
        except ValueError:
            continue
        if "ticker" not in role.modes:
            continue
        roles_by_path[normalized] = role.slug
    return tuple(roles_by_path.items())


def evaluate_revisit_readiness(
    workspace: Path | str,
    cycle_id: str | None = None,
) -> ContractResult:
    """Read-only readiness seam.

    ``cycle_id=None`` discovers the sole eligible cycle from globally validated
    history. All filesystem authority flows through one ``ObservedReadSession``;
    the returned ``ContractResult`` includes any semantic issues plus a single
    ``REVISIT_AUTHORITY_DRIFT`` if the observed authority changed before the
    closure recheck.
    """
    root = Path(workspace)
    result = ContractResult()
    session = ObservedReadSession(root)
    try:
        prepared = _prepare_revisit_readiness(session, result, cycle_id)
        closure = prepared.closure
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
        return result
    except ReadinessPlanError:
        raise
    except (OSError, RevisitContractError, LifecycleError, ValueError) as exc:
        # Unexpected I/O or impossible internal value propagates.
        raise

    try:
        closure.require_unchanged()
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
    return result


def check_revisit_readiness(
    workspace: Path | str,
    cycle_id: str,
    *,
    timestamp: str,
) -> RevisitCheckOutcome:
    """Evaluate the same policy as ``evaluate_revisit_readiness`` and atomically
    mark an active cycle ready.

    Acquires the existing re-entrant ``workspace_transaction`` around
    preparation + effect + persistence so the observed-read closure and the
    persistence boundary share one locked workspace.

    * ``BLOCKED`` = semantic or drift failure (zero writes).
    * ``TRANSITIONED`` = active->ready, one ``check`` audit at ``timestamp``.
    * ``UNCHANGED_READY`` = already ready, byte-preserving no-op (no audit).

    ``timestamp`` must be canonical UTC seconds; an invalid value is a
    programming/API error (raised). ``RevisitPersistenceRollbackError``
    propagates (catastrophic, NOT converted to a ContractResult).
    """
    _validate_canonical_timestamp(timestamp)
    result = ContractResult()
    with workspace_transaction(workspace) as locked_workspace:
        session = ObservedReadSession(locked_workspace)
        prepared = _prepare_revisit_readiness(session, result, cycle_id)
        closure = prepared.closure

        # Recheck the closure once after preparation. Any boundary change is a
        # BLOCKED drift (zero writes). The store rechecks again (with the two
        # cycle/mirror exclusions) before and after the write.
        try:
            closure.require_unchanged()
        except AuthorityDriftError as exc:
            result.fail(
                code="REVISIT_AUTHORITY_DRIFT",
                message=str(exc),
                path=exc.drift.relative_path,
            )
            return RevisitCheckOutcome(
                result=result,
                cycle_id=prepared.cycle_id,
                effect=RevisitCheckEffect.BLOCKED,
            )

        # Malformed history or semantic failure -> BLOCKED with zero writes.
        if not result.passed:
            return RevisitCheckOutcome(
                result=result,
                cycle_id=prepared.cycle_id,
                effect=RevisitCheckEffect.BLOCKED,
            )

        cycle = prepared.cycle
        if cycle is None or prepared.cycle_sha256 is None:
            # Selection succeeded but the cycle payload itself was unusable.
            return RevisitCheckOutcome(
                result=result,
                cycle_id=prepared.cycle_id,
                effect=RevisitCheckEffect.BLOCKED,
            )

        if cycle["status"] == "ready_for_report":
            # Byte-preserving no-op: recheck the complete unexcluded closure
            # exactly once (already done above) and return without rendering,
            # writing, or appending an audit entry.
            return RevisitCheckOutcome(
                result=result,
                cycle_id=prepared.cycle_id,
                effect=RevisitCheckEffect.UNCHANGED_READY,
            )

        # TRANSITIONED: active -> ready_for_report with one ``check`` audit at
        # the supplied timestamp. Persistence delegates to ``persist_cycle``
        # with the frozen closure so the store rechecks the non-excluded
        # closure before+after the write and derives the cycle/mirror
        # exclusions itself.
        proposed = mark_ready_for_report(cycle)
        updated = with_audit(
            cycle,
            proposed,
            "check",
            [prepared.cycle_id],
            timestamp,
        )
        try:
            persist_cycle(
                locked_workspace,
                updated,
                expected_sha256=prepared.cycle_sha256,
                generation_closure=closure,
            )
        except AuthorityDriftError as exc:
            # Handled post-write drift: the store restored exact prior bytes;
            # surface as BLOCKED with a REVISIT_AUTHORITY_DRIFT failure.
            result.fail(
                code="REVISIT_AUTHORITY_DRIFT",
                message=str(exc),
                path=exc.drift.relative_path,
            )
            return RevisitCheckOutcome(
                result=result,
                cycle_id=prepared.cycle_id,
                effect=RevisitCheckEffect.BLOCKED,
            )
        return RevisitCheckOutcome(
            result=result,
            cycle_id=prepared.cycle_id,
            effect=RevisitCheckEffect.TRANSITIONED,
        )


# Import helpers only to expose them for the read-only seam and tests.
__all__ = [
    "REVISIT_REQUIREMENT_IDS",
    "ReadinessPlanError",
    "RevisitCheckEffect",
    "RevisitCheckOutcome",
    "check_revisit_readiness",
    "evaluate_revisit_readiness",
]
