from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from ..capability_policy import build_prior_query_digest
    from ..frontier_lifecycle import LifecycleError, validate_registry
    from ..source_cache import (
        EXCERPT_MAX_CHARS,
        evaluate_index,
        excerpt_sha256,
        normalize_excerpt_text,
    )
except ImportError:
    from capability_policy import build_prior_query_digest
    from frontier_lifecycle import LifecycleError, validate_registry
    from source_cache import (
        EXCERPT_MAX_CHARS,
        evaluate_index,
        excerpt_sha256,
        normalize_excerpt_text,
    )

from .generation import _is_expected_input_os_error
from .model import RevisitContractError
from .store import load_cycle, resolve_workspace_path


_LOOP_ID_RE = re.compile(r"^loop_([1-9][0-9]*)$")


@dataclass(frozen=True)
class RevisitContext:
    text: str
    attachment_names: tuple[str, ...]


def build_revisit_context(
    workspace: str | Path,
    cycle_id: str,
    frontier_id: str,
    claim_ids: tuple[str, ...],
    role_slug: str,
    loop_id: str,
) -> RevisitContext:
    if role_slug not in {"frontier_scout", "challenge_probe"}:
        raise RevisitContractError(
            "revisit context is available only to frontier_scout and "
            "challenge_probe"
        )
    cycle = load_cycle(workspace, cycle_id)
    if cycle["status"] != "active":
        raise RevisitContractError(
            f"revisit cycle {cycle_id} is not active: {cycle['status']}"
        )
    binding = next(
        (
            row
            for row in cycle["frontier_bindings"]
            if row["frontier_id"] == frontier_id
        ),
        None,
    )
    if binding is None:
        raise RevisitContractError(
            f"frontier is not bound to cycle {cycle_id}: {frontier_id}"
        )
    if not claim_ids:
        raise RevisitContractError(
            "revisit context requires a non-empty claim subset"
        )
    if len(set(claim_ids)) != len(claim_ids):
        raise RevisitContractError("revisit context claim IDs must be unique")

    match = _LOOP_ID_RE.fullmatch(loop_id)
    if match is None:
        raise RevisitContractError(f"invalid revisit loop id: {loop_id}")
    loop_number = int(match.group(1))
    boundary = cycle["intake"]["workspace_boundary"]["max_existing_loop_number"]
    if loop_number <= boundary:
        raise RevisitContractError(
            f"revisit loop must be after cycle boundary {boundary}: {loop_id}"
        )

    claims_by_id = {
        claim["claim_id"]: claim
        for claim in (
            *cycle["intake"]["selected_claims"],
            *cycle["derived_claims"],
        )
    }
    unknown_claim_ids = [
        claim_id for claim_id in claim_ids if claim_id not in claims_by_id
    ]
    if unknown_claim_ids:
        raise RevisitContractError(
            "unknown revisit claim ID: " + ", ".join(unknown_claim_ids)
        )
    unbound_claim_ids = [
        claim_id for claim_id in claim_ids if claim_id not in binding["claim_ids"]
    ]
    if unbound_claim_ids:
        raise RevisitContractError(
            f"claims are not bound to frontier {frontier_id}: "
            + ", ".join(unbound_claim_ids)
        )
    selected_claims = [claims_by_id[claim_id] for claim_id in claim_ids]

    if role_slug == "frontier_scout":
        frontier = _load_frontier(workspace, frontier_id)
        text = _render_scout_context(
            Path(workspace),
            cycle,
            binding,
            frontier,
            selected_claims,
            claim_ids,
            loop_id,
        )
    else:
        text = _render_challenge_context(
            cycle,
            binding,
            claim_ids,
            loop_id,
        )
    return RevisitContext(text=text, attachment_names=("revisit_context",))


