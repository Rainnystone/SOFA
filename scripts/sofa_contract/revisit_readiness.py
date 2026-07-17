"""Single observed-read revisit readiness seam.

``evaluate_revisit_readiness`` is the ONLY thirteen-row readiness surface: the
named-selection (``evaluate_revisit_report``), profile-target
(``evaluate_workspace`` with ``target="revisit_report"``) and CLI ``check``
routes all delegate to it. All semantic filesystem access in the readiness call
graph flows through one ``ObservedReadSession`` so that ``freeze()`` captures
every authority actually consumed by the semantic owners, and a single
``require_unchanged()`` boundary recheck translates any drift to
``REVISIT_AUTHORITY_DRIFT``.

The thirteen-row ``_READINESS_PLAN`` is a closed, ordered list, not a plugin
registry. Each row carries its sole executable owner (or invariant handler) and
explicit prerequisites. ``_verify_plan_shape`` fails loudly before observation
if any row is missing, duplicated, unknown, unowned, multi-owned, or reordered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal

from workspace_contract import all_worker_output_directories, is_main_thread_artifact

from .result import ContractProfile, ContractResult

from .workspace import iter_jsonl_records

try:
    from framing_contract import FramingContractError, evaluate_contract
    from framing_contract.model import normalize_contract
except ImportError:
    from scripts.framing_contract import FramingContractError, evaluate_contract
    from scripts.framing_contract.model import normalize_contract

try:
    from frontier_lifecycle import (
        CURRENT_REGISTRY_VERSION,
        LifecycleError,
        validate_registry,
    )
except ImportError:
    from scripts.frontier_lifecycle import (
        CURRENT_REGISTRY_VERSION,
        LifecycleError,
        validate_registry,
    )

try:
    from revisit_contract import (
        CYCLE_ID_RE,
        RevisitContractError,
        derive_claim_issues,
        derive_freshness_issues,
        evaluate_history,
        mark_ready_for_report,
        persist_cycle,
        sha256_bytes,
        workspace_transaction,
    )
    from revisit_contract.model import validate_cycle, validate_pointer, with_audit
    from revisit_contract.store import RevisitPersistenceRollbackError
except ImportError:
    from scripts.revisit_contract import (
        CYCLE_ID_RE,
        RevisitContractError,
        derive_claim_issues,
        derive_freshness_issues,
        evaluate_history,
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
    from source_cache import (
        SOURCE_INDEX_FILENAME,
        SourceCacheEvaluation,
        SourceIssue,
    )
    from source_cache.store import evaluate_index_documents, plan_index_document
except ImportError:
    from scripts.source_cache import (
        SOURCE_INDEX_FILENAME,
        SourceCacheEvaluation,
        SourceIssue,
    )
    from scripts.source_cache.store import evaluate_index_documents, plan_index_document

from .evaluate import (  # noqa: E402
    TICKER_REPORT_REQUIREMENTS,
    _RevisitLedgerFacts,
    _RevisitStateFacts,
    _RevisitWorkflowFacts,
    _check_dispatch_documents,
    _check_state_workflow_facts,
    _check_worker_output_documents,
    _current_revision_matches_completed_cycle,
    _derive_revisit_dispatch_floor_issues_from_facts,
    _derive_revisit_frontier_progress_issues_from_facts,
    _derive_revisit_registry_issues_from_facts,
    _derive_revisit_search_floor_issues_from_facts,
    _dispatch_record_counts_as_delivery,
    _evaluate_specific_ticker_report_document,
    _has_exact_single_metadata_block,
    _missing_dispatch_delivery_fields,
    _missing_final_report_requirements,
    _normalize_delivery_path,
    _normalize_delivery_path_from_facts,
    _prepare_revisit_frontier_facts,
    _parse_revisit_ledger_facts,
    _parse_revisit_state_facts,
    _parse_revisit_workflow_facts,
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


_TraceStatus = Literal["evaluated", "skipped", "invariant"]


@dataclass(frozen=True)
class _ReadinessTraceEntry:
    requirement_id: str
    status: _TraceStatus


@dataclass(frozen=True)
class _ReadinessRequirement:
    requirement_id: str
    handlers: tuple[Callable[["_ReadinessContext"], None], ...]
    prerequisites: tuple[str, ...]
    invariant: bool = False


_SelectedCycleStatus = Literal[
    "active",
    "ready_for_report",
    "completed",
]


@dataclass(frozen=True)
class _SelectedCycle:
    cycle_id: str
    cycle: dict[str, Any]
    cycle_sha256: str
    status: _SelectedCycleStatus

    def __post_init__(self) -> None:
        if self.cycle.get("cycle_id") != self.cycle_id:
            raise ReadinessPlanError(
                "selected cycle ID disagrees with the selected document"
            )
        if self.cycle.get("status") != self.status:
            raise ReadinessPlanError(
                "selected cycle status disagrees with the selected document"
            )
        if self.status not in {
            "active",
            "ready_for_report",
            "completed",
        }:
            raise ReadinessPlanError(
                "selected cycle has an ineligible status"
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.cycle_sha256) is None:
            raise ReadinessPlanError(
                "selected cycle digest must be a lowercase SHA-256"
            )


@dataclass(frozen=True)
class _RevisitRegistryFacts:
    document: dict[str, Any]


@dataclass
class _ReadinessContext:
    session: ObservedReadSession
    result: ContractResult
    named_cycle_id: str | None
    lexical_workspace: Path
    workspace: Path
    published_current_cycle_id: str | None = None
    state_payload: bytes | None = None
    state_facts: _RevisitStateFacts | None = None
    state_error: Exception | None = None
    workflow_payload: bytes | None = None
    workflow_facts: _RevisitWorkflowFacts | None = None
    workflow_error: Exception | None = None
    pointer: dict | None = None
    pointer_error: RevisitContractError | None = None
    history: Any = None
    history_load_issues: list[tuple[str, str, str, str]] = field(
        default_factory=list
    )
    selected_cycle: _SelectedCycle | None = None
    payload_by_path: dict[str, bytes] = field(default_factory=dict)
    source_evaluation: Any = None
    source_ids: frozenset[str] = frozenset()
    source_context_valid: bool = False
    registry_payload: bytes | None = None
    registry_facts: _RevisitRegistryFacts | None = None
    registry_error: Exception | None = None
    ledger_payload: bytes | None = None
    ledger_facts: _RevisitLedgerFacts | None = None
    ledger_error: Exception | None = None
    search_payload: bytes | None = None
    search_records: tuple[dict, ...] | None = ()
    search_error: Exception | None = None
    dispatch_records: tuple[dict, ...] | None = ()
    delivered_payloads: tuple[tuple[str, bytes | None], ...] = ()
    dispatch_error: Exception | None = None
    worker_outputs: tuple[tuple[str, str], ...] = ()
    worker_output_errors: tuple[tuple[str, str], ...] = ()
    worker_output_paths: tuple[str, ...] = ()
    frontier_facts: Any = None
    prerequisite_status: dict[str, bool] = field(default_factory=dict)
    trace: list[_ReadinessTraceEntry] = field(default_factory=list)
    closure: GenerationClosure | None = None

    @property
    def selected_cycle_id(self) -> str | None:
        return (
            self.selected_cycle.cycle_id
            if self.selected_cycle is not None
            else None
        )

    @property
    def cycle(self) -> dict[str, Any] | None:
        return (
            self.selected_cycle.cycle
            if self.selected_cycle is not None
            else None
        )


@dataclass(frozen=True)
class _PreparedRevisitReadiness:
    """Module-private result of one complete executable readiness pass."""

    result: ContractResult
    selected_cycle: _SelectedCycle | None
    closure: GenerationClosure
    trace: tuple[_ReadinessTraceEntry, ...]

    @property
    def cycle_id(self) -> str | None:
        return (
            self.selected_cycle.cycle_id
            if self.selected_cycle is not None
            else None
        )


class RevisitCheckEffect(str, Enum):
    """The three atomic effects of ``check_revisit_readiness``.

    * ``BLOCKED`` -- semantic or drift failure; zero writes.
    * ``TRANSITIONED`` -- active->ready; exactly one ``check`` audit entry.
    * ``UNCHANGED_READY`` -- ready or completed-unpublished; byte-preserving
      no-op (no audit).
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


