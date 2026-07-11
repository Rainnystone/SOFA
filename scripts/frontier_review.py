#!/usr/bin/env python3
"""Manage SOFA frontier registry state and managed review logs."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from frontier_lifecycle import (
    CURRENT_REGISTRY_VERSION,
    LifecycleError,
    bind_frontier_layer,
    check_review_due,
    create_frontier,
    derive_frontier_layer_coverage,
    derive_loop_counts,
    format_frontier_layer_advisories,
    get_frontier,
    render_frontier_layer_coverage_md,
    render_discovery_log_md,
    render_review_log_md,
    set_layer_labels,
    transition,
    validate_registry,
)
from workspace_contract import (
    replace_managed_block,
    replace_managed_block_after,
    upsert_managed_block_after,
)


REGISTRY_FILE = "frontier_registry.json"
LEDGER_FILE = "evidence_ledger.md"
WORKFLOW_FILE = "research_workflow.md"
REVIEW_BLOCK = "frontier-review-log"
DISCOVERY_BLOCK = "frontier-discovery-log"
LAYER_BLOCK = "frontier-layer-coverage"
COMMANDS = frozenset(
    {
        "add",
        "bind-layer",
        "start",
        "check-review",
        "record",
        "retire",
        "reactivate",
        "set-layers",
        "status",
    }
)


class PersistenceRollbackError(OSError):
    """Both workflow persistence and registry rollback failed."""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_argv(sys.argv[1:] if argv is None else argv))

    try:
        return args.handler(args)
    except (LifecycleError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage SOFA frontier reviews")
    parser.add_argument(
        "--workspace",
        default=".",
        help="SOFA workspace path containing frontier_registry.json",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Create a New frontier")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument(
        "--source",
        required=True,
        choices=["initial", "discovery", "serendipity", "user"],
    )
    add_parser.add_argument("--source-frontier")
    add_parser.add_argument("--layer", type=_layer_index)
    add_parser.add_argument("--parent", dest="parent_frontier")
    add_parser.add_argument("--at-loop", required=True, type=_positive_int)
    add_parser.set_defaults(handler=command_add)

    set_layers_parser = subparsers.add_parser(
        "set-layers",
        help="Register or replace workspace layer labels",
    )
    set_layers_parser.add_argument(
        "--label",
        dest="labels",
        action="append",
        nargs=2,
        required=True,
        metavar=("INDEX", "TEXT"),
    )
    set_layers_parser.add_argument("--replace", action="store_true")
    set_layers_parser.set_defaults(handler=command_set_layers)

    bind_parser = subparsers.add_parser(
        "bind-layer",
        help="Bind, rebind, or clear one frontier layer",
    )
    bind_parser.add_argument("frontier_id")
    binding = bind_parser.add_mutually_exclusive_group(required=True)
    binding.add_argument("--layer", type=_layer_index)
    binding.add_argument("--clear", action="store_true")
    bind_parser.add_argument("--parent", dest="parent_frontier")
    bind_parser.set_defaults(handler=command_bind_layer)

    start_parser = subparsers.add_parser("start", help="Activate a New frontier")
    start_parser.add_argument("frontier_id")
    start_parser.set_defaults(handler=command_start)

    check_parser = subparsers.add_parser("check-review", help="Check review due frontiers")
    check_parser.set_defaults(handler=command_check_review)

    record_parser = subparsers.add_parser("record", help="Record a frontier review")
    record_parser.add_argument("frontier_id")
    record_parser.add_argument("--decision", required=True, choices=["Continued", "Retired"])
    record_parser.add_argument("--rationale", required=True)
    record_parser.add_argument("--category")
    record_parser.add_argument("--add", dest="adds", action="append", default=[])
    record_parser.add_argument("--retire", dest="retires", action="append", default=[])
    record_parser.add_argument(
        "--reprioritize",
        dest="reprioritizes",
        action="append",
        default=[],
    )
    record_parser.add_argument("--reject", dest="rejects", action="append", default=[])
    record_parser.set_defaults(handler=command_record)

    retire_parser = subparsers.add_parser("retire", help="Retire a frontier out of band")
    retire_parser.add_argument("frontier_id")
    retire_parser.add_argument("--category", required=True)
    retire_parser.add_argument("--reason", required=True)
    retire_parser.set_defaults(handler=command_retire)

    reactivate_parser = subparsers.add_parser("reactivate", help="Reactivate a Continued frontier")
    reactivate_parser.add_argument("frontier_id")
    reactivate_parser.set_defaults(handler=command_reactivate)

    status_parser = subparsers.add_parser("status", help="Print frontier status")
    status_parser.set_defaults(handler=command_status)

    return parser


def command_add(args: argparse.Namespace) -> int:
    if args.parent_frontier is not None and args.layer is None:
        raise LifecycleError("--parent requires --layer")
    workspace = workspace_path(args)
    registry, original_registry_bytes = read_registry_snapshot(workspace)
    updated = create_frontier_for_cli(
        registry,
        name=args.name,
        proposed_at_loop=args.at_loop,
        source=args.source,
        source_frontier=args.source_frontier,
        layer=args.layer,
        parent_frontier=args.parent_frontier,
    )
    added = updated["frontiers"][-1]
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_registry_bytes,
        updated_registry=updated,
    )
    print(f"Added {added['id']} ({added['status']}): {added['name']}")
    return 0


def command_set_layers(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry, original_bytes = read_registry_snapshot(workspace)
    previous = registry.get("layer_labels", [])
    updated = set_layer_labels(
        registry,
        parse_indexed_labels(args.labels),
        replace=args.replace,
    )
    changed = previous != updated["layer_labels"]
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_bytes,
        updated_registry=updated,
        allow_layer_insert=True,
    )
    print("Layer labels configured")
    if args.replace and changed:
        bound_ids = [
            row["frontier_id"]
            for row in derive_frontier_layer_coverage(updated)["lineage"]
            if row["layer"] is not None
        ]
        if bound_ids:
            print(
                "NOTICE: Review layer binding semantics for: "
                + ", ".join(bound_ids)
            )
    return 0


def command_bind_layer(args: argparse.Namespace) -> int:
    if args.parent_frontier is not None and args.layer is None:
        raise LifecycleError("--parent requires --layer")
    workspace = workspace_path(args)
    registry, original_bytes = read_registry_snapshot(workspace)
    updated = bind_frontier_layer(
        registry,
        args.frontier_id,
        layer=None if args.clear else args.layer,
        parent_frontier=None if args.clear else args.parent_frontier,
    )
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_bytes,
        updated_registry=updated,
    )
    if args.clear:
        print(f"Cleared layer binding for {args.frontier_id}")
    else:
        parent = args.parent_frontier or "none"
        print(
            f"Bound {args.frontier_id} layer={args.layer} "
            f"parent_frontier={parent}"
        )
    return 0


def command_start(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry, original_registry_bytes = read_registry_snapshot(workspace)
    loop_counts = read_loop_counts(workspace, registry)
    frontier = get_frontier(registry, args.frontier_id)
    at_loop = loop_counts.get(args.frontier_id) or frontier.get("proposed_at_loop")
    updated = transition(
        registry,
        args.frontier_id,
        "Active",
        loop_counts,
        mode=registry["mode"],
        action="start",
        at_loop=at_loop,
        ts=utc_now(),
    )
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_registry_bytes,
        updated_registry=updated,
    )
    print(f"{args.frontier_id} -> Active")
    return 0


def command_check_review(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry = read_registry(workspace)
    loop_counts = read_loop_counts(workspace, registry)
    due = check_review_due(registry, loop_counts)

    if due:
        for frontier_id in due:
            print(f"{frontier_id} reached loop {loop_counts.get(frontier_id, 0)}")
        result = 1
    else:
        print("No Frontier Review due")
        result = 0

    coverage = derive_frontier_layer_coverage(registry)
    for line in format_frontier_layer_advisories(
        coverage,
        prefix="[ADVISORY] ",
    ):
        print(line)
    return result


def command_record(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry, original_registry_bytes = read_registry_snapshot(workspace)
    loop_counts = read_loop_counts(workspace, registry)
    at_loop = loop_counts.get(args.frontier_id, 0)

    updated = transition(
        registry,
        args.frontier_id,
        args.decision,
        loop_counts,
        mode=registry["mode"],
        action="review",
        rationale=args.rationale,
        retire_category=args.category,
        at_loop=at_loop,
        ts=utc_now(),
    )
    updated, portfolio_actions = apply_portfolio_actions(
        args,
        updated,
        loop_counts,
        at_loop=at_loop,
    )
    reviewed = get_frontier(updated, args.frontier_id)
    reviewed["review_decisions"][-1]["portfolio_actions"] = portfolio_actions

    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_registry_bytes,
        updated_registry=updated,
        refresh_review_logs=True,
    )
    print(f"Recorded {args.frontier_id} -> {args.decision}")
    if updated["version"] == CURRENT_REGISTRY_VERSION:
        for action in portfolio_actions:
            if action["action"] == "add":
                print(f"Added {action['frontier']} (unbound)")
    return 0


def command_retire(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry, original_registry_bytes = read_registry_snapshot(workspace)
    loop_counts = read_loop_counts(workspace, registry)
    updated = transition(
        registry,
        args.frontier_id,
        "Retired",
        loop_counts,
        mode=registry["mode"],
        action="retire",
        rationale=args.reason,
        retire_category=args.category,
        at_loop=loop_counts.get(args.frontier_id, 0),
        ts=utc_now(),
    )
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_registry_bytes,
        updated_registry=updated,
    )
    print(f"{args.frontier_id} -> Retired ({args.category})")
    return 0


def command_reactivate(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry, original_registry_bytes = read_registry_snapshot(workspace)
    loop_counts = read_loop_counts(workspace, registry)
    updated = transition(
        registry,
        args.frontier_id,
        "Active",
        loop_counts,
        mode=registry["mode"],
        action="reactivate",
        at_loop=loop_counts.get(args.frontier_id, 0),
        ts=utc_now(),
    )
    persist_mutation(
        workspace=workspace,
        original_registry_bytes=original_registry_bytes,
        updated_registry=updated,
    )
    print(f"{args.frontier_id} -> Active")
    return 0


def command_status(args: argparse.Namespace) -> int:
    workspace = workspace_path(args)
    registry = read_registry(workspace)
    loop_counts = read_loop_counts(workspace, registry)

    for frontier in registry.get("frontiers", []):
        frontier_id = frontier.get("id")
        print(
            f"{frontier_id} status={frontier.get('status')} "
            f"derived_loops={loop_counts.get(frontier_id, 0)} "
            f"review_count={frontier.get('review_count', 0)} "
            f"name={frontier.get('name')}"
        )
        if registry["version"] == CURRENT_REGISTRY_VERSION:
            layer = frontier["layer"]
            layer_text = "unbound" if layer is None else str(layer)
            label = "none" if layer is None else registry["layer_labels"][layer]
            parent = frontier["parent_frontier"]
            parent_frontier = "none" if parent is None else parent
            source = frontier.get("source_frontier")
            source_frontier = "none" if source is None else source
            print(
                f"  layer={layer_text} label={label} "
                f"parent_frontier={parent_frontier} "
                f"source_frontier={source_frontier}"
            )
    if registry["version"] == CURRENT_REGISTRY_VERSION:
        print(
            html.unescape(render_frontier_layer_coverage_md(registry)).rstrip("\n")
        )
    else:
        coverage = derive_frontier_layer_coverage(registry)
        for line in format_frontier_layer_advisories(
            coverage,
            prefix="[ADVISORY] ",
        ):
            print(line)
    return 0


def create_frontier_for_cli(
    registry: dict[str, Any],
    *,
    name: str,
    proposed_at_loop: int,
    source: str,
    source_frontier: str | None,
    layer: int | None = None,
    parent_frontier: str | None = None,
) -> dict[str, Any]:
    if source == "user":
        if source_frontier is not None:
            raise LifecycleError("user frontiers cannot set source_frontier")
        updated = create_frontier(
            registry,
            name=name,
            proposed_at_loop=proposed_at_loop,
            source="initial",
            layer=layer,
            parent_frontier=parent_frontier,
            initial_status="New",
            ts=utc_now(),
        )
        updated["frontiers"][-1]["source"] = "user"
        validate_registry(updated)
        return updated

    return create_frontier(
        registry,
        name=name,
        proposed_at_loop=proposed_at_loop,
        source=source,
        source_frontier=source_frontier,
        layer=layer,
        parent_frontier=parent_frontier,
        initial_status="New",
        ts=utc_now(),
    )


def apply_portfolio_actions(
    args: argparse.Namespace,
    registry: dict[str, Any],
    loop_counts: dict[str, int],
    *,
    at_loop: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = registry
    add_actions: list[dict[str, Any]] = []
    retire_actions: list[dict[str, Any]] = []
    reprioritize_actions: list[dict[str, Any]] = []
    reject_actions: list[dict[str, Any]] = []

    for raw in args.retires:
        frontier_id, category, reason = parse_retire_action(raw)
        if frontier_id == args.frontier_id:
            raise ValueError("portfolio --retire cannot target the reviewed frontier; use --decision Retired")
        due_action = frontier_id in check_review_due(updated, loop_counts)
        updated = transition(
            updated,
            frontier_id,
            "Retired",
            loop_counts,
            mode=updated["mode"],
            action="review" if due_action else "retire",
            rationale=reason,
            retire_category=category,
            at_loop=loop_counts.get(frontier_id, at_loop),
            ts=utc_now(),
        )
        retire_actions.append(
            {
                "action": "retire",
                "frontier": frontier_id,
                "category": category,
                "reason": reason,
            }
        )

    for raw in args.adds:
        name, source, source_frontier, reason = parse_add_action(raw)
        updated = create_frontier_for_cli(
            updated,
            name=name,
            proposed_at_loop=at_loop or 1,
            source=source,
            source_frontier=source_frontier,
        )
        created = updated["frontiers"][-1]
        add_actions.append(
            {
                "action": "add",
                "frontier": created["id"],
                "source": source,
                "source_frontier": source_frontier,
                "reason": reason,
            }
        )

    for raw in args.reprioritizes:
        frontier_id, priority, reason = parse_reprioritize_action(raw)
        get_frontier(updated, frontier_id)
        reprioritize_actions.append(
            {
                "action": "reprioritize",
                "frontier": frontier_id,
                "priority": priority,
                "reason": reason,
            }
        )

    for raw in args.rejects:
        candidate, reason = parse_reject_action(raw)
        reject_actions.append({"action": "reject", "candidate": candidate, "reason": reason})

    return updated, add_actions + retire_actions + reprioritize_actions + reject_actions


def parse_add_action(raw: str) -> tuple[str, str, str | None, str]:
    name, source, source_frontier, reason = parse_exact_parts(
        raw,
        4,
        "--add requires NAME::source::source_frontier::reason",
        allow_empty_indexes={2},
    )
    return name, source, source_frontier or None, reason


def parse_retire_action(raw: str) -> tuple[str, str, str]:
    frontier_id, category, reason = parse_exact_parts(
        raw,
        3,
        "--retire requires F{id}::category::reason",
    )
    return frontier_id, category, reason


def parse_reprioritize_action(raw: str) -> tuple[str, str, str]:
    frontier_id, priority, reason = parse_exact_parts(
        raw,
        3,
        "--reprioritize requires F{id}::priority::reason",
    )
    return frontier_id, priority, reason


def parse_reject_action(raw: str) -> tuple[str, str]:
    candidate, reason = parse_exact_parts(raw, 2, "--reject requires candidate::reason")
    return candidate, reason


def parse_exact_parts(
    raw: str,
    expected_count: int,
    message: str,
    *,
    allow_empty_indexes: set[int] | None = None,
) -> list[str]:
    allowed_empty = allow_empty_indexes or set()
    parts = [part.strip() for part in raw.split("::")]
    if len(parts) != expected_count:
        raise ValueError(message)
    if any(part == "" and index not in allowed_empty for index, part in enumerate(parts)):
        raise ValueError(message)
    return parts


def render_workflow(
    workflow_text: str,
    registry: dict[str, Any],
    *,
    refresh_review_logs: bool = False,
    allow_layer_insert: bool = False,
) -> str:
    if refresh_review_logs:
        rendered_review = render_review_log_md(registry)
        rendered_discovery = render_discovery_log_md(registry)
        replace_managed_block(workflow_text, REVIEW_BLOCK, rendered_review)
        replace_managed_block(workflow_text, DISCOVERY_BLOCK, rendered_discovery)

    if registry["version"] == CURRENT_REGISTRY_VERSION:
        rendered_layer = render_frontier_layer_coverage_md(registry)
        if allow_layer_insert:
            upsert_managed_block_after(
                workflow_text,
                LAYER_BLOCK,
                rendered_layer,
                after_block_name=DISCOVERY_BLOCK,
            )
        else:
            replace_managed_block_after(
                workflow_text,
                LAYER_BLOCK,
                rendered_layer,
                after_block_name=DISCOVERY_BLOCK,
            )

    updated = workflow_text
    if refresh_review_logs:
        updated = replace_managed_block(
            updated,
            REVIEW_BLOCK,
            rendered_review,
        )
        updated = replace_managed_block(
            updated,
            DISCOVERY_BLOCK,
            rendered_discovery,
        )
    if registry["version"] == CURRENT_REGISTRY_VERSION:
        if allow_layer_insert:
            updated = upsert_managed_block_after(
                updated,
                LAYER_BLOCK,
                rendered_layer,
                after_block_name=DISCOVERY_BLOCK,
            )
        else:
            updated = replace_managed_block_after(
                updated,
                LAYER_BLOCK,
                rendered_layer,
                after_block_name=DISCOVERY_BLOCK,
            )
    return updated


def read_loop_counts(workspace: Path, registry: dict[str, Any]) -> dict[str, int]:
    ledger_text = read_required_text(workspace / LEDGER_FILE)
    if "## Loop " not in ledger_text:
        return {frontier.get("id"): 0 for frontier in registry.get("frontiers", [])}

    counts = derive_loop_counts(ledger_text, registry)
    for frontier in registry.get("frontiers", []):
        counts.setdefault(frontier.get("id"), 0)
    return counts


def read_registry_snapshot(workspace: Path) -> tuple[dict[str, Any], bytes]:
    original, text = read_required_utf8(workspace / REGISTRY_FILE)
    registry = json.loads(text)
    validate_registry(registry)
    return registry, original


def read_registry(workspace: Path) -> dict[str, Any]:
    registry, _ = read_registry_snapshot(workspace)
    return registry


def registry_to_text(registry: dict[str, Any]) -> str:
    return json.dumps(registry, indent=2, ensure_ascii=False) + "\n"


def persist_registry_and_workflow(
    *,
    registry_path: Path,
    workflow_path: Path,
    original_registry_bytes: bytes,
    rendered_registry: str,
    rendered_workflow: str,
) -> None:
    write_text(registry_path, rendered_registry)
    try:
        write_text(workflow_path, rendered_workflow)
    except (OSError, UnicodeError) as primary:
        try:
            write_bytes(registry_path, original_registry_bytes)
        except (OSError, UnicodeError) as rollback:
            raise PersistenceRollbackError(
                f"workflow write failed: {primary}; "
                f"registry rollback failed: {rollback}"
            ) from rollback
        raise


def persist_mutation(
    *,
    workspace: Path,
    original_registry_bytes: bytes,
    updated_registry: dict[str, Any],
    refresh_review_logs: bool = False,
    allow_layer_insert: bool = False,
) -> None:
    validate_registry(updated_registry)
    rendered_registry = registry_to_text(updated_registry)
    needs_workflow = (
        updated_registry["version"] == CURRENT_REGISTRY_VERSION
        or refresh_review_logs
    )
    if not needs_workflow:
        write_text(workspace / REGISTRY_FILE, rendered_registry)
        return

    original_workflow_bytes, workflow_text = read_required_utf8(
        workspace / WORKFLOW_FILE
    )
    rendered_workflow = render_workflow(
        workflow_text,
        updated_registry,
        refresh_review_logs=refresh_review_logs,
        allow_layer_insert=allow_layer_insert,
    )
    _ = original_workflow_bytes
    persist_registry_and_workflow(
        registry_path=workspace / REGISTRY_FILE,
        workflow_path=workspace / WORKFLOW_FILE,
        original_registry_bytes=original_registry_bytes,
        rendered_registry=rendered_registry,
        rendered_workflow=rendered_workflow,
    )


def read_required_utf8(path: Path) -> tuple[bytes, str]:
    original = Path(path).read_bytes()
    try:
        decoded = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LifecycleError(f"{Path(path).name} must be valid UTF-8") from exc
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return original, normalized


def read_required_text(path: Path) -> str:
    _, text = read_required_utf8(path)
    return text


def replace_with_retry(
    src: Path,
    dst: Path,
    *,
    retries: int = 3,
    delay: float = 0.05,
    is_windows: bool | None = None,
) -> None:
    """Atomically replace ``dst`` with ``src``, tolerating Windows file locks.

    On Windows, ``os.replace`` raises ``PermissionError`` when the destination
    is held open by another process (OneDrive sync, antivirus, an editor).
    This helper retries transient ``PermissionError`` a bounded number of times
    on Windows only. On POSIX it is a single attempt — identical to a bare
    ``os.replace`` — so behavior there is unchanged.

    Like ``os.replace`` itself, this does not clean up ``src`` on failure; the
    caller (``write_atomic``) owns temp-file cleanup. ``delay`` grows slightly
    between attempts (linear backoff) to give the lock holder time to release.
    """
    if is_windows is None:
        is_windows = sys.platform == "win32"

    attempts = retries + 1 if is_windows else 1
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if not is_windows or attempt == attempts - 1:
                raise
            # Brief backoff before retrying on Windows.
            import time

            time.sleep(delay * (attempt + 1))


def write_atomic(path: Path, payload: str | bytes) -> None:
    path = Path(path)
    binary = isinstance(payload, bytes)
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8"}
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode,
            dir=path.parent,
            delete=False,
            **kwargs,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temp_path, path)
    except Exception:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        raise


def write_text(path: Path, text: str) -> None:
    write_atomic(path, text)


def write_bytes(path: Path, data: bytes) -> None:
    write_atomic(path, data)


def workspace_path(args: argparse.Namespace) -> Path:
    return Path(args.workspace)


def normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    if argv[0] in COMMANDS or argv[0].startswith("-"):
        return argv
    return ["--workspace", argv[0], *argv[1:]]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _layer_index(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "layer index must be an integer from 0 through 5"
        ) from exc
    if parsed < 0 or parsed > 5:
        raise argparse.ArgumentTypeError(
            "layer index must be an integer from 0 through 5"
        )
    return parsed


def parse_indexed_labels(raw_labels: list[list[str]]) -> list[tuple[int, str]]:
    indexed: list[tuple[int, str]] = []
    for raw_index, label in raw_labels:
        try:
            index = _layer_index(raw_index)
        except argparse.ArgumentTypeError as exc:
            raise LifecycleError(str(exc)) from exc
        indexed.append((index, label))
    return indexed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so output containing non-ASCII (e.g.
    # user-supplied frontier names) prints consistently on every platform.
    # Without this, Windows pipes default to cp1252 and the subprocess crashes
    # with UnicodeEncodeError mid-output (exit 1).
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