def _load_frontier(workspace: str | Path, frontier_id: str) -> dict[str, Any]:
    path = Path(workspace) / "frontier_registry.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_registry(raw)
    except (
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        NotADirectoryError,
        UnicodeError,
        json.JSONDecodeError,
        LifecycleError,
    ) as exc:
        raise RevisitContractError(f"frontier registry is invalid: {exc}") from exc
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        raise RevisitContractError(f"frontier registry is invalid: {exc}") from exc
    for frontier in raw["frontiers"]:
        if frontier["id"] == frontier_id:
            return frontier
    raise RevisitContractError(f"unknown frontier id: {frontier_id}")


def _render_scout_context(
    workspace: Path,
    cycle: dict[str, Any],
    binding: dict[str, Any],
    frontier: dict[str, Any],
    selected_claims: list[dict[str, Any]],
    claim_ids: tuple[str, ...],
    loop_id: str,
) -> str:
    selected_claim_id_set = set(claim_ids)
    selected_trigger_ids = {
        trigger_id
        for claim in selected_claims
        for trigger_id in claim.get("trigger_ids", ())
    }
    selected_triggers = [
        trigger
        for trigger in cycle["intake"]["triggers"]
        if trigger["trigger_id"] in selected_trigger_ids
    ]

    lines = [
        "### Revisit Context",
        "",
        "#### Target",
        f"- Cycle: {cycle['cycle_id']}",
        f"- Loop: {loop_id}",
        f"- Frontier: {binding['frontier_id']}",
        f"- Layer: {frontier['layer']}",
        f"- Structural parent: {frontier['parent_frontier']}",
        f"- Expected evidence: {binding['expected_evidence']}",
        "",
        "#### Observed Triggers",
    ]
    for trigger in selected_triggers:
        lines.append(f"- {trigger['trigger_id']}: {trigger['statement']}")
        lines.extend(
            f"  - {_render_evidence_ref(reference)}"
            for reference in trigger["evidence_refs"]
        )

    lines.extend(("", "#### Selected Claims"))
    for claim in selected_claims:
        lines.append(f"- {claim['claim_id']}: {claim['statement']}")

    lines.extend(("", "#### Target Frontier Prior Search Trace"))
    try:
        digest_groups = build_prior_query_digest(workspace)
    except (UnicodeError, ValueError) as exc:
        raise RevisitContractError(
            f"prior-query search trace is invalid: {exc}"
        ) from exc
    except OSError as exc:
        if not _is_expected_input_os_error(exc):
            raise
        raise RevisitContractError(
            f"prior-query search trace is invalid: {exc}"
        ) from exc
    target_groups = [
        group
        for group in digest_groups
        if group.group_id == binding["frontier_id"]
    ]
    if not target_groups:
        lines.append("- (no recorded searches for this frontier)")
    for group in target_groups:
        if group.queries:
            lines.append("Queries:")
            lines.extend(f"- {query}" for query in group.queries)
        if group.dead_ends:
            lines.append("Dead ends:")
            lines.extend(
                f"- [{dead_end.category}] {dead_end.query}"
                for dead_end in group.dead_ends
            )
        if group.visited_hosts:
            lines.append("Visited hosts:")
            lines.extend(f"- {host}" for host in group.visited_hosts)

    source_ids = _selected_source_ids(
        cycle,
        selected_triggers,
        selected_claims,
        selected_claim_id_set,
    )
    lines.extend(("", "#### Referenced Source Excerpts"))
    evaluation = evaluate_index(workspace)
    if evaluation.issues:
        details = "; ".join(
            f"{issue.code} at {issue.location}: {issue.message}"
            for issue in evaluation.issues
        )
        raise RevisitContractError(f"source cache is invalid: {details}")
    records_by_id = {record["source_id"]: record for record in evaluation.records}
    for source_id in source_ids:
        record = records_by_id.get(source_id)
        if record is None:
            raise RevisitContractError(
                f"referenced source is absent from source cache: {source_id}"
            )
        excerpt_path = resolve_workspace_path(
            workspace,
            record["excerpt_path"],
            parent="sources",
        )
        try:
            excerpt_payload = excerpt_path.read_bytes()
        except (
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
            NotADirectoryError,
        ) as exc:
            raise RevisitContractError(
                f"cannot read source excerpt for {source_id}: {exc}"
            ) from exc
        except OSError as exc:
            if not _is_expected_input_os_error(exc):
                raise
            raise RevisitContractError(
                f"cannot read source excerpt for {source_id}: {exc}"
            ) from exc
        try:
            excerpt = excerpt_payload.decode("utf-8")
        except UnicodeError as exc:
            raise RevisitContractError(
                f"cannot read source excerpt for {source_id}: {exc}"
            ) from exc
        normalized_excerpt = normalize_excerpt_text(excerpt)
        if excerpt_sha256(excerpt) != record["sha256"]:
            raise RevisitContractError(
                f"source excerpt hash drift for {source_id}: "
                "payload does not match the registered hash"
            )
        if len(normalized_excerpt) > EXCERPT_MAX_CHARS:
            raise RevisitContractError(
                f"source excerpt for {source_id} is {len(normalized_excerpt)} "
                f"characters; the cap is {EXCERPT_MAX_CHARS}"
            )
        lines.extend(
            (
                f"- Source: {source_id}",
                f"  - Excerpt path: {record['excerpt_path']}",
                "  - Raw excerpt:",
                *[
                    f"    {line}"
                    for line in normalized_excerpt.rstrip().splitlines()
                ],
            )
        )
    if not source_ids:
        lines.append("- (no explicitly referenced sources)")
    return "\n".join(lines).rstrip() + "\n"