def _make_revisit_check_outcome(
    result: ContractResult,
    selected_cycle: _SelectedCycle | None,
) -> RevisitCheckOutcome:
    """Reduce one complete semantic state to the sole public outcome shape."""
    cycle_id = (
        selected_cycle.cycle_id if selected_cycle is not None else None
    )
    if not result.passed:
        effect = RevisitCheckEffect.BLOCKED
        return RevisitCheckOutcome(result, cycle_id, effect)
    if selected_cycle is None:
        raise ReadinessPlanError(
            "passing readiness requires one complete selected cycle"
        )
    if selected_cycle.status == "active":
        effect = RevisitCheckEffect.TRANSITIONED
    elif selected_cycle.status in {"ready_for_report", "completed"}:
        effect = RevisitCheckEffect.UNCHANGED_READY
    else:
        raise ReadinessPlanError(
            f"passing readiness selected impossible status: "
            f"{selected_cycle.status}"
        )
    return RevisitCheckOutcome(result, selected_cycle.cycle_id, effect)


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


def _observe_optional_file(
    session: ObservedReadSession,
    relative_path: str,
) -> tuple[bytes | None, Exception | None]:
    """Observe one expected file without translating its domain category.

    The observed lexical-node generation records missing and every present
    kind before attempting a read. The calling owner decides which stable
    issue code applies. A post-freeze call remains a generation-layer
    programming error and fails loudly.
    """
    try:
        return session.read_optional(relative_path), None
    except RevisitContractError as exc:
        return None, exc


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
    lexical_workspace: Path,
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
    normalized = _normalize_delivery_path(
        lexical_workspace,
        reference.get("path", ""),
        resolved_workspace=workspace,
    )
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


def _registered_base_report_matches(
    cycle: dict,
    payload_by_path: dict[str, bytes],
) -> bool:
    base = cycle["intake"]["base_revision"]
    payload = payload_by_path.get(base["report_path"])
    return payload is not None and sha256_bytes(payload) == base["report_sha256"]


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
    base_drift = base != expected_base or not _registered_base_report_matches(
        cycle,
        payload_by_path,
    )
    if base_drift:
        result.fail(
            code="REVISIT_BASE_REPORT_DRIFT",
            message="cycle base revision or current report bytes differ from the registered pointer",
            path="cycle.intake.base_revision",
        )


def _check_published_base_report_from_facts(
    cycle: dict,
    payload_by_path: dict[str, bytes],
    result: ContractResult,
) -> None:
    if not _registered_base_report_matches(cycle, payload_by_path):
        result.fail(
            code="REVISIT_BASE_REPORT_DRIFT",
            message="cycle base report bytes differ from immutable intake",
            path="cycle.intake.base_revision",
        )


def _evaluate_source_cache_from_session(
    session: ObservedReadSession,
) -> tuple:
    """Plan, read, and evaluate the source cache using the observed session.

    Returns ``(evaluation, source_ids, source_context_valid)``.
    """
    index_payload, index_error = _observe_optional_file(
        session,
        SOURCE_INDEX_FILENAME,
    )
    if index_error is not None:
        evaluation = SourceCacheEvaluation(
            (),
            (
                SourceIssue(
                    "SOURCE_INDEX_MALFORMED",
                    SOURCE_INDEX_FILENAME,
                    f"cannot read {SOURCE_INDEX_FILENAME}: {index_error}",
                ),
            ),
            (),
        )
        return evaluation, frozenset(), False
    plan = plan_index_document(index_payload)
    try:
        source_entries = session.list_directory(
            "sources",
            recursive=True,
            optional=True,
        )
    except RevisitContractError as exc:
        evaluation = SourceCacheEvaluation(
            (),
            (
                SourceIssue(
                    "SOURCE_INDEX_MALFORMED",
                    "sources",
                    f"source cache root is invalid or unreadable: {exc}",
                ),
            ),
            (),
        )
        return evaluation, frozenset(), False

    invalid_members = tuple(
        SourceIssue(
            "SOURCE_INDEX_MALFORMED",
            entry.relative_path,
            "source cache member must be a lexical regular file or directory",
        )
        for entry in source_entries
        if entry.kind == "other"
    )
    excerpt_payloads: list[tuple[str, bytes | None]] = []
    for excerpt_path in plan.excerpt_paths:
        excerpt_payload, _excerpt_error = _observe_optional_file(
            session,
            excerpt_path,
        )
        excerpt_payloads.append(
            (excerpt_path, excerpt_payload)
        )
    source_files = tuple(
        entry.relative_path
        for entry in source_entries
        if entry.kind == "file"
    )
    evaluation = evaluate_index_documents(
        plan, tuple(excerpt_payloads), source_files
    )
    if invalid_members:
        evaluation = SourceCacheEvaluation(
            evaluation.records,
            (*evaluation.issues, *invalid_members),
            evaluation.warnings,
        )
    source_ids = frozenset(
        str(record["source_id"]) for record in evaluation.records
    )
    source_context_valid = not evaluation.issues
    return evaluation, source_ids, source_context_valid


