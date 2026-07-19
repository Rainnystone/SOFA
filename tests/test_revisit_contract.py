import copy
import dataclasses
import errno
import hashlib
import inspect
import io
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import scripts.revisit_contract as revisit_contract
import scripts.revisit_contract.context as revisit_context
import scripts.revisit_contract.generation as revisit_generation
import scripts.revisit_contract.model as revisit_model
import scripts.revisit_contract.store as revisit_store
import scripts.revisit_cycle as revisit_cycle_cli
import scripts.sofa_contract.evaluate as sofa_evaluate
import scripts.sofa_contract.revisit_readiness as revisit_readiness
import scripts.timeliness_checker as timeliness_checker
from scripts.frontier_lifecycle import (
    bind_frontier_layer,
    create_frontier,
    make_registry,
    set_layer_labels,
    transition,
    validate_registry,
)
from scripts.framing_contract import evaluate_contract, load_contract
from scripts.capability_policy.search_records import build_prior_query_digest
from scripts.sofa_contract import (
    RevisitCheckEffect,
    check_revisit_readiness,
)
from scripts.source_cache import (
    EXCERPT_MAX_CHARS,
    add_source,
    evaluate_index,
    excerpt_sha256,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REVISIT_CYCLE_SCRIPT = REPO_ROOT / "scripts" / "revisit_cycle.py"


def _can_create_symlink() -> bool:
    """Probe whether the host can actually create a symbolic link.

    ``hasattr(os, "symlink")`` is True on Windows but creating a link still
    requires Developer Mode or administrator privileges, so the attribute test
    alone lets symlink-based tests run and fail with ``OSError`` on unprivileged
    Windows. This probe attempts a real throwaway link and returns False on any
    ``OSError`` so ``skipUnless`` gates skip those tests honestly.
    """
    if not hasattr(os, "symlink"):
        return False
    directory = tempfile.mkdtemp()
    try:
        target = os.path.join(directory, "target.txt")
        link = os.path.join(directory, "link.txt")
        open(target, "w", encoding="utf-8").close()
        try:
            os.symlink(target, link)
        except OSError:
            return False
        return True
    finally:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)


CAN_SYMLINK = _can_create_symlink()

TASK9_FIXTURE_PATHS = (
    "state.json",
    "research_workflow.md",
    "evidence_ledger.md",
    "claim_ledger.md",
    "search_log.jsonl",
    "dispatch_log.jsonl",
    "frontier_registry.json",
    "framing_contract.json",
    "sources_index.jsonl",
    "sources/src-001.md",
    "sources/src-002.md",
    "scouts/loop7_customer_qualification.md",
    "scouts/loop8_customer_qualification.md",
    "scouts/loop9_customer_qualification.md",
    "challenges/loop7_challenge.md",
    "challenges/loop8_challenge.md",
    "challenges/loop9_challenge.md",
    "financials/AXTI_bridge.md",
    "redteam/round1_redteam.md",
    "redteam/round1_defense.md",
    "redteam/thesis_revision.md",
    "reports/AXTI_SOFA_Report_2026-07-01.md",
)


def complete_ticker_report_bytes() -> bytes:
    return (
        "\n".join(
            [
                "# Final Report",
                "Conclusion: research status is Watch with Trigger.",
                "Confidence: medium.",
                "Time horizon: 12 months.",
                "Top supporting evidence: evidence_ledger.md#loop-1.",
                "Strongest counter evidence: customer qualification risk.",
                "Evidence map: evidence_ledger.md.",
                "Financial bridge: revenue bridge is constrained by qualification timing.",
                "Catalyst clock: next filing and customer update.",
                "Red-team results: unresolved substitution risk.",
                "Invalidation triggers: lost customer qualification.",
                "Watch protocol: monitor customer updates.",
                "UTF-8 proof: 中文证据保持原字节。",
            ]
        )
        + "\n"
    ).encode("utf-8")


def complete_revisit_report_bytes(cycle: dict) -> bytes:
    return (
        complete_ticker_report_bytes()
        + revisit_contract.render_report_metadata(cycle).encode("utf-8")
        + (
            "\n## Trigger Delta\nObserved trigger validated.\n"
            "## Claim Delta\nSelected claim confirmed.\n"
            "## Evidence Freshness Delta\nCurrent evidence checked.\n"
            "## Frontier Delta\nThree new loops reviewed.\n"
            "## Financial/Red-Team Delta\nNo mechanical rerun required.\n"
            "## Unresolved or Blocked Gaps\nNone.\n"
        ).encode("utf-8")
    )


def make_registration_workspace(root: Path, *, mode: str = "ticker") -> tuple[Path, Path]:
    workspace = root / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)
    (workspace / "state.json").write_text(
        json.dumps(
            {
                "subject": "TEST",
                "mode": mode,
                "current_stage": "stage_5",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = reports / "final.md"
    report.write_bytes(complete_ticker_report_bytes())
    return workspace, report


def write_valid_revisit_request(root: Path, workspace: Path) -> Path:
    claim_ledger = workspace / "claim_ledger.md"
    claim_ledger.write_bytes(
        b"# Claim Ledger\n\n## Claim C1\nCustomer qualification timing.\n"
    )
    request = {
        "triggers": [
            {
                "kind": "downgrade",
                "statement": (
                    "The named qualification milestone moved beyond the prior "
                    "watch window."
                ),
                "observed_at": "2026-07-14T10:00:00Z",
                "evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T10:00:00Z",
                    }
                ],
            }
        ],
        "selected_claims": [
            {
                "statement": (
                    "Customer qualification completes inside the prior watch window."
                ),
                "source_ref": {
                    "path": "claim_ledger.md",
                    "sha256": hashlib.sha256(claim_ledger.read_bytes()).hexdigest(),
                    "locator": "Claim C1",
                    "historical_claim_id": "C1",
                },
                "importance": "critical",
                "selection_reasons": [
                    "trigger_affected",
                    "decision_load_bearing",
                ],
                "trigger_indexes": [1],
                "inherited_grade": "B",
                "inherited_confidence": "medium",
                "inherited_evidence": [
                    {
                        "ref": {
                            "kind": "source",
                            "source_id": "src-001",
                            "checked_at": "2026-07-14T10:00:00Z",
                        },
                        "freshness": "unknown",
                        "checked_at": "2026-07-14T10:00:00Z",
                        "reason": "The old source predates the fired trigger.",
                    }
                ],
            }
        ],
    }
    request_path = root / "revisit-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return request_path


def make_revisit_start_workspace(root: Path) -> tuple[Path, Path]:
    workspace, report = make_registration_workspace(root)
    report_payload = report.read_bytes()
    pointer = revisit_contract.empty_pointer()
    pointer["current_revision"] = {
        "revision_id": "REV-0001",
        "cycle_id": None,
        "report_path": "reports/final.md",
        "report_sha256": hashlib.sha256(report_payload).hexdigest(),
        "action_class": "Watch with Trigger",
        "validated_at": "2026-07-14T09:00:00Z",
        "revision_of": None,
    }
    (workspace / revisit_contract.POINTER_FILENAME).write_bytes(
        revisit_contract.canonical_document_bytes(pointer)
    )
    (workspace / revisit_contract.CYCLES_DIRNAME).mkdir()

    framing = {
        "schema_version": "1.0",
        "subject_resolution": {
            "confirmed_name": "Test Issuer",
            "tickers": ["TEST"],
            "exchange": "NASDAQ",
            "resolution_method": "deterministic_quote",
            "candidates": [],
        },
        "mode": "ticker",
        "research_posture": "revisit",
        "time_horizon": "6-12 months",
        "market_scope": "US public market",
        "risk_appetite": "moderate",
        "output_expectation": "decision memo",
        "report_language": "en",
        "budget_appetite": "standard",
        "clarifications": [],
    }
    (workspace / "framing_contract.json").write_text(
        json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    registry = create_frontier(
        make_registry("Test Issuer", "ticker"),
        name="Qualification timing",
        proposed_at_loop=1,
        source="initial",
        initial_status="Active",
        ts="2026-07-01T00:00:00Z",
    )
    (workspace / "frontier_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace / "evidence_ledger.md").write_text(
        "\n".join(
            [
                "# Evidence Ledger",
                "",
                "## Loop 2: F1 - Qualification timing",
                "",
                "Prior evidence.",
                "",
                "## Loop 7: F1 - Qualification timing",
                "",
                "Later evidence.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    source_excerpt = "Archived source excerpt for the qualification milestone.\n"
    source_path = workspace / "sources" / "src-001.md"
    source_path.parent.mkdir()
    source_path.write_bytes(source_excerpt.encode("utf-8"))
    source_record = {
        "source_id": "src-001",
        "url": "https://example.test/qualification",
        "title": "Qualification milestone source",
        "retrieved": "2026-07-14",
        "grade": "B",
        "excerpt_path": "sources/src-001.md",
        "sha256": hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest(),
    }
    (workspace / "sources_index.jsonl").write_bytes(
        (json.dumps(source_record, ensure_ascii=False) + "\n").encode("utf-8")
    )
    return workspace, write_valid_revisit_request(root, workspace)


def make_task5_mutation_workspace(root: Path) -> tuple[Path, str]:
    workspace, request_path = make_revisit_start_workspace(root)
    start = run_revisit_cycle_cli(
        workspace,
        "start",
        "--intake-file",
        str(request_path),
    )
    if start.returncode != 0:
        raise AssertionError(start.stderr)

    excerpt = "Current source excerpt for the revised qualification window.\n"
    excerpt_path = workspace / "sources" / "src-002.md"
    excerpt_path.write_bytes(excerpt.encode("utf-8"))
    source_record = {
        "source_id": "src-002",
        "url": "https://example.test/revised-qualification",
        "title": "Revised qualification source",
        "retrieved": "2026-07-14",
        "grade": "B",
        "excerpt_path": "sources/src-002.md",
        "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }
    with (workspace / "sources_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(source_record, ensure_ascii=False) + "\n")

    delivery_path = workspace / "scouts" / "loop_10_scout.md"
    delivery_path.parent.mkdir()
    delivery_path.write_text("# Delivered Scout\n", encoding="utf-8")
    dispatch = {
        "dispatch_id": "dispatch_0010_scout",
        "loop_id": "loop_10",
        "role": "scout",
        "mechanism": "host_subagent",
        "delivery_path": "scouts/loop_10_scout.md",
        "status": "delivered",
    }
    (workspace / "dispatch_log.jsonl").write_text(
        json.dumps(dispatch, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return workspace, "RC-0001"


def make_task6_binding_workspace(root: Path) -> tuple[Path, str]:
    workspace, request_path = make_revisit_start_workspace(root)
    (workspace / "evidence_ledger.md").write_text(
        "\n".join(
            [
                "# Evidence Ledger",
                "",
                "## Loop 2: F1 - Qualification timing",
                "",
                "Prior evidence.",
                "",
                "## Loop 5: F1 - Qualification timing",
                "",
                "Prior challenge.",
                "",
                "## Loop 7: F1 - Qualification timing",
                "",
                "Prior review evidence.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        mock.patch.object(
            revisit_cycle_cli,
            "_utc_now_seconds",
            return_value="2026-07-14T10:00:00Z",
        ),
        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
    ):
        start = revisit_cycle_cli.main(
            [
                str(workspace),
                "start",
                "--intake-file",
                str(request_path),
            ]
        )
    if start != 0:
        raise AssertionError(stderr.getvalue())

    registry_path = workspace / "frontier_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = transition(
        registry,
        "F1",
        "Continued",
        {"F1": 3},
        mode="ticker",
        action="review",
        rationale="The historical frontier remains decision-relevant.",
        at_loop=7,
        ts="2026-07-14T10:30:00Z",
    )
    registry = transition(
        registry,
        "F1",
        "Active",
        {"F1": 3},
        mode="ticker",
        action="reactivate",
        at_loop=8,
        ts="2026-07-14T11:00:00Z",
    )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return workspace, "RC-0001"


def make_task7_context_workspace(root: Path) -> tuple[Path, str, str]:
    workspace, cycle_id = make_task6_binding_workspace(root)
    frontier_id = add_task6_frontier(workspace)

    registry_path = workspace / "frontier_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = set_layer_labels(
        registry,
        [(index, f"Layer {index}") for index in range(6)],
    )
    registry = bind_frontier_layer(registry, "F1", layer=0)
    registry = bind_frontier_layer(
        registry,
        frontier_id,
        layer=1,
        parent_frontier="F1",
    )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    bind_task6_frontier(
        workspace,
        cycle_id,
        frontier_id=frontier_id,
        action="added",
    )

    with (workspace / "evidence_ledger.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "## Loop 8: F2 - New qualification branch\n\n"
            "Target-frontier evidence.\n\n"
            "## Loop 9: F1 - Historical qualification timing\n\n"
            "Unrelated-frontier evidence.\n\n"
        )
    search_records = (
        {
            "loop_id": "loop_8",
            "query": "F2 current qualification milestone evidence",
            "result_status": "completed",
            "dead_ends": [
                {
                    "query": "F2 obsolete qualification rumor",
                    "category": "stale",
                }
            ],
            "evidence_refs": [
                "https://target-frontier.example/qualification",
                "src-001",
            ],
        },
        {
            "loop_id": "loop_9",
            "query": "F1 unrelated legacy qualification search",
            "result_status": "completed",
            "dead_ends": [
                {
                    "query": "F1 unrelated dead end",
                    "category": "irrelevant",
                }
            ],
            "evidence_refs": [
                "https://unrelated-frontier.example/legacy",
                "src-002",
            ],
        },
    )
    (workspace / "search_log.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in search_records),
        encoding="utf-8",
    )

    unrelated_excerpt = "Unrelated source excerpt that must never be rendered.\n"
    unrelated_path = workspace / "sources" / "src-002.md"
    unrelated_path.write_text(unrelated_excerpt, encoding="utf-8")
    unrelated_record = {
        "source_id": "src-002",
        "url": "https://unrelated-source.example/item",
        "title": "Unrelated source",
        "retrieved": "2026-07-14",
        "grade": "C",
        "excerpt_path": "sources/src-002.md",
        "sha256": hashlib.sha256(unrelated_excerpt.encode("utf-8")).hexdigest(),
    }
    with (workspace / "sources_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(unrelated_record) + "\n")

    scout_output = workspace / "scouts" / "loop_8_scout.md"
    scout_output.parent.mkdir(exist_ok=True)
    scout_output.write_text(
        "LEAKED_SCOUT_OUTPUT must never enter revisit context.\n",
        encoding="utf-8",
    )
    return workspace, cycle_id, frontier_id


def add_task6_frontier(
    workspace: Path,
    *,
    proposed_at_loop: int = 8,
    initial_status: str = "New",
    ts: str = "2026-07-14T10:30:00Z",
    retire: bool = False,
) -> str:
    registry_path = workspace / "frontier_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = create_frontier(
        registry,
        name="New cycle-relative qualification branch",
        proposed_at_loop=proposed_at_loop,
        source="discovery",
        source_frontier="F1",
        initial_status=initial_status,
        ts=ts,
    )
    frontier_id = registry["frontiers"][-1]["id"]
    if retire:
        registry = transition(
            registry,
            frontier_id,
            "Retired",
            {frontier_id: 0},
            mode="ticker",
            action="retire",
            rationale="The branch was invalidated before research started.",
            retire_category="invalidated",
            at_loop=proposed_at_loop,
            ts="2026-07-14T10:45:00Z",
        )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return frontier_id


def bind_task6_frontier(
    workspace: Path,
    cycle_id: str,
    *,
    frontier_id: str,
    action: str,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        mock.patch.object(
            revisit_cycle_cli,
            "_utc_now_seconds",
            return_value="2026-07-14T11:30:00Z",
        ),
        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
    ):
        result = revisit_cycle_cli.main(
            [
                str(workspace),
                "bind-frontier",
                cycle_id,
                "--frontier",
                frontier_id,
                "--action",
                action,
                "--claim",
                f"{cycle_id}-CL-01",
                "--expected-evidence",
                "Current qualification timing and counter-evidence.",
            ]
        )
    if result != 0:
        raise AssertionError(stderr.getvalue())


def bind_task6_reactivated_frontier(workspace: Path, cycle_id: str) -> None:
    bind_task6_frontier(
        workspace,
        cycle_id,
        frontier_id="F1",
        action="reactivated",
    )


def append_task6_loops(
    workspace: Path,
    count: int,
    *,
    frontier_id: str = "F1",
) -> tuple[str, ...]:
    loop_ids = tuple(f"loop_{number}" for number in range(8, 8 + count))
    with (workspace / "evidence_ledger.md").open("a", encoding="utf-8") as handle:
        for number in range(8, 8 + count):
            handle.write(
                f"## Loop {number}: {frontier_id} - Qualification timing\n\n"
                f"Cycle-relative evidence for loop {number}.\n\n"
            )
    return loop_ids


def write_task6_search_and_dispatch(
    workspace: Path,
    loop_ids: tuple[str, ...],
) -> None:
    (workspace / "research_workflow.md").write_text(
        "# Research Workflow\n",
        encoding="utf-8",
    )
    search_records = [
        {
            "loop_id": loop_id,
            "query": f"{loop_id} qualification evidence and counter-evidence",
            "result_status": "completed",
        }
        for loop_id in loop_ids
    ]
    (workspace / "search_log.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in search_records),
        encoding="utf-8",
    )
    dispatch_records = []
    for loop_id in loop_ids:
        for role, directory, suffix in (
            ("frontier_scout", "scouts", "scout"),
            ("challenge_probe", "challenges", "challenge"),
        ):
            delivery_path = f"{directory}/{loop_id}_{suffix}.md"
            absolute = workspace / delivery_path
            absolute.parent.mkdir(exist_ok=True)
            delivery_lines = [
                f"# {role}",
                "",
                "Method cards loaded: "
                + (
                    "supply-chain-mapping, customer-graph-discovery."
                    if role == "frontier_scout"
                    else "red-team, supply-chain-mapping, "
                    "customer-graph-discovery."
                ),
                "",
            ]
            delivery_lines.extend(
                [
                    "Sources consulted: accepted source trace for "
                    f"{loop_id}.",
                    "",
                ]
            )
            delivery_lines.append(
                f"Cycle-relative delivery for {loop_id}."
            )
            absolute.write_text(
                "\n".join(delivery_lines) + "\n",
                encoding="utf-8",
            )
            dispatch_records.append(
                {
                    "dispatch_id": f"dispatch_{loop_id}_{suffix}",
                    "loop_id": loop_id,
                    "role": role,
                    "mechanism": "host_subagent",
                    "delivery_path": delivery_path,
                    "status": "delivered",
                }
            )
    (workspace / "dispatch_log.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in dispatch_records),
        encoding="utf-8",
    )


def review_task6_frontier(
    workspace: Path,
    *,
    decision: str = "Continued",
    frontier_id: str = "F1",
    loop_count: int = 6,
) -> None:
    registry_path = workspace / "frontier_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = transition(
        registry,
        frontier_id,
        decision,
        {frontier_id: loop_count},
        mode="ticker",
        action="review",
        rationale="Three new loops completed the cycle-relative review.",
        retire_category="answered_out" if decision == "Retired" else None,
        at_loop=10,
        ts="2026-07-14T12:00:00Z",
    )
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def derive_task6_floor_issues(workspace: Path, cycle_id: str):
    dispatch_result = sofa_evaluate.ContractResult()
    dispatch_records = sofa_evaluate._read_dispatch_records(
        workspace,
        dispatch_result,
    )
    return sofa_evaluate._derive_revisit_frontier_floor_issues(
        workspace,
        revisit_contract.load_cycle(workspace, cycle_id),
        json.loads(
            (workspace / "frontier_registry.json").read_text(encoding="utf-8")
        ),
        (workspace / "evidence_ledger.md").read_text(encoding="utf-8"),
        dispatch_records or [],
    )


def make_task6_ready_workspace(
    root: Path,
    *,
    current_ref: dict | None = None,
) -> tuple[Path, str]:
    workspace, cycle_id = make_task6_binding_workspace(root)
    bind_task6_reactivated_frontier(workspace, cycle_id)
    loop_ids = append_task6_loops(workspace, 3)
    write_task6_search_and_dispatch(workspace, loop_ids)
    review_task6_frontier(workspace)

    _finish_task6_ready_claim(
        root,
        workspace,
        cycle_id,
        frontier_id="F1",
        current_ref=current_ref,
    )
    return workspace, cycle_id


TASK9_PRIOR_QUERY = "AXTI exact historical qualification query"
TASK9_PRIOR_DEAD_END_QUERY = "AXTI exact historical qualification dead end"


def make_task9_query_replay_workspace(
    root: Path,
    *,
    replay_kind: str,
    variation_fields: dict[str, object] | None = None,
    post_boundary_query: str | None = None,
) -> tuple[Path, str]:
    workspace, cycle_id = make_task6_ready_workspace(root)
    search_path = workspace / "search_log.jsonl"
    records = [
        json.loads(line)
        for line in search_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records.insert(
        0,
        {
            "loop_id": "loop_7",
            "query": TASK9_PRIOR_QUERY,
            "result_status": "completed",
            "dead_ends": [
                {
                    "query": TASK9_PRIOR_DEAD_END_QUERY,
                    "category": "stale",
                }
            ],
            "evidence_refs": ["src-001"],
        },
    )
    post_boundary = next(record for record in records if record["loop_id"] == "loop_8")
    replay_queries = {
        "prior_query": TASK9_PRIOR_QUERY,
        "dead_end": TASK9_PRIOR_DEAD_END_QUERY,
        "novel": "AXTI genuinely novel post-trigger qualification query",
    }
    post_boundary["query"] = (
        post_boundary_query
        if post_boundary_query is not None
        else replay_queries[replay_kind]
    )
    if variation_fields is not None:
        post_boundary.update(variation_fields)
    search_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return workspace, cycle_id


def make_task8_pre_report_workspace(
    root: Path,
    change_class: str,
) -> tuple[Path, str]:
    workspace, cycle_id = make_task6_binding_workspace(root)
    bind_task6_reactivated_frontier(workspace, cycle_id)
    loop_ids = append_task6_loops(workspace, 3)
    write_task6_search_and_dispatch(workspace, loop_ids)
    review_task6_frontier(workspace)

    resolution = make_confirmed_resolution_request()
    resolution["bound_frontier_ids"] = ["F1"]
    resolution["current_evidence_refs"] = [
        {
            "kind": "source",
            "source_id": "src-001",
            "checked_at": "2026-07-14T12:00:00Z",
        }
    ]
    resolution_path = root / f"task8-{change_class}-resolution.json"
    resolution_path.write_text(
        json.dumps(resolution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    resolved = run_revisit_cycle_cli(
        workspace,
        "resolve-claim",
        cycle_id,
        f"{cycle_id}-CL-01",
        "--resolution-file",
        str(resolution_path),
    )
    if resolved.returncode != 0:
        raise AssertionError(resolved.stderr)

    assessment = make_decision_assessment_request()
    if change_class == "financial_or_risk_change":
        assessment["financial_bridge_affected"] = True
        assessment["financial_bridge_rationale"] = (
            "The accepted claim changes the affected financial transmission."
        )
    elif change_class == "action_class_change":
        assessment["new_action_class"] = "Reject"
        assessment["financial_bridge_affected"] = True
        assessment["financial_bridge_rationale"] = (
            "The new action class requires a full financial bridge."
        )
    assessment_path = root / f"task8-{change_class}-assessment.json"
    assessment_path.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assessed = run_revisit_cycle_cli(
        workspace,
        "assess-decision",
        cycle_id,
        "--assessment-file",
        str(assessment_path),
    )
    if assessed.returncode != 0:
        raise AssertionError(assessed.stderr)
    return workspace, cycle_id


def record_task8_rerun(
    workspace: Path,
    cycle_id: str,
    *,
    kind: str,
    path: str,
    scope: str | None = None,
    round_number: int | None = None,
    dispatch_role: str | None = None,
) -> None:
    artifact = workspace / path
    artifact.parent.mkdir(exist_ok=True)
    card = "financial-bridge" if kind == "bridge" else "red-team"
    artifact.write_text(
        f"# Cycle rerun {path}\n\nMethod cards loaded: {card}.\n",
        encoding="utf-8",
    )
    arguments = [
        "record-rerun",
        cycle_id,
        "--kind",
        kind,
        "--path",
        path,
    ]
    if scope is not None:
        arguments.extend(("--scope", scope))
    if round_number is not None:
        arguments.extend(("--round", str(round_number)))
    result = run_revisit_cycle_cli(workspace, *arguments)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    if dispatch_role is not None:
        dispatch_path = workspace / "dispatch_log.jsonl"
        record = {
            "dispatch_id": f"dispatch_{kind}_{round_number or 0}",
            "loop_id": "loop_10",
            "role": dispatch_role,
            "mechanism": "host_subagent",
            "delivery_path": path,
            "status": "delivered",
        }
        with dispatch_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def make_task6_added_ready_workspace(root: Path) -> tuple[Path, str, str]:
    workspace, cycle_id = make_task6_binding_workspace(root)
    frontier_id = add_task6_frontier(workspace, initial_status="Active")
    bind_task6_frontier(
        workspace,
        cycle_id,
        frontier_id=frontier_id,
        action="added",
    )
    loop_ids = append_task6_loops(
        workspace,
        3,
        frontier_id=frontier_id,
    )
    write_task6_search_and_dispatch(workspace, loop_ids)
    review_task6_frontier(
        workspace,
        frontier_id=frontier_id,
        loop_count=3,
    )
    _finish_task6_ready_claim(
        root,
        workspace,
        cycle_id,
        frontier_id=frontier_id,
    )
    return workspace, cycle_id, frontier_id


def _finish_task6_ready_claim(
    root: Path,
    workspace: Path,
    cycle_id: str,
    *,
    frontier_id: str,
    current_ref: dict | None = None,
) -> None:
    resolution = make_confirmed_resolution_request()
    resolution["bound_frontier_ids"] = [frontier_id]
    resolution["current_evidence_refs"] = [
        current_ref
        or {
            "kind": "source",
            "source_id": "src-001",
            "checked_at": "2026-07-14T12:00:00Z",
        }
    ]
    resolution_path = root / "task6-resolution.json"
    resolution_path.write_text(
        json.dumps(resolution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    resolved = run_revisit_cycle_cli(
        workspace,
        "resolve-claim",
        cycle_id,
        f"{cycle_id}-CL-01",
        "--resolution-file",
        str(resolution_path),
    )
    if resolved.returncode != 0:
        raise AssertionError(resolved.stderr)

    assessment_path = root / "task6-assessment.json"
    assessment_path.write_text(
        json.dumps(
            make_decision_assessment_request(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assessed = run_revisit_cycle_cli(
        workspace,
        "assess-decision",
        cycle_id,
        "--assessment-file",
        str(assessment_path),
    )
    if assessed.returncode != 0:
        raise AssertionError(assessed.stderr)


def move_task6_review_to_bound_at(
    workspace: Path,
    cycle_id: str,
    frontier_id: str,
) -> None:
    cycle = revisit_contract.load_cycle(workspace, cycle_id)
    binding = next(
        row
        for row in cycle["frontier_bindings"]
        if row["frontier_id"] == frontier_id
    )
    registry_path = workspace / "frontier_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    frontier = next(
        row for row in registry["frontiers"] if row["id"] == frontier_id
    )
    if frontier["lifecycle"][-1]["to"] != "Continued":
        raise AssertionError("Task 6 ready fixture must end with Continued")
    frontier["lifecycle"][-1]["ts"] = binding["bound_at"]
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_emergent_claim_request() -> dict:
    return {
        "origin": "emergent",
        "statement": (
            "The revised qualification window depends on a new packaging constraint."
        ),
        "derived_from": None,
        "accepted_from": {
            "loop_id": "loop_10",
            "dispatch_id": "dispatch_0010_scout",
            "evidence_refs": [
                {
                    "kind": "source",
                    "source_id": "src-002",
                    "checked_at": "2026-07-14T12:00:00Z",
                }
            ],
        },
        "acceptance_rationale": (
            "The main thread accepted the constraint after checking the cited source."
        ),
    }


def bind_selected_claim_for_task5(workspace: Path, cycle_id: str) -> None:
    cycle = revisit_contract.load_cycle(workspace, cycle_id)
    cycle["frontier_bindings"] = [
        {
            "frontier_id": "F1",
            "action": "reactivated",
            "claim_ids": [f"{cycle_id}-CL-01"],
            "expected_evidence": "Current qualification evidence",
            "baseline_loop_count": 2,
            "baseline_review_count": 1,
            "registry_sha256": cycle["intake"]["workspace_boundary"][
                "frontier_registry_sha256"
            ],
            "bound_at": "2026-07-14T11:00:00Z",
        }
    ]
    attach_valid_audit(cycle)
    revisit_contract.persist_cycle(
        workspace,
        cycle,
        expected_sha256=revisit_contract.sha256_file(
            workspace / "revisit_cycles" / f"{cycle_id}.json"
        ),
    )


def make_confirmed_resolution_request() -> dict:
    return {
        "status": "confirmed",
        "revised_statement": None,
        "current_evidence_refs": [
            {
                "kind": "source",
                "source_id": "src-002",
                "checked_at": "2026-07-14T12:00:00Z",
            }
        ],
        "counter_evidence_refs": [],
        "current_grade": "B",
        "current_confidence": "medium",
        "bound_frontier_ids": ["F1"],
        "rationale": "Current evidence directly supports the atomic proposition.",
        "missing_proof": None,
        "attempted_loop_ids": [],
        "attempted_search_refs": [],
        "verdict_impact": None,
        "split_child_ids": [],
    }


def make_blocked_resolution(claim_id: str, frontier_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "status": "blocked",
        "revised_statement": None,
        "current_evidence_refs": [],
        "counter_evidence_refs": [],
        "current_grade": None,
        "current_confidence": None,
        "bound_frontier_ids": [frontier_id],
        "rationale": "The required public proof remains unavailable.",
        "missing_proof": "A named customer acceptance filing.",
        "attempted_loop_ids": ["loop-001"],
        "attempted_search_refs": [
            {"loop_id": "loop-001", "query": "customer acceptance filing"}
        ],
        "verdict_impact": "The action class cannot be upgraded.",
        "split_child_ids": [],
    }


def make_bound_model_cycle() -> dict:
    cycle = make_minimal_cycle()
    cycle["frontier_bindings"] = [
        {
            "frontier_id": "F1",
            "action": "reactivated",
            "claim_ids": ["RC-0001-CL-01"],
            "expected_evidence": "Current qualification evidence",
            "baseline_loop_count": 2,
            "baseline_review_count": 1,
            "registry_sha256": "c" * 64,
            "bound_at": "2026-07-15T00:10:00Z",
        }
    ]
    attach_valid_audit(cycle)
    return cycle


def make_terminal_model_cycle(status: str) -> dict:
    cycle = make_bound_model_cycle()
    outcome = make_confirmed_resolution_request()
    if status == "refuted":
        outcome.update(
            {
                "status": "refuted",
                "current_evidence_refs": [],
                "counter_evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T12:00:00Z",
                    }
                ],
                "current_grade": None,
                "current_confidence": None,
                "rationale": "Current counter-evidence defeats the proposition.",
            }
        )
    elif status == "blocked":
        outcome = make_blocked_resolution("RC-0001-CL-01", "F1")
        outcome.pop("claim_id")
    proposed = revisit_contract.resolve_claim(
        cycle, "RC-0001-CL-01", outcome
    )
    return revisit_model.with_audit(
        cycle,
        proposed,
        "resolve-claim",
        ["RC-0001-CL-01"],
        "2026-07-15T00:20:00Z",
    )


def make_split_terminal_model_cycle() -> dict:
    cycle = make_bound_model_cycle()
    for number, statement in ((1, "Customer A qualifies."), (2, "Customer B qualifies.")):
        request = {
            "origin": "split_child",
            "statement": statement,
            "derived_from": "RC-0001-CL-01",
            "accepted_from": None,
            "acceptance_rationale": "The parent combined two customers.",
        }
        proposed = revisit_contract.add_derived_claim(cycle, request)
        cycle = revisit_model.with_audit(
            cycle,
            proposed,
            "add-derived-claim",
            [f"RC-0001-DC-{number:02d}"],
            f"2026-07-15T00:{20 + number:02d}:00Z",
        )
    cycle["frontier_bindings"].append(
        {
            "frontier_id": "F2",
            "action": "added",
            "claim_ids": ["RC-0001-DC-01", "RC-0001-DC-02"],
            "expected_evidence": "Atomic customer qualification evidence",
            "baseline_loop_count": 0,
            "baseline_review_count": 0,
            "registry_sha256": "c" * 64,
            "bound_at": "2026-07-15T00:23:00Z",
        }
    )
    attach_valid_audit(cycle)
    for number in (1, 2):
        outcome = make_confirmed_resolution_request()
        outcome["bound_frontier_ids"] = ["F2"]
        claim_id = f"RC-0001-DC-{number:02d}"
        proposed = revisit_contract.resolve_claim(cycle, claim_id, outcome)
        cycle = revisit_model.with_audit(
            cycle,
            proposed,
            "resolve-claim",
            [claim_id],
            f"2026-07-15T00:{23 + number:02d}:00Z",
        )
    split = make_confirmed_resolution_request()
    split.update(
        {
            "status": "split",
            "current_evidence_refs": [],
            "current_grade": None,
            "current_confidence": None,
            "bound_frontier_ids": [],
            "rationale": None,
            "split_child_ids": ["RC-0001-DC-01", "RC-0001-DC-02"],
        }
    )
    proposed = revisit_contract.resolve_claim(
        cycle, "RC-0001-CL-01", split
    )
    return revisit_model.with_audit(
        cycle,
        proposed,
        "resolve-claim",
        ["RC-0001-CL-01"],
        "2026-07-15T00:26:00Z",
    )


def make_decision_assessment_request() -> dict:
    return {
        "new_action_class": "Watch with Trigger",
        "financial_bridge_affected": False,
        "financial_bridge_rationale": (
            "No accepted claim changes the modeled revenue transmission."
        ),
        "risk_class_changed": False,
        "risk_class_rationale": (
            "The remaining gap is disclosed but does not change the selected risk class."
        ),
        "supporting_claim_ids": ["RC-0001-CL-01"],
        "verdict_rationale": (
            "The trigger changes timing evidence but not the current action class."
        ),
        "blocked_claim_ids": [],
    }


def make_assessment_workspace(root: Path, *, outcome: dict | None = None) -> tuple[Path, str]:
    workspace, cycle_id = make_task5_mutation_workspace(root)
    bind_selected_claim_for_task5(workspace, cycle_id)
    resolution = outcome or make_confirmed_resolution_request()
    resolution_path = root / "assessment-prerequisite-resolution.json"
    resolution_path.write_text(
        json.dumps(resolution, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = run_revisit_cycle_cli(
        workspace,
        "resolve-claim",
        cycle_id,
        f"{cycle_id}-CL-01",
        "--resolution-file",
        str(resolution_path),
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return workspace, cycle_id


def run_revisit_cycle_cli(workspace: Path, *arguments: str, env=None):
    return subprocess.run(
        [
            sys.executable,
            str(REVISIT_CYCLE_SCRIPT),
            str(workspace),
            *arguments,
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
    )


def evaluate_task8_report_candidate(workspace: Path, cycle_id: str):
    return sofa_evaluate._prepare_revisit_report_for_publication(
        workspace,
        cycle_id,
    ).result


def snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | None]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = ("directory", None)
        else:
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def make_initial_revision():
    return {
        "revision_id": "REV-0001",
        "cycle_id": None,
        "report_path": "reports/initial.md",
        "report_sha256": "a" * 64,
        "action_class": "Watch with Trigger",
        "validated_at": "2026-07-15T00:00:00Z",
        "revision_of": None,
    }


def make_revisit_revision():
    revision = make_initial_revision()
    revision.update(
        {
            "revision_id": "REV-0002",
            "cycle_id": "RC-0001",
            "revision_of": "REV-0001",
        }
    )
    return revision


def test_semantic_sha256(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_minimal_cycle(
    cycle_id="RC-0001", candidate_revision_id="REV-0002"
):
    timestamp = "2026-07-15T00:00:00Z"
    trigger_id = f"{cycle_id}-TRG-01"
    claim_id = f"{cycle_id}-CL-01"
    source_ref = {
        "kind": "source",
        "source_id": "src-001",
        "checked_at": timestamp,
    }
    intake = {
        "base_revision": {
            "revision_id": "REV-0001",
            "report_path": "reports/initial.md",
            "report_sha256": "a" * 64,
            "action_class": "Watch with Trigger",
        },
        "framing": {
            "path": "framing_contract.json",
            "sha256": "b" * 64,
            "snapshot": {
                "subject_resolution": {},
                "research_posture": "revisit",
                "time_horizon": "long_term",
                "market_scope": "global",
                "risk_appetite": "moderate",
                "output_expectation": "ticker_dive",
                "report_language": "en",
                "budget_appetite": "standard",
            },
        },
        "workspace_boundary": {
            "frontier_registry_sha256": "c" * 64,
            "max_existing_loop_number": 0,
        },
        "triggers": [
            {
                "trigger_id": trigger_id,
                "kind": "upgrade",
                "statement": "A named milestone changed.",
                "observed_at": "2026-07-15",
                "evidence_refs": [copy.deepcopy(source_ref)],
            }
        ],
        "selected_claims": [
            {
                "claim_id": claim_id,
                "statement": "The prior milestone remains decision-relevant.",
                "source_ref": {
                    "path": "reports/initial.md",
                    "sha256": "a" * 64,
                    "locator": "Claim 1",
                    "historical_claim_id": None,
                },
                "importance": "critical",
                "selection_reasons": ["trigger_affected"],
                "trigger_ids": [trigger_id],
                "inherited_grade": "A",
                "inherited_confidence": "high",
                "inherited_evidence": [],
            }
        ],
    }
    cycle = {
        "schema_version": 1,
        "cycle_id": cycle_id,
        "candidate_revision_id": candidate_revision_id,
        "status": "active",
        "created_at": timestamp,
        "completed_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "intake_sha256": test_semantic_sha256(intake),
        "intake": intake,
        "frontier_bindings": [],
        "claim_resolutions": [
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
        ],
        "derived_claims": [],
        "decision_assessment": None,
        "rerun_artifacts": [],
        "report_candidate": None,
        "audit": [],
    }
    return attach_valid_audit(cycle)


def make_task1_skeleton_cycle():
    cycle = make_minimal_cycle()
    cycle["intake"]["framing"]["snapshot"][
        "research_posture"
    ] = "decision_support"
    cycle["intake"]["triggers"] = []
    cycle["intake"]["selected_claims"] = []
    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
    cycle["claim_resolutions"] = []
    cycle["audit"] = []
    return cycle


def make_populated_cycle():
    cycle = make_minimal_cycle()
    timestamp = "2026-07-15T00:30:00Z"
    source_ref = {
        "kind": "source",
        "source_id": "src-001",
        "checked_at": timestamp,
    }
    artifact_ref = {
        "kind": "artifact",
        "path": "evidence/filing.md",
        "sha256": "d" * 64,
        "locator": "p. 1",
        "checked_at": timestamp,
    }
    trigger_id = "RC-0001-TRG-01"
    claim_id = "RC-0001-CL-01"
    derived_id = "RC-0001-DC-01"
    cycle["intake"]["triggers"] = [
        {
            "trigger_id": trigger_id,
            "kind": "upgrade",
            "statement": "Primary filing changed the revenue baseline.",
            "observed_at": "2026-07-15",
            "evidence_refs": [copy.deepcopy(source_ref)],
        }
    ]
    cycle["intake"]["selected_claims"] = [
        {
            "claim_id": claim_id,
            "statement": "Revenue baseline remains decision-load-bearing.",
            "source_ref": {
                "path": "reports/initial.md",
                "sha256": "a" * 64,
                "locator": "Claim 1",
                "historical_claim_id": None,
            },
            "importance": "critical",
            "selection_reasons": ["trigger_affected"],
            "trigger_ids": [trigger_id],
            "inherited_grade": "A",
            "inherited_confidence": "high",
            "inherited_evidence": [
                {
                    "ref": copy.deepcopy(source_ref),
                    "freshness": "fresh",
                    "checked_at": timestamp,
                    "reason": "Primary source remains current.",
                }
            ],
        }
    ]
    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
    cycle["frontier_bindings"] = [
        {
            "frontier_id": "frontier-001",
            "action": "reactivated",
            "claim_ids": [claim_id, derived_id],
            "expected_evidence": "Primary filing",
            "baseline_loop_count": 1,
            "baseline_review_count": 1,
            "registry_sha256": "c" * 64,
            "bound_at": timestamp,
        }
    ]
    cycle["derived_claims"] = [
        {
            "claim_id": derived_id,
            "origin": "emergent",
            "statement": "Updated revenue evidence is decision-relevant.",
            "derived_from": None,
            "accepted_from": {
                "loop_id": "loop-001",
                "dispatch_id": "dispatch-001",
                "evidence_refs": [copy.deepcopy(artifact_ref)],
            },
            "acceptance_rationale": "The evidence is directly traceable.",
        }
    ]
    cycle["claim_resolutions"] = [
        {
            "claim_id": claim_id,
            "status": "confirmed",
            "revised_statement": None,
            "current_evidence_refs": [copy.deepcopy(artifact_ref)],
            "counter_evidence_refs": [],
            "current_grade": "A",
            "current_confidence": "high",
            "bound_frontier_ids": ["frontier-001"],
            "rationale": "The primary filing confirms the claim.",
            "missing_proof": None,
            "attempted_loop_ids": [],
            "attempted_search_refs": [],
            "verdict_impact": None,
            "split_child_ids": [],
        },
        {
            "claim_id": derived_id,
            "status": "confirmed",
            "revised_statement": None,
            "current_evidence_refs": [copy.deepcopy(artifact_ref)],
            "counter_evidence_refs": [],
            "current_grade": "A",
            "current_confidence": "high",
            "bound_frontier_ids": ["frontier-001"],
            "rationale": "The accepted worker output is traceable.",
            "missing_proof": None,
            "attempted_loop_ids": [],
            "attempted_search_refs": [],
            "verdict_impact": None,
            "split_child_ids": [],
        },
    ]
    cycle["decision_assessment"] = {
        "new_action_class": "Watch with Trigger",
        "financial_bridge_affected": False,
        "financial_bridge_rationale": (
            "No accepted claim changes the modeled revenue transmission."
        ),
        "risk_class_changed": False,
        "risk_class_rationale": (
            "The remaining gap does not change the selected risk class."
        ),
        "supporting_claim_ids": [claim_id, derived_id],
        "verdict_rationale": "The new evidence confirms the prior posture.",
        "blocked_claim_ids": [],
        "change_class": "evidence_or_claim_only",
        "required_reruns": ["delta-frontier-review"],
    }
    cycle["rerun_artifacts"] = [
        {
            "kind": "bridge",
            "scope": "affected",
            "round": None,
            "path": "financials/RC-0001_TEST_bridge.md",
            "sha256": "e" * 64,
            "recorded_at": timestamp,
        }
    ]
    cycle["status"] = "ready_for_report"
    cycle["report_candidate"] = {
        "revision_id": "REV-0002",
        "revision_of": "REV-0001",
        "report_path": "reports/revision_REV-0002.md",
        "report_sha256": "f" * 64,
        "registered_at": timestamp,
    }
    return attach_valid_audit(cycle)


def make_populated_cycle_with_blocked_resolution():
    cycle = make_populated_cycle()
    cycle["claim_resolutions"][0] = make_blocked_resolution(
        "RC-0001-CL-01", "frontier-001"
    )
    cycle["decision_assessment"] = None
    return attach_valid_audit(cycle)


def nested_value(value, path):
    for part in path:
        value = value[part]
    return value


def set_nested_value(value, path, replacement):
    parent = nested_value(value, path[:-1]) if len(path) > 1 else value
    parent[path[-1]] = replacement


def attach_valid_audit(cycle):
    state = copy.deepcopy(cycle)
    state.pop("audit", None)
    affected_ids = [
        cycle["cycle_id"],
        cycle["candidate_revision_id"],
        *(trigger["trigger_id"] for trigger in cycle["intake"]["triggers"]),
        *(claim["claim_id"] for claim in cycle["intake"]["selected_claims"]),
    ]
    cycle["audit"] = [
        {
            "sequence": 1,
            "timestamp": cycle["created_at"],
            "command": "start",
            "affected_ids": affected_ids,
            "pre_state_sha256": test_semantic_sha256(None),
            "post_state_sha256": test_semantic_sha256(state),
        }
    ]
    return cycle


def make_history_cycle(cycle_number, revision_number, status="aborted"):
    cycle = make_minimal_cycle(
        cycle_id=f"RC-{cycle_number:04d}",
        candidate_revision_id=f"REV-{revision_number:04d}",
    )
    if status == "completed":
        cycle["status"] = "ready_for_report"
        cycle["report_candidate"] = {
            "revision_id": cycle["candidate_revision_id"],
            "revision_of": cycle["intake"]["base_revision"]["revision_id"],
            "report_path": (
                f"reports/HISTORY_{cycle['candidate_revision_id']}.md"
            ),
            "report_sha256": "f" * 64,
            "registered_at": "2026-07-15T01:59:00Z",
        }
        attach_valid_audit(cycle)
        completed = copy.deepcopy(cycle)
        completed["status"] = "completed"
        completed["completed_at"] = "2026-07-15T02:00:00Z"
        return revisit_model.with_audit(
            cycle,
            completed,
            "publish",
            [cycle["cycle_id"], cycle["candidate_revision_id"]],
            "2026-07-15T02:00:00Z",
        )
    if status == "aborted":
        aborted = copy.deepcopy(cycle)
        aborted["status"] = "aborted"
        aborted["aborted_at"] = "2026-07-15T02:00:00Z"
        aborted["abort_reason"] = "Historical test reservation."
        return revisit_model.with_audit(
            cycle,
            aborted,
            "abort",
            [cycle["cycle_id"]],
            "2026-07-15T02:00:00Z",
        )
    cycle["status"] = status
    return attach_valid_audit(cycle)


def make_terminal_cycle_fixture(
    cycle,
    status,
    *,
    timestamp="2026-07-15T02:00:00Z",
    report_path=None,
    report_sha256=None,
    abort_reason="Historical test reservation.",
):
    previous = copy.deepcopy(cycle)
    previous["status"] = "active"
    previous["completed_at"] = None
    previous["aborted_at"] = None
    previous["abort_reason"] = None
    if status == "completed":
        previous["status"] = "ready_for_report"
        if previous["report_candidate"] is None:
            previous["report_candidate"] = {
                "revision_id": previous["candidate_revision_id"],
                "revision_of": previous["intake"]["base_revision"]["revision_id"],
                "report_path": report_path
                or f"reports/HISTORY_{previous['candidate_revision_id']}.md",
                "report_sha256": report_sha256 or "f" * 64,
                "registered_at": "2026-07-15T01:59:00Z",
            }
        attach_valid_audit(previous)
        terminal = copy.deepcopy(previous)
        terminal["status"] = "completed"
        terminal["completed_at"] = timestamp
        return revisit_model.with_audit(
            previous,
            terminal,
            "publish",
            [previous["cycle_id"], previous["candidate_revision_id"]],
            timestamp,
        )
    if status == "aborted":
        attach_valid_audit(previous)
        terminal = copy.deepcopy(previous)
        terminal["status"] = "aborted"
        terminal["aborted_at"] = timestamp
        terminal["abort_reason"] = abort_reason
        return revisit_model.with_audit(
            previous,
            terminal,
            "abort",
            [previous["cycle_id"]],
            timestamp,
        )
    raise AssertionError(f"unsupported terminal fixture status: {status}")


def make_drifted_task4_cycle():
    cycle = make_minimal_cycle()
    cycle["intake"]["framing"]["snapshot"][
        "research_posture"
    ] = "decision_support"
    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
    attach_valid_audit(cycle)
    return cycle


class TestRevisitContext(unittest.TestCase):
    def _replace_source_excerpt(
        self,
        workspace: Path,
        source_id: str,
        text: str,
    ) -> Path:
        records = [
            json.loads(line)
            for line in (workspace / "sources_index.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        record = next(row for row in records if row["source_id"] == source_id)
        excerpt_path = workspace / record["excerpt_path"]
        excerpt_path.write_text(text, encoding="utf-8")
        record["sha256"] = excerpt_sha256(text)
        (workspace / "sources_index.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in records),
            encoding="utf-8",
        )
        return excerpt_path

    def _build(
        self,
        workspace: Path,
        cycle_id: str,
        frontier_id: str,
        *,
        claim_ids: tuple[str, ...] | None = None,
        role_slug: str = "frontier_scout",
        loop_id: str = "loop_8",
    ):
        return revisit_contract.build_revisit_context(
            workspace,
            cycle_id,
            frontier_id,
            claim_ids
            if claim_ids is not None
            else (f"{cycle_id}-CL-01",),
            role_slug,
            loop_id,
        )

    def test_scout_context_is_target_filtered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            builder = getattr(revisit_contract, "build_revisit_context", None)
            self.assertTrue(
                callable(builder),
                "build_revisit_context must be exported by revisit_contract",
            )

            context = builder(
                workspace,
                cycle_id,
                frontier_id,
                (f"{cycle_id}-CL-01",),
                "frontier_scout",
                "loop_8",
            )

            self.assertEqual(("revisit_context",), context.attachment_names)
            required = (
                cycle_id,
                f"{cycle_id}-TRG-01",
                f"{cycle_id}-CL-01",
                frontier_id,
                "Layer: 1",
                "Structural parent: F1",
                "The named qualification milestone moved beyond the prior watch window.",
                "Customer qualification completes inside the prior watch window.",
                "Current qualification timing and counter-evidence.",
                "F2 current qualification milestone evidence",
                "F2 obsolete qualification rumor",
                "target-frontier.example",
                "src-001",
                "Archived source excerpt for the qualification milestone.",
            )
            for value in required:
                with self.subTest(required=value):
                    self.assertIn(value, context.text)

            forbidden = (
                "F1 unrelated legacy qualification search",
                "F1 unrelated dead end",
                "unrelated-frontier.example",
                "src-002",
                "Unrelated source excerpt",
                "Watch with Trigger",
                "Confidence: medium",
                "moderate",
                "research status is",
                "LEAKED_SCOUT_OUTPUT",
                "Grade: B",
                "Retrieved: 2026-07-14",
            )
            for value in forbidden:
                with self.subTest(forbidden=value):
                    self.assertNotIn(value, context.text)

    def test_scout_context_renders_artifact_trigger_evidence_identifiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            evidence_path = workspace / "evidence_ledger.md"
            artifact_ref = {
                "kind": "artifact",
                "path": "evidence_ledger.md",
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                "locator": "Loop 8 artifact trigger evidence",
                "checked_at": "2026-07-14T12:45:00Z",
            }
            cycle["intake"]["triggers"][0]["evidence_refs"] = [artifact_ref]
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
            attach_valid_audit(cycle)
            revisit_contract.cycle_json_path(workspace, cycle_id).write_bytes(
                revisit_contract.canonical_document_bytes(cycle)
            )

            context = self._build(workspace, cycle_id, frontier_id)

            for value in (
                "Artifact ref: evidence_ledger.md",
                artifact_ref["sha256"],
                "locator=Loop 8 artifact trigger evidence",
                "checked_at=2026-07-14T12:45:00Z",
            ):
                with self.subTest(identifier=value):
                    self.assertIn(value, context.text)

    def test_scout_context_renders_source_trigger_id_and_checked_at(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )

            context = self._build(workspace, cycle_id, frontier_id)

            self.assertIn(
                "Source ref: src-001; checked_at=2026-07-14T10:00:00Z",
                context.text,
            )

    def test_scout_context_rejects_excerpt_drift_after_source_evaluation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            evaluation = revisit_context.evaluate_index(workspace)
            excerpt_path = workspace / "sources" / "src-001.md"

            def evaluate_then_drift(_workspace):
                excerpt_path.write_text(
                    "DRIFTED_UNVALIDATED_SOURCE_BYTES\n",
                    encoding="utf-8",
                )
                return evaluation

            with mock.patch.object(
                revisit_context,
                "evaluate_index",
                side_effect=evaluate_then_drift,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"hash|drift|registered",
                ):
                    self._build(workspace, cycle_id, frontier_id)

    def test_scout_context_rejects_excerpt_over_character_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            self._replace_source_excerpt(
                workspace,
                "src-001",
                "x" * (EXCERPT_MAX_CHARS + 1),
            )

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                r"cap|16000|too large|characters",
            ):
                self._build(workspace, cycle_id, frontier_id)

    def test_scout_context_accepts_excerpt_exactly_at_character_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            excerpt = "x" * EXCERPT_MAX_CHARS
            self._replace_source_excerpt(workspace, "src-001", excerpt)

            context = self._build(workspace, cycle_id, frontier_id)

            self.assertIn(f"    {excerpt}\n", context.text)

    def test_public_context_translates_registry_eloop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            with mock.patch.object(
                Path,
                "read_text",
                side_effect=OSError(errno.ELOOP, "registry symlink loop"),
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"frontier registry is invalid|symlink loop",
                ) as raised:
                    self._build(workspace, cycle_id, frontier_id)

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertEqual(errno.ELOOP, raised.exception.__cause__.errno)

    def test_public_context_translates_search_eloop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            with mock.patch.object(
                revisit_context,
                "build_prior_query_digest",
                side_effect=OSError(errno.ELOOP, "search symlink loop"),
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"prior-query search trace is invalid|symlink loop",
                ) as raised:
                    self._build(workspace, cycle_id, frontier_id)

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertEqual(errno.ELOOP, raised.exception.__cause__.errno)

    def test_public_context_translates_excerpt_eloop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            excerpt_path = mock.Mock()
            excerpt_path.read_bytes.side_effect = OSError(
                errno.ELOOP,
                "excerpt symlink loop",
            )
            with mock.patch.object(
                revisit_context,
                "resolve_workspace_path",
                return_value=excerpt_path,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"cannot read source excerpt|symlink loop",
                ) as raised:
                    self._build(workspace, cycle_id, frontier_id)

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertEqual(errno.ELOOP, raised.exception.__cause__.errno)

    def test_registry_read_expected_error_is_domain_but_eio_stays_loud(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            with mock.patch.object(
                Path,
                "read_text",
                side_effect=PermissionError("registry permission denied"),
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"frontier registry is invalid|permission denied",
                ):
                    revisit_context._load_frontier(workspace, frontier_id)

            with mock.patch.object(
                Path,
                "read_text",
                side_effect=OSError(errno.EIO, "registry I/O failure"),
            ):
                with self.assertRaises(OSError) as raised:
                    revisit_context._load_frontier(workspace, frontier_id)
            self.assertEqual(errno.EIO, raised.exception.errno)

    def test_search_owner_error_is_domain_but_eio_stays_loud(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            with mock.patch.object(
                revisit_context,
                "build_prior_query_digest",
                side_effect=ValueError("malformed target search trace"),
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"prior-query search trace is invalid|malformed",
                ):
                    self._build(workspace, cycle_id, frontier_id)

            with mock.patch.object(
                revisit_context,
                "build_prior_query_digest",
                side_effect=OSError(errno.EIO, "search I/O failure"),
            ):
                with self.assertRaises(OSError) as raised:
                    self._build(workspace, cycle_id, frontier_id)
            self.assertEqual(errno.EIO, raised.exception.errno)

    def test_excerpt_read_expected_error_is_domain_but_eio_stays_loud(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            missing_path = mock.Mock()
            missing_path.read_bytes.side_effect = FileNotFoundError(
                "selected excerpt missing"
            )
            with mock.patch.object(
                revisit_context,
                "resolve_workspace_path",
                return_value=missing_path,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"cannot read source excerpt|missing",
                ):
                    self._build(workspace, cycle_id, frontier_id)

            eio_path = mock.Mock()
            eio_path.read_bytes.side_effect = OSError(
                errno.EIO,
                "selected excerpt I/O failure",
            )
            with mock.patch.object(
                revisit_context,
                "resolve_workspace_path",
                return_value=eio_path,
            ):
                with self.assertRaises(OSError) as raised:
                    self._build(workspace, cycle_id, frontier_id)
            self.assertEqual(errno.EIO, raised.exception.errno)

    def test_cycle_and_source_owner_unexpected_io_remain_unwrapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            with mock.patch.object(
                revisit_context,
                "load_cycle",
                side_effect=OSError(errno.EIO, "cycle I/O failure"),
            ):
                with self.assertRaises(OSError) as raised:
                    self._build(workspace, cycle_id, frontier_id)
            self.assertEqual(errno.EIO, raised.exception.errno)

            with mock.patch.object(
                revisit_context,
                "evaluate_index",
                side_effect=OSError(errno.EIO, "source evaluation I/O failure"),
            ):
                with self.assertRaises(OSError) as raised:
                    self._build(workspace, cycle_id, frontier_id)
            self.assertEqual(errno.EIO, raised.exception.errno)

    def test_revisit_context_value_is_frozen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            context = self._build(workspace, cycle_id, frontier_id)

            with self.assertRaises(dataclasses.FrozenInstanceError):
                context.text = "mutated"

    def test_rejects_unsupported_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                r"frontier_scout|challenge_probe|only",
            ):
                self._build(
                    workspace,
                    cycle_id,
                    frontier_id,
                    role_slug="financial_bridge",
                )

    def test_rejects_unknown_empty_and_unbound_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )

            with self.subTest("unknown cycle"):
                with self.assertRaises(revisit_contract.RevisitContractError):
                    self._build(workspace, "RC-9999", frontier_id)
            with self.subTest("unknown frontier"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, r"frontier|F99"
                ):
                    self._build(workspace, cycle_id, "F99")
            with self.subTest("unknown claim"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, r"claim|CL-99"
                ):
                    self._build(
                        workspace,
                        cycle_id,
                        frontier_id,
                        claim_ids=(f"{cycle_id}-CL-99",),
                    )
            with self.subTest("empty claim subset"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, r"claim|empty|non-empty"
                ):
                    self._build(
                        workspace,
                        cycle_id,
                        frontier_id,
                        claim_ids=(),
                    )

            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            extra_claim = copy.deepcopy(cycle["intake"]["selected_claims"][0])
            extra_claim["claim_id"] = f"{cycle_id}-CL-02"
            extra_claim["source_ref"]["historical_claim_id"] = "C2"
            cycle["intake"]["selected_claims"].append(extra_claim)
            extra_resolution = copy.deepcopy(cycle["claim_resolutions"][0])
            extra_resolution["claim_id"] = extra_claim["claim_id"]
            cycle["claim_resolutions"].append(extra_resolution)
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
            attach_valid_audit(cycle)
            revisit_contract.cycle_json_path(workspace, cycle_id).write_bytes(
                revisit_contract.canonical_document_bytes(cycle)
            )
            with self.subTest("known claim not bound to target frontier"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, r"claim|bound|frontier"
                ):
                    self._build(
                        workspace,
                        cycle_id,
                        frontier_id,
                        claim_ids=(extra_claim["claim_id"],),
                    )

    def test_rejects_malformed_or_missing_source_cache_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            (workspace / "sources_index.jsonl").write_text(
                "not-json\n", encoding="utf-8"
            )
            with self.subTest("malformed source cache"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"source cache|SOURCE_INDEX_MALFORMED",
                ):
                    self._build(workspace, cycle_id, frontier_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            (workspace / "sources" / "src-001.md").unlink()
            with self.subTest("missing excerpt"):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    r"source cache|SOURCE_EXCERPT_MISSING|missing excerpt",
                ):
                    self._build(workspace, cycle_id, frontier_id)

    def test_rejects_malformed_target_search_trace_with_domain_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            (workspace / "search_log.jsonl").write_text(
                "{not-json\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                r"prior-query|search trace|search_log",
            ):
                self._build(workspace, cycle_id, frontier_id)

    def test_rejects_loop_at_or_before_cycle_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            for loop_id in ("loop_7", "loop_6"):
                with self.subTest(loop_id=loop_id):
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        r"after cycle boundary|loop",
                    ):
                        self._build(
                            workspace,
                            cycle_id,
                            frontier_id,
                            loop_id=loop_id,
                        )

    def test_challenge_context_exposes_only_ids_and_accepted_evidence_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_task7_context_workspace(
                Path(temp_dir)
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            resolution = cycle["claim_resolutions"][0]
            accepted_ref = {
                "kind": "artifact",
                "path": "evidence_ledger.md",
                "sha256": hashlib.sha256(
                    (workspace / "evidence_ledger.md").read_bytes()
                ).hexdigest(),
                "locator": "Loop 8 accepted evidence",
                "checked_at": "2026-07-14T12:30:00Z",
            }
            resolution.update(
                {
                    "status": "confirmed",
                    "current_evidence_refs": [accepted_ref],
                    "current_grade": "B",
                    "current_confidence": "medium",
                    "bound_frontier_ids": [frontier_id],
                    "rationale": "INVENTED_RATIONALE must remain private.",
                }
            )
            attach_valid_audit(cycle)
            revisit_contract.cycle_json_path(workspace, cycle_id).write_bytes(
                revisit_contract.canonical_document_bytes(cycle)
            )

            context = self._build(
                workspace,
                cycle_id,
                frontier_id,
                role_slug="challenge_probe",
            )

            required = (
                cycle_id,
                "loop_8",
                frontier_id,
                f"{cycle_id}-CL-01",
                "evidence_ledger.md",
                accepted_ref["sha256"],
                "Loop 8 accepted evidence",
                "2026-07-14T12:30:00Z",
                "Grade: B",
            )
            for value in required:
                with self.subTest(required=value):
                    self.assertIn(value, context.text)
            forbidden = (
                "LEAKED_SCOUT_OUTPUT",
                "INVENTED_RATIONALE",
                "Customer qualification completes inside the prior watch window.",
                "Watch with Trigger",
                "medium",
                "research status is",
                "Layer: 1",
                "Structural parent: F1",
            )
            for value in forbidden:
                with self.subTest(forbidden=value):
                    self.assertNotIn(value, context.text)


class TestRevisitPackageBootstrap(unittest.TestCase):
    def test_revisit_contract_package_entrypoint_exists(self):
        self.assertTrue(
            (REPO_ROOT / "scripts" / "revisit_contract" / "__init__.py").is_file()
        )


class TestRevisitCycleCliBootstrap(unittest.TestCase):
    def test_revisit_cycle_cli_entrypoint_exists(self):
        self.assertTrue(
            REVISIT_CYCLE_SCRIPT.is_file(),
            "scripts/revisit_cycle.py must exist before behavioral CLI tests run",
        )

    def test_revisit_cycle_cli_module_imports_from_repo_root(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import scripts.revisit_cycle"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_register_current_adopts_one_explicit_complete_legacy_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            original_report = report.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            pointer_path = workspace / "revisit_contract.json"
            self.assertTrue(
                pointer_path.is_file(),
                f"registration did not create pointer: {result.stdout}{result.stderr}",
            )
            pointer = revisit_contract.load_pointer(workspace)
            revision = pointer["current_revision"]
            self.assertEqual("REV-0001", revision["revision_id"])
            self.assertIsNone(revision["cycle_id"])
            self.assertEqual("reports/final.md", revision["report_path"])
            self.assertEqual(
                hashlib.sha256(original_report).hexdigest(),
                revision["report_sha256"],
            )
            self.assertEqual("Watch with Trigger", revision["action_class"])
            self.assertRegex(
                revision["validated_at"],
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
            )
            self.assertIsNone(revision["revision_of"])
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((workspace / "revisit_cycles").is_dir())
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))
            self.assertEqual(original_report, report.read_bytes())


class TestRevisitCycleRegisterCurrentCli(unittest.TestCase):
    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_register_current_rejects_report_retarget_between_owner_and_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            first_target = report.with_name("first.md")
            second_target = report.with_name("second.md")
            report_bytes = report.read_bytes()
            second_target.write_bytes(report_bytes)
            real_evaluate_report = revisit_cycle_cli.evaluate_specific_ticker_report

            def evaluate_then_retarget(*args, **kwargs):
                result = real_evaluate_report(*args, **kwargs)
                report.replace(first_target)
                report.symlink_to(second_target.name)
                return result

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_specific_ticker_report",
                    side_effect=evaluate_then_retarget,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        "Watch with Trigger",
                    ]
                )

            self.assertNotEqual(0, result, stdout.getvalue())
            self.assertNotIn("CURRENT REPORT REGISTERED", stdout.getvalue())
            self.assertEqual(second_target.resolve(), report.resolve())
            self.assertEqual(report_bytes, first_target.read_bytes())
            self.assertEqual(report_bytes, second_target.read_bytes())
            self.assertFalse((workspace / revisit_contract.POINTER_FILENAME).exists())
            self.assertFalse((workspace / revisit_contract.CYCLES_DIRNAME).exists())

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_register_current_rejects_equal_byte_report_retarget_after_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            first_target = report.with_name("first.md")
            second_target = report.with_name("second.md")
            report_bytes = report.read_bytes()
            second_target.write_bytes(report_bytes)
            real_persist_pointer = revisit_cycle_cli.persist_pointer

            def retarget_then_persist(*args, **kwargs):
                report.replace(first_target)
                report.symlink_to(second_target.name)
                return real_persist_pointer(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_pointer",
                    side_effect=retarget_then_persist,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        "Watch with Trigger",
                    ]
                )

            self.assertNotEqual(0, result, stdout.getvalue())
            self.assertNotIn("CURRENT REPORT REGISTERED", stdout.getvalue())
            self.assertEqual(second_target.resolve(), report.resolve())
            self.assertEqual(report_bytes, first_target.read_bytes())
            self.assertEqual(report_bytes, second_target.read_bytes())
            self.assertFalse((workspace / revisit_contract.POINTER_FILENAME).exists())
            self.assertFalse((workspace / revisit_contract.CYCLES_DIRNAME).exists())

    def test_register_current_rejects_existing_cycle_history_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            cycle = make_history_cycle(1, 2, "aborted")
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=None,
            )
            before = snapshot_tree(workspace)
            report_before = report.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn(
                "cycle history exists without a current revision",
                result.stderr,
            )
            self.assertEqual(before, snapshot_tree(workspace))
            self.assertEqual(report_before, report.read_bytes())

    def test_register_current_rejects_pointer_changed_between_snapshot_and_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            report_bytes = report.read_bytes()
            revisit_contract.persist_pointer(
                workspace,
                revisit_contract.empty_pointer(),
                expected_sha256=None,
            )
            pointer_path = workspace / "revisit_contract.json"
            concurrent_pointer = revisit_contract.empty_pointer()
            concurrent_pointer["current_revision"] = {
                "revision_id": "REV-0001",
                "cycle_id": None,
                "report_path": "reports/concurrent.md",
                "report_sha256": "c" * 64,
                "action_class": "Reject",
                "validated_at": "2026-07-15T02:00:00Z",
                "revision_of": None,
            }
            concurrent_bytes = revisit_contract.canonical_document_bytes(
                concurrent_pointer
            )
            calls = []
            real_load_pointer = revisit_cycle_cli.load_pointer
            real_sha256_file = revisit_cycle_cli.sha256_file

            def inject_concurrent_pointer(operation):
                calls.append(operation)
                if len(calls) == 1:
                    pointer_path.write_bytes(concurrent_bytes)

            def interleaved_load_pointer(*args, **kwargs):
                loaded = real_load_pointer(*args, **kwargs)
                inject_concurrent_pointer("load")
                return loaded

            def interleaved_sha256_file(*args, **kwargs):
                digest = real_sha256_file(*args, **kwargs)
                inject_concurrent_pointer("digest")
                return digest

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "load_pointer",
                    side_effect=interleaved_load_pointer,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "sha256_file",
                    side_effect=interleaved_sha256_file,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", io.StringIO()),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", io.StringIO()),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        "Watch with Trigger",
                    ]
                )

            self.assertEqual(concurrent_bytes, pointer_path.read_bytes())
            self.assertEqual(["digest", "load"], calls)
            self.assertEqual(2, result)
            self.assertEqual(report_bytes, report.read_bytes())
            self.assertFalse((workspace / "revisit_cycles").exists())

    def test_register_current_accepts_exact_locked_action_vocabulary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, action_class in enumerate(revisit_contract.ACTION_CLASSES):
                with self.subTest(action_class=action_class):
                    workspace, _ = make_registration_workspace(root / str(index))

                    result = run_revisit_cycle_cli(
                        workspace,
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        action_class,
                    )

                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        action_class,
                        revisit_contract.load_pointer(workspace)["current_revision"][
                            "action_class"
                        ],
                    )

    def test_register_current_restores_pointer_when_report_drifts_after_commit(self):
        for prior_pointer in (False, True):
            with self.subTest(prior_pointer=prior_pointer):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, report = make_registration_workspace(Path(temp_dir))
                    pointer_path = workspace / revisit_contract.POINTER_FILENAME
                    cycles_path = workspace / revisit_contract.CYCLES_DIRNAME
                    if prior_pointer:
                        revisit_contract.persist_pointer(
                            workspace,
                            revisit_contract.empty_pointer(),
                            expected_sha256=None,
                        )
                        cycles_path.mkdir()
                        pointer_before = pointer_path.read_bytes()
                    else:
                        pointer_before = None
                    drifted_report = report.read_bytes() + b"registration drift\n"
                    cli_store = sys.modules[revisit_cycle_cli.persist_pointer.__module__]
                    real_atomic_replace = cli_store._atomic_replace
                    injected = False

                    def replace_then_drift(path, payload):
                        nonlocal injected
                        real_atomic_replace(path, payload)
                        if Path(path).name == revisit_contract.POINTER_FILENAME and not injected:
                            injected = True
                            report.write_bytes(drifted_report)

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            cli_store,
                            "_atomic_replace",
                            side_effect=replace_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "register-current",
                                "--report",
                                "reports/final.md",
                                "--action-class",
                                "Watch with Trigger",
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("CURRENT REPORT REGISTERED", stdout.getvalue())
                    self.assertEqual(drifted_report, report.read_bytes())
                    if pointer_before is None:
                        self.assertFalse(pointer_path.exists())
                        self.assertFalse(cycles_path.exists())
                    else:
                        self.assertEqual(pointer_before, pointer_path.read_bytes())
                        self.assertEqual([], list(cycles_path.iterdir()))

    def test_register_current_rejects_non_exact_action_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "watch with trigger",
            )

            self.assertEqual(2, result.returncode)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_register_current_rejects_unsafe_outside_and_non_markdown_paths_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = make_registration_workspace(root)
            outside = root / "outside.md"
            outside.write_bytes(complete_ticker_report_bytes())
            (workspace / "reports" / "final.txt").write_bytes(
                complete_ticker_report_bytes()
            )
            (workspace / "reports" / "nonutf8.md").write_bytes(b"\xff\xfe")
            paths = (
                "/".join(("..", "outside.md")),
                "/".join(("reports", "..", "outside.md")),
                str(outside.resolve()),
                "reports/final.txt",
                "reports/nonutf8.md",
                "reports/missing.md",
            )
            for report_path in paths:
                with self.subTest(report_path=report_path):
                    before = snapshot_tree(workspace)
                    outside_before = outside.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "register-current",
                        "--report",
                        report_path,
                        "--action-class",
                        "Watch with Trigger",
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))
                    self.assertEqual(outside_before, outside.read_bytes())

    def test_incomplete_report_is_readiness_failure_with_zero_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            report.write_bytes(
                report.read_bytes().replace(
                    b"Watch protocol: monitor customer updates.\n",
                    b"",
                )
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("FINAL_REPORT_MISSING_WATCH_PROTOCOL", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_register_current_accepts_strict_empty_pointer_and_preserves_raw_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            original_report = report.read_bytes().replace(b"\n", b"\r\n")
            report.write_bytes(original_report)
            revisit_contract.persist_pointer(
                workspace,
                revisit_contract.empty_pointer(),
                expected_sha256=None,
            )
            (workspace / "revisit_cycles").mkdir()

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            revision = revisit_contract.load_pointer(workspace)["current_revision"]
            self.assertEqual(
                hashlib.sha256(original_report).hexdigest(),
                revision["report_sha256"],
            )
            self.assertEqual(original_report, report.read_bytes())
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_second_registration_cannot_replace_non_null_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            first = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )
            self.assertEqual(0, first.returncode, first.stderr)
            second_report = workspace / "reports" / "second.md"
            second_report.write_bytes(complete_ticker_report_bytes())
            before = snapshot_tree(workspace)

            second = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/second.md",
                "--action-class",
                "Reject",
            )

            self.assertEqual(2, second.returncode, second.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_sector_workspace_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(
                Path(temp_dir),
                mode="sector",
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_malformed_pointer_is_rejected_without_repair_or_cycle_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            pointer = workspace / "revisit_contract.json"
            pointer.write_bytes(b'{"schema_version": 1, invalid json')
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_validation_error_prints_utf8_safely_under_ascii_stdio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            unicode_report = report.with_name("报告.md")
            unicode_report.write_bytes(
                report.read_bytes().replace(
                    b"Watch protocol: monitor customer updates.\n",
                    b"",
                )
            )
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "ascii"
            env["LC_ALL"] = "C"
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/报告.md",
                "--action-class",
                "Watch with Trigger",
                env=env,
            )

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("reports/报告.md", result.stderr)
            self.assertNotIn("UnicodeEncodeError", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitCycleStartCli(unittest.TestCase):
    def run_invalid_request_case(self, mutate_request, expected_error):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            mutate_request(request)
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            workspace_before = snapshot_tree(workspace)
            request_before = request_path.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertRegex(result.stderr, expected_error)
            self.assertEqual(workspace_before, snapshot_tree(workspace))
            self.assertEqual(request_before, request_path.read_bytes())

    def test_start_creates_immutable_intake_with_stable_ids_and_initial_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            pointer_before = (workspace / revisit_contract.POINTER_FILENAME).read_bytes()
            request_before = request_path.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "REVISIT CYCLE STARTED: RC-0001 (candidate REV-0002)\n",
                result.stdout,
            )
            cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
            mirror_path = workspace / "revisit_cycles" / "RC-0001.md"
            cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
            self.assertIs(cycle, revisit_contract.validate_cycle(cycle))
            self.assertEqual("RC-0001", cycle["cycle_id"])
            self.assertEqual("REV-0002", cycle["candidate_revision_id"])
            self.assertEqual("active", cycle["status"])
            self.assertEqual(
                ["RC-0001-TRG-01"],
                [trigger["trigger_id"] for trigger in cycle["intake"]["triggers"]],
            )
            self.assertEqual(
                ["RC-0001-CL-01"],
                [
                    claim["claim_id"]
                    for claim in cycle["intake"]["selected_claims"]
                ],
            )
            self.assertEqual(
                ["RC-0001-TRG-01"],
                cycle["intake"]["selected_claims"][0]["trigger_ids"],
            )
            self.assertNotIn(
                "trigger_indexes", cycle["intake"]["selected_claims"][0]
            )
            self.assertEqual(
                [
                    {
                        "claim_id": "RC-0001-CL-01",
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
                ],
                cycle["claim_resolutions"],
            )
            self.assertEqual(
                hashlib.sha256(
                    (workspace / "framing_contract.json").read_bytes()
                ).hexdigest(),
                cycle["intake"]["framing"]["sha256"],
            )
            self.assertEqual(
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
                set(cycle["intake"]["framing"]["snapshot"]),
            )
            self.assertEqual(
                {
                    "revision_id",
                    "report_path",
                    "report_sha256",
                    "action_class",
                },
                set(cycle["intake"]["base_revision"]),
            )
            self.assertEqual(
                hashlib.sha256(
                    (workspace / "frontier_registry.json").read_bytes()
                ).hexdigest(),
                cycle["intake"]["workspace_boundary"][
                    "frontier_registry_sha256"
                ],
            )
            self.assertEqual(
                7,
                cycle["intake"]["workspace_boundary"][
                    "max_existing_loop_number"
                ],
            )
            self.assertEqual(
                revisit_contract.intake_sha256(cycle["intake"]),
                cycle["intake_sha256"],
            )
            self.assertEqual(1, len(cycle["audit"]))
            self.assertEqual(1, cycle["audit"][0]["sequence"])
            self.assertEqual("start", cycle["audit"][0]["command"])
            self.assertEqual(
                revisit_contract.semantic_sha256(None),
                cycle["audit"][0]["pre_state_sha256"],
            )
            self.assertEqual(
                revisit_contract.cycle_state_sha256(cycle),
                cycle["audit"][0]["post_state_sha256"],
            )

            serialized = cycle_path.read_text(encoding="utf-8")
            mirror = mirror_path.read_text(encoding="utf-8")
            self.assertNotIn(str(request_path), serialized)
            self.assertNotIn("trigger_indexes", serialized)
            self.assertNotIn("Archived source excerpt", serialized)
            self.assertIn("RC-0001-TRG-01", mirror)
            self.assertIn("RC-0001-CL-01", mirror)
            self.assertIn(
                "Unselected historical claims are omitted and cannot support this cycle.",
                mirror,
            )
            self.assertEqual(1, mirror.count("Watch with Trigger"))
            for action_class in set(revisit_contract.ACTION_CLASSES) - {
                "Watch with Trigger"
            }:
                self.assertNotIn(action_class, mirror)
            self.assertEqual(
                pointer_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )
            self.assertEqual(request_before, request_path.read_bytes())

    def test_framing_semantics_and_hash_share_one_raw_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_revisit_start_workspace(Path(temp_dir))
            framing_path = workspace / "framing_contract.json"
            framing_target = framing_path.resolve()
            original_bytes = framing_path.read_bytes()
            drifted = json.loads(original_bytes.decode("utf-8"))
            drifted["time_horizon"] = "drifted horizon"
            drifted_bytes = (
                json.dumps(drifted, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            real_read_bytes = Path.read_bytes
            injected = False

            def read_then_drift(path):
                nonlocal injected
                payload = real_read_bytes(path)
                if Path(path) == framing_target and not injected:
                    injected = True
                    framing_path.write_bytes(drifted_bytes)
                return payload

            with mock.patch.object(Path, "read_bytes", new=read_then_drift):
                (
                    snapshot,
                    returned_path,
                    digest,
                    _,
                ) = revisit_cycle_cli._load_revisit_framing(workspace)

            self.assertEqual(framing_path, returned_path)
            self.assertEqual(hashlib.sha256(original_bytes).hexdigest(), digest)
            self.assertEqual("6-12 months", snapshot["time_horizon"])
            self.assertEqual(drifted_bytes, framing_path.read_bytes())

    def test_start_preserves_request_order_and_validates_artifact_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            second_trigger = copy.deepcopy(request["triggers"][0])
            second_trigger["statement"] = "A second fired trigger remains distinct."
            request["triggers"].append(second_trigger)
            second_claim = copy.deepcopy(request["selected_claims"][0])
            second_claim["statement"] = "The second selected claim keeps request order."
            second_claim["trigger_indexes"] = [2]
            request["selected_claims"].append(second_claim)
            request["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "claim_ledger.md",
                    "sha256": request["selected_claims"][0]["source_ref"]["sha256"],
                    "locator": "Claim C1",
                    "checked_at": "2026-07-14T10:00:00Z",
                }
            ]
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            cycle = revisit_contract.load_cycle(workspace, "RC-0001")
            self.assertEqual(
                ["RC-0001-TRG-01", "RC-0001-TRG-02"],
                [item["trigger_id"] for item in cycle["intake"]["triggers"]],
            )
            self.assertEqual(
                ["RC-0001-CL-01", "RC-0001-CL-02"],
                [item["claim_id"] for item in cycle["intake"]["selected_claims"]],
            )
            self.assertEqual(
                [["RC-0001-TRG-01"], ["RC-0001-TRG-02"]],
                [item["trigger_ids"] for item in cycle["intake"]["selected_claims"]],
            )
            self.assertEqual(
                "artifact",
                cycle["intake"]["triggers"][0]["evidence_refs"][0]["kind"],
            )
            self.assertEqual(
                "claim_ledger.md",
                cycle["intake"]["triggers"][0]["evidence_refs"][0]["path"],
            )
            self.assertEqual(
                ["RC-0001-CL-01", "RC-0001-CL-02"],
                [item["claim_id"] for item in cycle["claim_resolutions"]],
            )

    def test_start_rejects_unsafe_and_symlink_escape_artifact_paths_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / "outside.md"
            outside.write_text("Outside authority.\n", encoding="utf-8")
            outside_hash = hashlib.sha256(outside.read_bytes()).hexdigest()
            for label, unsafe_path in (
                ("parent", ".." + "/" + "outside.md"),
                ("absolute", str(outside.resolve())),
                ("windows", "C:" + "\\" + "outside.md"),
                ("symlink", "outside-link.md"),
            ):
                with self.subTest(label=label):
                    if label == "symlink" and not CAN_SYMLINK:
                        self.skipTest("requires symbolic links")
                    case_root = root / label
                    case_root.mkdir()
                    workspace, request_path = make_revisit_start_workspace(case_root)
                    if label == "symlink":
                        (workspace / unsafe_path).symlink_to(outside)
                    request = json.loads(request_path.read_text(encoding="utf-8"))
                    request["selected_claims"][0]["source_ref"].update(
                        {"path": unsafe_path, "sha256": outside_hash}
                    )
                    request_path.write_text(
                        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertRegex(
                        result.stderr,
                        r"canonical workspace-relative POSIX path|absolute workspace path is forbidden|forbidden '\.\.'|path escapes workspace",
                    )
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_start_request_rejects_unknown_fields_at_every_owned_object_without_writes(self):
        cases = (
            (
                "top level",
                lambda request: request.update({"hidden": True}),
                r"request unknown field.*hidden",
            ),
            (
                "trigger",
                lambda request: request["triggers"][0].update({"hidden": True}),
                r"request\.triggers\[0\] unknown field.*hidden",
            ),
            (
                "trigger evidence",
                lambda request: request["triggers"][0]["evidence_refs"][0].update(
                    {"hidden": True}
                ),
                r"request\.triggers\[0\]\.evidence_refs\[0\] unknown field.*hidden",
            ),
            (
                "selected claim",
                lambda request: request["selected_claims"][0].update(
                    {"hidden": True}
                ),
                r"request\.selected_claims\[0\] unknown field.*hidden",
            ),
            (
                "claim source ref",
                lambda request: request["selected_claims"][0][
                    "source_ref"
                ].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.source_ref unknown field.*hidden",
            ),
            (
                "inherited evidence",
                lambda request: request["selected_claims"][0][
                    "inherited_evidence"
                ][0].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.inherited_evidence\[0\] unknown field.*hidden",
            ),
            (
                "inherited evidence ref",
                lambda request: request["selected_claims"][0][
                    "inherited_evidence"
                ][0]["ref"].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.inherited_evidence\[0\]\.ref unknown field.*hidden",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_empty_required_arrays_without_writes(self):
        cases = (
            (
                "triggers",
                lambda request: request.__setitem__("triggers", []),
                r"request\.triggers must not be empty",
            ),
            (
                "selected claims",
                lambda request: request.__setitem__("selected_claims", []),
                r"request\.selected_claims must not be empty",
            ),
            (
                "trigger evidence",
                lambda request: request["triggers"][0].__setitem__(
                    "evidence_refs", []
                ),
                r"request\.triggers\[0\]\.evidence_refs must not be empty",
            ),
            (
                "selection reasons",
                lambda request: request["selected_claims"][0].__setitem__(
                    "selection_reasons", []
                ),
                r"selection_reasons must not be empty",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_malformed_times_raw_urls_and_missing_sources_without_writes(self):
        cases = (
            (
                "impossible observed date",
                lambda request: request["triggers"][0].__setitem__(
                    "observed_at", "2026-02-30"
                ),
                r"observed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "noncanonical checked at",
                lambda request: request["triggers"][0]["evidence_refs"][
                    0
                ].__setitem__("checked_at", "2026-07-14T10:00:00+00:00"),
                r"checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "raw URL evidence",
                lambda request: request["triggers"][0].__setitem__(
                    "evidence_refs", ["https://example.test/raw"]
                ),
                r"evidence_refs\[0\] must be an object",
            ),
            (
                "missing registered source",
                lambda request: request["triggers"][0]["evidence_refs"][
                    0
                ].__setitem__("source_id", "src-999"),
                r"source_id is not registered: src-999",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_bad_artifacts_or_trigger_mapping_without_writes(self):
        def artifact_ref(request, *, digest, locator="Claim C1"):
            request["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "claim_ledger.md",
                    "sha256": digest,
                    "locator": locator,
                    "checked_at": "2026-07-14T10:00:00Z",
                }
            ]

        cases = (
            (
                "artifact hash mismatch",
                lambda request: artifact_ref(request, digest="0" * 64),
                r"artifact hash mismatch: claim_ledger\.md",
            ),
            (
                "artifact locator empty",
                lambda request: artifact_ref(
                    request,
                    digest=request["selected_claims"][0]["source_ref"]["sha256"],
                    locator="",
                ),
                r"locator must be non-empty text",
            ),
            (
                "orphan trigger",
                lambda request: request["triggers"].append(
                    copy.deepcopy(request["triggers"][0])
                ),
                (
                    r"REVISIT_TRIGGER_ORPHANED: request trigger index 2 "
                    r"is not referenced by any selected claim"
                ),
            ),
            (
                "trigger index out of range",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", [2]
                ),
                r"trigger_indexes.*out of range: 2",
            ),
            (
                "boolean trigger index",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", [True]
                ),
                r"trigger_indexes.*integer >= 1",
            ),
            (
                "unsupported selection reason",
                lambda request: request["selected_claims"][0].__setitem__(
                    "selection_reasons", ["trigger_affected", "because_i_said_so"]
                ),
                r"selection_reasons selection reason is unsupported",
            ),
            (
                "trigger affected without mapping",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", []
                ),
                r"trigger_affected requires non-empty trigger_indexes",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_rejects_report_framing_and_registry_drift_without_writes(self):
        cases = (
            (
                "report hash drift",
                lambda workspace: (workspace / "reports" / "final.md").write_bytes(
                    complete_ticker_report_bytes() + b"drift\n"
                ),
                r"CURRENT_REPORT_HASH_DRIFT|registered report bytes do not match",
            ),
            (
                "framing mode drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "framing_contract.json", "mode", "sector"
                ),
                r"framing contract.*mode|FRAMING_MODE_DRIFT",
            ),
            (
                "framing posture drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "framing_contract.json",
                    "research_posture",
                    "fresh",
                ),
                r"framing contract research_posture must be revisit",
            ),
            (
                "registry mode drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "frontier_registry.json", "mode", "sector"
                ),
                r"frontier registry mode must be ticker",
            ),
            (
                "malformed loop header",
                lambda workspace: (workspace / "evidence_ledger.md").write_text(
                    "# Evidence Ledger\n\n## Loop X: F1 - Qualification timing\n",
                    encoding="utf-8",
                ),
                r"malformed loop header",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    mutate(workspace)
                    workspace_before = snapshot_tree(workspace)
                    request_before = request_path.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertNotEqual(0, result.returncode, result.stderr)
                    self.assertRegex(result.stderr, expected_error)
                    self.assertEqual(workspace_before, snapshot_tree(workspace))
                    self.assertEqual(request_before, request_path.read_bytes())

    def test_start_rejects_each_authority_drift_before_persistence(self):
        target_names = (
            "revisit_contract.json",
            "reports/final.md",
            "framing_contract.json",
            "frontier_registry.json",
            "evidence_ledger.md",
            "claim_ledger.md",
            "sources_index.jsonl",
            "sources/src-001.md",
        )
        real_create_cycle = revisit_cycle_cli.create_cycle
        for target_name in target_names:
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    before = snapshot_tree(workspace)
                    drifted_bytes = target.read_bytes() + b" "

                    def create_then_drift(**kwargs):
                        cycle = real_create_cycle(**kwargs)
                        target.write_bytes(drifted_bytes)
                        return cycle

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with mock.patch.object(
                        revisit_cycle_cli,
                        "create_cycle",
                        side_effect=create_then_drift,
                    ), mock.patch("sys.stdout", new=stdout), mock.patch(
                        "sys.stderr", new=stderr
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertIn(
                        f"authority changed before cycle persistence: {target.name}",
                        stderr.getvalue(),
                    )
                    after = snapshot_tree(workspace)
                    relative_target = target.relative_to(workspace).as_posix()
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertEqual(set(before), set(after))
                    for relative, expected in before.items():
                        if relative == relative_target:
                            continue
                        self.assertEqual(expected, after[relative], relative)
                    self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_start_rolls_back_committed_pair_when_report_drifts_after_json_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            report_path = workspace / "reports" / "final.md"
            report_before = report_path.read_bytes()
            drifted_report = report_before + b"post-commit drift\n"
            cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
            real_atomic_replace = cli_store._atomic_replace
            injected = False

            def replace_then_drift(path, payload):
                nonlocal injected
                real_atomic_replace(path, payload)
                if Path(path).name == "RC-0001.json" and not injected:
                    injected = True
                    report_path.write_bytes(drifted_report)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    cli_store,
                    "_atomic_replace",
                    side_effect=replace_then_drift,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "start",
                        "--intake-file",
                        str(request_path),
                    ]
                )

            self.assertEqual(2, result, stderr.getvalue())
            self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
            self.assertEqual(drifted_report, report_path.read_bytes())
            self.assertFalse((workspace / "revisit_cycles" / "RC-0001.json").exists())
            self.assertFalse((workspace / "revisit_cycles" / "RC-0001.md").exists())

    def test_start_rolls_back_committed_pair_when_other_authority_drifts_after_json_commit(self):
        target_names = (
            "revisit_contract.json",
            "framing_contract.json",
            "frontier_registry.json",
            "evidence_ledger.md",
            "claim_ledger.md",
        )
        for target_name in target_names:
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    drifted_bytes = target.read_bytes() + b"post-commit drift\n"
                    cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
                    real_atomic_replace = cli_store._atomic_replace
                    injected = False

                    def replace_then_drift(path, payload):
                        nonlocal injected
                        real_atomic_replace(path, payload)
                        if Path(path).name == "RC-0001.json" and not injected:
                            injected = True
                            target.write_bytes(drifted_bytes)

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            cli_store,
                            "_atomic_replace",
                            side_effect=replace_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertFalse((workspace / "revisit_cycles" / "RC-0001.json").exists())
                    self.assertFalse((workspace / "revisit_cycles" / "RC-0001.md").exists())

    def test_start_binds_source_index_and_excerpt_before_cycle_persistence(self):
        for target_name in ("sources_index.jsonl", "sources/src-001.md"):
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    drifted_bytes = target.read_bytes() + b"source drift\n"
                    real_create_cycle = revisit_cycle_cli.create_cycle

                    def create_then_drift(**kwargs):
                        cycle = real_create_cycle(**kwargs)
                        target.write_bytes(drifted_bytes)
                        return cycle

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            revisit_cycle_cli,
                            "create_cycle",
                            side_effect=create_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_source_excerpt_snapshot_preserves_canonical_lexical_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            lexical_excerpt = workspace / "sources" / "src-001.md"
            resolved_excerpt = workspace / "sources" / "src-001-target.md"
            resolved_excerpt.write_bytes(lexical_excerpt.read_bytes())
            lexical_excerpt.unlink()
            lexical_excerpt.symlink_to(resolved_excerpt.name)

            request = revisit_store.load_intake_request(request_path)
            _, snapshots = revisit_cycle_cli._validate_request_references(
                workspace, request
            )

            lexical_paths = {snapshot.lexical_path for snapshot in snapshots}
            canonical_workspace = workspace.resolve()
            self.assertIn(
                canonical_workspace / "sources" / "src-001.md",
                lexical_paths,
            )
            self.assertNotIn(
                canonical_workspace / "sources" / "src-001-target.md",
                lexical_paths,
            )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_start_rejects_equal_byte_source_retarget_after_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            lexical_excerpt = workspace / "sources" / "src-001.md"
            first_target = workspace / "sources" / "src-001-first.md"
            second_target = workspace / "sources" / "src-001-second.md"
            excerpt_bytes = lexical_excerpt.read_bytes()
            first_target.write_bytes(excerpt_bytes)
            second_target.write_bytes(excerpt_bytes)
            lexical_excerpt.unlink()
            lexical_excerpt.symlink_to(first_target.name)
            source_index = workspace / "sources_index.jsonl"
            pointer = workspace / revisit_contract.POINTER_FILENAME
            source_index_before = source_index.read_bytes()
            pointer_before = pointer.read_bytes()
            real_create_cycle = revisit_cycle_cli.create_cycle

            def create_then_retarget(**kwargs):
                cycle = real_create_cycle(**kwargs)
                lexical_excerpt.unlink()
                lexical_excerpt.symlink_to(second_target.name)
                return cycle

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "create_cycle",
                    side_effect=create_then_retarget,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "start",
                        "--intake-file",
                        str(request_path),
                    ]
                )

            self.assertNotEqual(0, result, stdout.getvalue())
            self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
            self.assertEqual(second_target.resolve(), lexical_excerpt.resolve())
            self.assertEqual(excerpt_bytes, first_target.read_bytes())
            self.assertEqual(excerpt_bytes, second_target.read_bytes())
            self.assertEqual(source_index_before, source_index.read_bytes())
            self.assertEqual(pointer_before, pointer.read_bytes())
            self.assertFalse(
                (workspace / "revisit_cycles" / "RC-0001.json").exists()
            )
            self.assertFalse(
                (workspace / "revisit_cycles" / "RC-0001.md").exists()
            )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_start_rejects_registry_retarget_between_owner_and_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            registry = workspace / "frontier_registry.json"
            first_target = workspace / "frontier_registry-first.json"
            second_target = workspace / "frontier_registry-second.json"
            registry_bytes = registry.read_bytes()
            second_target.write_bytes(registry_bytes)
            pointer = workspace / revisit_contract.POINTER_FILENAME
            source_index = workspace / "sources_index.jsonl"
            source_excerpt = workspace / "sources" / "src-001.md"
            pointer_before = pointer.read_bytes()
            source_index_before = source_index.read_bytes()
            source_excerpt_before = source_excerpt.read_bytes()
            real_read_registry = revisit_cycle_cli.read_registry_snapshot

            def read_then_retarget(*args, **kwargs):
                result = real_read_registry(*args, **kwargs)
                registry.replace(first_target)
                registry.symlink_to(second_target.name)
                return result

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "read_registry_snapshot",
                    side_effect=read_then_retarget,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "start",
                        "--intake-file",
                        str(request_path),
                    ]
                )

            self.assertNotEqual(0, result, stdout.getvalue())
            self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
            self.assertEqual(second_target.resolve(), registry.resolve())
            self.assertEqual(registry_bytes, first_target.read_bytes())
            self.assertEqual(registry_bytes, second_target.read_bytes())
            self.assertEqual(pointer_before, pointer.read_bytes())
            self.assertEqual(source_index_before, source_index.read_bytes())
            self.assertEqual(source_excerpt_before, source_excerpt.read_bytes())
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )

    def test_start_captures_all_authority_generations_before_owner_reads(self):
        read_generation = getattr(
            revisit_cycle_cli,
            "_read_authority_generation",
            None,
        )
        self.assertTrue(
            callable(read_generation),
            "authority generation read seam is missing",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            events = []

            def record_generation(snapshot_workspace, path):
                relative = Path(path).relative_to(snapshot_workspace).as_posix()
                events.append(("capture", relative))
                return read_generation(snapshot_workspace, path)

            def record_owner(label, operation):
                def wrapper(*args, **kwargs):
                    events.append(("owner", label))
                    return operation(*args, **kwargs)

                return wrapper

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_read_authority_generation",
                    side_effect=record_generation,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "load_pointer",
                    side_effect=record_owner(
                        "pointer",
                        revisit_cycle_cli.load_pointer,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "read_specific_markdown_report",
                    side_effect=record_owner(
                        "report-read",
                        revisit_cycle_cli.read_specific_markdown_report,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_specific_ticker_report",
                    side_effect=record_owner(
                        "report-evaluate",
                        revisit_cycle_cli.evaluate_specific_ticker_report,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_contract",
                    side_effect=record_owner(
                        "framing",
                        revisit_cycle_cli.evaluate_contract,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "read_registry_snapshot",
                    side_effect=record_owner(
                        "registry",
                        revisit_cycle_cli.read_registry_snapshot,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "derive_loop_counts",
                    side_effect=record_owner(
                        "ledger",
                        revisit_cycle_cli.derive_loop_counts,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_index",
                    side_effect=record_owner(
                        "source-cache",
                        revisit_cycle_cli.evaluate_index,
                    ),
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "verify_workspace_artifact",
                    side_effect=record_owner(
                        "artifact",
                        revisit_cycle_cli.verify_workspace_artifact,
                    ),
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", io.StringIO()),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "start",
                        "--intake-file",
                        str(request_path),
                    ]
                )

            self.assertEqual(0, result)
            captured_paths = {
                path for kind, path in events if kind == "capture"
            }
            self.assertEqual(
                {
                    "revisit_contract.json",
                    "reports/final.md",
                    "framing_contract.json",
                    "frontier_registry.json",
                    "evidence_ledger.md",
                    "sources_index.jsonl",
                    "sources/src-001.md",
                    "claim_ledger.md",
                },
                captured_paths,
            )

            def event_position(kind, label):
                return events.index((kind, label))

            for path, owner in (
                ("revisit_contract.json", "pointer"),
                ("reports/final.md", "report-read"),
                ("reports/final.md", "report-evaluate"),
                ("framing_contract.json", "framing"),
                ("frontier_registry.json", "registry"),
                ("evidence_ledger.md", "ledger"),
                ("claim_ledger.md", "artifact"),
            ):
                with self.subTest(path=path, owner=owner):
                    self.assertLess(
                        event_position("capture", path),
                        event_position("owner", owner),
                    )
            source_cache_positions = [
                index
                for index, event in enumerate(events)
                if event == ("owner", "source-cache")
            ]
            self.assertEqual(2, len(source_cache_positions))
            self.assertLess(
                event_position("capture", "sources_index.jsonl"),
                source_cache_positions[0],
            )
            self.assertLess(
                source_cache_positions[0],
                event_position("capture", "sources/src-001.md"),
            )
            self.assertLess(
                event_position("capture", "sources/src-001.md"),
                source_cache_positions[1],
            )

    def test_start_binds_source_index_and_excerpt_after_cycle_persistence(self):
        for target_name in ("sources_index.jsonl", "sources/src-001.md"):
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    drifted_bytes = target.read_bytes() + b"post-commit source drift\n"
                    cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
                    real_atomic_replace = cli_store._atomic_replace
                    injected = False

                    def replace_then_drift(path, payload):
                        nonlocal injected
                        real_atomic_replace(path, payload)
                        if Path(path).name == "RC-0001.json" and not injected:
                            injected = True
                            target.write_bytes(drifted_bytes)

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            cli_store,
                            "_atomic_replace",
                            side_effect=replace_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertFalse((workspace / "revisit_cycles" / "RC-0001.json").exists())
                    self.assertFalse((workspace / "revisit_cycles" / "RC-0001.md").exists())

    def test_source_evaluation_is_bound_to_the_snapshotted_raw_generation(self):
        for target_name in ("sources_index.jsonl", "sources/src-001.md"):
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    drifted_bytes = target.read_bytes() + b"evaluation drift\n"
                    real_evaluate_index = revisit_cycle_cli.evaluate_index
                    calls = 0

                    def evaluate_then_drift(*args, **kwargs):
                        nonlocal calls
                        evaluation = real_evaluate_index(*args, **kwargs)
                        calls += 1
                        if calls == 2:
                            target.write_bytes(drifted_bytes)
                        return evaluation

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            revisit_cycle_cli,
                            "evaluate_index",
                            side_effect=evaluate_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, calls)
                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_source_evaluations_must_agree_on_requested_record_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            original_excerpt = workspace / "sources" / "src-001.md"
            remapped_excerpt = workspace / "sources" / "src-001-remapped.md"
            remapped_excerpt.write_bytes(original_excerpt.read_bytes())
            before = snapshot_tree(workspace)
            real_evaluate_index = revisit_cycle_cli.evaluate_index
            calls = 0

            def evaluate_with_second_call_remap(*args, **kwargs):
                nonlocal calls
                evaluation = real_evaluate_index(*args, **kwargs)
                calls += 1
                if calls != 2:
                    return evaluation
                remapped_record = copy.deepcopy(evaluation.records[0])
                remapped_record["excerpt_path"] = "sources/src-001-remapped.md"
                return dataclasses.replace(
                    evaluation,
                    records=(remapped_record, *evaluation.records[1:]),
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_index",
                    side_effect=evaluate_with_second_call_remap,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "start",
                        "--intake-file",
                        str(request_path),
                    ]
                )

            self.assertEqual(2, calls)
            self.assertEqual(2, result, stderr.getvalue())
            self.assertIn(
                "source record changed during validation: src-001",
                stderr.getvalue(),
            )
            self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
            self.assertEqual(before, snapshot_tree(workspace))
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_start_refuses_to_rollback_over_third_party_cycle_pair_bytes(self):
        for authority_suffix in (".json", ".md"):
            with self.subTest(authority_suffix=authority_suffix):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    report_path = workspace / "reports" / "final.md"
                    drifted_report = report_path.read_bytes() + b"authority drift\n"
                    third_party_bytes = b"third-party cycle authority\n"
                    third_party_path = (
                        workspace / "revisit_cycles" / f"RC-0001{authority_suffix}"
                    )
                    cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
                    real_atomic_replace = cli_store._atomic_replace
                    injected = False

                    def replace_then_drift(path, payload):
                        nonlocal injected
                        real_atomic_replace(path, payload)
                        if Path(path).name == "RC-0001.json" and not injected:
                            injected = True
                            third_party_path.write_bytes(third_party_bytes)
                            report_path.write_bytes(drifted_report)

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            cli_store,
                            "_atomic_replace",
                            side_effect=replace_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertIn("rollback refused", stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE STARTED", stdout.getvalue())
                    self.assertEqual(third_party_bytes, third_party_path.read_bytes())
                    self.assertEqual(drifted_report, report_path.read_bytes())

    def test_start_rejects_active_ready_and_completed_unpublished_cycle_conflicts_without_writes(self):
        for status in ("active", "ready_for_report", "completed"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    first = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )
                    self.assertEqual(0, first.returncode, first.stderr)
                    if status != "active":
                        cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
                        previous = revisit_contract.load_cycle(workspace, "RC-0001")
                        if status == "completed":
                            transitioned = make_terminal_cycle_fixture(
                                previous,
                                "completed",
                                timestamp="2026-07-15T05:00:00Z",
                            )
                        else:
                            updated = copy.deepcopy(previous)
                            updated["status"] = status
                            transitioned = revisit_model.with_audit(
                                previous,
                                updated,
                                f"test-{status}",
                                ["RC-0001"],
                                "2026-07-15T05:00:00Z",
                            )
                        revisit_contract.persist_cycle(
                            workspace,
                            transitioned,
                            expected_sha256=hashlib.sha256(
                                cycle_path.read_bytes()
                            ).hexdigest(),
                        )
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    if status == "completed":
                        self.assertIn("completed-unpublished", result.stderr)
                    else:
                        self.assertIn(f"RC-0001 is {status}", result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))

    @staticmethod
    def rewrite_json_field(path, field, value):
        document = json.loads(path.read_text(encoding="utf-8"))
        document[field] = value
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class TestCanonicalAuthorityConsumers(unittest.TestCase):
    def test_load_persist_status_and_abort_reject_task4_drift(self):
        drifted = make_drifted_task4_cycle()
        pattern = "framing.snapshot.research_posture must be revisit"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            before = snapshot_tree(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, pattern
            ):
                revisit_contract.persist_cycle(
                    workspace, drifted, expected_sha256=None
                )
            self.assertEqual(before, snapshot_tree(workspace))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = make_revisit_start_workspace(root)
            cycle_path = (
                workspace
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.json"
            )
            cycle_path.write_bytes(
                revisit_contract.canonical_document_bytes(drifted)
            )
            before = snapshot_tree(workspace)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, pattern
            ):
                revisit_contract.load_cycle(workspace, "RC-0001")
            status = run_revisit_cycle_cli(workspace, "status", "--json")
            abort = run_revisit_cycle_cli(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                "Canonical authority drifted.",
            )

            self.assertEqual(2, status.returncode, status.stderr)
            self.assertIn(pattern, status.stderr)
            self.assertEqual(2, abort.returncode, abort.stderr)
            self.assertIn(pattern, abort.stderr)
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitHistoryValidation(unittest.TestCase):
    @staticmethod
    def initial_pointer():
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        return pointer

    @staticmethod
    def published_pointer(revision_number=3, cycle_number=2):
        pointer = revisit_contract.empty_pointer()
        current = make_revisit_revision()
        current.update(
            {
                "revision_id": f"REV-{revision_number:04d}",
                "cycle_id": f"RC-{cycle_number:04d}",
                "revision_of": f"REV-{revision_number - 1:04d}",
            }
        )
        pointer["current_revision"] = current
        return pointer

    def required_evaluator(self):
        evaluator = getattr(revisit_contract, "evaluate_history", None)
        self.assertTrue(callable(evaluator), "evaluate_history seam is missing")
        return evaluator

    def test_history_fact_is_pure_and_classifies_lower_equal_future_and_aborted(self):
        evaluator = self.required_evaluator()
        pointer = self.published_pointer()
        cycles = [
            make_history_cycle(4, 5, "completed"),
            make_history_cycle(2, 3, "completed"),
            make_history_cycle(3, 4, "aborted"),
            make_history_cycle(1, 2, "completed"),
        ]
        pointer_before = copy.deepcopy(pointer)
        cycles_before = copy.deepcopy(cycles)

        fact = evaluator(pointer, cycles)

        self.assertEqual(3, fact.current_revision_number)
        self.assertEqual(
            ("RC-0001", "RC-0002", "RC-0003", "RC-0004"),
            fact.ordered_cycle_ids,
        )
        self.assertEqual(4, fact.max_cycle_number)
        self.assertEqual(5, fact.max_revision_number)
        self.assertEqual((), fact.nonterminal_cycle_ids)
        self.assertEqual(("RC-0004",), fact.completed_unpublished_cycle_ids)
        self.assertEqual((), fact.issues)
        self.assertEqual(pointer_before, pointer)
        self.assertEqual(cycles_before, cycles)

        initial = evaluator(self.initial_pointer(), [])
        self.assertEqual(1, initial.current_revision_number)
        self.assertEqual((), initial.issues)

    def test_nonempty_history_requires_a_current_revision_for_every_status(self):
        evaluator = self.required_evaluator()
        for status in ("active", "ready_for_report", "aborted", "completed"):
            with self.subTest(status=status):
                pointer = revisit_contract.empty_pointer()
                cycle = make_history_cycle(1, 2, status)
                pointer_before = copy.deepcopy(pointer)
                cycle_before = copy.deepcopy(cycle)

                fact = evaluator(pointer, [cycle])

                self.assertEqual(
                    ["history_without_current_revision"],
                    [issue.code for issue in fact.issues],
                )
                self.assertEqual((), fact.completed_unpublished_cycle_ids)
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "cycle history exists without a current revision",
                ):
                    fact.require_valid()
                self.assertEqual(pointer_before, pointer)
                self.assertEqual(cycle_before, cycle)

    def test_history_validator_and_allocator_reject_every_global_conflict(self):
        invalid_histories = (
            (
                "duplicate candidate",
                self.initial_pointer(),
                [
                    make_history_cycle(1, 2),
                    make_history_cycle(2, 2),
                ],
                "duplicate_candidate_revision",
                "candidate revision REV-0002 is reserved by multiple cycles",
            ),
            (
                "candidate order",
                self.initial_pointer(),
                [
                    make_history_cycle(1, 3),
                    make_history_cycle(2, 2),
                ],
                "candidate_revision_order",
                "candidate revisions must increase with cycle allocation order",
            ),
            (
                "multiple nonterminal",
                self.initial_pointer(),
                [
                    make_history_cycle(1, 2, "active"),
                    make_history_cycle(2, 3, "ready_for_report"),
                ],
                "multiple_nonterminal_cycles",
                "more than one active or ready cycle",
            ),
            (
                "nonterminal and future",
                self.initial_pointer(),
                [
                    make_history_cycle(1, 2, "active"),
                    make_history_cycle(2, 3, "completed"),
                ],
                "nonterminal_with_unpublished",
                "active or ready cycle cannot coexist with completed-unpublished",
            ),
            (
                "multiple future",
                self.initial_pointer(),
                [
                    make_history_cycle(1, 2, "completed"),
                    make_history_cycle(2, 3, "completed"),
                ],
                "multiple_unpublished_cycles",
                "more than one completed-unpublished cycle",
            ),
            (
                "equal current conflict",
                self.published_pointer(revision_number=2, cycle_number=2),
                [make_history_cycle(1, 2, "completed")],
                "current_candidate_cycle_conflict",
                "completed current candidate conflicts with pointer cycle lineage",
            ),
            (
                "missing current lineage",
                self.published_pointer(revision_number=2, cycle_number=1),
                [make_history_cycle(1, 2, "aborted")],
                "current_lineage_missing",
                "current pointer has no matching completed cycle",
            ),
        )
        evaluator = self.required_evaluator()
        for label, pointer, cycles, code, pattern in invalid_histories:
            with self.subTest(case=label):
                fact = evaluator(pointer, cycles)
                self.assertTrue(fact.issues, "global conflict was accepted")
                self.assertEqual(code, fact.issues[0].code)
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, pattern
                ):
                    revisit_contract.allocate_cycle_and_revision_ids(
                        pointer, cycles
                    )

    def test_start_rejects_shared_duplicate_reservation_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            for cycle in (
                make_history_cycle(1, 2, "aborted"),
                make_history_cycle(2, 2, "aborted"),
            ):
                revisit_contract.persist_cycle(
                    workspace, cycle, expected_sha256=None
                )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn(
                "candidate revision REV-0002 is reserved by multiple cycles",
                result.stderr,
            )
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitCycleAllocation(unittest.TestCase):
    def test_allocation_uses_maximum_reserved_ids_without_filling_gaps(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"].update(
            {
                "revision_id": "REV-0003",
                "cycle_id": "RC-0003",
                "revision_of": "REV-0002",
            }
        )

        aborted = make_history_cycle(1, 2, "aborted")
        completed = make_history_cycle(4, 7, "completed")
        published = make_history_cycle(3, 3, "completed")

        original_pointer = copy.deepcopy(pointer)
        original_cycles = copy.deepcopy([aborted, published, completed])
        allocate = getattr(
            revisit_contract, "allocate_cycle_and_revision_ids", None
        )
        self.assertTrue(callable(allocate), "allocation helper is missing")

        self.assertEqual(
            ("RC-0005", "REV-0008"),
            allocate(pointer, [aborted, published, completed]),
        )
        self.assertEqual(original_pointer, pointer)
        self.assertEqual(original_cycles, [aborted, published, completed])

    def test_allocation_rejects_cycle_or_revision_overflow(self):
        allocate = getattr(
            revisit_contract, "allocate_cycle_and_revision_ids", None
        )
        self.assertTrue(callable(allocate), "allocation helper is missing")
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()

        last_cycle = make_minimal_cycle(cycle_id="RC-9999")
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "cycle ID space is exhausted"
        ):
            allocate(pointer, [last_cycle])

        pointer["current_revision"].update(
            {
                "revision_id": "REV-9999",
                "cycle_id": "RC-9998",
                "revision_of": "REV-9998",
            }
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "revision ID space is exhausted"
        ):
            allocate(pointer, [make_history_cycle(9998, 9999, "completed")])


class TestRevisitCycleStatusCli(unittest.TestCase):
    @staticmethod
    def make_status_workspace(root, condition):
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "state.json").write_text(
            json.dumps(
                {
                    "subject": "TEST",
                    "mode": "ticker",
                    "current_stage": "stage_5",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        report_payload = complete_ticker_report_bytes()
        report_path = workspace / "reports" / "initial.md"
        report_path.parent.mkdir()
        report_path.write_bytes(report_payload)
        pointer = revisit_contract.empty_pointer()
        cycle = None

        if condition != "empty":
            pointer["current_revision"] = make_initial_revision()
        if condition in {
            "active",
            "ready",
            "aborted",
            "published",
            "completed-unpublished",
        }:
            cycle = make_minimal_cycle()
        if condition == "ready":
            cycle["status"] = "ready_for_report"
        elif condition == "aborted":
            cycle = make_terminal_cycle_fixture(
                cycle,
                "aborted",
                timestamp="2026-07-15T03:00:00Z",
                abort_reason="The selected proof became unavailable.",
            )
        elif condition in {"published", "completed-unpublished"}:
            candidate_report_path = workspace / "reports" / "STATUS_REV-0002.md"
            candidate_report_path.write_bytes(report_payload)
            cycle = make_terminal_cycle_fixture(
                cycle,
                "completed",
                timestamp="2026-07-15T03:00:00Z",
                report_path="reports/STATUS_REV-0002.md",
                report_sha256=hashlib.sha256(report_payload).hexdigest(),
            )
        if condition == "published":
            pointer["current_revision"] = make_revisit_revision()
            pointer["current_revision"]["report_path"] = (
                "reports/STATUS_REV-0002.md"
            )
        if pointer["current_revision"] is not None:
            pointer["current_revision"]["report_sha256"] = hashlib.sha256(
                report_payload
            ).hexdigest()
        if cycle is not None and condition not in {
            "aborted",
            "published",
            "completed-unpublished",
        }:
            attach_valid_audit(cycle)

        (workspace / revisit_contract.POINTER_FILENAME).write_bytes(
            revisit_contract.canonical_document_bytes(pointer)
        )
        if cycle is not None:
            revisit_contract.persist_cycle(
                workspace, cycle, expected_sha256=None
            )
        return workspace

    def test_status_is_deterministic_read_only_and_reports_all_operational_conditions(self):
        cases = (
            (
                "empty",
                None,
                [],
                "register-current --report REPORT --action-class ACTION_CLASS",
            ),
            (
                "registered",
                "REV-0001",
                [],
                "start --intake-file REQUEST",
            ),
            (
                "active",
                "REV-0001",
                ["active"],
                "abort RC-0001 --reason TEXT",
            ),
            (
                "ready",
                "REV-0001",
                ["ready_for_report"],
                "abort RC-0001 --reason TEXT",
            ),
            (
                "aborted",
                "REV-0001",
                ["aborted"],
                "start --intake-file REQUEST",
            ),
            (
                "published",
                "REV-0002",
                ["completed"],
                "start --intake-file REQUEST",
            ),
            (
                "completed-unpublished",
                "REV-0001",
                ["completed-unpublished"],
                "publish RC-0001",
            ),
        )
        for condition, revision_id, statuses, next_command in cases:
            with self.subTest(condition=condition):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_status_workspace(
                        Path(temp_dir), condition
                    )
                    before = snapshot_tree(workspace)

                    first_json = run_revisit_cycle_cli(
                        workspace, "status", "--json"
                    )
                    second_json = run_revisit_cycle_cli(
                        workspace, "status", "--json"
                    )
                    text_result = run_revisit_cycle_cli(workspace, "status")

                    self.assertEqual(0, first_json.returncode, first_json.stderr)
                    self.assertEqual(0, second_json.returncode, second_json.stderr)
                    self.assertEqual(0, text_result.returncode, text_result.stderr)
                    self.assertEqual(first_json.stdout, second_json.stdout)
                    self.assertTrue(first_json.stdout.endswith("\n"))
                    summary = json.loads(first_json.stdout)
                    self.assertEqual(
                        {
                            "schema_version",
                            "mode",
                            "current_revision",
                            "cycles",
                            "issues",
                            "next_legal_command",
                        },
                        set(summary),
                    )
                    self.assertEqual(1, summary["schema_version"])
                    self.assertEqual("ticker", summary["mode"])
                    self.assertEqual([], summary["issues"])
                    self.assertEqual(next_command, summary["next_legal_command"])
                    self.assertEqual(
                        revision_id,
                        (
                            summary["current_revision"]["revision_id"]
                            if summary["current_revision"] is not None
                            else None
                        ),
                    )
                    self.assertEqual(
                        statuses,
                        [cycle["status"] for cycle in summary["cycles"]],
                    )
                    for cycle in summary["cycles"]:
                        self.assertEqual(
                            {
                                "cycle_id",
                                "candidate_revision_id",
                                "status",
                                "created_at",
                                "completed_at",
                                "aborted_at",
                                "abort_reason",
                            },
                            set(cycle),
                        )
                    self.assertIn(
                        f"NEXT LEGAL COMMAND: {next_command}",
                        text_result.stdout,
                    )
                    for status in statuses:
                        self.assertIn(f"STATUS: {status}", text_result.stdout)
                    self.assertEqual(before, snapshot_tree(workspace))

                    if condition == "completed-unpublished":
                        persisted = json.loads(
                            (
                                workspace
                                / "revisit_cycles"
                                / "RC-0001.json"
                            ).read_text(encoding="utf-8")
                        )
                        self.assertEqual("completed", persisted["status"])
                        self.assertNotIn(
                            "completed-unpublished",
                            (workspace / "revisit_cycles" / "RC-0001.json")
                            .read_text(encoding="utf-8"),
                        )

    def test_status_reports_history_without_current_revision_and_no_next_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "empty")
            revisit_contract.persist_cycle(
                workspace,
                make_history_cycle(1, 2, "completed"),
                expected_sha256=None,
            )
            before = snapshot_tree(workspace)

            json_result = run_revisit_cycle_cli(workspace, "status", "--json")
            text_result = run_revisit_cycle_cli(workspace, "status")

            self.assertEqual(0, json_result.returncode, json_result.stderr)
            self.assertEqual(0, text_result.returncode, text_result.stderr)
            summary = json.loads(json_result.stdout)
            self.assertTrue(
                any(
                    "history_without_current_revision" in issue
                    for issue in summary["issues"]
                ),
                summary,
            )
            self.assertEqual("completed", summary["cycles"][0]["status"])
            self.assertIsNone(summary["next_legal_command"])
            self.assertIn(
                "ISSUE: history_without_current_revision",
                text_result.stdout,
            )
            self.assertIn("NEXT LEGAL COMMAND: none", text_result.stdout)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_status_optional_cycle_filters_history_and_rejects_unknown_id_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "aborted")
            before = snapshot_tree(workspace)

            selected = run_revisit_cycle_cli(
                workspace, "status", "RC-0001", "--json"
            )
            missing = run_revisit_cycle_cli(
                workspace, "status", "RC-9999", "--json"
            )

            self.assertEqual(0, selected.returncode, selected.stderr)
            self.assertEqual(
                ["RC-0001"],
                [item["cycle_id"] for item in json.loads(selected.stdout)["cycles"]],
            )
            self.assertEqual(2, missing.returncode, missing.stderr)
            self.assertIn("cycle authority is missing: RC-9999", missing.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_status_rejects_sector_mode_before_reading_revisit_authority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "registered")
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["mode"] = "sector"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (workspace / revisit_contract.POINTER_FILENAME).write_text(
                "{broken", encoding="utf-8"
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(workspace, "status", "--json")

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn(
                "status is unavailable for Sector workspaces",
                result.stderr,
            )
            self.assertNotIn("malformed JSON", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_status_reports_current_report_drift_and_withholds_next_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "registered")
            report_path = workspace / "reports" / "initial.md"
            report_path.write_bytes(report_path.read_bytes() + b"drift\n")
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(workspace, "status", "--json")
            text_result = run_revisit_cycle_cli(workspace, "status")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(0, text_result.returncode, text_result.stderr)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["issues"])
            self.assertIn("current_report_invalid", summary["issues"][0])
            self.assertIsNone(summary["next_legal_command"])
            self.assertNotIn("start --intake-file REQUEST", result.stdout)
            self.assertIn("ISSUE: current_report_invalid", text_result.stdout)
            self.assertIn("NEXT LEGAL COMMAND: none", text_result.stdout)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_status_reports_global_history_conflicts_without_writes(self):
        cases = (
            (
                "duplicate reservation",
                (
                    make_history_cycle(1, 2, "aborted"),
                    make_history_cycle(2, 2, "aborted"),
                ),
                None,
                "duplicate_candidate_revision",
            ),
            (
                "multiple active",
                (
                    make_history_cycle(1, 2, "active"),
                    make_history_cycle(2, 3, "ready_for_report"),
                ),
                None,
                "multiple_nonterminal_cycles",
            ),
            (
                "active and unpublished",
                (
                    make_history_cycle(1, 2, "active"),
                    make_history_cycle(2, 3, "completed"),
                ),
                None,
                "nonterminal_with_unpublished",
            ),
            (
                "bad current lineage",
                (make_history_cycle(1, 2, "completed"),),
                {
                    "revision_id": "REV-0002",
                    "cycle_id": "RC-0002",
                    "revision_of": "REV-0001",
                },
                "current_candidate_cycle_conflict",
            ),
        )
        for label, cycles, pointer_update, expected_code in cases:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_status_workspace(
                        Path(temp_dir), "registered"
                    )
                    for cycle in cycles:
                        revisit_contract.persist_cycle(
                            workspace, cycle, expected_sha256=None
                        )
                    if pointer_update is not None:
                        pointer_path = workspace / revisit_contract.POINTER_FILENAME
                        pointer = revisit_contract.load_pointer(workspace)
                        pointer["current_revision"].update(pointer_update)
                        pointer_path.write_bytes(
                            revisit_contract.canonical_document_bytes(pointer)
                        )
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace, "status", "--json"
                    )

                    self.assertEqual(0, result.returncode, result.stderr)
                    summary = json.loads(result.stdout)
                    self.assertTrue(
                        any(expected_code in issue for issue in summary["issues"]),
                        summary,
                    )
                    self.assertIsNone(summary["next_legal_command"])
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_status_filter_changes_display_only_and_clean_history_stays_actionable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "registered")
            for cycle in (
                make_history_cycle(1, 2, "aborted"),
                make_history_cycle(2, 2, "aborted"),
            ):
                revisit_contract.persist_cycle(
                    workspace, cycle, expected_sha256=None
                )
            before = snapshot_tree(workspace)

            filtered = run_revisit_cycle_cli(
                workspace, "status", "RC-0001", "--json"
            )

            self.assertEqual(0, filtered.returncode, filtered.stderr)
            filtered_summary = json.loads(filtered.stdout)
            self.assertEqual(
                ["RC-0001"],
                [cycle["cycle_id"] for cycle in filtered_summary["cycles"]],
            )
            self.assertTrue(
                any(
                    "duplicate_candidate_revision" in issue
                    for issue in filtered_summary["issues"]
                )
            )
            self.assertIsNone(filtered_summary["next_legal_command"])
            self.assertEqual(before, snapshot_tree(workspace))

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "published")
            before = snapshot_tree(workspace)

            clean = run_revisit_cycle_cli(workspace, "status", "--json")

            self.assertEqual(0, clean.returncode, clean.stderr)
            clean_summary = json.loads(clean.stdout)
            self.assertEqual([], clean_summary["issues"])
            self.assertEqual(
                "start --intake-file REQUEST",
                clean_summary["next_legal_command"],
            )
            self.assertEqual(before, snapshot_tree(workspace))

    def test_lower_completed_revision_is_published_history_and_does_not_block_later_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["current_revision"].update(
                {
                    "revision_id": "REV-0003",
                    "cycle_id": "RC-0002",
                    "revision_of": "REV-0002",
                }
            )
            pointer_path.write_bytes(
                revisit_contract.canonical_document_bytes(pointer)
            )
            historical_bytes = {}
            for cycle_id, candidate_revision_id in (
                ("RC-0001", "REV-0002"),
                ("RC-0002", "REV-0003"),
            ):
                cycle = make_minimal_cycle(
                    cycle_id=cycle_id,
                    candidate_revision_id=candidate_revision_id,
                )
                cycle = make_terminal_cycle_fixture(
                    cycle,
                    "completed",
                    timestamp="2026-07-15T03:00:00Z",
                )
                revisit_contract.persist_cycle(
                    workspace, cycle, expected_sha256=None
                )
                historical_bytes[cycle_id] = (
                    (workspace / "revisit_cycles" / f"{cycle_id}.json").read_bytes(),
                    (workspace / "revisit_cycles" / f"{cycle_id}.md").read_bytes(),
                )
            pointer_before = pointer_path.read_bytes()

            status_result = run_revisit_cycle_cli(
                workspace, "status", "--json"
            )

            self.assertEqual(0, status_result.returncode, status_result.stderr)
            summary = json.loads(status_result.stdout)
            self.assertEqual(
                ["completed", "completed"],
                [item["status"] for item in summary["cycles"]],
            )
            self.assertEqual(
                "start --intake-file REQUEST", summary["next_legal_command"]
            )

            start_result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, start_result.returncode, start_result.stderr)
            third = revisit_contract.load_cycle(workspace, "RC-0003")
            self.assertEqual("REV-0004", third["candidate_revision_id"])
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            for cycle_id, (expected_json, expected_mirror) in historical_bytes.items():
                self.assertEqual(
                    expected_json,
                    (workspace / "revisit_cycles" / f"{cycle_id}.json").read_bytes(),
                )
                self.assertEqual(
                    expected_mirror,
                    (workspace / "revisit_cycles" / f"{cycle_id}.md").read_bytes(),
                )

    def test_status_prints_utf8_under_legacy_ascii_process_encoding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "registered")
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["current_revision"]["report_path"] = "reports/报告.md"
            pointer_path.write_bytes(
                revisit_contract.canonical_document_bytes(pointer)
            )
            before = snapshot_tree(workspace)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "ascii"
            env["LC_ALL"] = "C"

            result = run_revisit_cycle_cli(workspace, "status", env=env)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("reports/报告.md", result.stdout)
            self.assertNotIn("UnicodeEncodeError", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitCycleAbortCli(unittest.TestCase):
    def start_cycle(self, root):
        workspace, request_path = make_revisit_start_workspace(root)
        result = run_revisit_cycle_cli(
            workspace,
            "start",
            "--intake-file",
            str(request_path),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return workspace, request_path

    def transition_cycle_for_test(self, workspace, *, status):
        cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
        previous = revisit_contract.load_cycle(workspace, "RC-0001")
        if status == "completed":
            transitioned = make_terminal_cycle_fixture(
                previous,
                "completed",
                timestamp="2026-07-15T04:00:00Z",
            )
        else:
            updated = copy.deepcopy(previous)
            updated["status"] = status
            transitioned = revisit_model.with_audit(
                previous,
                updated,
                f"test-{status}",
                ["RC-0001"],
                "2026-07-15T04:00:00Z",
            )
        revisit_contract.persist_cycle(
            workspace,
            transitioned,
            expected_sha256=hashlib.sha256(cycle_path.read_bytes()).hexdigest(),
        )

    def test_abort_captures_pointer_and_report_before_owner_reads(self):
        read_generation = getattr(
            revisit_cycle_cli,
            "_read_authority_generation",
            None,
        )
        self.assertTrue(
            callable(read_generation),
            "authority generation read seam is missing",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = self.start_cycle(Path(temp_dir))
            captured_paths = []
            pointer_events = []
            real_load_pointer = revisit_cycle_cli.load_pointer

            def record_generation(snapshot_workspace, path):
                relative = Path(path).relative_to(snapshot_workspace).as_posix()
                captured_paths.append(relative)
                if relative == revisit_contract.POINTER_FILENAME:
                    pointer_events.append("capture")
                return read_generation(snapshot_workspace, path)

            def record_pointer_load(*args, **kwargs):
                pointer_events.append("load")
                return real_load_pointer(*args, **kwargs)

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_read_authority_generation",
                    side_effect=record_generation,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "load_pointer",
                    side_effect=record_pointer_load,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", io.StringIO()),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "abort",
                        "RC-0001",
                        "--reason",
                        "The prepared authority coverage test stopped this cycle.",
                    ]
                )

            self.assertEqual(0, result)
            self.assertEqual(
                {
                    "revisit_contract.json",
                    "reports/final.md",
                },
                set(captured_paths),
            )
            self.assertEqual(["capture", "load"], pointer_events)

    def test_abort_accepts_active_and_ready_with_copy_on_write_audit(self):
        for starting_status in ("active", "ready_for_report"):
            with self.subTest(starting_status=starting_status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, request_path = self.start_cycle(Path(temp_dir))
                    if starting_status == "ready_for_report":
                        self.transition_cycle_for_test(
                            workspace, status="ready_for_report"
                        )
                    cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
                    mirror_path = workspace / "revisit_cycles" / "RC-0001.md"
                    previous = revisit_contract.load_cycle(workspace, "RC-0001")
                    pointer_before = (
                        workspace / revisit_contract.POINTER_FILENAME
                    ).read_bytes()
                    request_before = request_path.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        "The required primary proof became unavailable.",
                    )

                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        "REVISIT CYCLE ABORTED: RC-0001\n", result.stdout
                    )
                    aborted = revisit_contract.load_cycle(workspace, "RC-0001")
                    self.assertEqual("aborted", aborted["status"])
                    self.assertRegex(
                        aborted["aborted_at"],
                        r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
                    )
                    self.assertEqual(
                        "The required primary proof became unavailable.",
                        aborted["abort_reason"],
                    )
                    self.assertEqual(
                        previous["audit"],
                        aborted["audit"][: len(previous["audit"])],
                    )
                    self.assertEqual("abort", aborted["audit"][-1]["command"])
                    self.assertEqual(
                        ["RC-0001"], aborted["audit"][-1]["affected_ids"]
                    )
                    self.assertEqual(
                        previous["audit"][-1]["post_state_sha256"],
                        aborted["audit"][-1]["pre_state_sha256"],
                    )
                    self.assertEqual(
                        revisit_contract.cycle_state_sha256(aborted),
                        aborted["audit"][-1]["post_state_sha256"],
                    )
                    mirror = mirror_path.read_text(encoding="utf-8")
                    self.assertIn("aborted", mirror)
                    self.assertIn(
                        "The required primary proof became unavailable.", mirror
                    )
                    self.assertTrue(cycle_path.is_file())
                    self.assertTrue(mirror_path.is_file())
                    self.assertEqual(
                        pointer_before,
                        (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
                    )
                    self.assertEqual(request_before, request_path.read_bytes())

    def test_abort_rejects_empty_reason_and_terminal_cycles_without_writes(self):
        reason_cases = ("", "   ", "bad\nreason")
        for reason in reason_cases:
            with self.subTest(reason=repr(reason)):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, _ = self.start_cycle(Path(temp_dir))
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        reason,
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn("abort reason must be non-empty", result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))

        for terminal_status in ("completed", "aborted"):
            with self.subTest(terminal_status=terminal_status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, _ = self.start_cycle(Path(temp_dir))
                    if terminal_status == "completed":
                        self.transition_cycle_for_test(
                            workspace, status="completed"
                        )
                    else:
                        first_abort = run_revisit_cycle_cli(
                            workspace,
                            "abort",
                            "RC-0001",
                            "--reason",
                            "First explicit abort.",
                        )
                        self.assertEqual(0, first_abort.returncode, first_abort.stderr)
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        "Attempted terminal rewrite.",
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(
                        f"cannot abort cycle RC-0001 with status {terminal_status}",
                        result.stderr,
                    )
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_abort_restores_exact_prior_pair_when_live_authority_drifts_after_commit(self):
        for target_name in ("revisit_contract.json", "reports/final.md"):
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, _ = self.start_cycle(Path(temp_dir))
                    json_path = workspace / "revisit_cycles" / "RC-0001.json"
                    markdown_path = workspace / "revisit_cycles" / "RC-0001.md"
                    prior_json = json_path.read_bytes()
                    prior_markdown = markdown_path.read_bytes()
                    target = workspace / target_name
                    drifted_bytes = target.read_bytes() + b"abort authority drift\n"
                    cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
                    real_atomic_replace = cli_store._atomic_replace
                    injected = False

                    def replace_then_drift(path, payload):
                        nonlocal injected
                        real_atomic_replace(path, payload)
                        if Path(path).name == "RC-0001.json" and not injected:
                            injected = True
                            target.write_bytes(drifted_bytes)

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(
                            cli_store,
                            "_atomic_replace",
                            side_effect=replace_then_drift,
                        ),
                        mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                        mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "abort",
                                "RC-0001",
                                "--reason",
                                "Abort with a drifting authority.",
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertNotIn("REVISIT CYCLE ABORTED", stdout.getvalue())
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertEqual(prior_json, json_path.read_bytes())
                    self.assertEqual(prior_markdown, markdown_path.read_bytes())

    def test_aborted_cycle_reserves_cycle_and_revision_ids_without_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, request_path = self.start_cycle(Path(temp_dir))
            pointer_before = (
                workspace / revisit_contract.POINTER_FILENAME
            ).read_bytes()
            first_abort = run_revisit_cycle_cli(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                "First cycle stopped explicitly.",
            )
            self.assertEqual(0, first_abort.returncode, first_abort.stderr)
            first_json = (workspace / "revisit_cycles" / "RC-0001.json").read_bytes()
            first_mirror = (workspace / "revisit_cycles" / "RC-0001.md").read_bytes()

            second_start = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, second_start.returncode, second_start.stderr)
            second = revisit_contract.load_cycle(workspace, "RC-0002")
            self.assertEqual("RC-0002", second["cycle_id"])
            self.assertEqual("REV-0003", second["candidate_revision_id"])
            self.assertEqual(
                ["RC-0002-TRG-01"],
                [item["trigger_id"] for item in second["intake"]["triggers"]],
            )
            self.assertEqual(
                first_json,
                (workspace / "revisit_cycles" / "RC-0001.json").read_bytes(),
            )
            self.assertEqual(
                first_mirror,
                (workspace / "revisit_cycles" / "RC-0001.md").read_bytes(),
            )
            self.assertEqual(
                pointer_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )
            self.assertEqual(
                {
                    "RC-0001.json",
                    "RC-0001.md",
                    "RC-0002.json",
                    "RC-0002.md",
                },
                {path.name for path in (workspace / "revisit_cycles").iterdir()},
            )


class TestRevisitFrontierBindingMutation(unittest.TestCase):
    def assert_bind_fails_without_writes(
        self,
        workspace: Path,
        cycle_id: str,
        *,
        frontier_id: str,
        action: str,
        claim_id: str = "RC-0001-CL-01",
        error_pattern: str,
    ) -> None:
        before = snapshot_tree(workspace)
        result = run_revisit_cycle_cli(
            workspace,
            "bind-frontier",
            cycle_id,
            "--frontier",
            frontier_id,
            "--action",
            action,
            "--claim",
            claim_id,
            "--expected-evidence",
            "Current qualification timing and counter-evidence.",
        )
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertRegex(result.stderr, error_pattern)
        self.assertEqual(before, snapshot_tree(workspace))

    def test_bind_rejects_first_post_boundary_loop_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            with (workspace / "evidence_ledger.md").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(
                    "## Loop 8: F1 - Qualification timing\n\n"
                    "Cycle-relative evidence has already started.\n"
                )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "bind-frontier",
                cycle_id,
                "--frontier",
                "F1",
                "--action",
                "reactivated",
                "--claim",
                f"{cycle_id}-CL-01",
                "--expected-evidence",
                "Current qualification timing and counter-evidence.",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertRegex(result.stderr, r"post-boundary loop|before new loops")
            self.assertEqual(before, snapshot_tree(workspace))

    def test_bind_persists_exact_legal_reactivated_snapshot_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            registry_path = workspace / "frontier_registry.json"
            registry_before = registry_path.read_bytes()
            cycle_before = revisit_contract.load_cycle(workspace, cycle_id)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-14T11:00:00Z",
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "bind-frontier",
                        cycle_id,
                        "--frontier",
                        "F1",
                        "--action",
                        "reactivated",
                        "--claim",
                        f"{cycle_id}-CL-01",
                        "--expected-evidence",
                        "Current qualification timing and counter-evidence.",
                    ]
                )

            self.assertEqual(0, result, stderr.getvalue())
            self.assertEqual(registry_before, registry_path.read_bytes())
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                [
                    {
                        "frontier_id": "F1",
                        "action": "reactivated",
                        "claim_ids": ["RC-0001-CL-01"],
                        "expected_evidence": (
                            "Current qualification timing and counter-evidence."
                        ),
                        "baseline_loop_count": 3,
                        "baseline_review_count": 1,
                        "registry_sha256": hashlib.sha256(
                            registry_before
                        ).hexdigest(),
                        "bound_at": "2026-07-14T11:00:00Z",
                    }
                ],
                cycle["frontier_bindings"],
            )
            self.assertEqual(
                len(cycle_before["audit"]) + 1,
                len(cycle["audit"]),
            )
            self.assertEqual("bind-frontier", cycle["audit"][-1]["command"])
            self.assertEqual(
                ["F1", "RC-0001-CL-01"],
                cycle["audit"][-1]["affected_ids"],
            )
            self.assertIn("FRONTIER BOUND: F1", stdout.getvalue())

    def test_bind_persists_exact_legal_added_snapshot_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            frontier_id = add_task6_frontier(workspace)
            registry_path = workspace / "frontier_registry.json"
            registry_before = registry_path.read_bytes()
            cycle_before = revisit_contract.load_cycle(workspace, cycle_id)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-14T11:00:00Z",
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "bind-frontier",
                        cycle_id,
                        "--frontier",
                        frontier_id,
                        "--action",
                        "added",
                        "--claim",
                        f"{cycle_id}-CL-01",
                        "--expected-evidence",
                        "Current qualification timing and counter-evidence.",
                    ]
                )

            self.assertEqual(0, result, stderr.getvalue())
            self.assertEqual(registry_before, registry_path.read_bytes())
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                {
                    "frontier_id": frontier_id,
                    "action": "added",
                    "claim_ids": ["RC-0001-CL-01"],
                    "expected_evidence": (
                        "Current qualification timing and counter-evidence."
                    ),
                    "baseline_loop_count": 0,
                    "baseline_review_count": 0,
                    "registry_sha256": hashlib.sha256(
                        registry_before
                    ).hexdigest(),
                    "bound_at": "2026-07-14T11:00:00Z",
                },
                cycle["frontier_bindings"][0],
            )
            self.assertEqual(
                len(cycle_before["audit"]) + 1,
                len(cycle["audit"]),
            )
            self.assertEqual("bind-frontier", cycle["audit"][-1]["command"])

    def test_bind_rejects_unknown_retired_and_illegal_lifecycle_frontiers(self):
        cases = (
            (
                "unknown",
                lambda workspace: "F99",
                "added",
                r"unknown frontier id: F99",
            ),
            (
                "retired added",
                lambda workspace: add_task6_frontier(
                    workspace, initial_status="Active", retire=True
                ),
                "added",
                r"must be New or Active",
            ),
            (
                "reactivated previous state",
                self._make_wrong_previous_reactivated,
                "reactivated",
                # Task 6.2 strict registry validation rejects this at load time:
                # the Continued review decision has no matching lifecycle
                # transition, surfacing as the raw LifecycleError on the CLI
                # before the revisit binding check runs.
                r"has no matching lifecycle transition",
            ),
            (
                "reactivated missing post-cycle Active",
                self._make_old_active_reactivated,
                "reactivated",
                # Task 6.2 strict registry validation rejects this at load time:
                # status 'Active' no longer matches the final lifecycle 'to'
                # after the pop, surfacing as the raw LifecycleError on the CLI
                # before the revisit binding check runs.
                r"status 'Active' must equal final lifecycle to 'Continued'",
            ),
            (
                "added before boundary",
                lambda workspace: add_task6_frontier(
                    workspace, proposed_at_loop=7
                ),
                "added",
                r"proposed_at_loop must be greater",
            ),
        )
        for label, prepare, action, error_pattern in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    frontier_id = prepare(workspace)
                    self.assert_bind_fails_without_writes(
                        workspace,
                        cycle_id,
                        frontier_id=frontier_id,
                        action=action,
                        error_pattern=error_pattern,
                    )

    @staticmethod
    def _make_wrong_previous_reactivated(workspace: Path) -> str:
        registry_path = workspace / "frontier_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["frontiers"][0]["lifecycle"][-2]["to"] = "New"
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return "F1"

    @staticmethod
    def _make_old_active_reactivated(workspace: Path) -> str:
        registry_path = workspace / "frontier_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["frontiers"][0]["lifecycle"].pop()
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return "F1"

    def test_bind_rejects_duplicate_empty_unknown_and_derived_backfill_without_writes(self):
        for claim_id, error_pattern in (
            ("", r"claim_ids must match RC-NNNN"),
            ("RC-0001-CL-99", r"known same-cycle claims"),
        ):
            with self.subTest(claim_id=claim_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    self.assert_bind_fails_without_writes(
                        workspace,
                        cycle_id,
                        frontier_id="F1",
                        action="reactivated",
                        claim_id=claim_id,
                        error_pattern=error_pattern,
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            first = run_revisit_cycle_cli(
                workspace,
                "bind-frontier",
                cycle_id,
                "--frontier",
                "F1",
                "--action",
                "reactivated",
                "--claim",
                "RC-0001-CL-01",
                "--expected-evidence",
                "Current qualification timing and counter-evidence.",
            )
            self.assertEqual(0, first.returncode, first.stderr)
            self.assert_bind_fails_without_writes(
                workspace,
                cycle_id,
                frontier_id="F1",
                action="reactivated",
                error_pattern=r"duplicate frontier_id",
            )

            previous = revisit_contract.load_cycle(workspace, cycle_id)
            derived_request = {
                "origin": "split_child",
                "statement": "Customer A qualifies independently.",
                "derived_from": "RC-0001-CL-01",
                "accepted_from": None,
                "acceptance_rationale": "The inherited claim combined customers.",
            }
            proposed = revisit_contract.add_derived_claim(
                previous, derived_request
            )
            updated = revisit_model.with_audit(
                previous,
                proposed,
                "add-derived-claim",
                ["RC-0001-DC-01"],
                "2026-07-14T12:00:00Z",
            )
            revisit_contract.persist_cycle(
                workspace,
                updated,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / "RC-0001.json"
                ),
            )
            self.assert_bind_fails_without_writes(
                workspace,
                cycle_id,
                frontier_id="F1",
                action="reactivated",
                claim_id="RC-0001-DC-01",
                error_pattern=r"duplicate frontier_id",
            )

    def test_bind_rejects_registry_generation_drift_without_cycle_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            registry_path = workspace / "frontier_registry.json"
            cycle_json = workspace / "revisit_cycles" / f"{cycle_id}.json"
            cycle_md = workspace / "revisit_cycles" / f"{cycle_id}.md"
            json_before = cycle_json.read_bytes()
            md_before = cycle_md.read_bytes()
            real_bind = revisit_cycle_cli.bind_frontier

            def bind_then_drift(cycle, binding):
                proposed = real_bind(cycle, binding)
                registry_path.write_bytes(registry_path.read_bytes() + b" \n")
                return proposed

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "bind_frontier",
                    side_effect=bind_then_drift,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "bind-frontier",
                        cycle_id,
                        "--frontier",
                        "F1",
                        "--action",
                        "reactivated",
                        "--claim",
                        "RC-0001-CL-01",
                        "--expected-evidence",
                        "Current qualification timing and counter-evidence.",
                    ]
                )

            self.assertEqual(2, result, stderr.getvalue())
            self.assertRegex(
                stderr.getvalue(),
                r"authority changed before cycle persistence: frontier_registry.json",
            )
            self.assertEqual(json_before, cycle_json.read_bytes())
            self.assertEqual(md_before, cycle_md.read_bytes())


class TestRevisitFrontierResearchFloors(unittest.TestCase):
    def test_historical_three_loops_cannot_satisfy_cycle_floor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            bound = run_revisit_cycle_cli(
                workspace,
                "bind-frontier",
                cycle_id,
                "--frontier",
                "F1",
                "--action",
                "reactivated",
                "--claim",
                "RC-0001-CL-01",
                "--expected-evidence",
                "Current qualification timing and counter-evidence.",
            )
            self.assertEqual(0, bound.returncode, bound.stderr)
            issues = derive_task6_floor_issues(workspace, cycle_id)

            self.assertIn(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                [issue.code for issue in issues],
            )

    def test_one_or_two_new_loops_and_state_counts_cannot_substitute(self):
        for count in (1, 2):
            with self.subTest(count=count):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    bind_task6_reactivated_frontier(workspace, cycle_id)
                    append_task6_loops(workspace, count)
                    state_path = workspace / "state.json"
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    state["loop_count"] = 999
                    state_path.write_text(
                        json.dumps(state, indent=2) + "\n", encoding="utf-8"
                    )

                    issues = derive_task6_floor_issues(workspace, cycle_id)

                    self.assertIn(
                        "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                        [issue.code for issue in issues],
                    )

    def test_three_new_loops_without_new_review_fail_only_review_floor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            loop_ids = append_task6_loops(workspace, 3)
            write_task6_search_and_dispatch(workspace, loop_ids)

            issues = derive_task6_floor_issues(workspace, cycle_id)

            codes = [issue.code for issue in issues]
            self.assertIn("REVISIT_REVIEW_FLOOR_MISSING", codes)
            self.assertNotIn("REVISIT_SEARCH_FLOOR_MISSING", codes)
            self.assertNotIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
            self.assertNotIn("REVISIT_CHALLENGE_FLOOR_MISSING", codes)

    def test_every_new_loop_requires_valid_search(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            loop_ids = append_task6_loops(workspace, 3)
            write_task6_search_and_dispatch(workspace, loop_ids)
            search_path = workspace / "search_log.jsonl"
            search_path.write_text(
                "".join(search_path.read_text(encoding="utf-8").splitlines(True)[:2]),
                encoding="utf-8",
            )
            review_task6_frontier(workspace)

            issues = derive_task6_floor_issues(workspace, cycle_id)

            search_issue = next(
                issue
                for issue in issues
                if issue.code == "REVISIT_SEARCH_FLOOR_MISSING"
            )
            self.assertIn("loop_10", search_issue.evidence)

    def test_every_new_loop_requires_exact_scout_and_challenge_delivery(self):
        for role, expected_code in (
            ("frontier_scout", "REVISIT_SCOUT_FLOOR_MISSING"),
            ("challenge_probe", "REVISIT_CHALLENGE_FLOOR_MISSING"),
        ):
            with self.subTest(role=role):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    bind_task6_reactivated_frontier(workspace, cycle_id)
                    loop_ids = append_task6_loops(workspace, 3)
                    write_task6_search_and_dispatch(workspace, loop_ids)
                    dispatch_path = workspace / "dispatch_log.jsonl"
                    records = [
                        json.loads(line)
                        for line in dispatch_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                    ]
                    records = [
                        record
                        for record in records
                        if not (
                            record["loop_id"] == "loop_10"
                            and record["role"] == role
                        )
                    ]
                    dispatch_path.write_text(
                        "".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8",
                    )
                    review_task6_frontier(workspace)

                    issues = derive_task6_floor_issues(workspace, cycle_id)

                    role_issue = next(
                        issue for issue in issues if issue.code == expected_code
                    )
                    self.assertIn("loop_10", role_issue.evidence)

    def test_new_looking_worker_paths_with_old_loop_ids_do_not_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            loop_ids = append_task6_loops(workspace, 3)
            write_task6_search_and_dispatch(workspace, loop_ids)
            dispatch_path = workspace / "dispatch_log.jsonl"
            records = [
                json.loads(line)
                for line in dispatch_path.read_text(encoding="utf-8").splitlines()
            ]
            for record in records:
                if record["loop_id"] == "loop_10":
                    record["loop_id"] = "loop_2"
            dispatch_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            review_task6_frontier(workspace)

            issues = derive_task6_floor_issues(workspace, cycle_id)
            codes = {issue.code for issue in issues}

            self.assertIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
            self.assertIn("REVISIT_CHALLENGE_FLOOR_MISSING", codes)

    def test_three_new_loops_all_work_and_post_binding_review_pass(self):
        for decision in ("Continued", "Retired"):
            with self.subTest(decision=decision):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    bind_task6_reactivated_frontier(workspace, cycle_id)
                    loop_ids = append_task6_loops(workspace, 3)
                    write_task6_search_and_dispatch(workspace, loop_ids)
                    review_task6_frontier(workspace, decision=decision)

                    issues = derive_task6_floor_issues(workspace, cycle_id)

                    self.assertEqual((), issues)

    def test_standalone_early_retirement_fails_and_status_directs_abort(self):
        for count in (1, 2):
            with self.subTest(count=count):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    bind_task6_reactivated_frontier(workspace, cycle_id)
                    append_task6_loops(workspace, count)
                    registry_path = workspace / "frontier_registry.json"
                    registry = json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )
                    registry = transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 3 + count},
                        mode="ticker",
                        action="retire",
                        rationale="The new evidence invalidated the frontier early.",
                        retire_category="invalidated",
                        at_loop=7 + count,
                        ts="2026-07-14T12:00:00Z",
                    )
                    registry_path.write_text(
                        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                    issues = derive_task6_floor_issues(workspace, cycle_id)
                    status = run_revisit_cycle_cli(
                        workspace, "status", cycle_id, "--json"
                    )

                    loop_issue = next(
                        issue
                        for issue in issues
                        if issue.code == "REVISIT_FRONTIER_LOOP_FLOOR_MISSING"
                    )
                    self.assertIn("abort", loop_issue.message)
                    self.assertEqual(0, status.returncode, status.stderr)
                    self.assertEqual(
                        f"abort {cycle_id} --reason TEXT",
                        json.loads(status.stdout)["next_legal_command"],
                    )


class TestRevisitClaimBindingAndFreshnessFacts(unittest.TestCase):
    def test_pending_claim_derives_structured_unresolved_fact(self):
        cycle = make_bound_model_cycle()

        issues = revisit_model.derive_claim_issues(cycle)

        self.assertEqual(
            ["REVISIT_CLAIM_UNRESOLVED"],
            [issue.code for issue in issues],
        )
        self.assertEqual("RC-0001-CL-01", issues[0].evidence)

    def test_each_claim_requires_its_own_completed_binding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_binding_workspace(root)
            previous = revisit_contract.load_cycle(workspace, cycle_id)
            proposed = revisit_contract.add_derived_claim(
                previous,
                {
                    "origin": "split_child",
                    "statement": "Customer A qualifies independently.",
                    "derived_from": "RC-0001-CL-01",
                    "accepted_from": None,
                    "acceptance_rationale": (
                        "The inherited claim combined independent customers."
                    ),
                },
            )
            updated = revisit_model.with_audit(
                previous,
                proposed,
                "add-derived-claim",
                ["RC-0001-DC-01"],
                "2026-07-14T10:10:00Z",
            )
            revisit_contract.persist_cycle(
                workspace,
                updated,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / "RC-0001.json"
                ),
            )
            frontier_id = add_task6_frontier(workspace)
            bind_task6_reactivated_frontier(workspace, cycle_id)
            second = run_revisit_cycle_cli(
                workspace,
                "bind-frontier",
                cycle_id,
                "--frontier",
                frontier_id,
                "--action",
                "added",
                "--claim",
                "RC-0001-DC-01",
                "--expected-evidence",
                "Independent customer qualification evidence.",
            )
            self.assertEqual(0, second.returncode, second.stderr)
            loop_ids = append_task6_loops(workspace, 3)
            write_task6_search_and_dispatch(workspace, loop_ids)
            review_task6_frontier(workspace)

            issues = derive_task6_floor_issues(workspace, cycle_id)

            self.assertIn(
                "REVISIT_FRONTIER_BINDING_INVALID",
                [issue.code for issue in issues],
            )
            claim_issue = next(
                issue
                for issue in issues
                if issue.code == "REVISIT_FRONTIER_BINDING_INVALID"
            )
            self.assertIn("RC-0001-DC-01", claim_issue.evidence)

    def test_stale_identity_with_non_newer_check_is_invalid_positive_support(self):
        cycle = self.make_stale_positive_cycle(
            current_source_id="src-001",
            current_checked_at="2026-07-15T00:05:00Z",
        )

        issues = revisit_model.derive_freshness_issues(cycle)

        self.assertEqual(
            ["REVISIT_FRESHNESS_SUPPORT_INVALID"],
            [issue.code for issue in issues],
        )
        self.assertNotRegex(
            issues[0].message,
            r"\b[0-9]+\s*(?:day|hour|minute|天|小时|分钟)s?\b",
        )

    def test_new_current_ref_or_newer_exact_identity_satisfies_freshness(self):
        cases = (
            ("src-002", "2026-07-15T00:05:00Z"),
            ("src-001", "2026-07-15T00:11:00Z"),
        )
        for source_id, checked_at in cases:
            with self.subTest(source_id=source_id, checked_at=checked_at):
                cycle = self.make_stale_positive_cycle(
                    current_source_id=source_id,
                    current_checked_at=checked_at,
                )

                self.assertEqual((), revisit_model.derive_freshness_issues(cycle))

    def test_stale_or_unknown_provenance_is_allowed_for_disclosed_negative_outcomes(self):
        for status in ("refuted", "blocked"):
            with self.subTest(status=status):
                cycle = self.make_stale_bound_cycle(freshness="unknown")
                if status == "refuted":
                    outcome = make_confirmed_resolution_request()
                    outcome.update(
                        {
                            "status": "refuted",
                            "current_evidence_refs": [],
                            "counter_evidence_refs": [
                                {
                                    "kind": "source",
                                    "source_id": "src-002",
                                    "checked_at": "2026-07-15T00:15:00Z",
                                }
                            ],
                            "current_grade": None,
                            "current_confidence": None,
                            "rationale": (
                                "Current counter-evidence defeats the proposition."
                            ),
                        }
                    )
                else:
                    outcome = make_blocked_resolution(
                        "RC-0001-CL-01", "F1"
                    )
                    outcome.pop("claim_id")
                proposed = revisit_contract.resolve_claim(
                    cycle, "RC-0001-CL-01", outcome
                )
                resolved = revisit_model.with_audit(
                    cycle,
                    proposed,
                    "resolve-claim",
                    ["RC-0001-CL-01"],
                    "2026-07-15T00:20:00Z",
                )

                self.assertEqual(
                    (), revisit_model.derive_freshness_issues(resolved)
                )

    def test_stale_and_unknown_inherited_refs_remain_visible_in_mirror(self):
        cycle = self.make_stale_bound_cycle(freshness="stale")
        cycle["intake"]["selected_claims"][0]["inherited_evidence"].append(
            {
                "ref": {
                    "kind": "source",
                    "source_id": "src-002",
                    "checked_at": "2026-07-15T00:10:00Z",
                },
                "freshness": "unknown",
                "checked_at": "2026-07-15T00:10:00Z",
                "reason": "The source has not been rechecked in this cycle.",
            }
        )
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)

        rendered = revisit_contract.render_cycle_markdown(cycle)

        self.assertIn("| RC-0001-CL-01 | stale |", rendered)
        self.assertIn("| RC-0001-CL-01 | unknown |", rendered)

    def test_revisit_freshness_checker_filters_structured_issue_prefix(self):
        issues = (
            revisit_contract.RevisitIssue(
                "REVISIT_FRESHNESS_SUPPORT_INVALID",
                "cycle.claim_resolutions[0]",
                "fresh support is invalid",
            ),
            revisit_contract.RevisitIssue(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                "cycle.frontier_bindings[0]",
                "three new loops are required",
            ),
        )

        passed, messages = timeliness_checker.check_revisit_freshness(issues)

        self.assertFalse(passed)
        self.assertEqual(
            ["cycle.claim_resolutions[0]: fresh support is invalid"],
            messages,
        )

    @staticmethod
    def make_stale_bound_cycle(*, freshness: str = "stale") -> dict:
        cycle = make_bound_model_cycle()
        cycle["intake"]["selected_claims"][0]["inherited_evidence"] = [
            {
                "ref": {
                    "kind": "source",
                    "source_id": "src-001",
                    "checked_at": "2026-07-15T00:10:00Z",
                },
                "freshness": freshness,
                "checked_at": "2026-07-15T00:10:00Z",
                "reason": "The source predates the fired trigger.",
            }
        ]
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)
        return cycle

    @staticmethod
    def make_stale_positive_cycle(
        *, current_source_id: str, current_checked_at: str
    ) -> dict:
        cycle = TestRevisitClaimBindingAndFreshnessFacts.make_stale_bound_cycle()
        outcome = make_confirmed_resolution_request()
        outcome["current_evidence_refs"] = [
            {
                "kind": "source",
                "source_id": current_source_id,
                "checked_at": current_checked_at,
            }
        ]
        proposed = revisit_contract.resolve_claim(
            cycle, "RC-0001-CL-01", outcome
        )
        return revisit_model.with_audit(
            cycle,
            proposed,
            "resolve-claim",
            ["RC-0001-CL-01"],
            "2026-07-15T00:20:00Z",
        )


class TestRevisitPreReportEvaluation(unittest.TestCase):
    def make_artifact_only_ready_workspace(
        self, root: Path
    ) -> tuple[Path, str]:
        evidence_dir = root / "workspace" / "evidence"
        evidence_dir.mkdir(parents=True)
        trigger_path = evidence_dir / "trigger.md"
        current_path = evidence_dir / "current.md"
        trigger_payload = b"Observed qualification timing trigger.\n"
        current_payload = b"Current qualification timing support.\n"
        trigger_path.write_bytes(trigger_payload)
        current_path.write_bytes(current_payload)
        workspace, cycle_id = make_task6_ready_workspace(
            root,
            current_ref={
                "kind": "artifact",
                "path": "evidence/current.md",
                "sha256": hashlib.sha256(current_payload).hexdigest(),
                "locator": "Current qualification timing support",
                "checked_at": "2026-07-14T12:00:00Z",
            },
        )
        cycle = revisit_contract.load_cycle(workspace, cycle_id)
        cycle["intake"]["triggers"][0]["evidence_refs"] = [
            {
                "kind": "artifact",
                "path": "evidence/trigger.md",
                "sha256": hashlib.sha256(trigger_payload).hexdigest(),
                "locator": "Observed qualification timing trigger",
                "checked_at": "2026-07-14T10:00:00Z",
            }
        ]
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)
        revisit_contract.persist_cycle(
            workspace,
            cycle,
            expected_sha256=revisit_contract.sha256_file(
                workspace / "revisit_cycles" / f"{cycle_id}.json"
            ),
        )
        return workspace, cycle_id

    def assert_revisit_failure(
        self,
        make_workspace,
        expected_code: str,
        *,
        expected_path: str | None = None,
    ) -> None:
        evaluators = (
            (
                "direct",
                lambda workspace, cycle_id: sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker", target="revisit_report"
                    ),
                ),
            ),
        )
        for evaluator_name, evaluate in evaluators:
            with (
                self.subTest(evaluator=evaluator_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_workspace(Path(temp_dir))

                result = evaluate(workspace, cycle_id)

                self.assertFalse(result.passed)
                self.assertIn(
                    expected_code,
                    [issue.code for issue in result.failures],
                )
                if expected_path is not None:
                    matching_issue = next(
                        issue
                        for issue in result.failures
                        if issue.code == expected_code
                    )
                    self.assertEqual(expected_path, matching_issue.path)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_workspace(Path(temp_dir))
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            prior_workspace = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn(expected_code, result.stderr)
            if expected_path is not None:
                self.assertIn(f"[{expected_path}]", result.stderr)
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())
            self.assertEqual(prior_workspace, snapshot_tree(workspace))

    def assert_invalid_worker_output_rejected(
        self,
        relative_path: str,
        mutate_output,
        expected_code: str,
    ) -> None:
        def make_workspace(root: Path) -> tuple[Path, str]:
            workspace, cycle_id = make_task6_ready_workspace(root)
            output_path = workspace / relative_path
            output_path.write_text(
                mutate_output(output_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            return workspace, cycle_id

        self.assert_revisit_failure(make_workspace, expected_code)

    def test_public_selection_keeps_loud_failure_for_missing_validated_cycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _cycle_id = make_task6_ready_workspace(Path(temp_dir))
            impossible_history = mock.Mock(
                issues=(),
                nonterminal_cycle_ids=("RC-9999",),
                completed_unpublished_cycle_ids=(),
            )
            with mock.patch.object(
                revisit_readiness,
                "evaluate_history",
                return_value=impossible_history,
            ):
                with self.assertRaisesRegex(
                    revisit_readiness.ReadinessPlanError,
                    "eligible history cycle lacks its validated document",
                ):
                    revisit_readiness.evaluate_revisit_readiness(workspace)

    def test_public_revisit_report_is_exact_two_argument_readiness_adapter(self):
        workspace = "workspace-token"
        cycle_id = "RC-0007"
        expected = object()
        with mock.patch.object(
            revisit_readiness,
            "evaluate_revisit_readiness",
            return_value=expected,
        ) as readiness_seam:
            with self.subTest(contract="signature"):
                self.assertEqual(
                    ("workspace", "cycle_id"),
                    tuple(
                        inspect.signature(
                            sofa_evaluate.evaluate_revisit_report
                        ).parameters
                    ),
                )
            for contract, args, kwargs in (
                (
                    "third positional",
                    (workspace, cycle_id, False),
                    {},
                ),
                (
                    "obsolete keyword",
                    (workspace, cycle_id),
                    {"require" + "_candidate": False},
                ),
            ):
                with self.subTest(contract=contract):
                    with self.assertRaises(TypeError):
                        sofa_evaluate.evaluate_revisit_report(*args, **kwargs)

            readiness_seam.reset_mock()
            actual = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)

        self.assertIs(expected, actual)
        readiness_seam.assert_called_once_with(workspace, cycle_id)

    def test_revisit_rejects_delivered_worker_missing_method_cards(self):
        self.assert_invalid_worker_output_rejected(
            "challenges/loop_8_challenge.md",
            lambda text: text.replace(
                "Method cards loaded: red-team, supply-chain-mapping, "
                "customer-graph-discovery.\n\n",
                "",
                1,
            ),
            "WORKER_METHOD_CARDS_MISSING",
        )

    def test_revisit_rejects_scout_missing_source_trace(self):
        self.assert_invalid_worker_output_rejected(
            "scouts/loop_8_scout.md",
            lambda text: text.replace(
                "Sources consulted: accepted source trace for loop_8.\n\n",
                "",
                1,
            ),
            "WORKER_SOURCE_TRACE_MISSING",
        )

    def test_revisit_rejects_scout_forbidden_conclusion(self):
        self.assert_invalid_worker_output_rejected(
            "scouts/loop_8_scout.md",
            lambda text: text + "\nAction Class: buy.\n",
            "SCOUT_FORBIDDEN_CONCLUSION",
        )

    def make_ready_with_drifted_artifact_ref(
        self,
        root: Path,
        *,
        reference_field: str,
        resolution_status: str = "confirmed",
    ) -> tuple[Path, str]:
        evidence_dir = root / "workspace" / "evidence"
        evidence_dir.mkdir(parents=True)
        references = []
        for label in ("drifted", "valid"):
            relative_path = f"evidence/{reference_field}-{label}.md"
            payload = (
                f"Exact {reference_field} evidence intended to remain {label}.\n"
            ).encode("utf-8")
            (root / "workspace" / relative_path).write_bytes(payload)
            references.append(
                {
                    "kind": "artifact",
                    "path": relative_path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "locator": f"Exact {reference_field} evidence {label}",
                    "checked_at": "2026-07-14T12:00:00Z",
                }
            )

        workspace, cycle_id = make_task6_ready_workspace(root)
        cycle = revisit_contract.load_cycle(workspace, cycle_id)
        if reference_field == "trigger":
            cycle["intake"]["triggers"][0]["evidence_refs"] = references
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        else:
            resolution = cycle["claim_resolutions"][0]
            resolution["status"] = resolution_status
            if resolution_status == "weakened":
                resolution["revised_statement"] = (
                    "Customer qualification completes only after the prior "
                    "watch window."
                )
                resolution["counter_evidence_refs"] = [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T12:00:00Z",
                    }
                ]
            elif resolution_status == "refuted":
                resolution["revised_statement"] = None
                resolution["current_evidence_refs"] = []
                resolution["current_grade"] = None
                resolution["current_confidence"] = None
                resolution["rationale"] = (
                    "Current counter-evidence defeats the proposition."
                )
                cycle["decision_assessment"]["supporting_claim_ids"] = []
            resolution[reference_field] = references
        attach_valid_audit(cycle)
        revisit_contract.persist_cycle(
            workspace,
            cycle,
            expected_sha256=revisit_contract.sha256_file(
                workspace / "revisit_cycles" / f"{cycle_id}.json"
            ),
        )
        drifted_path = workspace / references[0]["path"]
        drifted_path.write_bytes(drifted_path.read_bytes() + b"drift\n")
        return workspace, cycle_id

    def test_revisit_rejects_one_drifted_trigger_ref_among_valid_siblings(self):
        self.assert_revisit_failure(
            lambda root: self.make_ready_with_drifted_artifact_ref(
                root,
                reference_field="trigger",
            ),
            "REVISIT_TRIGGER_EVIDENCE_MISSING",
            expected_path="cycle.intake.triggers[0].evidence_refs[0]",
        )

    def test_revisit_rejects_one_drifted_current_ref_among_valid_siblings(self):
        for resolution_status in ("confirmed", "weakened"):
            with self.subTest(resolution_status=resolution_status):
                self.assert_revisit_failure(
                    lambda root: self.make_ready_with_drifted_artifact_ref(
                        root,
                        reference_field="current_evidence_refs",
                        resolution_status=resolution_status,
                    ),
                    "REVISIT_FRESHNESS_SUPPORT_INVALID",
                    expected_path=(
                        "cycle.claim_resolutions[0].current_evidence_refs[0]"
                    ),
                )

    def test_revisit_rejects_drifted_refuted_counter_evidence(self):
        self.assert_revisit_failure(
            lambda root: self.make_ready_with_drifted_artifact_ref(
                root,
                reference_field="counter_evidence_refs",
                resolution_status="refuted",
            ),
            "REVISIT_COUNTER_EVIDENCE_INVALID",
            expected_path=(
                "cycle.claim_resolutions[0].counter_evidence_refs[0]"
            ),
        )

    def test_revisit_rejects_drifted_weakened_counter_evidence(self):
        self.assert_revisit_failure(
            lambda root: self.make_ready_with_drifted_artifact_ref(
                root,
                reference_field="counter_evidence_refs",
                resolution_status="weakened",
            ),
            "REVISIT_COUNTER_EVIDENCE_INVALID",
            expected_path=(
                "cycle.claim_resolutions[0].counter_evidence_refs[0]"
            ),
        )

    def assert_review_lifecycle_incoherence_rejected(
        self,
        mutate_frontier,
    ) -> None:
        def make_workspace(root: Path) -> tuple[Path, str]:
            workspace, cycle_id = make_task6_ready_workspace(root)
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            mutate_frontier(registry["frontiers"][0])
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return workspace, cycle_id

        # Task 6.4 routes the canonical registry through ObservedReadSession and
        # maps LifecycleError to REVISIT_FRONTIER_REGISTRY_MALFORMED.
        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_FRONTIER_REGISTRY_MALFORMED",
            expected_path="frontier_registry.json",
        )

    def test_revisit_rejects_review_without_matching_lifecycle_transition(self):
        def remove_post_binding_review_transition(frontier: dict) -> None:
            self.assertEqual("Continued", frontier["status"])
            self.assertEqual("Continued", frontier["lifecycle"][-1]["to"])
            frontier["lifecycle"].pop()

        self.assert_review_lifecycle_incoherence_rejected(
            remove_post_binding_review_transition
        )

    def test_revisit_rejects_review_lifecycle_loop_mismatch(self):
        def move_post_binding_review_transition(frontier: dict) -> None:
            self.assertEqual("Continued", frontier["status"])
            self.assertEqual("Continued", frontier["lifecycle"][-1]["to"])
            self.assertEqual(
                frontier["review_decisions"][-1]["at_loop"],
                frontier["lifecycle"][-1]["at_loop"],
            )
            frontier["lifecycle"][-1]["at_loop"] = 9

        self.assert_review_lifecycle_incoherence_rejected(
            move_post_binding_review_transition
        )

    def assert_artifact_only_source_cache_failure(
        self,
        write_invalid_index,
        expected_code: str,
    ) -> None:
        def make_workspace(root: Path) -> tuple[Path, str]:
            workspace, cycle_id = self.make_artifact_only_ready_workspace(root)
            write_invalid_index(workspace / "sources_index.jsonl")
            return workspace, cycle_id

        self.assert_revisit_failure(make_workspace, expected_code)

    def test_artifact_only_revisit_rejects_malformed_present_source_cache(self):
        def write_invalid_index(index_path: Path) -> None:
            index_path.write_text("{not valid json\n", encoding="utf-8")

        self.assert_artifact_only_source_cache_failure(
            write_invalid_index,
            "SOURCE_INDEX_MALFORMED",
        )

    def test_artifact_only_revisit_rejects_unrelated_invalid_source_cache(self):
        def write_invalid_index(index_path: Path) -> None:
            invalid_record = {
                "source_id": "src-999",
                "url": "https://example.test/unrelated",
                "title": "Unrelated missing excerpt",
                "retrieved": "2026-07-14",
                "grade": "B",
                "excerpt_path": "sources/src-999.md",
                "sha256": "a" * 64,
            }
            index_path.write_text(
                json.dumps(invalid_record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        self.assert_artifact_only_source_cache_failure(
            write_invalid_index,
            "SOURCE_EXCERPT_MISSING",
        )

    def test_artifact_only_revisit_allows_absent_source_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = self.make_artifact_only_ready_workspace(
                Path(temp_dir)
            )
            (workspace / "sources_index.jsonl").unlink()

            direct = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)
            profile = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertTrue(
                direct.passed,
                [issue.display() for issue in direct.failures],
            )
            self.assertTrue(
                profile.passed,
                [issue.display() for issue in profile.failures],
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertEqual(
                "ready_for_report",
                revisit_contract.load_cycle(workspace, cycle_id)["status"],
            )

    def assert_artifact_only_source_index_race_rejected(
        self,
        *,
        starts_absent: bool,
    ) -> None:
        # The artifact-only cycle does not name any source_id, so the source
        # index authority is observed by the readiness session only because the
        # source-cache row reads every planned excerpt. A byte drift OR an
        # absence->appearance of the index during the pre-write window is
        # caught by the frozen closure -> BLOCKED with zero net writes.
        # ``closure_store`` is the top-level module object the readiness seam's
        # ``persist_cycle`` actually resolves ``_require_unchanged_except``
        # from (distinct from ``scripts.revisit_contract.store``).
        from revisit_contract import store as closure_store

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = self.make_artifact_only_ready_workspace(
                Path(temp_dir)
            )
            source_index = workspace / "sources_index.jsonl"
            original_index = source_index.read_bytes()
            changed_index = (
                original_index
                if starts_absent
                else original_index + b"\n"
            )
            if starts_absent:
                source_index.unlink()
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_require = closure_store._require_unchanged_except
            calls = []

            def injecting_require(closure, excluded):
                calls.append(1)
                if len(calls) == 1:
                    source_index.write_bytes(changed_index)
                return real_require(closure, excluded)

            with mock.patch.object(
                closure_store,
                "_require_unchanged_except",
                injecting_require,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            codes = [issue.code for issue in outcome.result.failures]
            self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
            self.assertEqual(changed_index, source_index.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_artifact_only_check_generation_binds_present_source_index(self):
        self.assert_artifact_only_source_index_race_rejected(
            starts_absent=False,
        )

    def test_artifact_only_check_rejects_source_index_missing_to_appearance(self):
        self.assert_artifact_only_source_index_race_rejected(
            starts_absent=True,
        )

    def test_reactivated_binding_rejects_decreasing_pre_binding_timestamps(self):
        def make_workspace(root: Path) -> tuple[Path, str]:
            workspace, cycle_id = make_task6_ready_workspace(root)
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            lifecycle = registry["frontiers"][0]["lifecycle"]
            active_index = max(
                index
                for index, transition_row in enumerate(lifecycle)
                if transition_row.get("to") == "Active"
            )
            lifecycle[active_index - 1]["ts"] = "2026-07-14T11:15:00Z"
            lifecycle[active_index]["ts"] = "2026-07-14T11:00:00Z"
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return workspace, cycle_id

        # Task 6.4 routes the canonical registry through ObservedReadSession and
        # maps LifecycleError to REVISIT_FRONTIER_REGISTRY_MALFORMED.
        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_FRONTIER_REGISTRY_MALFORMED",
            expected_path="frontier_registry.json",
        )

    def test_added_binding_rejects_decreasing_pre_binding_timestamps(self):
        def make_workspace(root: Path) -> tuple[Path, str]:
            workspace, cycle_id, frontier_id = make_task6_added_ready_workspace(
                root
            )
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            frontier = next(
                row
                for row in registry["frontiers"]
                if row["id"] == frontier_id
            )
            post_binding_review = copy.deepcopy(frontier["lifecycle"][-1])
            frontier["lifecycle"][-1]["ts"] = "2026-07-14T11:15:00Z"
            list_final_active = copy.deepcopy(frontier["lifecycle"][0])
            list_final_active["ts"] = "2026-07-14T10:30:00Z"
            frontier["lifecycle"].extend(
                [list_final_active, post_binding_review]
            )
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return workspace, cycle_id

        # Task 6.4 routes the canonical registry through ObservedReadSession and
        # maps LifecycleError to REVISIT_FRONTIER_REGISTRY_MALFORMED.
        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_FRONTIER_REGISTRY_MALFORMED",
            expected_path="frontier_registry.json",
        )

    def assert_bound_at_state_drift_rejected(self, make_workspace) -> None:
        evaluators = (
            (
                "direct",
                lambda workspace, cycle_id: sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker", target="revisit_report"
                    ),
                ),
            ),
        )
        for evaluator_name, evaluate in evaluators:
            with (
                self.subTest(evaluator=evaluator_name),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id, frontier_id = make_workspace(
                    Path(temp_dir)
                )
                move_task6_review_to_bound_at(
                    workspace,
                    cycle_id,
                    frontier_id,
                )

                result = evaluate(workspace, cycle_id)

                self.assertFalse(result.passed)
                self.assertIn(
                    "REVISIT_FRONTIER_BINDING_INVALID",
                    [issue.code for issue in result.failures],
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id, frontier_id = make_workspace(Path(temp_dir))
            move_task6_review_to_bound_at(
                workspace,
                cycle_id,
                frontier_id,
            )
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()

            result = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("REVISIT_FRONTIER_BINDING_INVALID", result.stderr)
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_reactivated_binding_rejects_non_active_state_at_bound_at(self):
        def make_workspace(root: Path) -> tuple[Path, str, str]:
            workspace, cycle_id = make_task6_ready_workspace(root)
            return workspace, cycle_id, "F1"

        self.assert_bound_at_state_drift_rejected(make_workspace)

    def test_added_binding_rejects_non_active_or_new_state_at_bound_at(self):
        self.assert_bound_at_state_drift_rejected(
            make_task6_added_ready_workspace
        )

    def test_revisit_report_profile_routes_to_cycle_relative_floor_verdict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)

            result = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )

            self.assertIn(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                [issue.code for issue in result.failures],
            )

    def test_direct_evaluator_passes_ready_pre_report_state_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            before = snapshot_tree(workspace)

            result = sofa_evaluate.evaluate_revisit_report(
                workspace, cycle_id
            )

            self.assertTrue(
                result.passed,
                [issue.display() for issue in result.failures],
            )
            self.assertEqual(before, snapshot_tree(workspace))

    def test_direct_evaluator_rejects_framing_raw_hash_or_snapshot_drift(self):
        for drift_case in ("raw_hash", "snapshot"):
            with (
                self.subTest(drift_case=drift_case),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                framing_path = workspace / "framing_contract.json"
                if drift_case == "raw_hash":
                    framing_path.write_bytes(framing_path.read_bytes() + b"\n")
                else:
                    framing = json.loads(framing_path.read_text(encoding="utf-8"))
                    framing["time_horizon"] = "12-18 months"
                    framing_path.write_text(
                        json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    cycle = revisit_contract.load_cycle(workspace, cycle_id)
                    cycle["intake"]["framing"]["sha256"] = hashlib.sha256(
                        framing_path.read_bytes()
                    ).hexdigest()
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                    attach_valid_audit(cycle)
                    revisit_contract.persist_cycle(
                        workspace,
                        cycle,
                        expected_sha256=revisit_contract.sha256_file(
                            workspace / "revisit_cycles" / f"{cycle_id}.json"
                        ),
                    )

                result = sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                )

                self.assertFalse(result.passed)
                self.assertIn(
                    "REVISIT_INTAKE_DRIFT",
                    [issue.code for issue in result.failures],
                )

    def test_direct_evaluator_rejects_selected_claim_source_deletion_or_hash_drift(
        self,
    ):
        for drift_case in ("deleted", "hash"):
            with (
                self.subTest(drift_case=drift_case),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                source_path = workspace / "claim_ledger.md"
                if drift_case == "deleted":
                    source_path.unlink()
                else:
                    source_path.write_bytes(
                        source_path.read_bytes() + b"selected claim source drift\n"
                    )

                result = sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                )

                self.assertFalse(result.passed)
                self.assertIn(
                    "REVISIT_INTAKE_DRIFT",
                    [issue.code for issue in result.failures],
                )

    def test_evaluator_reports_stable_malformed_base_trigger_and_unresolved_codes(self):
        cases = ("malformed", "base_drift", "trigger_missing", "unresolved")
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    if case == "unresolved":
                        workspace, cycle_id = make_task6_binding_workspace(root)
                        bind_task6_reactivated_frontier(workspace, cycle_id)
                        loop_ids = append_task6_loops(workspace, 3)
                        write_task6_search_and_dispatch(workspace, loop_ids)
                        review_task6_frontier(workspace)
                    else:
                        workspace, cycle_id = make_task6_ready_workspace(root)
                    if case == "malformed":
                        (workspace / "revisit_cycles" / f"{cycle_id}.json").write_text(
                            "{not valid json\n", encoding="utf-8"
                        )
                        expected = "REVISIT_CYCLE_MALFORMED"
                    elif case == "base_drift":
                        report = workspace / "reports" / "final.md"
                        report.write_bytes(report.read_bytes() + b"base drift\n")
                        expected = "REVISIT_BASE_REPORT_DRIFT"
                    elif case == "trigger_missing":
                        (workspace / "sources_index.jsonl").unlink()
                        expected = "REVISIT_TRIGGER_EVIDENCE_MISSING"
                    else:
                        expected = "REVISIT_CLAIM_UNRESOLVED"

                    result = sofa_evaluate.evaluate_revisit_report(
                        workspace, cycle_id
                    )

                    self.assertIn(
                        expected,
                        [issue.code for issue in result.failures],
                    )
                    if case in {"malformed", "base_drift"}:
                        self.assertNotIn(
                            "REVISIT_INTAKE_DRIFT",
                            [issue.code for issue in result.failures],
                        )

    def test_evaluator_reports_binding_and_each_live_floor_category(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            result = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )
            self.assertIn(
                "REVISIT_FRONTIER_BINDING_INVALID",
                [issue.code for issue in result.failures],
            )

        for case, expected in (
            ("search", "REVISIT_SEARCH_FLOOR_MISSING"),
            ("scout", "REVISIT_SCOUT_FLOOR_MISSING"),
            ("challenge", "REVISIT_CHALLENGE_FLOOR_MISSING"),
            ("review", "REVISIT_REVIEW_FLOOR_MISSING"),
        ):
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_binding_workspace(
                        Path(temp_dir)
                    )
                    bind_task6_reactivated_frontier(workspace, cycle_id)
                    loop_ids = append_task6_loops(workspace, 3)
                    write_task6_search_and_dispatch(workspace, loop_ids)
                    if case != "review":
                        review_task6_frontier(workspace)
                    if case == "search":
                        search_path = workspace / "search_log.jsonl"
                        records = search_path.read_text(encoding="utf-8").splitlines(
                            keepends=True
                        )
                        search_path.write_text(
                            "".join(records[:2]), encoding="utf-8"
                        )
                    elif case in {"scout", "challenge"}:
                        missing_role = (
                            "frontier_scout"
                            if case == "scout"
                            else "challenge_probe"
                        )
                        dispatch_path = workspace / "dispatch_log.jsonl"
                        records = [
                            json.loads(line)
                            for line in dispatch_path.read_text(
                                encoding="utf-8"
                            ).splitlines()
                        ]
                        records = [
                            record
                            for record in records
                            if not (
                                record["loop_id"] == "loop_10"
                                and record["role"] == missing_role
                            )
                        ]
                        dispatch_path.write_text(
                            "".join(
                                json.dumps(record) + "\n" for record in records
                            ),
                            encoding="utf-8",
                        )

                    result = sofa_evaluate.evaluate_revisit_report(
                        workspace, cycle_id
                    )

                    self.assertIn(
                        expected,
                        [issue.code for issue in result.failures],
                    )

    def test_direct_evaluator_rejects_historical_loop_regression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            ledger_path = workspace / "evidence_ledger.md"
            ledger_text = ledger_path.read_text(encoding="utf-8")
            ledger_path.write_text(
                ledger_text.replace(
                    "## Loop 2: F1 - Qualification timing\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )

            result = sofa_evaluate.evaluate_revisit_report(
                workspace, cycle_id
            )

            self.assertFalse(result.passed)
            self.assertIn(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                [issue.code for issue in result.failures],
            )

    def test_check_rejects_historical_loop_regression_without_cycle_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            ledger_path = workspace / "evidence_ledger.md"
            ledger_text = ledger_path.read_text(encoding="utf-8")
            ledger_path.write_text(
                ledger_text.replace(
                    "## Loop 2: F1 - Qualification timing\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            regressed_ledger = ledger_path.read_bytes()

            result = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                result.stderr,
            )
            self.assertEqual(regressed_ledger, ledger_path.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_direct_and_profile_reject_reactivated_binding_history_drift(self):
        evaluators = (
            (
                "direct",
                lambda workspace, cycle_id: sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker", target="revisit_report"
                    ),
                ),
            ),
        )
        for drift_case in ("timestamp", "preceding_state"):
            for evaluator_name, evaluate in evaluators:
                with (
                    self.subTest(
                        drift_case=drift_case,
                        evaluator=evaluator_name,
                    ),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    workspace, cycle_id = make_task6_ready_workspace(
                        Path(temp_dir)
                    )
                    registry_path = workspace / "frontier_registry.json"
                    registry = json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )
                    lifecycle = registry["frontiers"][0]["lifecycle"]
                    active_index = max(
                        index
                        for index, transition_row in enumerate(lifecycle)
                        if transition_row.get("to") == "Active"
                    )
                    if drift_case == "timestamp":
                        lifecycle[active_index]["ts"] = "2026-07-14T09:00:00Z"
                    else:
                        lifecycle[active_index - 1]["to"] = "New"
                    registry_path.write_text(
                        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                    result = evaluate(workspace, cycle_id)

                    self.assertFalse(result.passed)
                    # Task 6.4 routes the canonical registry through
                    # ObservedReadSession and maps LifecycleError to
                    # REVISIT_FRONTIER_REGISTRY_MALFORMED.
                    self.assertIn(
                        "REVISIT_FRONTIER_REGISTRY_MALFORMED",
                        [issue.code for issue in result.failures],
                    )

    def test_direct_and_profile_reject_added_binding_history_drift(self):
        evaluators = (
            (
                "direct",
                lambda workspace, cycle_id: sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker", target="revisit_report"
                    ),
                ),
            ),
        )
        for drift_case in ("first_transition", "proposal_loop"):
            for evaluator_name, evaluate in evaluators:
                with (
                    self.subTest(
                        drift_case=drift_case,
                        evaluator=evaluator_name,
                    ),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    workspace, cycle_id, frontier_id = (
                        make_task6_added_ready_workspace(Path(temp_dir))
                    )
                    registry_path = workspace / "frontier_registry.json"
                    registry = json.loads(
                        registry_path.read_text(encoding="utf-8")
                    )
                    frontier = next(
                        row
                        for row in registry["frontiers"]
                        if row["id"] == frontier_id
                    )
                    if drift_case == "first_transition":
                        frontier["lifecycle"][0]["ts"] = (
                            "2026-07-14T09:00:00Z"
                        )
                    else:
                        frontier["proposed_at_loop"] = 7
                    registry_path.write_text(
                        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )

                    result = evaluate(workspace, cycle_id)

                    self.assertFalse(result.passed)
                    self.assertIn(
                        "REVISIT_FRONTIER_BINDING_INVALID",
                        [issue.code for issue in result.failures],
                    )

    def test_revisit_evaluator_preserves_global_dispatch_invariants(self):
        cases = (
            ("duplicate_path", "DISPATCH_DELIVERY_PATH_DUPLICATE"),
            ("incomplete", "DISPATCH_RECORD_INCOMPLETE"),
            ("unsupported_mechanism", "DISPATCH_MECHANISM_UNSUPPORTED"),
            ("role_path_mismatch", "DISPATCH_ROLE_DELIVERY_MISMATCH"),
        )
        for dispatch_case, expected_code in cases:
            with (
                self.subTest(dispatch_case=dispatch_case),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                dispatch_path = workspace / "dispatch_log.jsonl"
                records = [
                    json.loads(line)
                    for line in dispatch_path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                if dispatch_case == "duplicate_path":
                    extra = copy.deepcopy(records[0])
                    extra["dispatch_id"] = "dispatch_duplicate_path"
                    extra["loop_id"] = "loop_11"
                elif dispatch_case == "incomplete":
                    extra = {
                        "dispatch_id": "dispatch_incomplete",
                        "status": "delivered",
                    }
                else:
                    delivery_path = (
                        "scouts/loop_11_scout.md"
                        if dispatch_case == "unsupported_mechanism"
                        else "challenges/loop_11_challenge.md"
                    )
                    delivery = workspace / delivery_path
                    delivery.parent.mkdir(exist_ok=True)
                    delivery.write_text(
                        "# Extra dispatch invariant probe\n",
                        encoding="utf-8",
                    )
                    extra = {
                        "dispatch_id": f"dispatch_{dispatch_case}",
                        "loop_id": "loop_11",
                        "role": "frontier_scout",
                        "mechanism": (
                            "unsupported"
                            if dispatch_case == "unsupported_mechanism"
                            else "host_subagent"
                        ),
                        "delivery_path": delivery_path,
                        "status": "delivered",
                    }
                records.append(extra)
                dispatch_path.write_text(
                    "".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8",
                )

                result = sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                )

                self.assertFalse(result.passed)
                self.assertIn(
                    expected_code,
                    [issue.code for issue in result.failures],
                )

    def test_evaluator_reports_invalid_current_support_and_forbidden_support(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            artifact = workspace / "evidence" / "current.md"
            artifact.parent.mkdir()
            artifact.write_text("Current qualification evidence.\n", encoding="utf-8")
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["claim_resolutions"][0]["current_evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "evidence/current.md",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "locator": "Current evidence",
                    "checked_at": "2026-07-14T12:00:00Z",
                }
            ]
            attach_valid_audit(cycle)
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / f"{cycle_id}.json"
                ),
            )
            artifact.unlink()

            result = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)

            self.assertIn(
                "REVISIT_FRESHNESS_SUPPORT_INVALID",
                [issue.code for issue in result.failures],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
            resolution = cycle["claim_resolutions"][0]
            resolution.update(
                {
                    "status": "refuted",
                    "current_evidence_refs": [],
                    "counter_evidence_refs": [
                        {
                            "kind": "source",
                            "source_id": "src-001",
                            "checked_at": "2026-07-14T12:00:00Z",
                        }
                    ],
                    "current_grade": None,
                    "current_confidence": None,
                    "rationale": "Current evidence refutes the proposition.",
                }
            )
            attach_valid_audit(cycle)
            cycle_path.write_bytes(revisit_contract.canonical_document_bytes(cycle))

            result = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)

            self.assertIn(
                "REVISIT_CLAIM_SUPPORT_FORBIDDEN",
                [issue.code for issue in result.failures],
            )

    def test_profile_discovery_requires_one_candidate_and_rejects_sector(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_revisit_start_workspace(Path(temp_dir))
            result = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )
            self.assertIn(
                "REVISIT_CYCLE_MALFORMED",
                [issue.code for issue in result.failures],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_task6_ready_workspace(Path(temp_dir))
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["mode"] = "sector"
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            result = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )

            self.assertIn(
                "REVISIT_UNSUPPORTED_MODE",
                [issue.code for issue in result.failures],
            )

    def test_revisit_profile_rejects_ordinary_sector_before_pointer_discovery(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(
                Path(temp_dir),
                mode="sector",
            )

            result = sofa_evaluate.evaluate_workspace(
                workspace,
                sofa_evaluate.ContractProfile(
                    mode="ticker", target="revisit_report"
                ),
            )

            self.assertFalse(result.passed)
            self.assertEqual(
                ["REVISIT_UNSUPPORTED_MODE"],
                [issue.code for issue in result.failures],
            )
            self.assertEqual("state.json", result.failures[0].path)

    def test_direct_and_profile_reject_missing_or_unknown_ticker_state(self):
        evaluators = (
            (
                "direct",
                lambda workspace, cycle_id: sofa_evaluate.evaluate_revisit_report(
                    workspace, cycle_id
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker", target="revisit_report"
                    ),
                ),
            ),
        )
        expected_by_state_case = {
            "missing": "STATE_JSON_MISSING",
            "unknown": "STATE_JSON_INVALID",
        }
        for state_case, expected_code in expected_by_state_case.items():
            for evaluator_name, evaluate in evaluators:
                with (
                    self.subTest(
                        state_case=state_case,
                        evaluator=evaluator_name,
                    ),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    workspace, cycle_id = make_task6_ready_workspace(
                        Path(temp_dir)
                    )
                    state_path = workspace / "state.json"
                    if state_case == "missing":
                        state_path.unlink()
                    else:
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        state["mode"] = "not-ticker"
                        state_path.write_text(
                            json.dumps(state, indent=2) + "\n",
                            encoding="utf-8",
                        )

                    result = evaluate(workspace, cycle_id)

                    self.assertFalse(result.passed)
                    self.assertEqual(
                        [expected_code],
                        [issue.code for issue in result.failures],
                    )

    def test_check_failure_prints_verdict_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            write_task6_search_and_dispatch(workspace, ())
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn(
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING", result.stderr
            )
            self.assertEqual(before, snapshot_tree(workspace))

    def test_check_passes_with_one_ready_transition_and_ready_recheck_is_noop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            before = revisit_contract.load_cycle(workspace, cycle_id)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-14T13:00:00Z",
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(0, result, stderr.getvalue())
            ready = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("ready_for_report", ready["status"])
            self.assertEqual(len(before["audit"]) + 1, len(ready["audit"]))
            self.assertEqual("check", ready["audit"][-1]["command"])
            self.assertIn("REVISIT CYCLE READY", stdout.getvalue())

            ready_bytes = snapshot_tree(workspace)
            second = run_revisit_cycle_cli(workspace, "check", cycle_id)

            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(ready_bytes, snapshot_tree(workspace))

    def test_check_rejects_source_record_remap_before_ready_persistence(self):
        # The source cache is read ONCE through the observed session, so a
        # source record cannot be silently remapped during the check. If the
        # source index bytes change in the pre-write window, the closure flags
        # drift and the outcome is BLOCKED with zero net writes.
        # ``closure_store`` is the top-level module object the readiness seam
        # resolves ``_require_unchanged_except`` from.
        from revisit_contract import store as closure_store

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            source_index = workspace / "sources_index.jsonl"
            drifted_index = source_index.read_bytes() + b"\n"
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_require = closure_store._require_unchanged_except
            calls = []

            def injecting_require(closure, excluded):
                calls.append(1)
                if len(calls) == 2:
                    source_index.write_bytes(drifted_index)
                return real_require(closure, excluded)

            with mock.patch.object(
                closure_store,
                "_require_unchanged_except",
                injecting_require,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            codes = [issue.code for issue in outcome.result.failures]
            self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
            self.assertEqual(drifted_index, source_index.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def assert_missing_authority_cannot_appear_during_evaluation(
        self,
        workspace: Path,
        cycle_id: str,
        authority_path: Path,
    ) -> None:
        """An observed authority must NOT change between preparation and the
        store's pre-write recheck.

        The file is left valid at preparation so the semantic plan passes; it
        is then byte-drifted during the store's pre-write closure recheck, so
        the closure flags drift and the outcome is BLOCKED with zero net
        writes.
        """
        # The readiness seam imports persist_cycle from the top-level
        # ``revisit_contract`` package, so its ``_persist_cycle_with_closure``
        # resolves ``_require_unchanged_except`` from that SAME module object
        # (which is distinct from ``scripts.revisit_contract.store``).
        from revisit_contract import store as closure_store

        authority_payload = authority_path.read_bytes()
        drifted_payload = authority_payload + b"pre-write drift\n"
        cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
        mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
        prior_cycle = cycle_path.read_bytes()
        prior_mirror = mirror_path.read_bytes()
        real_require = closure_store._require_unchanged_except
        calls = []

        def injecting_require(closure, excluded):
            calls.append(1)
            if len(calls) == 1:
                authority_path.write_bytes(drifted_payload)
            return real_require(closure, excluded)

        with mock.patch.object(
            closure_store,
            "_require_unchanged_except",
            injecting_require,
        ):
            outcome = check_revisit_readiness(
                workspace,
                cycle_id,
                timestamp="2026-07-16T12:00:00Z",
            )

        self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
        codes = [issue.code for issue in outcome.result.failures]
        self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
        self.assertEqual(drifted_payload, authority_path.read_bytes())
        self.assertEqual(prior_cycle, cycle_path.read_bytes())
        self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_check_rejects_search_log_missing_to_appearance_without_cycle_writes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            self.assert_missing_authority_cannot_appear_during_evaluation(
                workspace,
                cycle_id,
                workspace / "search_log.jsonl",
            )

    def test_check_rejects_dispatch_log_missing_to_appearance_without_cycle_writes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            self.assert_missing_authority_cannot_appear_during_evaluation(
                workspace,
                cycle_id,
                workspace / "dispatch_log.jsonl",
            )

    def test_check_rejects_delivered_target_missing_to_appearance_without_cycle_writes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            self.assert_missing_authority_cannot_appear_during_evaluation(
                workspace,
                cycle_id,
                workspace / "scouts" / "loop_8_scout.md",
            )

    def test_check_rejects_core_authority_missing_to_appearance_without_cycle_writes(
        self,
    ):
        for relative_path in (
            "frontier_registry.json",
            "evidence_ledger.md",
            "research_workflow.md",
        ):
            with (
                self.subTest(relative_path=relative_path),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                self.assert_missing_authority_cannot_appear_during_evaluation(
                    workspace,
                    cycle_id,
                    workspace / relative_path,
                )

    def test_check_rejects_artifact_ref_missing_to_appearance_without_cycle_writes(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_path = root / "workspace" / "evidence" / "current.md"
            artifact_path.parent.mkdir(parents=True)
            artifact_payload = b"Current cycle evidence.\n"
            artifact_path.write_bytes(artifact_payload)
            workspace, cycle_id = make_task6_ready_workspace(
                root,
                current_ref={
                    "kind": "artifact",
                    "path": "evidence/current.md",
                    "sha256": hashlib.sha256(artifact_payload).hexdigest(),
                    "locator": "Current cycle evidence",
                    "checked_at": "2026-07-14T12:00:00Z",
                },
            )
            self.assert_missing_authority_cannot_appear_during_evaluation(
                workspace,
                cycle_id,
                artifact_path,
            )

    def test_check_rejects_preexisting_orphan_output_disappearance_without_cycle_writes(
        self,
    ):
        # A pre-existing file in a worker-output directory is observed by the
        # readiness session's directory listing; its disappearance during the
        # pre-write window is a directory-membership drift -> BLOCKED with zero
        # net writes. The orphan is a non-``.md`` sidecar so the semantic
        # worker-output row does not flag it (it only evaluates ``.md`` files).
        # ``closure_store`` is the top-level module object the readiness seam
        # resolves ``_require_unchanged_except`` from.
        from revisit_contract import store as closure_store

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            orphan_path = workspace / "scouts" / "orphan-metadata.json"
            orphan_path.write_bytes(b'{"note": "sidecar"}\n')
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_require = closure_store._require_unchanged_except
            calls = []

            def injecting_require(closure, excluded):
                calls.append(1)
                if len(calls) == 1:
                    orphan_path.unlink()
                return real_require(closure, excluded)

            with mock.patch.object(
                closure_store,
                "_require_unchanged_except",
                injecting_require,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            codes = [issue.code for issue in outcome.result.failures]
            self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
            self.assertFalse(orphan_path.exists())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_check_closure_observes_complete_authority_set_once(self):
        # The frozen GenerationClosure observed during preparation is the single
        # authority the check re-checks. The closure's generations cover the
        # complete pre-evaluation authority set and are deduplicated by path
        # (first observation wins), so a drift of any one blocks the check.
        from revisit_contract.generation import (
            DirectoryGeneration,
            FileGeneration,
            GenerationClosure,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_path = root / "workspace" / "evidence" / "current.md"
            artifact_path.parent.mkdir(parents=True)
            artifact_payload = b"Current cycle evidence.\n"
            artifact_path.write_bytes(artifact_payload)
            workspace, cycle_id = make_task6_ready_workspace(
                root,
                current_ref={
                    "kind": "artifact",
                    "path": "evidence/current.md",
                    "sha256": hashlib.sha256(artifact_payload).hexdigest(),
                    "locator": "Current cycle evidence",
                    "checked_at": "2026-07-14T12:00:00Z",
                },
            )
            cycle_relative = f"revisit_cycles/{cycle_id}.json"
            delivered_targets = {
                (Path(directory) / f"loop_{loop_number}_{suffix}.md").as_posix()
                for loop_number in range(8, 11)
                for directory, suffix in (
                    ("scouts", "scout"),
                    ("challenges", "challenge"),
                )
            }
            expected_file_authorities = {
                revisit_contract.POINTER_FILENAME,
                "reports/final.md",
                cycle_relative,
                "sources_index.jsonl",
                "sources/src-001.md",
                "dispatch_log.jsonl",
                "state.json",
                "frontier_registry.json",
                "evidence_ledger.md",
                "search_log.jsonl",
                "research_workflow.md",
                "framing_contract.json",
                "claim_ledger.md",
                "evidence/current.md",
                *delivered_targets,
            }
            captured: list[GenerationClosure] = []
            real_require_unchanged = GenerationClosure.require_unchanged

            def capturing_require_unchanged(self):
                captured.append(self)
                return real_require_unchanged(self)

            with mock.patch.object(
                GenerationClosure,
                "require_unchanged",
                capturing_require_unchanged,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.TRANSITIONED, outcome.effect)
            # The readiness seam re-checks the closure exactly once.
            self.assertEqual(1, len(captured))
            closure = captured[0]
            # Build the path->generation count; a duplicate path would mean the
            # closure re-checks the same authority twice (a redundant capture).
            file_generation_paths = [
                gen.relative_path
                for gen in closure.generations
                if isinstance(gen, FileGeneration)
            ]
            path_counts: dict[str, int] = {}
            for path in file_generation_paths:
                path_counts[path] = path_counts.get(path, 0) + 1
            # Each expected file authority has a generation...
            observed_files = set(path_counts)
            for path in expected_file_authorities:
                self.assertIn(
                    path,
                    observed_files,
                    f"closure did not observe authority: {path}",
                )
            # ...and exactly ONE generation per path (deduplicated capture).
            duplicated = {
                path: n for path, n in path_counts.items() if n > 1
            }
            self.assertEqual({}, duplicated, duplicated)

    def test_check_closure_deduplicates_source_excerpt_artifact(self):
        # When a source excerpt is ALSO referenced as an artifact evidence ref
        # (same path), the closure observes ONE generation for it (no duplicate
        # capture/recheck), so a single drift of that path is detected once.
        from revisit_contract.generation import (
            FileGeneration,
            GenerationClosure,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            source_payload = (
                b"Archived source excerpt for the qualification milestone.\n"
            )
            workspace, cycle_id = make_task6_ready_workspace(
                Path(temp_dir),
                current_ref={
                    "kind": "artifact",
                    "path": "sources/src-001.md",
                    "sha256": hashlib.sha256(source_payload).hexdigest(),
                    "locator": "Qualification milestone excerpt",
                    "checked_at": "2026-07-14T12:00:00Z",
                },
            )
            captured: list[GenerationClosure] = []
            real_require_unchanged = GenerationClosure.require_unchanged

            def capturing_require_unchanged(self):
                captured.append(self)
                return real_require_unchanged(self)

            with mock.patch.object(
                GenerationClosure,
                "require_unchanged",
                capturing_require_unchanged,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.TRANSITIONED, outcome.effect)
            closure = captured[0]
            src_excerpt_generations = [
                gen
                for gen in closure.generations
                if isinstance(gen, FileGeneration)
                and gen.relative_path == "sources/src-001.md"
            ]
            self.assertEqual(
                1,
                len(src_excerpt_generations),
                "closure must deduplicate the source-excerpt/artifact path",
            )

    def test_check_rejects_delivered_worker_path_drift_before_ready_persistence(self):
        # ``closure_store`` is the top-level module object the readiness seam
        # resolves ``_require_unchanged_except`` from.
        from revisit_contract import store as closure_store

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            delivery = workspace / "scouts" / "loop_8_scout.md"
            drifted_delivery = delivery.read_bytes() + b"post-evaluation drift\n"
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_require = closure_store._require_unchanged_except
            calls = []

            def injecting_require(closure, excluded):
                calls.append(1)
                if len(calls) == 2:
                    delivery.write_bytes(drifted_delivery)
                return real_require(closure, excluded)

            with mock.patch.object(
                closure_store,
                "_require_unchanged_except",
                injecting_require,
            ):
                outcome = check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-16T12:00:00Z",
                )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            codes = [issue.code for issue in outcome.result.failures]
            self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
            self.assertEqual(drifted_delivery, delivery.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_check_rejects_intake_authority_byte_drift_without_cycle_writes(self):
        # ``closure_store`` is the top-level module object the readiness seam
        # resolves ``_require_unchanged_except`` from.
        from revisit_contract import store as closure_store

        for relative_path in ("framing_contract.json", "claim_ledger.md"):
            with (
                self.subTest(relative_path=relative_path),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                authority = workspace / relative_path
                drifted = authority.read_bytes() + b"post-evaluation drift\n"
                cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
                mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
                prior_cycle = cycle_path.read_bytes()
                prior_mirror = mirror_path.read_bytes()
                real_require = closure_store._require_unchanged_except
                calls = []

                def injecting_require(closure, excluded):
                    calls.append(1)
                    if len(calls) == 2:
                        authority.write_bytes(drifted)
                    return real_require(closure, excluded)

                with mock.patch.object(
                    closure_store,
                    "_require_unchanged_except",
                    injecting_require,
                ):
                    outcome = check_revisit_readiness(
                        workspace,
                        cycle_id,
                        timestamp="2026-07-16T12:00:00Z",
                    )

                self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
                codes = [issue.code for issue in outcome.result.failures]
                self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
                self.assertEqual(drifted, authority.read_bytes())
                self.assertEqual(prior_cycle, cycle_path.read_bytes())
                self.assertEqual(prior_mirror, mirror_path.read_bytes())

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_check_rejects_intake_authority_retarget_without_cycle_writes(self):
        # ``closure_store`` is the top-level module object the readiness seam
        # resolves ``_require_unchanged_except`` from.
        from revisit_contract import store as closure_store

        for relative_path in ("framing_contract.json", "claim_ledger.md"):
            with (
                self.subTest(relative_path=relative_path),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                authority = workspace / relative_path
                first_target = authority.with_name(
                    f"{authority.stem}-first{authority.suffix}"
                )
                second_target = authority.with_name(
                    f"{authority.stem}-second{authority.suffix}"
                )
                payload = authority.read_bytes()
                authority.replace(first_target)
                second_target.write_bytes(payload)
                authority.symlink_to(first_target.name)
                cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
                mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
                prior_cycle = cycle_path.read_bytes()
                prior_mirror = mirror_path.read_bytes()
                real_require = closure_store._require_unchanged_except
                calls = []

                def injecting_require(closure, excluded):
                    calls.append(1)
                    if len(calls) == 2:
                        authority.unlink()
                        authority.symlink_to(second_target.name)
                    return real_require(closure, excluded)

                with mock.patch.object(
                    closure_store,
                    "_require_unchanged_except",
                    injecting_require,
                ):
                    outcome = check_revisit_readiness(
                        workspace,
                        cycle_id,
                        timestamp="2026-07-16T12:00:00Z",
                    )

                self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
                codes = [issue.code for issue in outcome.result.failures]
                self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
                self.assertEqual(second_target.resolve(), authority.resolve())
                self.assertEqual(payload, first_target.read_bytes())
                self.assertEqual(payload, second_target.read_bytes())
                self.assertEqual(prior_cycle, cycle_path.read_bytes())
                self.assertEqual(prior_mirror, mirror_path.read_bytes())


class TestRevisitDerivedClaimMutation(unittest.TestCase):
    @staticmethod
    def write_request(root, name, request):
        path = root / name
        path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_add_derived_claim_cli_grammar_and_model_surface_exist(self):
        operation = getattr(revisit_contract, "add_derived_claim", None)
        self.assertTrue(callable(operation), "add_derived_claim export is missing")
        args = revisit_cycle_cli.build_parser().parse_args(
            [
                "workspace",
                "add-derived-claim",
                "RC-0001",
                "--request-file",
                "request.json",
            ]
        )
        self.assertEqual("RC-0001", args.cycle)
        self.assertEqual("request.json", args.request_file)
        self.assertIs(revisit_cycle_cli.command_add_derived_claim, args.handler)

    def test_emergent_claim_requires_exact_matching_delivered_dispatch_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            request = make_emergent_claim_request()
            request["accepted_from"]["loop_id"] = "loop_11"
            request_path = self.write_request(root, "emergent-claim.json", request)
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(result.stderr, r"dispatch.*loop_11|loop_11.*dispatch")
            self.assertEqual(before, snapshot_tree(workspace))

    def test_valid_emergent_claim_records_stable_id_pending_resolution_and_one_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            request = make_emergent_claim_request()
            original_request = copy.deepcopy(request)
            request_path = self.write_request(root, "emergent-claim.json", request)
            before = revisit_contract.load_cycle(workspace, cycle_id)

            result = run_revisit_cycle_cli(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("DERIVED CLAIM ADDED: RC-0001-DC-01", result.stdout)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                {
                    "claim_id": "RC-0001-DC-01",
                    **original_request,
                },
                cycle["derived_claims"][0],
            )
            self.assertEqual(
                {
                    "claim_id": "RC-0001-DC-01",
                    "status": "cycle-pending-validation",
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
                },
                cycle["claim_resolutions"][1],
            )
            self.assertEqual(len(before["audit"]) + 1, len(cycle["audit"]))
            self.assertEqual("add-derived-claim", cycle["audit"][-1]["command"])
            self.assertEqual(
                ["RC-0001-DC-01"], cycle["audit"][-1]["affected_ids"]
            )
            self.assertEqual(original_request, request)
            self.assertIn(
                "RC-0001-DC-01",
                (workspace / "revisit_cycles" / "RC-0001.md").read_text(
                    encoding="utf-8"
                ),
            )

    def test_emergent_claim_accepts_unrelated_exact_artifact_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            artifact = workspace / "evidence" / "accepted-filing.md"
            artifact.parent.mkdir()
            artifact.write_text(
                "Independent accepted evidence.\n", encoding="utf-8"
            )
            request = make_emergent_claim_request()
            request["accepted_from"]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "evidence/accepted-filing.md",
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "locator": "Independent accepted evidence",
                    "checked_at": "2026-07-14T12:00:00Z",
                }
            ]
            request_path = self.write_request(
                root, "unrelated-artifact-evidence.json", request
            )
            before = revisit_contract.load_cycle(workspace, cycle_id)

            result = run_revisit_cycle_cli(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                request["accepted_from"]["evidence_refs"],
                cycle["derived_claims"][0]["accepted_from"]["evidence_refs"],
            )
            self.assertEqual(len(before["audit"]) + 1, len(cycle["audit"]))

    def test_emergent_claim_rejects_unaccepted_provenance_with_zero_writes(self):
        cases = (
            ("undelivered", "dispatch", r"dispatch.*delivered"),
            ("missing_delivery", "delivery", r"delivery.*(missing|file)"),
            ("unknown_source", "source", r"source_id.*src-999"),
            ("empty_rationale", "request", r"acceptance_rationale.*non-empty"),
            ("duplicate_dispatch", "dispatch", r"dispatch.*(multiple|unique|duplicate)"),
        )
        for name, _authority, pattern in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                workspace, cycle_id = make_task5_mutation_workspace(root)
                request = make_emergent_claim_request()
                dispatch_path = workspace / "dispatch_log.jsonl"
                if name == "undelivered":
                    record = json.loads(dispatch_path.read_text(encoding="utf-8"))
                    record["status"] = "queued"
                    dispatch_path.write_text(
                        json.dumps(record) + "\n", encoding="utf-8"
                    )
                elif name == "missing_delivery":
                    (workspace / "scouts" / "loop_10_scout.md").unlink()
                elif name == "unknown_source":
                    request["accepted_from"]["evidence_refs"][0][
                        "source_id"
                    ] = "src-999"
                elif name == "empty_rationale":
                    request["acceptance_rationale"] = ""
                else:
                    dispatch_path.write_text(
                        dispatch_path.read_text(encoding="utf-8") * 2,
                        encoding="utf-8",
                    )
                request_path = self.write_request(
                    root, f"{name}-claim.json", request
                )
                before = snapshot_tree(workspace)

                result = run_revisit_cycle_cli(
                    workspace,
                    "add-derived-claim",
                    cycle_id,
                    "--request-file",
                    str(request_path),
                )

                self.assertNotEqual(0, result.returncode)
                self.assertRegex(result.stderr, pattern)
                self.assertEqual(before, snapshot_tree(workspace))

    def _assert_worker_delivery_artifact_rejected(self, *, alias: bool) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            delivery = workspace / "scouts" / "loop_10_scout.md"
            evidence_path = delivery
            form = "same-path"
            if alias:
                form = "resolved-alias"
                evidence_path = workspace / "evidence" / "delivery-alias.md"
                evidence_path.parent.mkdir()
                evidence_path.symlink_to(
                    Path("..") / "scouts" / "loop_10_scout.md"
                )
            request = make_emergent_claim_request()
            request["accepted_from"]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": evidence_path.relative_to(workspace).as_posix(),
                    "sha256": hashlib.sha256(delivery.read_bytes()).hexdigest(),
                    "locator": "Entire worker delivery",
                    "checked_at": "2026-07-14T12:00:00Z",
                }
            ]
            request_path = self.write_request(
                root, f"worker-delivery-{form}.json", request
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(
                result.stderr,
                r"worker delivery.*provenance|provenance.*worker delivery",
            )
            self.assertEqual(before, snapshot_tree(workspace))
            self.assertEqual(
                [], revisit_contract.load_cycle(workspace, cycle_id)["derived_claims"]
            )

    def test_emergent_claim_rejects_delivery_as_artifact_evidence_without_writes(
        self,
    ):
        self._assert_worker_delivery_artifact_rejected(alias=False)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_emergent_claim_rejects_delivery_alias_as_artifact_evidence_without_writes(
        self,
    ):
        self._assert_worker_delivery_artifact_rejected(alias=True)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_emergent_dispatch_delivery_keeps_declared_lexical_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            delivery = workspace / "scouts" / "loop_10_scout.md"
            first_target = workspace / "scouts" / "delivery-first.md"
            second_target = workspace / "scouts" / "delivery-second.md"
            payload = delivery.read_bytes()
            delivery.replace(first_target)
            second_target.write_bytes(payload)
            delivery.symlink_to(first_target.name)
            request = make_emergent_claim_request()
            request_path = self.write_request(root, "emergent-claim.json", request)
            json_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_json = json_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_validate = revisit_cycle_cli._validate_evidence_references

            def validate_then_retarget(*args, **kwargs):
                result = real_validate(*args, **kwargs)
                delivery.unlink()
                delivery.symlink_to(second_target.name)
                return result

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_validate_evidence_references",
                    side_effect=validate_then_retarget,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "add-derived-claim",
                        cycle_id,
                        "--request-file",
                        str(request_path),
                    ]
                )

            self.assertEqual(2, result, stderr.getvalue())
            self.assertRegex(stderr.getvalue(), "authority target changed")
            self.assertEqual(second_target.resolve(), delivery.resolve())
            self.assertEqual(prior_json, json_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_split_children_are_copy_on_write_monotonic_and_non_recursive(self):
        operation = getattr(revisit_contract, "add_derived_claim", None)
        self.assertTrue(callable(operation), "add_derived_claim export is missing")
        cycle = make_minimal_cycle()
        existing_request = {
            "origin": "split_child",
            "statement": "Existing customer B child.",
            "derived_from": "RC-0001-CL-01",
            "accepted_from": None,
            "acceptance_rationale": "The selected proposition combined customers.",
        }
        cycle["derived_claims"].append(
            {"claim_id": "RC-0001-DC-02", **copy.deepcopy(existing_request)}
        )
        cycle["claim_resolutions"].append(
            {
                "claim_id": "RC-0001-DC-02",
                "status": "cycle-pending-validation",
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
        attach_valid_audit(cycle)
        request = {
            "origin": "split_child",
            "statement": "Qualification completes for customer A inside the revised window.",
            "derived_from": "RC-0001-CL-01",
            "accepted_from": None,
            "acceptance_rationale": (
                "The inherited proposition combined two independently testable customers."
            ),
        }
        original_cycle = copy.deepcopy(cycle)
        original_request = copy.deepcopy(request)

        updated = operation(cycle, request)

        self.assertEqual(2, len(updated["derived_claims"]))
        self.assertEqual("RC-0001-DC-03", updated["derived_claims"][-1]["claim_id"])
        self.assertEqual(
            "inherited-pending-reverification",
            updated["claim_resolutions"][0]["status"],
        )
        self.assertEqual(original_cycle, cycle)
        self.assertEqual(original_request, request)

        recursive = copy.deepcopy(request)
        recursive["derived_from"] = "RC-0001-DC-02"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "selected inherited claim",
        ):
            operation(cycle, recursive)

    def test_persisted_derived_claim_number_zero_is_rejected(self):
        cycle = make_minimal_cycle()
        cycle["derived_claims"] = [
            {
                "claim_id": "RC-0001-DC-00",
                "origin": "split_child",
                "statement": "An invalid zero-numbered child.",
                "derived_from": "RC-0001-CL-01",
                "accepted_from": None,
                "acceptance_rationale": "The invalid ID must not become canonical.",
            }
        ]
        cycle["claim_resolutions"].append(
            {
                "claim_id": "RC-0001-DC-00",
                "status": "cycle-pending-validation",
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
        attach_valid_audit(cycle)

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            r"derived_claims\[0\]\.claim_id.*01.*99",
        ):
            revisit_contract.validate_cycle(cycle)

    def test_derived_claim_id_space_exhaustion_is_copy_on_write(self):
        cycle = make_minimal_cycle()
        existing_request = {
            "origin": "split_child",
            "statement": "The final available derived claim.",
            "derived_from": "RC-0001-CL-01",
            "accepted_from": None,
            "acceptance_rationale": "The selected proposition required a child.",
        }
        cycle["derived_claims"].append(
            {"claim_id": "RC-0001-DC-99", **copy.deepcopy(existing_request)}
        )
        cycle["claim_resolutions"].append(
            {
                "claim_id": "RC-0001-DC-99",
                "status": "cycle-pending-validation",
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
        attach_valid_audit(cycle)
        request = {
            **existing_request,
            "statement": "No derived claim ID remains available.",
        }
        original_cycle = copy.deepcopy(cycle)
        original_request = copy.deepcopy(request)

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "derived claim ID space is exhausted",
        ):
            revisit_contract.add_derived_claim(cycle, request)

        self.assertEqual(original_cycle, cycle)
        self.assertEqual(original_request, request)


class TestRevisitClaimResolutionMutation(unittest.TestCase):
    def test_resolve_claim_cli_grammar_and_model_surface_exist(self):
        operation = getattr(revisit_contract, "resolve_claim", None)
        self.assertTrue(callable(operation), "resolve_claim export is missing")
        args = revisit_cycle_cli.build_parser().parse_args(
            [
                "workspace",
                "resolve-claim",
                "RC-0001",
                "RC-0001-CL-01",
                "--resolution-file",
                "resolution.json",
            ]
        )
        self.assertEqual("RC-0001", args.cycle)
        self.assertEqual("RC-0001-CL-01", args.claim)
        self.assertEqual("resolution.json", args.resolution_file)
        self.assertIs(revisit_cycle_cli.command_resolve_claim, args.handler)

    def test_confirmed_resolution_is_copy_on_write_audited_and_persisted_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            bind_selected_claim_for_task5(workspace, cycle_id)
            outcome = make_confirmed_resolution_request()
            outcome_path = root / "confirmed-resolution.json"
            outcome_path.write_text(
                json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = revisit_contract.load_cycle(workspace, cycle_id)

            result = run_revisit_cycle_cli(
                workspace,
                "resolve-claim",
                cycle_id,
                f"{cycle_id}-CL-01",
                "--resolution-file",
                str(outcome_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("CLAIM RESOLVED: RC-0001-CL-01 (confirmed)", result.stdout)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                {"claim_id": "RC-0001-CL-01", **outcome},
                cycle["claim_resolutions"][0],
            )
            self.assertEqual(len(before["audit"]) + 1, len(cycle["audit"]))
            self.assertEqual("resolve-claim", cycle["audit"][-1]["command"])
            self.assertEqual(
                ["RC-0001-CL-01"], cycle["audit"][-1]["affected_ids"]
            )

    def test_blocked_resolution_rejects_current_grade_and_confidence_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            bind_selected_claim_for_task5(workspace, cycle_id)
            outcome = {
                "status": "blocked",
                "revised_statement": None,
                "current_evidence_refs": [],
                "counter_evidence_refs": [],
                "current_grade": "B",
                "current_confidence": "medium",
                "bound_frontier_ids": ["F1"],
                "rationale": "The required public proof remains unavailable.",
                "missing_proof": "A named customer acceptance filing.",
                "attempted_loop_ids": ["loop_10"],
                "attempted_search_refs": [
                    {"loop_id": "loop_10", "query": "customer acceptance filing"}
                ],
                "verdict_impact": "The action class cannot be upgraded.",
                "split_child_ids": [],
            }
            outcome_path = root / "blocked-resolution.json"
            outcome_path.write_text(
                json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "resolve-claim",
                cycle_id,
                f"{cycle_id}-CL-01",
                "--resolution-file",
                str(outcome_path),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(
                result.stderr,
                r"blocked.*(current_grade|current_confidence)|"
                r"(current_grade|current_confidence).*blocked",
            )
            self.assertEqual(before, snapshot_tree(workspace))

    def test_exact_stale_or_unknown_inherited_ref_cannot_be_current_support(self):
        for freshness in ("stale", "unknown"):
            with self.subTest(freshness=freshness), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                workspace, cycle_id = make_task5_mutation_workspace(root)
                bind_selected_claim_for_task5(workspace, cycle_id)
                cycle = revisit_contract.load_cycle(workspace, cycle_id)
                inherited = cycle["intake"]["selected_claims"][0][
                    "inherited_evidence"
                ][0]
                inherited["freshness"] = freshness
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                attach_valid_audit(cycle)
                revisit_contract.persist_cycle(
                    workspace,
                    cycle,
                    expected_sha256=revisit_contract.sha256_file(
                        workspace / "revisit_cycles" / f"{cycle_id}.json"
                    ),
                )
                outcome = make_confirmed_resolution_request()
                outcome["current_evidence_refs"] = [
                    copy.deepcopy(inherited["ref"])
                ]
                outcome_path = root / f"{freshness}-inherited-resolution.json"
                outcome_path.write_text(
                    json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                before = snapshot_tree(workspace)

                result = run_revisit_cycle_cli(
                    workspace,
                    "resolve-claim",
                    cycle_id,
                    f"{cycle_id}-CL-01",
                    "--resolution-file",
                    str(outcome_path),
                )

                self.assertNotEqual(0, result.returncode)
                self.assertRegex(result.stderr, rf"{freshness}.*current|current.*{freshness}")
                self.assertEqual(before, snapshot_tree(workspace))

    def test_new_checked_at_can_reaccept_the_same_source_as_current_support(self):
        cycle = make_bound_model_cycle()
        cycle["intake"]["selected_claims"][0]["inherited_evidence"] = [
            {
                "ref": {
                    "kind": "source",
                    "source_id": "src-002",
                    "checked_at": "2026-07-14T10:00:00Z",
                },
                "freshness": "stale",
                "checked_at": "2026-07-14T10:00:00Z",
                "reason": "The source predates the current acceptance check.",
            }
        ]
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)
        outcome = make_confirmed_resolution_request()
        outcome["current_evidence_refs"][0]["checked_at"] = "2026-07-14T12:00:00Z"

        proposed = revisit_contract.resolve_claim(
            cycle, "RC-0001-CL-01", outcome
        )

        self.assertEqual("confirmed", proposed["claim_resolutions"][0]["status"])

    def test_terminal_outcome_matrix_accepts_only_its_named_fields(self):
        operation = revisit_contract.resolve_claim
        base = make_confirmed_resolution_request()
        weakened = copy.deepcopy(base)
        weakened.update(
            {
                "status": "weakened",
                "revised_statement": (
                    "Qualification completes for customer A inside the revised window."
                ),
                "counter_evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T12:00:00Z",
                    }
                ],
            }
        )
        refuted = copy.deepcopy(base)
        refuted.update(
            {
                "status": "refuted",
                "current_evidence_refs": [],
                "counter_evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T12:00:00Z",
                    }
                ],
                "current_grade": None,
                "current_confidence": None,
                "rationale": "Current counter-evidence defeats the proposition.",
            }
        )
        blocked = copy.deepcopy(base)
        blocked.update(
            {
                "status": "blocked",
                "current_evidence_refs": [],
                "current_grade": None,
                "current_confidence": None,
                "rationale": "The required public proof remains unavailable.",
                "missing_proof": "A named customer acceptance filing.",
                "attempted_loop_ids": ["loop_10"],
                "attempted_search_refs": [
                    {"loop_id": "loop_10", "query": "customer acceptance filing"}
                ],
                "verdict_impact": "The action class cannot be upgraded.",
            }
        )
        for outcome in (base, weakened, refuted, blocked):
            with self.subTest(status=outcome["status"]):
                cycle = make_bound_model_cycle()
                original = copy.deepcopy(cycle)
                updated = operation(cycle, "RC-0001-CL-01", outcome)
                self.assertEqual(
                    outcome["status"], updated["claim_resolutions"][0]["status"]
                )
                self.assertEqual(original, cycle)

        invalid_cases = (
            (
                "confirmed counter",
                lambda outcome: outcome.update(
                    {"counter_evidence_refs": copy.deepcopy(refuted["counter_evidence_refs"])}
                ),
                "confirmed.*counter_evidence_refs",
            ),
            (
                "weakened revision",
                lambda outcome: outcome.update(
                    {"status": "weakened", "revised_statement": None,
                     "counter_evidence_refs": copy.deepcopy(refuted["counter_evidence_refs"])}
                ),
                "weakened.*revised_statement",
            ),
            (
                "refuted grade",
                lambda outcome: outcome.update(
                    {"status": "refuted", "current_evidence_refs": [],
                     "counter_evidence_refs": copy.deepcopy(refuted["counter_evidence_refs"])}
                ),
                "refuted.*current_grade",
            ),
            (
                "undeclared frontier",
                lambda outcome: outcome.update({"bound_frontier_ids": ["F2"]}),
                "F2.*declared|declared.*F2",
            ),
            (
                "no current evidence",
                lambda outcome: outcome.update({"current_evidence_refs": []}),
                "confirmed.*current_evidence_refs",
            ),
        )
        for name, mutate, pattern in invalid_cases:
            with self.subTest(invalid=name):
                outcome = make_confirmed_resolution_request()
                mutate(outcome)
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, pattern
                ):
                    operation(make_bound_model_cycle(), "RC-0001-CL-01", outcome)

    def test_split_requires_two_registered_siblings_and_terminal_rows_are_one_time(self):
        cycle = make_bound_model_cycle()
        for number, statement in ((1, "Customer A qualifies."), (2, "Customer B qualifies.")):
            claim_id = f"RC-0001-DC-{number:02d}"
            cycle["derived_claims"].append(
                {
                    "claim_id": claim_id,
                    "origin": "split_child",
                    "statement": statement,
                    "derived_from": "RC-0001-CL-01",
                    "accepted_from": None,
                    "acceptance_rationale": "The parent combined two customers.",
                }
            )
            cycle["claim_resolutions"].append(
                {
                    "claim_id": claim_id,
                    "status": "cycle-pending-validation",
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
        attach_valid_audit(cycle)
        split = {
            key: copy.deepcopy(value)
            for key, value in make_confirmed_resolution_request().items()
        }
        split.update(
            {
                "status": "split",
                "current_evidence_refs": [],
                "current_grade": None,
                "current_confidence": None,
                "bound_frontier_ids": [],
                "rationale": None,
                "split_child_ids": ["RC-0001-DC-01", "RC-0001-DC-02"],
            }
        )

        proposed = revisit_contract.resolve_claim(
            cycle, "RC-0001-CL-01", split
        )
        self.assertEqual("split", proposed["claim_resolutions"][0]["status"])

        one_child = copy.deepcopy(split)
        one_child["split_child_ids"] = ["RC-0001-DC-01"]
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "split.*at least two"
        ):
            revisit_contract.resolve_claim(cycle, "RC-0001-CL-01", one_child)

        terminal = revisit_model.with_audit(
            cycle,
            proposed,
            "resolve-claim",
            ["RC-0001-CL-01"],
            "2026-07-15T00:20:00Z",
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "already terminal"
        ):
            revisit_contract.resolve_claim(
                terminal, "RC-0001-CL-01", split
            )

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "selected inherited claim"
        ):
            revisit_contract.resolve_claim(
                cycle, "RC-0001-DC-01", split
            )

    def test_resolution_request_is_exact_and_only_terminal_states_are_allowed(self):
        cycle = make_bound_model_cycle()
        outcome = make_confirmed_resolution_request()
        outcome["hidden"] = "authority"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "unknown field.*hidden"
        ):
            revisit_contract.resolve_claim(cycle, "RC-0001-CL-01", outcome)

        nonterminal = make_confirmed_resolution_request()
        nonterminal["status"] = "cycle-pending-validation"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "terminal claim state"
        ):
            revisit_contract.resolve_claim(
                cycle, "RC-0001-CL-01", nonterminal
            )


class TestRevisitDecisionAssessmentMutation(unittest.TestCase):
    def test_assessment_cli_grammar_and_model_surfaces_exist(self):
        for name in (
            "assess_decision",
            "derive_change_class",
            "derive_rerun_requirements",
        ):
            self.assertTrue(
                callable(getattr(revisit_contract, name, None)),
                f"{name} export is missing",
            )
        args = revisit_cycle_cli.build_parser().parse_args(
            [
                "workspace",
                "assess-decision",
                "RC-0001",
                "--assessment-file",
                "assessment.json",
            ]
        )
        self.assertEqual("RC-0001", args.cycle)
        self.assertEqual("assessment.json", args.assessment_file)
        self.assertIs(revisit_cycle_cli.command_assess_decision, args.handler)

    def test_valid_assessment_derives_evidence_only_rerun_and_one_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_assessment_workspace(root)
            assessment = make_decision_assessment_request()
            assessment_path = root / "assessment.json"
            assessment_path.write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = revisit_contract.load_cycle(workspace, cycle_id)

            result = run_revisit_cycle_cli(
                workspace,
                "assess-decision",
                cycle_id,
                "--assessment-file",
                str(assessment_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("DECISION ASSESSED: RC-0001", result.stdout)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                {
                    **assessment,
                    "change_class": "evidence_or_claim_only",
                    "required_reruns": ["delta-frontier-review"],
                },
                cycle["decision_assessment"],
            )
            self.assertEqual(len(before["audit"]) + 1, len(cycle["audit"]))
            self.assertEqual("assess-decision", cycle["audit"][-1]["command"])
            self.assertEqual([cycle_id], cycle["audit"][-1]["affected_ids"])

    def test_blocked_claim_cannot_be_used_as_positive_support_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blocked = make_blocked_resolution("RC-0001-CL-01", "F1")
            blocked.pop("claim_id")
            workspace, cycle_id = make_assessment_workspace(
                root, outcome=blocked
            )
            assessment = make_decision_assessment_request()
            assessment["blocked_claim_ids"] = ["RC-0001-CL-01"]
            assessment_path = root / "blocked-support-assessment.json"
            assessment_path.write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "assess-decision",
                cycle_id,
                "--assessment-file",
                str(assessment_path),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(result.stderr, r"blocked.*positive|positive.*blocked")
            self.assertEqual(before, snapshot_tree(workspace))

    def test_positive_support_accepts_only_confirmed_or_weakened_claims(self):
        cases = (
            ("pending", make_bound_model_cycle()),
            ("refuted", make_terminal_model_cycle("refuted")),
            ("blocked", make_terminal_model_cycle("blocked")),
            ("split", make_split_terminal_model_cycle()),
        )
        for status, cycle in cases:
            with self.subTest(status=status):
                assessment = make_decision_assessment_request()
                if status == "blocked":
                    assessment["blocked_claim_ids"] = ["RC-0001-CL-01"]
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    rf"{status}.*positive|positive.*{status}|all.*terminal",
                ):
                    revisit_contract.assess_decision(cycle, assessment)

    def test_assessment_requires_all_terminal_claims_and_exact_blocked_set(self):
        confirmed = make_terminal_model_cycle("confirmed")
        pending_request = {
            "origin": "emergent",
            "statement": "A newly accepted packaging constraint matters.",
            "derived_from": None,
            "accepted_from": {
                "loop_id": "loop_10",
                "dispatch_id": "dispatch_0010_scout",
                "evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-002",
                        "checked_at": "2026-07-14T12:00:00Z",
                    }
                ],
            },
            "acceptance_rationale": "The main thread accepted the cited constraint.",
        }
        pending = revisit_contract.add_derived_claim(confirmed, pending_request)
        pending = revisit_model.with_audit(
            confirmed,
            pending,
            "add-derived-claim",
            ["RC-0001-DC-01"],
            "2026-07-15T00:30:00Z",
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "all.*terminal|pending"
        ):
            revisit_contract.assess_decision(
                pending, make_decision_assessment_request()
            )

        blocked = make_terminal_model_cycle("blocked")
        omitted = make_decision_assessment_request()
        omitted["supporting_claim_ids"] = []
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "blocked_claim_ids.*exact",
        ):
            revisit_contract.assess_decision(blocked, omitted)

        exact = copy.deepcopy(omitted)
        exact["blocked_claim_ids"] = ["RC-0001-CL-01"]
        proposed = revisit_contract.assess_decision(blocked, exact)
        self.assertEqual(["RC-0001-CL-01"], proposed["decision_assessment"]["blocked_claim_ids"])
        audited = revisit_model.with_audit(
            blocked,
            proposed,
            "assess-decision",
            ["RC-0001"],
            "2026-07-15T00:31:00Z",
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "already recorded"
        ):
            revisit_contract.assess_decision(audited, exact)

    def test_assessment_support_may_be_a_subset_of_terminal_positive_claims(self):
        cycle = make_populated_cycle()
        cycle["decision_assessment"] = None
        cycle["rerun_artifacts"] = []
        cycle["report_candidate"] = None
        cycle["status"] = "active"
        attach_valid_audit(cycle)

        proposed = revisit_contract.assess_decision(
            cycle, make_decision_assessment_request()
        )

        self.assertEqual(
            ["RC-0001-CL-01"],
            proposed["decision_assessment"]["supporting_claim_ids"],
        )
        self.assertEqual(
            "confirmed",
            next(
                resolution["status"]
                for resolution in proposed["claim_resolutions"]
                if resolution["claim_id"] == "RC-0001-DC-01"
            ),
        )

    def test_exact_derivation_rows_and_inconsistent_persisted_values_are_rejected(self):
        rows = (
            (
                "evidence_or_claim_only",
                {},
                ("delta-frontier-review",),
            ),
            (
                "financial_or_risk_change",
                {"financial_bridge_affected": True},
                ("delta-frontier-review", "affected-financial-bridge"),
            ),
            (
                "action_class_change",
                {"new_action_class": "Act"},
                (
                    "delta-frontier-review",
                    "full-financial-bridge",
                    "redteam-round-1",
                    "redteam-defense-1",
                    "redteam-round-2",
                    "redteam-defense-2",
                    "thesis-revision",
                ),
            ),
        )
        for expected_class, overrides, expected_reruns in rows:
            with self.subTest(change_class=expected_class):
                cycle = make_terminal_model_cycle("confirmed")
                assessment = make_decision_assessment_request()
                assessment.update(overrides)
                proposed = revisit_contract.assess_decision(cycle, assessment)
                self.assertEqual(
                    expected_class,
                    revisit_contract.derive_change_class(proposed),
                )
                self.assertEqual(
                    expected_reruns,
                    revisit_contract.derive_rerun_requirements(proposed),
                )
                self.assertEqual(
                    list(expected_reruns),
                    proposed["decision_assessment"]["required_reruns"],
                )

        supplied = make_decision_assessment_request()
        for forbidden in ("change_class", "required_reruns"):
            with self.subTest(forbidden=forbidden):
                request = copy.deepcopy(supplied)
                request[forbidden] = "user-supplied"
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    rf"unknown field.*{forbidden}",
                ):
                    revisit_contract.assess_decision(
                        make_terminal_model_cycle("confirmed"), request
                    )

        valid = make_terminal_model_cycle("confirmed")
        proposed = revisit_contract.assess_decision(
            valid, make_decision_assessment_request()
        )
        audited = revisit_model.with_audit(
            valid,
            proposed,
            "assess-decision",
            ["RC-0001"],
            "2026-07-15T00:32:00Z",
        )
        for field, replacement in (
            ("change_class", "action_class_change"),
            ("required_reruns", ["delta-frontier-review", "full-financial-bridge"]),
        ):
            with self.subTest(inconsistent=field):
                drifted = copy.deepcopy(audited)
                drifted["decision_assessment"][field] = replacement
                attach_valid_audit(drifted)
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    rf"{field}.*derived|derived.*{field}",
                ):
                    revisit_contract.validate_cycle(drifted)

    def test_assessment_scalars_are_strict_and_input_is_not_mutated(self):
        cycle = make_terminal_model_cycle("confirmed")
        assessment = make_decision_assessment_request()
        original_cycle = copy.deepcopy(cycle)
        original_assessment = copy.deepcopy(assessment)
        revisit_contract.assess_decision(cycle, assessment)
        self.assertEqual(original_cycle, cycle)
        self.assertEqual(original_assessment, assessment)

        cases = (
            ("financial_bridge_affected", 1, "must be a boolean"),
            ("risk_class_changed", 0, "must be a boolean"),
            ("financial_bridge_rationale", "", "must be non-empty text"),
            ("risk_class_rationale", "", "must be non-empty text"),
            ("verdict_rationale", "", "must be non-empty text"),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                invalid = make_decision_assessment_request()
                invalid[field] = replacement
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError, pattern
                ):
                    revisit_contract.assess_decision(cycle, invalid)


class TestPointerSchema(unittest.TestCase):
    def assert_contract_error(self, operation, pattern):
        try:
            operation()
        except Exception as error:
            self.assertIsInstance(error, revisit_contract.RevisitContractError)
            self.assertRegex(str(error), pattern)
            return
        self.fail("RevisitContractError not raised")

    def test_contract_error_is_an_explicit_value_error_export(self):
        error_type = getattr(revisit_contract, "RevisitContractError", None)
        self.assertTrue(
            isinstance(error_type, type) and issubclass(error_type, ValueError),
            "RevisitContractError export is missing",
        )

    def test_empty_pointer_is_strict_ticker_schema_v1(self):
        empty_pointer = getattr(revisit_contract, "empty_pointer", None)
        validate_pointer = getattr(revisit_contract, "validate_pointer", None)
        self.assertTrue(callable(empty_pointer), "empty_pointer export is missing")
        self.assertTrue(callable(validate_pointer), "validate_pointer export is missing")
        pointer = empty_pointer()
        self.assertEqual(
            {"schema_version": 1, "mode": "ticker", "current_revision": None},
            pointer,
        )
        self.assertIs(pointer, validate_pointer(pointer))

    def test_pointer_rejects_unknown_fields_without_mutating_input(self):
        pointer = revisit_contract.empty_pointer()
        pointer["hidden_authority"] = {"verdict": "Act"}
        original = copy.deepcopy(pointer)

        with self.assertRaisesRegex(ValueError, "pointer unknown field"):
            revisit_contract.validate_pointer(pointer)

        self.assertEqual(original, pointer)

    def test_pointer_rejects_non_object_input(self):
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer([]),
            "revisit_contract.json must contain an object",
        )

    def test_pointer_schema_version_rejects_bool(self):
        pointer = revisit_contract.empty_pointer()
        pointer["schema_version"] = True
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.schema_version must be an integer >= 1",
        )

    def test_pointer_rejects_unsupported_schema_version(self):
        pointer = revisit_contract.empty_pointer()
        pointer["schema_version"] = 2
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "unsupported pointer schema_version",
        )

    def test_pointer_mode_is_ticker_only(self):
        pointer = revisit_contract.empty_pointer()
        pointer["mode"] = "sector"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "pointer.mode must be ticker",
        )

    def test_current_revision_must_be_an_object_when_present(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = []
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision must be an object",
        )

    def test_current_revision_rejects_unknown_fields_without_mutation(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["hidden_authority"] = True
        original = copy.deepcopy(pointer)

        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision unknown field",
        )

        self.assertEqual(original, pointer)

    def test_current_revision_rejects_malformed_revision_id(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["revision_id"] = "rev-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.revision_id must match REV-NNNN",
        )

    def test_initial_registration_requires_revision_0001(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["revision_id"] = "REV-0002"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "initial registration revision_id must be REV-0001",
        )

    def test_revisit_revision_rejects_malformed_cycle_id(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["cycle_id"] = "RC-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.cycle_id must match RC-NNNN",
        )

    def test_revisit_revision_rejects_malformed_revision_of(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["revision_of"] = "REV-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.revision_of must match REV-NNNN",
        )

    def test_revisit_revision_requires_cycle_and_revision_of_together(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["cycle_id"] = None
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "cycle_id and revision_of must both be null or both be IDs",
        )

    def test_revision_report_path_must_be_non_empty_text(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_path"] = ""
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_path must be non-empty text",
        )

    def test_revision_report_path_rejects_control_characters(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_path"] = "reports/initial\n.md"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_path must not contain control characters",
        )

    def test_revision_report_hash_is_lowercase_sha256(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_sha256"] = "A" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_sha256 must be a lowercase SHA-256",
        )

    def test_revision_action_class_uses_locked_vocabulary(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["action_class"] = "Buy"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.action_class is unsupported",
        )

    def test_revision_validated_at_must_be_non_empty_text(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["validated_at"] = 0
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.validated_at must be non-empty text",
        )

    def test_revision_validated_at_requires_canonical_real_utc_timestamp(self):
        invalid_timestamps = (
            "2026-07-15 00:00:00Z",
            "2026-07-15T00:00:00+00:00",
            "2026-07-15T00:00:00.000Z",
            "2026-02-30T00:00:00Z",
            "２０２６-07-15T00:00:00Z",
        )
        for timestamp in invalid_timestamps:
            with self.subTest(timestamp=timestamp):
                pointer = revisit_contract.empty_pointer()
                pointer["current_revision"] = make_initial_revision()
                pointer["current_revision"]["validated_at"] = timestamp
                self.assert_contract_error(
                    lambda: revisit_contract.validate_pointer(pointer),
                    r"pointer\.current_revision\.validated_at must be YYYY-MM-DDTHH:MM:SSZ",
                )

    def test_pointer_missing_field_is_rejected(self):
        pointer = revisit_contract.empty_pointer()
        del pointer["mode"]
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "pointer missing field.*mode",
        )

    def test_revision_timestamp_rejects_control_characters(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["validated_at"] += "\x00"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.validated_at must not contain control characters",
        )

    def test_valid_initial_and_revisit_revisions_return_the_same_pointer(self):
        for revision in (make_initial_revision(), make_revisit_revision()):
            with self.subTest(revision_id=revision["revision_id"]):
                pointer = revisit_contract.empty_pointer()
                pointer["current_revision"] = revision
                original = copy.deepcopy(pointer)

                self.assertIs(pointer, revisit_contract.validate_pointer(pointer))
                self.assertEqual(original, pointer)

    def test_action_classes_are_the_exact_locked_vocabulary(self):
        self.assertEqual(
            (
                "Act",
                "Watch with Trigger",
                "Trade-only",
                "Basket-only",
                "Reject",
                "Needs Primary Evidence",
            ),
            getattr(revisit_contract, "ACTION_CLASSES", None),
        )


class TestCanonicalPersistedPaths(unittest.TestCase):
    _ERROR_SUFFIX = "must be a canonical workspace-relative POSIX path"
    _UNICODE_PATH = "reports/研究/最终.md"

    @staticmethod
    def _artifact(path):
        return {
            "kind": "artifact",
            "path": path,
            "sha256": "a" * 64,
            "locator": "Evidence locator",
            "checked_at": "2026-07-15T00:00:00Z",
        }

    def _intake_request(self):
        return {
            "triggers": [
                {
                    "kind": "upgrade",
                    "statement": "A named milestone changed.",
                    "observed_at": "2026-07-15",
                    "evidence_refs": [
                        {
                            "kind": "source",
                            "source_id": "src-001",
                            "checked_at": "2026-07-15T00:00:00Z",
                        }
                    ],
                }
            ],
            "selected_claims": [
                {
                    "statement": "The prior claim remains relevant.",
                    "source_ref": {
                        "path": "claims/ledger.md",
                        "sha256": "b" * 64,
                        "locator": "Claim 1",
                        "historical_claim_id": None,
                    },
                    "importance": "critical",
                    "selection_reasons": ["trigger_affected"],
                    "trigger_indexes": [1],
                    "inherited_grade": "A",
                    "inherited_confidence": "high",
                    "inherited_evidence": [],
                }
            ],
        }

    @staticmethod
    def _refresh_cycle(cycle):
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        return attach_valid_audit(cycle)

    def _strict_load_pointer(self, pointer):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            path = workspace / revisit_contract.POINTER_FILENAME
            path.write_bytes(revisit_contract.canonical_document_bytes(pointer))
            before = path.read_bytes()
            try:
                return revisit_contract.load_pointer(workspace)
            finally:
                self.assertEqual(before, path.read_bytes())

    def _strict_load_cycle(self, cycle):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            path = workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json"
            path.parent.mkdir()
            path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
            before = path.read_bytes()
            try:
                return revisit_contract.load_cycle(workspace, "RC-0001")
            finally:
                self.assertEqual(before, path.read_bytes())

    def _owner_cases(self):
        def pointer(path):
            value = revisit_contract.empty_pointer()
            value["current_revision"] = make_initial_revision()
            value["current_revision"]["report_path"] = path
            return value

        def request_source(path):
            value = self._intake_request()
            value["selected_claims"][0]["source_ref"]["path"] = path
            return value

        def request_trigger(path):
            value = self._intake_request()
            value["triggers"][0]["evidence_refs"] = [self._artifact(path)]
            return value

        def request_inherited(path):
            value = self._intake_request()
            value["selected_claims"][0]["inherited_evidence"] = [
                {
                    "ref": self._artifact(path),
                    "freshness": "fresh",
                    "checked_at": "2026-07-15T00:00:00Z",
                    "reason": "The evidence was checked after the trigger.",
                }
            ]
            return value

        def cycle_base(path):
            value = make_minimal_cycle()
            value["intake"]["base_revision"]["report_path"] = path
            return self._refresh_cycle(value)

        def cycle_source(path):
            value = make_minimal_cycle()
            value["intake"]["selected_claims"][0]["source_ref"]["path"] = path
            return self._refresh_cycle(value)

        def cycle_trigger(path):
            value = make_minimal_cycle()
            value["intake"]["triggers"][0]["evidence_refs"] = [
                self._artifact(path)
            ]
            return self._refresh_cycle(value)

        def cycle_inherited(path):
            value = make_minimal_cycle()
            value["intake"]["selected_claims"][0]["inherited_evidence"] = [
                {
                    "ref": self._artifact(path),
                    "freshness": "fresh",
                    "checked_at": value["created_at"],
                    "reason": "The inherited evidence remains current.",
                }
            ]
            return self._refresh_cycle(value)

        def cycle_accepted(path):
            value = make_populated_cycle()
            value["derived_claims"][0]["accepted_from"]["evidence_refs"][0][
                "path"
            ] = path
            return self._refresh_cycle(value)

        def cycle_current(path):
            value = make_populated_cycle()
            value["claim_resolutions"][0]["current_evidence_refs"][0][
                "path"
            ] = path
            return self._refresh_cycle(value)

        def cycle_counter(path):
            value = make_populated_cycle()
            resolution = value["claim_resolutions"][0]
            resolution["status"] = "weakened"
            resolution["revised_statement"] = "The evidence weakens the prior claim."
            resolution["counter_evidence_refs"] = [self._artifact(path)]
            return self._refresh_cycle(value)

        return (
            (
                "pointer-validate",
                "/reports/final.md",
                "pointer.current_revision.report_path",
                pointer,
                revisit_contract.validate_pointer,
            ),
            (
                "pointer-strict-load-drive",
                "C:/reports/final.md",
                "pointer.current_revision.report_path",
                pointer,
                self._strict_load_pointer,
            ),
            (
                "request-selected-source",
                "\\\\server\\share\\final.md",
                "request.selected_claims[0].source_ref.path",
                request_source,
                revisit_contract.validate_intake_request,
            ),
            (
                "request-trigger-artifact",
                "reports\\trigger.md",
                "request.triggers[0].evidence_refs[0].path",
                request_trigger,
                revisit_contract.validate_intake_request,
            ),
            (
                "request-inherited-artifact",
                "evidence/./inherited.md",
                "request.selected_claims[0].inherited_evidence[0].ref.path",
                request_inherited,
                revisit_contract.validate_intake_request,
            ),
            (
                "cycle-base-validate",
                "reports/../initial.md",
                "cycle.intake.base_revision.report_path",
                cycle_base,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-base-strict-load",
                "reports//initial.md",
                "cycle.intake.base_revision.report_path",
                cycle_base,
                self._strict_load_cycle,
            ),
            (
                "cycle-selected-source-validate",
                "claims/selected.md/",
                "cycle.intake.selected_claims[0].source_ref.path",
                cycle_source,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-selected-source-strict-load",
                "/claims/selected.md",
                "cycle.intake.selected_claims[0].source_ref.path",
                cycle_source,
                self._strict_load_cycle,
            ),
            (
                "cycle-trigger-artifact",
                "evidence//trigger.md",
                "cycle.intake.triggers[0].evidence_refs[0].path",
                cycle_trigger,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-inherited-artifact",
                "evidence/../inherited.md",
                "cycle.intake.selected_claims[0].inherited_evidence[0].ref.path",
                cycle_inherited,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-accepted-artifact",
                "C:/evidence/accepted.md",
                "cycle.derived_claims[0].accepted_from.evidence_refs[0].path",
                cycle_accepted,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-current-artifact",
                "evidence\\current.md",
                "cycle.claim_resolutions[0].current_evidence_refs[0].path",
                cycle_current,
                revisit_contract.validate_cycle,
            ),
            (
                "cycle-counter-artifact",
                "//server/share/counter.md",
                "cycle.claim_resolutions[0].counter_evidence_refs[0].path",
                cycle_counter,
                revisit_contract.validate_cycle,
            ),
        )

    def _assert_rejected(self, case):
        label, invalid_path, model_path, build, operation = case
        value = build(invalid_path)
        original = copy.deepcopy(value)
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            rf"^{re.escape(model_path)} {self._ERROR_SUFFIX}$",
        ):
            operation(value)
        self.assertEqual(original, value)

    def test_each_persisted_path_owner_rejects_one_invalid_path_independently(self):
        for case in self._owner_cases():
            label, invalid_path, _, _, _ = case
            with self.subTest(owner=label, path=invalid_path):
                self._assert_rejected(case)

        for case in self._owner_cases():
            label, _, _, build, operation = case
            with self.subTest(owner=label, path=self._UNICODE_PATH):
                value = build(self._UNICODE_PATH)
                original = copy.deepcopy(value)
                operation(value)
                self.assertEqual(original, value)

    def test_each_owner_mutation_makes_its_regression_fail(self):
        original = revisit_model._require_canonical_workspace_relative_posix_path
        for case in self._owner_cases():
            label, _, model_path, _, _ = case

            def bypass_target(value, path, *, target=model_path):
                if path == target:
                    return value
                return original(value, path)

            with self.subTest(owner=label):
                with mock.patch.object(
                    revisit_model,
                    "_require_canonical_workspace_relative_posix_path",
                    side_effect=bypass_target,
                ):
                    with self.assertRaisesRegex(
                        AssertionError, "RevisitContractError not raised"
                    ):
                        self._assert_rejected(case)


class TestRevisitStorePaths(unittest.TestCase):
    def assert_internal_symlink_target_rejected(
        self, target_parent, target_name, pattern
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            reports = workspace / "reports"
            target_directory = workspace / target_parent
            reports.mkdir(parents=True)
            target_directory.mkdir(parents=True, exist_ok=True)
            target = target_directory / target_name
            target.write_bytes(b"authority bytes")
            (reports / "final.md").symlink_to(target)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, pattern
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_resolve_workspace_path_rejects_internal_symlink_parent_and_suffix_change(
        self,
    ):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.json", "resolved path must be under reports/"
        )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_resolve_workspace_path_rejects_internal_symlink_parent_change(self):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.md", "resolved path must be under reports/"
        )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_resolve_workspace_path_rejects_internal_symlink_suffix_change(self):
        self.assert_internal_symlink_target_rejected(
            "reports", "authority.json", "resolved path must end with .md"
        )

    def test_resolve_workspace_path_accepts_real_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            report = workspace / "reports" / "final.md"
            report.parent.mkdir(parents=True)
            report.write_bytes(b"ordinary report")

            self.assertEqual(
                report.resolve(),
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                ),
            )

    def test_resolve_workspace_path_rejects_c1_control_character(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "control-free"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/next\u0085line.md",
                    parent="reports",
                    suffix=".md",
                )

    def test_normalize_workspace_relative_path_preserves_unicode_and_separators(self):
        normalize = getattr(
            revisit_contract, "normalize_workspace_relative_path", None
        )
        self.assertTrue(
            callable(normalize),
            "normalize_workspace_relative_path export is missing",
        )
        self.assertEqual(
            "reports/研究/最终.md",
            normalize("./reports\\研究//最终.md"),
        )

    def test_normalize_workspace_relative_path_rejects_absolute_forms(self):
        cases = (
            "/" + "reports/final.md",
            "C:" + "\\" + "reports\\final.md",
            "C:" + "reports\\final.md",
            "\\" + "reports\\final.md",
            "\\" + "\\" + "server\\share\\reports\\final.md",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for value in cases:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        "absolute workspace path is forbidden",
                    ):
                        revisit_contract.resolve_workspace_path(
                            workspace,
                            value,
                            parent="reports",
                            suffix=".md",
                        )

    def test_normalize_workspace_relative_path_rejects_raw_parent_components(self):
        cases = (
            ".." + "/" + "final.md",
            "reports/" + ".." + "/" + "final.md",
            "reports\\" + ".." + "\\" + "final.md",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for value in cases:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        "contains forbidden '..'",
                    ):
                        revisit_contract.resolve_workspace_path(
                            workspace,
                            value,
                            parent="reports",
                            suffix=".md",
                        )

    def test_resolve_workspace_path_requires_parent_and_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "path must be under reports/"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "other/final.md",
                    parent="reports",
                    suffix=".md",
                )
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "path must end with .md"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.json",
                    parent="reports",
                    suffix=".md",
                )

    def test_resolve_workspace_path_returns_normalized_path_under_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertEqual(
                workspace.resolve() / "reports" / "最终.md",
                revisit_contract.resolve_workspace_path(
                    workspace,
                    ".\\reports\\最终.md",
                    parent="reports",
                    suffix=".md",
                ),
            )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_resolve_workspace_path_rejects_symlink_escape(self):
        resolve_workspace_path = getattr(
            revisit_contract, "resolve_workspace_path", None
        )
        self.assertTrue(
            callable(resolve_workspace_path),
            "resolve_workspace_path export is missing",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "reports").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "escapes workspace"
            ):
                resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                )


class TestRevisitStoreBytes(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def test_canonical_value_bytes_are_compact_sorted_and_unicode(self):
        canonical_value_bytes = self.required_callable("canonical_value_bytes")
        first = {"z": "雪", "a": {"later": 2, "earlier": 1}}
        second = {"a": {"earlier": 1, "later": 2}, "z": "雪"}
        expected = '{"a":{"earlier":1,"later":2},"z":"雪"}'.encode("utf-8")

        self.assertEqual(expected, canonical_value_bytes(first))
        self.assertEqual(expected, canonical_value_bytes(second))
        self.assertNotIn(b"\\u", canonical_value_bytes(first))

    def test_canonical_document_bytes_are_indented_unicode_with_one_newline(self):
        canonical_document_bytes = self.required_callable("canonical_document_bytes")
        document = {"schema_version": 1, "label": "研究"}
        expected = (
            '{\n  "schema_version": 1,\n  "label": "研究"\n}\n'.encode("utf-8")
        )

        payload = canonical_document_bytes(document)

        self.assertEqual(expected, payload)
        self.assertTrue(payload.endswith(b"}\n"))
        self.assertFalse(payload.endswith(b"\n\n"))

    def test_sha256_helpers_hash_exact_raw_bytes(self):
        sha256_bytes = self.required_callable("sha256_bytes")
        sha256_file = self.required_callable("sha256_file")
        payload = "line one\r\n雪\r\n".encode("utf-8")
        expected = hashlib.sha256(payload).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.md"
            path.write_bytes(payload)
            self.assertEqual(expected, sha256_file(path))

        self.assertEqual(expected, sha256_bytes(payload))


class TestRevisitWorkspaceTransaction(unittest.TestCase):
    def start_barrier_cli(self, workspace, ready, release, *arguments):
        child_code = "\n".join(
            (
                "import sys, time",
                "from pathlib import Path",
                "from scripts.revisit_cycle import main",
                "ready, release = map(Path, sys.argv[1:3])",
                "ready.write_text('ready', encoding='utf-8')",
                "deadline = time.monotonic() + 10",
                "while not release.exists():",
                "    if time.monotonic() >= deadline:",
                "        raise RuntimeError('barrier release timed out')",
                "    time.sleep(0.01)",
                "raise SystemExit(main(sys.argv[3:]))",
            )
        )
        child = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                child_code,
                str(ready),
                str(release),
                str(workspace),
                *arguments,
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.reap_child, child)
        return child

    @staticmethod
    def reap_child(child):
        if child.poll() is None:
            child.kill()
        child.communicate()

    def wait_for_ready(self, ready_paths, children):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(path.exists() for path in ready_paths):
                return
            if any(child.poll() is not None for child in children):
                break
            time.sleep(0.01)
        details = []
        for child in children:
            if child.poll() is not None:
                stdout, stderr = child.communicate()
                details.append(f"rc={child.returncode} stdout={stdout} stderr={stderr}")
        self.fail(f"children did not reach barrier: {'; '.join(details)}")

    def finish_children(self, children):
        results = []
        for child in children:
            try:
                stdout, stderr = child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                stdout, stderr = child.communicate()
                self.fail(f"concurrent CLI timed out: {stdout}{stderr}")
            results.append((child.returncode, stdout, stderr))
        return results

    def test_transaction_blocks_a_real_process_and_direct_persistence_reenters(self):
        transaction = getattr(revisit_contract, "workspace_transaction", None)
        self.assertTrue(callable(transaction), "workspace_transaction export is missing")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            ready = root / "child-ready"
            acquired = root / "child-acquired"
            child_code = "\n".join(
                (
                    "import sys",
                    "from pathlib import Path",
                    "from scripts import revisit_contract",
                    "ready, acquired, workspace = map(Path, sys.argv[1:4])",
                    "ready.write_text('ready', encoding='utf-8')",
                    "with revisit_contract.workspace_transaction(workspace):",
                    "    acquired.write_text('acquired', encoding='utf-8')",
                )
            )

            with transaction(workspace):
                revisit_contract.persist_pointer(
                    workspace,
                    revisit_contract.empty_pointer(),
                    expected_sha256=None,
                )
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        "-c",
                        child_code,
                        str(ready),
                        str(acquired),
                        str(workspace),
                    ],
                    cwd=REPO_ROOT,
                    text=True,
                    encoding="utf-8",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.addCleanup(
                    lambda: (
                        child.kill() if child.poll() is None else None,
                        child.communicate(),
                    )
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "child did not reach the OS-lock boundary")
                self.assertIsNone(child.poll(), "child crossed the held workspace lock")
                self.assertFalse(acquired.exists(), "child acquired the held workspace lock")

            try:
                stdout, stderr = child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                stdout, stderr = child.communicate()
                self.fail(f"child remained blocked after release: {stdout}{stderr}")
            self.assertEqual(0, child.returncode, stderr)
            self.assertEqual("acquired", acquired.read_text(encoding="utf-8"))

    @unittest.skipUnless(hasattr(os, "fork"), "os.fork is unavailable")
    def test_forked_child_must_reacquire_after_parent_transaction_releases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            ready_read, ready_write = os.pipe()
            entered_read, entered_write = os.pipe()
            pid = None
            try:
                with revisit_contract.workspace_transaction(workspace):
                    pid = os.fork()
                    if pid == 0:
                        try:
                            os.close(ready_read)
                            os.close(entered_read)
                            os.write(ready_write, b"ready")
                            os.close(ready_write)
                            with revisit_contract.workspace_transaction(workspace):
                                os.write(entered_write, b"entered")
                            os.close(entered_write)
                        except BaseException:
                            os._exit(97)
                        os._exit(0)

                    os.close(ready_write)
                    ready_write = None
                    os.close(entered_write)
                    entered_write = None
                    readable, _, _ = select.select([ready_read], [], [], 5)
                    self.assertTrue(readable, "forked child did not reach lock boundary")
                    self.assertEqual(b"ready", os.read(ready_read, 5))
                    readable, _, _ = select.select([entered_read], [], [], 0.5)
                    self.assertFalse(
                        readable,
                        "forked child reused the parent's transaction entry",
                    )

                readable, _, _ = select.select([entered_read], [], [], 5)
                self.assertTrue(
                    readable,
                    "forked child did not enter after parent released the lock",
                )
                self.assertEqual(b"entered", os.read(entered_read, 7))
                waited_pid, status = os.waitpid(pid, 0)
                self.assertEqual(pid, waited_pid)
                self.assertEqual(0, os.waitstatus_to_exitcode(status))
                pid = None
            finally:
                if pid is not None:
                    waited_pid, _ = os.waitpid(pid, os.WNOHANG)
                    if waited_pid == 0:
                        os.kill(pid, 9)
                        os.waitpid(pid, 0)
                for descriptor in (
                    ready_read,
                    ready_write,
                    entered_read,
                    entered_write,
                ):
                    if descriptor is not None:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass

    def test_status_enters_the_workspace_transaction_before_reading_authority(self):
        transaction = revisit_contract.workspace_transaction
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_revisit_start_workspace(Path(temp_dir))
            with transaction(workspace):
                child = subprocess.Popen(
                    [
                        sys.executable,
                        str(REVISIT_CYCLE_SCRIPT),
                        str(workspace),
                        "status",
                        "--json",
                    ],
                    text=True,
                    encoding="utf-8",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.addCleanup(
                    lambda: (
                        child.kill() if child.poll() is None else None,
                        child.communicate(),
                    )
                )
                with self.assertRaises(
                    subprocess.TimeoutExpired,
                    msg="status read authority outside the workspace transaction",
                ):
                    child.wait(timeout=1)

            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(0, child.returncode, stderr)
            self.assertEqual("ticker", json.loads(stdout)["mode"])

    def test_two_real_process_starts_serialize_to_one_cycle_winner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            release = root / "release-starts"
            ready_paths = [root / "start-one-ready", root / "start-two-ready"]
            pointer_before = (workspace / revisit_contract.POINTER_FILENAME).read_bytes()
            with revisit_contract.workspace_transaction(workspace):
                children = [
                    self.start_barrier_cli(
                        workspace,
                        ready,
                        release,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )
                    for ready in ready_paths
                ]
                self.wait_for_ready(ready_paths, children)
                release.write_text("release", encoding="utf-8")
                time.sleep(0.1)
                self.assertTrue(
                    all(child.poll() is None for child in children),
                    "a start crossed the already-held workspace transaction",
                )

            results = self.finish_children(children)
            self.assertEqual([0, 2], sorted(result[0] for result in results))
            self.assertEqual(1, sum("REVISIT CYCLE STARTED" in row[1] for row in results))
            self.assertEqual(
                1,
                sum(
                    "REVISIT_CYCLE_CONFLICT: cycle conflict: RC-0001 is active"
                    in row[2]
                    for row in results
                ),
            )
            self.assertEqual(("RC-0001",), revisit_contract.list_cycle_ids(workspace))
            self.assertEqual("active", revisit_contract.load_cycle(workspace, "RC-0001")["status"])
            self.assertEqual(
                pointer_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )

    def test_two_real_process_aborts_preserve_the_first_terminal_authority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            started = run_revisit_cycle_cli(
                workspace, "start", "--intake-file", str(request_path)
            )
            self.assertEqual(0, started.returncode, started.stderr)
            release = root / "release-aborts"
            ready_paths = [root / "abort-one-ready", root / "abort-two-ready"]
            reasons = ("First concurrent reason.", "Second concurrent reason.")
            with revisit_contract.workspace_transaction(workspace):
                children = [
                    self.start_barrier_cli(
                        workspace,
                        ready,
                        release,
                        "abort",
                        "RC-0001",
                        "--reason",
                        reason,
                    )
                    for ready, reason in zip(ready_paths, reasons, strict=True)
                ]
                self.wait_for_ready(ready_paths, children)
                release.write_text("release", encoding="utf-8")
                time.sleep(0.1)
                self.assertTrue(all(child.poll() is None for child in children))

            results = self.finish_children(children)
            self.assertEqual([0, 2], sorted(result[0] for result in results))
            cycle = revisit_contract.load_cycle(workspace, "RC-0001")
            self.assertEqual("aborted", cycle["status"])
            self.assertIn(cycle["abort_reason"], reasons)
            self.assertEqual(1, sum(row["command"] == "abort" for row in cycle["audit"]))
            self.assertEqual(1, sum("REVISIT CYCLE ABORTED" in row[1] for row in results))
            self.assertEqual(1, sum("cannot abort cycle RC-0001 with status aborted" in row[2] for row in results))

    def test_real_process_start_and_abort_never_observe_torn_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            started = run_revisit_cycle_cli(
                workspace, "start", "--intake-file", str(request_path)
            )
            self.assertEqual(0, started.returncode, started.stderr)
            release = root / "release-start-abort"
            ready_paths = [root / "later-start-ready", root / "abort-ready"]
            with revisit_contract.workspace_transaction(workspace):
                start_child = self.start_barrier_cli(
                    workspace,
                    ready_paths[0],
                    release,
                    "start",
                    "--intake-file",
                    str(request_path),
                )
                abort_child = self.start_barrier_cli(
                    workspace,
                    ready_paths[1],
                    release,
                    "abort",
                    "RC-0001",
                    "--reason",
                    "Concurrent explicit abort.",
                )
                children = [start_child, abort_child]
                self.wait_for_ready(ready_paths, children)
                release.write_text("release", encoding="utf-8")
                time.sleep(0.1)
                self.assertTrue(all(child.poll() is None for child in children))

            start_result, abort_result = self.finish_children(children)
            self.assertEqual(0, abort_result[0], abort_result[2])
            self.assertIn(start_result[0], {0, 2})
            first = revisit_contract.load_cycle(workspace, "RC-0001")
            self.assertEqual("aborted", first["status"])
            if start_result[0] == 0:
                self.assertEqual(("RC-0001", "RC-0002"), revisit_contract.list_cycle_ids(workspace))
                second = revisit_contract.load_cycle(workspace, "RC-0002")
                self.assertEqual("REV-0003", second["candidate_revision_id"])
                self.assertEqual("active", second["status"])
            else:
                self.assertEqual(("RC-0001",), revisit_contract.list_cycle_ids(workspace))
                self.assertIn(
                    "REVISIT_CYCLE_CONFLICT: cycle conflict: RC-0001 is active",
                    start_result[2],
                )

    def test_two_real_process_initial_registrations_preserve_one_winning_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, first_report = make_registration_workspace(root)
            second_report = workspace / "reports" / "second.md"
            second_report.write_bytes(complete_ticker_report_bytes())
            report_bytes = {
                "reports/final.md": first_report.read_bytes(),
                "reports/second.md": second_report.read_bytes(),
            }
            release = root / "release-register"
            ready_paths = [root / "register-one-ready", root / "register-two-ready"]
            registrations = (
                ("reports/final.md", "Watch with Trigger"),
                ("reports/second.md", "Reject"),
            )
            with revisit_contract.workspace_transaction(workspace):
                children = [
                    self.start_barrier_cli(
                        workspace,
                        ready,
                        release,
                        "register-current",
                        "--report",
                        report_path,
                        "--action-class",
                        action_class,
                    )
                    for ready, (report_path, action_class) in zip(
                        ready_paths, registrations, strict=True
                    )
                ]
                self.wait_for_ready(ready_paths, children)
                release.write_text("release", encoding="utf-8")
                time.sleep(0.1)
                self.assertTrue(all(child.poll() is None for child in children))

            results = self.finish_children(children)
            self.assertEqual([0, 2], sorted(result[0] for result in results))
            pointer = revisit_contract.load_pointer(workspace)["current_revision"]
            winner_index = next(index for index, row in enumerate(results) if row[0] == 0)
            winning_report, winning_action = registrations[winner_index]
            self.assertEqual(winning_report, pointer["report_path"])
            self.assertEqual(winning_action, pointer["action_class"])
            self.assertEqual(
                hashlib.sha256(report_bytes[winning_report]).hexdigest(),
                pointer["report_sha256"],
            )
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))
            self.assertEqual(report_bytes["reports/final.md"], first_report.read_bytes())
            self.assertEqual(report_bytes["reports/second.md"], second_report.read_bytes())


class TestRevisitStoreReads(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def write_cycle(self, workspace, cycle, filename=None):
        directory = workspace / revisit_contract.CYCLES_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (filename or f"{cycle['cycle_id']}.json")
        path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
        return path

    def test_store_paths_are_canonical_and_cycle_ids_are_strict(self):
        pointer_path = self.required_callable("pointer_path")
        cycle_directory = self.required_callable("cycle_directory")
        cycle_json_path = self.required_callable("cycle_json_path")
        cycle_markdown_path = self.required_callable("cycle_markdown_path")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertEqual(
                workspace.resolve() / revisit_contract.POINTER_FILENAME,
                pointer_path(workspace),
            )
            self.assertEqual(
                workspace.resolve() / revisit_contract.CYCLES_DIRNAME,
                cycle_directory(workspace),
            )
            self.assertEqual(
                workspace.resolve()
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.json",
                cycle_json_path(workspace, "RC-0001"),
            )
            self.assertEqual(
                workspace.resolve()
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.md",
                cycle_markdown_path(workspace, "RC-0001"),
            )
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "cycle_id must match RC-NNNN"
            ):
                cycle_json_path(workspace, ".." + "/" + "RC-0001")

    def test_pointer_reads_are_strict_and_allow_missing_is_explicit(self):
        load_pointer = self.required_callable("load_pointer")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertIsNone(load_pointer(workspace, allow_missing=True))
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "pointer authority is missing"
            ):
                load_pointer(workspace)

            path = workspace / revisit_contract.POINTER_FILENAME
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed JSON.*revisit_contract"
            ):
                load_pointer(workspace)

    def test_cycle_reads_never_use_markdown_when_json_is_absent_or_malformed(self):
        load_cycle = self.required_callable("load_cycle")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            markdown = directory / "RC-0001.md"
            markdown.write_bytes(revisit_contract.canonical_document_bytes(make_minimal_cycle()))

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "cycle authority is missing"
            ):
                load_cycle(workspace, "RC-0001")

            (directory / "RC-0001.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed JSON.*RC-0001.json"
            ):
                load_cycle(workspace, "RC-0001")

            self.assertTrue(markdown.exists())

    def test_list_cycle_ids_validates_history_and_returns_numeric_order(self):
        list_cycle_ids = self.required_callable("list_cycle_ids")
        load_cycle = self.required_callable("load_cycle")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            second = make_minimal_cycle(
                cycle_id="RC-0002", candidate_revision_id="REV-0003"
            )
            self.write_cycle(workspace, second)
            self.write_cycle(workspace, make_minimal_cycle())
            (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").write_text(
                "derived mirror\n", encoding="utf-8"
            )

            self.assertEqual(("RC-0001", "RC-0002"), list_cycle_ids(workspace))
            self.assertEqual("RC-0002", load_cycle(workspace, "RC-0002")["cycle_id"])

    def test_list_cycle_ids_rejects_malformed_filenames_and_internal_ids(self):
        list_cycle_ids = self.required_callable("list_cycle_ids")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.write_cycle(workspace, make_minimal_cycle(), "RC-1.json")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed cycle filename"
            ):
                list_cycle_ids(workspace)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.write_cycle(workspace, make_minimal_cycle(), "RC-0002.json")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "filename RC-0002 does not match internal cycle_id RC-0001",
            ):
                list_cycle_ids(workspace)


class TestRevisitRender(unittest.TestCase):
    def test_render_cycle_markdown_is_deterministic_escaped_and_factual(self):
        render_cycle_markdown = getattr(
            revisit_contract, "render_cycle_markdown", None
        )
        self.assertTrue(
            callable(render_cycle_markdown),
            "render_cycle_markdown export is missing",
        )
        cycle = make_populated_cycle()
        cycle["intake"]["triggers"][0]["statement"] = "Revenue | baseline changed."
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)

        first = render_cycle_markdown(cycle)
        second = render_cycle_markdown(copy.deepcopy(cycle))

        self.assertEqual(first, second)
        for heading in (
            "## Identity And Status",
            "## Immutable Base And Framing Boundary",
            "## Fired Triggers",
            "## Selected And Derived Claims",
            "## Freshness",
            "## Frontier Bindings And Floors",
            "## Decision And Rerun Duties",
            "## Report Candidate",
            "## Audit",
        ):
            self.assertIn(heading, first)
        self.assertIn("Revenue \\| baseline changed.", first)
        self.assertIn("### Claim Resolutions", first)
        self.assertIn("confirmed", first)
        self.assertIn("The primary filing confirms the claim.", first)
        self.assertIn(
            "| RC-0001-DC-01 | emergent | Updated revenue evidence is "
            "decision-relevant.",
            first,
        )
        self.assertIn("| RC-0001-DC-01 | confirmed |", first)
        self.assertIn("| Change class | evidence_or_claim_only |", first)
        self.assertIn(
            '| Required reruns | ["delta-frontier-review"] |', first
        )
        self.assertNotIn("Inferred verdict", first)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))

        minimal = render_cycle_markdown(make_minimal_cycle())
        self.assertIn("No decision assessment recorded.", minimal)


class TestRevisitPersistence(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def test_persist_cycle_replaces_mirror_before_json_with_exact_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_populated_cycle()
        real_replace = os.replace
        destinations = []

        def recording_replace(source, destination):
            destinations.append(Path(destination).name)
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                json_path, markdown_path = persist_cycle(
                    workspace, cycle, expected_sha256=None
                )

            self.assertEqual(["RC-0001.md", "RC-0001.json"], destinations)
            self.assertEqual(
                revisit_contract.canonical_document_bytes(cycle),
                json_path.read_bytes(),
            )
            self.assertEqual(
                revisit_contract.render_cycle_markdown(cycle).encode("utf-8"),
                markdown_path.read_bytes(),
            )
            self.assertEqual(cycle, revisit_contract.load_cycle(workspace, "RC-0001"))

    def test_relative_workspace_accepts_cwd_prefixed_relative_snapshot_key(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        authority_bytes = b"validated relative authority\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            absolute_workspace = root / "workspace"
            absolute_workspace.mkdir()
            authority = absolute_workspace / "authority.md"
            authority.write_bytes(authority_bytes)
            workspace = Path("workspace")
            snapshot_key = workspace / "authority.md"
            expected_sha256 = hashlib.sha256(authority_bytes).hexdigest()
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                try:
                    json_path, markdown_path = persist_cycle(
                        workspace,
                        cycle,
                        expected_sha256=None,
                        authority_snapshots={snapshot_key: expected_sha256},
                    )
                except revisit_contract.RevisitContractError as error:
                    self.fail(
                        "cwd-prefixed relative snapshot key was rejected: "
                        f"{error}"
                    )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            self.assertEqual(authority_bytes, authority.read_bytes())

    def test_relative_workspace_rejects_actual_outside_relative_snapshot_key(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        authority_bytes = b"same inside and outside authority bytes\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            absolute_workspace = root / "workspace"
            absolute_workspace.mkdir()
            inside = absolute_workspace / "outside.md"
            outside = root / "outside.md"
            inside.write_bytes(authority_bytes)
            outside.write_bytes(authority_bytes)
            expected_sha256 = hashlib.sha256(authority_bytes).hexdigest()
            original_cwd = Path.cwd()
            os.chdir(root)
            try:
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "snapshot authority escapes workspace",
                ):
                    persist_cycle(
                        Path("workspace"),
                        cycle,
                        expected_sha256=None,
                        authority_snapshots={
                            Path("outside.md"): expected_sha256,
                        },
                    )
            finally:
                os.chdir(original_cwd)

            self.assertEqual(authority_bytes, inside.read_bytes())
            self.assertEqual(authority_bytes, outside.read_bytes())
            self.assertFalse(
                (
                    absolute_workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / "RC-0001.json"
                ).exists()
            )
            self.assertFalse(
                (
                    absolute_workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / "RC-0001.md"
                ).exists()
            )

    def test_prepared_snapshot_rejects_non_text_digest_as_contract_error(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            authority = workspace / "authority.md"
            authority.write_bytes(b"validated authority\n")
            snapshot = revisit_store.PreparedAuthoritySnapshot(
                workspace=workspace,
                lexical_path=authority,
                resolved_target=authority,
                expected_sha256=42,
            )

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "snapshot digest must be a lowercase SHA-256",
            ):
                persist_cycle(
                    workspace,
                    cycle,
                    expected_sha256=None,
                    authority_snapshots=(snapshot,),
                )

            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_snapshot_rejects_same_byte_target_change_before_cycle_persistence(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        authority_bytes = b"same authority generation\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            sources = workspace / "sources"
            sources.mkdir()
            first_target = sources / "src-001-first.md"
            second_target = sources / "src-001-second.md"
            lexical_excerpt = sources / "src-001.md"
            first_target.write_bytes(authority_bytes)
            second_target.write_bytes(authority_bytes)
            lexical_excerpt.symlink_to(first_target.name)
            expected_sha256 = hashlib.sha256(authority_bytes).hexdigest()
            real_require = revisit_store._require_snapshot_generations
            injected = False

            def retarget_then_require(snapshots, boundary):
                nonlocal injected
                if boundary == "before cycle persistence" and not injected:
                    injected = True
                    lexical_excerpt.unlink()
                    lexical_excerpt.symlink_to(second_target.name)
                return real_require(snapshots, boundary)

            with mock.patch.object(
                revisit_store,
                "_require_snapshot_generations",
                side_effect=retarget_then_require,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "authority target changed before cycle persistence",
                ):
                    persist_cycle(
                        workspace,
                        cycle,
                        expected_sha256=None,
                        authority_snapshots={
                            lexical_excerpt: expected_sha256,
                        },
                    )

            self.assertEqual(second_target.resolve(), lexical_excerpt.resolve())
            self.assertEqual(authority_bytes, first_target.read_bytes())
            self.assertEqual(authority_bytes, second_target.read_bytes())
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_snapshot_rejects_same_byte_target_change_after_cycle_persistence(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        authority_bytes = b"same authority generation\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            sources = workspace / "sources"
            sources.mkdir()
            first_target = sources / "src-001-first.md"
            second_target = sources / "src-001-second.md"
            lexical_excerpt = sources / "src-001.md"
            first_target.write_bytes(authority_bytes)
            second_target.write_bytes(authority_bytes)
            lexical_excerpt.symlink_to(first_target.name)
            expected_sha256 = hashlib.sha256(authority_bytes).hexdigest()
            real_atomic_replace = revisit_store._atomic_replace
            injected = False

            def replace_then_retarget(path, payload):
                nonlocal injected
                real_atomic_replace(path, payload)
                if Path(path).name == "RC-0001.json" and not injected:
                    injected = True
                    lexical_excerpt.unlink()
                    lexical_excerpt.symlink_to(second_target.name)

            with mock.patch.object(
                revisit_store,
                "_atomic_replace",
                side_effect=replace_then_retarget,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "authority target changed after cycle persistence",
                ):
                    persist_cycle(
                        workspace,
                        cycle,
                        expected_sha256=None,
                        authority_snapshots={
                            lexical_excerpt: expected_sha256,
                        },
                    )

            self.assertEqual(second_target.resolve(), lexical_excerpt.resolve())
            self.assertEqual(authority_bytes, first_target.read_bytes())
            self.assertEqual(authority_bytes, second_target.read_bytes())
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )

    def test_persist_cycle_rejects_path_alias_before_render_and_preserves_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        original_json = revisit_contract.canonical_document_bytes(original)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)

            try:
                with mock.patch(
                    "scripts.revisit_contract.store.cycle_markdown_path",
                    return_value=json_path.resolve(),
                ), mock.patch(
                    "scripts.revisit_contract.store.render_cycle_markdown",
                    side_effect=AssertionError("render must not be reached"),
                ):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )
            except Exception as error:
                self.assertIsInstance(error, revisit_contract.RevisitContractError)
                self.assertRegex(str(error), "authority targets must be distinct")
            else:
                self.fail("aliased cycle authority targets were not rejected")

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertFalse(markdown_path.exists())

    def test_json_replace_failure_restores_exact_existing_mirror_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        attach_valid_audit(updated)
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\nwith exact CRLF bytes\r\n"
        real_replace = os.replace
        destinations = []

        def fail_json_replace(source, destination):
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("cycle JSON replace failed")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_replace,
            ):
                with self.assertRaisesRegex(OSError, "cycle JSON replace failed"):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )

            self.assertEqual(original_markdown, markdown_path.read_bytes())
            self.assertEqual(original_json, json_path.read_bytes())
            self.assertEqual(
                ["RC-0001.md", "RC-0001.json", "RC-0001.md"], destinations
            )

    def test_first_write_json_failure_removes_new_orphan_mirror(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        real_replace = os.replace
        destinations = []

        def fail_json_replace(source, destination):
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("first cycle JSON replace failed")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_replace,
            ):
                with self.assertRaisesRegex(OSError, "first cycle JSON replace failed"):
                    persist_cycle(workspace, cycle, expected_sha256=None)

            directory = workspace / revisit_contract.CYCLES_DIRNAME
            self.assertFalse((directory / "RC-0001.md").exists())
            self.assertFalse((directory / "RC-0001.json").exists())
            self.assertEqual(["RC-0001.md", "RC-0001.json"], destinations)
            self.assertEqual([], list(directory.iterdir()))

    def test_first_write_json_failure_refuses_to_remove_third_party_mirror(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        third_party_bytes = b"third-party mirror after transaction write\n"
        real_replace = os.replace

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            markdown_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md"
            )
            json_path = workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json"

            def fail_json_after_third_party_write(source, destination):
                destination = Path(destination)
                if destination.name == "RC-0001.json":
                    markdown_path.write_bytes(third_party_bytes)
                    raise OSError("first cycle JSON replace failed")
                return real_replace(source, destination)

            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_after_third_party_write,
            ):
                try:
                    persist_cycle(workspace, cycle, expected_sha256=None)
                except Exception as error:
                    self.assertIsInstance(
                        error, revisit_contract.RevisitPersistenceRollbackError
                    )
                    self.assertIn("first cycle JSON replace failed", str(error))
                    self.assertIn("rollback refused", str(error))
                else:
                    self.fail("third-party mirror ownership loss was not reported")

            self.assertEqual(third_party_bytes, markdown_path.read_bytes())
            self.assertFalse(json_path.exists())

    def test_existing_json_failure_refuses_to_restore_over_third_party_mirror(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        attach_valid_audit(updated)
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior exact mirror bytes\n"
        third_party_bytes = b"third-party mirror after transaction write\n"
        real_replace = os.replace

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            def fail_json_after_third_party_write(source, destination):
                destination = Path(destination)
                if destination.name == "RC-0001.json":
                    markdown_path.write_bytes(third_party_bytes)
                    raise OSError("existing cycle JSON replace failed")
                return real_replace(source, destination)

            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_after_third_party_write,
            ):
                try:
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )
                except Exception as error:
                    self.assertIsInstance(
                        error, revisit_contract.RevisitPersistenceRollbackError
                    )
                    self.assertIn("existing cycle JSON replace failed", str(error))
                    self.assertIn("rollback refused", str(error))
                else:
                    self.fail("third-party mirror ownership loss was not reported")

            self.assertEqual(third_party_bytes, markdown_path.read_bytes())
            self.assertEqual(original_json, json_path.read_bytes())

    def test_rollback_error_is_an_explicit_contract_error(self):
        error_type = getattr(
            revisit_contract, "RevisitPersistenceRollbackError", None
        )
        self.assertTrue(
            isinstance(error_type, type)
            and issubclass(error_type, revisit_contract.RevisitContractError),
            "RevisitPersistenceRollbackError export is missing",
        )

    def test_rollback_failure_surfaces_original_and_rollback_errors_together(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        attach_valid_audit(updated)
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\n"
        real_replace = os.replace
        destinations = []
        markdown_replaces = 0

        def fail_json_and_rollback(source, destination):
            nonlocal markdown_replaces
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("original JSON failure")
            if destination.name == "RC-0001.md":
                markdown_replaces += 1
                if markdown_replaces == 2:
                    raise OSError("mirror rollback failure")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            try:
                with mock.patch(
                    "scripts.revisit_contract.store.os.replace",
                    side_effect=fail_json_and_rollback,
                ):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )
            except Exception as error:
                self.assertIsInstance(
                    error, revisit_contract.RevisitPersistenceRollbackError
                )
                self.assertIn("original JSON failure", str(error))
                self.assertIn("mirror rollback failure", str(error))
                self.assertEqual("original JSON failure", str(error.original_error))
                self.assertEqual("mirror rollback failure", str(error.rollback_error))
            else:
                self.fail("combined rollback error not raised")

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertNotEqual(original_markdown, markdown_path.read_bytes())
            self.assertEqual(
                ["RC-0001.md", "RC-0001.json", "RC-0001.md"], destinations
            )

    def test_render_payload_failure_writes_neither_cycle_file(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        self.assertIs(cycle, revisit_contract.validate_cycle(cycle))

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            render_error = UnicodeEncodeError(
                "utf-8", "\ud800", 0, 1, "surrogates not allowed"
            )
            with mock.patch(
                "scripts.revisit_contract.store.render_cycle_markdown",
                side_effect=render_error,
            ):
                with self.assertRaises(UnicodeEncodeError):
                    persist_cycle(workspace, cycle, expected_sha256=None)
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )

    def test_optimistic_cycle_digest_mismatch_changes_neither_file(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        attach_valid_audit(updated)
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\nexact bytes\r\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "authority changed before write"
            ):
                persist_cycle(workspace, updated, expected_sha256="0" * 64)

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertEqual(original_markdown, markdown_path.read_bytes())

    def test_persist_pointer_is_one_atomic_replace_with_optimistic_guard(self):
        persist_pointer = self.required_callable("persist_pointer")
        pointer = revisit_contract.empty_pointer()
        real_replace = os.replace
        destinations = []

        def recording_replace(source, destination):
            destinations.append(Path(destination).name)
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                path = persist_pointer(workspace, pointer, expected_sha256=None)
            self.assertEqual([revisit_contract.POINTER_FILENAME], destinations)
            self.assertEqual(
                revisit_contract.canonical_document_bytes(pointer), path.read_bytes()
            )

            prior_bytes = path.read_bytes()
            updated = revisit_contract.empty_pointer()
            updated["current_revision"] = make_initial_revision()
            destinations.clear()
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                persist_pointer(
                    workspace,
                    updated,
                    expected_sha256=hashlib.sha256(prior_bytes).hexdigest(),
                )
            self.assertEqual([revisit_contract.POINTER_FILENAME], destinations)
            updated_bytes = path.read_bytes()
            self.assertEqual(revisit_contract.canonical_document_bytes(updated), updated_bytes)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "authority changed before write"
            ):
                persist_pointer(workspace, pointer, expected_sha256="0" * 64)
            self.assertEqual(updated_bytes, path.read_bytes())


class TestRevisitAuditMutation(unittest.TestCase):
    def test_with_audit_is_copy_on_write_and_uses_locked_null_pre_hash(self):
        with_audit = getattr(revisit_model, "with_audit", None)
        self.assertTrue(callable(with_audit), "with_audit helper is missing")
        previous = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        previous_before = copy.deepcopy(previous)
        updated_before = copy.deepcopy(updated)

        result = with_audit(
            previous,
            updated,
            command="mark-ready",
            affected_ids=["RC-0001"],
            timestamp="2026-07-15T03:00:00Z",
        )

        self.assertEqual(previous_before, previous)
        self.assertEqual(updated_before, updated)
        self.assertIsNot(result, updated)
        self.assertEqual(previous["audit"], result["audit"][:-1])
        self.assertEqual(2, result["audit"][-1]["sequence"])
        self.assertEqual(
            previous["audit"][-1]["post_state_sha256"],
            result["audit"][-1]["pre_state_sha256"],
        )
        self.assertEqual(
            revisit_contract.cycle_state_sha256(updated),
            result["audit"][-1]["post_state_sha256"],
        )
        self.assertIs(result, revisit_contract.validate_cycle(result))

    def test_with_audit_preserves_prefix_and_audit_text_cannot_change_state_hashes(self):
        with_audit = getattr(revisit_model, "with_audit", None)
        self.assertTrue(callable(with_audit), "with_audit helper is missing")
        base = make_minimal_cycle()
        first = base
        updated = copy.deepcopy(first)
        updated["status"] = "ready_for_report"
        tampered_audit_text = copy.deepcopy(updated)
        tampered_audit_text["audit"][0]["command"] = "ignored audit-only text"

        second = with_audit(
            first,
            updated,
            command="mark-ready",
            affected_ids=["RC-0001"],
            timestamp="2026-07-15T03:05:00Z",
        )
        alternate = with_audit(
            first,
            tampered_audit_text,
            command="different audit text",
            affected_ids=["RC-0001", "REV-0002"],
            timestamp="2026-07-15T03:06:00Z",
        )

        self.assertEqual(first["audit"], second["audit"][:-1])
        self.assertEqual(first["audit"], alternate["audit"][:-1])
        self.assertEqual(2, second["audit"][-1]["sequence"])
        self.assertEqual(
            first["audit"][-1]["post_state_sha256"],
            second["audit"][-1]["pre_state_sha256"],
        )
        self.assertEqual(
            second["audit"][-1]["post_state_sha256"],
            alternate["audit"][-1]["post_state_sha256"],
        )
        self.assertEqual(
            revisit_contract.cycle_state_sha256(second),
            revisit_contract.cycle_state_sha256(alternate),
        )
        self.assertIs(second, revisit_contract.validate_cycle(second))
        self.assertIs(alternate, revisit_contract.validate_cycle(alternate))


class TestCycleSchema(unittest.TestCase):
    def assert_contract_error(self, operation, pattern):
        try:
            operation()
        except Exception as error:
            self.assertIsInstance(error, revisit_contract.RevisitContractError)
            self.assertRegex(str(error), pattern)
            return
        self.fail("RevisitContractError not raised")

    def test_validate_cycle_is_an_explicit_callable_export(self):
        self.assertTrue(
            callable(getattr(revisit_contract, "validate_cycle", None)),
            "validate_cycle export is missing",
        )

    def test_task4_rejects_the_temporary_empty_intake_and_audit_skeleton(self):
        skeleton = make_task1_skeleton_cycle()
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "framing.snapshot.research_posture must be revisit",
        ):
            revisit_contract.validate_cycle(skeleton)

    def test_task4_intake_cross_field_invariants_are_canonical(self):
        def too_many_triggers(cycle):
            template = cycle["intake"]["triggers"][0]
            cycle["intake"]["triggers"] = []
            for number in range(1, 101):
                trigger = copy.deepcopy(template)
                trigger["trigger_id"] = f"RC-0001-TRG-{number:02d}"
                cycle["intake"]["triggers"].append(trigger)

        def too_many_claims(cycle):
            template = cycle["intake"]["selected_claims"][0]
            cycle["intake"]["selected_claims"] = []
            for number in range(1, 101):
                claim = copy.deepcopy(template)
                claim["claim_id"] = f"RC-0001-CL-{number:02d}"
                cycle["intake"]["selected_claims"].append(claim)

        def orphan_trigger(cycle):
            trigger = copy.deepcopy(cycle["intake"]["triggers"][0])
            trigger["trigger_id"] = "RC-0001-TRG-02"
            cycle["intake"]["triggers"].append(trigger)

        cases = (
            (
                "empty triggers",
                lambda cycle: cycle["intake"].__setitem__("triggers", []),
                "cycle.intake.triggers must not be empty",
            ),
            ("too many triggers", too_many_triggers, "cannot exceed 99"),
            (
                "empty selected claims",
                lambda cycle: cycle["intake"].__setitem__("selected_claims", []),
                "cycle.intake.selected_claims must not be empty",
            ),
            ("too many selected claims", too_many_claims, "cannot exceed 99"),
            (
                "empty trigger evidence",
                lambda cycle: cycle["intake"]["triggers"][0].__setitem__(
                    "evidence_refs", []
                ),
                "trigger evidence_refs must not be empty",
            ),
            (
                "nonsequential trigger ID",
                lambda cycle: (
                    cycle["intake"]["triggers"][0].__setitem__(
                        "trigger_id", "RC-0001-TRG-02"
                    ),
                    cycle["intake"]["selected_claims"][0].__setitem__(
                        "trigger_ids", ["RC-0001-TRG-02"]
                    ),
                ),
                "trigger IDs must be exact sequential request-order IDs",
            ),
            (
                "nonsequential claim ID",
                lambda cycle: (
                    cycle["intake"]["selected_claims"][0].__setitem__(
                        "claim_id", "RC-0001-CL-02"
                    ),
                    cycle["claim_resolutions"][0].__setitem__(
                        "claim_id", "RC-0001-CL-02"
                    ),
                ),
                "claim IDs must be exact sequential request-order IDs",
            ),
            (
                "empty selection reasons",
                lambda cycle: cycle["intake"]["selected_claims"][0].__setitem__(
                    "selection_reasons", []
                ),
                "selection_reasons must not be empty",
            ),
            (
                "duplicate selection reasons",
                lambda cycle: cycle["intake"]["selected_claims"][0].__setitem__(
                    "selection_reasons", ["trigger_affected", "trigger_affected"]
                ),
                "selection_reasons must not contain duplicate selection reasons",
            ),
            (
                "unknown trigger reference",
                lambda cycle: cycle["intake"]["selected_claims"][0].__setitem__(
                    "trigger_ids", ["RC-0001-TRG-99"]
                ),
                "trigger_ids must reference known intake triggers",
            ),
            (
                "trigger affected without IDs",
                lambda cycle: cycle["intake"]["selected_claims"][0].__setitem__(
                    "trigger_ids", []
                ),
                "trigger_affected requires non-empty trigger_ids",
            ),
            (
                "orphan trigger",
                orphan_trigger,
                (
                    "REVISIT_TRIGGER_ORPHANED: "
                    r"cycle.intake.triggers\[1\].trigger_id "
                    "RC-0001-TRG-02 is not referenced by any selected claim"
                ),
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(case=label):
                cycle = make_minimal_cycle()
                mutate(cycle)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                attach_valid_audit(cycle)
                expected_cycle = copy.deepcopy(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )
                self.assertEqual(expected_cycle, cycle)
    def test_task4_resolution_and_start_audit_coverage_are_canonical(self):
        resolution_cases = (
            (
                "missing selected resolution",
                lambda cycle: cycle.__setitem__("claim_resolutions", []),
                "claim_resolutions must cover every selected and derived claim exactly once",
                make_minimal_cycle,
            ),
            (
                "duplicate selected resolution",
                lambda cycle: cycle["claim_resolutions"].append(
                    copy.deepcopy(cycle["claim_resolutions"][0])
                ),
                "cycle.claim_resolutions contains duplicate claim_id",
                make_minimal_cycle,
            ),
            (
                "missing derived resolution",
                lambda cycle: cycle["claim_resolutions"].pop(),
                "claim_resolutions must cover every selected and derived claim exactly once",
                make_populated_cycle,
            ),
            (
                "unknown resolution",
                lambda cycle: cycle["claim_resolutions"][0].__setitem__(
                    "claim_id", "RC-0001-CL-99"
                ),
                "claim_id must reference a known same-cycle claim",
                make_minimal_cycle,
            ),
        )
        for label, mutate, pattern, factory in resolution_cases:
            with self.subTest(case=label):
                cycle = factory()
                mutate(cycle)
                attach_valid_audit(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        expected_affected = [
            "RC-0001",
            "REV-0002",
            "RC-0001-TRG-01",
            "RC-0001-CL-01",
        ]
        audit_cases = (
            ("empty audit", lambda cycle: cycle.__setitem__("audit", []), "audit must not be empty"),
            (
                "first command",
                lambda cycle: cycle["audit"][0].__setitem__("command", "revisit-start"),
                "audit entry 1 command must be start",
            ),
            (
                "first timestamp",
                lambda cycle: cycle["audit"][0].__setitem__(
                    "timestamp", "2026-07-15T00:00:01Z"
                ),
                "audit entry 1 timestamp must match cycle.created_at",
            ),
            (
                "first pre-state",
                lambda cycle: cycle["audit"][0].__setitem__(
                    "pre_state_sha256", "0" * 64
                ),
                "audit entry 1 pre_state_sha256 must be the canonical null hash",
            ),
            (
                "first affected IDs",
                lambda cycle: cycle["audit"][0].__setitem__(
                    "affected_ids", list(reversed(expected_affected))
                ),
                "audit entry 1 affected_ids must name the reserved and initial intake IDs",
            ),
        )
        for label, mutate, pattern in audit_cases:
            with self.subTest(case=label):
                cycle = make_minimal_cycle()
                mutate(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_cycle_rejects_persisted_completed_unpublished_status(self):
        cycle = make_minimal_cycle()
        cycle["status"] = "completed-unpublished"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "unsupported cycle status"
        ):
            revisit_contract.validate_cycle(cycle)

    def test_semantic_hash_helpers_are_canonical_pure_and_audit_free(self):
        value = {"z": "中", "a": [2, 1]}
        expected_bytes = '{"a":[2,1],"z":"中"}'.encode()
        cycle = make_minimal_cycle()
        cycle["audit"] = [{"arbitrary": "excluded"}]
        original = copy.deepcopy(cycle)
        expected_state = copy.deepcopy(cycle)
        expected_state.pop("audit")

        checks = (
            (
                "canonical_semantic_bytes",
                expected_bytes,
                getattr(revisit_contract, "canonical_semantic_bytes", lambda _: b"")(
                    value
                ),
            ),
            (
                "semantic_sha256",
                test_semantic_sha256(value),
                getattr(revisit_contract, "semantic_sha256", lambda _: "")(value),
            ),
            (
                "intake_sha256",
                test_semantic_sha256(cycle["intake"]),
                getattr(revisit_contract, "intake_sha256", lambda _: "")(
                    cycle["intake"]
                ),
            ),
            (
                "state_without_audit",
                expected_state,
                getattr(revisit_contract, "state_without_audit", lambda _: {})(cycle),
            ),
            (
                "cycle_state_sha256",
                test_semantic_sha256(expected_state),
                getattr(revisit_contract, "cycle_state_sha256", lambda _: "")(cycle),
            ),
        )
        for name, expected, actual in checks:
            with self.subTest(helper=name):
                self.assertEqual(expected, actual)
        self.assertEqual(original, cycle)

    def test_cycle_rejects_non_object_input(self):
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle([]),
            "cycle JSON must contain an object",
        )

    def test_cycle_top_level_keys_are_exact_and_validation_is_non_mutating(self):
        cycle = make_minimal_cycle()
        cycle["hidden_authority"] = "Act"
        original = copy.deepcopy(cycle)
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle unknown field.*hidden_authority",
        )
        self.assertEqual(original, cycle)

    def test_cycle_schema_version_rejects_bool(self):
        cycle = make_minimal_cycle()
        cycle["schema_version"] = True
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle\.schema_version must be an integer >= 1",
        )

    def test_cycle_rejects_unsupported_schema_version(self):
        cycle = make_minimal_cycle()
        cycle["schema_version"] = 2
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "unsupported cycle schema_version",
        )

    def test_cycle_and_candidate_revision_ids_use_locked_formats(self):
        cases = (
            ("cycle_id", "RC-1", r"cycle\.cycle_id must match RC-NNNN"),
            (
                "candidate_revision_id",
                "REV-1",
                r"cycle\.candidate_revision_id must match REV-NNNN",
            ),
        )
        for field, value, pattern in cases:
            with self.subTest(field=field):
                cycle = make_minimal_cycle()
                cycle[field] = value
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_cycle_timestamps_and_abort_reason_follow_terminal_status(self):
        timestamp = "2026-07-15T01:00:00Z"
        cases = (
            (
                "created_at_format",
                {"created_at": "2026-02-30T00:00:00Z"},
                r"cycle\.created_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "completed_at_on_active",
                {"completed_at": timestamp},
                "cycle.completed_at is only valid when status is completed",
            ),
            (
                "aborted_at_on_active",
                {"aborted_at": timestamp},
                "cycle.aborted_at is only valid when status is aborted",
            ),
            (
                "abort_reason_on_active",
                {"abort_reason": "Stopped"},
                "cycle.abort_reason is only valid when status is aborted",
            ),
            (
                "completed_without_timestamp",
                {"status": "completed"},
                "completed cycle requires completed_at",
            ),
            (
                "aborted_without_timestamp",
                {"status": "aborted", "abort_reason": "Stopped"},
                "aborted cycle requires aborted_at",
            ),
            (
                "aborted_without_reason",
                {"status": "aborted", "aborted_at": timestamp},
                "aborted cycle requires abort_reason",
            ),
        )
        for name, overrides, pattern in cases:
            with self.subTest(case=name):
                cycle = make_minimal_cycle()
                cycle.update(overrides)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_cycle_rejects_intake_hash_mismatch(self):
        cycle = make_minimal_cycle()
        original = copy.deepcopy(cycle)
        cycle["intake_sha256"] = "0" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            (
                "REVISIT_INTAKE_DRIFT: cycle.intake_sha256 "
                "does not match immutable intake"
            ),
        )
        expected = copy.deepcopy(original)
        expected["intake_sha256"] = "0" * 64
        self.assertEqual(expected, cycle)

    def test_every_nested_object_rejects_unknown_fields(self):
        cases = (
            (("intake",), "cycle.intake"),
            (("intake", "base_revision"), "cycle.intake.base_revision"),
            (("intake", "framing"), "cycle.intake.framing"),
            (("intake", "framing", "snapshot"), "cycle.intake.framing.snapshot"),
            (
                ("intake", "workspace_boundary"),
                "cycle.intake.workspace_boundary",
            ),
            (("intake", "triggers", 0), "cycle.intake.triggers[0]"),
            (
                ("intake", "triggers", 0, "evidence_refs", 0),
                "cycle.intake.triggers[0].evidence_refs[0]",
            ),
            (("intake", "selected_claims", 0), "cycle.intake.selected_claims[0]"),
            (
                ("intake", "selected_claims", 0, "source_ref"),
                "cycle.intake.selected_claims[0].source_ref",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence", 0),
                "cycle.intake.selected_claims[0].inherited_evidence[0]",
            ),
            (("frontier_bindings", 0), "cycle.frontier_bindings[0]"),
            (("derived_claims", 0), "cycle.derived_claims[0]"),
            (
                ("derived_claims", 0, "accepted_from"),
                "cycle.derived_claims[0].accepted_from",
            ),
            (("claim_resolutions", 0), "cycle.claim_resolutions[0]"),
            (
                ("claim_resolutions", 0, "current_evidence_refs", 0),
                "cycle.claim_resolutions[0].current_evidence_refs[0]",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs", 0),
                "cycle.claim_resolutions[0].attempted_search_refs[0]",
            ),
            (("decision_assessment",), "cycle.decision_assessment"),
            (("rerun_artifacts", 0), "cycle.rerun_artifacts[0]"),
            (("report_candidate",), "cycle.report_candidate"),
        )
        for path, error_path in cases:
            with self.subTest(path=error_path):
                cycle = (
                    make_populated_cycle_with_blocked_resolution()
                    if "attempted_search_refs" in path
                    else make_populated_cycle()
                )
                nested_value(cycle, path)["extra"] = "hidden"
                if path[0] == "intake":
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"{re.escape(error_path)} unknown field.*extra",
                )

    def test_nested_objects_and_lists_reject_wrong_container_types(self):
        cases = (
            (("intake",), [], "cycle.intake must be an object"),
            (
                ("intake", "base_revision"),
                [],
                "cycle.intake.base_revision must be an object",
            ),
            (("intake", "framing"), [], "cycle.intake.framing must be an object"),
            (
                ("intake", "framing", "snapshot"),
                [],
                "cycle.intake.framing.snapshot must be an object",
            ),
            (
                ("intake", "workspace_boundary"),
                [],
                "cycle.intake.workspace_boundary must be an object",
            ),
            (("intake", "triggers"), {}, "cycle.intake.triggers must be a list"),
            (
                ("intake", "selected_claims"),
                {},
                "cycle.intake.selected_claims must be a list",
            ),
            (
                ("intake", "framing", "snapshot", "subject_resolution"),
                [],
                "subject_resolution must be an object",
            ),
            (
                ("intake", "triggers", 0),
                [],
                r"cycle\.intake\.triggers\[0\] must be an object",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs"),
                {},
                "evidence_refs must be a list",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0),
                [],
                r"evidence_refs\[0\] must be an object",
            ),
            (
                ("intake", "selected_claims", 0),
                [],
                r"cycle\.intake\.selected_claims\[0\] must be an object",
            ),
            (
                ("intake", "selected_claims", 0, "source_ref"),
                [],
                "source_ref must be an object",
            ),
            (
                ("intake", "selected_claims", 0, "selection_reasons"),
                {},
                "selection_reasons must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "trigger_ids"),
                {},
                "trigger_ids must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence"),
                {},
                "inherited_evidence must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence", 0),
                [],
                r"inherited_evidence\[0\] must be an object",
            ),
            (("frontier_bindings",), {}, "cycle.frontier_bindings must be a list"),
            (
                ("frontier_bindings", 0),
                [],
                r"cycle.frontier_bindings\[0\] must be an object",
            ),
            (
                ("frontier_bindings", 0, "claim_ids"),
                {},
                "claim_ids must be a list",
            ),
            (
                ("frontier_bindings", 0, "expected_evidence"),
                [],
                "expected_evidence must be non-empty text",
            ),
            (
                ("claim_resolutions",),
                {},
                "cycle.claim_resolutions must be a list",
            ),
            (("derived_claims",), {}, "cycle.derived_claims must be a list"),
            (
                ("derived_claims", 0),
                [],
                r"cycle.derived_claims\[0\] must be an object",
            ),
            (
                ("derived_claims", 0, "accepted_from"),
                [],
                "accepted_from must be an object or null",
            ),
            (
                ("derived_claims", 0, "accepted_from", "evidence_refs"),
                {},
                "accepted_from.evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0),
                [],
                r"cycle.claim_resolutions\[0\] must be an object",
            ),
            (
                ("claim_resolutions", 0, "current_evidence_refs"),
                {},
                "current_evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "counter_evidence_refs"),
                {},
                "counter_evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "bound_frontier_ids"),
                {},
                "bound_frontier_ids must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_loop_ids"),
                {},
                "attempted_loop_ids must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs"),
                {},
                "attempted_search_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs", 0),
                [],
                r"attempted_search_refs\[0\] must be an object",
            ),
            (
                ("claim_resolutions", 0, "split_child_ids"),
                {},
                "split_child_ids must be a list",
            ),
            (
                ("decision_assessment",),
                [],
                "cycle.decision_assessment must be an object or null",
            ),
            (
                ("decision_assessment", "supporting_claim_ids"),
                {},
                "supporting_claim_ids must be a list",
            ),
            (
                ("decision_assessment", "blocked_claim_ids"),
                {},
                "blocked_claim_ids must be a list",
            ),
            (
                ("decision_assessment", "required_reruns"),
                {},
                "required_reruns must be a list",
            ),
            (("rerun_artifacts",), {}, "cycle.rerun_artifacts must be a list"),
            (
                ("rerun_artifacts", 0),
                [],
                r"cycle.rerun_artifacts\[0\] must be an object",
            ),
            (
                ("report_candidate",),
                [],
                "cycle.report_candidate must be an object or null",
            ),
            (("audit",), {}, "cycle.audit must be a list"),
        )
        for path, replacement, pattern in cases:
            with self.subTest(path=path):
                cycle = (
                    make_populated_cycle_with_blocked_resolution()
                    if "attempted_search_refs" in path
                    else make_populated_cycle()
                )
                set_nested_value(cycle, path, replacement)
                if path[0] == "intake":
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_intake_foundation_scalars_are_strict(self):
        cases = [
            (
                ("intake", "base_revision", "revision_id"),
                "REV-1",
                "base_revision.revision_id must match REV-NNNN",
            ),
            (
                ("intake", "base_revision", "report_path"),
                "reports/bad\n.md",
                "base_revision.report_path must not contain control characters",
            ),
            (
                ("intake", "base_revision", "report_sha256"),
                "A" * 64,
                "base_revision.report_sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "base_revision", "action_class"),
                "Buy",
                "base_revision.action_class is unsupported",
            ),
            (
                ("intake", "framing", "path"),
                "other.json",
                "cycle.intake.framing.path must be framing_contract.json",
            ),
            (
                ("intake", "framing", "sha256"),
                "bad",
                "cycle.intake.framing.sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "workspace_boundary", "frontier_registry_sha256"),
                "bad",
                "frontier_registry_sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "workspace_boundary", "max_existing_loop_number"),
                True,
                "max_existing_loop_number must be an integer >= 0",
            ),
        ]
        snapshot_fields = (
            "research_posture",
            "time_horizon",
            "market_scope",
            "risk_appetite",
            "output_expectation",
            "report_language",
            "budget_appetite",
        )
        cases.extend(
            (
                ("intake", "framing", "snapshot", field),
                "",
                rf"{field} must be non-empty text",
            )
            for field in snapshot_fields
        )
        for path, replacement, pattern in cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        cycle = make_populated_cycle()
        cycle["intake_sha256"] = "A" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle.intake_sha256 must be a lowercase SHA-256",
        )

    def test_triggers_and_evidence_refs_enforce_ids_vocab_and_timestamps(self):
        intake_cases = (
            (
                ("intake", "triggers", 0, "trigger_id"),
                "RC-0001-TRG-1",
                "trigger_id must match RC-NNNN-TRG-NN",
            ),
            (
                ("intake", "triggers", 0, "trigger_id"),
                "RC-0002-TRG-01",
                "trigger_id must belong to cycle RC-0001",
            ),
            (
                ("intake", "triggers", 0, "kind"),
                "neutral",
                "trigger kind is unsupported",
            ),
            (
                ("intake", "triggers", 0, "statement"),
                "",
                "trigger.*statement must be non-empty text",
            ),
            (
                ("intake", "triggers", 0, "observed_at"),
                "2026-02-30",
                "observed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "kind"),
                "url",
                r"evidence_refs\[0\]\.kind must be source or artifact",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "source_id"),
                "src-001\n",
                "source_id must match src-NNN",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "checked_at"),
                "2026-07-15",
                "checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for path, replacement, pattern in intake_cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_selected_claim_scalars_use_locked_ids_and_vocabularies(self):
        cases = (
            (
                ("claim_id",),
                "RC-0001-CL-1",
                "claim_id must match RC-NNNN-CL-NN",
            ),
            (
                ("claim_id",),
                "RC-0002-CL-01",
                "claim_id must belong to cycle RC-0001",
            ),
            (("statement",), "", "selected_claims.*statement must be non-empty text"),
            (("source_ref", "path"), "", "source_ref.path must be non-empty text"),
            (
                ("source_ref", "sha256"),
                "bad",
                "source_ref.sha256 must be a lowercase SHA-256",
            ),
            (
                ("source_ref", "locator"),
                "",
                "source_ref.locator must be non-empty text",
            ),
            (
                ("source_ref", "historical_claim_id"),
                "",
                "historical_claim_id must be non-empty text or null",
            ),
            (("importance",), "urgent", "claim importance is unsupported"),
            (
                ("selection_reasons", 0),
                "manual",
                "selection reason is unsupported",
            ),
            (
                ("trigger_ids", 0),
                "RC-0002-TRG-01",
                "trigger_ids.*must belong to cycle RC-0001",
            ),
            (("inherited_grade",), "E", "inherited_grade is unsupported"),
            (
                ("inherited_confidence",),
                "certain",
                "inherited_confidence is unsupported",
            ),
            (
                ("inherited_evidence", 0, "freshness"),
                "expired",
                "freshness is unsupported",
            ),
            (
                ("inherited_evidence", 0, "checked_at"),
                "2026-07-15",
                "inherited_evidence.*checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                ("inherited_evidence", 0, "reason"),
                "",
                "inherited_evidence.*reason must be non-empty text",
            ),
        )
        for relative_path, replacement, pattern in cases:
            with self.subTest(path=relative_path):
                cycle = make_populated_cycle()
                path = ("intake", "selected_claims", 0, *relative_path)
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_frontier_binding_scalars_are_strict_and_same_cycle(self):
        cases = (
            ("frontier_id", "", "frontier_id must be non-empty text"),
            ("action", "", "frontier_bindings.*action is unsupported"),
            (
                "claim_ids",
                ["RC-0002-CL-01"],
                "claim_ids must belong to cycle RC-0001",
            ),
            (
                "expected_evidence",
                "",
                "expected_evidence.*must be non-empty text",
            ),
            (
                "baseline_loop_count",
                True,
                "baseline_loop_count must be an integer >= 0",
            ),
            (
                "baseline_review_count",
                True,
                "baseline_review_count must be an integer >= 0",
            ),
            (
                "registry_sha256",
                "bad",
                "registry_sha256 must be a lowercase SHA-256",
            ),
            (
                "bound_at",
                "2026-07-15",
                "bound_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["frontier_bindings"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_derived_claim_scalars_and_parent_reference_are_strict(self):
        cases = (
            ("claim_id", "RC-0001-DC-1", "claim_id must match RC-NNNN-DC-NN"),
            (
                "claim_id",
                "RC-0002-DC-01",
                "claim_id must belong to cycle RC-0001",
            ),
            ("origin", "", "derived_claims.*origin must be non-empty text"),
            ("statement", "", "derived_claims.*statement must be non-empty text"),
            (
                "derived_from",
                "RC-0001-CL-99",
                "emergent request.derived_from must be null",
            ),
            (
                "acceptance_rationale",
                "",
                "acceptance_rationale must be non-empty text",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        for field in ("loop_id", "dispatch_id"):
            with self.subTest(accepted_from=field):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0]["accepted_from"][field] = ""
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"accepted_from\.{field} must be non-empty text",
                )

    def test_missing_derived_claim_id_uses_the_public_contract_error(self):
        cycle = make_populated_cycle()
        del cycle["derived_claims"][0]["claim_id"]

        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle\.derived_claims\[0\] missing field\(s\): claim_id",
        )

    def test_malformed_derived_claim_id_containers_use_the_public_error(self):
        for malformed_id in ([], {}):
            with self.subTest(malformed_id=malformed_id):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0]["claim_id"] = malformed_id

                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    r"cycle\.derived_claims\[0\]\.claim_id must match RC-NNNN-DC-NN",
                )

    def test_free_text_rejects_unicode_c1_controls(self):
        cases = (
            (
                ("derived_claims", 0, "statement"),
                r"cycle\.derived_claims\[0\]\.statement must not contain control characters",
            ),
            (
                ("claim_resolutions", 0, "rationale"),
                r"cycle\.claim_resolutions\[0\]\.rationale must not contain control characters",
            ),
        )
        for path, pattern in cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, "plain\u0085text")

                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        ordinary_unicode = make_populated_cycle()
        ordinary_unicode["derived_claims"][0]["statement"] = "普通文本 café — Δ"
        ordinary_unicode["claim_resolutions"][0]["rationale"] = "证据审阅完成"
        attach_valid_audit(ordinary_unicode)
        self.assertIs(
            ordinary_unicode,
            revisit_contract.validate_cycle(ordinary_unicode),
        )

    def test_claim_resolution_scalars_and_references_are_strict(self):
        cases = (
            ("claim_id", "bad", "claim_id must match RC-NNNN-CL-NN or RC-NNNN-DC-NN"),
            (
                "claim_id",
                "RC-0002-CL-01",
                "claim_id must belong to cycle RC-0001",
            ),
            (
                "claim_id",
                "RC-0001-CL-99",
                "claim_id must reference a known same-cycle claim",
            ),
            ("status", "open", "claim resolution status is unsupported"),
            (
                "revised_statement",
                [],
                "revised_statement must be non-empty text or null",
            ),
            ("rationale", [], "rationale must be non-empty text or null"),
            ("missing_proof", [], "missing_proof must be non-empty text or null"),
            (
                "verdict_impact",
                [],
                "verdict_impact must be non-empty text or null",
            ),
            ("current_grade", "E", "current_grade is unsupported"),
            (
                "current_confidence",
                "certain",
                "current_confidence is unsupported",
            ),
            (
                "bound_frontier_ids",
                [""],
                "bound_frontier_ids must contain non-empty text",
            ),
            (
                "attempted_loop_ids",
                [""],
                "attempted_loop_ids must contain non-empty text",
            ),
            (
                "split_child_ids",
                ["RC-0002-DC-01"],
                "split_child_ids must belong to cycle RC-0001",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["claim_resolutions"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        for field in ("loop_id", "query"):
            with self.subTest(attempted_search=field):
                cycle = make_populated_cycle_with_blocked_resolution()
                cycle["claim_resolutions"][0]["attempted_search_refs"][0][field] = ""
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"attempted_search_refs.*{field} must be non-empty text",
                )

    def test_decision_rerun_and_report_candidate_scalars_are_strict(self):
        decision_cases = (
            ("new_action_class", "Buy", "new_action_class is unsupported"),
            (
                "financial_bridge_affected",
                1,
                "financial_bridge_affected must be a boolean",
            ),
            (
                "financial_bridge_rationale",
                [],
                "financial_bridge_rationale must be non-empty text",
            ),
            ("risk_class_changed", 0, "risk_class_changed must be a boolean"),
            (
                "risk_class_rationale",
                [],
                "risk_class_rationale must be non-empty text",
            ),
            (
                "supporting_claim_ids",
                ["RC-0002-CL-01"],
                "supporting_claim_ids must belong to cycle RC-0001",
            ),
            ("verdict_rationale", "", "verdict_rationale must be non-empty text"),
            (
                "blocked_claim_ids",
                ["bad"],
                "blocked_claim_ids must match RC-NNNN-CL-NN or RC-NNNN-DC-NN",
            ),
            ("change_class", "none", "change_class is unsupported"),
            (
                "required_reruns",
                ["all"],
                "required_reruns entry is unsupported",
            ),
        )
        for field, replacement, pattern in decision_cases:
            with self.subTest(decision_field=field):
                cycle = make_populated_cycle()
                cycle["decision_assessment"][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_ids_and_required_reruns_are_unique_within_arrays(self):
        cases = (
            (
                "triggers",
                lambda cycle: cycle["intake"]["triggers"].append(
                    copy.deepcopy(cycle["intake"]["triggers"][0])
                ),
                "cycle.intake.triggers contains duplicate trigger_id",
                True,
            ),
            (
                "selected_claims",
                lambda cycle: cycle["intake"]["selected_claims"].append(
                    copy.deepcopy(cycle["intake"]["selected_claims"][0])
                ),
                "cycle.intake.selected_claims contains duplicate claim_id",
                True,
            ),
            (
                "selected_trigger_ids",
                lambda cycle: cycle["intake"]["selected_claims"][0][
                    "trigger_ids"
                ].append("RC-0001-TRG-01"),
                "trigger_ids must not contain duplicate IDs",
                True,
            ),
            (
                "bindings",
                lambda cycle: cycle["frontier_bindings"].append(
                    copy.deepcopy(cycle["frontier_bindings"][0])
                ),
                "cycle.frontier_bindings contains duplicate frontier_id",
                False,
            ),
            (
                "binding_claim_ids",
                lambda cycle: cycle["frontier_bindings"][0]["claim_ids"].append(
                    "RC-0001-CL-01"
                ),
                "frontier_bindings.*claim_ids must not contain duplicate IDs",
                False,
            ),
            (
                "derived_claims",
                lambda cycle: cycle["derived_claims"].append(
                    copy.deepcopy(cycle["derived_claims"][0])
                ),
                "cycle.derived_claims contains duplicate claim_id",
                False,
            ),
            (
                "claim_resolutions",
                lambda cycle: cycle["claim_resolutions"].append(
                    copy.deepcopy(cycle["claim_resolutions"][0])
                ),
                "cycle.claim_resolutions contains duplicate claim_id",
                False,
            ),
            (
                "bound_frontier_ids",
                lambda cycle: cycle["claim_resolutions"][0][
                    "bound_frontier_ids"
                ].append("frontier-001"),
                "bound_frontier_ids must not contain duplicate IDs",
                False,
            ),
            (
                "attempted_loop_ids",
                lambda cycle: cycle["claim_resolutions"][0][
                    "attempted_loop_ids"
                ].append("loop-001"),
                "attempted_loop_ids must not contain duplicate IDs",
                False,
            ),
            (
                "split_child_ids",
                lambda cycle: cycle["claim_resolutions"][0].update(
                    {
                        "split_child_ids": [
                            "RC-0001-DC-01",
                            "RC-0001-DC-01",
                        ]
                    }
                ),
                "split_child_ids must not contain duplicate IDs",
                False,
            ),
            (
                "supporting_claim_ids",
                lambda cycle: cycle["decision_assessment"][
                    "supporting_claim_ids"
                ].append("RC-0001-CL-01"),
                "supporting_claim_ids must not contain duplicate IDs",
                False,
            ),
            (
                "required_reruns",
                lambda cycle: cycle["decision_assessment"]["required_reruns"].append(
                    "delta-frontier-review"
                ),
                "required_reruns must not contain duplicates",
                False,
            ),
        )
        for name, mutate, pattern, intake_changed in cases:
            with self.subTest(case=name):
                cycle = (
                    make_populated_cycle_with_blocked_resolution()
                    if name == "attempted_loop_ids"
                    else make_populated_cycle()
                )
                mutate(cycle)
                if intake_changed:
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_audit_rows_enforce_sequence_hash_chain_and_current_state(self):
        cases = (
            (
                "sequence_bool",
                lambda cycle: cycle["audit"][0].update({"sequence": True}),
                r"audit\[0\].sequence must be an integer >= 1",
            ),
            (
                "sequence_gap",
                lambda cycle: cycle["audit"][0].update({"sequence": 2}),
                "audit sequence must be continuous starting at 1",
            ),
            (
                "timestamp",
                lambda cycle: cycle["audit"][0].update({"timestamp": "2026-07-15"}),
                r"audit\[0\].timestamp must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "command",
                lambda cycle: cycle["audit"][0].update({"command": ""}),
                r"audit\[0\].command must be non-empty text",
            ),
            (
                "affected_id_text",
                lambda cycle: cycle["audit"][0].update({"affected_ids": [""]}),
                "affected_ids must contain non-empty text",
            ),
            (
                "affected_id_unique",
                lambda cycle: cycle["audit"][0].update(
                    {"affected_ids": ["RC-0001", "RC-0001"]}
                ),
                "affected_ids must not contain duplicate IDs",
            ),
            (
                "pre_hash",
                lambda cycle: cycle["audit"][0].update({"pre_state_sha256": "bad"}),
                "pre_state_sha256 must be a lowercase SHA-256",
            ),
            (
                "post_hash",
                lambda cycle: cycle["audit"][0].update({"post_state_sha256": "bad"}),
                "post_state_sha256 must be a lowercase SHA-256",
            ),
            (
                "current_state",
                lambda cycle: cycle["audit"][0].update(
                    {"post_state_sha256": "1" * 64}
                ),
                "last audit post_state_sha256 does not match current state",
            ),
        )
        for name, mutate, pattern in cases:
            with self.subTest(case=name):
                cycle = attach_valid_audit(make_populated_cycle())
                mutate(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        cycle = make_populated_cycle()
        state_hash = test_semantic_sha256(
            {key: value for key, value in cycle.items() if key != "audit"}
        )
        cycle["audit"] = [
            {
                "sequence": 1,
                "timestamp": "2026-07-15T00:45:00Z",
                "command": "revisit-start",
                "affected_ids": ["RC-0001"],
                "pre_state_sha256": "0" * 64,
                "post_state_sha256": "1" * 64,
            },
            {
                "sequence": 2,
                "timestamp": "2026-07-15T00:46:00Z",
                "command": "revisit-update",
                "affected_ids": ["RC-0001-CL-01"],
                "pre_state_sha256": "2" * 64,
                "post_state_sha256": state_hash,
            },
        ]
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "audit pre/post hash continuity is broken",
        )

    def test_audit_rows_have_exact_keys(self):
        cycle = attach_valid_audit(make_populated_cycle())
        cycle["audit"][0]["extra"] = "hidden"
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle.audit\[0\] unknown field.*extra",
        )

    def test_locked_public_surface_and_constants_are_exact(self):
        expected_names = {
            "SCHEMA_VERSION",
            "POINTER_FILENAME",
            "CYCLES_DIRNAME",
            "ACTION_CLASSES",
            "CYCLE_STATUSES",
            "TERMINAL_CYCLE_STATUSES",
            "TRIGGER_KINDS",
            "SELECTION_REASONS",
            "CLAIM_IMPORTANCE",
            "CLAIM_TERMINAL_STATES",
            "CURRENT_GRADES",
            "CURRENT_CONFIDENCE",
            "FRESHNESS",
            "CYCLE_ID_RE",
            "REVISION_ID_RE",
            "TRIGGER_ID_RE",
            "CLAIM_ID_RE",
            "DERIVED_CLAIM_ID_RE",
            "SHA256_RE",
            "CYCLE_KEYS",
            "RevisitIssue",
            "RevisitHistoryFact",
            "RevisitContractError",
            "RevisitContext",
            "build_revisit_context",
            "SOURCE_EVIDENCE_KEYS",
            "ARTIFACT_EVIDENCE_KEYS",
            "validate_evidence_ref",
            "validate_intake_request",
            "add_derived_claim",
            "bind_frontier",
            "derive_claim_issues",
            "derive_freshness_issues",
            "derive_frontier_requirements",
            "mark_ready_for_report",
            "resolve_claim",
            "assess_decision",
            "derive_change_class",
            "derive_rerun_requirements",
            "record_rerun",
            "register_report_candidate",
            "complete_cycle",
            "allocate_cycle_and_revision_ids",
            "evaluate_history",
            "create_cycle",
            "empty_pointer",
            "validate_pointer",
            "canonical_semantic_bytes",
            "canonical_value_bytes",
            "canonical_document_bytes",
            "sha256_bytes",
            "sha256_file",
            "workspace_transaction",
            "pointer_path",
            "cycle_directory",
            "cycle_json_path",
            "cycle_markdown_path",
            "load_pointer",
            "load_cycle",
            "list_cycle_ids",
            "persist_pointer",
            "persist_cycle",
            "RevisitPersistenceRollbackError",
            "render_cycle_markdown",
            "render_report_metadata",
            "semantic_sha256",
            "state_without_audit",
            "cycle_state_sha256",
            "intake_sha256",
            "validate_cycle",
            "normalize_workspace_relative_path",
            "resolve_workspace_path",
        }
        self.assertEqual(expected_names, set(revisit_contract.__all__))
        expected_values = {
            "SCHEMA_VERSION": 1,
            "POINTER_FILENAME": "revisit_contract.json",
            "CYCLES_DIRNAME": "revisit_cycles",
            "CYCLE_STATUSES": ("active", "ready_for_report", "completed", "aborted"),
            "TERMINAL_CYCLE_STATUSES": frozenset({"completed", "aborted"}),
            "TRIGGER_KINDS": ("upgrade", "downgrade", "invalidation"),
            "SELECTION_REASONS": (
                "trigger_affected",
                "decision_load_bearing",
                "stale_but_reused",
            ),
            "CLAIM_IMPORTANCE": ("critical", "high", "medium", "low"),
            "CLAIM_TERMINAL_STATES": (
                "confirmed",
                "weakened",
                "refuted",
                "split",
                "blocked",
            ),
            "CURRENT_GRADES": ("A", "B", "C", "D"),
            "CURRENT_CONFIDENCE": ("high", "medium", "low", "speculative"),
            "FRESHNESS": ("fresh", "stale", "unknown"),
        }
        for name, expected in expected_values.items():
            with self.subTest(constant=name):
                self.assertEqual(expected, getattr(revisit_contract, name, None))

        expected_patterns = {
            "CYCLE_ID_RE": r"^RC-(?P<number>[0-9]{4})$",
            "REVISION_ID_RE": r"^REV-(?P<number>[0-9]{4})$",
            "TRIGGER_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-TRG-(?P<number>[0-9]{2})$",
            "CLAIM_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-CL-(?P<number>[0-9]{2})$",
            "DERIVED_CLAIM_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-DC-(?P<number>[0-9]{2})$",
            "SHA256_RE": r"^[0-9a-f]{64}$",
        }
        for name, expected in expected_patterns.items():
            with self.subTest(regex=name):
                pattern = getattr(revisit_contract, name, None)
                self.assertEqual(expected, getattr(pattern, "pattern", None))

    def test_revisit_issue_is_a_frozen_value_object(self):
        issue_type = getattr(revisit_contract, "RevisitIssue", None)
        self.assertTrue(dataclasses.is_dataclass(issue_type), "RevisitIssue is missing")
        issue = issue_type("bad_state", "cycle.status", "Unsupported", "open")
        self.assertEqual(
            ("bad_state", "cycle.status", "Unsupported", "open"),
            (issue.code, issue.path, issue.message, issue.evidence),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issue.code = "changed"

    def test_cycle_state_hash_changes_for_every_non_audit_top_level_field(self):
        cycle = make_populated_cycle()
        baseline = revisit_contract.cycle_state_sha256(cycle)

        audit_changed = copy.deepcopy(cycle)
        audit_changed["audit"] = [{"anything": "is excluded"}]
        self.assertEqual(baseline, revisit_contract.cycle_state_sha256(audit_changed))

        for field in revisit_contract.CYCLE_KEYS - {"audit"}:
            with self.subTest(field=field):
                changed = copy.deepcopy(cycle)
                changed[field] = {"changed_field": field}
                self.assertNotEqual(
                    baseline,
                    revisit_contract.cycle_state_sha256(changed),
                )

    def test_valid_task4_populated_and_terminal_cycles_are_non_mutating(self):
        cycles = [make_minimal_cycle(), make_populated_cycle()]

        ready = make_minimal_cycle()
        ready["status"] = "ready_for_report"
        attach_valid_audit(ready)
        cycles.append(ready)

        completed = make_terminal_cycle_fixture(
            make_populated_cycle(), "completed"
        )
        cycles.append(completed)

        aborted = make_terminal_cycle_fixture(
            make_minimal_cycle(),
            "aborted",
            abort_reason="Primary evidence became unavailable.",
        )
        cycles.append(aborted)

        for cycle in cycles:
            with self.subTest(status=cycle["status"], audited=bool(cycle["audit"])):
                original = copy.deepcopy(cycle)
                self.assertIs(cycle, revisit_contract.validate_cycle(cycle))
                self.assertEqual(original, cycle)

    def test_locked_nullable_values_and_trigger_timestamp_variant_are_valid(self):
        cycle = make_minimal_cycle()
        cycle["intake"]["triggers"][0]["observed_at"] = "2026-07-15T00:30:00Z"
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
        attach_valid_audit(cycle)

        self.assertIs(cycle, revisit_contract.validate_cycle(cycle))

    def test_nullable_inherited_provenance_round_trips_request_cycle_and_mirror(self):
        template = make_minimal_cycle()
        trigger = copy.deepcopy(template["intake"]["triggers"][0])
        trigger.pop("trigger_id")
        claim = copy.deepcopy(template["intake"]["selected_claims"][0])
        claim.pop("claim_id")
        claim.pop("trigger_ids")
        claim["trigger_indexes"] = [1]
        claim["inherited_grade"] = None
        claim["inherited_confidence"] = None
        request = {"triggers": [trigger], "selected_claims": [claim]}

        self.assertIs(request, revisit_contract.validate_intake_request(request))
        cycle = revisit_contract.create_cycle(
            cycle_id="RC-0001",
            candidate_revision_id="REV-0002",
            base_revision=make_initial_revision(),
            framing_sha256="b" * 64,
            framing_snapshot=copy.deepcopy(
                template["intake"]["framing"]["snapshot"]
            ),
            frontier_registry_sha256="c" * 64,
            max_existing_loop_number=0,
            request=request,
            timestamp="2026-07-15T00:00:00Z",
        )

        selected = cycle["intake"]["selected_claims"][0]
        self.assertIsNone(selected["inherited_grade"])
        self.assertIsNone(selected["inherited_confidence"])
        self.assertIs(cycle, revisit_contract.validate_cycle(cycle))
        claim_row = next(
            line
            for line in revisit_contract.render_cycle_markdown(cycle).splitlines()
            if line.startswith("| RC-0001-CL-01 |")
        )
        self.assertIn("| — | — |", claim_row)

    def test_cycle_missing_required_field_is_rejected(self):
        cycle = make_minimal_cycle()
        del cycle["audit"]
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle missing field.*audit",
        )

        rerun_cases = (
            ("kind", "", "rerun_artifacts.*kind must be non-empty text"),
            ("scope", "partial", "bridge rerun requires affected or full scope"),
            ("round", True, "bridge rerun round must be null"),
            ("path", "", "rerun_artifacts.*path must be non-empty text"),
            ("sha256", "bad", "rerun_artifacts.*sha256 must be a lowercase"),
            (
                "recorded_at",
                "2026-07-15",
                "rerun_artifacts.*recorded_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in rerun_cases:
            with self.subTest(rerun_field=field):
                cycle = make_populated_cycle()
                cycle["rerun_artifacts"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        candidate_cases = (
            ("revision_id", "REV-1", "report_candidate.revision_id must match REV-NNNN"),
            ("revision_of", "REV-1", "report_candidate.revision_of must match REV-NNNN"),
            ("report_path", "", "report_candidate.report_path must be non-empty text"),
            (
                "report_sha256",
                "bad",
                "report_candidate.report_sha256 must be a lowercase SHA-256",
            ),
            (
                "registered_at",
                "2026-07-15",
                "report_candidate.registered_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in candidate_cases:
            with self.subTest(candidate_field=field):
                cycle = make_populated_cycle()
                cycle["report_candidate"][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        artifact_cases = (
            ("path", "", "current_evidence_refs.*path must be non-empty text"),
            ("sha256", "bad", "current_evidence_refs.*sha256 must be a lowercase"),
            ("locator", "", "current_evidence_refs.*locator must be non-empty text"),
            (
                "checked_at",
                "2026-07-15",
                "current_evidence_refs.*checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in artifact_cases:
            with self.subTest(artifact_field=field):
                cycle = make_populated_cycle()
                cycle["claim_resolutions"][0]["current_evidence_refs"][0][field] = (
                    replacement
                )
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )


class TestTask8RerunArtifacts(unittest.TestCase):
    def test_task8_public_transition_and_render_interfaces_are_exported(self):
        for name in (
            "record_rerun",
            "register_report_candidate",
            "complete_cycle",
            "render_report_metadata",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(revisit_contract, name, None)), name)

    @staticmethod
    def _active_assessed_cycle():
        cycle = make_populated_cycle()
        cycle["rerun_artifacts"] = []
        cycle["report_candidate"] = None
        cycle["status"] = "active"
        cycle["completed_at"] = None
        return attach_valid_audit(cycle)

    @staticmethod
    def _artifact(kind, path, *, scope=None, round_number=None, digest="1" * 64):
        return {
            "kind": kind,
            "scope": scope,
            "round": round_number,
            "path": path,
            "sha256": digest,
            "recorded_at": "2026-07-14T14:00:00Z",
        }

    def test_old_bridge_path_without_cycle_id_is_rejected(self):
        cycle = self._active_assessed_cycle()
        artifact = self._artifact(
            "bridge",
            "financials/AXTI_bridge.md",
            scope="affected",
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "cycle-specific bridge path",
        ):
            revisit_contract.record_rerun(cycle, artifact)

    def test_all_allowed_rerun_rows_are_exact_copy_on_write_records(self):
        cycle = self._active_assessed_cycle()
        rows = (
            self._artifact(
                "bridge",
                "financials/RC-0001_AXTI_bridge.md",
                scope="full",
                digest="1" * 64,
            ),
            self._artifact(
                "redteam_attack",
                "redteam/RC-0001_round1_redteam.md",
                round_number=1,
                digest="2" * 64,
            ),
            self._artifact(
                "redteam_defense",
                "redteam/RC-0001_round1_defense.md",
                round_number=1,
                digest="3" * 64,
            ),
            self._artifact(
                "thesis_revision",
                "redteam/RC-0001_thesis_revision.md",
                digest="4" * 64,
            ),
        )
        original = copy.deepcopy(cycle)
        updated = cycle
        for index, row in enumerate(rows, start=1):
            previous = updated
            proposed = revisit_contract.record_rerun(previous, row)
            updated = revisit_model.with_audit(
                previous,
                proposed,
                "record-rerun",
                [row["path"]],
                f"2026-07-14T14:00:0{index}Z",
            )
        self.assertEqual(original, cycle)
        self.assertEqual(list(rows), updated["rerun_artifacts"])
        self.assertIs(updated, revisit_contract.validate_cycle(updated))

    def test_rerun_kind_applicability_path_hash_and_uniqueness_are_strict(self):
        valid = self._artifact(
            "bridge",
            "financials/RC-0001_AXTI_bridge.md",
            scope="affected",
        )
        cases = (
            ({**valid, "kind": "other"}, "rerun artifact kind is unsupported"),
            ({**valid, "scope": None}, "bridge rerun requires affected or full scope"),
            ({**valid, "round": 1}, "bridge rerun round must be null"),
            (
                self._artifact(
                    "redteam_attack",
                    "redteam/RC-0001_round1_redteam.md",
                    scope="full",
                    round_number=1,
                ),
                "red-team rerun scope must be null",
            ),
            (
                self._artifact(
                    "redteam_attack",
                    "redteam/RC-0001_round2_redteam.md",
                    round_number=1,
                ),
                "red-team rerun path must match its round",
            ),
            (
                self._artifact(
                    "thesis_revision",
                    "redteam/RC-0002_thesis_revision.md",
                ),
                "cycle-specific thesis revision path",
            ),
        )
        for artifact, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    pattern,
                ):
                    revisit_contract.record_rerun(
                        self._active_assessed_cycle(), artifact
                    )

        previous = self._active_assessed_cycle()
        first = revisit_model.with_audit(
            previous,
            revisit_contract.record_rerun(previous, valid),
            "record-rerun",
            [valid["path"]],
            "2026-07-14T14:00:01Z",
        )
        for duplicate in (
            {**valid, "sha256": "2" * 64},
            {**valid, "path": "financials/RC-0001_OTHER_bridge.md"},
        ):
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "rerun artifact (path|hash) is already registered",
            ):
                revisit_contract.record_rerun(first, duplicate)

    def test_record_rerun_cli_grammar_is_exact(self):
        parser = revisit_cycle_cli.build_parser()
        for kind in (
            "bridge",
            "redteam-attack",
            "redteam-defense",
            "thesis-revision",
        ):
            with self.subTest(kind=kind):
                args = parser.parse_args(
                    [
                        "workspace",
                        "record-rerun",
                        "RC-0001",
                        "--kind",
                        kind,
                        "--path",
                        "artifact.md",
                    ]
                )
                self.assertEqual(kind, args.kind)

    def test_record_rerun_cli_hashes_exact_bytes_and_appends_one_audit_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task6_ready_workspace(Path(directory))
            artifact = workspace / "financials" / f"{cycle_id}_TEST_bridge.md"
            artifact.parent.mkdir()
            payload = b"cycle-specific bridge bytes\r\n"
            artifact.write_bytes(payload)
            before = revisit_contract.load_cycle(workspace, cycle_id)

            result = run_revisit_cycle_cli(
                workspace,
                "record-rerun",
                cycle_id,
                "--kind",
                "bridge",
                "--scope",
                "affected",
                "--path",
                artifact.relative_to(workspace).as_posix(),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            after = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("active", after["status"])
            self.assertEqual(len(before["audit"]) + 1, len(after["audit"]))
            self.assertEqual("record-rerun", after["audit"][-1]["command"])
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                after["rerun_artifacts"][0]["sha256"],
            )
            self.assertEqual(payload, artifact.read_bytes())


class TestTask8ReportMetadata(unittest.TestCase):
    @staticmethod
    def _ready_model_cycle():
        cycle = make_terminal_model_cycle("confirmed")
        proposed = revisit_contract.assess_decision(
            cycle, make_decision_assessment_request()
        )
        cycle = revisit_model.with_audit(
            cycle,
            proposed,
            "assess-decision",
            ["RC-0001"],
            "2026-07-15T00:30:00Z",
        )
        proposed = revisit_contract.mark_ready_for_report(cycle)
        return revisit_model.with_audit(
            cycle,
            proposed,
            "check",
            ["RC-0001"],
            "2026-07-15T00:31:00Z",
        )

    def test_render_report_metadata_matches_entire_managed_block_bytes(self):
        cycle = self._ready_model_cycle()
        expected = (
            "<!-- sofa:revisit-revision:start -->\n"
            "## Revisit Revision Metadata\n"
            "\n"
            "| Field | Value |\n"
            "| --- | --- |\n"
            "| Cycle ID | RC-0001 |\n"
            "| Revision ID | REV-0002 |\n"
            "| Revision of | REV-0001 |\n"
            f"| Base report SHA-256 | {'a' * 64} |\n"
            "| Base action class | Watch with Trigger |\n"
            "| Current action class | Watch with Trigger |\n"
            "| Change class | evidence_or_claim_only |\n"
            "| Supporting claims | RC-0001-CL-01 |\n"
            "| Blocked claims | none |\n"
            "| Required reruns | delta-frontier-review |\n"
            "<!-- sofa:revisit-revision:end -->\n"
        )
        self.assertEqual(expected, revisit_contract.render_report_metadata(cycle))
        self.assertNotIn("2026-", revisit_contract.render_report_metadata(cycle))

    def test_candidate_requires_all_ordinary_and_revisit_report_areas(self):
        cycle = self._ready_model_cycle()
        metadata = revisit_contract.render_report_metadata(cycle)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            reports = workspace / "reports"
            reports.mkdir()
            report = reports / "TEST_REV-0002.md"
            ordinary_only = complete_ticker_report_bytes() + metadata.encode("utf-8")
            report.write_bytes(ordinary_only)

            missing = sofa_evaluate.evaluate_specific_ticker_report(
                workspace,
                "reports/TEST_REV-0002.md",
                expected_sha256=hashlib.sha256(ordinary_only).hexdigest(),
                expected_metadata=metadata,
            )
            self.assertFalse(missing.passed)
            self.assertEqual(
                {
                    "FINAL_REPORT_MISSING_TRIGGER_DELTA",
                    "FINAL_REPORT_MISSING_CLAIM_DELTA",
                    "FINAL_REPORT_MISSING_EVIDENCE_FRESHNESS_DELTA",
                    "FINAL_REPORT_MISSING_FRONTIER_DELTA",
                    "FINAL_REPORT_MISSING_FINANCIAL_REDTEAM_DELTA",
                    "FINAL_REPORT_MISSING_UNRESOLVED_BLOCKED_GAPS",
                },
                {issue.code for issue in missing.failures},
            )

            revisit_sections = (
                "\n## Trigger Delta\n"
                "## Claim Delta\n"
                "## Evidence Freshness Delta\n"
                "## Frontier Delta\n"
                "## Financial/Red-Team Delta\n"
                "## Unresolved or Blocked Gaps\nNone.\n"
            ).encode("utf-8")
            complete = ordinary_only + revisit_sections
            report.write_bytes(complete)
            accepted = sofa_evaluate.evaluate_specific_ticker_report(
                workspace,
                "reports/TEST_REV-0002.md",
                expected_sha256=hashlib.sha256(complete).hexdigest(),
                expected_metadata=metadata,
            )
            self.assertTrue(accepted.passed, [item.display() for item in accepted.failures])

            delta_only = metadata.encode("utf-8") + revisit_sections
            report.write_bytes(delta_only)
            rejected = sofa_evaluate.evaluate_specific_ticker_report(
                workspace,
                "reports/TEST_REV-0002.md",
                expected_sha256=hashlib.sha256(delta_only).hexdigest(),
                expected_metadata=metadata,
            )
            self.assertFalse(rejected.passed)
            self.assertIn(
                "FINAL_REPORT_MISSING_CONFIDENCE",
                {issue.code for issue in rejected.failures},
            )

    def test_render_report_metadata_cli_is_exact_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task6_ready_workspace(Path(directory))
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            expected = revisit_contract.render_report_metadata(cycle)
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "render-report-metadata",
                cycle_id,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(expected, result.stdout)
            self.assertEqual(before, snapshot_tree(workspace))


class TestTask8ReportCandidate(unittest.TestCase):
    def test_candidate_registration_is_ready_only_copy_on_write_and_one_time(self):
        cycle = TestTask8ReportMetadata._ready_model_cycle()
        candidate = {
            "revision_id": "REV-0002",
            "revision_of": "REV-0001",
            "report_path": "reports/TEST_SOFA_Report_2026-07-14_REV-0002.md",
            "report_sha256": "f" * 64,
            "registered_at": "2026-07-14T15:00:00Z",
        }
        original = copy.deepcopy(cycle)
        proposed = revisit_contract.register_report_candidate(cycle, candidate)
        registered = revisit_model.with_audit(
            cycle,
            proposed,
            "register-report",
            ["REV-0002"],
            "2026-07-14T15:00:00Z",
        )
        self.assertEqual(original, cycle)
        self.assertEqual(candidate, registered["report_candidate"])
        before = revisit_contract.canonical_document_bytes(registered)
        changed = {**candidate, "report_sha256": "e" * 64}
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "report candidate is already registered",
        ):
            revisit_contract.register_report_candidate(registered, changed)
        self.assertEqual(before, revisit_contract.canonical_document_bytes(registered))

        active = copy.deepcopy(cycle)
        active["status"] = "active"
        attach_valid_audit(active)
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "ready_for_report",
        ):
            revisit_contract.register_report_candidate(active, candidate)

    def test_candidate_path_requires_an_exact_reserved_revision_token(self):
        cycle = TestTask8ReportMetadata._ready_model_cycle()
        candidate = {
            "revision_id": "REV-0002",
            "revision_of": "REV-0001",
            "report_path": "reports/TEST_REV-0002.md",
            "report_sha256": "f" * 64,
            "registered_at": "2026-07-14T15:00:00Z",
        }
        for report_path in (
            "reports/TEST_XREV-0002.md",
            "reports/TEST_REV-00020.md",
            "reports/TEST_REV-0003.md",
        ):
            with self.subTest(report_path=report_path):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "containing the reserved revision ID",
                ):
                    revisit_contract.register_report_candidate(
                        cycle,
                        {**candidate, "report_path": report_path},
                    )

    def test_register_report_cli_records_exact_complete_candidate_once(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task6_ready_workspace(Path(directory))
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            current_before = (workspace / revisit_contract.POINTER_FILENAME).read_bytes()
            report = (
                workspace
                / "reports"
                / "TEST_SOFA_Report_2026-07-14_REV-0002.md"
            )
            payload = complete_revisit_report_bytes(cycle)
            report.write_bytes(payload)

            first = run_revisit_cycle_cli(
                workspace,
                "register-report",
                cycle_id,
                "--report",
                report.relative_to(workspace).as_posix(),
            )
            self.assertEqual(0, first.returncode, first.stderr)
            registered = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                registered["report_candidate"]["report_sha256"],
            )
            self.assertEqual("register-report", registered["audit"][-1]["command"])
            self.assertEqual(
                current_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )

            cycle_bytes = (
                workspace
                / revisit_contract.CYCLES_DIRNAME
                / f"{cycle_id}.json"
            ).read_bytes()
            report.write_bytes(payload + b"one byte of drift")
            second = run_revisit_cycle_cli(
                workspace,
                "register-report",
                cycle_id,
                "--report",
                report.relative_to(workspace).as_posix(),
            )
            self.assertEqual(2, second.returncode)
            self.assertIn("already registered", second.stderr)
            self.assertEqual(
                cycle_bytes,
                (
                    workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / f"{cycle_id}.json"
                ).read_bytes(),
            )

    def test_register_report_binds_sibling_candidate_history_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = TestTask8FinalEvaluation._ready_workspace(
                Path(directory)
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            report = workspace / "reports" / "SHARED_REV-0002_REV-0003.md"
            report.write_bytes(complete_revisit_report_bytes(cycle))

            def completed_sibling(report_path):
                ready = make_minimal_cycle(
                    cycle_id="RC-0002", candidate_revision_id="REV-0003"
                )
                ready["status"] = "ready_for_report"
                ready["report_candidate"] = {
                    "revision_id": "REV-0003",
                    "revision_of": "REV-0001",
                    "report_path": report_path,
                    "report_sha256": "f" * 64,
                    "registered_at": "2026-07-15T01:30:00Z",
                }
                attach_valid_audit(ready)
                completed = copy.deepcopy(ready)
                completed["status"] = "completed"
                completed["completed_at"] = "2026-07-15T02:00:00Z"
                return revisit_model.with_audit(
                    ready,
                    completed,
                    "publish",
                    ["RC-0002", "REV-0003"],
                    "2026-07-15T02:00:00Z",
                )

            sibling = completed_sibling("reports/OTHER_REV-0003.md")
            revisit_contract.persist_cycle(
                workspace,
                sibling,
                expected_sha256=None,
            )
            target_cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            target_before = target_cycle_path.read_bytes()
            real_evaluator = revisit_cycle_cli.evaluate_specific_ticker_report

            def claim_same_path_after_history_scan(*args, **kwargs):
                if args[1] != report.relative_to(workspace).as_posix():
                    return real_evaluator(*args, **kwargs)
                mutated = completed_sibling(
                    "reports/SHARED_REV-0002_REV-0003.md"
                )
                sibling_json = (
                    workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / "RC-0002.json"
                )
                sibling_md = (
                    workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / "RC-0002.md"
                )
                sibling_md.write_text(
                    revisit_contract.render_cycle_markdown(mutated),
                    encoding="utf-8",
                )
                sibling_json.write_bytes(
                    revisit_contract.canonical_document_bytes(mutated)
                )
                return real_evaluator(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_specific_ticker_report",
                    side_effect=claim_same_path_after_history_scan,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "register-report",
                        cycle_id,
                        "--report",
                        report.relative_to(workspace).as_posix(),
                    ]
                )

            self.assertEqual(2, result)
            self.assertIn("RC-0002.json", stderr.getvalue())
            self.assertEqual(target_before, target_cycle_path.read_bytes())

    def test_register_report_rejects_historical_base_report_path_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, original_cycle_id = (
                TestTask8FinalEvaluation._ready_workspace(Path(directory))
            )
            self.assertEqual("RC-0001", original_cycle_id)
            original_path = revisit_contract.cycle_json_path(
                workspace, original_cycle_id
            )
            target = revisit_contract.load_cycle(workspace, original_cycle_id)
            target = json.loads(
                json.dumps(target)
                .replace("RC-0001", "RC-0002")
                .replace("REV-0002", "REV-0003")
            )
            target["intake_sha256"] = revisit_contract.intake_sha256(
                target["intake"]
            )
            attach_valid_audit(target)
            revisit_contract.persist_cycle(
                workspace,
                target,
                expected_sha256=None,
            )

            report = workspace / "reports" / "HISTORICAL_BASE_REV-0003.md"
            report.write_bytes(complete_revisit_report_bytes(target))
            relative = report.relative_to(workspace).as_posix()
            history = make_minimal_cycle(
                cycle_id="RC-0001",
                candidate_revision_id="REV-0002",
            )
            history["intake"]["base_revision"]["report_path"] = relative
            history["intake"]["base_revision"]["report_sha256"] = hashlib.sha256(
                report.read_bytes()
            ).hexdigest()
            history["intake_sha256"] = revisit_contract.intake_sha256(
                history["intake"]
            )
            attach_valid_audit(history)
            aborted = copy.deepcopy(history)
            aborted["status"] = "aborted"
            aborted["aborted_at"] = "2026-07-15T02:00:00Z"
            aborted["abort_reason"] = "Historical test reservation."
            history = revisit_model.with_audit(
                history,
                aborted,
                "abort",
                ["RC-0001"],
                "2026-07-15T02:00:00Z",
            )
            revisit_contract.persist_cycle(
                workspace,
                history,
                expected_sha256=revisit_contract.sha256_file(original_path),
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-report",
                "RC-0002",
                "--report",
                relative,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("already registered", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_registered_candidate_can_be_preserved_by_terminal_abort(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = TestTask8FinalEvaluation._ready_workspace(
                Path(directory)
            )
            report = TestTask8FinalEvaluation._register_candidate(
                workspace,
                cycle_id,
            )
            before = revisit_contract.load_cycle(workspace, cycle_id)
            candidate = copy.deepcopy(before["report_candidate"])
            pointer_bytes = (
                workspace / revisit_contract.POINTER_FILENAME
            ).read_bytes()
            report.write_bytes(report.read_bytes() + b"candidate drift")
            drifted_report = report.read_bytes()

            aborted = run_revisit_cycle_cli(
                workspace,
                "abort",
                cycle_id,
                "--reason",
                "The registered candidate drifted before publication.",
            )

            self.assertEqual(0, aborted.returncode, aborted.stderr)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("aborted", cycle["status"])
            self.assertEqual(candidate, cycle["report_candidate"])
            self.assertEqual("abort", cycle["audit"][-1]["command"])
            self.assertEqual(len(before["audit"]) + 1, len(cycle["audit"]))
            self.assertEqual(
                pointer_bytes,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )
            self.assertEqual(drifted_report, report.read_bytes())


class TestTask8FinalEvaluation(unittest.TestCase):
    @staticmethod
    def _ready_workspace(root: Path):
        workspace, cycle_id = make_task6_ready_workspace(root)
        checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
        if checked.returncode != 0:
            raise AssertionError(checked.stderr)
        return workspace, cycle_id

    @staticmethod
    def _register_candidate(
        workspace: Path,
        cycle_id: str,
        report_name: str = "TEST_SOFA_Report_REV-0002.md",
    ) -> Path:
        cycle = revisit_contract.load_cycle(workspace, cycle_id)
        report = workspace / "reports" / report_name
        report.write_bytes(complete_revisit_report_bytes(cycle))
        registered = run_revisit_cycle_cli(
            workspace,
            "register-report",
            cycle_id,
            "--report",
            report.relative_to(workspace).as_posix(),
        )
        if registered.returncode != 0:
            raise AssertionError(registered.stderr)
        return report

    @classmethod
    def _action_workspace_with_candidate(
        cls,
        root: Path,
        report_name: str = "TEST_SOFA_Report_REV-0002.md",
        extra_bridges: tuple[tuple[str, str], ...] = (),
        extra_tickers: tuple[str, ...] = (),
    ):
        workspace, cycle_id = make_task8_pre_report_workspace(
            root,
            "action_class_change",
        )
        if extra_tickers:
            framing_path = workspace / "framing_contract.json"
            framing = json.loads(framing_path.read_text(encoding="utf-8"))
            framing["subject_resolution"]["tickers"].extend(extra_tickers)
            framing_path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["intake"]["framing"]["sha256"] = hashlib.sha256(
                framing_path.read_bytes()
            ).hexdigest()
            cycle["intake"]["framing"]["snapshot"]["subject_resolution"] = (
                copy.deepcopy(framing["subject_resolution"])
            )
            cycle["intake_sha256"] = revisit_contract.intake_sha256(
                cycle["intake"]
            )
            cycle["audit"][-1]["post_state_sha256"] = (
                revisit_contract.cycle_state_sha256(cycle)
            )
            revisit_contract.cycle_json_path(workspace, cycle_id).write_bytes(
                revisit_contract.canonical_document_bytes(cycle)
            )
            (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            ).write_text(
                revisit_contract.render_cycle_markdown(cycle),
                encoding="utf-8",
            )
        record_task8_rerun(
            workspace,
            cycle_id,
            kind="bridge",
            path="financials/RC-0001_TEST_bridge.md",
            scope="full",
            dispatch_role="financial_bridge",
        )
        for round_number in (1, 2):
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="redteam-attack",
                path=f"redteam/RC-0001_round{round_number}_redteam.md",
                round_number=round_number,
                dispatch_role="red_team",
            )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="redteam-defense",
                path=f"redteam/RC-0001_round{round_number}_defense.md",
                round_number=round_number,
            )
        record_task8_rerun(
            workspace,
            cycle_id,
            kind="thesis-revision",
            path="redteam/RC-0001_thesis_revision.md",
        )
        for index, (path, scope) in enumerate(extra_bridges, start=1):
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="bridge",
                path=path,
                scope=scope,
            )
            dispatch_path = workspace / "dispatch_log.jsonl"
            dispatch_record = {
                "dispatch_id": f"dispatch_extra_bridge_{index}",
                "loop_id": "loop_10",
                "role": "financial_bridge",
                "mechanism": "host_subagent",
                "delivery_path": path,
                "status": "delivered",
            }
            with dispatch_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dispatch_record) + "\n")
        checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
        if checked.returncode != 0:
            raise AssertionError(checked.stderr)
        report = cls._register_candidate(
            workspace,
            cycle_id,
            report_name,
        )
        return workspace, cycle_id, report

    def test_final_requires_exact_registered_candidate_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            missing = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertIn(
                "REVISIT_REPORT_CANDIDATE_MISSING",
                {issue.code for issue in missing.failures},
            )

            report = self._register_candidate(workspace, cycle_id)
            write_complete = workspace / "reports" / "old-complete-mask.md"
            write_complete.write_bytes(complete_ticker_report_bytes())
            before = snapshot_tree(workspace)
            final = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertTrue(final.passed, [item.display() for item in final.failures])
            self.assertEqual(before, snapshot_tree(workspace))

            report.write_bytes(report.read_bytes() + b"candidate drift")
            drifted = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertIn(
                "REVISIT_REPORT_HASH_DRIFT",
                {issue.code for issue in drifted.failures},
            )

    def test_final_rejects_wrong_candidate_identity_and_reserved_path(self):
        mutations = (
            (
                "identity",
                lambda candidate: candidate.update({"revision_id": "REV-0003"}),
            ),
            (
                "path",
                lambda candidate: candidate.update(
                    {"report_path": "reports/wrong-revision.md"}
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                workspace, cycle_id = self._ready_workspace(Path(directory))
                self._register_candidate(workspace, cycle_id)
                cycle = revisit_contract.load_cycle(workspace, cycle_id)
                mutate(cycle["report_candidate"])
                attach_valid_audit(cycle)
                cycle_path = (
                    workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / f"{cycle_id}.json"
                )
                cycle_path.write_bytes(
                    revisit_contract.canonical_document_bytes(cycle)
                )

                result = evaluate_task8_report_candidate(workspace, cycle_id)

                self.assertIn(
                    "REVISIT_REPORT_CANDIDATE_MISSING",
                    {issue.code for issue in result.failures},
                )

    def test_final_rejects_exact_hash_with_wrong_derived_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            report = self._register_candidate(workspace, cycle_id)
            payload = report.read_bytes().replace(
                b"| Change class | evidence_or_claim_only |",
                b"| Change class | action_class_change |",
                1,
            )
            report.write_bytes(payload)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["report_candidate"]["report_sha256"] = hashlib.sha256(
                payload
            ).hexdigest()
            attach_valid_audit(cycle)
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            cycle_path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
            (workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md").write_text(
                revisit_contract.render_cycle_markdown(cycle),
                encoding="utf-8",
            )

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertIn(
                "REVISIT_REPORT_METADATA_MISMATCH",
                {issue.code for issue in result.failures},
            )

    def test_final_rejects_base_report_drift_after_candidate_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            self._register_candidate(workspace, cycle_id)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            base_report = workspace / cycle["intake"]["base_revision"]["report_path"]
            base_report.write_bytes(base_report.read_bytes() + b"base drift")

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertIn(
                "REVISIT_BASE_REPORT_DRIFT",
                {issue.code for issue in result.failures},
            )

    def test_check_final_uses_same_verdict_and_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            self._register_candidate(workspace, cycle_id)
            before = snapshot_tree(workspace)
            result = run_revisit_cycle_cli(workspace, "check", cycle_id, "--final")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("REVISIT FINAL CHECK PASSED", result.stdout)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_final_rechecks_candidate_generation_after_single_payload_owner_read(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            report = self._register_candidate(workspace, cycle_id)
            real_owner = sofa_evaluate._evaluate_specific_ticker_report_document

            def drift_after_owner_read(report_path, payload, **kwargs):
                result = real_owner(report_path, payload, **kwargs)
                if report_path == report.relative_to(workspace).as_posix():
                    report.write_bytes(payload + b"post-owner drift")
                return result

            with mock.patch.object(
                sofa_evaluate,
                "_evaluate_specific_ticker_report_document",
                side_effect=drift_after_owner_read,
            ):
                result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertIn(
                "REVISIT_REPORT_HASH_DRIFT",
                {issue.code for issue in result.failures},
            )

    def test_final_rechecks_readiness_closure_after_candidate_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            self._register_candidate(workspace, cycle_id)
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_bytes = cycle_path.read_bytes()
            pointer_bytes = pointer_path.read_bytes()
            registry = workspace / "frontier_registry.json"
            real_final_owner = sofa_evaluate._evaluate_revisit_report_impl

            def drift_after_final_owner(*args, **kwargs):
                result = real_final_owner(*args, **kwargs)
                registry.write_bytes(registry.read_bytes() + b"\n")
                return result

            with mock.patch.object(
                sofa_evaluate,
                "_evaluate_revisit_report_impl",
                side_effect=drift_after_final_owner,
            ):
                result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertIn(
                "REVISIT_AUTHORITY_DRIFT",
                {issue.code for issue in result.failures},
            )
            self.assertEqual(cycle_bytes, cycle_path.read_bytes())
            self.assertEqual(pointer_bytes, pointer_path.read_bytes())

    def test_final_keeps_candidate_and_rerun_post_owner_drift_codes_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = self._action_workspace_with_candidate(
                Path(directory)
            )
            defense = workspace / "redteam" / "RC-0001_round1_defense.md"
            real_owner = sofa_evaluate._evaluate_specific_ticker_report_document

            def drift_rerun_after_candidate_owner(report_path, payload, **kwargs):
                result = real_owner(report_path, payload, **kwargs)
                if report_path == report.relative_to(workspace).as_posix():
                    defense.write_bytes(defense.read_bytes() + b"post-owner drift")
                return result

            with mock.patch.object(
                sofa_evaluate,
                "_evaluate_specific_ticker_report_document",
                side_effect=drift_rerun_after_candidate_owner,
            ):
                result = evaluate_task8_report_candidate(workspace, cycle_id)

            codes = {issue.code for issue in result.failures}
            self.assertIn("REVISIT_RERUN_ARTIFACT_MISSING", codes)
            self.assertNotIn("REVISIT_REPORT_HASH_DRIFT", codes)

    def test_financial_row_requires_exact_bridge_artifact_and_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task8_pre_report_workspace(
                root,
                "financial_or_risk_change",
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self._register_candidate(workspace, cycle_id)

            missing = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertIn(
                "REVISIT_RERUN_ARTIFACT_MISSING",
                {issue.code for issue in missing.failures},
            )

    def test_bridge_path_must_match_one_frozen_resolved_ticker(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task8_pre_report_workspace(
                Path(directory),
                "financial_or_risk_change",
            )
            wrong_path = "financials/RC-0001_WRONG_bridge.md"
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="bridge",
                path=wrong_path,
                scope="affected",
                dispatch_role="financial_bridge",
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self._register_candidate(workspace, cycle_id)

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            issues = [
                issue
                for issue in result.failures
                if issue.code == "REVISIT_RERUN_ARTIFACT_MISSING"
            ]
            self.assertTrue(
                any(issue.path == wrong_path for issue in issues),
                [issue.display() for issue in result.failures],
            )

    def test_bridge_path_accepts_any_frozen_resolved_ticker_member(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task8_pre_report_workspace(
                Path(directory),
                "financial_or_risk_change",
            )
            framing_path = workspace / "framing_contract.json"
            framing = json.loads(framing_path.read_text(encoding="utf-8"))
            framing["subject_resolution"]["tickers"] = ["ALT", "TEST"]
            framing_path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["intake"]["framing"]["sha256"] = hashlib.sha256(
                framing_path.read_bytes()
            ).hexdigest()
            cycle["intake"]["framing"]["snapshot"]["subject_resolution"] = (
                copy.deepcopy(framing["subject_resolution"])
            )
            cycle["intake_sha256"] = revisit_contract.intake_sha256(
                cycle["intake"]
            )
            cycle["audit"][-1]["post_state_sha256"] = (
                revisit_contract.cycle_state_sha256(cycle)
            )
            cycle_path = revisit_contract.cycle_json_path(workspace, cycle_id)
            cycle_path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
            (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            ).write_text(
                revisit_contract.render_cycle_markdown(cycle),
                encoding="utf-8",
            )
            valid_path = "financials/RC-0001_TEST_bridge.md"
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="bridge",
                path=valid_path,
                scope="affected",
                dispatch_role="financial_bridge",
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self._register_candidate(workspace, cycle_id)

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertTrue(
                result.passed,
                [issue.display() for issue in result.failures],
            )

    def test_action_row_requires_each_exact_redteam_artifact_member(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task8_pre_report_workspace(
                Path(directory),
                "action_class_change",
            )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="bridge",
                path="financials/RC-0001_TEST_bridge.md",
                scope="full",
                dispatch_role="financial_bridge",
            )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="redteam-attack",
                path="redteam/RC-0001_round1_redteam.md",
                round_number=1,
                dispatch_role="red_team",
            )
            for round_number in (1, 2):
                record_task8_rerun(
                    workspace,
                    cycle_id,
                    kind="redteam-defense",
                    path=f"redteam/RC-0001_round{round_number}_defense.md",
                    round_number=round_number,
                )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="thesis-revision",
                path="redteam/RC-0001_thesis_revision.md",
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self._register_candidate(workspace, cycle_id)

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            issues = [
                issue
                for issue in result.failures
                if issue.code == "REVISIT_RERUN_ARTIFACT_MISSING"
            ]
            self.assertTrue(
                any("redteam-round-2" in (issue.evidence or "") for issue in issues),
                [issue.display() for issue in result.failures],
            )

    def test_bridge_and_attack_dispatch_role_path_mismatches_are_distinct(self):
        mismatches = (
            "financials/RC-0001_TEST_bridge.md",
            "redteam/RC-0001_round1_redteam.md",
        )
        for delivery_path in mismatches:
            with (
                self.subTest(delivery_path=delivery_path),
                tempfile.TemporaryDirectory() as directory,
            ):
                workspace, cycle_id, _ = self._action_workspace_with_candidate(
                    Path(directory)
                )
                dispatch_path = workspace / "dispatch_log.jsonl"
                records = [
                    json.loads(line)
                    for line in dispatch_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                for record in records:
                    if record.get("delivery_path") == delivery_path:
                        record["role"] = "evidence_scout"
                dispatch_path.write_text(
                    "".join(json.dumps(record) + "\n" for record in records),
                    encoding="utf-8",
                )

                result = evaluate_task8_report_candidate(workspace, cycle_id)

                issues = [
                    issue
                    for issue in result.failures
                    if issue.code == "REVISIT_RERUN_DISPATCH_MISSING"
                ]
                self.assertTrue(
                    any(delivery_path in (issue.evidence or "") for issue in issues),
                    [issue.display() for issue in result.failures],
                )

    def test_action_change_exact_matrix_passes_and_artifact_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task8_pre_report_workspace(
                root,
                "action_class_change",
            )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="bridge",
                path="financials/RC-0001_TEST_bridge.md",
                scope="full",
                dispatch_role="financial_bridge",
            )
            for round_number in (1, 2):
                record_task8_rerun(
                    workspace,
                    cycle_id,
                    kind="redteam-attack",
                    path=f"redteam/RC-0001_round{round_number}_redteam.md",
                    round_number=round_number,
                    dispatch_role="red_team",
                )
                record_task8_rerun(
                    workspace,
                    cycle_id,
                    kind="redteam-defense",
                    path=f"redteam/RC-0001_round{round_number}_defense.md",
                    round_number=round_number,
                )
            record_task8_rerun(
                workspace,
                cycle_id,
                kind="thesis-revision",
                path="redteam/RC-0001_thesis_revision.md",
            )
            checked = run_revisit_cycle_cli(workspace, "check", cycle_id)
            self.assertEqual(0, checked.returncode, checked.stderr)
            self._register_candidate(workspace, cycle_id)

            accepted = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertTrue(
                accepted.passed,
                [item.display() for item in accepted.failures],
            )

            defense = workspace / "redteam" / "RC-0001_round1_defense.md"
            defense.write_bytes(defense.read_bytes() + b"drift")
            drifted = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertIn(
                "REVISIT_RERUN_ARTIFACT_MISSING",
                {issue.code for issue in drifted.failures},
            )

    def test_final_validates_every_recorded_rerun_not_only_required_matches(self):
        extras = (
            (
                "non-required",
                "financials/RC-0001_EXTRA_bridge.md",
                "affected",
                "EXTRA",
            ),
            (
                "duplicate-semantic-slot",
                "financials/RC-0001_SECOND_bridge.md",
                "full",
                "SECOND",
            ),
        )
        for label, relative, scope, ticker in extras:
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as directory,
            ):
                workspace, cycle_id, _ = self._action_workspace_with_candidate(
                    Path(directory),
                    extra_bridges=((relative, scope),),
                    extra_tickers=(ticker,),
                )
                accepted = evaluate_task8_report_candidate(workspace, cycle_id)
                self.assertTrue(
                    accepted.passed,
                    [issue.display() for issue in accepted.failures],
                )

                artifact = workspace / relative
                artifact.write_bytes(artifact.read_bytes() + b"registered drift")
                drifted = evaluate_task8_report_candidate(workspace, cycle_id)

                self.assertTrue(
                    any(
                        issue.code == "REVISIT_RERUN_ARTIFACT_MISSING"
                        and issue.path == relative
                        for issue in drifted.failures
                    ),
                    [issue.display() for issue in drifted.failures],
                )

    def test_final_rejects_missing_non_required_recorded_rerun_at_exact_path(self):
        with tempfile.TemporaryDirectory() as directory:
            relative = "financials/RC-0001_EXTRA_bridge.md"
            workspace, cycle_id, _ = self._action_workspace_with_candidate(
                Path(directory),
                extra_bridges=((relative, "affected"),),
                extra_tickers=("EXTRA",),
            )
            (workspace / relative).unlink()

            result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertTrue(
                any(
                    issue.code == "REVISIT_RERUN_ARTIFACT_MISSING"
                    and issue.path == relative
                    for issue in result.failures
                ),
                [issue.display() for issue in result.failures],
            )

    def test_final_rechecks_non_required_rerun_generation_after_candidate_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            relative = "financials/RC-0001_EXTRA_bridge.md"
            workspace, cycle_id, report = self._action_workspace_with_candidate(
                Path(directory),
                extra_bridges=((relative, "affected"),),
                extra_tickers=("EXTRA",),
            )
            artifact = workspace / relative
            real_owner = sofa_evaluate._evaluate_specific_ticker_report_document

            def drift_extra_after_candidate_owner(report_path, payload, **kwargs):
                result = real_owner(report_path, payload, **kwargs)
                if report_path == report.relative_to(workspace).as_posix():
                    artifact.write_bytes(artifact.read_bytes() + b"post-owner drift")
                return result

            with mock.patch.object(
                sofa_evaluate,
                "_evaluate_specific_ticker_report_document",
                side_effect=drift_extra_after_candidate_owner,
            ):
                result = evaluate_task8_report_candidate(workspace, cycle_id)

            self.assertTrue(
                any(
                    issue.code == "REVISIT_RERUN_ARTIFACT_MISSING"
                    and issue.path == relative
                    for issue in result.failures
                ),
                [issue.display() for issue in result.failures],
            )

    def test_blocked_claim_id_must_appear_in_owned_gap_section(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = self._ready_workspace(Path(directory))
            report = self._register_candidate(workspace, cycle_id)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["claim_resolutions"][0] = make_blocked_resolution(
                f"{cycle_id}-CL-01", "F1"
            )
            cycle["decision_assessment"].update(
                {
                    "supporting_claim_ids": [],
                    "blocked_claim_ids": [f"{cycle_id}-CL-01"],
                    "verdict_rationale": (
                        "The unresolved proof is disclosed without positive support."
                    ),
                }
            )
            attach_valid_audit(cycle)
            report.write_bytes(complete_revisit_report_bytes(cycle))
            cycle["report_candidate"]["report_sha256"] = hashlib.sha256(
                report.read_bytes()
            ).hexdigest()
            attach_valid_audit(cycle)
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            cycle_path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
            (workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md").write_text(
                revisit_contract.render_cycle_markdown(cycle),
                encoding="utf-8",
            )

            result = evaluate_task8_report_candidate(workspace, cycle_id)
            self.assertIn(
                "REVISIT_REPORT_BLOCKED_DISCLOSURE_MISSING",
                {issue.code for issue in result.failures},
            )


class TestTask8Publication(unittest.TestCase):
    @staticmethod
    def _registered_model_cycle():
        cycle = TestTask8ReportMetadata._ready_model_cycle()
        candidate = {
            "revision_id": "REV-0002",
            "revision_of": "REV-0001",
            "report_path": "reports/TEST_SOFA_Report_REV-0002.md",
            "report_sha256": "f" * 64,
            "registered_at": "2026-07-15T00:32:00Z",
        }
        proposed = revisit_contract.register_report_candidate(cycle, candidate)
        return revisit_model.with_audit(
            cycle,
            proposed,
            "register-report",
            ["REV-0002"],
            "2026-07-15T00:32:00Z",
        )

    @staticmethod
    def _registered_workspace(root: Path):
        workspace, cycle_id = TestTask8FinalEvaluation._ready_workspace(root)
        report = TestTask8FinalEvaluation._register_candidate(
            workspace,
            cycle_id,
        )
        return workspace, cycle_id, report

    def test_complete_cycle_is_ready_candidate_only_and_copy_on_write(self):
        cycle = self._registered_model_cycle()
        original = copy.deepcopy(cycle)

        proposed = revisit_contract.complete_cycle(
            cycle,
            "2026-07-15T00:33:00Z",
        )
        completed = revisit_model.with_audit(
            cycle,
            proposed,
            "publish",
            ["RC-0001", "REV-0002"],
            "2026-07-15T00:33:00Z",
        )

        self.assertEqual(original, cycle)
        self.assertEqual("completed", completed["status"])
        self.assertEqual("2026-07-15T00:33:00Z", completed["completed_at"])
        self.assertEqual("publish", completed["audit"][-1]["command"])
        self.assertIs(completed, revisit_contract.validate_cycle(completed))

        active = TestTask8RerunArtifacts._active_assessed_cycle()
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "ready_for_report",
        ):
            revisit_contract.complete_cycle(active, "2026-07-15T00:33:00Z")

        ready_without_candidate = TestTask8ReportMetadata._ready_model_cycle()
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "report candidate",
        ):
            revisit_contract.complete_cycle(
                ready_without_candidate,
                "2026-07-15T00:33:00Z",
            )

    def test_publication_preconditions_keep_the_exact_stable_code(self):
        cycle = self._registered_model_cycle()
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = {
            **cycle["intake"]["base_revision"],
            "cycle_id": None,
            "validated_at": "2026-07-15T00:00:00Z",
            "revision_of": None,
        }
        history = revisit_contract.evaluate_history(pointer, [cycle])

        cases = []
        missing_candidate = copy.deepcopy(cycle)
        missing_candidate["report_candidate"] = None
        cases.append((missing_candidate, pointer, history, "report candidate is missing"))

        conflicting_ready_pointer = copy.deepcopy(pointer)
        conflicting_ready_pointer["current_revision"]["report_sha256"] = "0" * 64
        cases.append(
            (
                cycle,
                conflicting_ready_pointer,
                history,
                "current revision differs from cycle base",
            )
        )

        active = copy.deepcopy(cycle)
        active["status"] = "active"
        cases.append((active, pointer, history, "publish requires a ready or completed cycle"))

        proposed = revisit_contract.complete_cycle(
            cycle,
            "2026-07-15T00:33:00Z",
        )
        completed = revisit_model.with_audit(
            cycle,
            proposed,
            "publish",
            ["RC-0001", "REV-0002"],
            "2026-07-15T00:33:00Z",
        )
        completed_history = revisit_contract.evaluate_history(pointer, [completed])
        cases.append(
            (
                completed,
                conflicting_ready_pointer,
                completed_history,
                "current revision conflicts with completed candidate",
            )
        )
        cases.append(
            (
                completed,
                pointer,
                dataclasses.replace(
                    completed_history,
                    completed_unpublished_cycle_ids=(),
                ),
                "completed cycle is not the sole unpublished candidate",
            )
        )

        for tested_cycle, tested_pointer, tested_history, detail in cases:
            with self.subTest(detail=detail), self.assertRaisesRegex(
                revisit_cycle_cli.RevisitContractError,
                rf"^REVISIT_PUBLICATION_FAILED: {re.escape(detail)}$",
            ):
                revisit_cycle_cli._publication_state(
                    tested_pointer,
                    tested_cycle,
                    tested_history,
                )

    def test_validate_cycle_rejects_completed_without_report_candidate(self):
        previous = self._registered_model_cycle()
        proposed = revisit_contract.complete_cycle(
            previous,
            "2026-07-15T00:33:00Z",
        )
        completed = revisit_model.with_audit(
            previous,
            proposed,
            "publish",
            ["RC-0001", "REV-0002"],
            "2026-07-15T00:33:00Z",
        )
        completed["report_candidate"] = None
        completed["audit"][-1]["post_state_sha256"] = (
            revisit_contract.cycle_state_sha256(completed)
        )

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "completed cycle requires report_candidate",
        ):
            revisit_contract.validate_cycle(completed)

    def test_validate_cycle_rejects_completed_without_last_publish_audit(self):
        previous = self._registered_model_cycle()
        proposed = revisit_contract.complete_cycle(
            previous,
            "2026-07-15T00:33:00Z",
        )
        completed = revisit_model.with_audit(
            previous,
            proposed,
            "publish",
            ["RC-0001", "REV-0002"],
            "2026-07-15T00:33:00Z",
        )
        completed["audit"][-1]["command"] = "check"

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "completed cycle requires last audit command publish",
        ):
            revisit_contract.validate_cycle(completed)

    def test_validate_cycle_rejects_aborted_without_last_abort_audit(self):
        previous = self._registered_model_cycle()
        proposed = copy.deepcopy(previous)
        proposed["status"] = "aborted"
        proposed["aborted_at"] = "2026-07-15T00:33:00Z"
        proposed["abort_reason"] = "The main thread stopped this cycle."
        aborted = revisit_model.with_audit(
            previous,
            proposed,
            "abort",
            ["RC-0001"],
            "2026-07-15T00:33:00Z",
        )
        aborted["audit"][-1]["command"] = "check"

        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError,
            "aborted cycle requires last audit command abort",
        ):
            revisit_contract.validate_cycle(aborted)

    def test_validate_cycle_accepts_terminal_command_closure_controls(self):
        registered = self._registered_model_cycle()
        proposed = revisit_contract.complete_cycle(
            registered,
            "2026-07-15T00:33:00Z",
        )
        completed = revisit_model.with_audit(
            registered,
            proposed,
            "publish",
            ["RC-0001", "REV-0002"],
            "2026-07-15T00:33:00Z",
        )
        self.assertIs(completed, revisit_contract.validate_cycle(completed))

        for label, previous in (
            ("candidate retained", registered),
            ("candidate omitted", TestTask8ReportMetadata._ready_model_cycle()),
        ):
            with self.subTest(label=label):
                proposed = copy.deepcopy(previous)
                proposed["status"] = "aborted"
                proposed["aborted_at"] = "2026-07-15T00:34:00Z"
                proposed["abort_reason"] = "The main thread stopped this cycle."
                aborted = revisit_model.with_audit(
                    previous,
                    proposed,
                    "abort",
                    ["RC-0001"],
                    "2026-07-15T00:34:00Z",
                )
                self.assertIs(aborted, revisit_contract.validate_cycle(aborted))

    def test_publish_cli_grammar_is_exact(self):
        args = revisit_cycle_cli.build_parser().parse_args(
            ["workspace", "publish", "RC-0001"]
        )
        self.assertEqual("RC-0001", args.cycle)
        self.assertIs(revisit_cycle_cli.command_publish, args.handler)

    def test_publish_replaces_completed_mirror_then_json_then_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = self._registered_workspace(
                Path(directory)
            )
            before_cycle = revisit_contract.load_cycle(workspace, cycle_id)
            report_bytes = report.read_bytes()
            resolved_workspace = workspace.resolve()
            cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
            real_atomic_replace = cli_store._atomic_replace
            destinations = []

            def record_replace(path, payload):
                destinations.append(
                    Path(path).relative_to(resolved_workspace).as_posix()
                )
                return real_atomic_replace(path, payload)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-15T01:00:00Z",
                ),
                mock.patch.object(
                    cli_store,
                    "_atomic_replace",
                    side_effect=record_replace,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(0, result, stderr.getvalue())
            self.assertEqual(
                [
                    f"revisit_cycles/{cycle_id}.md",
                    f"revisit_cycles/{cycle_id}.json",
                    revisit_contract.POINTER_FILENAME,
                ],
                destinations,
            )
            completed = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("completed", completed["status"])
            self.assertEqual("2026-07-15T01:00:00Z", completed["completed_at"])
            self.assertEqual(len(before_cycle["audit"]) + 1, len(completed["audit"]))
            self.assertEqual("publish", completed["audit"][-1]["command"])
            current = revisit_contract.load_pointer(workspace)["current_revision"]
            candidate = completed["report_candidate"]
            self.assertEqual(
                {
                    "revision_id": candidate["revision_id"],
                    "cycle_id": cycle_id,
                    "report_path": candidate["report_path"],
                    "report_sha256": candidate["report_sha256"],
                    "action_class": completed["decision_assessment"][
                        "new_action_class"
                    ],
                    "validated_at": "2026-07-15T01:00:00Z",
                    "revision_of": candidate["revision_of"],
                },
                current,
            )
            self.assertEqual(report_bytes, report.read_bytes())

    def test_pointer_failure_leaves_completed_unpublished_and_retry_is_pointer_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id, _ = self._registered_workspace(root)
            resolved_workspace = workspace.resolve()
            pointer_path = revisit_contract.pointer_path(workspace)
            cycle_path = revisit_contract.cycle_json_path(workspace, cycle_id)
            mirror_path = revisit_contract.cycle_markdown_path(workspace, cycle_id)
            pointer_before = pointer_path.read_bytes()
            before_cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cli_store = sys.modules[revisit_cycle_cli.persist_cycle.__module__]
            real_atomic_replace = cli_store._atomic_replace

            def fail_pointer(path, payload):
                if Path(path) == pointer_path:
                    raise OSError("simulated pointer replace failure")
                return real_atomic_replace(path, payload)

            first_stdout = io.StringIO()
            first_stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-15T01:00:00Z",
                ),
                mock.patch.object(
                    cli_store,
                    "_atomic_replace",
                    side_effect=fail_pointer,
                ),
                mock.patch.object(
                    revisit_cycle_cli.sys,
                    "stdout",
                    first_stdout,
                ),
                mock.patch.object(
                    revisit_cycle_cli.sys,
                    "stderr",
                    first_stderr,
                ),
            ):
                failed = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(2, failed)
            self.assertIn(
                "REVISIT_PUBLICATION_FAILED: simulated pointer replace failure",
                first_stderr.getvalue(),
            )
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            completed = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("completed", completed["status"])
            self.assertEqual(len(before_cycle["audit"]) + 1, len(completed["audit"]))
            self.assertEqual("publish", completed["audit"][-1]["command"])
            completed_json = cycle_path.read_bytes()
            completed_mirror = mirror_path.read_bytes()

            status = run_revisit_cycle_cli(
                workspace,
                "status",
                cycle_id,
                "--json",
            )
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertEqual(
                "completed-unpublished",
                json.loads(status.stdout)["cycles"][0]["status"],
            )
            blocked_start = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(root / "revisit-request.json"),
            )
            self.assertEqual(2, blocked_start.returncode)
            self.assertIn(
                (
                    "REVISIT_CYCLE_CONFLICT: cycle conflict: RC-0001 "
                    "is completed-unpublished"
                ),
                blocked_start.stderr,
            )
            self.assertFalse(
                (
                    workspace
                    / revisit_contract.CYCLES_DIRNAME
                    / "RC-0002.json"
                ).exists()
            )
            before_blocked_start = snapshot_tree(root)
            repeated_blocked_start = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(root / "revisit-request.json"),
            )
            self.assertEqual(2, repeated_blocked_start.returncode)
            self.assertIn(
                (
                    "REVISIT_CYCLE_CONFLICT: cycle conflict: RC-0001 "
                    "is completed-unpublished"
                ),
                repeated_blocked_start.stderr,
            )
            self.assertEqual(before_blocked_start, snapshot_tree(root))

            retry_destinations = []

            def record_retry(path, payload):
                retry_destinations.append(
                    Path(path).relative_to(resolved_workspace).as_posix()
                )
                return real_atomic_replace(path, payload)

            retry_stdout = io.StringIO()
            retry_stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-15T01:05:00Z",
                ),
                mock.patch.object(
                    cli_store,
                    "_atomic_replace",
                    side_effect=record_retry,
                ),
                mock.patch.object(
                    revisit_cycle_cli.sys,
                    "stdout",
                    retry_stdout,
                ),
                mock.patch.object(
                    revisit_cycle_cli.sys,
                    "stderr",
                    retry_stderr,
                ),
            ):
                retried = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(0, retried, retry_stderr.getvalue())
            self.assertEqual(
                [revisit_contract.POINTER_FILENAME],
                retry_destinations,
            )
            self.assertEqual(completed_json, cycle_path.read_bytes())
            self.assertEqual(completed_mirror, mirror_path.read_bytes())
            self.assertEqual(completed, revisit_contract.load_cycle(workspace, cycle_id))
            current = revisit_contract.load_pointer(workspace)["current_revision"]
            self.assertEqual("REV-0002", current["revision_id"])
            self.assertEqual(cycle_id, current["cycle_id"])
            self.assertEqual("2026-07-15T01:05:00Z", current["validated_at"])

    def test_readiness_authority_drift_after_final_verdict_blocks_cycle_write(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = self._registered_workspace(Path(directory))
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            mirror_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            )
            pointer_before = pointer_path.read_bytes()
            cycle_before = cycle_path.read_bytes()
            mirror_before = mirror_path.read_bytes()
            registry = workspace / "frontier_registry.json"
            real_persist_cycle = revisit_cycle_cli.persist_cycle

            def drift_readiness_authority(*args, **kwargs):
                registry.write_bytes(registry.read_bytes() + b"\n")
                return real_persist_cycle(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value="2026-07-15T01:00:00Z",
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_cycle",
                    side_effect=drift_readiness_authority,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(2, result)
            self.assertIn("frontier_registry.json", stderr.getvalue())
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            self.assertEqual(cycle_before, cycle_path.read_bytes())
            self.assertEqual(mirror_before, mirror_path.read_bytes())

    def test_candidate_drift_blocks_completed_unpublished_pointer_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = self._registered_workspace(Path(directory))
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            mirror_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            )
            pointer_before = pointer_path.read_bytes()
            with mock.patch.object(
                revisit_cycle_cli,
                "persist_pointer",
                side_effect=OSError("simulated pointer failure"),
            ):
                failed = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )
            self.assertEqual(2, failed)
            completed_json = cycle_path.read_bytes()
            completed_mirror = mirror_path.read_bytes()
            self.assertEqual(
                "completed",
                revisit_contract.load_cycle(workspace, cycle_id)["status"],
            )

            report.write_bytes(report.read_bytes() + b"candidate drift")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                retried = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(1, retried)
            self.assertIn("REVISIT_REPORT_HASH_DRIFT", stderr.getvalue())
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            self.assertEqual(completed_json, cycle_path.read_bytes())
            self.assertEqual(completed_mirror, mirror_path.read_bytes())

    def test_base_report_drift_blocks_completed_unpublished_pointer_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = self._registered_workspace(Path(directory))
            with mock.patch.object(
                revisit_cycle_cli,
                "persist_pointer",
                side_effect=OSError("simulated pointer failure"),
            ):
                failed = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )
            self.assertEqual(2, failed)
            completed = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("completed", completed["status"])

            base_report = workspace / completed["intake"]["base_revision"][
                "report_path"
            ]
            base_report.write_bytes(base_report.read_bytes() + b"base drift")
            before = snapshot_tree(workspace)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                retried = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertNotEqual(0, retried)
            self.assertIn("REVISIT_BASE_REPORT_DRIFT", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before, snapshot_tree(workspace))

    def test_readiness_drift_after_completed_preparation_blocks_pointer_write(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = self._registered_workspace(Path(directory))
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer_before = pointer_path.read_bytes()
            registry = workspace / "frontier_registry.json"
            real_persist_pointer = revisit_cycle_cli.persist_pointer

            def drift_before_pointer(*args, **kwargs):
                registry.write_bytes(registry.read_bytes() + b"\n")
                return real_persist_pointer(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_pointer",
                    side_effect=drift_before_pointer,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(2, result)
            self.assertIn("frontier_registry.json", stderr.getvalue())
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            self.assertEqual(
                "completed",
                revisit_contract.load_cycle(workspace, cycle_id)["status"],
            )

    def test_sibling_history_drift_blocks_completed_unpublished_pointer_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = self._registered_workspace(Path(directory))
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer_before = pointer_path.read_bytes()
            with mock.patch.object(
                revisit_cycle_cli,
                "persist_pointer",
                side_effect=OSError("simulated pointer failure"),
            ):
                failed = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )
            self.assertEqual(2, failed)
            completed_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            completed_bytes = completed_path.read_bytes()

            sibling = make_history_cycle(2, 3, "aborted")
            revisit_contract.persist_cycle(
                workspace,
                sibling,
                expected_sha256=None,
            )
            sibling_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / "RC-0002.json"
            )
            real_persist_pointer = revisit_cycle_cli.persist_pointer

            def drift_sibling_before_pointer(*args, **kwargs):
                sibling_path.write_bytes(sibling_path.read_bytes() + b"\n")
                return real_persist_pointer(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_pointer",
                    side_effect=drift_sibling_before_pointer,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                retried = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(2, retried)
            self.assertIn("RC-0002.json", stderr.getvalue())
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            self.assertEqual(completed_bytes, completed_path.read_bytes())

    def test_already_current_publish_rejects_required_defense_drift_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(
                    Path(directory)
                )
            )
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)

            defense = workspace / "redteam" / "RC-0001_round1_defense.md"
            defense.write_bytes(defense.read_bytes() + b"drift")
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            mirror_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            )
            before = {
                "pointer": pointer_path.read_bytes(),
                "cycle": cycle_path.read_bytes(),
                "mirror": mirror_path.read_bytes(),
                "candidate": report.read_bytes(),
            }
            persisted = revisit_contract.load_cycle(workspace, cycle_id)
            candidate = copy.deepcopy(persisted["report_candidate"])
            audit = copy.deepcopy(persisted["audit"])

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertNotEqual(0, repeated)
            self.assertIn("REVISIT_RERUN_ARTIFACT_MISSING", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before["pointer"], pointer_path.read_bytes())
            self.assertEqual(before["cycle"], cycle_path.read_bytes())
            self.assertEqual(before["mirror"], mirror_path.read_bytes())
            self.assertEqual(before["candidate"], report.read_bytes())
            unchanged = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(candidate, unchanged["report_candidate"])
            self.assertEqual(audit, unchanged["audit"])

    def test_already_current_publish_rejects_stable_live_framing_mismatch_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(
                    Path(directory)
                )
            )
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)

            framing_path = workspace / "framing_contract.json"
            framing = json.loads(framing_path.read_text(encoding="utf-8"))
            framing["subject_resolution"]["tickers"] = ["OTHER"]
            framing_path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = snapshot_tree(workspace)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertNotEqual(0, repeated)
            self.assertIn("REVISIT_INTAKE_DRIFT", stderr.getvalue())
            self.assertNotIn("REVISIT_CYCLE_MALFORMED", stderr.getvalue())
            self.assertIn("cycle.intake.framing", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before, snapshot_tree(workspace))

    def test_already_current_publish_rejects_stable_base_report_drift_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(
                    Path(directory)
                )
            )
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)

            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            base_report = workspace / cycle["intake"]["base_revision"][
                "report_path"
            ]
            base_report.write_bytes(base_report.read_bytes() + b"base drift")
            before = snapshot_tree(workspace)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertNotEqual(0, repeated)
            self.assertIn("REVISIT_BASE_REPORT_DRIFT", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before, snapshot_tree(workspace))

    def test_already_current_publish_rejects_missing_required_rerun_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(
                    Path(directory)
                )
            )
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)

            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            mirror_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.md"
            )
            persisted = revisit_contract.load_cycle(workspace, cycle_id)
            persisted["rerun_artifacts"] = [
                artifact
                for artifact in persisted["rerun_artifacts"]
                if not (
                    artifact["kind"] == "redteam_attack"
                    and artifact["round"] == 2
                )
            ]
            persisted["audit"][-1]["post_state_sha256"] = (
                revisit_contract.cycle_state_sha256(persisted)
            )
            cycle_path.write_bytes(
                revisit_contract.canonical_document_bytes(persisted)
            )
            mirror_path.write_text(
                revisit_contract.render_cycle_markdown(persisted),
                encoding="utf-8",
            )
            before = {
                "pointer": pointer_path.read_bytes(),
                "cycle": cycle_path.read_bytes(),
                "mirror": mirror_path.read_bytes(),
                "candidate": report.read_bytes(),
            }

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertNotEqual(0, repeated)
            self.assertIn("REVISIT_RERUN_ARTIFACT_MISSING", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before["pointer"], pointer_path.read_bytes())
            self.assertEqual(before["cycle"], cycle_path.read_bytes())
            self.assertEqual(before["mirror"], mirror_path.read_bytes())
            self.assertEqual(before["candidate"], report.read_bytes())

    def test_already_current_publish_is_strict_validated_zero_write_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = self._registered_workspace(Path(directory))
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)
            published_tree = snapshot_tree(workspace)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(0, repeated, stderr.getvalue())
            self.assertIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(published_tree, snapshot_tree(workspace))

            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            pointer_bytes = pointer_path.read_bytes()
            cycle_bytes = cycle_path.read_bytes()
            report.write_bytes(report.read_bytes() + b"published candidate drift")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                drifted = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(1, drifted)
            self.assertIn("CURRENT_REPORT_HASH_DRIFT", stderr.getvalue())
            self.assertEqual(pointer_bytes, pointer_path.read_bytes())
            self.assertEqual(cycle_bytes, cycle_path.read_bytes())

    def test_already_current_publish_preserves_success_with_later_active_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id, _ = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(root)
            )
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)
            started = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(root / "revisit-request.json"),
            )
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(
                "active",
                revisit_contract.load_cycle(workspace, "RC-0002")["status"],
            )
            before = snapshot_tree(workspace)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(0, repeated, stderr.getvalue())
            self.assertIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(before, snapshot_tree(workspace))

    def test_already_current_rechecks_readiness_closure_before_success(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, _ = self._registered_workspace(Path(directory))
            first = revisit_cycle_cli.main([str(workspace), "publish", cycle_id])
            self.assertEqual(0, first)
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_path = (
                workspace / revisit_contract.CYCLES_DIRNAME / f"{cycle_id}.json"
            )
            pointer_bytes = pointer_path.read_bytes()
            cycle_bytes = cycle_path.read_bytes()
            registry = workspace / "frontier_registry.json"
            real_prepare = (
                revisit_cycle_cli._prepare_published_current_for_publication
            )

            def drift_after_preparation(*args, **kwargs):
                prepared = real_prepare(*args, **kwargs)
                registry.write_bytes(registry.read_bytes() + b"\n")
                return prepared

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_prepare_published_current_for_publication",
                    side_effect=drift_after_preparation,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                repeated = revisit_cycle_cli.main(
                    [str(workspace), "publish", cycle_id]
                )

            self.assertEqual(2, repeated)
            self.assertIn("frontier_registry.json", stderr.getvalue())
            self.assertNotIn("ALREADY PUBLISHED", stdout.getvalue())
            self.assertEqual(pointer_bytes, pointer_path.read_bytes())
            self.assertEqual(cycle_bytes, cycle_path.read_bytes())

    def test_published_cycle_metadata_remains_exactly_rerenderable_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id, report = self._registered_workspace(Path(directory))
            expected = revisit_contract.render_report_metadata(
                revisit_contract.load_cycle(workspace, cycle_id)
            )
            self.assertEqual(1, report.read_text(encoding="utf-8").count(expected))
            published = revisit_cycle_cli.main(
                [str(workspace), "publish", cycle_id]
            )
            self.assertEqual(0, published)
            before = snapshot_tree(workspace)

            rendered = run_revisit_cycle_cli(
                workspace,
                "render-report-metadata",
                cycle_id,
            )

            self.assertEqual(0, rendered.returncode, rendered.stderr)
            self.assertEqual(expected, rendered.stdout)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_next_same_day_cycle_reserves_a_distinct_revision_without_touching_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_name = "TEST_SOFA_Report_2026-07-15_REV-0002.md"
            workspace, cycle_id, report = (
                TestTask8FinalEvaluation._action_workspace_with_candidate(
                    root,
                    first_name,
                )
            )
            first_cycle = revisit_contract.load_cycle(workspace, cycle_id)
            base_report = (
                workspace / first_cycle["intake"]["base_revision"]["report_path"]
            )
            immutable_paths = [
                base_report,
                report,
                *(
                    workspace / artifact["path"]
                    for artifact in first_cycle["rerun_artifacts"]
                ),
            ]
            immutable_bytes = {
                path.relative_to(workspace).as_posix(): path.read_bytes()
                for path in immutable_paths
            }
            published = revisit_cycle_cli.main(
                [str(workspace), "publish", cycle_id]
            )
            self.assertEqual(0, published)

            started = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(root / "revisit-request.json"),
            )

            self.assertEqual(0, started.returncode, started.stderr)
            second = revisit_contract.load_cycle(workspace, "RC-0002")
            self.assertEqual("REV-0003", second["candidate_revision_id"])
            second_name = "TEST_SOFA_Report_2026-07-15_REV-0003.md"
            self.assertNotEqual(first_name, second_name)
            self.assertNotEqual(
                first_cycle["candidate_revision_id"],
                second["candidate_revision_id"],
            )
            self.assertEqual(
                immutable_bytes,
                {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in immutable_paths
                },
            )


class TestTask9QueryReplay(unittest.TestCase):
    def _assert_case(
        self,
        *,
        replay_kind: str,
        variation_fields: dict[str, object] | None,
        expected_codes: list[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task9_query_replay_workspace(
                Path(directory),
                replay_kind=replay_kind,
                variation_fields=variation_fields,
            )
            before = snapshot_tree(workspace)

            result = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)

            self.assertEqual(expected_codes, [issue.code for issue in result.failures])
            if expected_codes:
                self.assertEqual(
                    ["search_log.jsonl"],
                    [issue.path for issue in result.failures],
                )
            self.assertEqual(before, snapshot_tree(workspace))

    def test_exact_prior_query_replay_without_explanation_fails_zero_write(self):
        self._assert_case(
            replay_kind="prior_query",
            variation_fields=None,
            expected_codes=["REVISIT_QUERY_REPLAY_UNEXPLAINED"],
        )

    def test_exact_dead_end_replay_without_explanation_fails_zero_write(self):
        self._assert_case(
            replay_kind="dead_end",
            variation_fields=None,
            expected_codes=["REVISIT_QUERY_REPLAY_UNEXPLAINED"],
        )

    def test_exact_replay_with_each_allowed_dimension_and_reason_passes(self):
        for dimension in (
            "source",
            "operator",
            "language",
            "time_window",
            "evidence_hypothesis",
        ):
            with self.subTest(dimension=dimension):
                self._assert_case(
                    replay_kind="prior_query",
                    variation_fields={
                        "variation_dimension": dimension,
                        "variation_reason": (
                            "The fired trigger changes this exact search dimension."
                        ),
                    },
                    expected_codes=[],
                )

    def test_partial_invalid_and_empty_variation_metadata_fail(self):
        cases = (
            {"variation_dimension": "source"},
            {"variation_reason": "A new source is now available."},
            {
                "variation_dimension": "unsupported",
                "variation_reason": "A reason cannot legalize an invalid dimension.",
            },
            {
                "variation_dimension": "language",
                "variation_reason": "   ",
            },
            {
                "variation_dimension": 1,
                "variation_reason": "A non-string dimension is malformed.",
            },
            {
                "variation_dimension": "source",
                "variation_reason": 1,
            },
        )
        for variation_fields in cases:
            with self.subTest(variation_fields=variation_fields):
                self._assert_case(
                    replay_kind="prior_query",
                    variation_fields=variation_fields,
                    expected_codes=["REVISIT_QUERY_REPLAY_UNEXPLAINED"],
                )

    def test_novel_query_cannot_carry_replay_variation_fields(self):
        self._assert_case(
            replay_kind="novel",
            variation_fields={
                "variation_dimension": "operator",
                "variation_reason": "A different operator was used.",
            },
            expected_codes=["REVISIT_QUERY_REPLAY_UNEXPLAINED"],
        )

    def test_case_and_whitespace_variants_are_novel_without_fuzzy_matching(self):
        for query in (TASK9_PRIOR_QUERY.upper(), f"{TASK9_PRIOR_QUERY} "):
            with self.subTest(query=query):
                with tempfile.TemporaryDirectory() as directory:
                    workspace, cycle_id = make_task9_query_replay_workspace(
                        Path(directory),
                        replay_kind="novel",
                        variation_fields=None,
                        post_boundary_query=query,
                    )
                    before = snapshot_tree(workspace)

                    result = sofa_evaluate.evaluate_revisit_report(
                        workspace,
                        cycle_id,
                    )

                    self.assertTrue(
                        result.passed,
                        [issue.display() for issue in result.failures],
                    )
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_unrelated_frontier_does_not_require_search_or_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, cycle_id = make_task6_ready_workspace(Path(directory))
            unrelated_frontier_id = add_task6_frontier(
                workspace,
                initial_status="New",
            )
            before = snapshot_tree(workspace)

            result = sofa_evaluate.evaluate_revisit_report(workspace, cycle_id)

            self.assertTrue(result.passed, [issue.display() for issue in result.failures])
            self.assertNotIn(
                unrelated_frontier_id,
                (workspace / "search_log.jsonl").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                unrelated_frontier_id,
                (workspace / "dispatch_log.jsonl").read_text(encoding="utf-8"),
            )
            self.assertEqual(before, snapshot_tree(workspace))


class TestTask9ObservedReadCoverage(unittest.TestCase):
    def test_public_session_observes_cached_file_directory_and_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "authority.txt").write_bytes(b"stable authority\n")
            tree = workspace / "tree"
            tree.mkdir()
            (tree / "child.txt").write_bytes(b"child\n")
            (tree / "nested").mkdir()
            (tree / "nested" / "leaf.txt").write_bytes(b"leaf\n")

            session = revisit_generation.ObservedReadSession(workspace)
            self.assertEqual(
                b"stable authority\n",
                session.read_required("authority.txt"),
            )
            self.assertEqual(
                b"stable authority\n",
                session.read_required("authority.txt"),
            )
            self.assertIsNone(session.read_optional("missing/input.json"))
            self.assertEqual(
                (),
                session.list_directory(
                    "missing-directory",
                    recursive=False,
                    optional=True,
                ),
            )
            direct = session.list_directory("tree", recursive=False)
            self.assertEqual(
                ["tree/child.txt", "tree/nested"],
                [entry.relative_path for entry in direct],
            )
            self.assertEqual(direct, session.list_directory("tree", recursive=False))
            recursive = session.list_directory("tree", recursive=True)
            self.assertEqual(
                [
                    "tree/child.txt",
                    "tree/nested",
                    "tree/nested/leaf.txt",
                ],
                [entry.relative_path for entry in recursive],
            )

            closure = session.freeze()
            closure.require_unchanged()
            with self.assertRaisesRegex(RuntimeError, "closed after freeze"):
                session.read_optional("later.txt")
            with self.assertRaisesRegex(RuntimeError, "closed after freeze"):
                session.list_directory("tree", recursive=False)

    def test_public_session_rejects_invalid_paths_and_wrong_node_kinds(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "authority.txt").write_bytes(b"authority\n")
            (workspace / "tree").mkdir()

            for invalid in (
                "",
                ".",
                "../escape",
                str(workspace.resolve()),
                "control\npath",
            ):
                with self.subTest(path=invalid):
                    session = revisit_generation.ObservedReadSession(workspace)
                    with self.assertRaises(revisit_contract.RevisitContractError):
                        session.read_optional(invalid)

            session = revisit_generation.ObservedReadSession(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "not a readable file",
            ):
                session.read_required("tree")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "not a readable directory",
            ):
                session.list_directory("authority.txt", recursive=False)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "not a readable file",
            ):
                session.read_optional("authority.txt/child")
            closure = session.freeze()
            closure.require_unchanged()

            required = revisit_generation.ObservedReadSession(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "required authority is missing",
            ):
                required.read_required("absent.txt")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "required directory is missing",
            ):
                required.list_directory("absent-directory", recursive=False)

    def test_frozen_closure_detects_file_absence_and_directory_drift(self):
        cases = ("file-bytes", "absent-created", "member-added", "member-removed", "member-kind")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                workspace.mkdir()
                tree = workspace / "tree"
                tree.mkdir()
                child = tree / "child.txt"
                child.write_bytes(b"child\n")
                authority = workspace / "authority.txt"
                authority.write_bytes(b"before\n")
                session = revisit_generation.ObservedReadSession(workspace)

                if case == "file-bytes":
                    session.read_required("authority.txt")
                elif case == "absent-created":
                    self.assertIsNone(session.read_optional("absent.txt"))
                else:
                    session.list_directory("tree", recursive=False)
                closure = session.freeze()

                if case == "file-bytes":
                    authority.write_bytes(b"after\n")
                    expected = "file bytes changed"
                elif case == "absent-created":
                    (workspace / "absent.txt").write_bytes(b"created\n")
                    expected = "lexical state changed"
                elif case == "member-added":
                    (tree / "added.txt").write_bytes(b"added\n")
                    expected = "directory member was added"
                elif case == "member-removed":
                    child.unlink()
                    expected = "directory member was removed"
                else:
                    child.unlink()
                    child.mkdir()
                    expected = "lexical state or target changed"

                with self.assertRaisesRegex(
                    revisit_generation.AuthorityDriftError,
                    expected,
                ):
                    closure.require_unchanged()


class TestTask9InProcessCliCoverage(unittest.TestCase):
    def cli_at(
        self,
        workspace: Path,
        *arguments: str,
        timestamp: str = "2026-07-18T01:00:00Z",
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                revisit_cycle_cli,
                "_utc_now_seconds",
                return_value=timestamp,
            ),
            mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
            mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
        ):
            return_code = revisit_cycle_cli.main(
                [str(workspace), *arguments]
            )
        return return_code, stdout.getvalue(), stderr.getvalue()

    def test_status_json_and_text_cover_each_public_operational_state_read_only(self):
        cases = (
            (
                "empty",
                [],
                "register-current --report REPORT --action-class ACTION_CLASS",
            ),
            (
                "active",
                ["active"],
                "abort RC-0001 --reason TEXT",
            ),
            (
                "completed-unpublished",
                ["completed-unpublished"],
                "publish RC-0001",
            ),
        )
        for condition, statuses, next_command in cases:
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as directory:
                workspace = TestRevisitCycleStatusCli.make_status_workspace(
                    Path(directory),
                    condition,
                )
                before = snapshot_tree(workspace)
                return_code, stdout, stderr = self.cli_at(
                    workspace,
                    "status",
                    "--json",
                )
                self.assertEqual(0, return_code, stderr)
                summary = json.loads(stdout)
                self.assertEqual(
                    statuses,
                    [row["status"] for row in summary["cycles"]],
                )
                self.assertEqual(next_command, summary["next_legal_command"])

                return_code, stdout, stderr = self.cli_at(workspace, "status")
                self.assertEqual(0, return_code, stderr)
                self.assertIn(f"NEXT LEGAL COMMAND: {next_command}", stdout)
                for status in statuses:
                    self.assertIn(f"STATUS: {status}", stdout)
                self.assertEqual(before, snapshot_tree(workspace))

                if condition == "active":
                    return_code, stdout, stderr = self.cli_at(
                        workspace,
                        "status",
                        "RC-0001",
                        "--json",
                    )
                    self.assertEqual(0, return_code, stderr)
                    self.assertEqual(
                        ["RC-0001"],
                        [
                            row["cycle_id"]
                            for row in json.loads(stdout)["cycles"]
                        ],
                    )
                    return_code, _stdout, stderr = self.cli_at(
                        workspace,
                        "status",
                        "RC-9999",
                        "--json",
                    )
                    self.assertEqual(2, return_code)
                    self.assertIn("cycle authority is missing", stderr)
                    self.assertEqual(before, snapshot_tree(workspace))

        with tempfile.TemporaryDirectory() as directory:
            workspace = TestRevisitCycleStatusCli.make_status_workspace(
                Path(directory),
                "empty",
            )
            revisit_contract.persist_cycle(
                workspace,
                make_history_cycle(1, 2, "completed"),
                expected_sha256=None,
            )
            before = snapshot_tree(workspace)
            return_code, stdout, stderr = self.cli_at(
                workspace,
                "status",
                "--json",
            )
            self.assertEqual(0, return_code, stderr)
            summary = json.loads(stdout)
            self.assertTrue(summary["issues"])
            self.assertIsNone(summary["next_legal_command"])
            self.assertEqual(before, snapshot_tree(workspace))

    def test_abort_validates_reason_persists_once_and_rejects_terminal_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, request_path = make_revisit_start_workspace(root)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )
            self.assertEqual(0, return_code, stderr)

            before_invalid = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                " ",
            )
            self.assertEqual(2, return_code)
            self.assertIn("abort reason must be non-empty", stderr)
            self.assertEqual(before_invalid, snapshot_tree(workspace))

            reason = "The selected qualification proof is no longer available."
            return_code, stdout, stderr = self.cli_at(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                reason,
                timestamp="2026-07-18T01:05:00Z",
            )
            self.assertEqual(0, return_code, stderr)
            self.assertIn("REVISIT CYCLE ABORTED: RC-0001", stdout)
            aborted = revisit_contract.load_cycle(workspace, "RC-0001")
            self.assertEqual("aborted", aborted["status"])
            self.assertEqual(reason, aborted["abort_reason"])
            self.assertEqual("2026-07-18T01:05:00Z", aborted["aborted_at"])
            self.assertEqual("abort", aborted["audit"][-1]["command"])
            self.assertEqual(["RC-0001"], aborted["audit"][-1]["affected_ids"])
            self.assertEqual(
                revisit_contract.cycle_state_sha256(aborted),
                aborted["audit"][-1]["post_state_sha256"],
            )

            before_repeat = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                "A second abort must be rejected.",
            )
            self.assertEqual(2, return_code)
            self.assertIn("cannot abort cycle RC-0001 with status aborted", stderr)
            self.assertEqual(before_repeat, snapshot_tree(workspace))

    def test_emergent_derived_claim_rejects_bad_dispatch_then_persists_valid_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            invalid_request = make_emergent_claim_request()
            invalid_request["accepted_from"]["dispatch_id"] = "dispatch_missing"
            invalid_path = root / "invalid-derived-claim.json"
            invalid_path.write_text(
                json.dumps(invalid_request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before_invalid = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(invalid_path),
            )
            self.assertEqual(2, return_code)
            self.assertIn("dispatch", stderr.lower())
            self.assertEqual(before_invalid, snapshot_tree(workspace))

            valid_request = make_emergent_claim_request()
            valid_path = root / "valid-derived-claim.json"
            valid_path.write_text(
                json.dumps(valid_request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            dispatch_before = (workspace / "dispatch_log.jsonl").read_bytes()
            source_before = (workspace / "sources" / "src-002.md").read_bytes()
            return_code, stdout, stderr = self.cli_at(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(valid_path),
                timestamp="2026-07-18T01:10:00Z",
            )
            self.assertEqual(0, return_code, stderr)
            self.assertIn("DERIVED CLAIM ADDED: RC-0001-DC-01", stdout)
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                "RC-0001-DC-01",
                cycle["derived_claims"][0]["claim_id"],
            )
            self.assertEqual(
                "cycle-pending-validation",
                cycle["claim_resolutions"][1]["status"],
            )
            self.assertEqual(
                "2026-07-18T01:10:00Z",
                cycle["audit"][-1]["timestamp"],
            )
            self.assertEqual(
                "add-derived-claim",
                cycle["audit"][-1]["command"],
            )
            self.assertEqual(
                ["RC-0001-DC-01"],
                cycle["audit"][-1]["affected_ids"],
            )
            self.assertEqual(
                revisit_contract.cycle_state_sha256(cycle),
                cycle["audit"][-1]["post_state_sha256"],
            )
            self.assertEqual(
                dispatch_before,
                (workspace / "dispatch_log.jsonl").read_bytes(),
            )
            self.assertEqual(
                source_before,
                (workspace / "sources" / "src-002.md").read_bytes(),
            )


class TestTask9StoreAuthorityCoverage(unittest.TestCase):
    def test_intake_loader_rejects_missing_malformed_and_non_object_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            missing = root / "missing-request.json"
            before = snapshot_tree(root)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                r"intake request is missing: .*missing-request\.json",
            ):
                revisit_store.load_intake_request(missing)
            self.assertEqual(before, snapshot_tree(root))

            for name, payload in (
                ("invalid-utf8.json", b"\xff"),
                ("malformed.json", b"{broken"),
            ):
                with self.subTest(name=name):
                    request_path = root / name
                    request_path.write_bytes(payload)
                    before = snapshot_tree(root)
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        "intake request must be valid UTF-8 JSON",
                    ):
                        revisit_store.load_intake_request(request_path)
                    self.assertEqual(before, snapshot_tree(root))

            non_object = root / "non-object.json"
            non_object.write_text("[]\n", encoding="utf-8")
            before = snapshot_tree(root)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "request must be an object",
            ):
                revisit_store.load_intake_request(non_object)
            self.assertEqual(before, snapshot_tree(root))

    def test_public_path_artifact_and_history_rejections_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            artifact = workspace / "artifact.md"
            artifact.write_bytes(b"trusted artifact\n")

            before = snapshot_tree(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "workspace-relative path resolves to empty",
            ):
                revisit_contract.normalize_workspace_relative_path(".")
            self.assertEqual(before, snapshot_tree(workspace))

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "artifact is not a file: missing.md",
            ):
                revisit_store.verify_workspace_artifact(
                    workspace,
                    "missing.md",
                    "0" * 64,
                )
            self.assertEqual(before, snapshot_tree(workspace))

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "artifact hash mismatch: artifact.md",
            ):
                revisit_store.verify_workspace_artifact(
                    workspace,
                    "artifact.md",
                    "0" * 64,
                )
            self.assertEqual(before, snapshot_tree(workspace))
            relative, payload = revisit_store.verify_workspace_artifact(
                workspace,
                "artifact.md",
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
            )
            self.assertEqual("artifact.md", relative)
            self.assertEqual(b"trusted artifact\n", payload)
            self.assertEqual(before, snapshot_tree(workspace))

            cycles = workspace / revisit_contract.CYCLES_DIRNAME
            cycles.write_bytes(b"not a directory\n")
            before = snapshot_tree(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "cycle authority directory is not a directory",
            ):
                revisit_contract.list_cycle_ids(workspace)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_persistence_rejects_stale_and_foreign_authorities_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            foreign_workspace = root / "foreign"
            workspace.mkdir()
            foreign_workspace.mkdir()
            pointer = revisit_contract.empty_pointer()

            before = snapshot_tree(workspace)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "authority disappeared before write: revisit_contract.json",
            ):
                revisit_contract.persist_pointer(
                    workspace,
                    pointer,
                    expected_sha256="0" * 64,
                )
            self.assertEqual(before, snapshot_tree(workspace))

            foreign_session = revisit_generation.ObservedReadSession(
                foreign_workspace
            )
            self.assertIsNone(foreign_session.read_optional("absent.txt"))
            foreign_closure = foreign_session.freeze()
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "generation_closure workspace must equal the locked workspace",
            ):
                revisit_contract.persist_pointer(
                    workspace,
                    pointer,
                    expected_sha256=None,
                    generation_closure=foreign_closure,
                )
            self.assertEqual(before, snapshot_tree(workspace))
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "generation_closure workspace must equal the locked workspace",
            ):
                revisit_contract.persist_cycle(
                    workspace,
                    make_minimal_cycle(),
                    expected_sha256=None,
                    generation_closure=foreign_closure,
                )
            self.assertEqual(before, snapshot_tree(workspace))

            foreign_authority = foreign_workspace / "authority.md"
            foreign_authority.write_bytes(b"foreign authority\n")
            foreign_snapshot = revisit_store.prepare_authority_snapshot(
                foreign_workspace,
                foreign_authority,
                hashlib.sha256(foreign_authority.read_bytes()).hexdigest(),
            )
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "prepared snapshot belongs to a different workspace",
            ):
                revisit_contract.persist_pointer(
                    workspace,
                    pointer,
                    expected_sha256=None,
                    authority_snapshots=(foreign_snapshot,),
                )
            self.assertEqual(before, snapshot_tree(workspace))

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "snapshot authority escapes workspace",
            ):
                revisit_store.prepare_authority_snapshot(
                    workspace,
                    foreign_authority,
                    hashlib.sha256(foreign_authority.read_bytes()).hexdigest(),
                )
            self.assertEqual(before, snapshot_tree(workspace))


class TestTask9CliAuthorityCoverage(unittest.TestCase):
    def cli_at(
        self,
        workspace: Path,
        *arguments: str,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                revisit_cycle_cli,
                "_utc_now_seconds",
                return_value="2026-07-18T02:00:00Z",
            ),
            mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
            mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
        ):
            return_code = revisit_cycle_cli.main(
                [str(workspace), *arguments]
            )
        return return_code, stdout.getvalue(), stderr.getvalue()

    def test_request_document_errors_exit_two_and_preserve_authorities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            missing = root / "missing-derived-claim.json"
            before = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(missing),
            )
            self.assertEqual(2, return_code)
            self.assertRegex(
                stderr,
                r"derived claim request is missing: .*missing-derived-claim\.json",
            )
            self.assertEqual(before, snapshot_tree(workspace))

            for name, payload, expected in (
                (
                    "malformed-derived-claim.json",
                    b"{broken",
                    "derived claim request must be valid UTF-8 JSON",
                ),
                (
                    "non-object-derived-claim.json",
                    b"[]\n",
                    "derived claim request must contain an object",
                ),
            ):
                with self.subTest(name=name):
                    request_path = root / name
                    request_path.write_bytes(payload)
                    request_before = request_path.read_bytes()
                    before = snapshot_tree(workspace)
                    return_code, _stdout, stderr = self.cli_at(
                        workspace,
                        "add-derived-claim",
                        cycle_id,
                        "--request-file",
                        str(request_path),
                    )
                    self.assertEqual(2, return_code)
                    self.assertIn(expected, stderr)
                    self.assertEqual(before, snapshot_tree(workspace))
                    self.assertEqual(request_before, request_path.read_bytes())

    def test_start_rejects_invalid_framing_frontier_and_ledger_authorities(self):
        def mutate_framing_json(workspace: Path) -> None:
            (workspace / "framing_contract.json").write_bytes(b"{broken")

        def mutate_framing_incomplete(workspace: Path) -> None:
            path = workspace / "framing_contract.json"
            framing = json.loads(path.read_text(encoding="utf-8"))
            del framing["time_horizon"]
            path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def mutate_framing_mode(workspace: Path) -> None:
            path = workspace / "framing_contract.json"
            framing = json.loads(path.read_text(encoding="utf-8"))
            framing["mode"] = "sector"
            path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def mutate_framing_posture(workspace: Path) -> None:
            path = workspace / "framing_contract.json"
            framing = json.loads(path.read_text(encoding="utf-8"))
            framing["research_posture"] = "fresh"
            path.write_text(
                json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def mutate_frontier_mode(workspace: Path) -> None:
            path = workspace / "frontier_registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["mode"] = "sector"
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def mutate_ledger_encoding(workspace: Path) -> None:
            (workspace / "evidence_ledger.md").write_bytes(b"\xff")

        def mutate_ledger_header(workspace: Path) -> None:
            (workspace / "evidence_ledger.md").write_text(
                "# Evidence Ledger\n\n## Loop malformed\n",
                encoding="utf-8",
            )

        cases = (
            (
                "framing-json",
                mutate_framing_json,
                "framing_contract.json must be valid UTF-8 JSON",
            ),
            (
                "framing-incomplete",
                mutate_framing_incomplete,
                "framing contract is invalid",
            ),
            (
                "framing-mode",
                mutate_framing_mode,
                "framing contract is invalid: FRAMING_MODE_DRIFT",
            ),
            (
                "framing-posture",
                mutate_framing_posture,
                "framing contract research_posture must be revisit",
            ),
            (
                "frontier-mode",
                mutate_frontier_mode,
                "frontier registry mode must be ticker",
            ),
            (
                "ledger-encoding",
                mutate_ledger_encoding,
                "evidence_ledger.md must be valid UTF-8",
            ),
            (
                "ledger-header",
                mutate_ledger_header,
                "malformed loop header",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace, request_path = make_revisit_start_workspace(root)
                mutate(workspace)
                request_before = request_path.read_bytes()
                before = snapshot_tree(workspace)
                return_code, _stdout, stderr = self.cli_at(
                    workspace,
                    "start",
                    "--intake-file",
                    str(request_path),
                )
                self.assertEqual(2, return_code)
                self.assertIn(expected, stderr)
                self.assertEqual(before, snapshot_tree(workspace))
                self.assertEqual(request_before, request_path.read_bytes())

    def test_source_authority_rejections_exit_two_without_cycle_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            request = make_emergent_claim_request()
            request["accepted_from"]["evidence_refs"][0]["source_id"] = (
                "src-999"
            )
            request_path = root / "missing-source-claim.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )
            self.assertEqual(2, return_code)
            self.assertIn("source_id is not registered: src-999", stderr)
            self.assertEqual(before, snapshot_tree(workspace))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id = make_task5_mutation_workspace(root)
            request_path = root / "corrupt-cache-claim.json"
            request_path.write_text(
                json.dumps(
                    make_emergent_claim_request(),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with (workspace / "sources_index.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write("{broken\n")
            before = snapshot_tree(workspace)
            return_code, _stdout, stderr = self.cli_at(
                workspace,
                "add-derived-claim",
                cycle_id,
                "--request-file",
                str(request_path),
            )
            self.assertEqual(2, return_code)
            self.assertIn("source cache failed validation", stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_status_renders_current_report_drift_as_read_only_issue(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = TestRevisitCycleStatusCli.make_status_workspace(
                Path(directory),
                "registered",
            )
            report = workspace / "reports" / "initial.md"
            report.write_bytes(report.read_bytes() + b"drift\n")
            before = snapshot_tree(workspace)

            return_code, stdout, stderr = self.cli_at(
                workspace,
                "status",
                "--json",
            )
            self.assertEqual(0, return_code, stderr)
            summary = json.loads(stdout)
            self.assertTrue(
                any(
                    issue.startswith("current_report_invalid:")
                    for issue in summary["issues"]
                )
            )
            self.assertIsNone(summary["next_legal_command"])

            return_code, stdout, stderr = self.cli_at(workspace, "status")
            self.assertEqual(0, return_code, stderr)
            self.assertIn("ISSUE: current_report_invalid:", stdout)
            self.assertIn("NEXT LEGAL COMMAND: none", stdout)
            self.assertEqual(before, snapshot_tree(workspace))


class TestTask9CoverageClosure(unittest.TestCase):
    def cli_at(
        self,
        workspace: Path,
        *arguments: str,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                revisit_cycle_cli,
                "_utc_now_seconds",
                return_value="2026-07-18T03:00:00Z",
            ),
            mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
            mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
        ):
            return_code = revisit_cycle_cli.main(
                [str(workspace), *arguments]
            )
        return return_code, stdout.getvalue(), stderr.getvalue()

    def test_dispatch_delivery_and_provenance_rejections_are_zero_write(self):
        cases = (
            (
                "non-utf8-log",
                "dispatch_log.jsonl must be valid UTF-8 JSONL",
            ),
            (
                "malformed-json",
                "dispatch_log.jsonl line 1 must be valid JSON",
            ),
            (
                "non-object-record",
                "dispatch_log.jsonl line 1 must contain an object",
            ),
            (
                "empty-delivery-path",
                "dispatch dispatch_0010_scout delivery_path must be non-empty text",
            ),
            (
                "escaping-delivery-path",
                "dispatch dispatch_0010_scout delivery path escapes workspace",
            ),
            (
                "missing-delivery-path",
                "dispatch dispatch_0010_scout delivery path is missing or not a file",
            ),
            (
                "duplicate-record",
                "dispatch dispatch_0010_scout has multiple matching records for loop_10",
            ),
            (
                "undelivered-record",
                "dispatch dispatch_0010_scout must have status delivered",
            ),
            (
                "delivery-as-evidence",
                "worker delivery is provenance only and cannot be accepted as artifact evidence",
            ),
        )
        for case, expected in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace, cycle_id = make_task5_mutation_workspace(root)
                dispatch_path = workspace / "dispatch_log.jsonl"
                request = make_emergent_claim_request()

                if case == "non-utf8-log":
                    dispatch_path.write_bytes(b"\xff")
                elif case == "malformed-json":
                    dispatch_path.write_text("{broken\n", encoding="utf-8")
                elif case == "non-object-record":
                    dispatch_path.write_text("[]\n", encoding="utf-8")
                elif case == "duplicate-record":
                    dispatch_path.write_text(
                        dispatch_path.read_text(encoding="utf-8") * 2,
                        encoding="utf-8",
                    )
                elif case in {
                    "empty-delivery-path",
                    "escaping-delivery-path",
                    "missing-delivery-path",
                    "undelivered-record",
                }:
                    record = json.loads(
                        dispatch_path.read_text(encoding="utf-8")
                    )
                    if case == "empty-delivery-path":
                        record["delivery_path"] = ""
                    elif case == "escaping-delivery-path":
                        record["delivery_path"] = "../outside.md"
                    elif case == "missing-delivery-path":
                        record["delivery_path"] = "scouts/missing.md"
                    else:
                        record["status"] = "queued"
                    dispatch_path.write_text(
                        json.dumps(record, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                elif case == "delivery-as-evidence":
                    delivery = workspace / "scouts" / "loop_10_scout.md"
                    request["accepted_from"]["evidence_refs"] = [
                        {
                            "kind": "artifact",
                            "path": "scouts/loop_10_scout.md",
                            "sha256": hashlib.sha256(
                                delivery.read_bytes()
                            ).hexdigest(),
                            "locator": "Entire delivered worker output",
                            "checked_at": "2026-07-14T12:00:00Z",
                        }
                    ]

                request_path = root / f"{case}.json"
                request_path.write_text(
                    json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                before = snapshot_tree(root)
                return_code, _stdout, stderr = self.cli_at(
                    workspace,
                    "add-derived-claim",
                    cycle_id,
                    "--request-file",
                    str(request_path),
                )
                self.assertEqual(2, return_code)
                self.assertIn(expected, stderr)
                self.assertEqual(before, snapshot_tree(root))

    def test_closure_backed_cycle_json_failure_restores_exact_authorities(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            stable_authority = workspace / "authority.md"
            stable_authority.write_bytes(b"stable authority\n")
            original = make_minimal_cycle()
            json_path, markdown_path = revisit_contract.persist_cycle(
                workspace,
                original,
                expected_sha256=None,
            )
            session = revisit_generation.ObservedReadSession(workspace)
            self.assertEqual(
                b"stable authority\n",
                session.read_required("authority.md"),
            )
            session.list_directory(
                revisit_contract.CYCLES_DIRNAME,
                recursive=False,
            )
            session.read_required(
                f"{revisit_contract.CYCLES_DIRNAME}/RC-0001.json"
            )
            session.read_required(
                f"{revisit_contract.CYCLES_DIRNAME}/RC-0001.md"
            )
            closure = session.freeze()

            updated = make_minimal_cycle()
            updated["status"] = "ready_for_report"
            attach_valid_audit(updated)
            before = snapshot_tree(workspace)
            original_json = json_path.read_bytes()
            original_markdown = markdown_path.read_bytes()
            real_replace = os.replace

            def fail_cycle_json(source, destination):
                if Path(destination).name == "RC-0001.json":
                    raise OSError("closure cycle JSON replace failed")
                return real_replace(source, destination)

            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_cycle_json,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "closure cycle JSON replace failed",
                ):
                    revisit_contract.persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(
                            original_json
                        ).hexdigest(),
                        generation_closure=closure,
                    )

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertEqual(original_markdown, markdown_path.read_bytes())
            self.assertEqual(b"stable authority\n", stable_authority.read_bytes())
            self.assertEqual(before, snapshot_tree(workspace))

    def test_second_start_rejects_active_cycle_without_authority_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, request_path = make_revisit_start_workspace(root)
            return_code, stdout, stderr = self.cli_at(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )
            self.assertEqual(0, return_code, stderr)
            self.assertIn("REVISIT CYCLE STARTED: RC-0001", stdout)

            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            cycle_json = (
                workspace
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.json"
            )
            cycle_markdown = cycle_json.with_suffix(".md")
            authority_bytes = {
                "pointer": pointer_path.read_bytes(),
                "cycle_json": cycle_json.read_bytes(),
                "cycle_markdown": cycle_markdown.read_bytes(),
                "request": request_path.read_bytes(),
            }
            before = snapshot_tree(root)
            return_code, stdout, stderr = self.cli_at(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(2, return_code)
            self.assertNotIn("REVISIT CYCLE STARTED", stdout)
            self.assertIn(
                "REVISIT_CYCLE_CONFLICT: cycle conflict: RC-0001 is active",
                stderr,
            )
            self.assertEqual(authority_bytes["pointer"], pointer_path.read_bytes())
            self.assertEqual(authority_bytes["cycle_json"], cycle_json.read_bytes())
            self.assertEqual(
                authority_bytes["cycle_markdown"],
                cycle_markdown.read_bytes(),
            )
            self.assertEqual(authority_bytes["request"], request_path.read_bytes())
            self.assertEqual(before, snapshot_tree(root))


class TestTask9RepresentativeWorkflows(unittest.TestCase):
    def test_three_copied_fixture_rows_publish_without_reducing_research_floors(self):
        fixture_root = REPO_ROOT / "tests" / "fixtures" / "revisit_completed_ticker"
        old_report_relative = "reports/AXTI_SOFA_Report_2026-07-01.md"
        historical_reruns = (
            "financials/AXTI_bridge.md",
            "redteam/round1_redteam.md",
            "redteam/round1_defense.md",
            "redteam/thesis_revision.md",
        )

        def cli_at(workspace: Path, timestamp: str, *arguments: str):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_utc_now_seconds",
                    return_value=timestamp,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                return_code = revisit_cycle_cli.main(
                    [str(workspace), *arguments]
                )
            return return_code, stdout.getvalue(), stderr.getvalue()

        def require_cli(
            workspace: Path,
            timestamp: str,
            *arguments: str,
        ) -> str:
            return_code, stdout, stderr = cli_at(
                workspace,
                timestamp,
                *arguments,
            )
            self.assertEqual(0, return_code, stderr)
            return stdout

        def prepare_assessed_row(root: Path, change_class: str):
            workspace = root / "workspace"
            shutil.copytree(fixture_root, workspace)
            immutable_bytes = {
                relative: (workspace / relative).read_bytes()
                for relative in (old_report_relative, *historical_reruns)
            }

            require_cli(
                workspace,
                "2026-07-18T00:00:00Z",
                "register-current",
                "--report",
                old_report_relative,
                "--action-class",
                "Watch with Trigger",
            )
            framing = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(REPO_ROOT / "scripts" / "framing_intake.py"),
                    str(workspace),
                    "set",
                    "--field",
                    "research_posture",
                    "--value",
                    "revisit",
                ],
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(0, framing.returncode, framing.stderr)
            self.assertEqual("revisit", load_contract(workspace)["research_posture"])

            claim_ledger = workspace / "claim_ledger.md"
            request = {
                "triggers": [
                    {
                        "kind": "downgrade",
                        "statement": (
                            "The named AXTI customer qualification milestone moved "
                            "beyond the prior watch window."
                        ),
                        "observed_at": "2026-07-18T00:01:00Z",
                        "evidence_refs": [
                            {
                                "kind": "source",
                                "source_id": "src-001",
                                "checked_at": "2026-07-18T00:01:00Z",
                            }
                        ],
                    }
                ],
                "selected_claims": [
                    {
                        "statement": (
                            "AXTI customer qualification completes inside the "
                            "prior watch window."
                        ),
                        "source_ref": {
                            "path": "claim_ledger.md",
                            "sha256": hashlib.sha256(
                                claim_ledger.read_bytes()
                            ).hexdigest(),
                            "locator": "Claim C1 - Customer qualification",
                            "historical_claim_id": "C1",
                        },
                        "importance": "critical",
                        "selection_reasons": [
                            "trigger_affected",
                            "decision_load_bearing",
                        ],
                        "trigger_indexes": [1],
                        "inherited_grade": "B",
                        "inherited_confidence": "medium",
                        "inherited_evidence": [
                            {
                                "ref": {
                                    "kind": "source",
                                    "source_id": "src-001",
                                    "checked_at": "2026-07-01T12:00:00Z",
                                },
                                "freshness": "stale",
                                "checked_at": "2026-07-01T12:00:00Z",
                                "reason": (
                                    "The source predates the fired qualification trigger."
                                ),
                            }
                        ],
                    }
                ],
            }
            request_path = root / f"{change_class}-request.json"
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            require_cli(
                workspace,
                "2026-07-18T00:01:00Z",
                "start",
                "--intake-file",
                str(request_path),
            )
            cycle_id = "RC-0001"
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(
                9,
                cycle["intake"]["workspace_boundary"][
                    "max_existing_loop_number"
                ],
            )

            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry = transition(
                registry,
                "F1",
                "Active",
                {"F1": 3, "F2": 0},
                mode="ticker",
                action="reactivate",
                at_loop=10,
                ts="2026-07-18T00:02:00Z",
            )
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            require_cli(
                workspace,
                "2026-07-18T00:03:00Z",
                "bind-frontier",
                cycle_id,
                "--frontier",
                "F1",
                "--action",
                "reactivated",
                "--claim",
                f"{cycle_id}-CL-01",
                "--expected-evidence",
                "Current AXTI qualification evidence and counter-evidence.",
            )

            historical_dossier = b"".join(
                (workspace / relative).read_bytes()
                for relative in (
                    old_report_relative,
                    "claim_ledger.md",
                    "evidence_ledger.md",
                    "search_log.jsonl",
                    "sources_index.jsonl",
                    "sources/src-001.md",
                    "sources/src-002.md",
                )
            )
            contexts = {
                role: revisit_context.build_revisit_context(
                    workspace,
                    cycle_id,
                    "F1",
                    (f"{cycle_id}-CL-01",),
                    role,
                    "loop_10",
                )
                for role in ("frontier_scout", "challenge_probe")
            }
            for role, context in contexts.items():
                with self.subTest(change_class=change_class, role=role):
                    self.assertLess(
                        len(context.text.encode("utf-8")),
                        len(historical_dossier),
                    )
                    for required in (
                        cycle_id,
                        "loop_10",
                        "F1",
                        f"{cycle_id}-CL-01",
                    ):
                        self.assertIn(required, context.text)
                    self.assertNotIn("F2", context.text)
                    self.assertNotIn("Omitted historical claim", context.text)
            self.assertNotIn("src-002", contexts["frontier_scout"].text)
            self.assertNotIn(
                "AXTI manufacturing capacity construction schedule",
                contexts["frontier_scout"].text,
            )

            index_path = workspace / "sources_index.jsonl"
            source_bytes = {
                path.relative_to(workspace).as_posix(): path.read_bytes()
                for path in (workspace / "sources").glob("*.md")
            }
            index_bytes = index_path.read_bytes()
            duplicate = add_source(
                workspace,
                url="https://qualification.example.test/milestone",
                title="AXTI customer qualification update",
                retrieved="2026-07-18",
                grade="B",
                excerpt_text=(workspace / "sources" / "src-001.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertFalse(duplicate.created)
            self.assertEqual("src-001", duplicate.source_id)
            self.assertEqual(index_bytes, index_path.read_bytes())
            self.assertEqual(
                source_bytes,
                {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in (workspace / "sources").glob("*.md")
                },
            )
            self.assertEqual(
                "stale",
                revisit_contract.load_cycle(workspace, cycle_id)["intake"][
                    "selected_claims"
                ][0]["inherited_evidence"][0]["freshness"],
            )

            with (workspace / "evidence_ledger.md").open(
                "a", encoding="utf-8"
            ) as handle:
                for loop_number in (10, 11, 12):
                    handle.write(
                        f"\n## Loop {loop_number}: F1 - Customer qualification timing\n\n"
                        f"Cycle-relative AXTI evidence for loop {loop_number}.\n"
                    )

            search_path = workspace / "search_log.jsonl"
            with search_path.open("a", encoding="utf-8") as handle:
                for loop_number in (10, 11, 12):
                    handle.write(
                        json.dumps(
                            {
                                "loop_id": f"loop_{loop_number}",
                                "query": (
                                    f"AXTI post-trigger qualification evidence "
                                    f"loop {loop_number}"
                                ),
                                "result_status": "completed",
                                "dead_ends": [],
                                "evidence_refs": ["src-001"],
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

            dispatch_path = workspace / "dispatch_log.jsonl"
            with dispatch_path.open("a", encoding="utf-8") as dispatch_handle:
                for loop_number in (10, 11, 12):
                    for role, directory, suffix, cards in (
                        (
                            "frontier_scout",
                            "scouts",
                            "customer_qualification",
                            "supply-chain-mapping, customer-graph-discovery",
                        ),
                        (
                            "challenge_probe",
                            "challenges",
                            "challenge",
                            (
                                "red-team, supply-chain-mapping, "
                                "customer-graph-discovery"
                            ),
                        ),
                    ):
                        relative = f"{directory}/loop{loop_number}_{suffix}.md"
                        output_path = workspace / relative
                        output_path.parent.mkdir(exist_ok=True)
                        output_path.write_text(
                            f"# {role} loop {loop_number}\n\n"
                            f"Method cards loaded: {cards}.\n\n"
                            "Sources consulted: src-001.\n\n"
                            "Cycle-relative qualification evidence.\n",
                            encoding="utf-8",
                        )
                        dispatch_handle.write(
                            json.dumps(
                                {
                                    "dispatch_id": (
                                        f"dispatch_loop_{loop_number}_{role}"
                                    ),
                                    "loop_id": f"loop_{loop_number}",
                                    "role": role,
                                    "mechanism": "host_subagent",
                                    "delivery_path": relative,
                                    "status": "delivered",
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        )

            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry = transition(
                registry,
                "F1",
                "Continued",
                {"F1": 6, "F2": 0},
                mode="ticker",
                action="review",
                rationale="Three new loops completed the AXTI revisit review.",
                at_loop=12,
                ts="2026-07-18T00:12:00Z",
            )
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            resolution = make_confirmed_resolution_request()
            resolution.update(
                {
                    "current_evidence_refs": [
                        {
                            "kind": "source",
                            "source_id": "src-001",
                            "checked_at": "2026-07-18T00:13:00Z",
                        }
                    ],
                    "bound_frontier_ids": ["F1"],
                    "rationale": (
                        "Current AXTI evidence resolves the selected proposition."
                    ),
                }
            )
            resolution_path = root / f"{change_class}-resolution.json"
            resolution_path.write_text(
                json.dumps(resolution, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            require_cli(
                workspace,
                "2026-07-18T00:13:00Z",
                "resolve-claim",
                cycle_id,
                f"{cycle_id}-CL-01",
                "--resolution-file",
                str(resolution_path),
            )

            assessment = make_decision_assessment_request()
            if change_class == "financial_or_risk_change":
                assessment.update(
                    {
                        "financial_bridge_affected": True,
                        "financial_bridge_rationale": (
                            "The accepted claim changes the affected revenue bridge."
                        ),
                    }
                )
            elif change_class == "action_class_change":
                assessment.update(
                    {
                        "new_action_class": "Reject",
                        "financial_bridge_affected": True,
                        "financial_bridge_rationale": (
                            "The action-class change requires a full bridge."
                        ),
                    }
                )
            assessment_path = root / f"{change_class}-assessment.json"
            assessment_path.write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            require_cli(
                workspace,
                "2026-07-18T00:14:00Z",
                "assess-decision",
                cycle_id,
                "--assessment-file",
                str(assessment_path),
            )
            self.assertEqual(
                change_class,
                revisit_contract.load_cycle(workspace, cycle_id)[
                    "decision_assessment"
                ]["change_class"],
            )
            return workspace, cycle_id, immutable_bytes, contexts

        def record_rerun_artifact(
            workspace: Path,
            cycle_id: str,
            *,
            timestamp: str,
            kind: str,
            relative: str,
            scope: str | None = None,
            round_number: int | None = None,
            dispatch_role: str | None = None,
        ) -> None:
            artifact = workspace / relative
            artifact.parent.mkdir(exist_ok=True)
            card = "financial-bridge" if kind == "bridge" else "red-team"
            artifact.write_text(
                f"# {kind} rerun\n\nMethod cards loaded: {card}.\n\n"
                "Sources consulted: src-001.\n\n"
                f"Artifact: {relative}; scope: {scope}; round: {round_number}.\n",
                encoding="utf-8",
            )
            arguments = [
                "record-rerun",
                cycle_id,
                "--kind",
                kind,
                "--path",
                relative,
            ]
            if scope is not None:
                arguments.extend(("--scope", scope))
            if round_number is not None:
                arguments.extend(("--round", str(round_number)))
            require_cli(workspace, timestamp, *arguments)
            if dispatch_role is not None:
                with (workspace / "dispatch_log.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(
                        json.dumps(
                            {
                                "dispatch_id": (
                                    f"dispatch_{kind}_{round_number or 0}"
                                ),
                                "loop_id": "loop_12",
                                "role": dispatch_role,
                                "mechanism": "host_subagent",
                                "delivery_path": relative,
                                "status": "delivered",
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

        def register_required_reruns(
            workspace: Path,
            cycle_id: str,
            change_class: str,
        ) -> None:
            if change_class == "evidence_or_claim_only":
                return
            bridge_scope = (
                "affected"
                if change_class == "financial_or_risk_change"
                else "full"
            )
            record_rerun_artifact(
                workspace,
                cycle_id,
                timestamp="2026-07-18T00:15:00Z",
                kind="bridge",
                relative="financials/RC-0001_AXTI_bridge.md",
                scope=bridge_scope,
                dispatch_role="financial_bridge",
            )
            if change_class != "action_class_change":
                return
            minute = 16
            for round_number in (1, 2):
                record_rerun_artifact(
                    workspace,
                    cycle_id,
                    timestamp=f"2026-07-18T00:{minute:02d}:00Z",
                    kind="redteam-attack",
                    relative=(
                        f"redteam/RC-0001_round{round_number}_redteam.md"
                    ),
                    round_number=round_number,
                    dispatch_role="red_team",
                )
                minute += 1
                record_rerun_artifact(
                    workspace,
                    cycle_id,
                    timestamp=f"2026-07-18T00:{minute:02d}:00Z",
                    kind="redteam-defense",
                    relative=(
                        f"redteam/RC-0001_round{round_number}_defense.md"
                    ),
                    round_number=round_number,
                )
                minute += 1
            record_rerun_artifact(
                workspace,
                cycle_id,
                timestamp=f"2026-07-18T00:{minute:02d}:00Z",
                kind="thesis-revision",
                relative="redteam/RC-0001_thesis_revision.md",
            )

        def write_and_register_candidate(
            workspace: Path,
            cycle_id: str,
            *,
            timestamp: str,
        ) -> Path:
            metadata = require_cli(
                workspace,
                timestamp,
                "render-report-metadata",
                cycle_id,
            )
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual(revisit_contract.render_report_metadata(cycle), metadata)
            report = workspace / "reports" / "AXTI_SOFA_Report_2026-07-18_REV-0002.md"
            report.write_bytes(complete_revisit_report_bytes(cycle))
            self.assertIn(metadata.encode("utf-8"), report.read_bytes())
            require_cli(
                workspace,
                timestamp,
                "register-report",
                cycle_id,
                "--report",
                report.relative_to(workspace).as_posix(),
            )
            return report

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, cycle_id, immutable_bytes, _contexts = prepare_assessed_row(
                root,
                "action_class_change",
            )
            require_cli(
                workspace,
                "2026-07-18T00:25:00Z",
                "check",
                cycle_id,
            )
            write_and_register_candidate(
                workspace,
                cycle_id,
                timestamp="2026-07-18T00:26:00Z",
            )
            return_code, _stdout, stderr = cli_at(
                workspace,
                "2026-07-18T00:26:00Z",
                "check",
                cycle_id,
                "--final",
            )
            self.assertEqual(1, return_code)
            self.assertIn("REVISIT_RERUN_ARTIFACT_MISSING", stderr)
            self.assertEqual(
                immutable_bytes,
                {
                    relative: (workspace / relative).read_bytes()
                    for relative in immutable_bytes
                },
            )

        for change_class in (
            "evidence_or_claim_only",
            "financial_or_risk_change",
            "action_class_change",
        ):
            with self.subTest(change_class=change_class), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace, cycle_id, immutable_bytes, contexts = prepare_assessed_row(
                    root,
                    change_class,
                )

                if change_class == "evidence_or_claim_only":
                    probe = root / "unrelated-floor-probe"
                    shutil.copytree(workspace, probe)
                    search_path = probe / "search_log.jsonl"
                    records = [
                        json.loads(line)
                        for line in search_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    records = [
                        record
                        for record in records
                        if record.get("loop_id") != "loop_12"
                    ]
                    records.append(
                        {
                            "loop_id": "loop_13",
                            "query": "AXTI unrelated capacity follow-up",
                            "result_status": "completed",
                        }
                    )
                    search_path.write_text(
                        "".join(
                            json.dumps(record, separators=(",", ":")) + "\n"
                            for record in records
                        ),
                        encoding="utf-8",
                    )
                    with (probe / "evidence_ledger.md").open(
                        "a", encoding="utf-8"
                    ) as handle:
                        handle.write(
                            "\n## Loop 13: F2 - Manufacturing capacity expansion\n\n"
                            "Unrelated frontier evidence.\n"
                        )
                    before_probe = snapshot_tree(probe)
                    probe_result = sofa_evaluate.evaluate_revisit_report(
                        probe,
                        cycle_id,
                    )
                    self.assertIn(
                        "REVISIT_SEARCH_FLOOR_MISSING",
                        [issue.code for issue in probe_result.failures],
                    )
                    self.assertEqual(before_probe, snapshot_tree(probe))

                register_required_reruns(workspace, cycle_id, change_class)
                require_cli(
                    workspace,
                    "2026-07-18T00:25:00Z",
                    "check",
                    cycle_id,
                )
                report = write_and_register_candidate(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-18T00:26:00Z",
                )
                require_cli(
                    workspace,
                    "2026-07-18T00:26:00Z",
                    "check",
                    cycle_id,
                    "--final",
                )

                pointer_before = revisit_contract.load_pointer(workspace)
                self.assertEqual(
                    old_report_relative,
                    pointer_before["current_revision"]["report_path"],
                )
                publish_events: list[tuple[str, str | None]] = []
                real_persist_cycle = revisit_cycle_cli.persist_cycle
                real_persist_pointer = revisit_cycle_cli.persist_pointer

                def tracked_cycle(*args, **kwargs):
                    publish_events.append(("cycle", args[1].get("status")))
                    return real_persist_cycle(*args, **kwargs)

                def tracked_pointer(*args, **kwargs):
                    current = args[1].get("current_revision")
                    publish_events.append(
                        ("pointer", current.get("cycle_id") if current else None)
                    )
                    return real_persist_pointer(*args, **kwargs)

                with (
                    mock.patch.object(
                        revisit_cycle_cli,
                        "persist_cycle",
                        side_effect=tracked_cycle,
                    ),
                    mock.patch.object(
                        revisit_cycle_cli,
                        "persist_pointer",
                        side_effect=tracked_pointer,
                    ),
                ):
                    require_cli(
                        workspace,
                        "2026-07-18T00:27:00Z",
                        "publish",
                        cycle_id,
                    )

                self.assertEqual(("pointer", cycle_id), publish_events[-1])
                self.assertIn(("cycle", "completed"), publish_events[:-1])
                pointer = revisit_contract.load_pointer(workspace)
                self.assertEqual(
                    report.relative_to(workspace).as_posix(),
                    pointer["current_revision"]["report_path"],
                )
                self.assertEqual(
                    hashlib.sha256(report.read_bytes()).hexdigest(),
                    pointer["current_revision"]["report_sha256"],
                )
                self.assertEqual(
                    "completed",
                    revisit_contract.load_cycle(workspace, cycle_id)["status"],
                )
                ordinary = sofa_evaluate.evaluate_workspace(
                    workspace,
                    sofa_evaluate.ContractProfile(
                        mode="ticker",
                        target="final_report",
                    ),
                )
                self.assertTrue(
                    ordinary.passed,
                    [issue.display() for issue in ordinary.failures],
                )
                self.assertEqual(
                    immutable_bytes,
                    {
                        relative: (workspace / relative).read_bytes()
                        for relative in immutable_bytes
                    },
                )
                cycle = revisit_contract.load_cycle(workspace, cycle_id)
                expected_rerun_counts = {
                    "evidence_or_claim_only": 0,
                    "financial_or_risk_change": 1,
                    "action_class_change": 6,
                }
                self.assertEqual(
                    expected_rerun_counts[change_class],
                    len(cycle["rerun_artifacts"]),
                )
                for context in contexts.values():
                    self.assertIn("loop_10", context.text)


class TestTask9OfflineFixture(unittest.TestCase):
    def test_completed_ticker_fixture_is_exact_immutable_and_semantically_valid(self):
        fixture_root = REPO_ROOT / "tests" / "fixtures" / "revisit_completed_ticker"
        self.assertTrue(
            fixture_root.is_dir(),
            f"missing Task 9 fixture root: {fixture_root}",
        )

        actual_paths = {
            path.relative_to(fixture_root).as_posix()
            for path in fixture_root.rglob("*")
            if path.is_file()
        }
        expected_paths = set(TASK9_FIXTURE_PATHS)
        self.assertEqual(
            expected_paths,
            actual_paths,
            "Task 9 fixture path mismatch; "
            f"missing={sorted(expected_paths - actual_paths)!r}; "
            f"extra={sorted(actual_paths - expected_paths)!r}",
        )
        source_snapshot = snapshot_tree(fixture_root)

        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "workspace"
            shutil.copytree(fixture_root, workspace)

            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("AXTI", state["subject"])
            self.assertEqual("ticker", state["mode"])

            report_path = "reports/AXTI_SOFA_Report_2026-07-01.md"
            report_result = sofa_evaluate._evaluate_specific_ticker_report_document(
                report_path,
                (workspace / report_path).read_bytes(),
            )
            self.assertTrue(
                report_result.passed,
                [issue.display() for issue in report_result.failures],
            )

            framing = load_contract(workspace)
            framing_result = evaluate_contract(framing, state_mode="ticker")
            self.assertTrue(framing_result.complete, framing_result.issues)
            self.assertNotEqual("revisit", framing["research_posture"])

            registry = json.loads(
                (workspace / "frontier_registry.json").read_text(encoding="utf-8")
            )
            self.assertIs(registry, validate_registry(registry))
            self.assertEqual(["F1", "F2"], [row["id"] for row in registry["frontiers"]])

            source_result = evaluate_index(workspace)
            self.assertEqual((), source_result.issues)
            self.assertEqual(
                ("src-001", "src-002"),
                tuple(record["source_id"] for record in source_result.records),
            )

            digest = build_prior_query_digest(workspace)
            self.assertTrue(any(group.dead_ends for group in digest))
            self.assertEqual(
                {"src-001", "src-002"},
                {
                    source_id
                    for group in digest
                    for source_id in group.source_identifiers
                },
            )

            dispatch_result = sofa_evaluate.ContractResult()
            dispatch_records = sofa_evaluate._read_dispatch_records(
                workspace,
                dispatch_result,
            )
            self.assertTrue(
                dispatch_result.passed,
                [issue.display() for issue in dispatch_result.failures],
            )
            self.assertEqual(10, len(dispatch_records or ()))

            claim_ledger = (workspace / "claim_ledger.md").read_text(encoding="utf-8")
            self.assertIn("Customer qualification", claim_ledger)
            self.assertIn("Omitted historical claim", claim_ledger)
            self.assertIn(
                "Watch with Trigger",
                (workspace / report_path).read_text(encoding="utf-8"),
            )

            self.assertEqual(source_snapshot, snapshot_tree(workspace))

        self.assertEqual(source_snapshot, snapshot_tree(fixture_root))
