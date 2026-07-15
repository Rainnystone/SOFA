from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1
POINTER_FILENAME = "revisit_contract.json"
CYCLES_DIRNAME = "revisit_cycles"
ACTION_CLASSES = (
    "Act",
    "Watch with Trigger",
    "Trade-only",
    "Basket-only",
    "Reject",
    "Needs Primary Evidence",
)
CYCLE_STATUSES = ("active", "ready_for_report", "completed", "aborted")
TERMINAL_CYCLE_STATUSES = frozenset({"completed", "aborted"})
TRIGGER_KINDS = ("upgrade", "downgrade", "invalidation")
SELECTION_REASONS = (
    "trigger_affected",
    "decision_load_bearing",
    "stale_but_reused",
)
CLAIM_IMPORTANCE = ("critical", "high", "medium", "low")
CLAIM_TERMINAL_STATES = ("confirmed", "weakened", "refuted", "split", "blocked")
CURRENT_GRADES = ("A", "B", "C", "D")
CURRENT_CONFIDENCE = ("high", "medium", "low", "speculative")
FRESHNESS = ("fresh", "stale", "unknown")
_CHANGE_CLASSES = (
    "evidence_or_claim_only",
    "financial_or_risk_change",
    "action_class_change",
)
_REQUIRED_RERUNS = (
    "delta-frontier-review",
    "affected-financial-bridge",
    "full-financial-bridge",
    "redteam-round-1",
    "redteam-defense-1",
    "redteam-round-2",
    "redteam-defense-2",
    "thesis-revision",
)
_RERUN_SCOPES = ("affected", "full")
CYCLE_ID_RE = re.compile(r"^RC-(?P<number>[0-9]{4})$")
REVISION_ID_RE = re.compile(r"^REV-(?P<number>[0-9]{4})$")
TRIGGER_ID_RE = re.compile(
    r"^(?P<cycle>RC-[0-9]{4})-TRG-(?P<number>[0-9]{2})$"
)
CLAIM_ID_RE = re.compile(r"^(?P<cycle>RC-[0-9]{4})-CL-(?P<number>[0-9]{2})$")
DERIVED_CLAIM_ID_RE = re.compile(
    r"^(?P<cycle>RC-[0-9]{4})-DC-(?P<number>[0-9]{2})$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^src-[0-9]{3,}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
CYCLE_KEYS = {
    "schema_version",
    "cycle_id",
    "candidate_revision_id",
    "status",
    "created_at",
    "completed_at",
    "aborted_at",
    "abort_reason",
    "intake_sha256",
    "intake",
    "frontier_bindings",
    "claim_resolutions",
    "derived_claims",
    "decision_assessment",
    "rerun_artifacts",
    "report_candidate",
    "audit",
}
SOURCE_EVIDENCE_KEYS = frozenset({"kind", "source_id", "checked_at"})
ARTIFACT_EVIDENCE_KEYS = frozenset(
    {"kind", "path", "sha256", "locator", "checked_at"}
)
_REQUEST_TRIGGER_KEYS = {
    "kind",
    "statement",
    "observed_at",
    "evidence_refs",
}
_REQUEST_CLAIM_KEYS = {
    "statement",
    "source_ref",
    "importance",
    "selection_reasons",
    "trigger_indexes",
    "inherited_grade",
    "inherited_confidence",
    "inherited_evidence",
}
_CLAIM_SOURCE_REF_KEYS = {"path", "sha256", "locator", "historical_claim_id"}
_INHERITED_EVIDENCE_KEYS = {"ref", "freshness", "checked_at", "reason"}
_CLAIM_RESOLUTION_STATES = (
    "inherited-pending-reverification",
    *CLAIM_TERMINAL_STATES,
)


@dataclass(frozen=True)
class RevisitIssue:
    code: str
    path: str
    message: str
    evidence: str = ""


@dataclass(frozen=True)
class RevisitHistoryFact:
    current_revision_number: int | None
    ordered_cycle_ids: tuple[str, ...]
    max_cycle_number: int
    max_revision_number: int
    nonterminal_cycle_ids: tuple[str, ...]
    completed_unpublished_cycle_ids: tuple[str, ...]
    issues: tuple[RevisitIssue, ...]

    def require_valid(self) -> None:
        if not self.issues:
            return
        issue = self.issues[0]
        detail = issue.message
        if issue.evidence:
            detail = f"{detail}: {issue.evidence}"
        raise RevisitContractError(detail)


class RevisitContractError(ValueError):
    pass


def empty_pointer() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "mode": "ticker", "current_revision": None}


def _require_exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise RevisitContractError(f"{path} missing field(s): {', '.join(missing)}")
    if unknown:
        raise RevisitContractError(f"{path} unknown field(s): {', '.join(unknown)}")