def _load_worker_output_facts(
    session: ObservedReadSession,
) -> tuple[
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str], ...],
    tuple[str, ...],
]:
    """Read every known worker-output directory member through the session."""
    outputs: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    output_paths: list[str] = []
    for dirname in all_worker_output_directories():
        try:
            entries = session.list_directory(
                dirname,
                recursive=False,
                optional=True,
            )
        except RevisitContractError as exc:
            errors.append((dirname, str(exc)))
            continue
        for entry in entries:
            if not entry.relative_path.endswith(".md"):
                continue
            if is_main_thread_artifact(entry.relative_path):
                continue
            output_paths.append(entry.relative_path)
            if entry.kind != "file":
                errors.append(
                    (
                        entry.relative_path,
                        "worker output must be a lexical regular file",
                    )
                )
                continue
            payload, read_error = _observe_optional_file(
                session,
                entry.relative_path,
            )
            if read_error is not None:
                errors.append((entry.relative_path, str(read_error)))
                continue
            if payload is None:
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                errors.append((entry.relative_path, str(exc)))
                continue
            outputs.append((entry.relative_path, text))
    return tuple(outputs), tuple(errors), tuple(output_paths)


def _load_dispatch_facts(
    session: ObservedReadSession,
    workspace: Path,
    lexical_workspace: Path,
) -> tuple[
    tuple[dict, ...] | None,
    tuple[tuple[str, bytes | None], ...],
    Exception | None,
]:
    """Parse dispatch_log.jsonl and preload delivered payloads.

    Returns parsed records, delivered payloads, and a parse error if present.
    The Row 9 owner is the only code that translates the error to an issue.
    """
    payload, read_error = _observe_optional_file(
        session,
        "dispatch_log.jsonl",
    )
    if read_error is not None:
        return None, (), read_error
    if payload is None:
        return (), (), None
    try:
        records = _iter_jsonl_bytes(payload)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        return None, (), exc
    record_tuple = tuple(record for _line_number, record in records)
    delivered_payloads: list[tuple[str, bytes | None]] = []
    seen: set[str] = set()
    for record in record_tuple:
        if record.get("status") != "delivered":
            continue
        raw_path = record.get("delivery_path", "")
        if not raw_path:
            continue
        normalized = _normalize_delivery_path(
            lexical_workspace,
            raw_path,
            resolved_workspace=workspace,
        )
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        delivered_payload, _delivery_error = _observe_optional_file(
            session,
            normalized,
        )
        delivered_payloads.append((normalized, delivered_payload))
    return record_tuple, tuple(delivered_payloads), None


def _load_search_facts(
    session: ObservedReadSession,
) -> tuple[bytes | None, tuple[dict, ...] | None, Exception | None]:
    payload, read_error = _observe_optional_file(
        session,
        "search_log.jsonl",
    )
    if read_error is not None:
        return None, None, read_error
    if payload is None:
        return None, (), None
    try:
        records = tuple(
            record for _line_number, record in _iter_jsonl_bytes(payload)
        )
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        return payload, None, exc
    return payload, records, None


def _discover_eligible_cycle_id(
    history,
    result: ContractResult,
) -> str | None:
    """Return the sole eligible cycle id, or record a failure and return None."""
    if _append_history_issues(history, result):
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


def _append_history_issues(history, result: ContractResult) -> bool:
    for issue in history.issues:
        result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )
    return bool(history.issues)


def _map_cycle_load_error(exc: RevisitContractError) -> str:
    """Preserve the historical special-case code for forbidden positive support."""
    message = str(exc)
    if "cannot be used as positive support" in message:
        return "REVISIT_CLAIM_SUPPORT_FORBIDDEN"
    return "REVISIT_CYCLE_MALFORMED"


def _append_revisit_issues(
    result: ContractResult,
    issues,
) -> None:
    for issue in issues:
        result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.path,
            evidence=issue.evidence,
        )


