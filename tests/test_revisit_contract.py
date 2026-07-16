import copy
import dataclasses
import hashlib
import io
import json
import os
import re
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import scripts.revisit_contract as revisit_contract
import scripts.revisit_contract.model as revisit_model
import scripts.revisit_contract.store as revisit_store
import scripts.revisit_cycle as revisit_cycle_cli
import scripts.sofa_contract.evaluate as sofa_evaluate
import scripts.timeliness_checker as timeliness_checker
from scripts.frontier_lifecycle import create_frontier, make_registry, transition

REPO_ROOT = Path(__file__).resolve().parents[1]
REVISIT_CYCLE_SCRIPT = REPO_ROOT / "scripts" / "revisit_cycle.py"


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
    source_path.write_text(source_excerpt, encoding="utf-8")
    source_record = {
        "source_id": "src-001",
        "url": "https://example.test/qualification",
        "title": "Qualification milestone source",
        "retrieved": "2026-07-14",
        "grade": "B",
        "excerpt_path": "sources/src-001.md",
        "sha256": hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest(),
    }
    (workspace / "sources_index.jsonl").write_text(
        json.dumps(source_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
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
    excerpt_path.write_text(excerpt, encoding="utf-8")
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
            "kind": "delta-frontier-review",
            "scope": "affected",
            "round": 1,
            "path": "artifacts/delta-frontier-review.json",
            "sha256": "e" * 64,
            "recorded_at": timestamp,
        }
    ]
    cycle["report_candidate"] = {
        "revision_id": "REV-0002",
        "revision_of": "REV-0001",
        "report_path": "reports/revision-0002.md",
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
    cycle["status"] = status
    if status == "completed":
        cycle["completed_at"] = "2026-07-15T02:00:00Z"
    elif status == "aborted":
        cycle["aborted_at"] = "2026-07-15T02:00:00Z"
        cycle["abort_reason"] = "Historical test reservation."
    attach_valid_audit(cycle)
    return cycle


def make_drifted_task4_cycle():
    cycle = make_minimal_cycle()
    cycle["intake"]["framing"]["snapshot"][
        "research_posture"
    ] = "decision_support"
    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
    attach_valid_audit(cycle)
    return cycle


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
    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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
                        r"absolute workspace path is forbidden|forbidden '\.\.'|path escapes workspace",
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
                r"request trigger index 2 is not referenced by any selected claim",
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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
                        updated = copy.deepcopy(previous)
                        updated["status"] = status
                        if status == "completed":
                            updated["completed_at"] = "2026-07-15T05:00:00Z"
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

        aborted = make_minimal_cycle()
        aborted["status"] = "aborted"
        aborted["aborted_at"] = "2026-07-15T01:00:00Z"
        aborted["abort_reason"] = "Evidence access ended."
        aborted["candidate_revision_id"] = "REV-0002"
        attach_valid_audit(aborted)

        completed = make_minimal_cycle(
            cycle_id="RC-0004", candidate_revision_id="REV-0007"
        )
        completed["status"] = "completed"
        completed["completed_at"] = "2026-07-15T02:00:00Z"
        attach_valid_audit(completed)
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
    def make_status_workspace(self, root, condition):
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
            cycle["status"] = "aborted"
            cycle["aborted_at"] = "2026-07-15T03:00:00Z"
            cycle["abort_reason"] = "The selected proof became unavailable."
        elif condition in {"published", "completed-unpublished"}:
            cycle["status"] = "completed"
            cycle["completed_at"] = "2026-07-15T03:00:00Z"
        if condition == "published":
            pointer["current_revision"] = make_revisit_revision()
        if pointer["current_revision"] is not None:
            pointer["current_revision"]["report_sha256"] = hashlib.sha256(
                report_payload
            ).hexdigest()
        if cycle is not None:
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
                cycle["status"] = "completed"
                cycle["completed_at"] = "2026-07-15T03:00:00Z"
                attach_valid_audit(cycle)
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
        updated = copy.deepcopy(previous)
        updated["status"] = status
        if status == "completed":
            updated["completed_at"] = "2026-07-15T04:00:00Z"
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
                r"immediately follow Continued",
            ),
            (
                "reactivated missing post-cycle Active",
                self._make_old_active_reactivated,
                "reactivated",
                r"post-cycle Active transition",
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

        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_REVIEW_FLOOR_MISSING",
            expected_path="cycle.frontier_bindings[0]",
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
        mutate_before_evaluate: bool,
        expected_message: str,
    ) -> None:
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
            real_evaluate = revisit_cycle_cli.evaluate_revisit_report

            def mutate_index() -> None:
                source_index.write_bytes(changed_index)

            def evaluate_with_index_race(*args, **kwargs):
                if mutate_before_evaluate:
                    mutate_index()
                evaluation = real_evaluate(*args, **kwargs)
                if not mutate_before_evaluate:
                    mutate_index()
                return evaluation

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_revisit_report",
                    side_effect=evaluate_with_index_race,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(2, result, stderr.getvalue())
            self.assertRegex(stderr.getvalue(), expected_message)
            self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
            self.assertEqual(changed_index, source_index.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_artifact_only_check_generation_binds_present_source_index(self):
        self.assert_artifact_only_source_index_race_rejected(
            starts_absent=False,
            mutate_before_evaluate=False,
            expected_message="authority changed",
        )

    def test_artifact_only_check_rejects_source_index_missing_to_appearance(self):
        self.assert_artifact_only_source_index_race_rejected(
            starts_absent=True,
            mutate_before_evaluate=True,
            expected_message="authority appeared",
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

        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_FRONTIER_BINDING_INVALID",
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

        self.assert_revisit_failure(
            make_workspace,
            "REVISIT_FRONTIER_BINDING_INVALID",
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
                workspace, cycle_id, require_candidate=False
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
                    "REVISIT_CYCLE_MALFORMED",
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
                    "REVISIT_CYCLE_MALFORMED",
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
                    self.assertIn(
                        "REVISIT_FRONTIER_BINDING_INVALID",
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
        for state_case in ("missing", "unknown"):
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
                    self.assertIn(
                        "REVISIT_CYCLE_MALFORMED",
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
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            original_excerpt = workspace / "sources" / "src-001.md"
            remapped_excerpt = workspace / "sources" / "src-001-remapped.md"
            remapped_excerpt.write_bytes(original_excerpt.read_bytes())
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_evaluate_index = revisit_cycle_cli.evaluate_index
            calls = 0

            def evaluate_with_second_call_remap(*args, **kwargs):
                nonlocal calls
                evaluation = real_evaluate_index(*args, **kwargs)
                calls += 1
                if calls != 2:
                    return evaluation
                remapped_record = copy.deepcopy(evaluation.records[0])
                remapped_record["excerpt_path"] = (
                    "sources/src-001-remapped.md"
                )
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
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(2, calls)
            self.assertEqual(2, result, stderr.getvalue())
            self.assertIn(
                "source record changed during validation: src-001",
                stderr.getvalue(),
            )
            self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def assert_missing_authority_cannot_appear_during_evaluation(
        self,
        workspace: Path,
        cycle_id: str,
        authority_path: Path,
    ) -> None:
        authority_payload = authority_path.read_bytes()
        authority_path.unlink()
        cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
        mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
        prior_cycle = cycle_path.read_bytes()
        prior_mirror = mirror_path.read_bytes()
        real_evaluate = revisit_cycle_cli.evaluate_revisit_report
        evaluate_calls = 0

        def restore_before_evaluate(*args, **kwargs):
            nonlocal evaluate_calls
            evaluate_calls += 1
            authority_path.write_bytes(authority_payload)
            return real_evaluate(*args, **kwargs)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(
                revisit_cycle_cli,
                "evaluate_revisit_report",
                side_effect=restore_before_evaluate,
            ),
            mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
            mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
        ):
            result = revisit_cycle_cli.main(
                [str(workspace), "check", cycle_id]
            )

        self.assertNotEqual(0, result, stderr.getvalue())
        self.assertEqual(0, evaluate_calls)
        self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
        self.assertFalse(authority_path.exists())
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
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            orphan_path = workspace / "scouts" / "orphan.md"
            orphan_path.write_text(
                "# Orphan worker output\n",
                encoding="utf-8",
            )
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_evaluate = revisit_cycle_cli.evaluate_revisit_report
            evaluate_calls = 0

            def remove_before_evaluate(*args, **kwargs):
                nonlocal evaluate_calls
                evaluate_calls += 1
                orphan_path.unlink()
                return real_evaluate(*args, **kwargs)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_revisit_report",
                    side_effect=remove_before_evaluate,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertNotEqual(0, result, stderr.getvalue())
            self.assertEqual(1, evaluate_calls)
            self.assertRegex(stderr.getvalue(), "authority disappeared")
            self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
            self.assertFalse(orphan_path.exists())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_check_binds_complete_pre_evaluation_authority_set_once_in_order(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_path = root / "workspace" / "evidence" / "current.md"
            artifact_path.parent.mkdir(parents=True)
            artifact_payload = b"Current cycle evidence.\n"
            artifact_path.write_bytes(artifact_payload)
            current_ref = {
                "kind": "artifact",
                "path": "evidence/current.md",
                "sha256": hashlib.sha256(artifact_payload).hexdigest(),
                "locator": "Current cycle evidence",
                "checked_at": "2026-07-14T12:00:00Z",
            }
            workspace, cycle_id = make_task6_ready_workspace(
                root,
                current_ref=current_ref,
            )
            cycle_relative = f"revisit_cycles/{cycle_id}.json"
            prior_cycle_sha256 = revisit_contract.sha256_file(
                workspace / cycle_relative
            )
            delivered_targets = {
                (Path(directory) / f"loop_{loop_number}_{suffix}.md").as_posix()
                for loop_number in range(8, 11)
                for directory, suffix in (
                    ("scouts", "scout"),
                    ("challenges", "challenge"),
                )
            }
            expected_captures = {
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
            events = []
            post_evaluation_checks = []
            persisted_paths = []
            persisted_expected_sha256 = None
            real_read = revisit_cycle_cli._read_authority_generation
            real_require = revisit_cycle_cli._require_authority_generation
            real_require_snapshots = revisit_cycle_cli._require_snapshot_generations
            real_evaluate = revisit_cycle_cli.evaluate_revisit_report
            real_persist = revisit_cycle_cli.persist_cycle

            def relative_path(snapshot):
                return snapshot.lexical_path.relative_to(
                    snapshot.workspace
                ).as_posix()

            def record_generation(snapshot_workspace, path):
                generation = real_read(snapshot_workspace, path)
                events.append(("capture", relative_path(generation.snapshot)))
                return generation

            def record_generation_check(generation, boundary):
                if boundary == "after revisit report evaluation":
                    checked_path = relative_path(generation.snapshot)
                    post_evaluation_checks.append(checked_path)
                    events.append(("post_evaluation_check", checked_path))
                return real_require(generation, boundary)

            def record_snapshot_checks(snapshots, boundary):
                if boundary == "after revisit report evaluation":
                    for snapshot in snapshots.values():
                        checked_path = relative_path(snapshot)
                        post_evaluation_checks.append(checked_path)
                        events.append(("post_evaluation_check", checked_path))
                return real_require_snapshots(snapshots, boundary)

            def record_evaluate(*args, **kwargs):
                events.append(("evaluate", cycle_id))
                return real_evaluate(*args, **kwargs)

            def record_persist(
                snapshot_workspace,
                cycle,
                expected_sha256,
                *,
                authority_snapshots=None,
            ):
                nonlocal persisted_expected_sha256
                persisted_expected_sha256 = expected_sha256
                persisted_paths.extend(
                    relative_path(snapshot)
                    for snapshot in authority_snapshots or ()
                )
                events.append(("persist", cycle["cycle_id"]))
                return real_persist(
                    snapshot_workspace,
                    cycle,
                    expected_sha256,
                    authority_snapshots=authority_snapshots,
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_read_authority_generation",
                    side_effect=record_generation,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "_require_authority_generation",
                    side_effect=record_generation_check,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "_require_snapshot_generations",
                    side_effect=record_snapshot_checks,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_revisit_report",
                    side_effect=record_evaluate,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_cycle",
                    side_effect=record_persist,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(0, result, stderr.getvalue())
            capture_paths = [
                path for event, path in events if event == "capture"
            ]
            self.assertEqual(expected_captures, set(capture_paths))
            self.assertEqual(len(capture_paths), len(set(capture_paths)))
            evaluate_index = events.index(("evaluate", cycle_id))
            persist_index = events.index(("persist", cycle_id))
            self.assertTrue(
                all(
                    index < evaluate_index
                    for index, (event, _path) in enumerate(events)
                    if event == "capture"
                )
            )
            self.assertLess(evaluate_index, persist_index)
            self.assertEqual(expected_captures, set(post_evaluation_checks))
            self.assertEqual(
                len(post_evaluation_checks),
                len(set(post_evaluation_checks)),
            )
            self.assertTrue(
                all(
                    evaluate_index < index < persist_index
                    for index, (event, _path) in enumerate(events)
                    if event == "post_evaluation_check"
                )
            )
            expected_persisted = expected_captures - {cycle_relative}
            self.assertEqual(expected_persisted, set(persisted_paths))
            self.assertEqual(len(persisted_paths), len(set(persisted_paths)))
            self.assertEqual(prior_cycle_sha256, persisted_expected_sha256)

    def test_check_deduplicates_source_excerpt_artifact_authority_union(self):
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

            def relative_path(snapshot):
                return snapshot.lexical_path.relative_to(
                    snapshot.workspace
                ).as_posix()

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "_read_authority_generation",
                    wraps=revisit_cycle_cli._read_authority_generation,
                ) as read_spy,
                mock.patch.object(
                    revisit_cycle_cli,
                    "_require_authority_generation",
                    wraps=revisit_cycle_cli._require_authority_generation,
                ) as generation_check_spy,
                mock.patch.object(
                    revisit_cycle_cli,
                    "_require_snapshot_generations",
                    wraps=revisit_cycle_cli._require_snapshot_generations,
                ) as snapshot_check_spy,
                mock.patch.object(
                    revisit_cycle_cli,
                    "persist_cycle",
                    wraps=revisit_cycle_cli.persist_cycle,
                ) as persist_spy,
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(0, result, stderr.getvalue())
            captured_paths = [
                Path(os.path.abspath(os.fspath(call.args[1])))
                .relative_to(workspace.resolve())
                .as_posix()
                for call in read_spy.call_args_list
            ]
            post_evaluation_paths = [
                relative_path(call.args[0].snapshot)
                for call in generation_check_spy.call_args_list
                if call.args[1] == "after revisit report evaluation"
            ]
            for call in snapshot_check_spy.call_args_list:
                if call.args[1] != "after revisit report evaluation":
                    continue
                post_evaluation_paths.extend(
                    relative_path(snapshot)
                    for snapshot in call.args[0].values()
                )
            persisted_paths = [
                relative_path(snapshot)
                for snapshot in persist_spy.call_args.kwargs[
                    "authority_snapshots"
                ]
            ]
            for phase, paths in (
                ("capture", captured_paths),
                ("post-evaluation recheck", post_evaluation_paths),
                ("persistence", persisted_paths),
            ):
                with self.subTest(phase=phase):
                    self.assertEqual(len(paths), len(set(paths)), paths)
                    self.assertEqual(1, paths.count("sources/src-001.md"))

    def test_check_rejects_delivered_worker_path_drift_before_ready_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            delivery = workspace / "scouts" / "loop_8_scout.md"
            drifted_delivery = delivery.read_bytes() + b"post-evaluation drift\n"
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_evaluate = revisit_cycle_cli.evaluate_revisit_report

            def evaluate_then_drift(*args, **kwargs):
                evaluation = real_evaluate(*args, **kwargs)
                delivery.write_bytes(drifted_delivery)
                return evaluation

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "evaluate_revisit_report",
                    side_effect=evaluate_then_drift,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
            ):
                result = revisit_cycle_cli.main(
                    [str(workspace), "check", cycle_id]
                )

            self.assertEqual(2, result, stderr.getvalue())
            self.assertRegex(stderr.getvalue(), "authority changed")
            self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
            self.assertEqual(drifted_delivery, delivery.read_bytes())
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    def test_check_rejects_intake_authority_byte_drift_without_cycle_writes(self):
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
                real_evaluate = revisit_cycle_cli.evaluate_revisit_report

                def evaluate_then_drift(*args, **kwargs):
                    evaluation = real_evaluate(*args, **kwargs)
                    authority.write_bytes(drifted)
                    return evaluation

                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(
                        revisit_cycle_cli,
                        "evaluate_revisit_report",
                        side_effect=evaluate_then_drift,
                    ),
                    mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                    mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                ):
                    result = revisit_cycle_cli.main(
                        [str(workspace), "check", cycle_id]
                    )

                self.assertEqual(2, result, stderr.getvalue())
                self.assertRegex(stderr.getvalue(), "authority changed")
                self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
                self.assertEqual(drifted, authority.read_bytes())
                self.assertEqual(prior_cycle, cycle_path.read_bytes())
                self.assertEqual(prior_mirror, mirror_path.read_bytes())

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
    def test_check_rejects_intake_authority_retarget_without_cycle_writes(self):
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
                real_evaluate = revisit_cycle_cli.evaluate_revisit_report

                def evaluate_then_retarget(*args, **kwargs):
                    evaluation = real_evaluate(*args, **kwargs)
                    authority.unlink()
                    authority.symlink_to(second_target.name)
                    return evaluation

                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(
                        revisit_cycle_cli,
                        "evaluate_revisit_report",
                        side_effect=evaluate_then_retarget,
                    ),
                    mock.patch.object(revisit_cycle_cli.sys, "stdout", stdout),
                    mock.patch.object(revisit_cycle_cli.sys, "stderr", stderr),
                ):
                    result = revisit_cycle_cli.main(
                        [str(workspace), "check", cycle_id]
                    )

                self.assertEqual(2, result, stderr.getvalue())
                self.assertRegex(stderr.getvalue(), "authority target changed")
                self.assertNotIn("REVISIT CYCLE READY", stdout.getvalue())
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
    def test_emergent_claim_rejects_delivery_alias_as_artifact_evidence_without_writes(
        self,
    ):
        self._assert_worker_delivery_artifact_rejected(alias=True)

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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

    def test_resolve_workspace_path_rejects_internal_symlink_parent_and_suffix_change(
        self,
    ):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.json", "resolved path must be under reports/"
        )

    def test_resolve_workspace_path_rejects_internal_symlink_parent_change(self):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.md", "resolved path must be under reports/"
        )

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
            self.assertEqual(1, sum("cycle conflict: RC-0001 is active" in row[2] for row in results))
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
                self.assertIn("cycle conflict: RC-0001 is active", start_result[2])

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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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

    @unittest.skipUnless(hasattr(os, "symlink"), "requires symbolic links")
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
                "every intake trigger must be referenced",
            ),
        )
        for label, mutate, pattern in cases:
            with self.subTest(case=label):
                cycle = make_minimal_cycle()
                mutate(cycle)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                attach_valid_audit(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

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
        cycle["intake_sha256"] = "0" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle.intake_sha256 does not match immutable intake",
        )

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

        completed = make_populated_cycle()
        completed["status"] = "completed"
        completed["completed_at"] = "2026-07-15T02:00:00Z"
        attach_valid_audit(completed)
        cycles.append(completed)

        aborted = make_minimal_cycle()
        aborted["status"] = "aborted"
        aborted["aborted_at"] = "2026-07-15T02:00:00Z"
        aborted["abort_reason"] = "Primary evidence became unavailable."
        attach_valid_audit(aborted)
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
            ("scope", "partial", "rerun_artifacts.*scope is unsupported"),
            ("round", True, "rerun_artifacts.*round must be an integer >= 1"),
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
