"""Deterministic frontier lifecycle helpers for SOFA workflows."""

from __future__ import annotations

import copy
import html
import re
import unicodedata
from typing import Any


STATUSES = ("New", "Active", "Continued", "Retired")
SUPPORTED_MODES = ("sector", "ticker")
FRONTIER_SOURCES = ("initial", "discovery", "serendipity")
CURRENT_REGISTRY_VERSION = 3
LEGACY_REGISTRY_VERSION = 2
LAYER_COUNT = 6
PERSISTED_FRONTIER_SOURCES = frozenset((*FRONTIER_SOURCES, "user"))
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
FRONTIER_LAYER_SEMANTIC_LIMIT = (
    "Presence/status snapshot only. This does not establish research "
    "completeness, evidence adequacy, or action-class readiness."
)


class LifecycleError(ValueError):
    """Base error for deterministic lifecycle contract violations."""


class BindingError(LifecycleError):
    """Raised when a ledger loop cannot be bound to a known frontier ID."""


class InvalidTransition(LifecycleError):
    """Raised when a requested lifecycle transition violates lifecycle rules."""


def make_registry(subject: str, mode: str) -> dict[str, Any]:
    """Create an empty frontier registry using registry schema v3."""
    if mode not in SUPPORTED_MODES:
        raise LifecycleError(f"unsupported mode: {mode}")

    return {
        "version": CURRENT_REGISTRY_VERSION,
        "subject": subject,
        "mode": mode,
        "layer_labels": [],
        "frontiers": [],
        "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
        "review_trigger": {"every_loops": 3, "max_reviews": 3},
    }


def validate_registry(registry: Any) -> dict[str, Any]:
    """Validate without mutation or normalization; return the same object."""
    if not isinstance(registry, dict):
        raise LifecycleError("registry must be an object")

    version = _require_strict_int(registry.get("version"), "version")
    if version == LEGACY_REGISTRY_VERSION:
        _validate_v2_boundary(registry)
    elif version == CURRENT_REGISTRY_VERSION:
        _validate_v3_registry(registry)
    else:
        raise LifecycleError(f"unsupported registry version: {version}")

    return registry