def _load_core_facts(context: _ReadinessContext) -> None:
    context.state_payload, context.state_error = _observe_optional_file(
        context.session,
        "state.json",
    )
    if context.state_payload is not None and context.state_error is None:
        try:
            state_value = json.loads(context.state_payload.decode("utf-8"))
            context.state_facts = _parse_revisit_state_facts(state_value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            context.state_error = exc

    (
        context.workflow_payload,
        context.workflow_error,
    ) = _observe_optional_file(
        context.session,
        "research_workflow.md",
    )
    if (
        context.workflow_payload is not None
        and context.workflow_error is None
    ):
        try:
            workflow_text = context.workflow_payload.decode("utf-8")
            context.workflow_facts = _parse_revisit_workflow_facts(
                workflow_text
            )
        except (UnicodeDecodeError, ValueError) as exc:
            context.workflow_error = exc


def _load_history_facts(context: _ReadinessContext) -> None:
    pointer_payload, pointer_read_error = _observe_optional_file(
        context.session,
        "revisit_contract.json",
    )
    if pointer_read_error is not None:
        context.pointer_error = RevisitContractError(
            "revisit_contract.json is invalid or unreadable: "
            f"{pointer_read_error}"
        )
    elif pointer_payload is None:
        context.pointer_error = RevisitContractError(
            "required authority is missing: revisit_contract.json"
        )
    else:
        try:
            context.pointer = validate_pointer(
                _json_from_bytes(pointer_payload, "revisit_contract.json")
            )
        except RevisitContractError as exc:
            context.pointer_error = exc

    try:
        cycle_entries = context.session.list_directory(
            "revisit_cycles",
            recursive=False,
            optional=False,
        )
    except RevisitContractError as exc:
        context.history_load_issues.append(
            (
                "REVISIT_CYCLE_MALFORMED",
                str(exc),
                "revisit_cycles",
                "",
            )
        )
        cycle_entries = ()

    cycles: list[dict] = []
    cycle_payloads: dict[str, bytes] = {}
    cycles_by_id: dict[str, dict] = {}
    for entry in cycle_entries:
        member = Path(entry.relative_path)
        cycle_id_from_name = member.stem
        if (
            entry.kind != "file"
            or member.suffix not in {".json", ".md"}
            or CYCLE_ID_RE.fullmatch(cycle_id_from_name) is None
        ):
            context.history_load_issues.append(
                (
                    "REVISIT_CYCLE_MALFORMED",
                    "cycle history member must be a lexical regular "
                    "RC-NNNN.json or RC-NNNN.md file",
                    entry.relative_path,
                    "",
                )
            )
            continue
        if member.suffix == ".md":
            continue
        payload, payload_error = _observe_optional_file(
            context.session,
            entry.relative_path,
        )
        if payload_error is not None:
            context.history_load_issues.append(
                (
                    "REVISIT_CYCLE_MALFORMED",
                    str(payload_error),
                    entry.relative_path,
                    "",
                )
            )
            continue
        if payload is None:
            context.history_load_issues.append(
                (
                    "REVISIT_CYCLE_MALFORMED",
                    "cycle JSON disappeared during observation",
                    entry.relative_path,
                    "",
                )
            )
            continue
        cycle_payloads[cycle_id_from_name] = payload
        try:
            cycle_value = validate_cycle(
                _json_from_bytes(payload, entry.relative_path)
            )
            if cycle_value["cycle_id"] != cycle_id_from_name:
                raise RevisitContractError(
                    f"filename {cycle_id_from_name} does not match internal "
                    f"cycle_id {cycle_value['cycle_id']}"
                )
        except RevisitContractError as exc:
            context.history_load_issues.append(
                (
                    _map_cycle_load_error(exc),
                    str(exc),
                    entry.relative_path,
                    "",
                )
            )
            continue
        cycles.append(cycle_value)
        cycles_by_id[cycle_id_from_name] = cycle_value

    if context.pointer is not None:
        context.history = evaluate_history(context.pointer, cycles)
        if not context.history_load_issues and not context.history.issues:
            eligible = (
                *context.history.nonterminal_cycle_ids,
                *context.history.completed_unpublished_cycle_ids,
            )
            selected_cycle_id = (
                context.published_current_cycle_id
                if context.published_current_cycle_id is not None
                else eligible[0] if len(eligible) == 1 else None
            )
            if selected_cycle_id is not None:
                selected_cycle = cycles_by_id.get(selected_cycle_id)
                payload = cycle_payloads.get(selected_cycle_id)
                if selected_cycle is not None and payload is not None:
                    context.selected_cycle = _SelectedCycle(
                        cycle_id=selected_cycle_id,
                        cycle=selected_cycle,
                        cycle_sha256=sha256_bytes(payload),
                        status=selected_cycle["status"],
                    )
                elif context.published_current_cycle_id is None:
                    raise ReadinessPlanError(
                        "eligible history cycle lacks its validated document"
                    )

        current = context.pointer.get("current_revision")
        if current is not None:
            report_path = current["report_path"]
            report_payload, _report_error = _observe_optional_file(
                context.session,
                report_path,
            )
            if report_payload is not None:
                context.payload_by_path[report_path] = report_payload


def _load_source_facts(context: _ReadinessContext) -> None:
    (
        context.source_evaluation,
        context.source_ids,
        context.source_context_valid,
    ) = _evaluate_source_cache_from_session(context.session)


def _load_registry_facts(context: _ReadinessContext) -> None:
    (
        context.registry_payload,
        registry_read_error,
    ) = _observe_optional_file(
        context.session,
        "frontier_registry.json",
    )
    if registry_read_error is not None:
        context.registry_error = registry_read_error
        return
    if context.registry_payload is None:
        return
    try:
        registry_value = _json_from_bytes(
            context.registry_payload,
            "frontier_registry.json",
        )
        validate_registry(registry_value)
        if registry_value.get("version") != CURRENT_REGISTRY_VERSION:
            raise LifecycleError(
                "revisit readiness requires the current registry schema"
            )
        if registry_value.get("mode") != "ticker":
            raise LifecycleError(
                "revisit readiness requires a ticker registry"
            )
    except (RevisitContractError, LifecycleError) as exc:
        context.registry_error = exc
        return
    context.registry_facts = _RevisitRegistryFacts(registry_value)


def _load_ledger_facts(context: _ReadinessContext) -> None:
    (
        context.ledger_payload,
        context.ledger_error,
    ) = _observe_optional_file(
        context.session,
        "evidence_ledger.md",
    )
    if context.ledger_payload is None:
        return
    if context.ledger_error is None:
        try:
            ledger_text = context.ledger_payload.decode("utf-8")
            context.ledger_facts = _parse_revisit_ledger_facts(ledger_text)
        except (UnicodeDecodeError, ValueError) as exc:
            context.ledger_error = exc


def _load_cycle_artifact_facts(context: _ReadinessContext) -> None:
    cycle = context.cycle
    if cycle is None:
        return

    def observe(relative_path: str) -> None:
        payload, _read_error = _observe_optional_file(
            context.session,
            relative_path,
        )
        if payload is not None:
            context.payload_by_path[relative_path] = payload

    observe(cycle["intake"]["base_revision"]["report_path"])
    observe(cycle["intake"]["framing"]["path"])
    for claim in cycle["intake"]["selected_claims"]:
        observe(claim["source_ref"]["path"])

    for trigger in cycle["intake"]["triggers"]:
        for reference in trigger["evidence_refs"]:
            if reference.get("kind") != "artifact":
                continue
            normalized = _normalize_delivery_path(
                context.lexical_workspace,
                reference.get("path", ""),
                resolved_workspace=context.workspace,
            )
            if normalized is not None:
                observe(normalized)

    for resolution in cycle["claim_resolutions"]:
        for field_name in (
            "current_evidence_refs",
            "counter_evidence_refs",
        ):
            for reference in resolution[field_name]:
                if reference.get("kind") != "artifact":
                    continue
                normalized = _normalize_delivery_path(
                    context.lexical_workspace,
                    reference.get("path", ""),
                    resolved_workspace=context.workspace,
                )
                if normalized is not None:
                    observe(normalized)


def _load_readiness_facts(context: _ReadinessContext) -> None:
    """Observe and parse facts without appending any ContractResult issue."""
    _load_core_facts(context)
    _load_history_facts(context)
    _load_source_facts(context)
    _load_registry_facts(context)
    _load_ledger_facts(context)

    (
        context.search_payload,
        context.search_records,
        context.search_error,
    ) = _load_search_facts(context.session)
    (
        context.dispatch_records,
        context.delivered_payloads,
        context.dispatch_error,
    ) = _load_dispatch_facts(
        context.session,
        context.workspace,
        context.lexical_workspace,
    )
    (
        context.worker_outputs,
        context.worker_output_errors,
        context.worker_output_paths,
    ) = _load_worker_output_facts(context.session)
    _load_cycle_artifact_facts(context)

    context.prerequisite_status.update(
        {
            "ticker_mode": (
                context.state_facts is not None
                and context.state_facts.mode == "ticker"
            ),
            "cycle": context.cycle is not None,
        }
    )


def _frontier_facts(context: _ReadinessContext):
    if context.cycle is None:
        return None
    if context.frontier_facts is None:
        covered_search_loops = None
        if context.search_records is not None:
            covered_search_loops = frozenset(
                _search_facts_from_records(context.search_records)[0]
            )
        context.frontier_facts = _prepare_revisit_frontier_facts(
            cycle=context.cycle,
            registry=(
                context.registry_facts.document
                if context.registry_facts is not None
                else None
            ),
            ledger_facts=context.ledger_facts,
            dispatch_records=context.dispatch_records,
            covered_search_loops=covered_search_loops,
        )
    return context.frontier_facts


def _evaluate_core_state_workflow(context: _ReadinessContext) -> None:
    if (
        context.state_facts is not None
        and context.state_facts.mode == "sector"
    ):
        context.result.fail(
            code="REVISIT_UNSUPPORTED_MODE",
            message="revisit_report is unavailable for Sector workspaces",
            path="state.json",
        )
        return

    if context.state_payload is None and context.state_error is None:
        context.result.fail(
            code="STATE_JSON_MISSING",
            message=(
                "state.json is required as the machine-readable workspace "
                "authority"
            ),
            path="state.json",
        )
    elif context.state_error is not None:
        context.result.fail(
            code="STATE_JSON_INVALID",
            message=(
                "state.json is invalid or unreadable: "
                f"{context.state_error}"
            ),
            path="state.json",
        )

    if context.workflow_payload is None and context.workflow_error is None:
        context.result.fail(
            code="RESEARCH_WORKFLOW_MISSING",
            message=(
                "research_workflow.md is required as the human-readable "
                "workflow mirror"
            ),
            path="research_workflow.md",
        )
    elif context.workflow_error is not None:
        context.result.fail(
            code="RESEARCH_WORKFLOW_INVALID",
            message=(
                "research_workflow.md is invalid or unreadable: "
                f"{context.workflow_error}"
            ),
            path="research_workflow.md",
        )

    if context.ledger_payload is None and context.ledger_error is None:
        context.result.fail(
            code="EVIDENCE_LEDGER_MISSING",
            message=(
                "evidence_ledger.md is required for evidence-first research"
            ),
            path="evidence_ledger.md",
        )
    elif context.ledger_error is not None:
        context.result.fail(
            code="EVIDENCE_LEDGER_INVALID",
            message=(
                "evidence_ledger.md is invalid or unreadable: "
                f"{context.ledger_error}"
            ),
            path="evidence_ledger.md",
        )

    if context.state_facts is None:
        return
    if context.workflow_facts is not None:
        _check_state_workflow_facts(
            context.state_facts,
            context.workflow_facts,
            context.result,
        )


def _evaluate_global_cycle_history(context: _ReadinessContext) -> None:
    if context.pointer_error is not None:
        context.result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=str(context.pointer_error),
            path="revisit_contract.json",
        )
    for code, message, path, evidence in context.history_load_issues:
        context.result.fail(
            code=code,
            message=message,
            path=path,
            evidence=evidence,
        )

    if context.pointer_error is not None or context.history_load_issues:
        return

    if context.published_current_cycle_id is not None:
        if context.history is None or _append_history_issues(
            context.history,
            context.result,
        ):
            return
        selected = context.selected_cycle
        current = context.pointer["current_revision"]
        if (
            selected is None
            or current is None
            or not _current_revision_matches_completed_cycle(
                current,
                selected.cycle,
            )
        ):
            context.result.fail(
                code="CURRENT_REPORT_LINEAGE_MISMATCH",
                message=(
                    "published-current readiness requires the exact completed "
                    "pointer/candidate lineage"
                ),
                path=(
                    f"revisit_cycles/"
                    f"{context.published_current_cycle_id}.json"
                ),
            )
            return
        _check_published_base_report_from_facts(
            selected.cycle,
            context.payload_by_path,
            context.result,
        )
        return

    eligible_cycle_id = None
    if context.history is not None:
        discovered_cycle_id = _discover_eligible_cycle_id(
            context.history,
            context.result,
        )
        if (
            not context.history_load_issues
            and discovered_cycle_id is not None
            and context.selected_cycle_id != discovered_cycle_id
        ):
            raise ReadinessPlanError(
                "history selection fact diverged from Row 2 evaluation"
            )
        if not context.history_load_issues:
            eligible_cycle_id = discovered_cycle_id

    if (
        context.named_cycle_id is not None
        and eligible_cycle_id is not None
        and context.named_cycle_id != eligible_cycle_id
    ):
        context.result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message=(
                f"named cycle {context.named_cycle_id} is not the sole "
                f"globally eligible cycle ({eligible_cycle_id})"
            ),
            path="revisit_cycles",
            evidence=(
                f"named={context.named_cycle_id}; "
                f"eligible={eligible_cycle_id}"
            ),
        )

    if context.pointer is not None and context.cycle is not None:
        _check_current_report_from_facts(
            context.pointer,
            context.cycle,
            context.payload_by_path,
            context.result,
        )


