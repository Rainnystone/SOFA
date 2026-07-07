"""Deterministic frontier lifecycle helpers for SOFA workflows."""

from __future__ import annotations

import copy
import re
from typing import Any


STATUSES = ("New", "Active", "Continued", "Retired")
SUPPORTED_MODES = ("sector", "ticker")
FRONTIER_SOURCES = ("initial", "discovery", "serendipity")
VALID_RETIRE_CATEGORIES = frozenset(
    {"blocked", "invalidated", "barren", "superseded", "bad_pick", "answered_out"}
)
REVIEW_RETIRE_CATEGORIES = frozenset({"answered_out", "bad_pick", "superseded"})
EARLY_RETIRE_CATEGORIES_BY_MODE = {
    "ticker": frozenset({"blocked", "invalidated"}),
    "sector": frozenset({"blocked", "invalidated", "barren"}),
}
KNOWN_STAGES = frozenset(f"stage_{index}" for index in range(7))
LOOP_HEADER_RE = re.compile(r"^## Loop (?P<loop>[1-9][0-9]*): (?P<frontier_id>F[1-9][0-9]*) - (?P<name>.+)$")
FRONTIER_ID_RE = re.compile(r"^F(?P<number>[1-9][0-9]*)$")


class LifecycleError(ValueError):
    """Base error for deterministic lifecycle contract violations."""


class BindingError(LifecycleError):
    """Raised when a ledger loop cannot be bound to a known frontier ID."""


class InvalidTransition(LifecycleError):
    """Raised when a requested lifecycle transition violates v4 semantics."""


def make_registry(subject: str, mode: str) -> dict[str, Any]:
    """Create an empty v4 frontier registry."""
    if mode not in SUPPORTED_MODES:
        raise LifecycleError(f"unsupported mode: {mode}")

    return {
        "version": 2,
        "subject": subject,
        "mode": mode,
        "frontiers": [],
        "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
        "review_trigger": {"every_loops": 3, "max_reviews": 3},
    }


def create_frontier(
    registry: dict[str, Any],
    *,
    name: str,
    proposed_at_loop: int,
    source: str,
    source_frontier: str | None = None,
    initial_status: str = "New",
    ts: str | None = None,
) -> dict[str, Any]:
    """Return a registry copy with one new frontier record appended."""
    if source not in FRONTIER_SOURCES:
        raise InvalidTransition(f"unsupported frontier source: {source}")
    if initial_status not in {"New", "Active"}:
        raise InvalidTransition("frontiers can only be created as New or Active")
    if int(proposed_at_loop) < 1:
        raise InvalidTransition("proposed_at_loop must be positive")

    updated = copy.deepcopy(registry)
    existing_ids = {frontier.get("id") for frontier in updated.get("frontiers", [])}

    if source == "initial" and source_frontier is not None:
        raise InvalidTransition("initial frontiers cannot set source_frontier")
    if source in {"discovery", "serendipity"}:
        if source_frontier is None:
            raise InvalidTransition(f"{source} frontiers require source_frontier")
        if source_frontier not in existing_ids:
            raise BindingError(f"unknown source_frontier: {source_frontier}")

    frontier_id = _next_frontier_id(updated)
    lifecycle = [{"to": "New", "at_loop": proposed_at_loop, "ts": ts}]
    if initial_status == "Active":
        lifecycle.append({"to": "Active", "at_loop": proposed_at_loop, "ts": ts})

    updated.setdefault("frontiers", []).append(
        {
            "id": frontier_id,
            "name": name,
            "proposed_at_loop": proposed_at_loop,
            "source": source,
            "source_frontier": source_frontier,
            "status": initial_status,
            "review_count": 0,
            "max_reviews": int(updated.get("review_trigger", {}).get("max_reviews", 3)),
            "retire_category": None,
            "lifecycle": lifecycle,
            "review_decisions": [],
            "evidence_pointers": [],
        }
    )

    violations = enforce_portfolio_limits(updated)
    if violations:
        raise InvalidTransition("; ".join(violations))

    return updated