def _render_challenge_context(
    cycle: dict[str, Any],
    binding: dict[str, Any],
    claim_ids: tuple[str, ...],
    loop_id: str,
) -> str:
    lines = [
        "### Revisit Context",
        "",
        "#### Challenge Target",
        f"- Cycle: {cycle['cycle_id']}",
        f"- Loop: {loop_id}",
        f"- Frontier: {binding['frontier_id']}",
        "- Claims: " + ", ".join(claim_ids),
        "",
        "#### Accepted Current Evidence References",
    ]
    resolutions_by_claim = {
        resolution["claim_id"]: resolution
        for resolution in cycle["claim_resolutions"]
    }
    for claim_id in claim_ids:
        resolution = resolutions_by_claim[claim_id]
        lines.append(f"- Claim: {claim_id}")
        if resolution["current_grade"] is not None:
            lines.append(f"  - Grade: {resolution['current_grade']}")
        if not resolution["current_evidence_refs"]:
            lines.append("  - Evidence refs: (none accepted)")
        for reference in resolution["current_evidence_refs"]:
            lines.append("  - " + _render_evidence_ref(reference))
    return "\n".join(lines).rstrip() + "\n"


def _render_evidence_ref(reference: dict[str, Any]) -> str:
    if reference["kind"] == "source":
        return (
            f"Source ref: {reference['source_id']}; "
            f"checked_at={reference['checked_at']}"
        )
    return (
        f"Artifact ref: {reference['path']}; sha256={reference['sha256']}; "
        f"locator={reference['locator']}; checked_at={reference['checked_at']}"
    )


def _selected_source_ids(
    cycle: dict[str, Any],
    selected_triggers: list[dict[str, Any]],
    selected_claims: list[dict[str, Any]],
    selected_claim_ids: set[str],
) -> tuple[str, ...]:
    references: list[dict[str, Any]] = []
    for trigger in selected_triggers:
        references.extend(trigger["evidence_refs"])
    for claim in selected_claims:
        for inherited in claim.get("inherited_evidence", ()):
            references.append(inherited["ref"])
        accepted_from = claim.get("accepted_from")
        if accepted_from is not None:
            references.extend(accepted_from["evidence_refs"])
    for resolution in cycle["claim_resolutions"]:
        if resolution["claim_id"] in selected_claim_ids:
            references.extend(resolution["current_evidence_refs"])
            references.extend(resolution["counter_evidence_refs"])

    source_ids: list[str] = []
    for reference in references:
        if reference.get("kind") == "source":
            source_id = reference["source_id"]
            if source_id not in source_ids:
                source_ids.append(source_id)
    return tuple(source_ids)