def _evaluate_intake_provenance(context: _ReadinessContext) -> None:
    _check_intake_authorities_from_facts(
        context.cycle,
        context.payload_by_path,
        context.result,
    )


def _evaluate_trigger_evidence(context: _ReadinessContext) -> None:
    for trigger_index, trigger in enumerate(
        context.cycle["intake"]["triggers"]
    ):
        for reference_index, reference in enumerate(
            trigger["evidence_refs"]
        ):
            if (
                reference.get("kind") == "source"
                and not context.source_context_valid
            ):
                continue
            if _evidence_ref_valid_from_facts(
                reference,
                context.workspace,
                context.lexical_workspace,
                source_ids=context.source_ids,
                source_context_valid=context.source_context_valid,
                payload_by_path=context.payload_by_path,
            ):
                continue
            context.result.fail(
                code="REVISIT_TRIGGER_EVIDENCE_MISSING",
                message=(
                    "fired trigger evidence reference is not currently valid"
                ),
                path=(
                    f"cycle.intake.triggers[{trigger_index}]"
                    f".evidence_refs[{reference_index}]"
                ),
                evidence=trigger["trigger_id"],
            )


def _evaluate_claim_freshness(context: _ReadinessContext) -> None:
    _append_revisit_issues(
        context.result,
        derive_claim_issues(context.cycle),
    )
    if context.cycle["decision_assessment"] is None and not any(
        issue.code == "REVISIT_CLAIM_UNRESOLVED"
        for issue in context.result.failures
    ):
        context.result.fail(
            code="REVISIT_CYCLE_MALFORMED",
            message="pre-report readiness requires a decision assessment",
            path="cycle.decision_assessment",
        )
    _append_revisit_issues(
        context.result,
        derive_freshness_issues(context.cycle),
    )

    for resolution_index, resolution in enumerate(
        context.cycle["claim_resolutions"]
    ):
        status = resolution["status"]
        checks = []
        if status in {"confirmed", "weakened"}:
            checks.append(
                (
                    "current_evidence_refs",
                    "REVISIT_FRESHNESS_SUPPORT_INVALID",
                    "positive claim support evidence reference is not currently valid",
                )
            )
        if status in {"weakened", "refuted"}:
            checks.append(
                (
                    "counter_evidence_refs",
                    "REVISIT_COUNTER_EVIDENCE_INVALID",
                    "claim counter-evidence reference is not currently valid",
                )
            )
        for field_name, code, message in checks:
            for reference_index, reference in enumerate(
                resolution[field_name]
            ):
                if (
                    reference.get("kind") == "source"
                    and not context.source_context_valid
                ):
                    continue
                if _evidence_ref_valid_from_facts(
                    reference,
                    context.workspace,
                    context.lexical_workspace,
                    source_ids=context.source_ids,
                    source_context_valid=context.source_context_valid,
                    payload_by_path=context.payload_by_path,
                ):
                    continue
                context.result.fail(
                    code=code,
                    message=message,
                    path=(
                        f"cycle.claim_resolutions[{resolution_index}]"
                        f".{field_name}[{reference_index}]"
                    ),
                    evidence=resolution["claim_id"],
                )


