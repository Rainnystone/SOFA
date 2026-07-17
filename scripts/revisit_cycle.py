#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from revisit_contract import (
    ACTION_CLASSES,
    POINTER_FILENAME,
    RevisitContractError,
    add_derived_claim,
    allocate_cycle_and_revision_ids,
    assess_decision,
    bind_frontier,
    complete_cycle,
    create_cycle,
    cycle_directory,
    cycle_json_path,
    empty_pointer,
    evaluate_history,
    list_cycle_ids,
    load_cycle,
    load_pointer,
    persist_cycle,
    persist_pointer,
    record_rerun,
    render_report_metadata,
    register_report_candidate,
    resolve_claim,
    sha256_file,
    validate_evidence_ref,
    workspace_transaction,
)
from revisit_contract.model import (
    derive_frontier_binding_legality_issue,
    with_audit,
)
from revisit_contract.store import (
    PreparedAuthoritySnapshot,
    _AuthorityGeneration,
    _load_observed_cycle_history,
    _read_authority_generation,
    _require_authority_generation,
    _require_snapshot_generations,
    load_intake_request,
    normalize_workspace_relative_path,
    resolve_workspace_path,
    verify_workspace_artifact,
)
from framing_contract import evaluate_contract
from framing_contract.model import normalize_contract
from frontier_lifecycle import LOOP_HEADER_RE, derive_loop_counts, get_frontier
from frontier_review import read_registry_snapshot
from source_cache import evaluate_index
from sofa_contract import check_revisit_readiness
from sofa_contract.evaluate import (
    _prepare_published_current_for_publication,
    _prepare_revisit_report_for_publication,
    evaluate_specific_ticker_report,
)
from sofa_contract.workspace import read_specific_markdown_report


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _load_ticker_state(workspace: Path, operation: str) -> dict:
    state_path = workspace / "state.json"
    try:
        state = json.loads(state_path.read_bytes().decode("utf-8"))
    except FileNotFoundError as exc:
        raise RevisitContractError("state.json is required") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError("state.json must be valid UTF-8 JSON") from exc
    if not isinstance(state, dict):
        raise RevisitContractError("state.json must contain an object")
    if state.get("mode") != "ticker":
        if str(state.get("mode", "")).lower() == "sector":
            raise RevisitContractError(
                f"{operation} is unavailable for Sector workspaces; "
                "revisit cycles require ticker mode"
            )
        raise RevisitContractError(
            f"{operation} is available only for ticker workspaces"
        )
    return state


def _utc_now_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_owner_generation(
    generation: _AuthorityGeneration,
    owner_payload: bytes,
    authority: str,
) -> None:
    if owner_payload != generation.payload:
        raise RevisitContractError(
            f"{authority} owner bytes differ from captured generation"
        )
    _require_authority_generation(
        generation,
        f"after {authority} validation",
    )


def _require_current_report(
    workspace: Path, pointer: dict
) -> tuple[dict, Path, str, PreparedAuthoritySnapshot]:
    current = pointer["current_revision"]
    if current is None:
        raise RevisitContractError(
            "current report is not registered; run register-current first"
        )
    report_relative = normalize_workspace_relative_path(current["report_path"])
    report_generation = _read_authority_generation(
        workspace,
        workspace / report_relative,
    )
    relative, payload, _ = read_specific_markdown_report(
        workspace, current["report_path"]
    )
    _require_owner_generation(
        report_generation,
        payload,
        "current report",
    )
    if relative != current["report_path"]:
        raise RevisitContractError(
            "pointer current report path is not canonical: "
            f"{current['report_path']}"
        )
    report_sha256 = report_generation.snapshot.expected_sha256
    if report_sha256 != current["report_sha256"]:
        raise RevisitContractError(
            "registered report bytes do not match current pointer"
        )
    result = evaluate_specific_ticker_report(
        workspace,
        relative,
        expected_sha256=report_sha256,
    )
    if not result.passed:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in result.failures
        )
        raise RevisitContractError(details)
    _require_authority_generation(
        report_generation,
        "after current report evaluation",
    )
    return (
        current,
        report_generation.snapshot.lexical_path,
        report_sha256,
        report_generation.snapshot,
    )


def _load_revisit_framing(
    workspace: Path,
) -> tuple[dict, Path, str, PreparedAuthoritySnapshot]:
    path = workspace / "framing_contract.json"
    generation = _read_authority_generation(workspace, path)
    payload = generation.payload
    try:
        raw_contract = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError(
            "framing_contract.json must be valid UTF-8 JSON"
        ) from exc
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
        "subject_resolution": copy.deepcopy(contract["subject_resolution"]),
        "research_posture": contract["research_posture"],
        "time_horizon": contract["time_horizon"],
        "market_scope": contract["market_scope"],
        "risk_appetite": contract["risk_appetite"],
        "output_expectation": contract["output_expectation"],
        "report_language": contract["report_language"],
        "budget_appetite": contract["budget_appetite"],
    }
    digest = generation.snapshot.expected_sha256
    return (
        snapshot,
        path,
        digest,
        generation.snapshot,
    )


def _load_workspace_boundary(
    workspace: Path,
) -> tuple[
    dict,
    Path,
    str,
    Path,
    str,
    int,
    PreparedAuthoritySnapshot,
    PreparedAuthoritySnapshot,
]:
    registry_path = workspace / "frontier_registry.json"
    registry_generation = _read_authority_generation(workspace, registry_path)
    registry, registry_payload = read_registry_snapshot(workspace)
    _require_owner_generation(
        registry_generation,
        registry_payload,
        "frontier registry",
    )
    if registry.get("mode") != "ticker":
        raise RevisitContractError("frontier registry mode must be ticker")
    ledger_path = workspace / "evidence_ledger.md"
    ledger_generation = _read_authority_generation(workspace, ledger_path)
    ledger_payload = ledger_generation.payload
    ledger_text = ledger_payload.decode("utf-8")
    max_loop_number = 0
    if "## Loop " in ledger_text:
        derive_loop_counts(ledger_text, registry)
        for raw_line in ledger_text.splitlines():
            line = raw_line.rstrip()
            if not line.startswith("## Loop "):
                continue
            match = LOOP_HEADER_RE.fullmatch(line)
            if match is None:
                raise RevisitContractError(f"malformed loop header: {line}")
            max_loop_number = max(max_loop_number, int(match.group("loop")))
    registry_sha256 = registry_generation.snapshot.expected_sha256
    ledger_sha256 = ledger_generation.snapshot.expected_sha256
    return (
        registry,
        registry_generation.snapshot.lexical_path,
        registry_sha256,
        ledger_generation.snapshot.lexical_path,
        ledger_sha256,
        max_loop_number,
        registry_generation.snapshot,
        ledger_generation.snapshot,
    )