def set_layer_labels(
    registry: dict[str, Any],
    indexed_labels: list[tuple[int, str]],
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Return a validated copy with canonical Layer 0-5 labels."""
    validate_registry(registry)
    canonical_labels = _canonical_layer_labels(indexed_labels)

    if registry["version"] == CURRENT_REGISTRY_VERSION:
        existing_labels = registry["layer_labels"]
        if existing_labels and existing_labels != canonical_labels and not replace:
            raise LifecycleError("layer labels are already configured; use replace=True to change them")

        updated = copy.deepcopy(registry)
        updated["layer_labels"] = canonical_labels
        return validate_registry(updated)

    _validate_v2_for_adoption(registry)
    updated = copy.deepcopy(registry)
    updated["version"] = CURRENT_REGISTRY_VERSION
    updated["layer_labels"] = canonical_labels
    for frontier in updated["frontiers"]:
        frontier["layer"] = None
        frontier["parent_frontier"] = None

    return validate_registry(updated)


def bind_frontier_layer(
    registry: dict[str, Any],
    frontier_id: str,
    *,
    layer: int | None,
    parent_frontier: str | None = None,
) -> dict[str, Any]:
    """Return a validated copy with one complete frontier binding replaced."""
    validate_registry(registry)
    if registry["version"] != CURRENT_REGISTRY_VERSION or not registry["layer_labels"]:
        raise LifecycleError("frontier layer labels are unavailable; run set-layers")
    if parent_frontier is not None and layer is None:
        raise LifecycleError("parent_frontier requires layer")
    if layer is not None:
        _require_strict_int(
            layer,
            f"frontier {frontier_id}.layer",
            minimum=0,
            maximum=LAYER_COUNT - 1,
        )

    updated = copy.deepcopy(registry)
    frontier = get_frontier(updated, frontier_id)
    frontier["layer"] = layer
    frontier["parent_frontier"] = parent_frontier if layer is not None else None
    return validate_registry(updated)


def derive_frontier_layer_coverage(registry: dict[str, Any]) -> dict[str, Any]:
    """Derive validated layer presence and lifecycle-status facts."""
    validate_registry(registry)
    registry_version = registry["version"]
    if registry_version == LEGACY_REGISTRY_VERSION:
        return {
            "registry_version": LEGACY_REGISTRY_VERSION,
            "labels_configured": False,
            "layers": [],
            "lineage": [],
            "unbound_frontier_ids": [],
            "advisories": [
                {
                    "code": "LAYER_LABELS_UNCONFIGURED",
                    "layer_indexes": [],
                    "frontier_ids": [],
                }
            ],
        }

    frontiers = sorted(registry["frontiers"], key=lambda row: _frontier_numeric_key(row["id"]))
    lineage = [
        {
            "frontier_id": frontier["id"],
            "layer": frontier["layer"],
            "parent_frontier": frontier["parent_frontier"],
            "source_frontier": frontier.get("source_frontier"),
            "status": frontier["status"],
            "retire_category": frontier.get("retire_category"),
        }
        for frontier in frontiers
    ]
    unbound_frontier_ids = [
        frontier["id"] for frontier in frontiers if frontier["layer"] is None
    ]
    labels_configured = bool(registry["layer_labels"])
    layers = []
    if labels_configured:
        for index, label in enumerate(registry["layer_labels"]):
            layer_frontiers = [frontier for frontier in frontiers if frontier["layer"] == index]
            layers.append(
                {
                    "index": index,
                    "label": label,
                    "frontier_ids": [frontier["id"] for frontier in layer_frontiers],
                    "status_counts": {
                        status: sum(frontier["status"] == status for frontier in layer_frontiers)
                        for status in STATUSES
                    },
                    "frontiers": [
                        {
                            "frontier_id": frontier["id"],
                            "status": frontier["status"],
                            "retire_category": frontier.get("retire_category"),
                        }
                        for frontier in layer_frontiers
                    ],
                }
            )

    advisories = []
    if not labels_configured:
        advisories.append(
            {
                "code": "LAYER_LABELS_UNCONFIGURED",
                "layer_indexes": [],
                "frontier_ids": [],
            }
        )
    else:
        for layer_row in layers:
            layer_frontiers = layer_row["frontiers"]
            if not layer_frontiers:
                code = "LAYER_UNREPRESENTED"
            elif all(frontier["status"] == "Retired" for frontier in layer_frontiers):
                if all(
                    frontier["retire_category"] == "blocked"
                    for frontier in layer_frontiers
                ):
                    code = "LAYER_BLOCKED_ONLY"
                else:
                    code = "LAYER_RETIRED_ONLY"
            else:
                continue
            advisories.append(
                {
                    "code": code,
                    "layer_indexes": [layer_row["index"]],
                    "frontier_ids": list(layer_row["frontier_ids"]),
                }
            )
    if unbound_frontier_ids:
        advisories.append(
            {
                "code": "FRONTIER_LAYER_UNBOUND",
                "layer_indexes": [],
                "frontier_ids": list(unbound_frontier_ids),
            }
        )

    return {
        "registry_version": CURRENT_REGISTRY_VERSION,
        "labels_configured": labels_configured,
        "layers": layers,
        "lineage": lineage,
        "unbound_frontier_ids": unbound_frontier_ids,
        "advisories": advisories,
    }


def format_frontier_layer_advisories(
    coverage: dict[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    """Format structured layer advisories without managed-Markdown encoding."""
    return _format_frontier_layer_advisories(
        coverage,
        prefix=prefix,
        marker_safe_markdown=False,
    )


def _format_frontier_layer_advisories(
    coverage: dict[str, Any],
    *,
    prefix: str,
    marker_safe_markdown: bool,
) -> list[str]:
    """Format layer advisories in deterministic scan order for one output view."""
    layer_by_index = {layer["index"]: layer for layer in coverage["layers"]}
    lines: list[str] = []
    unrepresented_indexes: list[int] = []

    def flush_unrepresented() -> None:
        if not unrepresented_indexes:
            return
        lines.append(
            prefix
            + "LAYER_UNREPRESENTED: Layers "
            + _compress_layer_indexes(unrepresented_indexes)
            + " have no bound frontier."
        )
        unrepresented_indexes.clear()

    for advisory in coverage["advisories"]:
        code = advisory["code"]
        if code == "LAYER_UNREPRESENTED":
            for index in advisory["layer_indexes"]:
                if unrepresented_indexes and index != unrepresented_indexes[-1] + 1:
                    flush_unrepresented()
                unrepresented_indexes.append(index)
            continue

        flush_unrepresented()
        frontier_ids = sorted(advisory["frontier_ids"], key=_frontier_numeric_key)
        if code == "LAYER_LABELS_UNCONFIGURED":
            message = (
                "LAYER_LABELS_UNCONFIGURED: Frontier layer labels are unavailable; "
                "run set-layers."
            )
        elif code == "LAYER_BLOCKED_ONLY":
            index = advisory["layer_indexes"][0]
            label = layer_by_index[index]["label"]
            if marker_safe_markdown:
                label = _escape_managed_markdown_text(label)
            message = (
                f"LAYER_BLOCKED_ONLY: Layer {index} ({label}) has only blocked retired "
                f"frontiers: {', '.join(frontier_ids)}."
            )
        elif code == "LAYER_RETIRED_ONLY":
            index = advisory["layer_indexes"][0]
            layer = layer_by_index[index]
            label = layer["label"]
            if marker_safe_markdown:
                label = _escape_managed_markdown_text(label)
            frontier_by_id = {
                frontier["frontier_id"]: frontier for frontier in layer["frontiers"]
            }
            facts = [
                f"{frontier_id}={frontier_by_id[frontier_id]['status']}"
                f"({frontier_by_id[frontier_id]['retire_category']})"
                for frontier_id in frontier_ids
            ]
            message = (
                f"LAYER_RETIRED_ONLY: Layer {index} ({label}) has only retired "
                f"frontiers: {', '.join(facts)}."
            )
        elif code == "FRONTIER_LAYER_UNBOUND":
            message = (
                f"FRONTIER_LAYER_UNBOUND: Frontiers {', '.join(frontier_ids)} are not "
                "bound to a layer."
            )
        else:
            raise LifecycleError(f"unsupported frontier layer advisory code: {code}")
        lines.append(prefix + message)

    flush_unrepresented()
    return lines


def render_frontier_layer_coverage_md(registry: dict[str, Any]) -> str:
    """Render only the deterministic managed-block interior for layer coverage."""
    coverage = derive_frontier_layer_coverage(registry)
    lines = [f"> {FRONTIER_LAYER_SEMANTIC_LIMIT}", ""]

    if coverage["labels_configured"]:
        lines.extend(
            [
                "| Layer | Label | New | Active | Continued | Retired | Frontier facts |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for layer in coverage["layers"]:
            frontier_facts = []
            for frontier in sorted(
                layer["frontiers"],
                key=lambda row: _frontier_numeric_key(row["frontier_id"]),
            ):
                fact = f"{frontier['frontier_id']}={frontier['status']}"
                if frontier["status"] == "Retired":
                    fact += f"({frontier['retire_category']})"
                frontier_facts.append(fact)
            values = [
                layer["index"],
                layer["label"],
                layer["status_counts"]["New"],
                layer["status_counts"]["Active"],
                layer["status_counts"]["Continued"],
                layer["status_counts"]["Retired"],
                ", ".join(frontier_facts) if frontier_facts else None,
            ]
            lines.append(
                "| "
                + " | ".join(
                    _escape_markdown_cell(value)
                    for value in values
                )
                + " |"
            )

        lines.extend(
            [
                "",
                "### Structural Lineage",
                "",
                "| Frontier | Layer | Structural parent | Discovery source | Status | Retire category |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        lineage = sorted(
            coverage["lineage"],
            key=lambda row: _frontier_numeric_key(row["frontier_id"]),
        )
        for frontier in lineage:
            values = [
                frontier["frontier_id"],
                frontier["layer"],
                frontier["parent_frontier"],
                frontier["source_frontier"],
                frontier["status"],
                frontier["retire_category"],
            ]
            lines.append(
                "| "
                + " | ".join(
                    _escape_markdown_cell(value)
                    for value in values
                )
                + " |"
            )
        if not lineage:
            lines.append("_No frontiers are registered._")
        lines.append("")

    lines.extend(["### Advisory Gaps", ""])
    advisory_lines = _format_frontier_layer_advisories(
        coverage,
        prefix="- ",
        marker_safe_markdown=True,
    )
    lines.extend(advisory_lines or ["- None at this snapshot."])
    return "\n".join(lines) + "\n"


def _escape_managed_markdown_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _escape_markdown_cell(value: Any) -> str:
    if value is None:
        return "none"
    text = _escape_managed_markdown_text(value)
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _compress_layer_indexes(indexes: list[int]) -> str:
    if not indexes:
        return ""

    parts: list[str] = []
    start = previous = indexes[0]
    for index in indexes[1:]:
        if index == previous + 1:
            previous = index
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = index
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(parts)


def _canonical_layer_labels(indexed_labels: list[tuple[int, str]]) -> list[str]:
    if not isinstance(indexed_labels, list) or len(indexed_labels) != LAYER_COUNT:
        raise LifecycleError(f"indexed_labels must contain exactly {LAYER_COUNT} entries")

    labels_by_index: dict[int, str] = {}
    for position, entry in enumerate(indexed_labels):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise LifecycleError(f"indexed_labels entry {position} must be an index-label pair")
        index, label = entry
        _require_strict_int(
            index,
            f"indexed_labels entry {position} index",
            minimum=0,
            maximum=LAYER_COUNT - 1,
        )
        if index in labels_by_index:
            raise LifecycleError(f"duplicate layer index: {index}")
        if not isinstance(label, str):
            raise LifecycleError(f"layer label {index} must be a string")
        _validate_layer_label_characters(label, index)
        labels_by_index[index] = label.strip()

    canonical_labels = [labels_by_index[index] for index in range(LAYER_COUNT)]
    _validate_persisted_layer_labels(canonical_labels)
    return canonical_labels


def _validate_v2_for_adoption(registry: dict[str, Any]) -> None:
    candidate = copy.deepcopy(registry)
    candidate["version"] = CURRENT_REGISTRY_VERSION
    candidate["layer_labels"] = []
    frontiers = candidate.get("frontiers")
    if isinstance(frontiers, list):
        for frontier in frontiers:
            if isinstance(frontier, dict):
                frontier["layer"] = None
                frontier["parent_frontier"] = None
    validate_registry(candidate)


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_strict_int(
    value: Any,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if not _is_strict_int(value):
        raise LifecycleError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise LifecycleError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise LifecycleError(f"{field} must be at most {maximum}")
    return value


def _validate_v2_boundary(registry: dict[str, Any]) -> None:
    if "layer_labels" in registry:
        raise LifecycleError("registry v2 cannot contain layer_labels")

    frontiers = registry.get("frontiers")
    if not isinstance(frontiers, list):
        return
    for index, frontier in enumerate(frontiers):
        if not isinstance(frontier, dict):
            continue
        if "layer" in frontier or "parent_frontier" in frontier:
            raise LifecycleError(f"registry v2 frontier {index} cannot contain v3 layer fields")


def _validate_v3_registry(registry: dict[str, Any]) -> None:
    if not isinstance(registry.get("subject"), str):
        raise LifecycleError("subject must be a string")
    if registry.get("mode") not in SUPPORTED_MODES:
        raise LifecycleError(f"unsupported registry mode: {registry.get('mode')}")

    layer_labels = registry.get("layer_labels")
    if not isinstance(layer_labels, list):
        raise LifecycleError("layer_labels must be a list")
    _validate_persisted_layer_labels(layer_labels)

    if "portfolio_limits" in registry:
        limits = registry["portfolio_limits"]
        if not isinstance(limits, dict):
            raise LifecycleError("portfolio_limits must be an object")
        for field in ("max_active", "max_active_plus_new"):
            if field in limits:
                _require_strict_int(limits[field], f"portfolio_limits.{field}", minimum=0)

    if "review_trigger" in registry:
        trigger = registry["review_trigger"]
        if not isinstance(trigger, dict):
            raise LifecycleError("review_trigger must be an object")
        if "every_loops" in trigger:
            _require_strict_int(trigger["every_loops"], "review_trigger.every_loops", minimum=1)
        if "max_reviews" in trigger:
            _require_strict_int(trigger["max_reviews"], "review_trigger.max_reviews", minimum=0)

    frontiers = registry.get("frontiers")
    if not isinstance(frontiers, list):
        raise LifecycleError("frontiers must be a list")

    frontier_by_id: dict[str, dict[str, Any]] = {}
    for index, frontier in enumerate(frontiers):
        if not isinstance(frontier, dict):
            raise LifecycleError(f"frontier {index} must be an object")

        frontier_id = frontier.get("id")
        if not isinstance(frontier_id, str) or FRONTIER_ID_RE.fullmatch(frontier_id) is None:
            raise LifecycleError(f"frontier {index}.id must be a stable frontier ID")
        if frontier_id in frontier_by_id:
            raise LifecycleError(f"duplicate frontier id: {frontier_id}")
        frontier_by_id[frontier_id] = frontier

        if not isinstance(frontier.get("name"), str):
            raise LifecycleError(f"frontier {frontier_id}.name must be a string")

        _require_strict_int(
            frontier.get("proposed_at_loop"),
            f"frontier {frontier_id}.proposed_at_loop",
            minimum=1,
        )

        source = frontier.get("source")
        if not isinstance(source, str) or source not in PERSISTED_FRONTIER_SOURCES:
            raise LifecycleError(f"frontier {frontier_id} has unsupported source: {source}")
        _validate_optional_frontier_id(
            frontier.get("source_frontier"),
            f"frontier {frontier_id}.source_frontier",
        )

        status = frontier.get("status")
        if status not in STATUSES:
            raise LifecycleError(f"frontier {frontier_id} has unsupported status: {status}")
        for field in ("review_count", "max_reviews"):
            if field in frontier:
                _require_strict_int(frontier[field], f"frontier {frontier_id}.{field}", minimum=0)
        _validate_status_category(frontier, frontier_id)

        for field in ("lifecycle", "review_decisions", "evidence_pointers"):
            if field in frontier and not isinstance(frontier[field], list):
                raise LifecycleError(f"frontier {frontier_id}.{field} must be a list")

        if "layer" not in frontier:
            raise LifecycleError(f"frontier {frontier_id}.layer is required")
        layer = frontier["layer"]
        if layer is not None:
            _require_strict_int(layer, f"frontier {frontier_id}.layer", minimum=0, maximum=LAYER_COUNT - 1)

        if "parent_frontier" not in frontier:
            raise LifecycleError(f"frontier {frontier_id}.parent_frontier is required")
        parent_frontier = frontier["parent_frontier"]
        _validate_optional_frontier_id(parent_frontier, f"frontier {frontier_id}.parent_frontier")

        if not layer_labels and (layer is not None or parent_frontier is not None):
            raise LifecycleError(
                f"frontier {frontier_id} must remain unbound while layer_labels is empty"
            )

    for frontier_id, frontier in frontier_by_id.items():
        _validate_source_provenance(frontier, frontier_id, frontier_by_id)
        _validate_parent_relationship(frontier, frontier_id, frontier_by_id)


def _validate_persisted_layer_labels(layer_labels: list[Any]) -> None:
    if not layer_labels:
        return
    if len(layer_labels) != LAYER_COUNT:
        raise LifecycleError(f"layer_labels must contain exactly {LAYER_COUNT} labels")

    folded_labels: set[str] = set()
    for index, label in enumerate(layer_labels):
        if not isinstance(label, str):
            raise LifecycleError(f"layer label {index} must be a string")
        if label != label.strip() or not label:
            raise LifecycleError(f"layer label {index} must be non-empty and already trimmed")
        _validate_layer_label_characters(label, index)

        folded = label.casefold()
        if folded in folded_labels:
            raise LifecycleError("layer labels must be unique after case-folding")
        folded_labels.add(folded)


def _validate_layer_label_characters(label: str, index: int) -> None:
    if any(character in label for character in ("\n", "\r", "\u2028", "\u2029")):
        raise LifecycleError(f"layer label {index} must be single-line")
    if any(unicodedata.category(character) == "Cc" for character in label):
        raise LifecycleError(f"layer label {index} cannot contain Unicode control characters")


def _validate_optional_frontier_id(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or FRONTIER_ID_RE.fullmatch(value) is None:
        raise LifecycleError(f"{field} must be null or a stable frontier ID")


def _frontier_numeric_key(frontier_id: str) -> int:
    match = FRONTIER_ID_RE.fullmatch(frontier_id)
    if match is None:
        raise LifecycleError(f"malformed frontier id: {frontier_id}")
    return int(match.group("number"))


def _validate_source_provenance(
    frontier: dict[str, Any],
    frontier_id: str,
    frontier_by_id: dict[str, dict[str, Any]],
) -> None:
    source = frontier["source"]
    source_frontier = frontier.get("source_frontier")
    if source in {"initial", "user"}:
        if source_frontier is not None:
            raise LifecycleError(
                f"frontier {frontier_id} source={source} requires source_frontier=null"
            )
        return
    if source_frontier is None:
        raise LifecycleError(
            f"frontier {frontier_id} source={source} requires source_frontier"
        )
    if source_frontier == frontier_id or source_frontier not in frontier_by_id:
        raise LifecycleError(
            f"frontier {frontier_id} has invalid source_frontier: {source_frontier}"
        )


def _validate_parent_relationship(
    frontier: dict[str, Any],
    frontier_id: str,
    frontier_by_id: dict[str, dict[str, Any]],
) -> None:
    parent_frontier = frontier["parent_frontier"]
    if parent_frontier is None:
        return

    parent = frontier_by_id.get(parent_frontier)
    if parent is None:
        raise LifecycleError(
            f"frontier {frontier_id} has invalid parent_frontier: {parent_frontier}"
        )

    child_layer = frontier["layer"]
    if child_layer is None:
        raise LifecycleError(
            f"frontier {frontier_id} with parent_frontier requires layer"
        )
    parent_layer = parent["layer"]
    if parent_layer is None:
        raise LifecycleError(
            f"frontier {frontier_id} parent {parent_frontier} requires layer"
        )
    if parent_layer >= child_layer:
        raise LifecycleError(
            f"frontier {frontier_id} parent {parent_frontier} must have a shallower layer"
        )


def _validate_status_category(frontier: dict[str, Any], frontier_id: str) -> None:
    status = frontier["status"]
    retire_category = frontier.get("retire_category")
    if status == "Retired":
        if not isinstance(retire_category, str) or retire_category not in VALID_RETIRE_CATEGORIES:
            raise LifecycleError(
                f"frontier {frontier_id} must have a valid retire_category when Retired"
            )
    elif retire_category is not None:
        raise LifecycleError(
            f"frontier {frontier_id} must have retire_category=null unless Retired"
        )


def create_frontier(
    registry: dict[str, Any],
    *,
    name: str,
    proposed_at_loop: int,
    source: str,
    source_frontier: str | None = None,
    layer: int | None = None,
    parent_frontier: str | None = None,
    initial_status: str = "New",
    ts: str | None = None,
) -> dict[str, Any]:
    """Return a registry copy with one new frontier record appended."""
    validate_registry(registry)

    if source not in FRONTIER_SOURCES:
        raise InvalidTransition(f"unsupported frontier source: {source}")
    if initial_status not in {"New", "Active"}:
        raise InvalidTransition("frontiers can only be created as New or Active")
    if int(proposed_at_loop) < 1:
        raise InvalidTransition("proposed_at_loop must be positive")
    if registry["version"] == LEGACY_REGISTRY_VERSION and (
        layer is not None or parent_frontier is not None
    ):
        raise LifecycleError("registry v2 cannot set layer facts; run set-layers")

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

    frontier_record = {
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
    if updated["version"] == CURRENT_REGISTRY_VERSION:
        frontier_record["layer"] = layer
        frontier_record["parent_frontier"] = parent_frontier

    updated.setdefault("frontiers", []).append(frontier_record)
    updated = validate_registry(updated)

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
        frontier_id = _escape_managed_markdown_text(frontier.get("id"))
        max_reviews = _escape_managed_markdown_text(frontier.get("max_reviews", 0))
        for decision in frontier.get("review_decisions", []):
            wrote_decision = True
            review_number = _escape_managed_markdown_text(decision.get("review_number"))
            at_loop = _escape_managed_markdown_text(decision.get("at_loop"))
            decision_text = _escape_managed_markdown_text(decision.get("decision"))
            lines.extend(
                [
                    f"## Frontier Review: {frontier_id} @ loop {at_loop} (review {review_number}/{max_reviews})",
                    f"**Decision**: {decision_text}",
                ]
            )

            rationale = decision.get("rationale_short")
            if rationale:
                lines.append(
                    f"**Rationale**: {_escape_managed_markdown_text(rationale)}"
                )

            retire_category = decision.get("retire_category")
            if retire_category:
                lines.append(
                    "**Retire category**: "
                    + _escape_managed_markdown_text(retire_category)
                )

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
        frontier_id = _escape_managed_markdown_text(frontier.get("id"))
        for decision in frontier.get("review_decisions", []):
            actions = decision.get("portfolio_actions", [])
            if not actions:
                continue

            wrote_action = True
            at_loop = _escape_managed_markdown_text(decision.get("at_loop"))
            review_number = _escape_managed_markdown_text(
                decision.get("review_number")
            )
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
        frontier = _escape_managed_markdown_text(action.get("frontier"))
        source_frontier = action.get("source_frontier")
        source = action.get("source")
        text = f"Added {frontier}"
        details = []
        if source:
            details.append(
                f"source={_escape_managed_markdown_text(source)}"
            )
        if source_frontier:
            details.append(
                "source_frontier="
                + _escape_managed_markdown_text(source_frontier)
            )
        if details:
            text = f"{text} ({', '.join(details)})"
        if reason:
            text = f"{text}: {_escape_managed_markdown_text(reason)}"
        return text

    if action_type == "reject":
        candidate = _escape_managed_markdown_text(action.get("candidate"))
        text = f"Rejected {candidate}"
        if reason:
            text = f"{text}: {_escape_managed_markdown_text(reason)}"
        return text

    if action_type == "retire":
        frontier = _escape_managed_markdown_text(action.get("frontier"))
        category = action.get("category")
        text = f"Retired {frontier}"
        if category:
            text = (
                f"{text} (category={_escape_managed_markdown_text(category)})"
            )
        if reason:
            text = f"{text}: {_escape_managed_markdown_text(reason)}"
        return text

    if action_type == "reprioritize":
        frontier = _escape_managed_markdown_text(action.get("frontier"))
        priority = action.get("priority")
        text = f"Reprioritized {frontier}"
        if priority:
            text = f"{text} to {_escape_managed_markdown_text(priority)}"
        if reason:
            text = f"{text}: {_escape_managed_markdown_text(reason)}"
        return text

    text = _escape_managed_markdown_text(action_type)
    if reason:
        text = f"{text}: {_escape_managed_markdown_text(reason)}"
    return text