def _evaluate_frontier_registry(context: _ReadinessContext) -> None:
    if context.registry_error is not None:
        context.result.fail(
            code="REVISIT_FRONTIER_REGISTRY_MALFORMED",
            message=str(context.registry_error),
            path="frontier_registry.json",
        )
        return
    if context.registry_payload is None:
        context.result.fail(
            code="FRONTIER_REGISTRY_MISSING",
            message=(
                "frontier_registry.json is required for revisit readiness"
            ),
            path="frontier_registry.json",
        )
        return
    facts = _frontier_facts(context)
    if facts is not None:
        _append_revisit_issues(
            context.result,
            _derive_revisit_registry_issues_from_facts(facts),
        )


def _evaluate_frontier_research_floor(
    context: _ReadinessContext,
) -> None:
    facts = _frontier_facts(context)
    if facts is not None:
        _append_revisit_issues(
            context.result,
            _derive_revisit_frontier_progress_issues_from_facts(facts),
        )


def _evaluate_search_coverage(context: _ReadinessContext) -> None:
    if context.search_error is not None:
        context.result.fail(
            code="SEARCH_LOG_INVALID",
            message=(
                "search_log.jsonl must be valid UTF-8 JSONL with one "
                "object per non-blank line"
            ),
            path="search_log.jsonl",
            evidence=str(context.search_error),
        )
        return

    state_loop_count = (
        context.state_facts.loop_count
        if context.state_facts is not None
        else 0
    )
    covered_loop_ids, has_any_valid = _search_facts_from_records(
        context.search_records or ()
    )
    if state_loop_count > 0:
        if has_any_valid:
            expected_loop_ids = {
                f"loop_{index}"
                for index in range(1, state_loop_count + 1)
            }
            missing_loop_ids = sorted(
                expected_loop_ids - covered_loop_ids
            )
            if missing_loop_ids:
                context.result.fail(
                    code="SEARCH_LOG_LOOP_COVERAGE_MISSING",
                    message=(
                        "each completed loop requires its own valid "
                        "search_log.jsonl record; loops without a valid "
                        f"search record: {', '.join(missing_loop_ids)}"
                    ),
                    path="search_log.jsonl",
                    evidence=(
                        f"covered loops: "
                        f"{sorted(covered_loop_ids) or 'none'}; "
                        f"missing loops: {missing_loop_ids}"
                    ),
                )
        else:
            context.result.fail(
                code="SEARCH_LOG_MISSING",
                message=(
                    "completed loops require valid search_log.jsonl records"
                ),
                path="search_log.jsonl",
                evidence="no valid search record found",
            )

    facts = _frontier_facts(context)
    if facts is not None:
        _append_revisit_issues(
            context.result,
            _derive_revisit_search_floor_issues_from_facts(facts),
        )


