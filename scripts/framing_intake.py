#!/usr/bin/env python3
"""SOFA Stage 0 framing intent contract mutation CLI.

The only supported mutation path for framing_contract.json and its managed
Markdown mirror in research_workflow.md. Every mutating subcommand rewrites
the JSON atomically (tempfile-and-replace) and re-renders the mirror in the
same operation.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framing_contract import (  # noqa: E402
    UNKNOWN_ACCEPTED,
    add_candidate,
    add_clarification,
    apply_field,
    empty_contract,
    evaluate_contract,
    load_contract,
    render_contract_markdown,
    resolve_subject,
    save_contract,
)
from workspace_contract import managed_block_for_name, replace_managed_block  # noqa: E402


def command_init(workspace: Path, _args: argparse.Namespace) -> int:
    workflow_path = workspace / "research_workflow.md"
    if not workflow_path.exists():
        # A pre-Phase-5 workspace should always have research_workflow.md
        # (Phase 1 made it a core required file). If it is missing, the
        # workspace was not initialized properly; tell the user to run
        # init_workspace.py first rather than crashing mid-render.
        raise ValueError(
            "research_workflow.md not found. Run "
            "python scripts/init_workspace.py <subject> <workspace> --mode <ticker|sector> "
            "before framing_intake.py init."
        )
    if not (workspace / "framing_contract.json").exists():
        contract = empty_contract()
        save_contract(workspace, contract)
    else:
        contract = load_contract(workspace)
    render_into_workflow(workspace, contract)
    print("Framing intent contract initialized.")
    return 0


def command_set(workspace: Path, args: argparse.Namespace) -> int:
    if bool(args.value) == bool(args.unknown_accepted):
        raise ValueError("set requires exactly one of --value or --unknown-accepted.")
    contract = load_contract(workspace)
    value = UNKNOWN_ACCEPTED if args.unknown_accepted else args.value
    apply_field(contract, args.field, value)
    save_and_render(workspace, contract)
    print(f"Framing field updated: {args.field}")
    return 0


def command_resolve_subject(workspace: Path, args: argparse.Namespace) -> int:
    contract = load_contract(workspace)
    resolve_subject(
        contract,
        name=args.name,
        tickers=args.ticker,
        exchange=args.exchange,
        method=args.method,
    )
    save_and_render(workspace, contract)
    print("Subject resolution updated.")
    return 0


def command_add_candidate(workspace: Path, args: argparse.Namespace) -> int:
    contract = load_contract(workspace)
    # The CLI flag stays --reason for brevity, but it maps to the model's
    # reason_excluded field (semantic: the rationale for excluding this
    # candidate). add_candidate validates all four fields are non-empty.
    add_candidate(
        contract,
        name=args.name,
        ticker=args.ticker,
        exchange=args.exchange,
        reason_excluded=args.reason,
    )
    save_and_render(workspace, contract)
    print("Disambiguation candidate recorded.")
    return 0


def command_add_clarification(workspace: Path, args: argparse.Namespace) -> int:
    contract = load_contract(workspace)
    add_clarification(contract, question=args.question, answer=args.answer)
    save_and_render(workspace, contract)
    print("Clarification recorded.")
    return 0


def command_status(workspace: Path, args: argparse.Namespace) -> int:
    contract = load_contract(workspace)
    evaluation = evaluate_contract(contract)
    if args.json:
        print(
            json.dumps(
                {
                    "complete": evaluation.complete,
                    "fields": [asdict(field) for field in evaluation.fields],
                    "issues": [asdict(issue) for issue in evaluation.issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("Framing contract complete." if evaluation.complete else "Framing contract incomplete.")
        for issue in evaluation.issues:
            print(f"- {issue.code}: {issue.field}: {issue.message}")
    return 0


def command_render(workspace: Path, _args: argparse.Namespace) -> int:
    contract = load_contract(workspace)
    render_into_workflow(workspace, contract)
    print("Framing contract mirror rendered.")
    return 0


def save_and_render(workspace: Path, contract: dict) -> None:
    save_contract(workspace, contract)
    render_into_workflow(workspace, contract)


def render_into_workflow(workspace: Path, contract: dict) -> None:
    workflow_path = workspace / "research_workflow.md"
    text = workflow_path.read_text(encoding="utf-8")
    block = managed_block_for_name("framing-contract")
    rendered = render_contract_markdown(contract)
    if block.start_marker in text or block.end_marker in text:
        updated = replace_managed_block(text, "framing-contract", rendered)
    else:
        managed = f"## {block.heading}\n{block.start_marker}\n{rendered.rstrip()}\n{block.end_marker}\n\n"
        marker = "\n## Stage Progress"
        if marker in text:
            updated = text.replace(marker, "\n" + managed.rstrip() + marker, 1)
        else:
            updated = text.rstrip() + "\n\n" + managed
    workflow_path.write_text(updated, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mutate the SOFA framing intent contract.")
    parser.add_argument("workspace", help="SOFA workspace directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create missing framing contract and mirror").set_defaults(func=command_init)

    set_parser = subparsers.add_parser("set", help="Set a top-level framing field")
    set_parser.add_argument("--field", required=True)
    set_parser.add_argument("--value")
    set_parser.add_argument("--unknown-accepted", action="store_true")
    set_parser.set_defaults(func=command_set)

    resolve_parser = subparsers.add_parser("resolve-subject", help="Record subject resolution")
    resolve_parser.add_argument("--name", required=True)
    resolve_parser.add_argument("--ticker", action="append", default=[])
    resolve_parser.add_argument("--exchange", required=True)
    resolve_parser.add_argument("--method", required=True)
    resolve_parser.set_defaults(func=command_resolve_subject)

    candidate_parser = subparsers.add_parser("add-candidate", help="Record a subject disambiguation candidate")
    candidate_parser.add_argument("--name", required=True)
    candidate_parser.add_argument("--ticker", default="")
    candidate_parser.add_argument("--exchange", default="")
    candidate_parser.add_argument("--reason", required=True)
    candidate_parser.set_defaults(func=command_add_candidate)

    clarification_parser = subparsers.add_parser("add-clarification", help="Record a clarification")
    clarification_parser.add_argument("--question", required=True)
    clarification_parser.add_argument("--answer", required=True)
    clarification_parser.set_defaults(func=command_add_clarification)

    status_parser = subparsers.add_parser("status", help="Show completion status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=command_status)

    subparsers.add_parser("render", help="Render the Markdown mirror").set_defaults(func=command_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace = Path(args.workspace)
    try:
        return args.func(workspace, args)
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
