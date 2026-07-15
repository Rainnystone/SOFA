#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from revisit_contract import (
    ACTION_CLASSES,
    RevisitContractError,
    allocate_cycle_and_revision_ids,
    create_cycle,
    cycle_directory,
    cycle_json_path,
    empty_pointer,
    list_cycle_ids,
    load_cycle,
    load_pointer,
    persist_cycle,
    persist_pointer,
    pointer_path,
    sha256_bytes,
    sha256_file,
)
from revisit_contract.model import with_audit
from revisit_contract.store import load_intake_request, verify_workspace_artifact
from framing_contract import evaluate_contract, load_contract
from frontier_lifecycle import LOOP_HEADER_RE, derive_loop_counts
from frontier_review import read_registry_snapshot
from source_cache import evaluate_index
from sofa_contract.evaluate import evaluate_specific_ticker_report
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


def _load_ticker_state(workspace: Path) -> dict:
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
        raise RevisitContractError(
            "register-current is available only for ticker workspaces"
        )
    return state


def _utc_now_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_current_report(
    workspace: Path, pointer: dict
) -> tuple[dict, Path, str]:
    current = pointer["current_revision"]
    if current is None:
        raise RevisitContractError(
            "current report is not registered; run register-current first"
        )
    relative, payload, _ = read_specific_markdown_report(
        workspace, current["report_path"]
    )
    if relative != current["report_path"]:
        raise RevisitContractError(
            "pointer current report path is not canonical: "
            f"{current['report_path']}"
        )
    result = evaluate_specific_ticker_report(
        workspace,
        relative,
        expected_sha256=current["report_sha256"],
    )
    if not result.passed:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in result.failures
        )
        raise RevisitContractError(details)
    return current, workspace / relative, sha256_bytes(payload)


def _load_revisit_framing(workspace: Path) -> tuple[dict, Path, str]:
    path = workspace / "framing_contract.json"
    payload = path.read_bytes()
    contract = load_contract(workspace)
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
    return snapshot, path, sha256_bytes(payload)


def _load_workspace_boundary(
    workspace: Path,
) -> tuple[dict, Path, str, Path, str, int]:
    registry, registry_payload = read_registry_snapshot(workspace)
    if registry.get("mode") != "ticker":
        raise RevisitContractError("frontier registry mode must be ticker")
    ledger_path = workspace / "evidence_ledger.md"
    ledger_payload = ledger_path.read_bytes()
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
    return (
        registry,
        workspace / "frontier_registry.json",
        sha256_bytes(registry_payload),
        ledger_path,
        sha256_bytes(ledger_payload),
        max_loop_number,
    )


def _validate_request_references(
    workspace: Path, request: dict
) -> tuple[dict, dict[Path, str]]:
    canonical = copy.deepcopy(request)
    evaluation = evaluate_index(workspace)
    if evaluation.issues:
        details = "; ".join(
            f"{issue.code} at {issue.location}: {issue.message}"
            for issue in evaluation.issues
        )
        raise RevisitContractError(f"source cache failed validation: {details}")
    registered_source_ids = {
        str(record["source_id"]) for record in evaluation.records
    }
    artifact_snapshots: dict[Path, str] = {}

    def validate_reference(ref: dict) -> None:
        if ref["kind"] == "source":
            if ref["source_id"] not in registered_source_ids:
                raise RevisitContractError(
                    f"source_id is not registered: {ref['source_id']}"
                )
            return
        relative, payload = verify_workspace_artifact(
            workspace, ref["path"], ref["sha256"]
        )
        ref["path"] = relative
        artifact_snapshots[workspace / relative] = sha256_bytes(payload)

    for trigger in canonical["triggers"]:
        for ref in trigger["evidence_refs"]:
            validate_reference(ref)
    for claim in canonical["selected_claims"]:
        source_ref = claim["source_ref"]
        relative, payload = verify_workspace_artifact(
            workspace, source_ref["path"], source_ref["sha256"]
        )
        source_ref["path"] = relative
        artifact_snapshots[workspace / relative] = sha256_bytes(payload)
        for inherited in claim["inherited_evidence"]:
            validate_reference(inherited["ref"])
    return canonical, artifact_snapshots


def _require_unchanged_authorities(snapshots: dict[Path, str]) -> None:
    for path, expected_sha256 in snapshots.items():
        try:
            current_sha256 = sha256_file(path)
        except FileNotFoundError as exc:
            raise RevisitContractError(
                f"authority disappeared before cycle persistence: {path.name}"
            ) from exc
        if current_sha256 != expected_sha256:
            raise RevisitContractError(
                f"authority changed before cycle persistence: {path.name}"
            )


def _is_completed_unpublished(
    cycle: dict, current_revision: dict | None
) -> bool:
    if cycle["status"] != "completed":
        return False
    if current_revision is None:
        return True
    candidate_number = int(cycle["candidate_revision_id"].removeprefix("REV-"))
    current_number = int(current_revision["revision_id"].removeprefix("REV-"))
    return candidate_number > current_number