def _evaluate_dispatch_delivery(context: _ReadinessContext) -> None:
    if context.dispatch_error is not None:
        context.result.fail(
            code="DISPATCH_LOG_INVALID",
            message=(
                "dispatch_log.jsonl must be valid JSONL with one object "
                "per non-blank line"
            ),
            path="dispatch_log.jsonl",
            evidence=str(context.dispatch_error),
        )
        return

    _check_dispatch_documents(
        records=context.dispatch_records or (),
        workflow_text=(
            context.workflow_facts.text
            if context.workflow_facts is not None
            else None
        ),
        profile=ContractProfile(
            mode="ticker",
            target="revisit_report",
        ),
        worker_output_paths=context.worker_output_paths,
        delivered_payloads=context.delivered_payloads,
        result=context.result,
        workspace=context.workspace,
        lexical_workspace=context.lexical_workspace,
    )

    facts = _frontier_facts(context)
    if facts is not None:
        _append_revisit_issues(
            context.result,
            _derive_revisit_dispatch_floor_issues_from_facts(facts),
        )


def _evaluate_worker_outputs(context: _ReadinessContext) -> None:
    for relative_path, message in context.worker_output_errors:
        context.result.fail(
            code="WORKER_OUTPUT_INVALID",
            message=f"worker output is invalid or unreadable: {message}",
            path=relative_path,
        )
    delivered_roles = (
        _delivered_roles_from_records(context.dispatch_records)
        if context.dispatch_records is not None
        else None
    )
    _check_worker_output_documents(
        outputs=context.worker_outputs,
        delivered_roles=delivered_roles,
        registered_source_ids=(
            context.source_ids
            if context.source_context_valid
            else None
        ),
        profile=ContractProfile(
            mode="ticker",
            target="revisit_report",
        ),
        result=context.result,
    )


def _evaluate_source_cache(context: _ReadinessContext) -> None:
    if context.source_evaluation is None:
        return
    for issue in context.source_evaluation.issues:
        context.result.fail(
            code=issue.code,
            message=issue.message,
            path=issue.location,
        )
    for warning in context.source_evaluation.warnings:
        context.result.warn(
            code=warning.code,
            message=warning.message,
            path=warning.location,
        )


def _evaluate_generation_closure(context: _ReadinessContext) -> None:
    context.closure = context.session.freeze()


def _evaluate_route_and_effect_parity(
    context: _ReadinessContext,
) -> None:
    visited = tuple(entry.requirement_id for entry in context.trace)
    if visited != REVISIT_REQUIREMENT_IDS[:-1]:
        raise ReadinessPlanError(
            "route/effect invariant observed an incomplete readiness trace"
        )
    if context.closure is None:
        raise ReadinessPlanError(
            "route/effect invariant requires a frozen generation closure"
        )
    _make_revisit_check_outcome(
        context.result,
        context.selected_cycle,
    )


_ALLOWED_PREREQUISITES = frozenset(
    {"ticker_mode", "cycle"}
)


_READINESS_PLAN = (
    _ReadinessRequirement(
        "core_state_workflow",
        (_evaluate_core_state_workflow,),
        (),
    ),
    _ReadinessRequirement(
        "global_cycle_history",
        (_evaluate_global_cycle_history,),
        ("ticker_mode",),
    ),
    _ReadinessRequirement(
        "intake_provenance",
        (_evaluate_intake_provenance,),
        ("ticker_mode", "cycle"),
    ),
    _ReadinessRequirement(
        "trigger_evidence",
        (_evaluate_trigger_evidence,),
        ("ticker_mode", "cycle"),
    ),
    _ReadinessRequirement(
        "claim_freshness",
        (_evaluate_claim_freshness,),
        ("ticker_mode", "cycle"),
    ),
    _ReadinessRequirement(
        "frontier_registry",
        (_evaluate_frontier_registry,),
        ("ticker_mode",),
    ),
    _ReadinessRequirement(
        "frontier_research_floor",
        (_evaluate_frontier_research_floor,),
        ("ticker_mode", "cycle"),
    ),
    _ReadinessRequirement(
        "search_coverage",
        (_evaluate_search_coverage,),
        ("ticker_mode",),
    ),
    _ReadinessRequirement(
        "dispatch_delivery",
        (_evaluate_dispatch_delivery,),
        ("ticker_mode",),
    ),
    _ReadinessRequirement(
        "worker_outputs",
        (_evaluate_worker_outputs,),
        ("ticker_mode",),
    ),
    _ReadinessRequirement(
        "source_cache",
        (_evaluate_source_cache,),
        (),
    ),
    _ReadinessRequirement(
        "generation_closure",
        (_evaluate_generation_closure,),
        (),
    ),
    _ReadinessRequirement(
        "route_and_effect_parity",
        (_evaluate_route_and_effect_parity,),
        (),
        invariant=True,
    ),
)


