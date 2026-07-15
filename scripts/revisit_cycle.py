#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from revisit_contract import (
    ACTION_CLASSES,
    RevisitContractError,
    cycle_directory,
    empty_pointer,
    load_pointer,
    persist_pointer,
    pointer_path,
    sha256_bytes,
    sha256_file,
)
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


def command_register_current(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    _load_ticker_state(workspace)

    existing = load_pointer(workspace, allow_missing=True)
    expected_pointer_sha256 = None
    if existing is None:
        pointer = empty_pointer()
    else:
        if existing["current_revision"] is not None:
            raise RevisitContractError("current report is already registered")
        pointer = existing
        expected_pointer_sha256 = sha256_file(pointer_path(workspace))

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