def _load_frontier_binding_snapshot(
    workspace: Path,
) -> tuple[
    dict,
    dict[str, int],
    tuple[tuple[int, str], ...],
    PreparedAuthoritySnapshot,
    PreparedAuthoritySnapshot,
]:
    registry_generation = _read_authority_generation(
        workspace, workspace / "frontier_registry.json"
    )
    registry, registry_payload = read_registry_snapshot(workspace)
    _require_owner_generation(
        registry_generation,
        registry_payload,
        "frontier registry",
    )
    if registry.get("mode") != "ticker":
        raise RevisitContractError("frontier registry mode must be ticker")

    ledger_generation = _read_authority_generation(
        workspace, workspace / "evidence_ledger.md"
    )
    try:
        ledger_text = ledger_generation.payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RevisitContractError(
            "evidence_ledger.md must be valid UTF-8"
        ) from exc
    loop_counts = (
        derive_loop_counts(ledger_text, registry)
        if "## Loop " in ledger_text
        else {frontier["id"]: 0 for frontier in registry["frontiers"]}
    )
    headers: list[tuple[int, str]] = []
    for raw_line in ledger_text.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("## Loop "):
            continue
        match = LOOP_HEADER_RE.fullmatch(line)
        if match is None:
            raise RevisitContractError(f"malformed loop header: {line}")
        headers.append((int(match.group("loop")), match.group("frontier_id")))
    _require_authority_generation(
        ledger_generation,
        "after evidence ledger validation",
    )
    return (
        registry,
        loop_counts,
        tuple(headers),
        registry_generation.snapshot,
        ledger_generation.snapshot,
    )


def _validate_workspace_artifact_generation(
    workspace: Path,
    value: str,
    expected_sha256: str,
) -> tuple[str, _AuthorityGeneration]:
    relative = normalize_workspace_relative_path(value)
    resolve_workspace_path(workspace, relative)
    generation = _read_authority_generation(
        workspace,
        workspace / relative,
    )
    owner_relative, owner_payload = verify_workspace_artifact(
        workspace,
        relative,
        expected_sha256,
    )
    _require_owner_generation(
        generation,
        owner_payload,
        "workspace artifact",
    )
    return owner_relative, generation


def _load_json_object(path: str | Path, label: str) -> dict:
    request_path = Path(path)
    try:
        payload = request_path.read_bytes()
    except FileNotFoundError as exc:
        raise RevisitContractError(f"{label} is missing: {request_path}") from exc
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisitContractError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise RevisitContractError(f"{label} must contain an object")
    return raw


def _validate_source_ids(
    workspace: Path, requested_source_ids: set[str]
) -> tuple[set[str], tuple[PreparedAuthoritySnapshot, ...]]:
    source_index_path = workspace / "sources_index.jsonl"
    if not requested_source_ids and not source_index_path.exists():
        return set(), ()
    source_index_generation = _read_authority_generation(
        workspace,
        source_index_path,
    )
    if not requested_source_ids:
        return set(), (source_index_generation.snapshot,)
    preliminary = evaluate_index(workspace)
    _require_authority_generation(
        source_index_generation,
        "after preliminary source cache validation",
    )
    if preliminary.issues:
        details = "; ".join(
            f"{issue.code} at {issue.location}: {issue.message}"
            for issue in preliminary.issues
        )
        raise RevisitContractError(f"source cache failed validation: {details}")
    preliminary_by_id = {
        str(record["source_id"]): copy.deepcopy(record)
        for record in preliminary.records
    }
    missing = sorted(requested_source_ids - set(preliminary_by_id))
    if missing:
        raise RevisitContractError(f"source_id is not registered: {missing[0]}")

    snapshots = [source_index_generation.snapshot]
    excerpt_generations: list[_AuthorityGeneration] = []
    for source_id in sorted(requested_source_ids):
        excerpt_relative = normalize_workspace_relative_path(
            preliminary_by_id[source_id]["excerpt_path"]
        )
        excerpt_generation = _read_authority_generation(
            workspace,
            workspace / excerpt_relative,
        )
        resolved_excerpt = resolve_workspace_path(
            workspace,
            excerpt_relative,
            parent="sources",
        )
        if (
            resolved_excerpt != excerpt_generation.snapshot.resolved_target
            or not resolved_excerpt.is_file()
        ):
            raise RevisitContractError(f"source excerpt is not a file: {source_id}")
        excerpt_generations.append(excerpt_generation)
        snapshots.append(excerpt_generation.snapshot)

    evaluation = evaluate_index(workspace)
    _require_authority_generation(
        source_index_generation,
        "after source cache validation",
    )
    for generation in excerpt_generations:
        _require_authority_generation(
            generation,
            "after source cache validation",
        )
    if evaluation.issues:
        details = "; ".join(
            f"{issue.code} at {issue.location}: {issue.message}"
            for issue in evaluation.issues
        )
        raise RevisitContractError(f"source cache failed validation: {details}")
    final_by_id = {
        str(record["source_id"]): record for record in evaluation.records
    }
    for source_id in sorted(requested_source_ids):
        if final_by_id.get(source_id) != preliminary_by_id[source_id]:
            raise RevisitContractError(
                f"source record changed during validation: {source_id}"
            )
    return set(final_by_id), tuple(snapshots)


def _validate_evidence_references(
    workspace: Path,
    references: list[dict],
    path: str,
    *,
    forbidden_delivery_snapshot: PreparedAuthoritySnapshot | None = None,
) -> tuple[list[dict], tuple[PreparedAuthoritySnapshot, ...]]:
    canonical = copy.deepcopy(references)
    for index, reference in enumerate(canonical):
        validate_evidence_ref(reference, f"{path}[{index}]")
    requested_source_ids = {
        reference["source_id"]
        for reference in canonical
        if reference["kind"] == "source"
    }
    registered_source_ids, source_snapshots = _validate_source_ids(
        workspace, requested_source_ids
    )
    snapshots = list(source_snapshots)
    for reference in canonical:
        if reference["kind"] == "source":
            if reference["source_id"] not in registered_source_ids:
                raise RevisitContractError(
                    f"source_id is not registered: {reference['source_id']}"
                )
            continue
        relative, generation = _validate_workspace_artifact_generation(
            workspace,
            reference["path"],
            reference["sha256"],
        )
        if forbidden_delivery_snapshot is not None and (
            generation.snapshot.lexical_path
            == forbidden_delivery_snapshot.lexical_path
            or generation.snapshot.resolved_target
            == forbidden_delivery_snapshot.resolved_target
        ):
            raise RevisitContractError(
                "worker delivery is provenance only and cannot be accepted "
                "as artifact evidence"
            )
        reference["path"] = relative
        snapshots.append(generation.snapshot)
    return canonical, tuple(snapshots)


def _decode_dispatch_generation(
    generation: _AuthorityGeneration,
    *,
    strict: bool,
) -> list[dict]:
    try:
        text = generation.payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        if not strict:
            return []
        raise RevisitContractError(
            "dispatch_log.jsonl must be valid UTF-8 JSONL"
        ) from exc
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            if not strict:
                return []
            raise RevisitContractError(
                f"dispatch_log.jsonl line {line_number} must be valid JSON"
            ) from exc
        if not isinstance(record, dict):
            if not strict:
                return []
            raise RevisitContractError(
                f"dispatch_log.jsonl line {line_number} must contain an object"
            )
        records.append(record)
    return records