def _require_strict_int(value: Any, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RevisitContractError(f"{path} must be an integer >= {minimum}")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise RevisitContractError(f"{path} must be a boolean")
    return value


def _require_revision_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or REVISION_ID_RE.fullmatch(value) is None:
        raise RevisitContractError(f"{path} must match REV-NNNN")
    return value


def _require_cycle_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or CYCLE_ID_RE.fullmatch(value) is None:
        raise RevisitContractError(f"{path} must match RC-NNNN")
    return value


def _require_trigger_id(value: Any, path: str, cycle_id: str) -> str:
    match = TRIGGER_ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RevisitContractError(f"{path} must match RC-NNNN-TRG-NN")
    if match.group("cycle") != cycle_id:
        raise RevisitContractError(f"{path} must belong to cycle {cycle_id}")
    return value


def _require_claim_id(value: Any, path: str, cycle_id: str) -> str:
    match = CLAIM_ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RevisitContractError(f"{path} must match RC-NNNN-CL-NN")
    if match.group("cycle") != cycle_id:
        raise RevisitContractError(f"{path} must belong to cycle {cycle_id}")
    return value


def _require_derived_claim_id(value: Any, path: str, cycle_id: str) -> str:
    match = DERIVED_CLAIM_ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise RevisitContractError(f"{path} must match RC-NNNN-DC-NN")
    if match.group("cycle") != cycle_id:
        raise RevisitContractError(f"{path} must belong to cycle {cycle_id}")
    return value


def _require_any_claim_id(value: Any, path: str, cycle_id: str) -> str:
    for pattern in (CLAIM_ID_RE, DERIVED_CLAIM_ID_RE):
        match = pattern.fullmatch(value) if isinstance(value, str) else None
        if match is not None:
            if match.group("cycle") != cycle_id:
                raise RevisitContractError(f"{path} must belong to cycle {cycle_id}")
            return value
    raise RevisitContractError(
        f"{path} must match RC-NNNN-CL-NN or RC-NNNN-DC-NN"
    )


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _require_non_empty_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise RevisitContractError(f"{path} must be non-empty text")
    if _contains_control_character(value):
        raise RevisitContractError(f"{path} must not contain control characters")
    return value


def _require_nullable_text(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RevisitContractError(f"{path} must be non-empty text or null")
    if _contains_control_character(value):
        raise RevisitContractError(f"{path} must not contain control characters")
    return value


def _require_sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RevisitContractError(f"{path} must be a lowercase SHA-256")
    return value


def _require_source_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SOURCE_ID_RE.fullmatch(value) is None:
        raise RevisitContractError(f"{path} must match src-NNN")
    return value


def _require_utc_timestamp(value: Any, path: str) -> str:
    value = _require_non_empty_text(value, path)
    if _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise RevisitContractError(f"{path} must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise RevisitContractError(
            f"{path} must be YYYY-MM-DDTHH:MM:SSZ"
        ) from error
    return value


def _require_observed_at(value: Any, path: str) -> str:
    value = _require_non_empty_text(value, path)
    format_string = None
    if _ISO_DATE_RE.fullmatch(value) is not None:
        format_string = "%Y-%m-%d"
    elif _UTC_TIMESTAMP_RE.fullmatch(value) is not None:
        format_string = "%Y-%m-%dT%H:%M:%SZ"
    if format_string is not None:
        try:
            datetime.strptime(value, format_string)
            return value
        except ValueError:
            pass
    raise RevisitContractError(
        f"{path} must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ"
    )


def _validate_revision(raw: Any, path: str) -> None:
    if not isinstance(raw, dict):
        raise RevisitContractError(f"{path} must be an object")
    _require_exact_keys(
        raw,
        {
            "revision_id",
            "cycle_id",
            "report_path",
            "report_sha256",
            "action_class",
            "validated_at",
            "revision_of",
        },
        path,
    )
    _require_revision_id(raw["revision_id"], f"{path}.revision_id")
    if raw["cycle_id"] is not None:
        _require_cycle_id(raw["cycle_id"], f"{path}.cycle_id")
    if raw["revision_of"] is not None:
        _require_revision_id(raw["revision_of"], f"{path}.revision_of")
    if (raw["cycle_id"] is None) != (raw["revision_of"] is None):
        raise RevisitContractError(
            f"{path}.cycle_id and revision_of must both be null or both be IDs"
        )
    if (
        raw["cycle_id"] is None
        and raw["revision_of"] is None
        and raw["revision_id"] != "REV-0001"
    ):
        raise RevisitContractError("initial registration revision_id must be REV-0001")
    _require_non_empty_text(raw["report_path"], f"{path}.report_path")
    _require_sha256(raw["report_sha256"], f"{path}.report_sha256")
    if raw["action_class"] not in ACTION_CLASSES:
        raise RevisitContractError(f"{path}.action_class is unsupported")
    _require_utc_timestamp(raw["validated_at"], f"{path}.validated_at")


def validate_pointer(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RevisitContractError("revisit_contract.json must contain an object")
    _require_exact_keys(raw, {"schema_version", "mode", "current_revision"}, "pointer")
    if _require_strict_int(raw["schema_version"], "pointer.schema_version", 1) != 1:
        raise RevisitContractError("unsupported pointer schema_version")
    if raw["mode"] != "ticker":
        raise RevisitContractError("pointer.mode must be ticker")
    if raw["current_revision"] is not None:
        _validate_revision(raw["current_revision"], "pointer.current_revision")
    return raw


def canonical_semantic_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_semantic_bytes(value)).hexdigest()


def state_without_audit(cycle: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(cycle)
    state.pop("audit", None)
    return state


def cycle_state_sha256(cycle: dict[str, Any]) -> str:
    return semantic_sha256(state_without_audit(cycle))


def evaluate_history(
    pointer: dict[str, Any], cycles: list[dict[str, Any]]
) -> RevisitHistoryFact:
    validate_pointer(pointer)
    if not isinstance(cycles, list):
        raise RevisitContractError("cycles must be a list")
    for cycle in cycles:
        validate_cycle(cycle)
    ordered = sorted(
        cycles,
        key=lambda cycle: int(
            CYCLE_ID_RE.fullmatch(cycle["cycle_id"]).group("number")
        ),
    )
    current = pointer["current_revision"]
    current_revision_number = (
        int(REVISION_ID_RE.fullmatch(current["revision_id"]).group("number"))
        if current is not None
        else None
    )
    max_cycle_number = max(
        (
            int(CYCLE_ID_RE.fullmatch(cycle["cycle_id"]).group("number"))
            for cycle in ordered
        ),
        default=0,
    )
    max_revision_number = max(
        (
            int(
                REVISION_ID_RE.fullmatch(
                    cycle["candidate_revision_id"]
                ).group("number")
            )
            for cycle in ordered
        ),
        default=current_revision_number or 0,
    )
    if current_revision_number is not None:
        max_revision_number = max(max_revision_number, current_revision_number)
    nonterminal_cycle_ids = tuple(
        cycle["cycle_id"]
        for cycle in ordered
        if cycle["status"] in {"active", "ready_for_report"}
    )
    completed_unpublished_cycle_ids = tuple(
        cycle["cycle_id"]
        for cycle in ordered
        if cycle["status"] == "completed"
        and current_revision_number is not None
        and int(
            REVISION_ID_RE.fullmatch(
                cycle["candidate_revision_id"]
            ).group("number")
        ) > current_revision_number
    )
    issues: list[RevisitIssue] = []
    if current is None and ordered:
        issues.append(
            RevisitIssue(
                "history_without_current_revision",
                "pointer.current_revision",
                "cycle history exists without a current revision",
                ", ".join(cycle["cycle_id"] for cycle in ordered),
            )
        )
    reservations: dict[str, list[str]] = {}
    for cycle in ordered:
        reservations.setdefault(cycle["candidate_revision_id"], []).append(
            cycle["cycle_id"]
        )
    for revision_id in sorted(
        reservations,
        key=lambda value: int(
            REVISION_ID_RE.fullmatch(value).group("number")
        ),
    ):
        reserved_by = reservations[revision_id]
        if len(reserved_by) > 1:
            issues.append(
                RevisitIssue(
                    "duplicate_candidate_revision",
                    "cycles.candidate_revision_id",
                    f"candidate revision {revision_id} is reserved by multiple cycles",
                    ", ".join(reserved_by),
                )
            )

    prior_cycle = None
    prior_revision_number = None
    for cycle in ordered:
        revision_number = int(
            REVISION_ID_RE.fullmatch(
                cycle["candidate_revision_id"]
            ).group("number")
        )
        if (
            prior_revision_number is not None
            and revision_number < prior_revision_number
        ):
            issues.append(
                RevisitIssue(
                    "candidate_revision_order",
                    "cycles.candidate_revision_id",
                    "candidate revisions must increase with cycle allocation order",
                    (
                        f"{prior_cycle} -> {cycle['cycle_id']} "
                        f"({prior_revision_number} -> {revision_number})"
                    ),
                )
            )
            break
        prior_cycle = cycle["cycle_id"]
        prior_revision_number = revision_number

    if len(nonterminal_cycle_ids) > 1:
        issues.append(
            RevisitIssue(
                "multiple_nonterminal_cycles",
                "cycles.status",
                "more than one active or ready cycle",
                ", ".join(nonterminal_cycle_ids),
            )
        )
    if nonterminal_cycle_ids and completed_unpublished_cycle_ids:
        issues.append(
            RevisitIssue(
                "nonterminal_with_unpublished",
                "cycles.status",
                "active or ready cycle cannot coexist with completed-unpublished",
                (
                    f"nonterminal={','.join(nonterminal_cycle_ids)}; "
                    f"unpublished={','.join(completed_unpublished_cycle_ids)}"
                ),
            )
        )
    if len(completed_unpublished_cycle_ids) > 1:
        issues.append(
            RevisitIssue(
                "multiple_unpublished_cycles",
                "cycles.status",
                "more than one completed-unpublished cycle",
                ", ".join(completed_unpublished_cycle_ids),
            )
        )

    if current is not None:
        equal_completed = tuple(
            cycle
            for cycle in ordered
            if cycle["status"] == "completed"
            and cycle["candidate_revision_id"] == current["revision_id"]
        )
        conflicting_equal = tuple(
            cycle["cycle_id"]
            for cycle in equal_completed
            if cycle["cycle_id"] != current["cycle_id"]
        )
        if conflicting_equal:
            issues.append(
                RevisitIssue(
                    "current_candidate_cycle_conflict",
                    "pointer.current_revision.cycle_id",
                    "completed current candidate conflicts with pointer cycle lineage",
                    (
                        f"pointer={current['cycle_id']}; "
                        f"completed={','.join(conflicting_equal)}"
                    ),
                )
            )
        if current["cycle_id"] is not None:
            matching_completed = any(
                cycle["status"] == "completed"
                and cycle["cycle_id"] == current["cycle_id"]
                and cycle["candidate_revision_id"] == current["revision_id"]
                for cycle in ordered
            )
            if not matching_completed:
                issues.append(
                    RevisitIssue(
                        "current_lineage_missing",
                        "pointer.current_revision",
                        "current pointer has no matching completed cycle",
                        (
                            f"{current['cycle_id']} / "
                            f"{current['revision_id']}"
                        ),
                    )
                )

    return RevisitHistoryFact(
        current_revision_number=current_revision_number,
        ordered_cycle_ids=tuple(cycle["cycle_id"] for cycle in ordered),
        max_cycle_number=max_cycle_number,
        max_revision_number=max_revision_number,
        nonterminal_cycle_ids=nonterminal_cycle_ids,
        completed_unpublished_cycle_ids=completed_unpublished_cycle_ids,
        issues=tuple(issues),
    )


def with_audit(
    previous: dict[str, Any],
    updated: dict[str, Any],
    command: str,
    affected_ids: list[str],
    timestamp: str,
) -> dict[str, Any]:
    validate_cycle(previous)
    result = copy.deepcopy(updated)
    audit_prefix = copy.deepcopy(previous["audit"])
    result["audit"] = audit_prefix
    pre_state_sha256 = (
        audit_prefix[-1]["post_state_sha256"]
        if audit_prefix
        else semantic_sha256(None)
    )
    result["audit"].append(
        {
            "sequence": len(audit_prefix) + 1,
            "timestamp": timestamp,
            "command": command,
            "affected_ids": copy.deepcopy(affected_ids),
            "pre_state_sha256": pre_state_sha256,
            "post_state_sha256": cycle_state_sha256(result),
        }
    )
    validate_cycle(result)
    return result


def intake_sha256(intake: dict[str, Any]) -> str:
    return semantic_sha256(intake)


def allocate_cycle_and_revision_ids(
    pointer: dict[str, Any], cycles: list[dict[str, Any]]
) -> tuple[str, str]:
    history = evaluate_history(pointer, cycles)
    history.require_valid()
    next_cycle_number = history.max_cycle_number + 1
    next_revision_number = history.max_revision_number + 1
    if next_cycle_number > 9999:
        raise RevisitContractError("cycle ID space is exhausted")
    if next_revision_number > 9999:
        raise RevisitContractError("revision ID space is exhausted")
    return (
        f"RC-{next_cycle_number:04d}",
        f"REV-{next_revision_number:04d}",
    )


def create_cycle(
    *,
    cycle_id: str,
    candidate_revision_id: str,
    base_revision: dict[str, Any],
    framing_sha256: str,
    framing_snapshot: dict[str, Any],
    frontier_registry_sha256: str,
    max_existing_loop_number: int,
    request: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    _require_cycle_id(cycle_id, "cycle_id")
    _require_revision_id(candidate_revision_id, "candidate_revision_id")
    _validate_revision(base_revision, "base_revision")
    _require_sha256(framing_sha256, "framing_sha256")
    _require_sha256(frontier_registry_sha256, "frontier_registry_sha256")
    _require_strict_int(
        max_existing_loop_number, "max_existing_loop_number"
    )
    _require_utc_timestamp(timestamp, "timestamp")
    validate_intake_request(request)

    triggers = []
    trigger_ids = []
    for index, request_trigger in enumerate(request["triggers"], start=1):
        trigger_id = f"{cycle_id}-TRG-{index:02d}"
        trigger_ids.append(trigger_id)
        trigger = copy.deepcopy(request_trigger)
        trigger["trigger_id"] = trigger_id
        triggers.append(trigger)

    selected_claims = []
    claim_resolutions = []
    for index, request_claim in enumerate(request["selected_claims"], start=1):
        claim_id = f"{cycle_id}-CL-{index:02d}"
        claim = copy.deepcopy(request_claim)
        indexes = claim.pop("trigger_indexes")
        claim["claim_id"] = claim_id
        claim["trigger_ids"] = [trigger_ids[item - 1] for item in indexes]
        selected_claims.append(claim)
        claim_resolutions.append(
            {
                "claim_id": claim_id,
                "status": "inherited-pending-reverification",
                "revised_statement": None,
                "current_evidence_refs": [],
                "counter_evidence_refs": [],
                "current_grade": None,
                "current_confidence": None,
                "bound_frontier_ids": [],
                "rationale": None,
                "missing_proof": None,
                "attempted_loop_ids": [],
                "attempted_search_refs": [],
                "verdict_impact": None,
                "split_child_ids": [],
            }
        )

    intake = {
        "base_revision": {
            "revision_id": base_revision["revision_id"],
            "report_path": base_revision["report_path"],
            "report_sha256": base_revision["report_sha256"],
            "action_class": base_revision["action_class"],
        },
        "framing": {
            "path": "framing_contract.json",
            "sha256": framing_sha256,
            "snapshot": copy.deepcopy(framing_snapshot),
        },
        "workspace_boundary": {
            "frontier_registry_sha256": frontier_registry_sha256,
            "max_existing_loop_number": max_existing_loop_number,
        },
        "triggers": triggers,
        "selected_claims": selected_claims,
    }
    cycle = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "candidate_revision_id": candidate_revision_id,
        "status": "active",
        "created_at": timestamp,
        "completed_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "intake_sha256": intake_sha256(intake),
        "intake": intake,
        "frontier_bindings": [],
        "claim_resolutions": claim_resolutions,
        "derived_claims": [],
        "decision_assessment": None,
        "rerun_artifacts": [],
        "report_candidate": None,
        "audit": [],
    }
    affected_ids = [
        cycle_id,
        candidate_revision_id,
        *trigger_ids,
        *(claim["claim_id"] for claim in selected_claims),
    ]
    cycle["audit"] = [
        {
            "sequence": 1,
            "timestamp": timestamp,
            "command": "start",
            "affected_ids": affected_ids,
            "pre_state_sha256": semantic_sha256(None),
            "post_state_sha256": cycle_state_sha256(cycle),
        }
    ]
    validate_cycle(cycle)
    return cycle


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RevisitContractError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise RevisitContractError(f"{path} must be a list")
    return value


def _require_unique(values: list[str], path: str, label: str = "IDs") -> None:
    if len(values) != len(set(values)):
        raise RevisitContractError(f"{path} must not contain duplicate {label}")


def validate_evidence_ref(ref: Any, path: str) -> dict[str, Any]:
    raw = _require_object(ref, path)
    kind = raw.get("kind")
    if kind == "source":
        _require_exact_keys(raw, set(SOURCE_EVIDENCE_KEYS), path)
        _require_source_id(raw["source_id"], f"{path}.source_id")
    elif kind == "artifact":
        _require_exact_keys(raw, set(ARTIFACT_EVIDENCE_KEYS), path)
        _require_non_empty_text(raw["path"], f"{path}.path")
        _require_sha256(raw["sha256"], f"{path}.sha256")
        _require_non_empty_text(raw["locator"], f"{path}.locator")
    else:
        raise RevisitContractError(f"{path}.kind must be source or artifact")
    _require_utc_timestamp(raw["checked_at"], f"{path}.checked_at")
    return raw


def _validate_evidence_ref(value: Any, path: str) -> None:
    validate_evidence_ref(value, path)


def validate_intake_request(raw: Any) -> dict[str, Any]:
    path = "request"
    request = _require_object(raw, path)
    _require_exact_keys(request, {"triggers", "selected_claims"}, path)

    triggers = _require_list(request["triggers"], f"{path}.triggers")
    if not triggers:
        raise RevisitContractError("request.triggers must not be empty")
    if len(triggers) > 99:
        raise RevisitContractError("request.triggers cannot exceed 99 entries")
    for index, trigger_value in enumerate(triggers):
        trigger_path = f"{path}.triggers[{index}]"
        trigger = _require_object(trigger_value, trigger_path)
        _require_exact_keys(trigger, _REQUEST_TRIGGER_KEYS, trigger_path)
        if trigger["kind"] not in TRIGGER_KINDS:
            raise RevisitContractError(f"{trigger_path} trigger kind is unsupported")
        _require_non_empty_text(trigger["statement"], f"{trigger_path}.statement")
        _require_observed_at(trigger["observed_at"], f"{trigger_path}.observed_at")
        evidence_path = f"{trigger_path}.evidence_refs"
        evidence_refs = _require_list(trigger["evidence_refs"], evidence_path)
        if not evidence_refs:
            raise RevisitContractError(f"{evidence_path} must not be empty")
        for evidence_index, evidence in enumerate(evidence_refs):
            validate_evidence_ref(evidence, f"{evidence_path}[{evidence_index}]")

    claims = _require_list(request["selected_claims"], f"{path}.selected_claims")
    if not claims:
        raise RevisitContractError("request.selected_claims must not be empty")
    if len(claims) > 99:
        raise RevisitContractError("request.selected_claims cannot exceed 99 entries")
    referenced_trigger_indexes: set[int] = set()
    for index, claim_value in enumerate(claims):
        claim_path = f"{path}.selected_claims[{index}]"
        claim = _require_object(claim_value, claim_path)
        _require_exact_keys(claim, _REQUEST_CLAIM_KEYS, claim_path)
        _require_non_empty_text(claim["statement"], f"{claim_path}.statement")

        source_path = f"{claim_path}.source_ref"
        source = _require_object(claim["source_ref"], source_path)
        _require_exact_keys(source, _CLAIM_SOURCE_REF_KEYS, source_path)
        _require_non_empty_text(source["path"], f"{source_path}.path")
        _require_sha256(source["sha256"], f"{source_path}.sha256")
        _require_non_empty_text(source["locator"], f"{source_path}.locator")
        _require_nullable_text(
            source["historical_claim_id"], f"{source_path}.historical_claim_id"
        )

        if claim["importance"] not in CLAIM_IMPORTANCE:
            raise RevisitContractError(f"{claim_path} claim importance is unsupported")
        reasons_path = f"{claim_path}.selection_reasons"
        reasons = _require_list(claim["selection_reasons"], reasons_path)
        if not reasons:
            raise RevisitContractError(f"{reasons_path} must not be empty")
        for reason in reasons:
            if reason not in SELECTION_REASONS:
                raise RevisitContractError(
                    f"{reasons_path} selection reason is unsupported"
                )
        _require_unique(reasons, reasons_path, "selection reasons")

        indexes_path = f"{claim_path}.trigger_indexes"
        trigger_indexes = _require_list(claim["trigger_indexes"], indexes_path)
        if "trigger_affected" in reasons and not trigger_indexes:
            raise RevisitContractError(
                f"{claim_path} trigger_affected requires non-empty trigger_indexes"
            )
        for trigger_index in trigger_indexes:
            trigger_index = _require_strict_int(trigger_index, indexes_path, 1)
            if trigger_index > len(triggers):
                raise RevisitContractError(
                    f"{indexes_path} trigger index is out of range: {trigger_index}"
                )
            referenced_trigger_indexes.add(trigger_index)
        _require_unique(trigger_indexes, indexes_path, "trigger indexes")

        if (
            claim["inherited_grade"] is not None
            and claim["inherited_grade"] not in CURRENT_GRADES
        ):
            raise RevisitContractError(f"{claim_path}.inherited_grade is unsupported")
        if (
            claim["inherited_confidence"] is not None
            and claim["inherited_confidence"] not in CURRENT_CONFIDENCE
        ):
            raise RevisitContractError(
                f"{claim_path}.inherited_confidence is unsupported"
            )
        inherited_path = f"{claim_path}.inherited_evidence"
        inherited = _require_list(claim["inherited_evidence"], inherited_path)
        for evidence_index, evidence_value in enumerate(inherited):
            evidence_path = f"{inherited_path}[{evidence_index}]"
            evidence = _require_object(evidence_value, evidence_path)
            _require_exact_keys(
                evidence, _INHERITED_EVIDENCE_KEYS, evidence_path
            )
            validate_evidence_ref(evidence["ref"], f"{evidence_path}.ref")
            if evidence["freshness"] not in FRESHNESS:
                raise RevisitContractError(f"{evidence_path}.freshness is unsupported")
            _require_utc_timestamp(
                evidence["checked_at"], f"{evidence_path}.checked_at"
            )
            _require_non_empty_text(evidence["reason"], f"{evidence_path}.reason")

    for trigger_index in range(1, len(triggers) + 1):
        if trigger_index not in referenced_trigger_indexes:
            raise RevisitContractError(
                f"request trigger index {trigger_index} is not referenced by any selected claim"
            )
    return request


def _validate_intake(value: Any, cycle_id: str) -> None:
    path = "cycle.intake"
    raw = _require_object(value, path)
    _require_exact_keys(
        raw,
        {
            "base_revision",
            "framing",
            "workspace_boundary",
            "triggers",
            "selected_claims",
        },
        path,
    )

    base_path = f"{path}.base_revision"
    base = _require_object(raw["base_revision"], base_path)
    _require_exact_keys(
        base,
        {"revision_id", "report_path", "report_sha256", "action_class"},
        base_path,
    )
    _require_revision_id(base["revision_id"], f"{base_path}.revision_id")
    _require_non_empty_text(base["report_path"], f"{base_path}.report_path")
    _require_sha256(base["report_sha256"], f"{base_path}.report_sha256")
    if base["action_class"] not in ACTION_CLASSES:
        raise RevisitContractError(f"{base_path}.action_class is unsupported")

    framing_path = f"{path}.framing"
    framing = _require_object(raw["framing"], framing_path)
    _require_exact_keys(framing, {"path", "sha256", "snapshot"}, framing_path)
    if framing["path"] != "framing_contract.json":
        raise RevisitContractError(
            "cycle.intake.framing.path must be framing_contract.json"
        )
    _require_sha256(framing["sha256"], f"{framing_path}.sha256")
    snapshot_path = f"{framing_path}.snapshot"
    snapshot = _require_object(framing["snapshot"], snapshot_path)
    _require_exact_keys(
        snapshot,
        {
            "subject_resolution",
            "research_posture",
            "time_horizon",
            "market_scope",
            "risk_appetite",
            "output_expectation",
            "report_language",
            "budget_appetite",
        },
        snapshot_path,
    )
    _require_object(
        snapshot["subject_resolution"], f"{snapshot_path}.subject_resolution"
    )
    for field in (
        "research_posture",
        "time_horizon",
        "market_scope",
        "risk_appetite",
        "output_expectation",
        "report_language",
        "budget_appetite",
    ):
        _require_non_empty_text(snapshot[field], f"{snapshot_path}.{field}")
    if snapshot["research_posture"] != "revisit":
        raise RevisitContractError(
            "cycle.intake.framing.snapshot.research_posture must be revisit"
        )

    boundary_path = f"{path}.workspace_boundary"
    boundary = _require_object(raw["workspace_boundary"], boundary_path)
    _require_exact_keys(
        boundary,
        {"frontier_registry_sha256", "max_existing_loop_number"},
        boundary_path,
    )
    _require_sha256(
        boundary["frontier_registry_sha256"],
        f"{boundary_path}.frontier_registry_sha256",
    )
    _require_strict_int(
        boundary["max_existing_loop_number"],
        f"{boundary_path}.max_existing_loop_number",
    )

    triggers_path = f"{path}.triggers"
    triggers = _require_list(raw["triggers"], triggers_path)
    if not triggers:
        raise RevisitContractError("cycle.intake.triggers must not be empty")
    if len(triggers) > 99:
        raise RevisitContractError("cycle.intake.triggers cannot exceed 99 entries")
    expected_trigger_ids = [
        f"{cycle_id}-TRG-{index:02d}" for index in range(1, len(triggers) + 1)
    ]
    for index, trigger_value in enumerate(triggers):
        trigger_path = f"{triggers_path}[{index}]"
        trigger = _require_object(trigger_value, trigger_path)
        _require_exact_keys(
            trigger,
            {"trigger_id", "kind", "statement", "observed_at", "evidence_refs"},
            trigger_path,
        )
        _require_trigger_id(
            trigger["trigger_id"], f"{trigger_path}.trigger_id", cycle_id
        )
        if trigger["kind"] not in TRIGGER_KINDS:
            raise RevisitContractError(f"{trigger_path} trigger kind is unsupported")
        _require_non_empty_text(trigger["statement"], f"{trigger_path}.statement")
        _require_observed_at(trigger["observed_at"], f"{trigger_path}.observed_at")
        evidence_path = f"{trigger_path}.evidence_refs"
        evidence_refs = _require_list(trigger["evidence_refs"], evidence_path)
        if not evidence_refs:
            raise RevisitContractError("trigger evidence_refs must not be empty")
        for evidence_index, evidence in enumerate(evidence_refs):
            _validate_evidence_ref(evidence, f"{evidence_path}[{evidence_index}]")
    if len({trigger["trigger_id"] for trigger in triggers}) != len(triggers):
        raise RevisitContractError(
            "cycle.intake.triggers contains duplicate trigger_id"
        )
    if [trigger["trigger_id"] for trigger in triggers] != expected_trigger_ids:
        raise RevisitContractError(
            "trigger IDs must be exact sequential request-order IDs"
        )

    claims_path = f"{path}.selected_claims"
    claims = _require_list(raw["selected_claims"], claims_path)
    if not claims:
        raise RevisitContractError("cycle.intake.selected_claims must not be empty")
    if len(claims) > 99:
        raise RevisitContractError(
            "cycle.intake.selected_claims cannot exceed 99 entries"
        )
    expected_claim_ids = [
        f"{cycle_id}-CL-{index:02d}" for index in range(1, len(claims) + 1)
    ]
    known_trigger_ids = set(expected_trigger_ids)
    referenced_trigger_ids: set[str] = set()
    for index, claim_value in enumerate(claims):
        claim_path = f"{claims_path}[{index}]"
        claim = _require_object(claim_value, claim_path)
        _require_exact_keys(
            claim,
            {
                "claim_id",
                "statement",
                "source_ref",
                "importance",
                "selection_reasons",
                "trigger_ids",
                "inherited_grade",
                "inherited_confidence",
                "inherited_evidence",
            },
            claim_path,
        )
        _require_claim_id(claim["claim_id"], f"{claim_path}.claim_id", cycle_id)
        _require_non_empty_text(claim["statement"], f"{claim_path}.statement")
        source_path = f"{claim_path}.source_ref"
        source = _require_object(claim["source_ref"], source_path)
        _require_exact_keys(
            source,
            {"path", "sha256", "locator", "historical_claim_id"},
            source_path,
        )
        _require_non_empty_text(source["path"], f"{source_path}.path")
        _require_sha256(source["sha256"], f"{source_path}.sha256")
        _require_non_empty_text(source["locator"], f"{source_path}.locator")
        _require_nullable_text(
            source["historical_claim_id"], f"{source_path}.historical_claim_id"
        )
        if claim["importance"] not in CLAIM_IMPORTANCE:
            raise RevisitContractError(f"{claim_path} claim importance is unsupported")
        reasons_path = f"{claim_path}.selection_reasons"
        reasons = _require_list(claim["selection_reasons"], reasons_path)
        if not reasons:
            raise RevisitContractError(f"{reasons_path} must not be empty")
        for reason in reasons:
            if reason not in SELECTION_REASONS:
                raise RevisitContractError(
                    f"{claim_path}.selection_reasons selection reason is unsupported"
                )
        _require_unique(reasons, reasons_path, "selection reasons")
        trigger_ids = _require_list(claim["trigger_ids"], f"{claim_path}.trigger_ids")
        for trigger_id in trigger_ids:
            _require_trigger_id(
                trigger_id, f"{claim_path}.trigger_ids", cycle_id
            )
        _require_unique(trigger_ids, f"{claim_path}.trigger_ids")
        if "trigger_affected" in reasons and not trigger_ids:
            raise RevisitContractError(
                "trigger_affected requires non-empty trigger_ids"
            )
        if not set(trigger_ids).issubset(known_trigger_ids):
            raise RevisitContractError(
                f"{claim_path}.trigger_ids must reference known intake triggers"
            )
        referenced_trigger_ids.update(trigger_ids)
        if (
            claim["inherited_grade"] is not None
            and claim["inherited_grade"] not in CURRENT_GRADES
        ):
            raise RevisitContractError(f"{claim_path}.inherited_grade is unsupported")
        if (
            claim["inherited_confidence"] is not None
            and claim["inherited_confidence"] not in CURRENT_CONFIDENCE
        ):
            raise RevisitContractError(
                f"{claim_path}.inherited_confidence is unsupported"
            )
        inherited_path = f"{claim_path}.inherited_evidence"
        for evidence_index, evidence_value in enumerate(
            _require_list(claim["inherited_evidence"], inherited_path)
        ):
            evidence_path = f"{inherited_path}[{evidence_index}]"
            evidence = _require_object(evidence_value, evidence_path)
            _require_exact_keys(
                evidence,
                {"ref", "freshness", "checked_at", "reason"},
                evidence_path,
            )
            _validate_evidence_ref(evidence["ref"], f"{evidence_path}.ref")
            if evidence["freshness"] not in FRESHNESS:
                raise RevisitContractError(f"{evidence_path}.freshness is unsupported")
            _require_utc_timestamp(
                evidence["checked_at"], f"{evidence_path}.checked_at"
            )
            _require_non_empty_text(evidence["reason"], f"{evidence_path}.reason")
    if len({claim["claim_id"] for claim in claims}) != len(claims):
        raise RevisitContractError(
            "cycle.intake.selected_claims contains duplicate claim_id"
        )
    if [claim["claim_id"] for claim in claims] != expected_claim_ids:
        raise RevisitContractError(
            "claim IDs must be exact sequential request-order IDs"
        )
    if referenced_trigger_ids != known_trigger_ids:
        raise RevisitContractError("every intake trigger must be referenced")


def _validate_bindings(raw: dict[str, Any]) -> None:
    bindings_path = "cycle.frontier_bindings"
    bindings = _require_list(raw["frontier_bindings"], bindings_path)
    for index, binding_value in enumerate(bindings):
        path = f"{bindings_path}[{index}]"
        binding = _require_object(binding_value, path)
        _require_exact_keys(
            binding,
            {
                "frontier_id",
                "action",
                "claim_ids",
                "expected_evidence",
                "baseline_loop_count",
                "baseline_review_count",
                "registry_sha256",
                "bound_at",
            },
            path,
        )
        _require_non_empty_text(binding["frontier_id"], f"{path}.frontier_id")
        _require_non_empty_text(binding["action"], f"{path}.action")
        claim_ids = _require_list(binding["claim_ids"], f"{path}.claim_ids")
        for claim_id in claim_ids:
            _require_claim_id(claim_id, f"{path}.claim_ids", raw["cycle_id"])
        _require_unique(claim_ids, f"{path}.claim_ids")
        for expected in _require_list(
            binding["expected_evidence"], f"{path}.expected_evidence"
        ):
            _require_non_empty_text(expected, f"{path}.expected_evidence")
        _require_strict_int(
            binding["baseline_loop_count"], f"{path}.baseline_loop_count"
        )
        _require_strict_int(
            binding["baseline_review_count"], f"{path}.baseline_review_count"
        )
        _require_sha256(binding["registry_sha256"], f"{path}.registry_sha256")
        _require_utc_timestamp(binding["bound_at"], f"{path}.bound_at")
    if len({binding["frontier_id"] for binding in bindings}) != len(bindings):
        raise RevisitContractError(
            "cycle.frontier_bindings contains duplicate frontier_id"
        )


def _validate_claims(raw: dict[str, Any]) -> None:
    derived_path = "cycle.derived_claims"
    derived_values = _require_list(raw["derived_claims"], derived_path)
    known_claim_ids = {
        claim["claim_id"] for claim in raw["intake"]["selected_claims"]
    }
    for index, claim in enumerate(derived_values):
        if isinstance(claim, dict) and "claim_id" in claim:
            known_claim_ids.add(
                _require_derived_claim_id(
                    claim["claim_id"],
                    f"{derived_path}[{index}].claim_id",
                    raw["cycle_id"],
                )
            )
    for index, claim_value in enumerate(derived_values):
        path = f"{derived_path}[{index}]"
        claim = _require_object(claim_value, path)
        _require_exact_keys(
            claim,
            {
                "claim_id",
                "origin",
                "statement",
                "derived_from",
                "accepted_from",
                "acceptance_rationale",
            },
            path,
        )
        _require_derived_claim_id(
            claim["claim_id"], f"{path}.claim_id", raw["cycle_id"]
        )
        _require_non_empty_text(claim["origin"], f"{path}.origin")
        _require_non_empty_text(claim["statement"], f"{path}.statement")
        if claim["derived_from"] is not None:
            _require_any_claim_id(
                claim["derived_from"], f"{path}.derived_from", raw["cycle_id"]
            )
            if claim["derived_from"] not in known_claim_ids:
                raise RevisitContractError(
                    f"{path}.derived_from must reference a known same-cycle claim ID"
                )
        accepted = claim["accepted_from"]
        if accepted is not None:
            accepted_path = f"{path}.accepted_from"
            if not isinstance(accepted, dict):
                raise RevisitContractError(
                    f"{accepted_path} must be an object or null"
                )
            _require_exact_keys(
                accepted,
                {"loop_id", "dispatch_id", "evidence_refs"},
                accepted_path,
            )
            _require_non_empty_text(accepted["loop_id"], f"{accepted_path}.loop_id")
            _require_non_empty_text(
                accepted["dispatch_id"], f"{accepted_path}.dispatch_id"
            )
            evidence_path = f"{accepted_path}.evidence_refs"
            for evidence_index, evidence in enumerate(
                _require_list(accepted["evidence_refs"], evidence_path)
            ):
                _validate_evidence_ref(evidence, f"{evidence_path}[{evidence_index}]")
        _require_non_empty_text(
            claim["acceptance_rationale"], f"{path}.acceptance_rationale"
        )
    if len({claim["claim_id"] for claim in derived_values}) != len(derived_values):
        raise RevisitContractError(
            "cycle.derived_claims contains duplicate claim_id"
        )

    resolutions_path = "cycle.claim_resolutions"
    resolutions = _require_list(raw["claim_resolutions"], resolutions_path)
    for index, resolution_value in enumerate(resolutions):
        path = f"{resolutions_path}[{index}]"
        resolution = _require_object(resolution_value, path)
        _require_exact_keys(
            resolution,
            {
                "claim_id",
                "status",
                "revised_statement",
                "current_evidence_refs",
                "counter_evidence_refs",
                "current_grade",
                "current_confidence",
                "bound_frontier_ids",
                "rationale",
                "missing_proof",
                "attempted_loop_ids",
                "attempted_search_refs",
                "verdict_impact",
                "split_child_ids",
            },
            path,
        )
        _require_any_claim_id(
            resolution["claim_id"], f"{path}.claim_id", raw["cycle_id"]
        )
        if resolution["claim_id"] not in known_claim_ids:
            raise RevisitContractError(
                f"{path}.claim_id must reference a known same-cycle claim"
            )
        if resolution["status"] not in _CLAIM_RESOLUTION_STATES:
            raise RevisitContractError(
                f"{path} claim resolution status is unsupported"
            )
        for field in ("revised_statement", "rationale", "missing_proof", "verdict_impact"):
            _require_nullable_text(resolution[field], f"{path}.{field}")
        if (
            resolution["current_grade"] is not None
            and resolution["current_grade"] not in CURRENT_GRADES
        ):
            raise RevisitContractError(f"{path}.current_grade is unsupported")
        if (
            resolution["current_confidence"] is not None
            and resolution["current_confidence"] not in CURRENT_CONFIDENCE
        ):
            raise RevisitContractError(f"{path}.current_confidence is unsupported")
        for field in ("current_evidence_refs", "counter_evidence_refs"):
            evidence_path = f"{path}.{field}"
            for evidence_index, evidence in enumerate(
                _require_list(resolution[field], evidence_path)
            ):
                _validate_evidence_ref(evidence, f"{evidence_path}[{evidence_index}]")
        for field in ("bound_frontier_ids", "attempted_loop_ids"):
            values = _require_list(resolution[field], f"{path}.{field}")
            for value in values:
                if not isinstance(value, str) or not value:
                    raise RevisitContractError(
                        f"{path}.{field} must contain non-empty text"
                    )
                _require_non_empty_text(value, f"{path}.{field}")
            _require_unique(values, f"{path}.{field}")
        child_ids = _require_list(
            resolution["split_child_ids"], f"{path}.split_child_ids"
        )
        for child_id in child_ids:
            _require_derived_claim_id(
                child_id, f"{path}.split_child_ids", raw["cycle_id"]
            )
        _require_unique(child_ids, f"{path}.split_child_ids")
        searches_path = f"{path}.attempted_search_refs"
        for search_index, search_value in enumerate(
            _require_list(resolution["attempted_search_refs"], searches_path)
        ):
            search_path = f"{searches_path}[{search_index}]"
            search = _require_object(search_value, search_path)
            _require_exact_keys(search, {"loop_id", "query"}, search_path)
            _require_non_empty_text(search["loop_id"], f"{search_path}.loop_id")
            _require_non_empty_text(search["query"], f"{search_path}.query")
    if len({resolution["claim_id"] for resolution in resolutions}) != len(
        resolutions
    ):
        raise RevisitContractError(
            "cycle.claim_resolutions contains duplicate claim_id"
        )
    if {resolution["claim_id"] for resolution in resolutions} != known_claim_ids:
        raise RevisitContractError(
            "cycle.claim_resolutions must cover every selected and derived claim exactly once"
        )


def _validate_decision_and_reruns(raw: dict[str, Any]) -> None:
    assessment = raw["decision_assessment"]
    if assessment is not None:
        path = "cycle.decision_assessment"
        if not isinstance(assessment, dict):
            raise RevisitContractError(f"{path} must be an object or null")
        _require_exact_keys(
            assessment,
            {
                "new_action_class",
                "financial_bridge_affected",
                "financial_bridge_rationale",
                "risk_class_changed",
                "risk_class_rationale",
                "supporting_claim_ids",
                "verdict_rationale",
                "blocked_claim_ids",
                "change_class",
                "required_reruns",
            },
            path,
        )
        if assessment["new_action_class"] not in ACTION_CLASSES:
            raise RevisitContractError(f"{path}.new_action_class is unsupported")
        _require_bool(
            assessment["financial_bridge_affected"],
            f"{path}.financial_bridge_affected",
        )
        _require_nullable_text(
            assessment["financial_bridge_rationale"],
            f"{path}.financial_bridge_rationale",
        )
        _require_bool(assessment["risk_class_changed"], f"{path}.risk_class_changed")
        _require_nullable_text(
            assessment["risk_class_rationale"], f"{path}.risk_class_rationale"
        )
        known_claim_ids = {
            claim["claim_id"] for claim in raw["intake"]["selected_claims"]
        }
        known_claim_ids.update(claim["claim_id"] for claim in raw["derived_claims"])
        for field in ("supporting_claim_ids", "blocked_claim_ids"):
            claim_ids = _require_list(assessment[field], f"{path}.{field}")
            for claim_id in claim_ids:
                _require_any_claim_id(claim_id, f"{path}.{field}", raw["cycle_id"])
                if claim_id not in known_claim_ids:
                    raise RevisitContractError(
                        f"{path}.{field} must reference known same-cycle claims"
                    )
            _require_unique(claim_ids, f"{path}.{field}")
        _require_non_empty_text(
            assessment["verdict_rationale"], f"{path}.verdict_rationale"
        )
        if assessment["change_class"] not in _CHANGE_CLASSES:
            raise RevisitContractError(f"{path}.change_class is unsupported")
        required_reruns = _require_list(
            assessment["required_reruns"], f"{path}.required_reruns"
        )
        for rerun in required_reruns:
            if rerun not in _REQUIRED_RERUNS:
                raise RevisitContractError(
                    f"{path}.required_reruns entry is unsupported"
                )
        if len(required_reruns) != len(set(required_reruns)):
            raise RevisitContractError(
                f"{path}.required_reruns must not contain duplicates"
            )

    reruns_path = "cycle.rerun_artifacts"
    for index, artifact_value in enumerate(
        _require_list(raw["rerun_artifacts"], reruns_path)
    ):
        path = f"{reruns_path}[{index}]"
        artifact = _require_object(artifact_value, path)
        _require_exact_keys(
            artifact,
            {"kind", "scope", "round", "path", "sha256", "recorded_at"},
            path,
        )
        _require_non_empty_text(artifact["kind"], f"{path}.kind")
        if artifact["scope"] is not None and artifact["scope"] not in _RERUN_SCOPES:
            raise RevisitContractError(f"{path}.scope is unsupported")
        if artifact["round"] is not None:
            _require_strict_int(artifact["round"], f"{path}.round", 1)
        _require_non_empty_text(artifact["path"], f"{path}.path")
        _require_sha256(artifact["sha256"], f"{path}.sha256")
        _require_utc_timestamp(artifact["recorded_at"], f"{path}.recorded_at")


def _validate_report_candidate(raw: dict[str, Any]) -> None:
    candidate = raw["report_candidate"]
    if candidate is None:
        return
    path = "cycle.report_candidate"
    if not isinstance(candidate, dict):
        raise RevisitContractError(f"{path} must be an object or null")
    _require_exact_keys(
        candidate,
        {"revision_id", "revision_of", "report_path", "report_sha256", "registered_at"},
        path,
    )
    _require_revision_id(candidate["revision_id"], f"{path}.revision_id")
    _require_revision_id(candidate["revision_of"], f"{path}.revision_of")
    _require_non_empty_text(candidate["report_path"], f"{path}.report_path")
    _require_sha256(candidate["report_sha256"], f"{path}.report_sha256")
    _require_utc_timestamp(candidate["registered_at"], f"{path}.registered_at")


def _validate_audit(raw: dict[str, Any]) -> None:
    audit_path = "cycle.audit"
    audit = _require_list(raw["audit"], audit_path)
    if not audit:
        raise RevisitContractError("cycle.audit must not be empty")
    previous_post = None
    for index, entry_value in enumerate(audit):
        path = f"{audit_path}[{index}]"
        entry = _require_object(entry_value, path)
        _require_exact_keys(
            entry,
            {
                "sequence",
                "timestamp",
                "command",
                "affected_ids",
                "pre_state_sha256",
                "post_state_sha256",
            },
            path,
        )
        sequence = _require_strict_int(entry["sequence"], f"{path}.sequence", 1)
        if sequence != index + 1:
            raise RevisitContractError(
                "audit sequence must be continuous starting at 1"
            )
        _require_utc_timestamp(entry["timestamp"], f"{path}.timestamp")
        _require_non_empty_text(entry["command"], f"{path}.command")
        affected_ids = _require_list(entry["affected_ids"], f"{path}.affected_ids")
        for affected_id in affected_ids:
            if not isinstance(affected_id, str) or not affected_id:
                raise RevisitContractError(
                    f"{path}.affected_ids must contain non-empty text"
                )
            _require_non_empty_text(affected_id, f"{path}.affected_ids")
        _require_unique(affected_ids, f"{path}.affected_ids")
        _require_sha256(entry["pre_state_sha256"], f"{path}.pre_state_sha256")
        _require_sha256(entry["post_state_sha256"], f"{path}.post_state_sha256")
        if previous_post is not None and entry["pre_state_sha256"] != previous_post:
            raise RevisitContractError("audit pre/post hash continuity is broken")
        previous_post = entry["post_state_sha256"]
    first = audit[0]
    if first["command"] != "start":
        raise RevisitContractError("audit entry 1 command must be start")
    if first["timestamp"] != raw["created_at"]:
        raise RevisitContractError(
            "audit entry 1 timestamp must match cycle.created_at"
        )
    if first["pre_state_sha256"] != semantic_sha256(None):
        raise RevisitContractError(
            "audit entry 1 pre_state_sha256 must be the canonical null hash"
        )
    expected_affected_ids = [
        raw["cycle_id"],
        raw["candidate_revision_id"],
        *(trigger["trigger_id"] for trigger in raw["intake"]["triggers"]),
        *(claim["claim_id"] for claim in raw["intake"]["selected_claims"]),
    ]
    if first["affected_ids"] != expected_affected_ids:
        raise RevisitContractError(
            "audit entry 1 affected_ids must name the reserved and initial intake IDs"
        )
    if previous_post != cycle_state_sha256(raw):
        raise RevisitContractError(
            "last audit post_state_sha256 does not match current state"
        )


def _validate_cycle_timestamps(raw: dict[str, Any]) -> None:
    _require_utc_timestamp(raw["created_at"], "cycle.created_at")
    status = raw["status"]
    if status == "completed":
        if raw["completed_at"] is None:
            raise RevisitContractError("completed cycle requires completed_at")
        _require_utc_timestamp(raw["completed_at"], "cycle.completed_at")
        if raw["aborted_at"] is not None:
            raise RevisitContractError(
                "cycle.aborted_at is only valid when status is aborted"
            )
        if raw["abort_reason"] is not None:
            raise RevisitContractError(
                "cycle.abort_reason is only valid when status is aborted"
            )
        return
    if status == "aborted":
        if raw["completed_at"] is not None:
            raise RevisitContractError(
                "cycle.completed_at is only valid when status is completed"
            )
        if raw["aborted_at"] is None:
            raise RevisitContractError("aborted cycle requires aborted_at")
        _require_utc_timestamp(raw["aborted_at"], "cycle.aborted_at")
        if raw["abort_reason"] is None:
            raise RevisitContractError("aborted cycle requires abort_reason")
        _require_non_empty_text(raw["abort_reason"], "cycle.abort_reason")
        return
    if raw["completed_at"] is not None:
        raise RevisitContractError(
            "cycle.completed_at is only valid when status is completed"
        )
    if raw["aborted_at"] is not None:
        raise RevisitContractError(
            "cycle.aborted_at is only valid when status is aborted"
        )
    if raw["abort_reason"] is not None:
        raise RevisitContractError(
            "cycle.abort_reason is only valid when status is aborted"
        )


def validate_cycle(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RevisitContractError("cycle JSON must contain an object")
    _require_exact_keys(raw, CYCLE_KEYS, "cycle")
    if _require_strict_int(raw["schema_version"], "cycle.schema_version", 1) != 1:
        raise RevisitContractError("unsupported cycle schema_version")
    _require_cycle_id(raw["cycle_id"], "cycle.cycle_id")
    _require_revision_id(raw["candidate_revision_id"], "cycle.candidate_revision_id")
    if raw["status"] not in CYCLE_STATUSES:
        raise RevisitContractError(f"unsupported cycle status: {raw['status']!r}")
    _validate_cycle_timestamps(raw)
    _validate_intake(raw["intake"], raw["cycle_id"])
    _require_sha256(raw["intake_sha256"], "cycle.intake_sha256")
    if raw["intake_sha256"] != intake_sha256(raw["intake"]):
        raise RevisitContractError(
            "cycle.intake_sha256 does not match immutable intake"
        )
    _validate_bindings(raw)
    _validate_claims(raw)
    _validate_decision_and_reruns(raw)
    _validate_report_candidate(raw)
    _validate_audit(raw)
    return raw