def get_frontier(registry: dict[str, Any], frontier_id: str) -> dict[str, Any]:
    """Return a frontier by stable ID."""
    if FRONTIER_ID_RE.fullmatch(frontier_id) is None:
        raise BindingError(f"malformed frontier id: {frontier_id}")

    for frontier in registry.get("frontiers", []):
        if frontier.get("id") == frontier_id:
            return frontier
    raise BindingError(f"unknown frontier id: {frontier_id}")


def derive_loop_counts(ledger_md: str, registry: dict[str, Any]) -> dict[str, int]:
    """Parse exact loop headers and count appearances by stable frontier ID."""
    known_ids = {frontier.get("id") for frontier in registry.get("frontiers", [])}
    counts: dict[str, int] = {}
    saw_loop_header = False

    for raw_line in ledger_md.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("## Loop "):
            continue

        saw_loop_header = True
        match = LOOP_HEADER_RE.fullmatch(line)
        if match is None:
            raise BindingError(f"malformed loop header: {line}")

        frontier_id = match.group("frontier_id")
        if frontier_id not in known_ids:
            raise BindingError(f"unknown frontier id in loop header: {frontier_id}")

        counts[frontier_id] = counts.get(frontier_id, 0) + 1

    if not saw_loop_header:
        raise BindingError("missing loop frontier binding headers")

    return counts


def check_review_due(registry: dict[str, Any], loop_counts: dict[str, int]) -> list[str]:
    """Return frontier IDs whose loop count has crossed a new review boundary."""
    every_loops = _review_every_loops(registry)
    due = []
    for frontier in registry.get("frontiers", []):
        if frontier.get("status") != "Active":
            continue

        frontier_id = frontier.get("id")
        count = int(loop_counts.get(frontier_id, 0))
        review_count = int(frontier.get("review_count", 0))
        max_reviews = int(frontier.get("max_reviews", 0))

        if _has_unrecorded_review_boundary(
            loop_count=count,
            every_loops=every_loops,
            review_count=review_count,
            max_reviews=max_reviews,
        ):
            due.append(frontier_id)

    return due