def _read_dispatch_delivery_generation(
    workspace: Path,
    record: dict,
    *,
    strict: bool,
    missing_is_error: bool = False,
) -> _AuthorityGeneration | None:
    dispatch_id = str(record.get("dispatch_id", ""))
    raw_delivery = record.get("delivery_path")
    if (
        not isinstance(raw_delivery, str)
        or not raw_delivery
        or any(unicodedata.category(character) == "Cc" for character in raw_delivery)
    ):
        if not strict:
            return None
        raise RevisitContractError(
            f"dispatch {dispatch_id} delivery_path must be non-empty text"
        )
    candidate = Path(raw_delivery)
    lexical_delivery = (
        candidate if candidate.is_absolute() else workspace / candidate
    )
    resolved = (
        candidate.resolve(strict=False)
        if candidate.is_absolute()
        else (workspace / candidate).resolve(strict=False)
    )
    try:
        relative = resolved.relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        if not strict:
            return None
        raise RevisitContractError(
            f"dispatch {dispatch_id} delivery path escapes workspace"
        ) from exc
    if not resolved.is_file():
        if not strict and not missing_is_error:
            return None
        raise RevisitContractError(
            f"dispatch {dispatch_id} delivery path is missing or not a file: {relative}"
        )
    return _read_authority_generation(workspace, lexical_delivery)


def _validate_emergent_dispatch(
    workspace: Path, accepted_from: dict
) -> tuple[PreparedAuthoritySnapshot, PreparedAuthoritySnapshot]:
    dispatch_generation = _read_authority_generation(
        workspace,
        workspace / "dispatch_log.jsonl",
    )
    records = _decode_dispatch_generation(dispatch_generation, strict=True)
    _require_authority_generation(
        dispatch_generation,
        "after dispatch log validation",
    )
    loop_id = accepted_from["loop_id"]
    dispatch_id = accepted_from["dispatch_id"]
    matching = [
        record
        for record in records
        if record.get("loop_id") == loop_id
        and record.get("dispatch_id") == dispatch_id
    ]
    if not matching:
        raise RevisitContractError(
            f"dispatch {dispatch_id} has no exact matching record for {loop_id}"
        )
    if len(matching) != 1:
        raise RevisitContractError(
            f"dispatch {dispatch_id} has multiple matching records for {loop_id}"
        )
    record = matching[0]
    if record.get("status") != "delivered":
        raise RevisitContractError(
            f"dispatch {dispatch_id} must have status delivered"
        )
    delivery_generation = _read_dispatch_delivery_generation(
        workspace,
        record,
        strict=True,
    )
    if delivery_generation is None:
        raise RevisitContractError(
            f"dispatch {dispatch_id} delivery path could not be captured"
        )
    return dispatch_generation.snapshot, delivery_generation.snapshot


def _validate_request_references(
    workspace: Path, request: dict
) -> tuple[dict, tuple[PreparedAuthoritySnapshot, ...]]:
    canonical = copy.deepcopy(request)
    artifact_snapshots: list[PreparedAuthoritySnapshot] = []

    requested_source_ids: set[str] = set()
    for trigger in canonical["triggers"]:
        for ref in trigger["evidence_refs"]:
            if ref["kind"] == "source":
                requested_source_ids.add(ref["source_id"])
    for claim in canonical["selected_claims"]:
        for inherited in claim["inherited_evidence"]:
            ref = inherited["ref"]
            if ref["kind"] == "source":
                requested_source_ids.add(ref["source_id"])

    registered_source_ids, source_snapshots = _validate_source_ids(
        workspace, requested_source_ids
    )
    artifact_snapshots.extend(source_snapshots)

    def validate_reference(ref: dict) -> None:
        if ref["kind"] == "source":
            if ref["source_id"] not in registered_source_ids:
                raise RevisitContractError(
                    f"source_id is not registered: {ref['source_id']}"
                )
            return
        relative, generation = _validate_workspace_artifact_generation(
            workspace,
            ref["path"],
            ref["sha256"],
        )
        ref["path"] = relative
        artifact_snapshots.append(generation.snapshot)

    for trigger in canonical["triggers"]:
        for ref in trigger["evidence_refs"]:
            validate_reference(ref)
    for claim in canonical["selected_claims"]:
        source_ref = claim["source_ref"]
        relative, generation = _validate_workspace_artifact_generation(
            workspace,
            source_ref["path"],
            source_ref["sha256"],
        )
        source_ref["path"] = relative
        artifact_snapshots.append(generation.snapshot)
        for inherited in claim["inherited_evidence"]:
            validate_reference(inherited["ref"])
    return canonical, tuple(artifact_snapshots)


def _command_start_in_transaction(args: argparse.Namespace, workspace: Path) -> int:
    _load_ticker_state(workspace, "start")
    request = load_intake_request(args.intake_file)
    request, artifact_snapshots = _validate_request_references(workspace, request)

    current_pointer_path = workspace / POINTER_FILENAME
    pointer_generation = _read_authority_generation(
        workspace,
        current_pointer_path,
    )
    pointer = load_pointer(workspace)
    _require_authority_generation(
        pointer_generation,
        "after pointer validation",
    )
    current, _, _, report_authority = _require_current_report(
        workspace, pointer
    )

    cycle_ids = list_cycle_ids(workspace)
    cycles = [load_cycle(workspace, cycle_id) for cycle_id in cycle_ids]
    history = evaluate_history(pointer, cycles)
    history.require_valid()
    cycles_by_id = {cycle["cycle_id"]: cycle for cycle in cycles}
    if history.nonterminal_cycle_ids:
        cycle = cycles_by_id[history.nonterminal_cycle_ids[0]]
        raise RevisitContractError(
            f"cycle conflict: {cycle['cycle_id']} is {cycle['status']}"
        )
    if history.completed_unpublished_cycle_ids:
        raise RevisitContractError(
            "cycle conflict: "
            f"{history.completed_unpublished_cycle_ids[0]} "
            "is completed-unpublished"
        )

    (
        framing_snapshot,
        _,
        framing_sha256,
        framing_authority,
    ) = _load_revisit_framing(workspace)
    (
        _,
        _,
        registry_sha256,
        _,
        _,
        max_loop_number,
        registry_authority,
        ledger_authority,
    ) = _load_workspace_boundary(workspace)
    cycle_id, candidate_revision_id = allocate_cycle_and_revision_ids(
        pointer, cycles
    )
    cycle = create_cycle(
        cycle_id=cycle_id,
        candidate_revision_id=candidate_revision_id,
        base_revision=current,
        framing_sha256=framing_sha256,
        framing_snapshot=framing_snapshot,
        frontier_registry_sha256=registry_sha256,
        max_existing_loop_number=max_loop_number,
        request=request,
        timestamp=_utc_now_seconds(),
    )

    snapshots = (
        pointer_generation.snapshot,
        report_authority,
        framing_authority,
        registry_authority,
        ledger_authority,
        *artifact_snapshots,
    )
    persist_cycle(
        workspace,
        cycle,
        expected_sha256=None,
        authority_snapshots=snapshots,
    )
    print(
        f"REVISIT CYCLE STARTED: {cycle_id} "
        f"(candidate {candidate_revision_id})"
    )
    return 0


