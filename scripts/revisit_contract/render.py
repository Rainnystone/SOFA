from __future__ import annotations

import json
from typing import Any, Iterable

from .model import RevisitContractError, validate_cycle


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _table_cell(value: Any) -> str:
    return (
        _display(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
    )


def _append_table(
    lines: list[str], headers: tuple[str, ...], rows: Iterable[tuple[Any, ...]]
) -> None:
    materialized = list(rows)
    if not materialized:
        lines.extend(("_None recorded._", ""))
        return
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in materialized:
        lines.append("| " + " | ".join(_table_cell(value) for value in row) + " |")
    lines.append("")


def render_cycle_markdown(cycle: dict[str, Any]) -> str:
    validate_cycle(cycle)
    intake = cycle["intake"]
    base = intake["base_revision"]
    framing = intake["framing"]
    boundary = intake["workspace_boundary"]
    lines = [
        f"# Revisit Cycle {_table_cell(cycle['cycle_id'])}",
        "",
        "> Deterministic human-readable mirror. The cycle JSON is canonical authority.",
        "",
        "## Identity And Status",
        "",
    ]
    _append_table(
        lines,
        ("Field", "Value"),
        (
            ("Cycle ID", cycle["cycle_id"]),
            ("Candidate revision ID", cycle["candidate_revision_id"]),
            ("Status", cycle["status"]),
            ("Created at", cycle["created_at"]),
            ("Completed at", cycle["completed_at"]),
            ("Aborted at", cycle["aborted_at"]),
            ("Abort reason", cycle["abort_reason"]),
            ("Intake SHA-256", cycle["intake_sha256"]),
        ),
    )

    lines.extend(("## Immutable Base And Framing Boundary", ""))
    _append_table(
        lines,
        ("Field", "Value"),
        (
            ("Base revision ID", base["revision_id"]),
            ("Base report path", base["report_path"]),
            ("Base report SHA-256", base["report_sha256"]),
            ("Base action class", base["action_class"]),
            ("Framing path", framing["path"]),
            ("Framing SHA-256", framing["sha256"]),
            ("Framing snapshot", framing["snapshot"]),
            ("Frontier registry SHA-256", boundary["frontier_registry_sha256"]),
            ("Maximum existing loop number", boundary["max_existing_loop_number"]),
        ),
    )

    lines.extend(("## Fired Triggers", ""))
    _append_table(
        lines,
        ("Trigger ID", "Kind", "Observed at", "Statement", "Evidence refs"),
        (
            (
                trigger["trigger_id"],
                trigger["kind"],
                trigger["observed_at"],
                trigger["statement"],
                trigger["evidence_refs"],
            )
            for trigger in sorted(
                intake["triggers"], key=lambda item: item["trigger_id"]
            )
        ),
    )

    lines.extend(
        (
            "## Selected And Derived Claims",
            "",
            "> Unselected historical claims are omitted and cannot support this cycle.",
            "",
            "### Selected Claims",
            "",
        )
    )
    _append_table(
        lines,
        (
            "Claim ID",
            "Statement",
            "Importance",
            "Selection reasons",
            "Trigger IDs",
            "Inherited grade",
            "Inherited confidence",
            "Source ref",
        ),
        (
            (
                claim["claim_id"],
                claim["statement"],
                claim["importance"],
                claim["selection_reasons"],
                claim["trigger_ids"],
                claim["inherited_grade"],
                claim["inherited_confidence"],
                claim["source_ref"],
            )
            for claim in sorted(
                intake["selected_claims"], key=lambda item: item["claim_id"]
            )
        ),
    )
    lines.extend(("### Derived Claims", ""))
    _append_table(
        lines,
        (
            "Claim ID",
            "Origin",
            "Statement",
            "Derived from",
            "Accepted from",
            "Acceptance rationale",
        ),
        (
            (
                claim["claim_id"],
                claim["origin"],
                claim["statement"],
                claim["derived_from"],
                claim["accepted_from"],
                claim["acceptance_rationale"],
            )
            for claim in sorted(
                cycle["derived_claims"], key=lambda item: item["claim_id"]
            )
        ),
    )
    lines.extend(("### Claim Resolutions", ""))
    _append_table(
        lines,
        (
            "Claim ID",
            "Status",
            "Revised statement",
            "Current evidence refs",
            "Counter-evidence refs",
            "Current grade",
            "Current confidence",
            "Bound frontier IDs",
            "Rationale",
            "Missing proof",
            "Attempted loop IDs",
            "Attempted search refs",
            "Recorded verdict impact",
            "Split child IDs",
        ),
        (
            (
                resolution["claim_id"],
                resolution["status"],
                resolution["revised_statement"],
                resolution["current_evidence_refs"],
                resolution["counter_evidence_refs"],
                resolution["current_grade"],
                resolution["current_confidence"],
                resolution["bound_frontier_ids"],
                resolution["rationale"],
                resolution["missing_proof"],
                resolution["attempted_loop_ids"],
                resolution["attempted_search_refs"],
                resolution["verdict_impact"],
                resolution["split_child_ids"],
            )
            for resolution in sorted(
                cycle["claim_resolutions"], key=lambda item: item["claim_id"]
            )
        ),
    )

    lines.extend(("## Freshness", ""))
    freshness_rows = []
    for claim in sorted(
        intake["selected_claims"], key=lambda item: item["claim_id"]
    ):
        for evidence in claim["inherited_evidence"]:
            freshness_rows.append(
                (
                    claim["claim_id"],
                    evidence["freshness"],
                    evidence["checked_at"],
                    evidence["reason"],
                    evidence["ref"],
                )
            )
    _append_table(
        lines,
        ("Claim ID", "Freshness", "Checked at", "Reason", "Evidence ref"),
        freshness_rows,
    )

    lines.extend(("## Frontier Bindings And Floors", ""))
    _append_table(
        lines,
        (
            "Frontier ID",
            "Action",
            "Claim IDs",
            "Expected evidence",
            "Baseline loops",
            "Baseline reviews",
            "Registry SHA-256",
            "Bound at",
        ),
        (
            (
                binding["frontier_id"],
                binding["action"],
                binding["claim_ids"],
                binding["expected_evidence"],
                binding["baseline_loop_count"],
                binding["baseline_review_count"],
                binding["registry_sha256"],
                binding["bound_at"],
            )
            for binding in sorted(
                cycle["frontier_bindings"], key=lambda item: item["frontier_id"]
            )
        ),
    )

    lines.extend(("## Decision And Rerun Duties", ""))
    assessment = cycle["decision_assessment"]
    if assessment is None:
        lines.extend(("No decision assessment recorded.", ""))
    else:
        _append_table(
            lines,
            ("Field", "Recorded value"),
            (
                ("New action class", assessment["new_action_class"]),
                ("Financial bridge affected", assessment["financial_bridge_affected"]),
                (
                    "Financial bridge rationale",
                    assessment["financial_bridge_rationale"],
                ),
                ("Risk class changed", assessment["risk_class_changed"]),
                ("Risk class rationale", assessment["risk_class_rationale"]),
                ("Supporting claim IDs", assessment["supporting_claim_ids"]),
                ("Recorded verdict rationale", assessment["verdict_rationale"]),
                ("Blocked claim IDs", assessment["blocked_claim_ids"]),
                ("Change class", assessment["change_class"]),
                ("Required reruns", assessment["required_reruns"]),
            ),
        )
    lines.extend(("### Recorded Rerun Artifacts", ""))
    _append_table(
        lines,
        ("Kind", "Scope", "Round", "Path", "SHA-256", "Recorded at"),
        (
            (
                artifact["kind"],
                artifact["scope"],
                artifact["round"],
                artifact["path"],
                artifact["sha256"],
                artifact["recorded_at"],
            )
            for artifact in sorted(
                cycle["rerun_artifacts"],
                key=lambda item: (
                    item["kind"],
                    item["round"] if item["round"] is not None else 0,
                    item["path"],
                ),
            )
        ),
    )

    lines.extend(("## Report Candidate", ""))
    candidate = cycle["report_candidate"]
    if candidate is None:
        lines.extend(("No report candidate recorded.", ""))
    else:
        _append_table(
            lines,
            ("Field", "Value"),
            (
                ("Revision ID", candidate["revision_id"]),
                ("Revision of", candidate["revision_of"]),
                ("Report path", candidate["report_path"]),
                ("Report SHA-256", candidate["report_sha256"]),
                ("Registered at", candidate["registered_at"]),
            ),
        )

    lines.extend(("## Audit", ""))
    _append_table(
        lines,
        (
            "Sequence",
            "Timestamp",
            "Command",
            "Affected IDs",
            "Pre-state SHA-256",
            "Post-state SHA-256",
        ),
        (
            (
                entry["sequence"],
                entry["timestamp"],
                entry["command"],
                entry["affected_ids"],
                entry["pre_state_sha256"],
                entry["post_state_sha256"],
            )
            for entry in sorted(cycle["audit"], key=lambda item: item["sequence"])
        ),
    )
    return "\n".join(lines).rstrip("\n") + "\n"


def render_report_metadata(cycle: dict[str, Any]) -> str:
    validate_cycle(cycle)
    if cycle["status"] not in {"ready_for_report", "completed"}:
        raise RevisitContractError(
            "report metadata requires a ready or completed cycle"
        )
    assessment = cycle["decision_assessment"]
    if assessment is None:
        raise RevisitContractError(
            "report metadata requires a deterministic decision assessment"
        )
    base = cycle["intake"]["base_revision"]

    def joined(values: list[str]) -> str:
        return ", ".join(values) if values else "none"

    rows = (
        ("Cycle ID", cycle["cycle_id"]),
        ("Revision ID", cycle["candidate_revision_id"]),
        ("Revision of", base["revision_id"]),
        ("Base report SHA-256", base["report_sha256"]),
        ("Base action class", base["action_class"]),
        ("Current action class", assessment["new_action_class"]),
        ("Change class", assessment["change_class"]),
        ("Supporting claims", joined(assessment["supporting_claim_ids"])),
        ("Blocked claims", joined(assessment["blocked_claim_ids"])),
        ("Required reruns", joined(assessment["required_reruns"])),
    )
    lines = [
        "<!-- sofa:revisit-revision:start -->",
        "## Revisit Revision Metadata",
        "",
        "| Field | Value |",
        "| --- | --- |",
        *(f"| {_table_cell(label)} | {_table_cell(value)} |" for label, value in rows),
        "<!-- sofa:revisit-revision:end -->",
    ]
    return "\n".join(lines) + "\n"