def transition(
    registry: dict[str, Any],
    frontier_id: str,
    to_status: str,
    loop_counts: dict[str, int],
    *,
    mode: str,
    action: str,
    rationale: str | None = None,
    retire_category: str | None = None,
    at_loop: int | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Return a registry copy with one validated frontier transition applied."""
    if to_status not in STATUSES:
        raise InvalidTransition(f"unsupported frontier status: {to_status}")

    resolved_mode = _resolve_registry_mode(registry, mode, InvalidTransition)
    updated = copy.deepcopy(registry)
    frontier = get_frontier(updated, frontier_id)
    from_status = frontier.get("status")

    _validate_transition_request(
        registry=updated,
        frontier=frontier,
        frontier_id=frontier_id,
        from_status=from_status,
        to_status=to_status,
        loop_count=int(loop_counts.get(frontier_id, 0)),
        mode=resolved_mode,
        action=action,
        retire_category=retire_category,
    )

    if action == "review":
        _validate_review_due(
            registry=updated,
            frontier=frontier,
            frontier_id=frontier_id,
            loop_count=int(loop_counts.get(frontier_id, 0)),
        )
        _record_review_decision(frontier, to_status, retire_category, rationale, at_loop)

    frontier["status"] = to_status
    frontier["retire_category"] = retire_category if to_status == "Retired" else None
    lifecycle_entry = {"to": to_status, "at_loop": at_loop, "ts": ts}
    if rationale:
        lifecycle_entry["rationale"] = rationale
    if to_status == "Retired" and retire_category:
        lifecycle_entry["retire_category"] = retire_category
    frontier.setdefault("lifecycle", []).append(lifecycle_entry)

    violations = enforce_portfolio_limits(updated)
    if violations:
        raise InvalidTransition("; ".join(violations))

    return updated


def validate_for_stage_transition(
    registry: dict[str, Any],
    loop_counts: dict[str, int],
    mode: str,
    target_stage: str,
) -> tuple[bool, list[str]]:
    """Validate whether the registry is ready to enter a target workflow stage."""
    if target_stage not in KNOWN_STAGES:
        return False, [f"unsupported target_stage: {target_stage}"]

    if target_stage != "stage_3":
        return True, []

    try:
        resolved_mode = _resolve_registry_mode(registry, mode, LifecycleError)
    except LifecycleError as exc:
        return False, [str(exc)]

    missing: list[str] = []
    has_continued = False

    for frontier in registry.get("frontiers", []):
        frontier_id = frontier.get("id")
        status = frontier.get("status")

        if status == "Continued":
            has_continued = True
            loop_count = int(loop_counts.get(frontier_id, 0))
            if loop_count < 3:
                missing.append(
                    f"frontier {frontier_id} is Continued with only {loop_count} loop(s); "
                    "minimum 3 required before stage_3"
                )
        elif status == "Active":
            missing.append(f"frontier {frontier_id} is Active; resolve it before stage_3")
        elif status == "New":
            missing.append(f"frontier {frontier_id} is New; start and resolve it or retire it before stage_3")
        elif status == "Retired":
            reason = _retire_validation_error(
                mode=resolved_mode,
                loop_count=int(loop_counts.get(frontier_id, 0)),
                retire_category=frontier.get("retire_category"),
            )
            if reason is not None:
                missing.append(f"frontier {frontier_id} retirement is invalid for stage_3: {reason}")
        else:
            missing.append(f"frontier {frontier_id} has unsupported status {status!r}")

    if not has_continued:
        missing.append("at least one Continued frontier is required before stage_3")

    return not missing, missing


def enforce_portfolio_limits(registry: dict[str, Any]) -> list[str]:
    """Check portfolio caps, counting only Active and New frontiers."""
    limits = registry.get("portfolio_limits", {})
    frontiers = registry.get("frontiers", [])
    active_count = sum(1 for frontier in frontiers if frontier.get("status") == "Active")
    active_new_count = sum(1 for frontier in frontiers if frontier.get("status") in {"Active", "New"})

    violations = []
    max_active = limits.get("max_active")
    max_active_plus_new = limits.get("max_active_plus_new")

    if max_active is not None and active_count > int(max_active):
        violations.append(f"Active frontier count {active_count} exceeds max_active={max_active}")
    if max_active_plus_new is not None and active_new_count > int(max_active_plus_new):
        violations.append(
            f"Active+New frontier count {active_new_count} exceeds max_active_plus_new={max_active_plus_new}"
        )

    return violations


def render_review_log_md(registry: dict[str, Any]) -> str:
    """Render review decisions in registry order with stable field ordering."""
    lines = ["# Frontier Review Log", ""]
    wrote_decision = False

    for frontier in registry.get("frontiers", []):
        frontier_id = frontier.get("id")
        max_reviews = frontier.get("max_reviews", 0)
        for decision in frontier.get("review_decisions", []):
            wrote_decision = True
            review_number = decision.get("review_number")
            at_loop = decision.get("at_loop")
            lines.extend(
                [
                    f"## Frontier Review: {frontier_id} @ loop {at_loop} (review {review_number}/{max_reviews})",
                    f"**Decision**: {decision.get('decision')}",
                ]
            )

            rationale = decision.get("rationale_short")
            if rationale:
                lines.append(f"**Rationale**: {rationale}")

            retire_category = decision.get("retire_category")
            if retire_category:
                lines.append(f"**Retire category**: {retire_category}")

            actions = decision.get("portfolio_actions", [])
            if actions:
                lines.append("")
                lines.append("### Portfolio Actions")
                for action in actions:
                    lines.append(f"- {_render_portfolio_action(action)}")

            lines.append("")

    if not wrote_decision:
        lines.append("_No frontier reviews recorded._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_discovery_log_md(registry: dict[str, Any]) -> str:
    """Render discovery portfolio actions from review decisions."""
    lines = ["# Frontier Discovery Log", ""]
    wrote_action = False

    for frontier in registry.get("frontiers", []):
        frontier_id = frontier.get("id")
        for decision in frontier.get("review_decisions", []):
            actions = decision.get("portfolio_actions", [])
            if not actions:
                continue

            wrote_action = True
            at_loop = decision.get("at_loop")
            review_number = decision.get("review_number")
            lines.append(f"## {frontier_id} @ loop {at_loop} (review {review_number})")
            for action in actions:
                lines.append(f"- {_render_portfolio_action(action)}")
            lines.append("")

    if not wrote_action:
        lines.append("_No discovery actions recorded._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _next_frontier_id(registry: dict[str, Any]) -> str:
    max_seen = 0
    for frontier in registry.get("frontiers", []):
        frontier_id = frontier.get("id")
        match = FRONTIER_ID_RE.fullmatch(str(frontier_id))
        if match is None:
            raise BindingError(f"malformed frontier id: {frontier_id}")
        max_seen = max(max_seen, int(match.group("number")))
    return f"F{max_seen + 1}"


def _review_every_loops(registry: dict[str, Any]) -> int:
    every_loops = registry.get("review_trigger", {}).get("every_loops", 3)
    if isinstance(every_loops, bool) or not isinstance(every_loops, int) or every_loops <= 0:
        raise LifecycleError(f"review_trigger.every_loops must be a positive integer, got {every_loops!r}")
    return every_loops


def _resolve_registry_mode(
    registry: dict[str, Any],
    requested_mode: str,
    error_type: type[LifecycleError],
) -> str:
    registry_mode = registry.get("mode")
    if registry_mode not in SUPPORTED_MODES:
        raise error_type(f"unsupported registry mode: {registry_mode}")
    if requested_mode not in SUPPORTED_MODES:
        raise error_type(f"unsupported requested mode: {requested_mode}")
    if registry_mode != requested_mode:
        raise error_type(f"mode mismatch: registry mode {registry_mode} does not match requested mode {requested_mode}")
    return registry_mode


def _validate_review_due(
    *,
    registry: dict[str, Any],
    frontier: dict[str, Any],
    frontier_id: str,
    loop_count: int,
) -> None:
    if frontier.get("status") != "Active":
        raise InvalidTransition(f"frontier {frontier_id} is not Active and cannot be reviewed")

    try:
        every_loops = _review_every_loops(registry)
    except LifecycleError as exc:
        raise InvalidTransition(str(exc)) from exc

    review_count = int(frontier.get("review_count", 0))
    max_reviews = int(frontier.get("max_reviews", 0))
    if not _has_unrecorded_review_boundary(
        loop_count=loop_count,
        every_loops=every_loops,
        review_count=review_count,
        max_reviews=max_reviews,
    ):
        raise InvalidTransition(f"frontier {frontier_id} is not review-due at loop count {loop_count}")


def _validate_transition_request(
    *,
    registry: dict[str, Any],
    frontier: dict[str, Any],
    frontier_id: str,
    from_status: str,
    to_status: str,
    loop_count: int,
    mode: str,
    action: str,
    retire_category: str | None,
) -> None:
    if from_status not in STATUSES:
        raise InvalidTransition(f"frontier {frontier_id} has unsupported status: {from_status}")
    if from_status == "Retired":
        raise InvalidTransition(f"frontier {frontier_id} is already Retired")

    if to_status == "Active":
        if from_status == "Continued":
            if action != "reactivate":
                raise InvalidTransition("Continued frontiers require action='reactivate' to become Active")
            if int(frontier.get("review_count", 0)) >= int(frontier.get("max_reviews", 0)):
                raise InvalidTransition("cannot reactivate a frontier at max_reviews")
            return
        if from_status == "New" and action in {"start", "activate"}:
            return
        if from_status == "Active" and action == "noop":
            return
        raise InvalidTransition(f"invalid {from_status} -> Active transition via action={action!r}")

    if to_status == "Continued":
        if action != "review":
            raise InvalidTransition("Continued can only be recorded by a review decision")
        if from_status not in {"Active", "Continued"}:
            raise InvalidTransition(f"invalid {from_status} -> Continued transition")
        if int(frontier.get("review_count", 0)) >= int(frontier.get("max_reviews", 0)):
            raise InvalidTransition("cannot continue a frontier at max_reviews")
        return

    if to_status == "Retired":
        if action not in {"retire", "review"}:
            raise InvalidTransition("Retired requires action='retire' or action='review'")
        if action == "review":
            reason = _review_retire_validation_error(retire_category)
        else:
            every_loops = _review_every_loops(registry)
            if from_status == "Active" and _has_unrecorded_review_boundary(
                loop_count=loop_count,
                every_loops=every_loops,
                review_count=int(frontier.get("review_count", 0)),
                max_reviews=int(frontier.get("max_reviews", 0)),
            ):
                raise InvalidTransition(
                    f"frontier {frontier_id} has a review due; use record --decision Retired"
                )
            reason = _retire_validation_error(mode=mode, loop_count=loop_count, retire_category=retire_category)
        if reason is not None:
            raise InvalidTransition(reason)
        return

    if to_status == "New":
        raise InvalidTransition("frontiers cannot transition back to New")


def _record_review_decision(
    frontier: dict[str, Any],
    decision: str,
    retire_category: str | None,
    rationale: str | None,
    at_loop: int | None,
) -> None:
    next_review = int(frontier.get("review_count", 0)) + 1
    max_reviews = int(frontier.get("max_reviews", 0))
    if next_review > max_reviews:
        raise InvalidTransition("review_count cannot exceed max_reviews")

    frontier["review_count"] = next_review
    frontier.setdefault("review_decisions", []).append(
        {
            "review_number": next_review,
            "at_loop": at_loop,
            "decision": decision,
            "retire_category": retire_category if decision == "Retired" else None,
            "rationale_short": rationale,
            "portfolio_actions": [],
        }
    )


def _retire_validation_error(mode: str, loop_count: int, retire_category: str | None) -> str | None:
    if not retire_category:
        return "retire_category is required"

    if retire_category not in VALID_RETIRE_CATEGORIES:
        return f"unsupported retire_category: {retire_category}"

    early_categories = EARLY_RETIRE_CATEGORIES_BY_MODE.get(mode, frozenset())
    if loop_count < 3 and retire_category not in early_categories:
        allowed = ", ".join(sorted(early_categories))
        return f"{mode} early retire before three loops only allows: {allowed}"

    return None


def _review_retire_validation_error(retire_category: str | None) -> str | None:
    if not retire_category:
        return "retire_category is required"

    if retire_category not in REVIEW_RETIRE_CATEGORIES:
        allowed = ", ".join(sorted(REVIEW_RETIRE_CATEGORIES))
        return f"review retire only allows: {allowed}"

    return None


def _has_unrecorded_review_boundary(
    *,
    loop_count: int,
    every_loops: int,
    review_count: int,
    max_reviews: int,
) -> bool:
    return (
        loop_count > 0
        and loop_count // every_loops > review_count
        and review_count < max_reviews
    )


def _render_portfolio_action(action: dict[str, Any]) -> str:
    action_type = action.get("action")
    reason = action.get("reason")

    if action_type == "add":
        frontier = action.get("frontier")
        source_frontier = action.get("source_frontier")
        source = action.get("source")
        text = f"Added {frontier}"
        details = []
        if source:
            details.append(f"source={source}")
        if source_frontier:
            details.append(f"source_frontier={source_frontier}")
        if details:
            text = f"{text} ({', '.join(details)})"
        if reason:
            text = f"{text}: {reason}"
        return text

    if action_type == "reject":
        candidate = action.get("candidate")
        text = f"Rejected {candidate}"
        if reason:
            text = f"{text}: {reason}"
        return text

    if action_type == "retire":
        frontier = action.get("frontier")
        category = action.get("category")
        text = f"Retired {frontier}"
        if category:
            text = f"{text} (category={category})"
        if reason:
            text = f"{text}: {reason}"
        return text

    if action_type == "reprioritize":
        frontier = action.get("frontier")
        priority = action.get("priority")
        text = f"Reprioritized {frontier}"
        if priority:
            text = f"{text} to {priority}"
        if reason:
            text = f"{text}: {reason}"
        return text

    text = str(action_type)
    if reason:
        text = f"{text}: {reason}"
    return text