def command_start(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_start_in_transaction(args, workspace)


def _status_summary(workspace: Path, selected_cycle_id: str | None) -> dict:
    pointer = load_pointer(workspace)
    current = pointer["current_revision"]
    report_issue = None
    if current is not None:
        try:
            _require_current_report(workspace, pointer)
        except RevisitContractError as error:
            report_issue = f"current_report_invalid: {error}"
    all_cycles = [
        load_cycle(workspace, cycle_id)
        for cycle_id in list_cycle_ids(workspace)
    ]
    history = evaluate_history(pointer, all_cycles)
    if selected_cycle_id is None:
        selected_cycles = all_cycles
    else:
        selected_by_id = {
            cycle["cycle_id"]: cycle for cycle in all_cycles
        }
        if selected_cycle_id not in selected_by_id:
            cycle_json_path(workspace, selected_cycle_id)
            raise RevisitContractError(
                f"cycle authority is missing: {selected_cycle_id}"
            )
        selected_cycles = [selected_by_id[selected_cycle_id]]

    cycles = []
    unpublished_ids = set(history.completed_unpublished_cycle_ids)
    for cycle in selected_cycles:
        cycles.append(
            {
                "cycle_id": cycle["cycle_id"],
                "candidate_revision_id": cycle["candidate_revision_id"],
                "status": (
                    "completed-unpublished"
                    if cycle["cycle_id"] in unpublished_ids
                    else cycle["status"]
                ),
                "created_at": cycle["created_at"],
                "completed_at": cycle["completed_at"],
                "aborted_at": cycle["aborted_at"],
                "abort_reason": cycle["abort_reason"],
            }
        )

    selected_by_id = {cycle["cycle_id"]: cycle for cycle in all_cycles}
    completed_unpublished = (
        selected_by_id[history.completed_unpublished_cycle_ids[0]]
        if history.completed_unpublished_cycle_ids
        else None
    )
    nonterminal = (
        selected_by_id[history.nonterminal_cycle_ids[0]]
        if history.nonterminal_cycle_ids
        else None
    )
    issues = ([report_issue] if report_issue is not None else []) + [
        (
            f"{issue.code}: {issue.message}"
            + (f" ({issue.evidence})" if issue.evidence else "")
        )
        for issue in history.issues
    ]
    if issues:
        next_command = None
    elif current is None:
        next_command = (
            "register-current --report REPORT --action-class ACTION_CLASS"
        )
    elif completed_unpublished is not None:
        next_command = f"publish {completed_unpublished['cycle_id']}"
    elif nonterminal is not None:
        next_command = f"abort {nonterminal['cycle_id']} --reason TEXT"
    else:
        next_command = "start --intake-file REQUEST"

    return {
        "schema_version": 1,
        "mode": "ticker",
        "current_revision": copy.deepcopy(current),
        "cycles": cycles,
        "issues": issues,
        "next_legal_command": next_command,
    }


def _render_status_text(summary: dict) -> str:
    current = summary["current_revision"]
    lines = []
    if current is None:
        lines.append("CURRENT REVISION: none")
    else:
        lines.append(
            f"CURRENT REVISION: {current['revision_id']} "
            f"({current['report_path']})"
        )
    if not summary["cycles"]:
        lines.append("CYCLES: none")
    else:
        for cycle in summary["cycles"]:
            lines.extend(
                (
                    f"CYCLE: {cycle['cycle_id']}",
                    f"CANDIDATE REVISION: {cycle['candidate_revision_id']}",
                    f"STATUS: {cycle['status']}",
                )
            )
    if summary["issues"]:
        for issue in summary["issues"]:
            lines.append(f"ISSUE: {issue}")
    else:
        lines.append("ISSUES: none")
    next_command = summary["next_legal_command"] or "none"
    lines.append(f"NEXT LEGAL COMMAND: {next_command}")
    return "\n".join(lines) + "\n"


def command_status(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        _load_ticker_state(workspace, "status")
        summary = _status_summary(workspace, args.cycle)
    if args.json:
        print(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        sys.stdout.write(_render_status_text(summary))
    return 0


def _command_abort_in_transaction(args: argparse.Namespace, workspace: Path) -> int:
    reason = args.reason
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or any(unicodedata.category(character) == "Cc" for character in reason)
    ):
        raise RevisitContractError(
            "abort reason must be non-empty text without control characters"
        )

    _load_ticker_state(workspace, "abort")
    current_pointer_path = workspace / POINTER_FILENAME
    pointer_generation = _read_authority_generation(
        workspace,
        current_pointer_path,
    )
    pointer = load_pointer(workspace)
    _require_authority_generation(
        pointer_generation,
        "after pointer validation",
    )
    current, _, _, report_authority = _require_current_report(
        workspace, pointer
    )

    json_path = cycle_json_path(workspace, args.cycle)
    expected_cycle_sha256 = sha256_file(json_path)
    previous = load_cycle(workspace, args.cycle)
    if previous["status"] not in {"active", "ready_for_report"}:
        raise RevisitContractError(
            f"cannot abort cycle {args.cycle} with status {previous['status']}"
        )
    expected_base = {
        "revision_id": current["revision_id"],
        "report_path": current["report_path"],
        "report_sha256": current["report_sha256"],
        "action_class": current["action_class"],
    }
    if previous["intake"]["base_revision"] != expected_base:
        raise RevisitContractError(
            f"cycle {args.cycle} base revision does not match current pointer"
        )

    timestamp = _utc_now_seconds()
    updated = copy.deepcopy(previous)
    updated["status"] = "aborted"
    updated["aborted_at"] = timestamp
    updated["abort_reason"] = reason
    aborted = with_audit(
        previous,
        updated,
        "abort",
        [args.cycle],
        timestamp,
    )
    persist_cycle(
        workspace,
        aborted,
        expected_sha256=expected_cycle_sha256,
        authority_snapshots=(pointer_generation.snapshot, report_authority),
    )
    print(f"REVISIT CYCLE ABORTED: {args.cycle}")
    return 0


def command_abort(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_abort_in_transaction(args, workspace)


def _load_active_cycle_mutation_context(
    workspace: Path,
    cycle_id: str,
    operation: str,
) -> tuple[
    dict,
    str,
    tuple[PreparedAuthoritySnapshot, PreparedAuthoritySnapshot],
]:
    _load_ticker_state(workspace, operation)
    pointer_generation = _read_authority_generation(
        workspace,
        workspace / POINTER_FILENAME,
    )
    pointer = load_pointer(workspace)
    _require_authority_generation(
        pointer_generation,
        "after pointer validation",
    )
    current, _, _, report_authority = _require_current_report(workspace, pointer)
    json_path = cycle_json_path(workspace, cycle_id)
    expected_cycle_sha256 = sha256_file(json_path)
    cycle = load_cycle(workspace, cycle_id)
    if cycle["status"] != "active":
        raise RevisitContractError(
            f"{operation} requires active cycle {cycle_id}; "
            f"current status is {cycle['status']}"
        )
    expected_base = {
        "revision_id": current["revision_id"],
        "report_path": current["report_path"],
        "report_sha256": current["report_sha256"],
        "action_class": current["action_class"],
    }
    if cycle["intake"]["base_revision"] != expected_base:
        raise RevisitContractError(
            f"cycle {cycle_id} base revision does not match current pointer"
        )
    return (
        cycle,
        expected_cycle_sha256,
        (pointer_generation.snapshot, report_authority),
    )


def _command_add_derived_claim_in_transaction(
    args: argparse.Namespace, workspace: Path
) -> int:
    request = _load_json_object(args.request_file, "derived claim request")
    previous, expected_cycle_sha256, base_authorities = (
        _load_active_cycle_mutation_context(
            workspace,
            args.cycle,
            "add-derived-claim",
        )
    )
    proposed = add_derived_claim(previous, request)
    external_authorities: tuple[PreparedAuthoritySnapshot, ...] = ()
    if request["origin"] == "emergent":
        dispatch_authority, delivery_authority = _validate_emergent_dispatch(
            workspace,
            request["accepted_from"],
        )
        canonical_refs, evidence_authorities = _validate_evidence_references(
            workspace,
            request["accepted_from"]["evidence_refs"],
            "request.accepted_from.evidence_refs",
            forbidden_delivery_snapshot=delivery_authority,
        )
        canonical_request = copy.deepcopy(request)
        canonical_request["accepted_from"]["evidence_refs"] = canonical_refs
        proposed = add_derived_claim(previous, canonical_request)
        external_authorities = (
            dispatch_authority,
            delivery_authority,
            *evidence_authorities,
        )
    claim_id = proposed["derived_claims"][-1]["claim_id"]
    updated = with_audit(
        previous,
        proposed,
        "add-derived-claim",
        [claim_id],
        _utc_now_seconds(),
    )
    persist_cycle(
        workspace,
        updated,
        expected_sha256=expected_cycle_sha256,
        authority_snapshots=(*base_authorities, *external_authorities),
    )
    print(f"DERIVED CLAIM ADDED: {claim_id}")
    return 0


def command_add_derived_claim(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_add_derived_claim_in_transaction(args, workspace)


def _command_resolve_claim_in_transaction(
    args: argparse.Namespace, workspace: Path
) -> int:
    outcome = _load_json_object(args.resolution_file, "claim resolution")
    previous, expected_cycle_sha256, base_authorities = (
        _load_active_cycle_mutation_context(
            workspace,
            args.cycle,
            "resolve-claim",
        )
    )
    resolve_claim(previous, args.claim, outcome)
    current_refs = outcome.get("current_evidence_refs", [])
    counter_refs = outcome.get("counter_evidence_refs", [])
    combined_refs = [*current_refs, *counter_refs]
    canonical_refs, evidence_authorities = _validate_evidence_references(
        workspace,
        combined_refs,
        "outcome.evidence_refs",
    )
    canonical_outcome = copy.deepcopy(outcome)
    current_count = len(current_refs)
    canonical_outcome["current_evidence_refs"] = canonical_refs[:current_count]
    canonical_outcome["counter_evidence_refs"] = canonical_refs[current_count:]
    proposed = resolve_claim(previous, args.claim, canonical_outcome)
    updated = with_audit(
        previous,
        proposed,
        "resolve-claim",
        [args.claim],
        _utc_now_seconds(),
    )
    persist_cycle(
        workspace,
        updated,
        expected_sha256=expected_cycle_sha256,
        authority_snapshots=(*base_authorities, *evidence_authorities),
    )
    print(f"CLAIM RESOLVED: {args.claim} ({canonical_outcome['status']})")
    return 0


def command_resolve_claim(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_resolve_claim_in_transaction(args, workspace)


def _command_assess_decision_in_transaction(
    args: argparse.Namespace, workspace: Path
) -> int:
    assessment = _load_json_object(args.assessment_file, "decision assessment")
    previous, expected_cycle_sha256, base_authorities = (
        _load_active_cycle_mutation_context(
            workspace,
            args.cycle,
            "assess-decision",
        )
    )
    proposed = assess_decision(previous, assessment)
    updated = with_audit(
        previous,
        proposed,
        "assess-decision",
        [args.cycle],
        _utc_now_seconds(),
    )
    persist_cycle(
        workspace,
        updated,
        expected_sha256=expected_cycle_sha256,
        authority_snapshots=base_authorities,
    )
    print(f"DECISION ASSESSED: {args.cycle}")
    return 0


def command_assess_decision(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_assess_decision_in_transaction(args, workspace)


def command_record_rerun(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        previous, expected_cycle_sha256, base_authorities = (
            _load_active_cycle_mutation_context(
                workspace,
                args.cycle,
                "record-rerun",
            )
        )
        relative = normalize_workspace_relative_path(args.path)
        generation = _read_authority_generation(workspace, workspace / relative)
        if not generation.snapshot.resolved_target.is_file():
            raise RevisitContractError(
                f"rerun artifact is not a file: {relative}"
            )
        timestamp = _utc_now_seconds()
        artifact = {
            "kind": args.kind.replace("-", "_"),
            "scope": args.scope,
            "round": args.round,
            "path": relative,
            "sha256": generation.snapshot.expected_sha256,
            "recorded_at": timestamp,
        }
        proposed = record_rerun(previous, artifact)
        updated = with_audit(
            previous,
            proposed,
            "record-rerun",
            [relative],
            timestamp,
        )
        persist_cycle(
            workspace,
            updated,
            expected_sha256=expected_cycle_sha256,
            authority_snapshots=(*base_authorities, generation.snapshot),
        )
        print(f"RERUN ARTIFACT RECORDED: {relative}")
        return 0


def command_render_report_metadata(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        _load_ticker_state(workspace, "render-report-metadata")
        pointer = load_pointer(workspace)
        current, _, _, _ = _require_current_report(workspace, pointer)
        cycle = load_cycle(workspace, args.cycle)
        base_is_current = (
            cycle["intake"]["base_revision"]
            == _pointer_base_projection(current)
        )
        candidate_is_current = (
            cycle["status"] == "completed"
            and _current_matches_published_cycle(current, cycle)
        )
        if not base_is_current and not candidate_is_current:
            raise RevisitContractError(
                f"cycle {args.cycle} lineage does not match current pointer"
            )
        rendered = render_report_metadata(cycle)
    sys.stdout.write(rendered)
    return 0


def command_register_report(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        _load_ticker_state(workspace, "register-report")
        pointer_generation = _read_authority_generation(
            workspace, workspace / POINTER_FILENAME
        )
        pointer = load_pointer(workspace)
        _require_authority_generation(
            pointer_generation,
            "after pointer validation",
        )
        current, _, _, base_report_authority = _require_current_report(
            workspace, pointer
        )
        cycle_path = cycle_json_path(workspace, args.cycle)
        expected_cycle_sha256 = sha256_file(cycle_path)
        previous = load_cycle(workspace, args.cycle)
        if previous["report_candidate"] is not None:
            raise RevisitContractError("report candidate is already registered")
        if previous["status"] != "ready_for_report":
            raise RevisitContractError(
                "register-report requires ready_for_report status"
            )
        expected_base = {
            "revision_id": current["revision_id"],
            "report_path": current["report_path"],
            "report_sha256": current["report_sha256"],
            "action_class": current["action_class"],
        }
        if previous["intake"]["base_revision"] != expected_base:
            raise RevisitContractError(
                f"cycle {args.cycle} base revision does not match current pointer"
            )

        relative = normalize_workspace_relative_path(args.report)
        report_path = resolve_workspace_path(
            workspace,
            relative,
            parent="reports",
            suffix=".md",
        )
        if relative == current["report_path"]:
            raise RevisitContractError(
                "report path is already registered as the current revision"
            )
        history_cycles, history_closure = _load_observed_cycle_history(workspace)
        for history_cycle in history_cycles:
            candidate = history_cycle["report_candidate"]
            registered_report_paths = {
                history_cycle["intake"]["base_revision"]["report_path"]
            }
            if candidate is not None:
                registered_report_paths.add(candidate["report_path"])
            if relative in registered_report_paths:
                raise RevisitContractError(
                    "report path is already registered by "
                    f"{history_cycle['cycle_id']}"
                )
        report_generation = _read_authority_generation(
            workspace, report_path
        )
        if not report_generation.snapshot.resolved_target.is_file():
            raise RevisitContractError(
                f"report candidate is not a file: {relative}"
            )
        metadata = render_report_metadata(previous)
        report_result = evaluate_specific_ticker_report(
            workspace,
            relative,
            expected_sha256=report_generation.snapshot.expected_sha256,
            expected_metadata=metadata,
        )
        if not report_result.passed:
            for issue in report_result.failures:
                print(issue.display(), file=sys.stderr)
            return 1
        _require_authority_generation(
            report_generation,
            "after report candidate evaluation",
        )
        timestamp = _utc_now_seconds()
        candidate = {
            "revision_id": previous["candidate_revision_id"],
            "revision_of": current["revision_id"],
            "report_path": relative,
            "report_sha256": report_generation.snapshot.expected_sha256,
            "registered_at": timestamp,
        }
        proposed = register_report_candidate(previous, candidate)
        updated = with_audit(
            previous,
            proposed,
            "register-report",
            [candidate["revision_id"]],
            timestamp,
        )
        persist_cycle(
            workspace,
            updated,
            expected_sha256=expected_cycle_sha256,
            authority_snapshots=(
                pointer_generation.snapshot,
                base_report_authority,
                report_generation.snapshot,
            ),
            generation_closure=history_closure,
        )
        print(f"REPORT CANDIDATE REGISTERED: {relative}")
        return 0


def _pointer_base_projection(current: dict | None) -> dict | None:
    if current is None:
        return None
    return {
        "revision_id": current["revision_id"],
        "report_path": current["report_path"],
        "report_sha256": current["report_sha256"],
        "action_class": current["action_class"],
    }


def _published_revision(cycle: dict, validated_at: str) -> dict:
    candidate = cycle["report_candidate"]
    if candidate is None:
        raise RevisitContractError(
            "REVISIT_PUBLICATION_FAILED: report candidate is missing"
        )
    return {
        "revision_id": candidate["revision_id"],
        "cycle_id": cycle["cycle_id"],
        "report_path": candidate["report_path"],
        "report_sha256": candidate["report_sha256"],
        "action_class": cycle["decision_assessment"]["new_action_class"],
        "validated_at": validated_at,
        "revision_of": candidate["revision_of"],
    }


def _current_matches_published_cycle(current: dict | None, cycle: dict) -> bool:
    if current is None:
        return False
    expected = _published_revision(cycle, current["validated_at"])
    return current == expected


def _publication_state(
    pointer: dict,
    cycle: dict,
    history,
) -> str:
    current = pointer["current_revision"]
    candidate = cycle["report_candidate"]
    if candidate is None:
        raise RevisitContractError(
            "REVISIT_PUBLICATION_FAILED: report candidate is missing"
        )
    if cycle["status"] == "ready_for_report":
        if _pointer_base_projection(current) != cycle["intake"]["base_revision"]:
            raise RevisitContractError(
                "REVISIT_PUBLICATION_FAILED: current revision differs from cycle base"
            )
        return "ready"
    if cycle["status"] != "completed":
        raise RevisitContractError(
            "REVISIT_PUBLICATION_FAILED: publish requires a ready or completed cycle"
        )
    if _current_matches_published_cycle(current, cycle):
        return "already_current"
    if _pointer_base_projection(current) != cycle["intake"]["base_revision"]:
        raise RevisitContractError(
            "REVISIT_PUBLICATION_FAILED: current revision conflicts with completed candidate"
        )
    if history.completed_unpublished_cycle_ids != (cycle["cycle_id"],):
        raise RevisitContractError(
            "REVISIT_PUBLICATION_FAILED: completed cycle is not the sole unpublished candidate"
        )
    return "completed_unpublished"


def _print_revisit_result(result) -> None:
    for warning in result.warnings:
        print(warning.display(), file=sys.stderr)
    for failure in result.failures:
        print(failure.display(), file=sys.stderr)


def _persist_published_pointer(
    workspace: Path,
    pointer: dict,
    cycle: dict,
    validated_at: str,
    expected_pointer_sha256: str,
    authority_snapshots: tuple[PreparedAuthoritySnapshot, ...],
    generation_closure,
) -> None:
    updated_pointer = copy.deepcopy(pointer)
    updated_pointer["current_revision"] = _published_revision(
        cycle,
        validated_at,
    )
    persist_pointer(
        workspace,
        updated_pointer,
        expected_sha256=expected_pointer_sha256,
        authority_snapshots=authority_snapshots,
        generation_closure=generation_closure,
    )


def command_publish(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        _load_ticker_state(workspace, "publish")
        pointer_generation = _read_authority_generation(
            workspace,
            workspace / POINTER_FILENAME,
        )
        pointer = load_pointer(workspace)
        cycle_generation = _read_authority_generation(
            workspace,
            cycle_json_path(workspace, args.cycle),
        )
        cycle = load_cycle(workspace, args.cycle)
        all_cycles = [
            load_cycle(workspace, cycle_id)
            for cycle_id in list_cycle_ids(workspace)
        ]
        history = evaluate_history(pointer, all_cycles)
        state = _publication_state(pointer, cycle, history)
        history.require_valid()

        if state == "already_current":
            prepared_current = _prepare_published_current_for_publication(
                workspace,
                cycle,
            )
            if not prepared_current.result.passed:
                _print_revisit_result(prepared_current.result)
                return 1
            if prepared_current.generation_closure is None:
                raise RevisitContractError(
                    "REVISIT_PUBLICATION_FAILED: current validation lacks authority closure"
                )
            _require_authority_generation(
                pointer_generation,
                "after current publication validation",
            )
            _require_authority_generation(
                cycle_generation,
                "after current publication validation",
            )
            _require_snapshot_generations(
                {
                    snapshot.lexical_path: snapshot
                    for snapshot in prepared_current.authority_snapshots
                },
                "after current publication validation",
            )
            prepared_current.generation_closure.require_unchanged()
            print(
                "REVISIT REPORT ALREADY PUBLISHED: "
                f"{cycle['candidate_revision_id']}"
            )
            return 0

        prepared = _prepare_revisit_report_for_publication(
            workspace,
            args.cycle,
        )
        if not prepared.result.passed:
            _print_revisit_result(prepared.result)
            return 1
        if prepared.generation_closure is None or prepared.cycle is None:
            raise RevisitContractError(
                "REVISIT_PUBLICATION_FAILED: final preparation lacks authority closure"
            )
        publication_authorities = prepared.authority_snapshots
        _require_authority_generation(
            pointer_generation,
            "after final publication validation",
        )
        _require_authority_generation(
            cycle_generation,
            "after final publication validation",
        )

        timestamp = _utc_now_seconds()
        if state == "ready":
            proposed = complete_cycle(cycle, timestamp)
            completed = with_audit(
                cycle,
                proposed,
                "publish",
                [args.cycle, cycle["candidate_revision_id"]],
                timestamp,
            )
            persist_cycle(
                workspace,
                completed,
                expected_sha256=cycle_generation.snapshot.expected_sha256,
                authority_snapshots=publication_authorities,
                generation_closure=prepared.generation_closure,
            )
            cycle = completed
            prepared = _prepare_revisit_report_for_publication(
                workspace,
                args.cycle,
            )
            if not prepared.result.passed:
                _print_revisit_result(prepared.result)
                return 1
            if prepared.generation_closure is None or prepared.cycle is None:
                raise RevisitContractError(
                    "REVISIT_PUBLICATION_FAILED: completed preparation lacks authority closure"
                )
            cycle = prepared.cycle
            publication_authorities = prepared.authority_snapshots

        _persist_published_pointer(
            workspace,
            pointer,
            cycle,
            timestamp,
            pointer_generation.snapshot.expected_sha256,
            publication_authorities,
            prepared.generation_closure,
        )
        print(f"REVISIT REPORT PUBLISHED: {cycle['candidate_revision_id']}")
        return 0


def _command_bind_frontier_in_transaction(
    args: argparse.Namespace, workspace: Path
) -> int:
    cycle, expected_cycle_sha256, base_authorities = (
        _load_active_cycle_mutation_context(
        workspace,
        args.cycle,
        "bind-frontier",
        )
    )
    (
        registry,
        loop_counts,
        headers,
        registry_authority,
        ledger_authority,
    ) = _load_frontier_binding_snapshot(workspace)
    boundary = cycle["intake"]["workspace_boundary"][
        "max_existing_loop_number"
    ]
    post_boundary = [
        loop_number
        for loop_number, frontier_id in headers
        if frontier_id == args.frontier and loop_number > boundary
    ]
    if post_boundary:
        raise RevisitContractError(
            f"frontier {args.frontier} has post-boundary loop "
            f"{min(post_boundary)}; bind before new loops"
        )

    frontier = get_frontier(registry, args.frontier)
    if args.action == "reactivated":
        if frontier.get("status") != "Active":
            raise RevisitContractError(
                f"reactivated frontier {args.frontier} must be Active"
            )
    else:
        if frontier.get("status") not in {"New", "Active"}:
            raise RevisitContractError(
                f"added frontier {args.frontier} must be New or Active"
            )

    binding = {
        "frontier_id": args.frontier,
        "action": args.action,
        "claim_ids": list(args.claims),
        "expected_evidence": args.expected_evidence,
        "baseline_loop_count": int(loop_counts.get(args.frontier, 0)),
        "baseline_review_count": int(frontier.get("review_count", 0)),
        "registry_sha256": registry_authority.expected_sha256,
        "bound_at": _utc_now_seconds(),
    }
    legality_issue = derive_frontier_binding_legality_issue(
        cycle,
        binding,
        frontier,
    )
    if legality_issue is not None:
        raise RevisitContractError(legality_issue.message)
    proposed = bind_frontier(cycle, binding)
    updated = with_audit(
        cycle,
        proposed,
        "bind-frontier",
        [args.frontier, *args.claims],
        binding["bound_at"],
    )
    persist_cycle(
        workspace,
        updated,
        expected_sha256=expected_cycle_sha256,
        authority_snapshots=(
            *base_authorities,
            registry_authority,
            ledger_authority,
        ),
    )
    print(f"FRONTIER BOUND: {args.frontier}")
    return 0


def command_bind_frontier(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_bind_frontier_in_transaction(args, workspace)


def command_check(args: argparse.Namespace) -> int:
    if args.final:
        result = _prepare_revisit_report_for_publication(
            Path(args.workspace),
            args.cycle,
        ).result
        if args.json:
            print(
                json.dumps(
                    {
                        "passed": result.passed,
                        "failures": [
                            {
                                "code": issue.code,
                                "path": issue.path,
                                "message": issue.message,
                                "evidence": issue.evidence,
                            }
                            for issue in result.failures
                        ],
                        "warnings": [
                            {
                                "code": issue.code,
                                "path": issue.path,
                                "message": issue.message,
                                "evidence": issue.evidence,
                            }
                            for issue in result.warnings
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            for warning in result.warnings:
                print(warning.display(), file=sys.stderr)
            if not result.passed:
                for failure in result.failures:
                    print(failure.display(), file=sys.stderr)
            else:
                print(f"REVISIT FINAL CHECK PASSED: {args.cycle}")
        return 0 if result.passed else 1
    outcome = check_revisit_readiness(
        Path(args.workspace),
        args.cycle,
        timestamp=_utc_now_seconds(),
    )
    for warning in outcome.result.warnings:
        print(warning.display(), file=sys.stderr)
    if not outcome.result.passed:
        for failure in outcome.result.failures:
            print(failure.display(), file=sys.stderr)
        return 1
    print(f"REVISIT CYCLE READY: {outcome.cycle_id}")
    return 0


def _command_register_current_in_transaction(
    args: argparse.Namespace, workspace: Path
) -> int:
    _load_ticker_state(workspace, "register-current")

    current_pointer_path = workspace / POINTER_FILENAME
    expected_pointer_sha256 = (
        sha256_file(current_pointer_path) if current_pointer_path.exists() else None
    )
    existing = load_pointer(workspace, allow_missing=True)
    if existing is None:
        pointer = empty_pointer()
    else:
        if existing["current_revision"] is not None:
            raise RevisitContractError("current report is already registered")
        pointer = existing

    existing_cycles = [
        load_cycle(workspace, cycle_id)
        for cycle_id in list_cycle_ids(workspace)
    ]
    evaluate_history(pointer, existing_cycles).require_valid()

    report_relative = normalize_workspace_relative_path(args.report)
    report_generation = _read_authority_generation(
        workspace,
        workspace / report_relative,
    )
    relative, payload, _ = read_specific_markdown_report(workspace, args.report)
    _require_owner_generation(
        report_generation,
        payload,
        "current report",
    )
    report_sha256 = report_generation.snapshot.expected_sha256
    report_result = evaluate_specific_ticker_report(
        workspace,
        relative,
        expected_sha256=report_sha256,
    )
    if not report_result.passed:
        for issue in report_result.failures:
            print(issue.display(), file=sys.stderr)
        return 1
    _require_authority_generation(
        report_generation,
        "after current report evaluation",
    )

    pointer["current_revision"] = {
        "revision_id": "REV-0001",
        "cycle_id": None,
        "report_path": relative,
        "report_sha256": report_sha256,
        "action_class": args.action_class,
        "validated_at": _utc_now_seconds(),
        "revision_of": None,
    }

    cycles = cycle_directory(workspace)
    created_cycles = False
    try:
        if cycles.exists():
            if not cycles.is_dir():
                raise RevisitContractError("revisit_cycles must be a directory")
        else:
            cycles.mkdir(parents=False)
            created_cycles = True
        persist_pointer(
            workspace,
            pointer,
            expected_sha256=expected_pointer_sha256,
            authority_snapshots=(report_generation.snapshot,),
        )
    except Exception:
        if created_cycles:
            cycles.rmdir()
        raise

    print(f"CURRENT REPORT REGISTERED: {relative}")
    return 0


def command_register_current(args: argparse.Namespace) -> int:
    with workspace_transaction(Path(args.workspace)) as workspace:
        return _command_register_current_in_transaction(args, workspace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage SOFA ticker revisit cycles")
    parser.add_argument("workspace", help="SOFA ticker workspace")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser(
        "register-current",
        help="explicitly register an existing complete ticker report",
    )
    register.add_argument("--report", required=True, help="Markdown report under reports/")
    register.add_argument(
        "--action-class",
        required=True,
        choices=ACTION_CLASSES,
        help="locked SOFA action class",
    )
    register.set_defaults(handler=command_register_current)
    start = subparsers.add_parser(
        "start",
        help="create one immutable revisit cycle from an explicit request",
    )
    start.add_argument(
        "--intake-file",
        required=True,
        help="temporary JSON request containing triggers and selected claims",
    )
    start.set_defaults(handler=command_start)
    status = subparsers.add_parser(
        "status",
        help="show current revision, cycle history, and the next legal command",
    )
    status.add_argument("cycle", nargs="?", help="optional cycle ID to display")
    status.add_argument(
        "--json",
        action="store_true",
        help="emit deterministic JSON instead of text",
    )
    status.set_defaults(handler=command_status)
    abort = subparsers.add_parser(
        "abort",
        help="terminally close an active or ready revisit cycle",
    )
    abort.add_argument("cycle", help="cycle ID to abort")
    abort.add_argument(
        "--reason",
        required=True,
        help="non-empty explicit reason for stopping the cycle",
    )
    abort.set_defaults(handler=command_abort)
    derived = subparsers.add_parser(
        "add-derived-claim",
        help="add a split-child or accepted emergent cycle claim",
    )
    derived.add_argument("cycle", help="active revisit cycle ID")
    derived.add_argument(
        "--request-file",
        required=True,
        help="JSON split-child or emergent claim request",
    )
    derived.set_defaults(handler=command_add_derived_claim)
    resolve = subparsers.add_parser(
        "resolve-claim",
        help="record one terminal main-thread claim outcome",
    )
    resolve.add_argument("cycle", help="active revisit cycle ID")
    resolve.add_argument("claim", help="selected or derived cycle claim ID")
    resolve.add_argument(
        "--resolution-file",
        required=True,
        help="JSON terminal claim resolution",
    )
    resolve.set_defaults(handler=command_resolve_claim)
    assess = subparsers.add_parser(
        "assess-decision",
        help="record one main-thread decision assessment and derive rerun duties",
    )
    assess.add_argument("cycle", help="active revisit cycle ID")
    assess.add_argument(
        "--assessment-file",
        required=True,
        help="JSON main-thread decision assessment",
    )
    assess.set_defaults(handler=command_assess_decision)
    rerun = subparsers.add_parser(
        "record-rerun",
        help="register one exact cycle-specific downstream rerun artifact",
    )
    rerun.add_argument("cycle", help="active revisit cycle ID")
    rerun.add_argument(
        "--kind",
        required=True,
        choices=(
            "bridge",
            "redteam-attack",
            "redteam-defense",
            "thesis-revision",
        ),
    )
    rerun.add_argument("--path", required=True, help="workspace-relative artifact path")
    rerun.add_argument("--scope", choices=("affected", "full"))
    rerun.add_argument("--round", type=int)
    rerun.set_defaults(handler=command_record_rerun)
    metadata = subparsers.add_parser(
        "render-report-metadata",
        help="render the exact managed report revision metadata block",
    )
    metadata.add_argument("cycle", help="ready or completed revisit cycle ID")
    metadata.set_defaults(handler=command_render_report_metadata)
    candidate = subparsers.add_parser(
        "register-report",
        help="register one immutable complete report revision candidate",
    )
    candidate.add_argument("cycle", help="ready revisit cycle ID")
    candidate.add_argument(
        "--report",
        required=True,
        help="new complete Markdown report under reports/",
    )
    candidate.set_defaults(handler=command_register_report)
    publish = subparsers.add_parser(
        "publish",
        help="atomically publish one validated immutable report revision",
    )
    publish.add_argument("cycle", help="ready or completed revisit cycle ID")
    publish.set_defaults(handler=command_publish)
    bind = subparsers.add_parser(
        "bind-frontier",
        help="bind one legal cycle-relative frontier before new loop work",
    )
    bind.add_argument("cycle", help="active revisit cycle ID")
    bind.add_argument("--frontier", required=True, help="stable frontier ID")
    bind.add_argument(
        "--action",
        required=True,
        choices=("reactivated", "added"),
    )
    bind.add_argument(
        "--claim",
        dest="claims",
        action="append",
        required=True,
        help="selected or derived same-cycle claim ID",
    )
    bind.add_argument("--expected-evidence", required=True)
    bind.set_defaults(handler=command_bind_frontier)
    check = subparsers.add_parser(
        "check",
        help="evaluate one cycle and mark it ready for report when complete",
    )
    check.add_argument("cycle", help="active or ready revisit cycle ID")
    check.add_argument(
        "--final",
        action="store_true",
        help="read-only validation of the exact registered report candidate",
    )
    check.add_argument(
        "--json",
        action="store_true",
        help="emit deterministic JSON for final checks",
    )
    check.set_defaults(handler=command_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, RevisitContractError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