def _verify_plan_shape(plan) -> None:
    rows = tuple(plan)
    requirement_ids = tuple(
        getattr(row, "requirement_id", None) for row in rows
    )
    expected = REVISIT_REQUIREMENT_IDS
    violations: list[str] = []

    missing = tuple(
        requirement_id
        for requirement_id in expected
        if requirement_id not in requirement_ids
    )
    if missing:
        violations.append(f"missing rows: {', '.join(missing)}")

    unknown = tuple(
        requirement_id
        for requirement_id in requirement_ids
        if requirement_id not in expected
    )
    if unknown:
        violations.append(
            "unknown rows: "
            + ", ".join(str(requirement_id) for requirement_id in unknown)
        )

    duplicate = tuple(
        requirement_id
        for requirement_id in expected
        if requirement_ids.count(requirement_id) > 1
    )
    if duplicate:
        violations.append(
            f"duplicate rows: {', '.join(duplicate)}"
        )

    if requirement_ids != expected:
        violations.append("wrong-order rows")

    for row in rows:
        requirement_id = str(
            getattr(row, "requirement_id", "<unknown>")
        )
        handlers = getattr(row, "handlers", ())
        if not isinstance(handlers, tuple) or len(handlers) == 0:
            violations.append(f"unowned row: {requirement_id}")
        elif len(handlers) > 1:
            violations.append(f"multi-owned row: {requirement_id}")
        elif not callable(handlers[0]):
            violations.append(f"unowned row: {requirement_id}")

        prerequisites = getattr(row, "prerequisites", None)
        if not isinstance(prerequisites, tuple):
            violations.append(
                f"invalid prerequisites for row: {requirement_id}"
            )
        else:
            unknown_prerequisites = tuple(
                prerequisite
                for prerequisite in prerequisites
                if prerequisite not in _ALLOWED_PREREQUISITES
            )
            if unknown_prerequisites:
                violations.append(
                    "unknown prerequisites for row "
                    f"{requirement_id}: "
                    + ", ".join(unknown_prerequisites)
                )

        expected_invariant = (
            requirement_id == "route_and_effect_parity"
        )
        if bool(getattr(row, "invariant", False)) != expected_invariant:
            violations.append(
                f"invalid invariant ownership for row: {requirement_id}"
            )

    if violations:
        raise ReadinessPlanError(
            "invalid readiness plan: " + "; ".join(violations)
        )


def _run_readiness_plan(
    context: _ReadinessContext,
    plan=None,
) -> None:
    rows = _READINESS_PLAN if plan is None else tuple(plan)
    for row in rows:
        if any(
            not context.prerequisite_status.get(prerequisite, False)
            for prerequisite in row.prerequisites
        ):
            status: _TraceStatus = "skipped"
        else:
            row.handlers[0](context)
            status = "invariant" if row.invariant else "evaluated"
        context.trace.append(
            _ReadinessTraceEntry(
                requirement_id=row.requirement_id,
                status=status,
            )
        )


def _prepare_readiness_context(
    context: _ReadinessContext,
) -> _PreparedRevisitReadiness:
    """Load facts once, execute every fixed requirement row, then freeze."""
    _load_readiness_facts(context)
    _run_readiness_plan(context, _READINESS_PLAN)
    if context.closure is None:
        raise ReadinessPlanError(
            "readiness plan completed without a generation closure"
        )
    return _PreparedRevisitReadiness(
        result=context.result,
        selected_cycle=context.selected_cycle,
        closure=context.closure,
        trace=tuple(context.trace),
    )


def _prepare_revisit_readiness(
    session: ObservedReadSession,
    result: ContractResult,
    named_cycle_id: str | None,
    lexical_workspace: Path,
) -> _PreparedRevisitReadiness:
    return _prepare_readiness_context(
        _ReadinessContext(
            session=session,
            result=result,
            named_cycle_id=named_cycle_id,
            lexical_workspace=lexical_workspace,
            workspace=session._workspace,
        )
    )


def _prepare_published_current_readiness(
    session: ObservedReadSession,
    result: ContractResult,
    cycle_id: str,
    lexical_workspace: Path,
) -> _PreparedRevisitReadiness:
    """Run the existing plan for one exact completed current cycle lineage."""
    return _prepare_readiness_context(
        _ReadinessContext(
            session=session,
            result=result,
            named_cycle_id=None,
            lexical_workspace=lexical_workspace,
            workspace=session._workspace,
            published_current_cycle_id=cycle_id,
        )
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
    _verify_plan_shape(_READINESS_PLAN)
    root = Path(workspace)
    result = ContractResult()
    session = ObservedReadSession(root)
    try:
        prepared = _prepare_revisit_readiness(session, result, cycle_id, root)
        closure = prepared.closure
    except AuthorityDriftError as exc:
        result.fail(
            code="REVISIT_AUTHORITY_DRIFT",
            message=str(exc),
            path=exc.drift.relative_path,
        )
        return result

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
    _verify_plan_shape(_READINESS_PLAN)
    _validate_canonical_timestamp(timestamp)
    result = ContractResult()
    lexical_workspace = Path(workspace)
    with workspace_transaction(workspace) as locked_workspace:
        session = ObservedReadSession(locked_workspace)
        prepared = _prepare_revisit_readiness(
            session,
            result,
            cycle_id,
            lexical_workspace,
        )
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
            return _make_revisit_check_outcome(
                result,
                prepared.selected_cycle,
            )

        outcome = _make_revisit_check_outcome(
            result,
            prepared.selected_cycle,
        )
        if outcome.effect == RevisitCheckEffect.BLOCKED:
            return outcome

        selected_cycle = prepared.selected_cycle
        if selected_cycle is None:
            raise ReadinessPlanError(
                "non-blocked effect lacks a complete selected cycle"
            )
        if outcome.effect == RevisitCheckEffect.UNCHANGED_READY:
            # Byte-preserving no-op: recheck the complete unexcluded closure
            # exactly once (already done above) and return without rendering,
            # writing, or appending an audit entry.
            return outcome

        # TRANSITIONED: active -> ready_for_report with one ``check`` audit at
        # the supplied timestamp. Persistence delegates to ``persist_cycle``
        # with the frozen closure so the store rechecks the non-excluded
        # closure before+after the write and derives the cycle/mirror
        # exclusions itself.
        cycle = selected_cycle.cycle
        proposed = mark_ready_for_report(cycle)
        updated = with_audit(
            cycle,
            proposed,
            "check",
            [selected_cycle.cycle_id],
            timestamp,
        )
        try:
            persist_cycle(
                locked_workspace,
                updated,
                expected_sha256=selected_cycle.cycle_sha256,
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
            return _make_revisit_check_outcome(
                result,
                selected_cycle,
            )
        return outcome


# Import helpers only to expose them for the read-only seam and tests.
__all__ = [
    "REVISIT_REQUIREMENT_IDS",
    "ReadinessPlanError",
    "RevisitCheckEffect",
    "RevisitCheckOutcome",
    "check_revisit_readiness",
    "evaluate_revisit_readiness",
]