def command_start(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    _load_ticker_state(workspace)
    request = load_intake_request(args.intake_file)
    request, artifact_snapshots = _validate_request_references(workspace, request)

    current_pointer_path = pointer_path(workspace)
    expected_pointer_sha256 = sha256_file(current_pointer_path)
    pointer = load_pointer(workspace)
    current, report_path, report_sha256 = _require_current_report(
        workspace, pointer
    )

    cycle_ids = list_cycle_ids(workspace)
    cycles = [load_cycle(workspace, cycle_id) for cycle_id in cycle_ids]
    for cycle in cycles:
        if cycle["status"] in {"active", "ready_for_report"}:
            raise RevisitContractError(
                f"cycle conflict: {cycle['cycle_id']} is {cycle['status']}"
            )
        if _is_completed_unpublished(cycle, current):
            raise RevisitContractError(
                f"cycle conflict: {cycle['cycle_id']} is completed-unpublished"
            )

    framing_snapshot, framing_path, framing_sha256 = _load_revisit_framing(
        workspace
    )
    (
        _,
        registry_path,
        registry_sha256,
        ledger_path,
        ledger_sha256,
        max_loop_number,
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

    snapshots = {
        current_pointer_path: expected_pointer_sha256,
        report_path: report_sha256,
        framing_path: framing_sha256,
        registry_path: registry_sha256,
        ledger_path: ledger_sha256,
        **artifact_snapshots,
    }
    _require_unchanged_authorities(snapshots)
    persist_cycle(workspace, cycle, expected_sha256=None)
    print(
        f"REVISIT CYCLE STARTED: {cycle_id} "
        f"(candidate {candidate_revision_id})"
    )
    return 0


def _operational_cycle_status(cycle: dict, current_revision: dict | None) -> str:
    if _is_completed_unpublished(cycle, current_revision):
        return "completed-unpublished"
    return cycle["status"]


def _status_summary(workspace: Path, selected_cycle_id: str | None) -> dict:
    pointer = load_pointer(workspace)
    current = pointer["current_revision"]
    all_cycles = [
        load_cycle(workspace, cycle_id)
        for cycle_id in list_cycle_ids(workspace)
    ]
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
    for cycle in selected_cycles:
        cycles.append(
            {
                "cycle_id": cycle["cycle_id"],
                "candidate_revision_id": cycle["candidate_revision_id"],
                "status": _operational_cycle_status(cycle, current),
                "created_at": cycle["created_at"],
                "completed_at": cycle["completed_at"],
                "aborted_at": cycle["aborted_at"],
                "abort_reason": cycle["abort_reason"],
            }
        )

    completed_unpublished = next(
        (
            cycle
            for cycle in all_cycles
            if _operational_cycle_status(cycle, current)
            == "completed-unpublished"
        ),
        None,
    )
    nonterminal = next(
        (
            cycle
            for cycle in all_cycles
            if cycle["status"] in {"active", "ready_for_report"}
        ),
        None,
    )
    if current is None:
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
        "issues": [],
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
    lines.append(f"NEXT LEGAL COMMAND: {summary['next_legal_command']}")
    return "\n".join(lines) + "\n"


def command_status(args: argparse.Namespace) -> int:
    summary = _status_summary(Path(args.workspace), args.cycle)
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


def command_abort(args: argparse.Namespace) -> int:
    reason = args.reason
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or any(unicodedata.category(character) == "Cc" for character in reason)
    ):
        raise RevisitContractError(
            "abort reason must be non-empty text without control characters"
        )

    workspace = Path(args.workspace)
    _load_ticker_state(workspace)
    current_pointer_path = pointer_path(workspace)
    expected_pointer_sha256 = sha256_file(current_pointer_path)
    pointer = load_pointer(workspace)
    current, report_path, report_sha256 = _require_current_report(
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
    _require_unchanged_authorities(
        {
            current_pointer_path: expected_pointer_sha256,
            report_path: report_sha256,
        }
    )
    persist_cycle(
        workspace,
        aborted,
        expected_sha256=expected_cycle_sha256,
    )
    print(f"REVISIT CYCLE ABORTED: {args.cycle}")
    return 0


def command_register_current(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    _load_ticker_state(workspace)

    current_pointer_path = pointer_path(workspace)
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

    relative, payload, _ = read_specific_markdown_report(workspace, args.report)
    report_sha256 = sha256_bytes(payload)
    report_result = evaluate_specific_ticker_report(
        workspace,
        relative,
        expected_sha256=report_sha256,
    )
    if not report_result.passed:
        for issue in report_result.failures:
            print(issue.display(), file=sys.stderr)
        return 1

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
        )
    except Exception:
        if created_cycles:
            cycles.rmdir()
        raise

    print(f"CURRENT REPORT REGISTERED: {relative}")
    return 0


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
